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
from typing import Any, Dict, Iterator, List, Optional, Tuple

import yaml
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from storyloom.db.base import database_url, get_engine
from storyloom.db.models import (
    AgentConfigRow,
    Base,
    ChapterRow,
    CharacterRow,
    ForeshadowRow,
    LocationRow,
    MemoryConfigRow,
    MemoryRow,
    ProjectRow,
    SceneRow,
    TaskConfigRow,
)

SCENE_CREW = "scene_crew"
# 内置示例项目：原有配置与种子数据都归属于它，用户可直接上手试用
DEFAULT_PROJECT_ID = "demo"

_CONFIG_DIR = (
    Path(__file__).resolve().parents[1] / "crews" / "scene_crew" / "config"
)
_MEMORY_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "memory_config.default.yaml"
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
        # 同一实例只做一次建表/迁移探测；失败时不置位，下次仍会重试
        self._schema_ready = False

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

    def _ensure_schema(self) -> None:
        """方法入口的轻量建表检查：本实例建过一次后直接返回。"""
        if not self._schema_ready:
            self.create_all()

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
            for table in ("agent_configs", "task_configs", "scenes"):
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

        # 一次性数据迁移：记忆层 canon / private 旧格式
        self._migrate_memory_data()
        # 角色秘密 → 记忆条目；伏笔可见性列
        self._migrate_character_secrets()
        self._migrate_foreshadow_visibility()

        if legacy:
            self.seed_from_yaml()

        self._schema_ready = True

    def _migrate_memory_data(self) -> None:
        """一次性改写旧记忆数据：canon → key_events、private:<角色> → known_by。

        硬切后模型层不再接受旧格式，这里只做数据搬运，不保留运行时兼容。
        """
        inspector = inspect(self.engine)
        if inspector.has_table("memory_items"):
            columns = {
                c["name"] for c in inspector.get_columns("memory_items")
            }
            with self.engine.begin() as conn:
                if "known_by" not in columns:
                    conn.exec_driver_sql(
                        "ALTER TABLE memory_items "
                        "ADD COLUMN known_by JSON"
                    )
                conn.exec_driver_sql(
                    "UPDATE memory_items SET tier = 'key_events' "
                    "WHERE tier = 'canon'"
                )
                rows = conn.execute(
                    select(MemoryRow.id, MemoryRow.visibility)
                ).all()
                for item_id, visibility in rows:
                    if visibility == "public":
                        continue
                    if visibility and visibility.startswith("private:"):
                        name = visibility.split(":", 1)[1]
                        known_by = [name] if name else []
                        values = {
                            "visibility": "restricted",
                            "known_by": known_by,
                        }
                    elif visibility != "restricted":
                        values = {"visibility": "public", "known_by": []}
                    else:
                        continue
                    conn.execute(
                        MemoryRow.__table__.update()
                        .where(MemoryRow.id == item_id)
                        .values(**values)
                    )
        if not inspector.has_table("memory_configs"):
            return
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(MemoryConfigRow.project_id, MemoryConfigRow.payload)
            ).all()
            for project_id, payload in rows:
                updated = self._rewrite_memory_payload(payload)
                if updated is None:
                    continue
                conn.execute(
                    MemoryConfigRow.__table__.update()
                    .where(MemoryConfigRow.project_id == project_id)
                    .values(payload=updated)
                )

    def _migrate_character_secrets(self) -> None:
        """把旧 characters.secrets 迁成 restricted 记忆条目，然后删除旧列。"""
        inspector = inspect(self.engine)
        if not inspector.has_table("characters"):
            return
        columns = {c["name"] for c in inspector.get_columns("characters")}
        if "secrets" not in columns:
            return

        with self.engine.begin() as conn:
            legacy = conn.execute(
                text(
                    "SELECT project_id, name, secrets FROM characters "
                    "WHERE secrets IS NOT NULL AND secrets <> ''"
                )
            ).all()

        with self.session() as session:
            for project_id, name, secrets in legacy:
                storage_id = f"{project_id}::secret:{name}"
                if session.get(MemoryRow, storage_id) is None:
                    self._write_secret_memory(
                        session, project_id, name, secrets
                    )
            # 历史条目文本形如“<角色>的秘密：...”，统一成秘密原文
            rows = session.scalars(
                select(MemoryRow).where(MemoryRow.id.like("%::secret:%"))
            ).all()
            for row in rows:
                name = row.id.split("::secret:", 1)[1]
                prefix = f"{name}的秘密："
                if row.text.startswith(prefix):
                    row.text = row.text[len(prefix):]
                    row.summary = row.text[:200]

        try:
            with self.engine.begin() as conn:
                conn.exec_driver_sql(
                    "ALTER TABLE characters DROP COLUMN secrets"
                )
        except Exception:
            # SQLite 老版本不支持 DROP COLUMN；模型已不再映射该列
            print("  ⚠️ 无法删除 characters.secrets 列，已忽略")

    def _migrate_foreshadow_visibility(self) -> None:
        """给旧 foreshadowings 表补 visibility / known_by 列。"""
        inspector = inspect(self.engine)
        if not inspector.has_table("foreshadowings"):
            return
        columns = {c["name"] for c in inspector.get_columns("foreshadowings")}
        with self.engine.begin() as conn:
            if "visibility" not in columns:
                conn.exec_driver_sql(
                    "ALTER TABLE foreshadowings ADD COLUMN "
                    "visibility VARCHAR(32) DEFAULT 'restricted'"
                )
            if "known_by" not in columns:
                conn.exec_driver_sql(
                    "ALTER TABLE foreshadowings ADD COLUMN known_by JSON"
                )
            conn.exec_driver_sql(
                "UPDATE foreshadowings SET visibility = 'restricted' "
                "WHERE visibility IS NULL OR visibility = ''"
            )
            conn.exec_driver_sql(
                "UPDATE foreshadowings SET known_by = '[]' "
                "WHERE known_by IS NULL"
            )

    @staticmethod
    def _write_secret_memory(
        session: Session, project_id: str, name: str, secrets: str
    ) -> None:
        """角色秘密的唯一存储：archive + restricted + known_by=[角色]。"""
        storage_id = f"{project_id}::secret:{name}"
        row = session.get(MemoryRow, storage_id)
        if not secrets:
            if row is not None:
                session.delete(row)
            return
        if row is None:
            row = MemoryRow(
                id=storage_id,
                project_id=project_id,
                tier="archive",
                text=secrets,
                summary=secrets[:200],
                importance=0.8,
                visibility="restricted",
                known_by=[name],
                tags=["secret", "asset"],
                source="asset",
            )
            session.add(row)
            return
        row.text = secrets
        row.summary = secrets[:200]
        row.visibility = "restricted"
        row.known_by = [name]
        row.tags = ["secret", "asset"]
        row.source = "asset"

    @staticmethod
    def _rewrite_memory_payload(
        payload: Any,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        changed = False
        out = dict(payload)
        if "canon" in out:
            out["key_events"] = out.pop("canon")
            changed = True
        key_events = out.get("key_events")
        if isinstance(key_events, dict) and (
            key_events.get("compress_into") == "canon"
        ):
            out["key_events"] = {**key_events, "compress_into": "key_events"}
            changed = True
        demotion = out.get("demotion")
        if isinstance(demotion, dict) and "canon" in demotion:
            demotion = dict(demotion)
            demotion["key_events"] = demotion.pop("canon")
            out["demotion"] = demotion
            changed = True
        tiers = out.get("tiers")
        if isinstance(tiers, list):
            out["tiers"] = [
                {**tier, "compress_into": "key_events"}
                if isinstance(tier, dict)
                and tier.get("compress_into") == "canon"
                else tier
                for tier in tiers
            ]
            changed = changed or out["tiers"] != tiers
        return out if changed else None

    def _detect_and_preserve_legacy_data(self) -> Optional[Dict[str, Any]]:
        """
        检测是否需要迁移（旧表缺 project_id 列或缺外键）。
        如果需要，把旧表数据读出来返回，之后由 create_all 重建新表。
        同时处理 #2 场景：scenes 表已存在但缺指向 chapters 的外键。
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

        # scenes 表迁移：已存在但缺指向 chapters 的外键（#2 之前建的库）
        if inspector.has_table("scenes"):
            scene_fks = inspector.get_foreign_keys("scenes")
            has_chapter_fk = any(
                "chapter_id" in fk["constrained_columns"]
                and "chapters" in fk.get("referred_table", "")
                for fk in scene_fks
            )
            if not has_chapter_fk:
                need_migration = True
                with self.engine.connect() as conn:
                    col_names = [c["name"] for c in inspector.get_columns("scenes")]
                    col_sql = ", ".join(col_names)
                    raw_rows = conn.exec_driver_sql(
                        f"SELECT {col_sql} FROM scenes"
                    ).all()
                    rows = [dict(zip(col_names, row)) for row in raw_rows]
                preserved["scenes"] = {
                    "columns": list({c["name"] for c in inspector.get_columns("scenes")}),
                    "rows": rows,
                }

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
        self._ensure_schema()
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
        self._ensure_schema()
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
        self._ensure_schema()
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
        # 每个项目一份独立的记忆配置（种子来自 memory_config.default.yaml）
        self.load_memory_config(project_id)
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

    # ---------------- 场景（SceneRow） ----------------

    def list_scenes(self, project_id: str) -> List[Dict[str, Any]]:
        self._ensure_schema()
        with self.session() as session:
            rows = session.scalars(
                select(SceneRow)
                .where(SceneRow.project_id == project_id)
                .order_by(SceneRow.created_at, SceneRow.scene_id)
            ).all()
            return [_scene_record(row) for row in rows]

    def get_scene(self, scene_id: str) -> Optional[Dict[str, Any]]:
        with self.session() as session:
            row = session.scalar(
                select(SceneRow).where(SceneRow.scene_id == scene_id)
            )
            return _scene_record(row) if row else None

    def create_scene(
        self,
        scene_id: str,
        project_id: str,
        brief: str,
        present_characters: Optional[List[str]] = None,
        prose: str = "",
        quality_score: Optional[float] = None,
        duration_ms: Optional[int] = None,
        model_usage: Optional[Dict[str, Any]] = None,
        chapter_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._ensure_schema()
        self.ensure_project(project_id)
        with self.session() as session:
            if session.get(SceneRow, scene_id) is not None:
                raise ValueError(f"场景已存在: {scene_id}")
            row = SceneRow(
                scene_id=scene_id,
                project_id=project_id,
                chapter_id=chapter_id,
                brief=brief,
                present_characters=list(present_characters or []),
                prose=prose,
                quality_score=quality_score,
                duration_ms=duration_ms,
                model_usage=dict(model_usage or {}),
            )
            session.add(row)
            session.flush()
            return _scene_record(row)

    def update_scene(self, scene_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {
            "brief", "present_characters", "prose",
            "quality_score", "duration_ms", "model_usage", "chapter_id",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"未知的场景字段: {sorted(unknown)}")
        with self.session() as session:
            row = session.get(SceneRow, scene_id)
            if row is None:
                return None
            for field, value in fields.items():
                if value is not None:
                    setattr(row, field, value)
            session.flush()
            return _scene_record(row)

    def delete_scene(self, scene_id: str) -> bool:
        with self.session() as session:
            row = session.get(SceneRow, scene_id)
            if row is None:
                return False
            session.delete(row)
            return True

    # ---------------- 章节（ChapterRow） ----------------

    def list_chapters(self, project_id: str) -> List[Dict[str, Any]]:
        self._ensure_schema()
        with self.session() as session:
            rows = session.scalars(
                select(ChapterRow)
                .where(ChapterRow.project_id == project_id)
                .order_by(ChapterRow.position, ChapterRow.chapter_id)
            ).all()
            return [_chapter_record(row) for row in rows]

    def get_chapter(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        with self.session() as session:
            row = session.get(ChapterRow, chapter_id)
            return _chapter_record(row) if row else None

    def create_chapter(
        self,
        chapter_id: str,
        project_id: str,
        title: str,
        outline: str = "",
        position: Optional[int] = None,
        status: str = "draft",
    ) -> Dict[str, Any]:
        self._ensure_schema()
        self.ensure_project(project_id)
        with self.session() as session:
            if session.get(ChapterRow, chapter_id) is not None:
                raise ValueError(f"章节已存在: {chapter_id}")
            if position is None:
                # 自动取当前项目最大 position + 1
                max_pos = session.scalar(
                    select(func.coalesce(func.max(ChapterRow.position), -1)).where(
                        ChapterRow.project_id == project_id
                    )
                )
                position = (max_pos or 0) + 1
            row = ChapterRow(
                chapter_id=chapter_id,
                project_id=project_id,
                title=title,
                outline=outline,
                position=position,
                status=status,
            )
            session.add(row)
            session.flush()
            return _chapter_record(row)

    def update_chapter(self, chapter_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {"title", "outline", "position", "status"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"未知的章节字段: {sorted(unknown)}")
        with self.session() as session:
            row = session.get(ChapterRow, chapter_id)
            if row is None:
                return None
            for field, value in fields.items():
                if value is not None:
                    setattr(row, field, value)
            session.flush()
            return _chapter_record(row)

    def delete_chapter(self, chapter_id: str) -> bool:
        with self.session() as session:
            row = session.get(ChapterRow, chapter_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def assign_scene_to_chapter(
        self, scene_id: str, chapter_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """把场景归属到某章节；chapter_id=None 表示解除归属。"""
        with self.session() as session:
            row = session.get(SceneRow, scene_id)
            if row is None:
                return None
            if chapter_id is not None and session.get(ChapterRow, chapter_id) is None:
                raise ValueError(f"章节不存在: {chapter_id}")
            row.chapter_id = chapter_id
            session.flush()
            return _scene_record(row)

    def list_scenes_by_chapter(
        self, project_id: str, chapter_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """列出某项目下指定章节的场景；chapter_id=None 列出未归属章节的场景。"""
        self._ensure_schema()
        with self.session() as session:
            stmt = select(SceneRow).where(SceneRow.project_id == project_id)
            if chapter_id is None:
                stmt = stmt.where(SceneRow.chapter_id.is_(None))
            else:
                stmt = stmt.where(SceneRow.chapter_id == chapter_id)
            stmt = stmt.order_by(SceneRow.created_at, SceneRow.scene_id)
            rows = session.scalars(stmt).all()
            return [_scene_record(row) for row in rows]

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
        self._ensure_schema()
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
        self._ensure_schema()
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

    # ---------------- 角色（CharacterRow） ----------------

    def list_characters(self, project_id: str) -> List[Dict[str, Any]]:
        self._ensure_schema()
        with self.session() as session:
            rows = session.scalars(
                select(CharacterRow)
                .where(CharacterRow.project_id == project_id)
                .order_by(CharacterRow.id)
            ).all()
            return [_character_record(row) for row in rows]

    def get_character_asset(
        self, name: str, project_id: str
    ) -> Optional[Dict[str, Any]]:
        with self.session() as session:
            row = session.scalar(
                select(CharacterRow).where(
                    CharacterRow.project_id == project_id,
                    CharacterRow.name == name,
                )
            )
            return _character_record(row) if row else None

    def upsert_character(
        self,
        project_id: str,
        name: str,
        importance_tier: str,
        persona: str,
        motivation: str,
        secrets: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._ensure_schema()
        self.ensure_project(project_id)
        with self.session() as session:
            row = session.scalar(
                select(CharacterRow).where(
                    CharacterRow.project_id == project_id,
                    CharacterRow.name == name,
                )
            )
            if row is None:
                row = CharacterRow(
                    project_id=project_id,
                    name=name,
                    importance_tier=importance_tier,
                    persona=persona,
                    motivation=motivation,
                )
                session.add(row)
            else:
                row.importance_tier = importance_tier
                row.persona = persona
                row.motivation = motivation
            if secrets is not None:
                self._write_secret_memory(session, project_id, name, secrets)
            session.flush()
            return _character_record(row)

    def delete_character_asset(self, name: str, project_id: str) -> bool:
        with self.session() as session:
            row = session.scalar(
                select(CharacterRow).where(
                    CharacterRow.project_id == project_id,
                    CharacterRow.name == name,
                )
            )
            if row is None:
                return False
            session.delete(row)
            secret = session.get(
                MemoryRow, f"{project_id}::secret:{name}"
            )
            if secret is not None:
                session.delete(secret)
            return True

    # ---------------- 场景/地点（LocationRow） ----------------

    def list_locations(self, project_id: str) -> List[Dict[str, Any]]:
        self._ensure_schema()
        with self.session() as session:
            rows = session.scalars(
                select(LocationRow)
                .where(LocationRow.project_id == project_id)
                .order_by(LocationRow.id)
            ).all()
            return [_location_record(row) for row in rows]

    def get_location_asset(
        self, name: str, project_id: str
    ) -> Optional[Dict[str, Any]]:
        with self.session() as session:
            row = session.scalar(
                select(LocationRow).where(
                    LocationRow.project_id == project_id,
                    LocationRow.name == name,
                )
            )
            return _location_record(row) if row else None

    def upsert_location(
        self, project_id: str, name: str, description: str = ""
    ) -> Dict[str, Any]:
        self._ensure_schema()
        self.ensure_project(project_id)
        with self.session() as session:
            row = session.scalar(
                select(LocationRow).where(
                    LocationRow.project_id == project_id,
                    LocationRow.name == name,
                )
            )
            if row is None:
                row = LocationRow(
                    project_id=project_id, name=name, description=description
                )
                session.add(row)
            else:
                row.description = description
            session.flush()
            return _location_record(row)

    def delete_location_asset(self, name: str, project_id: str) -> bool:
        with self.session() as session:
            row = session.scalar(
                select(LocationRow).where(
                    LocationRow.project_id == project_id,
                    LocationRow.name == name,
                )
            )
            if row is None:
                return False
            session.delete(row)
            return True

    # ---------------- 伏笔（ForeshadowRow） ----------------

    def list_foreshadowings(self, project_id: str) -> List[Dict[str, Any]]:
        self._ensure_schema()
        with self.session() as session:
            rows = session.scalars(
                select(ForeshadowRow)
                .where(ForeshadowRow.project_id == project_id)
                .order_by(ForeshadowRow.id)
            ).all()
            return [_foreshadow_record(row) for row in rows]

    def get_foreshadowing(
        self, foreshadow_id: str, project_id: str
    ) -> Optional[Dict[str, Any]]:
        with self.session() as session:
            row = session.scalar(
                select(ForeshadowRow).where(
                    ForeshadowRow.project_id == project_id,
                    ForeshadowRow.foreshadow_id == foreshadow_id,
                )
            )
            return _foreshadow_record(row) if row else None

    def upsert_foreshadowing(
        self,
        project_id: str,
        foreshadow_id: str,
        description: str,
        planted_in_scene: str,
        target_revelation: str,
        status: str = "planted",
        reinforcement_count: int = 0,
        max_dormant_scenes: int = 5,
        scenes_since_last_mention: int = 0,
        linked_characters: Optional[List[str]] = None,
        linked_surprise_ids: Optional[List[str]] = None,
        visibility: str = "restricted",
        known_by: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        self._ensure_schema()
        self.ensure_project(project_id)
        with self.session() as session:
            row = session.scalar(
                select(ForeshadowRow).where(
                    ForeshadowRow.project_id == project_id,
                    ForeshadowRow.foreshadow_id == foreshadow_id,
                )
            )
            if row is None:
                row = ForeshadowRow(
                    project_id=project_id,
                    foreshadow_id=foreshadow_id,
                    description=description,
                    planted_in_scene=planted_in_scene,
                    target_revelation=target_revelation,
                    status=status,
                    reinforcement_count=reinforcement_count,
                    max_dormant_scenes=max_dormant_scenes,
                    scenes_since_last_mention=scenes_since_last_mention,
                    linked_characters=list(linked_characters or []),
                    linked_surprise_ids=list(linked_surprise_ids or []),
                    visibility=visibility,
                    known_by=list(known_by or []),
                )
                session.add(row)
            else:
                row.description = description
                row.planted_in_scene = planted_in_scene
                row.target_revelation = target_revelation
                row.status = status
                row.reinforcement_count = reinforcement_count
                row.max_dormant_scenes = max_dormant_scenes
                row.scenes_since_last_mention = scenes_since_last_mention
                row.linked_characters = list(linked_characters or [])
                row.linked_surprise_ids = list(linked_surprise_ids or [])
                row.visibility = visibility
                row.known_by = list(known_by or [])
            session.flush()
            return _foreshadow_record(row)

    def delete_foreshadowing(
        self, foreshadow_id: str, project_id: str
    ) -> bool:
        with self.session() as session:
            row = session.scalar(
                select(ForeshadowRow).where(
                    ForeshadowRow.project_id == project_id,
                    ForeshadowRow.foreshadow_id == foreshadow_id,
                )
            )
            if row is None:
                return False
            session.delete(row)
            return True

    # ---------------- 记忆层配置（MemoryConfigRow） ----------------

    def load_memory_config(
        self, project_id: str = DEFAULT_PROJECT_ID
    ) -> Dict[str, Any]:
        """读取项目记忆配置；首次访问时从 memory_config.default.yaml 播种"""
        self._ensure_schema()
        self.ensure_project(project_id)
        with self.session() as session:
            row = session.get(MemoryConfigRow, project_id)
            if row is None:
                row = MemoryConfigRow(
                    project_id=project_id, payload=_load_yaml(_MEMORY_CONFIG_PATH)
                )
                session.add(row)
                session.flush()
            return dict(row.payload or {})

    def memory_config_exists(
        self, project_id: str = DEFAULT_PROJECT_ID
    ) -> bool:
        """项目是否已有记忆配置行（不触发播种）"""
        with self.session() as session:
            return session.get(MemoryConfigRow, project_id) is not None

    def save_memory_config(
        self, project_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """整体覆盖项目记忆配置（调用方负责补全默认值）"""
        self._ensure_schema()
        self.ensure_project(project_id)
        with self.session() as session:
            row = session.get(MemoryConfigRow, project_id)
            if row is None:
                row = MemoryConfigRow(project_id=project_id, payload=dict(payload))
                session.add(row)
            else:
                row.payload = dict(payload)
            session.flush()
            return dict(row.payload or {})

    def reset_memory_config(
        self, project_id: str = DEFAULT_PROJECT_ID
    ) -> Dict[str, Any]:
        """恢复为 memory_config.default.yaml 的默认值（项目级重置）"""
        return self.save_memory_config(
            project_id, _load_yaml(_MEMORY_CONFIG_PATH)
        )

    # ---------------- 分层记忆（MemoryRow） ----------------

    def upsert_memory_item(
        self, project_id: str, **fields: Any
    ) -> Dict[str, Any]:
        """写入 / 更新一条记忆（索引可重建，不强制外键）"""
        self._ensure_schema()
        item_id = fields.get("id")
        if not item_id:
            raise ValueError("记忆条目缺少 id")
        allowed = {
            "tier", "text", "summary", "importance", "pinned",
            "scene_index", "hits", "adoptions", "last_hit_scene",
            "visibility", "known_by", "tags", "source",
            "active_foreshadow",
        }
        with self.session() as session:
            row = session.get(MemoryRow, item_id)
            if row is None:
                row = MemoryRow(id=item_id, project_id=project_id)
                session.add(row)
            for key, value in fields.items():
                if key in allowed:
                    setattr(row, key, value)
            session.flush()
            return _memory_record(row)

    def list_memory_items(
        self, project_id: str, tier: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        self._ensure_schema()
        with self.session() as session:
            stmt = select(MemoryRow).where(
                MemoryRow.project_id == project_id
            )
            if tier is not None:
                stmt = stmt.where(MemoryRow.tier == tier)
            rows = session.scalars(
                stmt.order_by(MemoryRow.scene_index, MemoryRow.id)
            ).all()
            return [_memory_record(row) for row in rows]

    def delete_memory_item(self, item_id: str) -> bool:
        with self.session() as session:
            row = session.get(MemoryRow, item_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def clear_memory_items(self, project_id: str) -> int:
        """清空项目记忆（用于回填 / 测试）"""
        with self.session() as session:
            rows = session.scalars(
                select(MemoryRow).where(MemoryRow.project_id == project_id)
            ).all()
            for row in rows:
                session.delete(row)
            return len(rows)

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
        kinds: Tuple[str, ...] = ("agents", "tasks"),
    ) -> Dict[str, int]:
        """
        把 crew 的 agents.default.yaml / tasks.default.yaml 导入数据库。

        overwrite=False 时只补充缺失条目，不覆盖手工修改。
        kinds 可限定只同步 agents 或 tasks（配置迁移脚本使用）。
        """
        self._ensure_schema()
        # 必须先确保 projects 表里有目标 project_id 行，
        # 否则插入 agent_configs / task_configs 时撞外键（迁移场景下 demo 可能缺失）
        self.ensure_project(project_id)
        agents_yaml = (
            _load_yaml(_CONFIG_DIR / "agents.default.yaml")
            if "agents" in kinds
            else {}
        )
        tasks_yaml = (
            _load_yaml(_CONFIG_DIR / "tasks.default.yaml")
            if "tasks" in kinds
            else {}
        )

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
                    "enabled": conf.get("enabled", True),
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


def _scene_record(row: SceneRow) -> Dict[str, Any]:
    return {
        "scene_id": row.scene_id,
        "project_id": row.project_id,
        "chapter_id": row.chapter_id,
        "brief": row.brief,
        "present_characters": list(row.present_characters or []),
        "prose": row.prose or "",
        "quality_score": row.quality_score,
        "duration_ms": row.duration_ms,
        "model_usage": dict(row.model_usage or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _chapter_record(row: ChapterRow) -> Dict[str, Any]:
    return {
        "chapter_id": row.chapter_id,
        "project_id": row.project_id,
        "title": row.title,
        "outline": row.outline or "",
        "position": row.position,
        "status": row.status,
    }


def _character_record(row: CharacterRow) -> Dict[str, Any]:
    return {
        "name": row.name,
        "project_id": row.project_id,
        "importance_tier": row.importance_tier,
        "persona": row.persona,
        "motivation": row.motivation,
    }


def _location_record(row: LocationRow) -> Dict[str, Any]:
    return {
        "name": row.name,
        "project_id": row.project_id,
        "description": row.description or "",
    }


def _foreshadow_record(row: ForeshadowRow) -> Dict[str, Any]:
    return {
        "foreshadow_id": row.foreshadow_id,
        "project_id": row.project_id,
        "description": row.description,
        "planted_in_scene": row.planted_in_scene,
        "target_revelation": row.target_revelation,
        "status": row.status,
        "reinforcement_count": row.reinforcement_count,
        "max_dormant_scenes": row.max_dormant_scenes,
        "scenes_since_last_mention": row.scenes_since_last_mention,
        "linked_characters": list(row.linked_characters or []),
        "linked_surprise_ids": list(row.linked_surprise_ids or []),
        "visibility": row.visibility or "restricted",
        "known_by": list(row.known_by or []),
    }


def _memory_record(row: MemoryRow) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "tier": row.tier,
        "text": row.text or "",
        "summary": row.summary or "",
        "importance": row.importance,
        "pinned": row.pinned,
        "scene_index": row.scene_index,
        "hits": row.hits,
        "adoptions": row.adoptions,
        "last_hit_scene": row.last_hit_scene,
        "visibility": row.visibility,
        "known_by": list(row.known_by or []),
        "tags": list(row.tags or []),
        "source": row.source,
        "active_foreshadow": row.active_foreshadow,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
