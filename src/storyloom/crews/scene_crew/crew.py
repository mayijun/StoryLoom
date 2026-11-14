"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

场景生成 Crew（CrewAI 官方约定版）

- Agent 的 role/goal/backstory 持久化在数据库（agent_configs 表），
  由 DbConfig 描述符接入 @CrewBase 的 self.agents_config
- 标准任务序列持久化在数据库（task_configs 表），
  由 self.tasks_config 读取、self.crew() 按 agent_key/context_keys 装配
- Flow 单 Agent 步骤的提示词同样存放在 task_configs（enabled=false），
  由 self.task_prompt() 渲染，避免在代码里重复硬编码
- 同级 config/*.default.yaml 仅作为首次运行的种子数据，数据库是唯一事实来源
- 通过 AgentModelRouter 为每个 Agent 注入最适合的 LLM
  （router 为 None 时使用 CrewAI 默认 LLM）
- protagonist / ensemble / prose 三个 Agent 由 Flow 按资产数据动态生成，
  配置中的 {name}/{persona}/{motivation}/{names}/{brief}/{style}
  占位符会被代码填充（_config）

核心 Agent 角色划分：
- ProtagonistAgent   重要角色，1 角色 = 1 实例
- EnsembleAgent      "群演"，1 实例承载 N 个次要角色，压缩成本
- DirectorAgent      导演，统一负责意外、伏笔、场景意图与一致性自检
- OffscreenDirector   侧台导演，只裁决不在场角色之间的互动
- ProseAgent         润色 / 叙事者
"""

from typing import Any, List, Optional, Tuple

import asyncio

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew

from storyloom.crews.scene_crew.packet import (
    PACKET_CONTRACT,
    AgentPacket,
    packet_to_proposals,
    packet_to_result,
    parse_agent_packet,
)
from storyloom.db import DEFAULT_PROJECT_ID, DbConfig, get_repository
from storyloom.llm.router import AgentModelRouter
from storyloom.memory.models import CharacterAsset
from storyloom.memory.state import (
    ActionProposal,
    AdjudicationResult,
    StateDelta,
    WorldState,
)


@CrewBase
class SceneCrew:
    """场景生成 Crew：Agent / Task 定义来自数据库 + 模型路由注入 LLM"""

    # 覆盖 @CrewBase 的 YAML 加载：实例访问时从数据库读取配置
    agents_config = DbConfig("agents")
    tasks_config = DbConfig("tasks")

    def __init__(
        self,
        router: Optional[AgentModelRouter] = None,
        project_id: str = DEFAULT_PROJECT_ID,
    ):
        self.router = router          # AgentModelRouter，可为 None（用 CrewAI 默认 LLM）
        self.project_id = project_id  # 读取该小说项目的 Agent / Task 配置
        self._summary: List[Tuple[str, str]] = []
        # (agent_key, model_key) 记录，供 print_creation_summary

    # ---------------- 内部工具 ----------------

    def _llm(self, key: str, label: Optional[str] = None):
        """按角色从路由器获取 LLM；router 为 None 时返回 None（用 CrewAI 默认 LLM）"""
        if self.router is None:
            return None
        llm, model_key = self.router.get_llm_for_role(key)
        agent_key = label or key
        if not any(k == agent_key for k, _ in self._summary):
            self._summary.append((agent_key, model_key))
        return llm

    def _config(self, key: str, **values) -> dict:
        """复制数据库配置，再用实际资产数据填充占位符"""
        config = self.agents_config.get(key)
        if config is None:
            row = get_repository().get_agent(
                key, project_id=self.project_id
            )
            if row is not None and not row.get("enabled", True):
                raise KeyError(
                    f"Agent 已停用: {key}（项目 {self.project_id}）"
                )
            raise KeyError(
                f"Agent 未定义: {key}（项目 {self.project_id}）"
            )
        config = dict(config)
        if values:
            for field in ("role", "goal", "backstory"):
                if isinstance(config.get(field), str):
                    try:
                        config[field] = config[field].format(**values)
                    except (KeyError, IndexError, ValueError):
                        # 用户自定义 prompt 可能含未转义的花括号：保留原文
                        pass
        return config

    def _render_task_field(
        self, key: str, field: str, values: dict
    ) -> str:
        """把数据库里的任务模板渲染成最终提示词。

        数据库是任务提示词的唯一来源：Flow 的单 Agent 步骤与标准 Crew
        共用同一份 description，避免两处各写一遍导致漂移。提示词模板
        即使 enabled=false（不进入标准 Crew）也仍然可以被读取。
        """
        config = get_repository().load_task_template(
            key, project_id=self.project_id
        )
        if config is None:
            raise KeyError(f"数据库中没有 Task 定义: {key}")
        template = str(config.get(field, ""))
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            # 用户手工编辑的模板可能有未转义的花括号：退回原文而不是中断生成
            return template

    def task_prompt(self, key: str, **values: Any) -> str:
        """按 key 读取任务描述并填充占位符"""
        return self._render_task_field(key, "description", values)

    def task_expected_output(self, key: str, **values: Any) -> str:
        """按 key 读取期望输出并填充占位符"""
        return self._render_task_field(key, "expected_output", values)

    def agent_for_key(self, key: str, **values: Any) -> Agent:
        """
        按 Agent key 创建实例。

        优先使用本类中带 @agent 的工厂方法（可注入角色专属的模型/参数）；
        数据库中新增、但没有对应工厂方法的 key，则回退为通用 Agent。
        """
        factory = getattr(self, key, None)
        if callable(factory) and getattr(factory, "is_agent", False):
            return factory(**values)

        return Agent(
            config=self._config(key, **values),
            llm=self._llm(key),
            verbose=False,
        )

    # ---------------- 角色类 Agent ----------------

    @agent
    def protagonist(self, char: Optional[CharacterAsset] = None) -> Agent:
        """主角 Agent：1 角色 = 1 实例，用最有创意表现力的模型"""
        return self.build_protagonist(char)

    def build_protagonist(
        self,
        char: Optional[CharacterAsset] = None,
        extra_tools: Optional[List[Any]] = None,
    ) -> Agent:
        """构建主角 Agent（不经过 @agent 的缓存包装）。

        extra_tools 用于注入按场景动态生成的 function-call 工具
        （例如唤醒不在场重要角色的 wake_character）。这些工具随场景变化，
        因此不能走 CrewAI 对 @agent 方法按参数缓存的路径。
        """
        tools = list(extra_tools or [])
        if char is None:
            return Agent(
                config=self._config("protagonist"),
                llm=self._llm("protagonist"),
                verbose=True,
                tools=tools,
            )
        llm = self._llm("protagonist", label=f"protagonist:{char.name}")
        return Agent(
            config=self._config(
                "protagonist",
                name=char.name,
                persona=char.persona,
                motivation=char.motivation,
            ),
            llm=llm,
            verbose=False,
            tools=tools,
        )

    @agent
    def ensemble(self, characters: Optional[List[CharacterAsset]] = None) -> Agent:
        """群演 Agent：多个次要角色共享一个实例，用便宜模型"""
        if characters is None:
            return Agent(
                config=self._config("ensemble"),
                llm=self._llm("ensemble"),
                verbose=True,
            )
        names = ", ".join(c.name for c in characters)
        brief = "\n".join(
            f"  - {c.name}: {c.persona}（动机: {c.motivation}）"
            for c in characters
        )
        llm = self._llm("ensemble", label=f"ensemble:{names}")
        return Agent(
            config=self._config("ensemble", names=names, brief=brief),
            llm=llm,
            verbose=False,
        )

    # ---------------- 全局类 Agent ----------------

    @agent
    def director(self) -> Agent:
        """
        导演 Agent（三合一）：用推理能力最强的模型，产出完整 JSON。

        职责：
        1. 意外判断（surprise）— 合理但未预期的事件
        2. 伏笔决策（foreshadow_ops）— 种植/强化/回收/颠覆
        3. 场景/回合意图（director_intent）— goal/tone/key_events
        4. 一致性自检（consistency）— 人设/时间线/设定冲突
        """
        return self.build_director()

    def build_director(
        self, extra_tools: Optional[List[Any]] = None
    ) -> Agent:
        """构建导演 Agent（不经过 @agent 的缓存包装）。

        Tools:
        - query_active_foreshadows（按需查伏笔详情，不是每次都调）
        - extra_tools：按场景注入，例如 wake_character 惰性唤醒不在场角色
        """
        from storyloom.crews.scene_crew.tools import query_active_foreshadows

        tools = [query_active_foreshadows, *(extra_tools or [])]
        return Agent(
            config=self._config("director"),
            llm=self._llm("director"),
            verbose=True,
            tools=tools,
        )

    def build_offscreen_director(self) -> Agent:
        """侧台导演：只裁决不在场角色之间的互动，不参与正文生成。

        单独收窄 max_iter 且不挂工具，保证它只做一次结构化 JSON 输出。
        """
        return Agent(
            config=self._config("offscreen_director"),
            llm=self._llm("director", label="offscreen_director"),
            verbose=False,
        )

    @agent
    def prose(self, style: Optional[str] = None) -> Agent:
        """润色 Agent：用文学表现力最强的模型"""
        if style is None:
            return Agent(
                config=self._config("prose"),
                llm=self._llm("prose"),
                verbose=True,
            )
        llm = self._llm("prose", label=f"prose:{style}")
        return Agent(
            config=self._config("prose", style=style),
            llm=llm,
            verbose=False,
        )

    # ---------------- 世界裁决（导演 Agent） ----------------
    # 原确定性规则与双模式策略已并入此处：
    # 导演 Agent 输出统一 JSON，裁决段直接生成 StateDelta。
    # 没有 LLM 时退化为「自由叙事」兜底，不阻塞回合。

    async def run_agent(
        self, agent: Agent, prompt: str, timeout_s: float = 60.0
    ) -> Optional[str]:
        """同步 kickoff 的异步包装；不可用或超时返回 None。"""
        loop = asyncio.get_event_loop()

        def _kickoff():
            return agent.kickoff(prompt)

        try:
            output = await asyncio.wait_for(
                loop.run_in_executor(None, _kickoff), timeout=timeout_s
            )
            return str(output.raw).strip() if output else None
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    async def adjudicate(
        self,
        proposal: ActionProposal,
        state: WorldState,
        mode: str = "game",
        frame: Any = None,
    ) -> AdjudicationResult:
        """导演 Agent 裁决一个行动，返回结构化结果。"""
        actor = state.characters.get(proposal.actor)
        if actor is None:
            return AdjudicationResult(
                success=False,
                outcome="rejected",
                error_code="actor_not_found",
                narrative=f"不存在的行动者：{proposal.actor}",
                rule="existence",
            )
        if actor.status == "dead":
            return AdjudicationResult(
                success=False,
                outcome="rejected",
                error_code="actor_dead",
                narrative="你已经无法行动。",
                rule="existence",
            )

        prompt = self._adjudication_prompt(proposal, state, mode, frame)
        raw = await self.run_agent(self.director(), prompt)
        if raw is None:
            return _narrate_fallback(proposal, state)
        packet = parse_agent_packet(raw)
        result = packet_to_result(packet, default_narrative=proposal.detail)
        if result.success:
            # 每个成功行动至少留下时间推进与一条事件，便于回放与记忆。
            if result.state_delta.time_delta <= 0:
                result.state_delta.time_delta = 1
            if not result.state_delta.events:
                result.state_delta.events.append(
                    state.touch(
                        "action",
                        proposal.actor,
                        proposal.detail or result.narrative,
                    )
                )
        return result

    def _adjudication_prompt(
        self,
        proposal: ActionProposal,
        state: WorldState,
        mode: str,
        frame: Any = None,
    ) -> str:
        goal = getattr(frame, "goal", "") if frame is not None else ""
        phase = getattr(frame, "phase", "") if frame is not None else ""
        mode_rule = (
            "导演模式：这是作者指令，decision 用 direct，不要否决。"
            if mode == "director"
            else "游戏模式：世界先于玩家，不可行的行动用 reject。"
        )
        return self.task_prompt(
            "adjudicate_action",
            mode_rule=mode_rule,
            packet_contract=PACKET_CONTRACT,
            phase=phase,
            goal=goal or "（未指定）",
            world_brief=self._world_brief(state, proposal.actor),
            actor=proposal.actor,
            action=proposal.detail or proposal.kind,
            target=proposal.target or "（无）",
        )

    @staticmethod
    def _world_brief(state: WorldState, actor: str) -> str:
        view = state.view(
            actor if actor in ("gm", "director", "narrator") else actor
        )
        lines = [
            f"时间：{view['time']}（第 {view['turn']} 回合）",
            f"地点：{', '.join(loc['name'] for loc in view['locations']) or '未知'}",
            "在场角色："
            + (
                ", ".join(c["name"] for c in view["characters"])
                or "无"
            ),
        ]
        if view["facts"]:
            lines.append(
                "已知事实："
                + "；".join(
                    f"{f['subject']} {f['predicate']} {f['object']}"
                    for f in view["facts"]
                )
            )
        if view["events"]:
            lines.append(
                "最近发生："
                + "；".join(e["summary"] for e in view["events"][-5:])
            )
        return "\n".join(lines)

    # ---------------- NPC 自主（群演 Agent） ----------------
    # AutonomousAgent 已并入群演 Agent：一次 JSON 调用产出 npc_actions。

    async def npc_actions(
        self,
        state: WorldState,
        idle_turns: int = 0,
        threshold: int = 3,
        memory: Any = None,
    ) -> Tuple[List[ActionProposal], List[str]]:
        if idle_turns < threshold:
            return [], []

        player = state.characters.get("玩家")
        location = player.location if player else ""
        candidates = [
            name for name in state.characters_at(location) if name != "玩家"
        ] or [
            name for name, char in state.characters.items()
            if name != "玩家" and char.status == "active"
        ]
        if not candidates:
            return [], []

        prompt = self.task_prompt(
            "npc_actions",
            packet_contract=PACKET_CONTRACT,
            world_brief=self._world_brief(state, "导演"),
            candidates=", ".join(candidates),
        )
        raw = await self.run_agent(self.ensemble(), prompt)
        packet = parse_agent_packet(raw) if raw else AgentPacket()

        proposals = [
            item for item in packet_to_proposals(packet)
            if item.actor in candidates
        ]
        if not proposals:
            proposals = _fallback_npc(state, candidates[:2])
        actors: List[str] = []
        for item in proposals:
            if item.actor not in actors:
                actors.append(item.actor)
        return proposals, actors

    # ---------------- 标准任务序列 ----------------
    # 任务完全由数据库 task_configs 表驱动：position 决定顺序，
    # agent_key 决定执行者，context_keys 决定上游任务的输出作为上下文。
    # 因此不再定义 @task 方法——新增 / 删除 / 停用任务只需改数据库。

    @crew
    def crew(self) -> Crew:
        """按数据库中的任务顺序与依赖关系装配标准 Crew"""
        tasks: List[Task] = []
        built: dict[str, Task] = {}

        for meta in get_repository().load_task_meta(self.project_id):
            config = self.tasks_config.get(meta["key"])
            if config is None:
                continue
            kwargs: dict[str, Any] = {"config": dict(config)}
            if meta.get("agent_key"):
                kwargs["agent"] = self.agent_for_key(meta["agent_key"])
            context = [
                built[key]
                for key in meta.get("context_keys", [])
                if key in built
            ]
            if context:
                kwargs["context"] = context
            task = Task(**kwargs)
            built[meta["key"]] = task
            tasks.append(task)

        agents = [self.agent_for_key(key) for key in self.agents_config]
        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
        )

    def print_creation_summary(self):
        """打印已创建 Agent 的模型分配摘要"""
        print("\n📋 Agent 创建摘要：")
        for agent_id, model_key in self._summary:
            print(f"  {agent_id:35s} → {model_key}")


def _narrate_fallback(
    proposal: ActionProposal, state: WorldState
) -> AdjudicationResult:
    """LLM 不可用时的最小兜底：记录行动并推进 1 分钟。"""
    detail = proposal.detail.strip() or "世界安静地向前推进。"
    return AdjudicationResult(
        success=True,
        outcome="narrated",
        narrative=detail,
        state_delta=StateDelta(
            time_delta=1,
            events=[state.touch("freeform", proposal.actor, detail)],
        ),
        rule="freeform_narrative",
    )


def _fallback_npc(
    state: WorldState, candidates: List[str]
) -> List[ActionProposal]:
    """LLM 不可用时的最小 NPC 提案：与旧 AutonomousAgent 行为一致。"""
    proposals: List[ActionProposal] = []
    player = state.characters.get("玩家")
    player_location = player.location if player else ""

    for name in candidates:
        char = state.characters.get(name)
        if char is None or char.status != "active":
            continue
        others = [
            other for other in state.characters_at(char.location)
            if other != name
        ]
        if char.location == player_location and player is not None:
            proposals.append(
                ActionProposal(
                    actor=name,
                    kind="talk",
                    target="玩家",
                    detail=f"{name}主动与玩家搭话",
                    source="npc",
                )
            )
        elif others:
            proposals.append(
                ActionProposal(
                    actor=name,
                    kind="talk",
                    target=others[0],
                    detail=f"{name}与{others[0]}交谈",
                    source="npc",
                )
            )
        else:
            loc = state.locations.get(char.location)
            if loc and loc.exits:
                destination = next(iter(loc.exits))
                proposals.append(
                    ActionProposal(
                        actor=name,
                        kind="move",
                        target=destination,
                        detail=f"{name}前往{destination}",
                        source="npc",
                    )
                )
            else:
                proposals.append(
                    ActionProposal(
                        actor=name,
                        kind="observe",
                        detail=f"{name}观察四周",
                        source="npc",
                    )
                )
    return proposals[:2]
