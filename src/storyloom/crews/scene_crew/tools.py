"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

CrewAI Tools：供 Agent 在 kickoff 过程中按需调用（function call）。

当前工具：
- query_active_foreshadows: 查询当前活跃伏笔的详细状态
- wake_character: 惰性唤醒不在场的重要角色（每次场景有调用预算）

惰性调用原则：
- 不在场的重要角色默认不创建 Agent、不消耗 LLM 调用；
- 导演或在场的 ProtagonistAgent 认为剧情需要时，才通过 wake_character
  临时唤醒该角色，拿到它的想法/台词/行动意图后继续叙事；
- 导演模式同步唤醒；游戏模式只登记 pending 记忆条目，由引擎在
  回合间推进（drain_side_stage）后以「侧台回响」送达。
"""

import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from crewai.tools import tool

from storyloom.crews.scene_crew.context import PromptContextAssembler
from storyloom.crews.scene_crew.offscreen import (
    SideStageEvent,
    detect_participants,
    queue_side_stage,
    resolve_side_stage,
    select_participants,
    write_side_stage_memory,
)

_EXPERIENCE_RE = re.compile(
    r"【沉睡(?:期间)?(?:的)?经历】\s*(.*)$", re.S
)
_REPLY_RE = re.compile(r"【此刻(?:的)?回应】\s*(.*)$", re.S)


def split_wake_output(text: str) -> Tuple[str, str]:
    """把唤醒输出拆成「沉睡期间经历」与「此刻回应」。

    模型未按格式输出时，整段内容都视为此刻回应。
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return "", ""

    reply_match = _REPLY_RE.search(cleaned)
    if reply_match:
        reply = reply_match.group(1).strip()
        prefix = cleaned[: reply_match.start()]
        exp_match = _EXPERIENCE_RE.search(prefix)
        experience = exp_match.group(1).strip() if exp_match else ""
        return experience, reply or cleaned

    exp_match = _EXPERIENCE_RE.search(cleaned)
    if exp_match:
        experience = exp_match.group(1).strip()
        remainder = cleaned[exp_match.end():].strip()
        return experience, remainder or cleaned

    return "", cleaned


if TYPE_CHECKING:  # 仅用于类型提示，避免与 crew.py 循环导入
    from storyloom.crews.scene_crew.crew import SceneCrew
    from storyloom.memory.models import CharacterAsset, NovelProject


@tool("query_active_foreshadows")
def query_active_foreshadows(
    project_forshadowings_json: str = "[]",
    only_urgent: bool = True,
    min_dormant: int = 3,
) -> str:
    """
    查询当前活跃伏笔的详细状态。

    Prompt 里已经有伏笔简要状态表（id + desc + status + dormant 计数），
    只有当需要关联角色、预期揭示、即将超时等**详细信息**时才调用本工具。

    输入格式：JSON 字符串，对应 project.foreshadowings 的模型导出
    如果输入为空或不合法，返回从提示词里能看到的简要摘要（占位）。

    Args:
        project_forshadowings_json: NovelProject.foreshadowings 的 model_dump_json 字符串
        only_urgent: True=只返回即将超时的紧急伏笔；False=全部活跃伏笔
        min_dormant: dormant_scenes >= 这个值视为即将超时
    """
    import json as _json

    try:
        foreshadows = _json.loads(project_forshadowings_json)
    except (ValueError, TypeError):
        foreshadows = []

    active = [
        f for f in foreshadows
        if f.get("status") in ("planted", "reinforced", "PLANTED", "REINFORCED")
    ]

    if only_urgent:
        active = [
            f for f in active
            if f.get("scenes_since_last_mention", 0) >= f.get("max_dormant_scenes", 5) - min_dormant + 1
        ]

    if not active:
        return "（当前没有需要关注的活跃伏笔）"

    lines: list[str] = []
    for f in active:
        fid = f.get("foreshadow_id", "?")
        desc = f.get("description", "")
        status = f.get("status", "?")
        dormant = f.get("scenes_since_last_mention", 0)
        max_d = f.get("max_dormant_scenes", 5)
        target = f.get("target_revelation", "")
        chars = ", ".join(f.get("linked_characters", [])) or "（无）"
        urgent = dormant >= max_d - 1
        tag = "🚨 紧急" if urgent else ""
        lines.append(
            f"- [{fid}] {desc}\n"
            f"  状态: {status} | 已沉睡 {dormant}/{max_d} 场景 {tag}\n"
            f"  预期揭示: {target}\n"
            f"  关联角色: {chars}"
        )

    return "\n".join(lines)


