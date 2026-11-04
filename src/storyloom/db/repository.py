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
from storyloom.db.models import AgentConfigRow, Base, ProjectRow, TaskConfigRow

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
        """
        建表 + 迁移旧库。核心原则：**整个流程里 Base.metadata.create_all
        只调一次**（SQLite 的 CREATE INDEX 不幂等）。

        流程：
        1) 先探测旧表结构，把需要迁移的数据读出来
        2) 原生建 projects 表（它是外键依赖，create_all 也会建它）
        3) 丢弃旧表，把需要保留的数据暂存
        4) 一次 create_all 建出全部新表（projects + agent + task，都带外键）
        5) 把旧数据插回新表（跳过 created_at/updated_at，用 server_default）
        6) 补全 projects 表里缺失的 project_id
        """
        legacy = self._detect_and_preserve_legacy_data()

        # 原生建 projects 表（保证后续 agent/task 重建时外键有目标）
        self._ensure_projects_table_exists()

        # 丢弃旧表（如果需要迁移）
        if legacy:
            for table in ("agent_configs", "task_configs"):
                if legacy.get(table):
                    with self.engine.begin() as conn:
                        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")

        # 一次 create_all 建出全部最新结构（带外键）
        Base.metadata.create_all(self.engine)

        # 迁移场景：先从 legacy 数据收集所有 project_id，补进 projects 表，
        # 这样后续 INSERT agent/task 不会撞外键约束
        if legacy:
            self._pre_populate_projects_from_legacy(legacy)
            self._restore_legacy_data(legacy)

        # 补全 projects 表：确保所有 agent/task 引用的 project_id 都存在
        self._ensure_all_project_ids_known()

        if legacy:
            self.seed_from_yaml()

    def _detect_and_preserve_legacy_data(self) -> Optional[Dict[str, Any]]:
        """
        检测是否需要迁移（旧表缺 project_id 列或缺外键）。
        如果需要，把旧表数据读出来返回，之后由 create_all 重建新表。
        """
        inspector = inspect(self.engine)
        need_migration = False
        preserved: Dict[str, Any] = {}

        for table in ("agent_configs", "task_configs"):
            if not inspector.has_table(table):
                continue
            columns = {c["name"] for c in inspector.get_columns(table)}
            fks = inspector.get_foreign_keys(table)
            has_project_fk = any(
                "project_id" in fk["constrained_columns"]
                and "projects" in fk.get("referred_table", "")
                for fk in fks
            )

            # 需要迁移：缺 project_id 列 或 缺外键
            has_project_col = "project_id" in columns
            if not has_project_col or not has_project_fk:
                need_migration = True
                # 读数据
                with self.engine.connect() as conn:
                    col_names = [c["name"] for c in inspector.get_columns(table)]
                    col_sql = ", ".join(col_names)
                    raw_rows = conn.exec_driver_sql(
                        f"SELECT {col_sql} FROM {table}"
                    ).all()
                    rows = [
                        dict(zip(col_names, row)) for row in raw_rows
                    ]
                preserved[table] = {"columns": list(columns), "rows": rows}

        return preserved if need_migration else None

    def _restore_legacy_data(self, legacy: Dict[str, Any]) -> None:
        """把旧表数据插回由 create_all 新建的表（跳过 created_at/updated_at）"""
        for table, info in legacy.items():
            old_columns = info["columns"]
            rows = info["rows"]
            # 用 inspector 获取新表的列（最可靠）
            new_columns_set = {
                c["name"]
                for c in inspect(self.engine).get_columns(table)
            }
            # 可复制的列：两个表都有，且不是时间戳（server_default 会自动填）
            shared = [
                c
                for c in old_columns
                if c in new_columns_set
                and c not in ("created_at", "updated_at")
            ]
            # 如果旧表缺 project_id 列，强制把它加进去（新表有这个列且是 NOT NULL）
            need_project_id = (
                "project_id" not in old_columns
                and "project_id" in new_columns_set
            )
            if need_project_id:
                shared.append("project_id")
                rows = [
                    {"project_id": DEFAULT_PROJECT_ID, **r} for r in rows
                ]
            # 过滤脏数据：project_id 为空/None 的行无法通过新表的外键约束，
            # 跳过它们，避免一条垃圾行阻塞整个迁移
            if "project_id" in shared:
                rows = [r for r in rows if r.get("project_id")]
            if not shared or not rows:
                continue
            shared_sql = ", ".join(shared)
            placeholders = ", ".join(f":{c}" for c in shared)
            with self.engine.begin() as conn:
                for row in rows:
                    conn.exec_driver_sql(
                        f"INSERT INTO {table} ({shared_sql}) "
                        f"VALUES ({placeholders})",
                        {c: row.get(c) for c in shared},
                    )

    def ensure_seeded(self, project_id: str = DEFAULT_PROJECT_ID) -> None:
        """建表；确保项目存在；若该项目还没有任何 Agent，则从 YAML 种子导入"""
        self.create_all()
        self.ensure_project(project_id)
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

    # ---------------- 项目元数据读写 ----------------

    def list_projects(self) -> List[Dict[str, Any]]:
        self.create_all()
        with self.session() as session:
            rows = session.scalars(
                select(ProjectRow).order_by(ProjectRow.updated_at.desc())
            ).all()
            return [_project_record(row) for row in rows]

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self.session() as session:
            row = session.scalar(
                select(ProjectRow).where(
                    ProjectRow.project_id == project_id
                )
            )
            return _project_record(row) if row else None

    def create_project(
        self,
        project_id: str,
        title: str,
        style: str,
        description: str = "",
    ) -> Dict[str, Any]:
        self.create_all()
        with self.session() as session:
            existing = session.scalar(
                select(ProjectRow).where(ProjectRow.project_id == project_id)
            )
            if existing is not None:
                raise ValueError(f"项目已存在: {project_id}")
            row = ProjectRow(
                project_id=project_id,
                title=title,
                style=style,
                description=description,
            )
            session.add(row)
            session.flush()
            record = _project_record(row)
        # 必须在 session 提交/关闭之后再调 seed_from_yaml，
        # 否则 SQLite 写锁未释放，seed 内部开新 session 会 database is locked
        self.seed_from_yaml(project_id=project_id)
        return record

    def upsert_project(
        self,
        project_id: str,
        *,
        title: Optional[str] = None,
        style: Optional[str] = None,
        description: Optional[str] = None,
        scene_count: Optional[int] = None,
        character_count: Optional[int] = None,
        foreshadowing_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """部分更新；不存在则新建（使用占位 title/style）"""
        # 注意：这里不调 create_all()，避免在 create_all 的
        # _ensure_all_project_ids_known 阶段触发递归。
        # 调用方（ensure_seeded / create_project / list_projects）
        # 都已经负责在更早阶段建表。
        with self.session() as session:
            row = session.scalar(
                select(ProjectRow).where(ProjectRow.project_id == project_id)
            )
            if row is None:
                row = ProjectRow(
                    project_id=project_id,
                    title=title or f"项目 {project_id}",
                    style=style or "unknown",
                    description=description or "",
                )
                session.add(row)
            else:
                for field in (
                    "title",
                    "style",
                    "description",
                    "scene_count",
                    "character_count",
                    "foreshadowing_count",
                ):
                    value = locals().get(field)
                    if value is not None:
                        setattr(row, field, value)
            session.flush()
            return _project_record(row)

    def update_project_stats(
        self,
        project_id: str,
        *,
        scene_count: Optional[int] = None,
        character_count: Optional[int] = None,
        foreshadowing_count: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """只更新统计字段（生成场景后调用）"""
        with self.session() as session:
            row = session.scalar(
                select(ProjectRow).where(ProjectRow.project_id == project_id)
            )
            if row is None:
                return None
            if scene_count is not None:
                row.scene_count = scene_count
            if character_count is not None:
                row.character_count = character_count
            if foreshadowing_count is not None:
                row.foreshadowing_count = foreshadowing_count
            session.flush()
            return _project_record(row)

    def delete_project(self, project_id: str) -> bool:
        """
        删除项目。由于外键 ON DELETE CASCADE，
        agent_configs / task_configs 中该项目的记录会自动清除。
        demo 项目禁止删除（避免系统默认配置丢失）。
        """
        if project_id == DEFAULT_PROJECT_ID:
            raise ValueError("demo 内置项目禁止删除")
        with self.session() as session:
            row = session.scalar(
                select(ProjectRow).where(ProjectRow.project_id == project_id)
            )
            if row is None:
                return False
            session.delete(row)
            return True

    def project_exists(self, project_id: str) -> bool:
        with self.session() as session:
            return (
                session.scalar(
                    select(ProjectRow.project_id).where(
                        ProjectRow.project_id == project_id
                    )
                )
                is not None
            )

    def ensure_project(self, project_id: str) -> Dict[str, Any]:
        """
        确保 projects 表里有指定的 project_id 行。
        已存在时直接返回（**不修改**，避免覆盖用户已设置的 title/style）；
        不存在时插入占位记录。
        """
        with self.session() as session:
            row = session.scalar(
                select(ProjectRow).where(ProjectRow.project_id == project_id)
            )
            if row is not None:
                return _project_record(row)
            row = ProjectRow(
                project_id=project_id,
                title=f"项目 {project_id}",
                style="unknown",
                description="",
            )
            session.add(row)
            session.flush()
            return _project_record(row)

    # ---------------- create_all 内部辅助 ----------------

    def _pre_populate_projects_from_legacy(
        self, legacy: Dict[str, Any]
    ) -> None:
        """
        从 legacy 暂存数据里提取所有 project_id，确保它们在 projects 表里。
        必须在 restore 之前调用，否则 agent/task INSERT 会撞外键约束。
        如果旧表根本没 project_id 列，所有数据都归入 DEFAULT_PROJECT_ID。
        """
        project_ids: set[str] = set()
        has_project_col_in_any = False
        for info in legacy.values():
            if "project_id" in info["columns"]:
                has_project_col_in_any = True
                for row in info["rows"]:
                    pid = row.get("project_id")
                    if pid:
                        project_ids.add(pid)
        if not has_project_col_in_any:
            project_ids.add(DEFAULT_PROJECT_ID)
        for pid in project_ids:
            self.ensure_project(pid)

    def _ensure_projects_table_exists(self) -> None:
        """
        原生建 projects 表。必须在 drop agent/task 旧表之前调用，
        保证后续重建 agent/task 时外键目标已存在。
        （即使 Base.metadata.create_all 也会建 projects，
        我们先原生建一个，这样 DROP TABLE 之后、create_all 之前
        外键约束不会因为"被引用对象不存在"而出错。）
        """
        with self.engine.begin() as conn:
            # SQLite / PostgreSQL / MySQL 的 CREATE TABLE IF NOT EXISTS 都幂等
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id VARCHAR(64) PRIMARY KEY,
                    title TEXT NOT NULL,
                    style VARCHAR(64) NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    scene_count INTEGER NOT NULL DEFAULT 0,
                    character_count INTEGER NOT NULL DEFAULT 0,
                    foreshadowing_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _ensure_all_project_ids_known(self) -> None:
        """
        扫描 agent_configs / task_configs 表里所有出现的 project_id，
        确保它们在 projects 表里都有对应行（避免外键悬挂）。
        缺失的 project_id 会被 upsert 一个占位记录。
        """
        with self.engine.connect() as conn:
            project_ids: set[str] = set()
            for table in ("agent_configs", "task_configs"):
                try:
                    rows = conn.exec_driver_sql(
                        f"SELECT DISTINCT project_id FROM {table}"
                    ).all()
                    project_ids.update(
                        r[0] for r in rows if r[0]  # 过滤 None 和空串
                    )
                except Exception:
                    # 表可能不存在（全新库），忽略
                    pass

        for pid in project_ids:
            self.ensure_project(pid)

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
        # 必须先确保 projects 表里有目标 project_id 行，
        # 否则插入 agent_configs / task_configs 时撞外键（迁移场景下 demo 可能缺失）
        self.ensure_project(project_id)
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


def _project_record(row: ProjectRow) -> Dict[str, Any]:
    return {
        "project_id": row.project_id,
        "title": row.title,
        "style": row.style,
        "description": row.description or "",
        "scene_count": row.scene_count,
        "character_count": row.character_count,
        "foreshadowing_count": row.foreshadowing_count,
    }
