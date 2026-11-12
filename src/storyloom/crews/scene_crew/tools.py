"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

CrewAI Tools：供 Agent 在 kickoff 过程中按需调用（function call）。

当前工具：
- query_active_foreshadows: 查询当前活跃伏笔的详细状态
"""

from typing import Any, Optional

from crewai.tools import tool


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
