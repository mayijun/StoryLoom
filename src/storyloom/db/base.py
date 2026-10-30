"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

数据库连接层。

默认连接 SQLite 文件（<项目根>/data/storyloom.db），
设置 STORYLOOM_DATABASE_URL 可无缝切换到大型数据库，例如：

    STORYLOOM_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/storyloom
"""

import os
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import Engine, create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_FILE = DEFAULT_DATA_DIR / "storyloom.db"

_engines: Dict[str, Engine] = {}


def database_url() -> str:
    """返回当前数据库 URL（环境变量优先，否则使用本地 SQLite）"""
    url = os.getenv("STORYLOOM_DATABASE_URL", "").strip()
    if url:
        return url
    return f"sqlite:///{DEFAULT_DB_FILE}"


def get_engine(url: Optional[str] = None) -> Engine:
    """按 URL 获取（并缓存）SQLAlchemy Engine"""
    resolved = url or database_url()
    engine = _engines.get(resolved)
    if engine is None:
        kwargs = {}
        if resolved.startswith("sqlite"):
            # SQLite 文件库会被多线程（FastAPI 线程池）访问
            kwargs["connect_args"] = {"check_same_thread": False}
            if resolved.startswith("sqlite:///"):
                db_path = Path(resolved.replace("sqlite:///", ""))
                db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(resolved, future=True, **kwargs)
        _engines[resolved] = engine
    return engine


def reset_engines() -> None:
    """清空 Engine 缓存（测试或多库切换时使用）"""
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
