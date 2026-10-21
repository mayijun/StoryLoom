"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.
资产数据模型：角色 / 场景 / 项目 / 伏笔 / 意外提案"""

import uuid
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class CharacterAsset(BaseModel):
    """角色资产：每个角色的完整定义"""

    name: str
    importance_tier: Literal["primary", "secondary", "background"]
    persona: str            # 性格、说话习惯
    motivation: str         # 当前动机
    secrets: str = ""       # 隐藏设定，只在需要时通过 RAG 提供


class LocationAsset(BaseModel):
    """场景资产：地点环境定义"""

    name: str
    description: str


# ================================================================
# 伏笔生命周期模型
# 参考 CreAgentive 知识图谱三元组 + Showrunner Agents 戏剧算子
# ================================================================

class ForeshadowStatus(str, Enum):
    PLANTED = "planted"           # 刚埋下
    REINFORCED = "reinforced"     # 已强化暗示
    ACTIVATED = "activated"       # 已触发揭示
    RESOLVED = "resolved"         # 已完成回收
    SUBVERTED = "subverted"       # 被意外颠覆（与 SurpriseAgent 联动）
    ABANDONED = "abandoned"       # 废弃（需清理）


class Foreshadowing(BaseModel):
    """
    伏笔资产：显式追踪每一条伏笔的生命周期

    设计依据：
    - CreAgentive: 将情节逻辑编码为语义三元组，
      支持强制执行回溯和伏笔等结构性约束
    - 长篇写作的注意力稀释：第 20 章埋下的伏笔在第 40 章
      容易被模型遗忘，需要显式追踪机制
    """

    foreshadow_id: str = Field(
        default_factory=lambda: f"fs_{uuid.uuid4().hex[:8]}"
    )
    description: str                       # "旅店墙上被涂改的航海图"
    planted_in_scene: str                  # 哪个场景埋下的
    target_revelation: str                 # 预期揭示的真相
    status: ForeshadowStatus = ForeshadowStatus.PLANTED
    reinforcement_count: int = 0           # 已暗示强化几次
    max_dormant_scenes: int = 5            # 最多允许多少场景不提及
    scenes_since_last_mention: int = 0     # 距上次提及过了几个场景
    linked_characters: List[str] = Field(default_factory=list)
    linked_surprise_ids: List[str] = Field(default_factory=list)


class SurpriseType(str, Enum):
    CHARACTER = "character"       # 角色意外：违反表面人设但符合深层动机
    INFORMATION = "information"   # 信息意外：揭露改变局势的新信息
    ENVIRONMENT = "environment"   # 环境意外：场景物理变化
    RELATIONSHIP = "relationship" # 关系意外：角色关系被重新定义
    TEMPORAL = "temporal"         # 时间意外：打破预期的时间节奏


class SurpriseProposal(BaseModel):
    """
    意外事件提案：SurpriseAgent 的结构化输出

    设计依据：
    - ACL 论文: 意外元素应当是有意为之的，服务于故事
    - 工业界倾向于"可控的随机性"，
      通过专门 Agent 管理何时、何处引入意外
    """

    proposal_id: str = Field(
        default_factory=lambda: f"sp_{uuid.uuid4().hex[:8]}"
    )
    surprise_type: SurpriseType
    description: str                       # 意外事件描述
    justification: str                     # 为什么合理（可追溯性论证）
    impact_on_plot: str                    # 对后续剧情的实质影响
    linked_foreshadow_id: Optional[str] = None  # 可关联的伏笔 ID
    severity: Literal["minor", "moderate", "major"] = "moderate"


class NovelProject(BaseModel):
    """
    项目层：封装一个完整的小说项目
    多项目切换在这一层做实例隔离，每个 project 有独立的向量库 namespace
    """

    project_id: str
    title: str
    style: str                              # 整体文风基调
    characters: List[CharacterAsset]
    locations: List[LocationAsset]
    foreshadowings: List[Foreshadowing] = Field(default_factory=list)
    scene_count: int = 0                    # 已生成场景数（用于频率控制）
    surprise_cooldown: int = 3              # 每 N 个场景最多 1 次重大意外
    last_major_surprise_scene: int = -99    # 上次重大意外的场景号

    def get_character(self, name: str) -> Optional[CharacterAsset]:
        for char in self.characters:
            if char.name == name:
                return char
        return None
