"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

配置仓储：Agent / Task 定义的读写、YAML 种子导入与查询。

首次使用时自动建表，并把 crews/scene_crew/config 下的 YAML
作为“种子数据”导入数据库。此后数据库是唯一事实来源，
修改数据库即可改变 Agent / Task 行为。
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import yaml
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from storyloom.db.base import database_url, get_engine
from storyloom.db.models import AgentConfigRow, Base, TaskConfigRow

SCENE_CREW = "scene_crew"
# 内置示例项目：原有配置与种子数据都归属于它，用户可直接上手试用
DEFAULT_PROJECT_ID = "demo"

_CONFIG_DIR = (
    Path(__file__).resolve().parents[1] / "crews" / "scene_crew" / "config"
)

_AGENT_FIELDS = (
    "role",
    "goal",
    "backstory",
    "allow_delegation",
    "verbose",
    "max_iter",
    "settings",
    "enabled",
    "position",
)
_TASK_FIELDS = (
    "description",
    "expected_output",
    "agent_key",
    "context_keys",
    "enabled",
    "position",
)

# 标准任务序列的装配关系（对应 crew.py 中 @task 的 agent/context 显式装配）
_DEFAULT_TASK_WIRING: Dict[str, Dict[str, Any]] = {
    "surprise_proposal": {"agent_key": "surprise", "context_keys": []},
    "foreshadowing_ops": {"agent_key": "foreshadowing", "context_keys": []},
    "director_plan": {
        "agent_key": "director",
        "context_keys": ["surprise_proposal", "foreshadowing_ops"],
    },
    "actor_interaction": {
        "agent_key": "protagonist",
        "context_keys": ["director_plan"],
    },
    "consistency_check": {
        "agent_key": "consistency",
        "context_keys": ["actor_interaction"],
    },
    "prose_polish": {
        "agent_key": "prose",
        "context_keys": ["consistency_check"],
    },
}


