"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

Agent / Task 配置表。

字段设计与 CrewAI 的 agents.yaml / tasks.yaml 一一对应：
- AgentConfigRow: role / goal / backstory / allow_delegation / verbose / max_iter
  + settings(JSON) 保存其余 CrewAI 可用的 Agent 参数
- TaskConfigRow: description / expected_output / agent_key / context_keys
  （agent/context 由代码在装配 Crew 时解析，避免 CrewBase 提前物化对象）
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """ORM 基类"""


class AgentConfigRow(Base):
    """Agent 定义（一个 crew 下的一个角色）"""

    __tablename__ = "agent_configs"
    __table_args__ = (
        UniqueConstraint("crew", "key", name="uq_agent_crew_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
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
    """Task 定义（一个 crew 下的一个任务）"""

    __tablename__ = "task_configs"
    __table_args__ = (
        UniqueConstraint("crew", "key", name="uq_task_crew_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
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
