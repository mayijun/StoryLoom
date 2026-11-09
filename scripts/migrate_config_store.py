#!/usr/bin/env python3
"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

配置存储迁移脚本：把「静态 YAML + 数据库种子」升级为「按项目数据库配置」。

迁移内容：
1. 补建 memory_configs 表（已存在则跳过，幂等）
2. 为每个已有项目播种一份记忆配置（来源 config/memory_config.default.yaml）
3. 把 tasks.default.yaml 中标准任务的最新提示词同步到 task_configs
   （Flow 与标准 Crew 现在共用数据库里的同一份任务描述）

用法：
    uv run python scripts/migrate_config_store.py --dry-run
    uv run python scripts/migrate_config_store.py --apply
    uv run python scripts/migrate_config_store.py --apply --project demo
    uv run python scripts/migrate_config_store.py --apply --skip-tasks
    uv run python scripts/migrate_config_store.py --apply --reset-memory

默认只预览，必须显式加 --apply 才会写入项目数据。
"""

import argparse
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    """尽量加载项目根目录 .env，保证读到 STORYLOOM_DATABASE_URL"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env")


def _tasks_yaml_path() -> Path:
    import storyloom

    return (
        Path(storyloom.__file__).resolve().parent
        / "crews"
        / "scene_crew"
        / "config"
        / "tasks.default.yaml"
    )


def _load_tasks() -> dict:
    path = _tasks_yaml_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"任务配置格式不正确: {path}")
    return data


def _diff_tasks(repo, project_id: str, desired: dict) -> tuple[list, list]:
    """对比数据库与 tasks.default.yaml，返回 (缺失, 内容有变化) 的任务键"""
    added, updated = [], []
    for key, conf in desired.items():
        current = repo.get_task(key, project_id=project_id)
        if current is None:
            added.append(key)
            continue
        if (
            current.get("description", "") != conf.get("description", "")
            or current.get("expected_output", "")
            != conf.get("expected_output", "")
        ):
            updated.append(key)
    return added, updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="迁移 StoryLoom 的按项目配置存储（memory_configs + 任务模板）",
    )
    parser.add_argument("--url", help="覆盖 STORYLOOM_DATABASE_URL")
    parser.add_argument("--project", help="只迁移指定项目（默认全部）")
    parser.add_argument(
        "--skip-tasks",
        action="store_true",
        help="只迁移记忆配置，不同步标准任务提示词",
    )
    parser.add_argument(
        "--reset-memory",
        action="store_true",
        help="把已有项目的记忆配置重置为 memory_config.default.yaml 默认值",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写库；不加时仅预览",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览（默认行为，与 --apply 互斥）",
    )
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error("--apply 与 --dry-run 不能同时使用")

    _load_env()

    from storyloom.db import DEFAULT_PROJECT_ID, get_repository

    repo = get_repository(args.url)
    print(f"数据库: {repo.url}")

    # create_all 只补建缺失的表，不会改动已有数据
    repo.create_all()
    print("✓ 表结构已就绪（memory_configs 已创建 / 已存在）")

    project_ids = (
        [args.project]
        if args.project
        else [p["project_id"] for p in repo.list_projects()]
    )
    if not project_ids:
        project_ids = [DEFAULT_PROJECT_ID]
    print(f"待迁移项目: {', '.join(project_ids)}")

    desired_tasks = {} if args.skip_tasks else _load_tasks()
    memory_created = 0
    tasks_added = 0
    tasks_updated = 0

    for pid in project_ids:
        if args.apply:
            repo.ensure_project(pid)

        # 1) 记忆配置：按项目一行，缺失时从 YAML 播种
        if not repo.memory_config_exists(pid):
            memory_created += 1
            if args.apply:
                repo.load_memory_config(pid)
                print(f"  [{pid}] + memory_configs（memory_config.default.yaml）")
            else:
                print(f"  [{pid}] + memory_configs（预览）")
        elif args.reset_memory:
            if args.apply:
                repo.reset_memory_config(pid)
                print(f"  [{pid}] ~ memory_configs 重置为 YAML 默认值")
            else:
                print(f"  [{pid}] ~ memory_configs 将重置为 YAML 默认值")
        else:
            print(f"  [{pid}] = memory_configs 已存在，保留")

        # 2) 标准任务提示词：只覆盖 description / expected_output，
        #    保留项目自定义的 agent_key、context_keys、enabled、position
        if not desired_tasks:
            continue
        added, updated = _diff_tasks(repo, pid, desired_tasks)
        tasks_added += len(added)
        tasks_updated += len(updated)
        for key in added:
            print(f"  [{pid}] + task: {key}")
        for key in updated:
            print(f"  [{pid}] ~ task: {key}")
        if not added and not updated:
            print(f"  [{pid}] = 标准任务提示词已是最新")
            continue
        if args.apply:
            if added:
                repo.seed_from_yaml(
                    project_id=pid, overwrite=False, kinds=("tasks",)
                )
            for key in updated:
                conf = desired_tasks[key]
                repo.upsert_task(
                    key,
                    project_id=pid,
                    description=conf.get("description", ""),
                    expected_output=conf.get("expected_output", ""),
                )

    print("\n汇总:")
    print(f"  记忆配置新建: {memory_created}")
    if desired_tasks:
        print(f"  任务新增: {tasks_added}，任务更新: {tasks_updated}")
    print(
        "  已写入。"
        if args.apply
        else "  [dry-run] 未写入任何项目数据，加 --apply 执行。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