class CrewConfigRepository:
    """Agent / Task 配置仓储（SQLAlchemy 实现，SQLite/PostgreSQL 通用）"""

    def __init__(self, url: Optional[str] = None):
        self.url = url or database_url()
        self.engine = get_engine(self.url)

    # ---------------- 基础设施 ----------------

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = Session(self.engine, expire_on_commit=False)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_all(self) -> None:
        # 1) 旧表先迁移（重建含 project_id 的新表并搬数据）
        migrated = self._migrate_to_project_scope()
        # 2) 再补建缺失的表
        Base.metadata.create_all(self.engine)
        if migrated:
            # 旧库数据已归入 demo 项目，从种子补齐其余配置
            self.seed_from_yaml()

    def _migrate_to_project_scope(self) -> bool:
        """
        旧库升级：为 agent_configs / task_configs 增加 project_id 列，
        并把历史数据归入 demo 项目。

        SQLite 无法删除旧约束，因此重建表；其他数据库用 ALTER TABLE。
        返回是否发生了迁移。
        """
        inspector = inspect(self.engine)
        migrated = False
        for table in ("agent_configs", "task_configs"):
            if not inspector.has_table(table):
                continue
            columns = {c["name"] for c in inspector.get_columns(table)}
            if "project_id" in columns:
                continue
            migrated = True
            if self.engine.dialect.name == "sqlite":
                self._rebuild_sqlite_for_project_scope(table)
            else:
                prefix = "agent" if table == "agent_configs" else "task"
                with self.engine.begin() as conn:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN project_id "
                        f"VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_PROJECT_ID}'"
                    )
                    try:
                        conn.exec_driver_sql(
                            f"ALTER TABLE {table} "
                            f"DROP CONSTRAINT uq_{prefix}_crew_key"
                        )
                    except Exception:
                        pass
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD CONSTRAINT "
                        f"uq_{prefix}_project_crew_key "
                        "UNIQUE (project_id, crew, key)"
                    )
        return migrated

    def _rebuild_sqlite_for_project_scope(self, table: str) -> None:
        legacy = f"{table}_legacy"
        inspector = inspect(self.engine)
        old_columns = [c["name"] for c in inspector.get_columns(table)]
        with self.engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {table} RENAME TO {legacy}")

        Base.metadata.create_all(self.engine)

        new_columns = {
            c["name"] for c in inspect(self.engine).get_columns(table)
        }
        # created_at / updated_at 不搬运：旧库可能是 NULL，
        # 新表 NOT NULL + server_default，插入时自动补当前时间
        shared = [
            name
            for name in old_columns
            if name in new_columns
            and name not in ("project_id", "created_at", "updated_at")
        ]
        shared_sql = ", ".join(shared)
        with self.engine.begin() as conn:
            conn.exec_driver_sql(
                f"INSERT INTO {table} (project_id, {shared_sql}) "
                f"SELECT '{DEFAULT_PROJECT_ID}', {shared_sql} FROM {legacy}"
            )
            conn.exec_driver_sql(f"DROP TABLE {legacy}")

    def ensure_seeded(self, project_id: str = DEFAULT_PROJECT_ID) -> None:
        """建表；若该项目还没有任何 Agent，则从 YAML 种子导入"""
        self.create_all()
        with self.session() as session:
            has_agents = session.scalar(
                select(AgentConfigRow.id)
                .where(
                    AgentConfigRow.project_id == project_id,
                    AgentConfigRow.crew == SCENE_CREW,
                )
                .limit(1)
            )
        if not has_agents:
            self.seed_from_yaml(project_id=project_id)

    # ---------------- 读取：给 CrewAI 用 ----------------

    def load_agents(
        self, project_id: str = DEFAULT_PROJECT_ID, crew: str = SCENE_CREW
    ) -> Dict[str, Dict[str, Any]]:
        """
        返回 CrewAI 可直接使用的 agents 配置字典：

            {"director": {"role": ..., "goal": ..., "backstory": ...}, ...}
        """
        self.ensure_seeded(project_id)
        with self.session() as session:
            rows = session.scalars(
                select(AgentConfigRow)
                .where(
                    AgentConfigRow.project_id == project_id,
                    AgentConfigRow.crew == crew,
                    AgentConfigRow.enabled.is_(True),
                )
                .order_by(AgentConfigRow.position, AgentConfigRow.id)
            ).all()
            return {row.key: _agent_config(row) for row in rows}

    def load_tasks(
        self, project_id: str = DEFAULT_PROJECT_ID, crew: str = SCENE_CREW
    ) -> Dict[str, Dict[str, Any]]:
        """返回 CrewAI 可直接使用的 tasks 配置字典"""
        self.ensure_seeded(project_id)
        with self.session() as session:
            rows = session.scalars(
                select(TaskConfigRow)
                .where(
                    TaskConfigRow.project_id == project_id,
                    TaskConfigRow.crew == crew,
                    TaskConfigRow.enabled.is_(True),
                )
                .order_by(TaskConfigRow.position, TaskConfigRow.id)
            ).all()
            return {
                row.key: {
                    "description": row.description,
                    "expected_output": row.expected_output,
                }
                for row in rows
            }

    def load_task_meta(
        self, project_id: str = DEFAULT_PROJECT_ID, crew: str = SCENE_CREW
    ) -> List[Dict[str, Any]]:
        """返回任务的装配元信息（顺序、agent、context）"""
        self.ensure_seeded(project_id)
        with self.session() as session:
            rows = session.scalars(
                select(TaskConfigRow)
                .where(
                    TaskConfigRow.project_id == project_id,
                    TaskConfigRow.crew == crew,
                    TaskConfigRow.enabled.is_(True),
                )
                .order_by(TaskConfigRow.position, TaskConfigRow.id)
            ).all()
            return [
                {
                    "key": row.key,
                    "agent_key": row.agent_key,
                    "context_keys": list(row.context_keys or []),
                    "position": row.position,
                }
                for row in rows
            ]

    # ---------------- 读取：给管理界面 / CLI 用 ----------------

    def list_agents(
        self, project_id: str = DEFAULT_PROJECT_ID, crew: str = SCENE_CREW
    ) -> List[Dict[str, Any]]:
        self.ensure_seeded(project_id)
        with self.session() as session:
            rows = session.scalars(
                select(AgentConfigRow)
                .where(
                    AgentConfigRow.project_id == project_id,
                    AgentConfigRow.crew == crew,
                )
                .order_by(AgentConfigRow.position, AgentConfigRow.id)
            ).all()
            return [_agent_record(row) for row in rows]

    def list_tasks(
        self, project_id: str = DEFAULT_PROJECT_ID, crew: str = SCENE_CREW
    ) -> List[Dict[str, Any]]:
        self.ensure_seeded(project_id)
        with self.session() as session:
            rows = session.scalars(
                select(TaskConfigRow)
                .where(
                    TaskConfigRow.project_id == project_id,
                    TaskConfigRow.crew == crew,
                )
                .order_by(TaskConfigRow.position, TaskConfigRow.id)
            ).all()
            return [_task_record(row) for row in rows]

    def get_agent(
        self,
        key: str,
        project_id: str = DEFAULT_PROJECT_ID,
        crew: str = SCENE_CREW,
    ) -> Optional[Dict[str, Any]]:
        with self.session() as session:
            row = session.scalar(
                select(AgentConfigRow).where(
                    AgentConfigRow.project_id == project_id,
                    AgentConfigRow.crew == crew,
                    AgentConfigRow.key == key,
                )
            )
            return _agent_record(row) if row else None

    def get_task(
        self,
        key: str,
        project_id: str = DEFAULT_PROJECT_ID,
        crew: str = SCENE_CREW,
    ) -> Optional[Dict[str, Any]]:
        with self.session() as session:
            row = session.scalar(
                select(TaskConfigRow).where(
                    TaskConfigRow.project_id == project_id,
                    TaskConfigRow.crew == crew,
                    TaskConfigRow.key == key,
                )
            )
            return _task_record(row) if row else None

    # ---------------- 写入 ----------------

    def upsert_agent(
        self,
        key: str,
        project_id: str = DEFAULT_PROJECT_ID,
        crew: str = SCENE_CREW,
        **fields: Any,
    ) -> Dict[str, Any]:
        unknown = set(fields) - set(_AGENT_FIELDS)
        if unknown:
            raise ValueError(f"未知的 Agent 字段: {sorted(unknown)}")
        self.create_all()
        with self.session() as session:
            row = session.scalar(
                select(AgentConfigRow).where(
                    AgentConfigRow.project_id == project_id,
                    AgentConfigRow.crew == crew,
                    AgentConfigRow.key == key,
                )
            )
            if row is None:
                missing = {
                    f for f in ("role", "goal", "backstory") if f not in fields
                }
                if missing:
                    raise ValueError(
                        f"新建 Agent 缺少必填字段: {sorted(missing)}"
                    )
                fields.setdefault(
                    "position",
                    self._next_position(
                        session, project_id, crew, AgentConfigRow
                    ),
                )
                row = AgentConfigRow(
                    project_id=project_id, crew=crew, key=key, **fields
                )
                session.add(row)
            else:
                for name, value in fields.items():
                    setattr(row, name, value)
            session.flush()
            return _agent_record(row)

    def upsert_task(
        self,
        key: str,
        project_id: str = DEFAULT_PROJECT_ID,
        crew: str = SCENE_CREW,
        **fields: Any,
    ) -> Dict[str, Any]:
        unknown = set(fields) - set(_TASK_FIELDS)
        if unknown:
            raise ValueError(f"未知的 Task 字段: {sorted(unknown)}")
        self.create_all()
        with self.session() as session:
            row = session.scalar(
                select(TaskConfigRow).where(
                    TaskConfigRow.project_id == project_id,
                    TaskConfigRow.crew == crew,
                    TaskConfigRow.key == key,
                )
            )
            if row is None:
                missing = {
                    f
                    for f in ("description", "expected_output")
                    if f not in fields
                }
                if missing:
                    raise ValueError(
                        f"新建 Task 缺少必填字段: {sorted(missing)}"
                    )
                fields.setdefault(
                    "position",
                    self._next_position(
                        session, project_id, crew, TaskConfigRow
                    ),
                )
                row = TaskConfigRow(
                    project_id=project_id, crew=crew, key=key, **fields
                )
                session.add(row)
            else:
                for name, value in fields.items():
                    setattr(row, name, value)
            session.flush()
            return _task_record(row)

    def delete_agent(
        self,
        key: str,
        project_id: str = DEFAULT_PROJECT_ID,
        crew: str = SCENE_CREW,
    ) -> bool:
        with self.session() as session:
            row = session.scalar(
                select(AgentConfigRow).where(
                    AgentConfigRow.project_id == project_id,
                    AgentConfigRow.crew == crew,
                    AgentConfigRow.key == key,
                )
            )
            if row is None:
                return False
            session.delete(row)
            return True

    def delete_task(
        self,
        key: str,
        project_id: str = DEFAULT_PROJECT_ID,
        crew: str = SCENE_CREW,
    ) -> bool:
        with self.session() as session:
            row = session.scalar(
                select(TaskConfigRow).where(
                    TaskConfigRow.project_id == project_id,
                    TaskConfigRow.crew == crew,
                    TaskConfigRow.key == key,
                )
            )
            if row is None:
                return False
            session.delete(row)
            return True

    # ---------------- 种子导入 ----------------

    @staticmethod
    def _next_position(
        session: Session, project_id: str, crew: str, model
    ) -> int:
        """新增条目时排到末尾"""
        current = session.scalar(
            select(func.max(model.position)).where(
                model.project_id == project_id,
                model.crew == crew,
            )
        )
        return 0 if current is None else current + 1

    def seed_from_yaml(
        self,
        project_id: str = DEFAULT_PROJECT_ID,
        crew: str = SCENE_CREW,
        overwrite: bool = False,
    ) -> Dict[str, int]:
        """
        把 crew 的 agents.yaml / tasks.yaml 导入数据库。

        overwrite=False 时只补充缺失条目，不覆盖手工修改。
        """
        self.create_all()
        agents_yaml = _load_yaml(_CONFIG_DIR / "agents.yaml")
        tasks_yaml = _load_yaml(_CONFIG_DIR / "tasks.yaml")

        inserted = {"agents": 0, "tasks": 0}
        with self.session() as session:
            for position, (key, conf) in enumerate(agents_yaml.items()):
                row = session.scalar(
                    select(AgentConfigRow).where(
                        AgentConfigRow.project_id == project_id,
                        AgentConfigRow.crew == crew,
                        AgentConfigRow.key == key,
                    )
                )
                payload = {
                    "role": conf.get("role", ""),
                    "goal": conf.get("goal", ""),
                    "backstory": conf.get("backstory", ""),
                    "allow_delegation": conf.get("allow_delegation"),
                    "verbose": conf.get("verbose"),
                    "max_iter": conf.get("max_iter"),
                    "settings": {
                        k: v
                        for k, v in conf.items()
                        if k
                        not in {
                            "role",
                            "goal",
                            "backstory",
                            "allow_delegation",
                            "verbose",
                            "max_iter",
                        }
                    },
                    "position": position,
                }
                if row is None:
                    session.add(
                        AgentConfigRow(
                            project_id=project_id,
                            crew=crew,
                            key=key,
                            **payload,
                        )
                    )
                    inserted["agents"] += 1
                elif overwrite:
                    for name, value in payload.items():
                        setattr(row, name, value)

            for position, (key, conf) in enumerate(tasks_yaml.items()):
                row = session.scalar(
                    select(TaskConfigRow).where(
                        TaskConfigRow.project_id == project_id,
                        TaskConfigRow.crew == crew,
                        TaskConfigRow.key == key,
                    )
                )
                wiring = _DEFAULT_TASK_WIRING.get(key, {})
                payload = {
                    "description": conf.get("description", ""),
                    "expected_output": conf.get("expected_output", ""),
                    "agent_key": conf.get(
                        "agent", wiring.get("agent_key")
                    ),
                    "context_keys": list(
                        conf.get("context", wiring.get("context_keys", []))
                    ),
                    "position": position,
                }
                if row is None:
                    session.add(
                        TaskConfigRow(
                            project_id=project_id,
                            crew=crew,
                            key=key,
                            **payload,
                        )
                    )
                    inserted["tasks"] += 1
                elif overwrite:
                    for name, value in payload.items():
                        setattr(row, name, value)

        return inserted


