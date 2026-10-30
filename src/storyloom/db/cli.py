"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

Agent / Task 配置管理 CLI。

用法示例：
    uv run storyloom-config list
    uv run storyloom-config show agent director
    uv run storyloom-config set agent director backstory "新的背景设定"
    uv run storyloom-config add agent critic --role 批评家 --goal 挑刺 --backstory ...
    uv run storyloom-config add task review --agent critic --description ... --expected-output ...
    uv run storyloom-config rm task review
    uv run storyloom-config seed --overwrite
"""

import argparse
import sys
from typing import Any, List, Optional

from storyloom.db.repository import get_repository

_BOOL_FIELDS = {"allow_delegation", "verbose", "enabled"}
_INT_FIELDS = {"max_iter", "position"}
_LIST_FIELDS = {"context_keys"}


def _coerce(field: str, raw: str) -> Any:
    if field in _BOOL_FIELDS:
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    if field in _INT_FIELDS:
        return int(raw)
    if field in _LIST_FIELDS:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


def _print_agents(rows: List[dict]) -> None:
    print(f"{'KEY':<18}{'ENABLED':<9}{'ROLE'}")
    for row in rows:
        print(
            f"{row['key']:<18}{str(row['enabled']):<9}{row['role'].splitlines()[0][:60]}"
        )


def _print_tasks(rows: List[dict]) -> None:
    print(f"{'KEY':<22}{'AGENT':<16}{'CONTEXT':<32}DESCRIPTION")
    for row in rows:
        context = ",".join(row["context_keys"]) or "-"
        first_line = row["description"].strip().splitlines()[0][:40]
        print(
            f"{row['key']:<22}{str(row['agent_key']):<16}{context:<32}{first_line}"
        )


def _print_record(record: dict) -> None:
    width = max(len(key) for key in record)
    for key, value in record.items():
        print(f"{key:<{width}} : {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="storyloom-config",
        description="查看 / 修改 StoryLoom 的 Agent 与 Task 配置（数据库存储）",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="数据库 URL（默认读取 STORYLOOM_DATABASE_URL 或本地 SQLite）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出全部 Agent 和 Task")

    show = sub.add_parser("show", help="查看单个 Agent / Task")
    show.add_argument("kind", choices=["agent", "task"])
    show.add_argument("key")

    set_cmd = sub.add_parser("set", help="修改 Agent / Task 的某个字段")
    set_cmd.add_argument("kind", choices=["agent", "task"])
    set_cmd.add_argument("key")
    set_cmd.add_argument("field")
    set_cmd.add_argument("value")

    add_agent = sub.add_parser("add-agent", help="新增 Agent")
    add_agent.add_argument("key")
    add_agent.add_argument("--role", required=True)
    add_agent.add_argument("--goal", required=True)
    add_agent.add_argument("--backstory", required=True)
    add_agent.add_argument("--allow-delegation", default=None)
    add_agent.add_argument("--verbose", default=None)
    add_agent.add_argument("--max-iter", type=int, default=None)

    add_task = sub.add_parser("add-task", help="新增 Task")
    add_task.add_argument("key")
    add_task.add_argument("--description", required=True)
    add_task.add_argument("--expected-output", required=True)
    add_task.add_argument("--agent", dest="agent_key", default=None)
    add_task.add_argument(
        "--context", default=None, help="上游任务 key，逗号分隔"
    )

    rm_cmd = sub.add_parser("rm", help="删除 Agent / Task")
    rm_cmd.add_argument("kind", choices=["agent", "task"])
    rm_cmd.add_argument("key")

    seed = sub.add_parser("seed", help="从 YAML 种子文件导入配置")
    seed.add_argument(
        "--overwrite", action="store_true", help="覆盖已存在的条目"
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo = get_repository(args.url)

    if args.command == "list":
        repo.ensure_seeded()
        print("Agents:")
        _print_agents(repo.list_agents())
        print("\nTasks:")
        _print_tasks(repo.list_tasks())
        return 0

    if args.command == "show":
        record = (
            repo.get_agent(args.key)
            if args.kind == "agent"
            else repo.get_task(args.key)
        )
        if record is None:
            print(f"未找到 {args.kind}: {args.key}", file=sys.stderr)
            return 1
        _print_record(record)
        return 0

    if args.command == "set":
        value = _coerce(args.field, args.value)
        if args.kind == "agent":
            record = repo.upsert_agent(args.key, **{args.field: value})
        else:
            record = repo.upsert_task(args.key, **{args.field: value})
        print(f"已更新 {args.kind} {args.key}.{args.field} = {record[args.field]}")
        return 0

    if args.command == "add-agent":
        fields: dict[str, Any] = {
            "role": args.role,
            "goal": args.goal,
            "backstory": args.backstory,
        }
        if args.allow_delegation is not None:
            fields["allow_delegation"] = _coerce(
                "allow_delegation", args.allow_delegation
            )
        if args.verbose is not None:
            fields["verbose"] = _coerce("verbose", args.verbose)
        if args.max_iter is not None:
            fields["max_iter"] = args.max_iter
        repo.upsert_agent(args.key, **fields)
        print(f"已新增 agent: {args.key}")
        return 0

    if args.command == "add-task":
        fields = {
            "description": args.description,
            "expected_output": args.expected_output,
        }
        if args.agent_key:
            fields["agent_key"] = args.agent_key
        if args.context:
            fields["context_keys"] = _coerce("context_keys", args.context)
        repo.upsert_task(args.key, **fields)
        print(f"已新增 task: {args.key}")
        return 0

    if args.command == "rm":
        deleted = (
            repo.delete_agent(args.key)
            if args.kind == "agent"
            else repo.delete_task(args.key)
        )
        if not deleted:
            print(f"未找到 {args.kind}: {args.key}", file=sys.stderr)
            return 1
        print(f"已删除 {args.kind}: {args.key}")
        return 0

    if args.command == "seed":
        inserted = repo.seed_from_yaml(overwrite=args.overwrite)
        print(
            f"种子导入完成：agents +{inserted['agents']}，"
            f"tasks +{inserted['tasks']}"
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