@dataclass
class WakeRecord:
    """一次惰性唤醒的完整记录，供叙事与排查使用。"""

    character: str
    reason: str
    source: str
    response: str
    experience: str = ""
    side_stage: Optional[SideStageEvent] = None


@dataclass
class CharacterWakeRegistry:
    """惰性角色唤醒登记表：为一次场景提供 wake_character 工具。

    设计要点：
    - 默认不为不在场角色创建 Agent，只有工具被调用才实例化；
    - 同一角色在本次场景内只真正唤醒一次，重复调用直接返回缓存；
    - 每次场景有唤醒预算（默认 2 次），避免函数调用被滥用导致成本失控；
    - 只允许唤醒 primary / secondary 角色，background 交给群像叙事带过；
    - 唤醒结果统一记录，最后拼进角色日志交给 ProseAgent。
    """

    crew: "SceneCrew"
    project: "NovelProject"
    present_chars: List[str]
    memory: Any = None
    scene_brief: str = ""
    intent: str = ""
    scene_index: int = 0
    max_wakes: int = 2
    max_side_participants: int = 2
    #: 游戏模式：唤醒只登记，回应在后续回合以「侧台回响」送达
    defer_side_stage: bool = False
    #: 统一上下文装配器（可选；有则优先用它取记忆/场景）
    assembler: Optional[PromptContextAssembler] = None
    records: List[WakeRecord] = field(default_factory=list)
    _count: int = field(default=0, init=False)
    _cache: dict = field(default_factory=dict, init=False)
    _event_cache: dict = field(default_factory=dict, init=False)
    _remembered_events: set = field(default_factory=set, init=False)
    _queued: set = field(default_factory=set, init=False)

    @property
    def wake_count(self) -> int:
        return self._count

    def wakeable_characters(self) -> List["CharacterAsset"]:
        """返回允许被唤醒的角色（不在场且非背景）。"""
        present = set(self.present_chars)
        return [
            char
            for char in self.project.characters
            if char.name not in present
            and char.importance_tier != "background"
        ]

    def prompt_block(self) -> str:
        """给持有 wake_character tool 的 Agent 的提示块。"""
        candidates = self.wakeable_characters()
        mode_hint = (
            "游戏模式：唤醒是异步的。调用后本回合只得到「已登记」，"
            "对方的回应与沉睡期间的互动会在后续回合以「侧台回响」送达；"
            "本回合请按「消息已发出、尚未收到回复」处理，"
            "不要让在场角色替对方回答。\n"
            if self.defer_side_stage
            else "导演模式：唤醒是同步的，响应会立刻回到本场角色日志。\n"
        )
        names = ", ".join(
            f"{c.name}（{c.importance_tier}）" for c in candidates
        )
        return self.crew.task_prompt(
            "wake_character_hint",
            candidates=names or "（无，所有重要角色均已在场）",
            max_wakes=self.max_wakes,
            mode_hint=mode_hint,
        )

    def make_tool(self, source: str) -> Any:
        """为指定来源（导演 / 某位在场主角）生成一个绑定本场景的唤醒工具。"""

        @tool("wake_character")
        def wake_character(
            character: str,
            reason: str = "",
            involves: str = "",
        ) -> str:
            """唤醒一名不在场的重要角色，获取他/她此刻的想法、台词或行动意图。

            仅在剧情确实需要该角色通过消息、回忆、远程联络或突然到场参与时调用。
            已在场角色不需要调用；本次场景最多唤醒 2 名角色。
            游戏模式下本工具只登记异步唤醒，回应会在后续回合送达。

            Args:
                character: 角色姓名，必须在作品的 important 角色列表中。
                reason: 为什么需要唤醒他/她，以及希望他/她回应什么。
                involves: 可选。他/她沉睡期间可能互动的其他不在场角色名，
                    逗号分隔。填写后侧台导演会统一裁决互动，并补全所有
                    参与者的私有记忆。
            """
            return self._wake(character, reason, source, involves)

        return wake_character

    def wake(
        self,
        character: str,
        reason: str = "",
        involves: str = "",
        source: str = "async",
    ) -> str:
        """同步唤醒入口：供异步侧台在回合间推进时复用。"""
        return self._wake(character, reason, source, involves)

    def _wake(
        self,
        character: str,
        reason: str,
        source: str,
        involves: str = "",
    ) -> str:
        name = (character or "").strip()
        char = self.project.get_character(name)
        if char is None:
            candidates = ", ".join(
                c.name for c in self.wakeable_characters()
            ) or "（无）"
            return (
                f"唤醒失败：作品中没有角色「{name}」。"
                f"可唤醒角色：{candidates}"
            )

        if char.importance_tier == "background":
            return (
                f"「{name}」是背景角色，不单独唤醒；"
                "请在群像行动日志或正文中一笔带过。"
            )

        if name in self.present_chars:
            return (
                f"「{name}」已在场，无需唤醒；"
                "直接让在场 Agent 给出反应即可。"
            )

        if name in self._cache:
            cached_text, cached_event = self._cache[name]
            return self._render(
                name, cached_text, cached=True, event=cached_event
            )

        if name in self._queued:
            return (
                f"「{name}」已登记异步唤醒，回应会在后续回合以"
                "「侧台回响」送达，无需重复登记。"
            )

        if self._count >= self.max_wakes:
            return (
                f"本次场景的唤醒预算已用完（上限 {self.max_wakes} 次）。"
                "请基于已有信息继续推进，不要再唤醒新角色。"
            )

        self._count += 1

        # 游戏模式：异步侧台。不调用任何 Agent，只把请求写成一条
        # pending 记忆条目，回合间再由 drain_side_stage 推进。
        if self.defer_side_stage and self.memory is not None:
            explicit = select_participants(
                self.project,
                self.present_chars,
                name,
                involves,
                limit=self.max_side_participants,
            )
            # 导演意图优先取 assembler（与 _narrate 回写一致）
            deferred_intent = (
                self.assembler.director_intent
                if self.assembler is not None
                else self.intent
            )
            pending_id = queue_side_stage(
                memory=self.memory,
                focus=char,
                participants=[char, *explicit],
                reason=reason,
                scene_brief=self.scene_brief,
                intent=deferred_intent,
                scene_index=self.scene_index,
                source=source,
            )
            if pending_id is not None:
                self._queued.add(name)
                self.records.append(
                    WakeRecord(
                        character=name,
                        reason=reason.strip(),
                        source=source,
                        response=(
                            "已登记异步唤醒，回应将在后续回合送达"
                        ),
                    )
                )
                return self._render_deferred(name, explicit)

        # 调用方显式指定了互动对象：先让侧台导演裁决，再带着
        # 已确认的经历唤醒角色，避免角色先编造再被推翻。
        explicit = select_participants(
            self.project,
            self.present_chars,
            name,
            involves,
            limit=self.max_side_participants,
        )
        side_stage: Optional[SideStageEvent] = None
        canonical_experience = ""
        if explicit:
            side_stage = self._resolve_event(
                char, explicit, reason, ""
            )
            if side_stage is not None:
                canonical_experience = side_stage.perspective_for(name)

        prompt = self._build_prompt(
            char, reason, source, canonical_experience
        )
        try:
            agent = self.crew.build_protagonist(char)
            output = agent.kickoff(prompt)
            text = str(getattr(output, "raw", output) or "").strip()
        except Exception as exc:  # noqa: BLE001 - 单次唤醒失败不阻断场景
            return f"唤醒「{name}」失败：{exc}"

        if not text:
            return f"唤醒「{name}」成功，但对方没有给出有效回应。"

        experience, reply = split_wake_output(text)

        if side_stage is None:
            # 调用方未指定，就从角色自述里检测是否提到了其他沉睡角色
            detected = detect_participants(
                self.project,
                self.present_chars,
                name,
                experience,
                limit=self.max_side_participants,
            )
            if detected:
                side_stage = self._resolve_event(
                    char, detected, reason, experience
                )

        if side_stage is not None:
            # 侧台事实是权威版本：无论角色自述写了什么，都替换为
            # 该角色在事件卡中的视角，避免留下自相矛盾的记忆。
            canonical = side_stage.perspective_for(name)
            experience = canonical or experience or side_stage.facts
            self._remember_side_stage(side_stage)
        else:
            self._remember_experience(char, experience)

        self._cache[name] = (text, side_stage)
        self.records.append(
            WakeRecord(
                character=name,
                reason=reason.strip(),
                source=source,
                response=reply,
                experience=experience,
                side_stage=side_stage,
            )
        )
        return self._render(name, text, event=side_stage)

    def _resolve_event(
        self,
        focus: "CharacterAsset",
        others: List["CharacterAsset"],
        reason: str,
        draft_experience: str,
    ) -> Optional[SideStageEvent]:
        """同一组参与者在本次场景内只裁决一次。"""
        participants = [focus, *others]
        key = tuple(sorted(char.name for char in participants))
        cached = self._event_cache.get(key)
        if cached is not None:
            return cached

        # 导演意图优先取 assembler（与 _narrate 回写一致）
        intent = (
            self.assembler.director_intent
            if self.assembler is not None
            else self.intent
        )
        event = resolve_side_stage(
            crew=self.crew,
            project=self.project,
            participants=participants,
            scene_brief=self.scene_brief,
            reason=reason,
            focus=focus.name,
            intent=intent,
            draft_experience=draft_experience,
            memory=self.memory,
            assembler=self.assembler,
        )
        if event is not None:
            self._event_cache[key] = event
        return event

    def _remember_side_stage(self, event: SideStageEvent) -> None:
        if event.event_id in self._remembered_events:
            return
        self._remembered_events.add(event.event_id)
        write_side_stage_memory(
            memory=self.memory,
            project=self.project,
            event=event,
            scene_index=self.scene_index,
        )

    def _remember_experience(
        self, char: "CharacterAsset", experience: str
    ) -> None:
        """把沉睡期间的经历写入该角色的私有近期记忆，供后续唤醒续接。"""
        if not experience or self.memory is None:
            return
        try:
            self.memory.add_scene(
                scene_index=self.scene_index,
                prose=f"{char.name}（不在场）：{experience}",
                brief=f"{char.name}沉睡期间的经历",
                present_characters=[char.name],
                key=f"offscreen:{char.name}:{uuid.uuid4().hex[:8]}",
            )
        except Exception:  # noqa: BLE001 - 记忆写入失败不阻断唤醒
            pass

    def _render_deferred(
        self,
        name: str,
        others: List["CharacterAsset"],
    ) -> str:
        """异步登记的即时回执：告诉调用方本回合不要替对方回答。"""
        participants = "、".join(char.name for char in others) or "（未指定）"
        return (
            f"【已登记异步唤醒 {name}】\n"
            "游戏模式的侧台是异步的：本次不会让该角色当场回答。\n"
            f"侧台参与：{participants}\n"
            "回应与沉睡期间的互动将在后续回合以「侧台回响」送达，"
            "并同步写入记忆与世界书。\n"
            "本回合请按「消息已发出、尚未收到回复」处理，"
            "不要让在场角色替对方回答。"
        )

    def _render(
        self,
        name: str,
        text: str,
        cached: bool = False,
        event: Optional[SideStageEvent] = None,
    ) -> str:
        suffix = "（本次场景已唤醒过，返回缓存回应）" if cached else ""
        experience, reply = split_wake_output(text)
        parts = [f"【已唤醒 {name}】{suffix}"]
        if experience:
            parts.append(f"【沉睡期间经历】{experience}")
        parts.append(f"【此刻回应】{reply}")
        if event is not None:
            parts.append(f"【侧台事实】{event.facts}")
            for message in event.messages:
                parts.append(
                    f"【侧台消息】{message['from']} → "
                    f"{message['to']}：{message['content']}"
                )
        parts.append("（该回应已记入本场角色日志，会交给叙事者使用）")
        return "\n".join(parts)

    def _build_prompt(
        self,
        char: "CharacterAsset",
        reason: str,
        source: str,
        canonical_experience: str = "",
    ) -> str:
        """为被唤醒角色构造最小上下文：人设 + 记忆 + 场景 + 唤醒原因。"""
        # 优先用统一上下文装配器；没有 assembler 时退回直接读 memory
        if self.assembler is not None:
            memory_block = self.assembler.memory_block(char.name)
            rag = self.assembler.rag_context(
                char.name, reason or self.scene_brief, k=3
            )
        elif self.memory is not None:
            try:
                raw_memory = self.memory.prompt_block(viewer=char.name)
                memory_block = (
                    f"【记忆】\n{raw_memory}" if raw_memory.strip() else ""
                )
                raw_rag = self.memory.retrieval_block(
                    reason or self.scene_brief, k=3, viewer=char.name
                )
                rag = (
                    f"【相关回忆检索】\n{raw_rag}"
                    if raw_rag.strip()
                    else ""
                )
            except Exception:  # noqa: BLE001 - 记忆不可用不阻断唤醒
                memory_block = ""
                rag = ""
        else:
            memory_block = ""
            rag = ""

        present = ", ".join(self.present_chars) or "（无）"
        # 导演意图优先取 assembler（与 _narrate 回写一致），
        # 没有 assembler 时退回 registry 自己的 intent 字段
        intent_text = (
            self.assembler.director_intent
            if self.assembler is not None
            else self.intent
        )
        intent_block = f"\n【导演意图】\n{intent_text}\n" if intent_text else ""
        canonical_block = (
            "\n【侧台已确认的经历（必须以此为准，不得矛盾）】\n"
            f"{canonical_experience}\n"
            if canonical_experience
            else ""
        )
        return self.crew.task_prompt(
            "wake_character",
            name=char.name,
            persona=char.persona,
            motivation=char.motivation,
            scene_brief=self.scene_brief or "（未提供）",
            present=present,
            source=source,
            reason=reason or "导演需要你对当前局势做出反应",
            memory_block=memory_block or "【记忆】\n（无）",
            rag=rag or "【相关回忆检索】\n（无）",
            canonical_block=canonical_block,
            intent_block=intent_block,
        )

    def transcript_block(self) -> str:
        """把唤醒记录拼成一段可注入 actor_log 的文本。"""
        if not self.records:
            return ""
        lines = ["【被唤醒角色的回应】（默认不在场，通过消息/回忆/远程方式参与）"]
        seen_events = set()
        for record in self.records:
            reason = record.reason or "未说明"
            lines.append(
                f"- {record.character}"
                f"（{record.source} 唤醒；原因：{reason}）"
            )
            if record.experience:
                lines.append(f"  沉睡期间经历：{record.experience}")
            lines.append(f"  此刻回应：{record.response}")
            event = record.side_stage
            if event is not None and event.event_id not in seen_events:
                seen_events.add(event.event_id)
                lines.append(
                    "  侧台事实："
                    f"{event.facts}（参与者："
                    f"{', '.join(event.participant_names)}）"
                )
                for message in event.messages:
                    lines.append(
                        f"  侧台消息：{message['from']} → "
                        f"{message['to']}：{message['content']}"
                    )
        return "\n".join(lines)


__all__ = [
    "CharacterWakeRegistry",
    "WakeRecord",
    "query_active_foreshadows",
]
