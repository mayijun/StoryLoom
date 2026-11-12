"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

分层记忆压缩器：

- 短期 → 长期：保留主线事实、人物选择、承诺 / 契约 / 关键物品 / 伏笔线索；
- 长期 → 关键事件：只保留改变主线或世界格局的事件，忽略日常互动；
- LLM 可用时由 LLM 动态压缩，不可用或返回空时走确定性选择性兜底。

压缩不是拼接：无论走哪条路径，输出都必须受 max_chars 约束。
"""

import re
from typing import Iterable, List, Sequence

from storyloom.memory.base import MemoryItem

_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")

# 与主线 / 伏笔 / 世界格局相关的信号词
_HIGH_VALUE = (
    "伏笔", "秘密", "真相", "契约", "承诺", "背叛", "死亡", "失踪",
    "身份", "王位", "钥匙", "地图", "航海图", "线索", "预言", "主线",
    "目标", "决定", "选择", "发现", "揭示", "救", "杀", "夺", "继承",
    "婚约", "血", "复仇", "交易", "代价",
)
_ACTION = (
    "进入", "离开", "前往", "回到", "打开", "交给", "拿出", "答应",
    "拒绝", "攻击", "逃跑", "追上", "救下", "杀死", "发现", "决定",
    "选择", "夺走", "失去", "出现", "消失", "拜入", "挑战", "质问",
    "坦白", "承认", "立誓", "签约", "交付",
)
_SCENERY = (
    "天气", "阳光", "月光", "风", "雾", "雨", "雪", "空气", "气味",
    "声音", "远处", "四周", "安静", "仿佛", "似乎", "景色", "街道",
    "房间", "海面", "天空", "云", "灯火", "香气",
)
_EMPTY_MARKERS = (
    "无关键事件", "没有关键事件", "无重要事件", "没有重要事件",
    "（无）", "无。", "none",
)


def build_compress_prompt(
    target_tier: str,
    items: Sequence[MemoryItem],
    max_chars: int,
    hint: str = "",
) -> str:
    """构造压缩提示：目标层不同，保留标准不同。"""
    if target_tier == "key_events":
        rules = [
            "你是编年史记录者。把下列长期剧情压缩成「关键事件」。",
            "要求：",
            "1. 只记录改变主线走向或世界格局的关键事件：转折、死亡、背叛、契约、"
            "身份揭示、伏笔回收、重大得失；",
            "2. 忽略日常互动、赶路、普通对话、环境描写与情绪渲染；",
            "3. 每条一行，格式「事件：……；影响：……」；没有影响可省略影响；",
            "4. 按时间顺序，不重复，不推测，不添加原文没有的信息；",
            f"5. 最多 {max_chars} 字。如果没有任何关键事件，只输出「无关键事件」。",
            "6. 只输出压缩结果，不要标题、序号、解释或 Markdown。",
        ]
    else:
        rules = [
            "你是叙事记忆压缩器。把下列场景记录压缩成一段「长期剧情记忆」。",
            "要求：",
            "1. 只保留推动主线的事实：谁做了什么、结果如何、承诺、契约、"
            "关键物品与线索；",
            "2. 与伏笔、秘密、人物目标相关的内容必须保留，并标注（伏笔）或（目标）；",
            "3. 删除环境描写、重复对话、情绪渲染和无关细节；",
            "4. 用陈述句按时间顺序概括，不添加原文没有的信息；",
            f"5. 不超过 {max_chars} 字，输出一段纯文本，不要标题、序号或解释。",
        ]
    if hint:
        rules.insert(1, f"额外约束：{hint}")
    material = _material(items, limit=4000)
    return "\n".join(rules + ["", "【待压缩记录】", material])


def _material(items: Sequence[MemoryItem], limit: int = 4000) -> str:
    lines: List[str] = []
    for item in items:
        label = f"场景 {item.scene_index}" if item.scene_index else "记录"
        body = (item.text or item.summary or "").strip()
        if not body:
            continue
        lines.append(
            f"[{label}｜重要度 {item.importance:.2f}] {body[:800]}"
        )
    return "\n".join(lines)[:limit]


def fallback_compress(
    items: Sequence[MemoryItem],
    target_tier: str,
    max_chars: int,
) -> str:
    """确定性选择性压缩：从原文抽关键句，而不是拼接全文。"""
    candidates: List[str] = []
    seen = set()
    for item in items:
        body = (item.text or item.summary or "").strip()
        for part in _SENTENCE_SPLIT.split(body):
            sentence = part.strip(" ，,、：:—-·")
            if len(sentence) < 6:
                continue
            key = sentence[:20]
            if key in seen:
                continue
            seen.add(key)
            candidates.append(sentence)

    if not candidates:
        return ""

    if target_tier == "key_events":
        return _select_events(candidates, max_chars)

    scored = [
        (index, sentence, _score_sentence(sentence))
        for index, sentence in enumerate(candidates)
    ]
    ranked = sorted(scored, key=lambda row: (-row[2], row[0]))
    selected: List[int] = []
    used = 0
    for index, sentence, score in ranked:
        if score <= 0:
            continue
        cost = len(sentence) + 1
        if used + cost > max_chars:
            continue
        selected.append(index)
        used += cost
    if not selected:
        selected = [ranked[0][0]] if ranked else []
    chosen = [candidates[index] for index in sorted(selected)]
    return _clamp_single("；".join(chosen), max_chars)


def _select_events(candidates: Iterable[str], max_chars: int) -> str:
    selected: List[str] = []
    used = 0
    for sentence in candidates:
        if not _is_event(sentence):
            continue
        line = sentence if sentence.startswith("事件：") else f"事件：{sentence}"
        cost = len(line) + 1
        if used + cost > max_chars:
            continue
        selected.append(line)
        used += cost
        if len(selected) >= 3:
            break
    return "\n".join(selected)


def _is_event(sentence: str) -> bool:
    high = sum(1 for word in _HIGH_VALUE if word in sentence)
    actions = sum(1 for word in _ACTION if word in sentence)
    return high >= 1 or actions >= 2


def _score_sentence(sentence: str) -> float:
    high = sum(1 for word in _HIGH_VALUE if word in sentence)
    actions = sum(1 for word in _ACTION if word in sentence)
    scenery = sum(1 for word in _SCENERY if word in sentence)
    score = high * 2.0 + min(2.0, actions)
    if high or actions:
        score += min(1.0, len(sentence) / 80)
    if scenery and not high and not actions:
        score -= 2.0
    if not high and not actions and len(sentence) < 12:
        score -= 1.0
    return score


def clamp_compressed_text(
    text: str, max_chars: int, multiline: bool = False
) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    lines = [
        line.strip(" -•\t")
        for line in text.splitlines()
        if line.strip(" -•\t")
    ]
    if multiline:
        deduped: List[str] = []
        for line in lines:
            if line not in deduped:
                deduped.append(line)
        result = ""
        for line in deduped:
            candidate = f"{result}\n{line}" if result else line
            if len(candidate) > max_chars:
                break
            result = candidate
        if result:
            return result
        lines = deduped[:1]
    joined = "；".join(line for line in lines if line)
    return _clamp_single(joined, max_chars)


def _clamp_single(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return text[: max_chars - 1].rstrip("，,、；;。 ") + "…"


def is_empty_compression(text: str, target_tier: str) -> bool:
    normalized = (text or "").strip().strip("。")
    if not normalized:
        return True
    if target_tier != "key_events":
        return False
    lowered = normalized.lower()
    return any(marker in lowered for marker in _EMPTY_MARKERS)


__all__ = [
    "build_compress_prompt",
    "clamp_compressed_text",
    "fallback_compress",
    "is_empty_compression",
]
