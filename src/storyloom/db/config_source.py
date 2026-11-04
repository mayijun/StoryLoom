"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

把 CrewAI 的 agents_config / tasks_config 接到数据库上。

CrewAI 的 @CrewBase 会从 YAML 路径加载配置并赋给实例属性；
这里用描述符拦截该行为：
- 类访问时返回种子 YAML 的相对路径（满足 CrewBase 对字符串路径的约定）
- 实例访问时从数据库读取最新配置
- CrewBase 的 YAML 赋值被忽略（数据库才是事实来源）
"""

from typing import Any, Dict, Optional, Tuple

from storyloom.db.repository import (
    DEFAULT_PROJECT_ID,
    SCENE_CREW,
    get_repository,
)


class DbConfig:
    """agents_config / tasks_config 的数据库配置描述符"""

    def __init__(self, kind: str, crew: str = SCENE_CREW):
        if kind not in ("agents", "tasks"):
            raise ValueError(f"不支持的配置类型: {kind}")
        self.kind = kind
        self.crew = crew

    def __get__(self, obj: Optional[Any], owner: Optional[type] = None):
        # 类访问：CrewBase 用它推导 original_*_config_path（YAML 种子路径）
        if obj is None:
            return f"config/{self.kind}.yaml"

        project_id = getattr(obj, "project_id", DEFAULT_PROJECT_ID)
        cache: Dict[Tuple[str, str], Dict[str, Any]] = obj.__dict__.setdefault(
            "_db_config_cache", {}
        )
        cache_key = (self.kind, project_id)
        if cache_key not in cache:
            repo = get_repository()
            if self.kind == "agents":
                cache[cache_key] = repo.load_agents(
                    project_id=project_id, crew=self.crew
                )
            else:
                cache[cache_key] = repo.load_tasks(
                    project_id=project_id, crew=self.crew
                )
        return cache[cache_key]

    def __set__(self, obj: Any, value: Any) -> None:
        # CrewBase 会把 YAML 内容赋给该属性：数据库才是唯一来源，忽略
        obj.__dict__.setdefault("_db_config_cache", {})
