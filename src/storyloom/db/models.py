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

    # 对应 tasks.yaml 的 agent / context 字段
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
