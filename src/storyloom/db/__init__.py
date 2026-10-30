"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

轻量级配置库：Agent / Task 定义的持久化层。

默认使用 SQLite（零部署），通过 SQLAlchemy 提供统一接口，
只需设置环境变量 STORYLOOM_DATABASE_URL 即可切换到
PostgreSQL / MySQL 等大型数据库，业务代码无需修改。
"""

from storyloom.db.base import database_url, get_engine, reset_engines
from storyloom.db.config_source import DbConfig
from storyloom.db.models import AgentConfigRow, Base, TaskConfigRow
from storyloom.db.repository import (
    SCENE_CREW,
    CrewConfigRepository,
    get_repository,
    reset_repositories,
)

__all__ = [
    "AgentConfigRow",
    "Base",
    "CrewConfigRepository",
    "DbConfig",
    "SCENE_CREW",
    "TaskConfigRow",
    "database_url",
    "get_engine",
    "get_repository",
    "reset_engines",
    "reset_repositories",
]