# ============================================================
# 全局单例
# ============================================================

_repositories: Dict[str, CrewConfigRepository] = {}


def get_repository(url: Optional[str] = None) -> CrewConfigRepository:
    """按数据库 URL 获取（并缓存）仓储实例"""
    resolved = url or database_url()
    repo = _repositories.get(resolved)
    if repo is None:
        repo = CrewConfigRepository(resolved)
        _repositories[resolved] = repo
    return repo


def reset_repositories() -> None:
    """清空仓储缓存（测试用）"""
    _repositories.clear()


# ============================================================
# 内部工具
# ============================================================


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def _agent_config(row: AgentConfigRow) -> Dict[str, Any]:
    """ORM → CrewAI agents 配置字典（只保留非空字段）"""
    config: Dict[str, Any] = {
        "role": row.role,
        "goal": row.goal,
        "backstory": row.backstory,
    }
    for field in ("allow_delegation", "verbose", "max_iter"):
        value = getattr(row, field)
        if value is not None:
            config[field] = value
    config.update(row.settings or {})
    return config


def _agent_record(row: AgentConfigRow) -> Dict[str, Any]:
    return {
        "key": row.key,
        "project_id": row.project_id,
        "crew": row.crew,
        "role": row.role,
        "goal": row.goal,
        "backstory": row.backstory,
        "allow_delegation": row.allow_delegation,
        "verbose": row.verbose,
        "max_iter": row.max_iter,
        "settings": dict(row.settings or {}),
        "enabled": row.enabled,
        "position": row.position,
    }


def _task_record(row: TaskConfigRow) -> Dict[str, Any]:
    return {
        "key": row.key,
        "project_id": row.project_id,
        "crew": row.crew,
        "description": row.description,
        "expected_output": row.expected_output,
        "agent_key": row.agent_key,
        "context_keys": list(row.context_keys or []),
        "enabled": row.enabled,
        "position": row.position,
    }
