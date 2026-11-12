"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

数据库表定义：
- ProjectRow: 小说项目元数据（project_id 主键，供 agent / task 表外键引用）
- AgentConfigRow / TaskConfigRow: 从属于某个小说项目的 CrewAI 配置
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Integer,
    JSON,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """ORM 基类"""


class ProjectRow(Base):
    """小说项目元数据（唯一主键 project_id，被 agent/task_configs 外键引用）"""

    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    style: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")

    # 运行时统计（每次生成后累加）
    scene_count: Mapped[int] = mapped_column(Integer, default=0)
    character_count: Mapped[int] = mapped_column(Integer, default=0)
    foreshadowing_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AgentConfigRow(Base):
    """Agent 定义（某个小说项目、某个 crew 下的一个角色）"""

    __tablename__ = "agent_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "crew", "key", name="uq_agent_project_crew_key"),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name="fk_agent_project",
            # 项目删除时级联清理其 Agent / Task 配置（避免外键悬挂）
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), default="demo", index=True)
    crew: Mapped[str] = mapped_column(
        String(64), default="scene_crew", index=True
    )
    key: Mapped[str] = mapped_column(String(64), index=True)

    role: Mapped[str] = mapped_column(Text)
    goal: Mapped[str] = mapped_column(Text)
    backstory: Mapped[str] = mapped_column(Text)

    allow_delegation: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
    verbose: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    max_iter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 其余 CrewAI Agent 参数（如 max_rpm / reasoning / guardrail_max_retries）
    settings: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TaskConfigRow(Base):
    """Task 定义（某个小说项目、某个 crew 下的一个任务）"""

    __tablename__ = "task_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "crew", "key", name="uq_task_project_crew_key"),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name="fk_task_project",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), default="demo", index=True)
    crew: Mapped[str] = mapped_column(
        String(64), default="scene_crew", index=True
    )
    key: Mapped[str] = mapped_column(String(64), index=True)

    description: Mapped[str] = mapped_column(Text)
    expected_output: Mapped[str] = mapped_column(Text)

    # 对应 tasks.default.yaml 的 agent / context 字段
    agent_key: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    context_keys: Mapped[List[str]] = mapped_column(JSON, default=list)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class MemoryConfigRow(Base):
    """项目级记忆层配置（memory_config.default.yaml 的数据库版本）

    每个项目一份，payload 与 YAML 结构一致（tiers / key_events / demotion /
    retrieval），便于按项目单独调节记忆策略。
    """

    __tablename__ = "memory_configs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name="fk_memory_config_project",
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ================================================================
# 章节结构
# ================================================================

class ChapterRow(Base):
    """章节：小说的层级组织单元，场景归属于章节"""

    __tablename__ = "chapters"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name="fk_chapter_project",
            ondelete="CASCADE",
        ),
    )

    chapter_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)

    title: Mapped[str] = mapped_column(Text)
    outline: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    # draft(草稿) / locked(锁定大纲) / written(已写完)
    status: Mapped[str] = mapped_column(String(32), default="draft")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ================================================================
# 场景正文与生成历史
# ================================================================

class SceneRow(Base):
    """已生成的场景正文与生成元数据（按项目隔离）"""

    __tablename__ = "scenes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name="fk_scene_project",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.chapter_id"],
            name="fk_scene_chapter",
            # 删除章节时场景不丢失，仅解除归属（chapter_id 置 NULL）
            ondelete="SET NULL",
        ),
    )

    scene_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    chapter_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    brief: Mapped[str] = mapped_column(Text)
    present_characters: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True, default=list)
    prose: Mapped[str] = mapped_column(Text, default="")

    quality_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_usage: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


# ================================================================
# 资产：角色 / 场景 / 伏笔
# ================================================================

class CharacterRow(Base):
    """角色资产"""

    __tablename__ = "characters"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_char_project_name"),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name="fk_char_project",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)

    name: Mapped[str] = mapped_column(String(128))
    importance_tier: Mapped[str] = mapped_column(String(32))  # primary/secondary/background
    persona: Mapped[str] = mapped_column(Text)
    motivation: Mapped[str] = mapped_column(Text)
    secrets: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class LocationRow(Base):
    """场景（地点）资产"""

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_loc_project_name"),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name="fk_loc_project",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)

    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ForeshadowRow(Base):
    """伏笔资产（显式生命周期状态机）"""

    __tablename__ = "foreshadowings"
    __table_args__ = (
        UniqueConstraint("project_id", "foreshadow_id", name="uq_fs_project_id"),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name="fk_fs_project",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)

    foreshadow_id: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    planted_in_scene: Mapped[str] = mapped_column(String(64))
    target_revelation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="planted")
    reinforcement_count: Mapped[int] = mapped_column(Integer, default=0)
    max_dormant_scenes: Mapped[int] = mapped_column(Integer, default=5)
    scenes_since_last_mention: Mapped[int] = mapped_column(Integer, default=0)
    linked_characters: Mapped[List[str]] = mapped_column(JSON, default=list)
    linked_surprise_ids: Mapped[List[str]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ================================================================
# 分层记忆 v2
# ================================================================

class MemoryRow(Base):
    """叙事记忆条目（分层核心记忆 + 降级检索库）

    作品数据（scenes / 资产）是事实来源；本表是可重建的索引与分层缓存。
    """

    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)

    tier: Mapped[str] = mapped_column(String(32), index=True)  # short/long/key_events/archive
    text: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    scene_index: Mapped[int] = mapped_column(Integer, default=0)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    adoptions: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_scene: Mapped[int] = mapped_column(Integer, default=0)

    # public / private:<角色名>
    visibility: Mapped[str] = mapped_column(String(128), default="public")
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(32), default="scene")
    active_foreshadow: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
