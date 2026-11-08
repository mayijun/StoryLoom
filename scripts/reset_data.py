#!/usr/bin/env python3
"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

一键清空 StoryLoom 的本地数据，回到「从零开始」的测试状态。

会清理：
- SQLite 数据库（默认 data/storyloom.db，遵循 STORYLOOM_DATABASE_URL）
- 存档文件（默认 data/saves/，遵循 STORYLOOM_SAVE_DIR）
- ChromaDB 向量库（memory_store/）

用法：
    uv run python scripts/reset_data.py          # 交互确认后清空
    uv run python scripts/reset_data.py --yes    # 跳过确认（适合脚本/CI）
    uv run python scripts/reset_data.py --dry-run  # 只查看将删除的内容

注意：执行前请先停止后端（python app.py），否则数据库/向量库可能仍被占用。
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    """尽量加载项目根目录 .env，保证读到 STORYLOOM_* 配置"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env")


def _database_target() -> tuple[Path | None, str]:
    """返回 (待删除的 SQLite 文件, 说明)；非 SQLite 数据库返回 None"""
    url = os.getenv("STORYLOOM_DATABASE_URL", "").strip()
    if not url:
        return PROJECT_ROOT / "data" / "storyloom.db", "默认 SQLite"
    if not url.startswith("sqlite"):
        return None, f"非 SQLite 数据库，跳过（{url}）"
    raw = url.replace("sqlite:///", "").replace("sqlite://", "", 1)
    path = Path(raw)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path, f"STORYLOOM_DATABASE_URL={url}"


def _save_dir() -> Path:
    raw = os.getenv("STORYLOOM_SAVE_DIR", "").strip()
    return Path(raw) if raw else PROJECT_ROOT / "data" / "saves"


def _memory_store_dir() -> Path:
    return PROJECT_ROOT / "memory_store"


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _describe(label: str, path: Path, note: str = "") -> bool:
    """打印目标信息，返回是否存在"""
    exists = path.exists()
    suffix = f"  [{note}]" if note else ""
    if exists:
        print(f"  - {label}: {path} ({_human_size(_path_size(path))}){suffix}")
    else:
        print(f"  - {label}: {path} (不存在，跳过){suffix}")
    return exists


def _remove_database(path: Path) -> None:
    # 连同 SQLite 的 WAL / SHM 附属文件一起删除
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.exists():
            candidate.unlink()


def _clear_directory(path: Path) -> None:
    """清空目录内容但保留目录本身"""
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="清空 StoryLoom 本地数据（数据库 / 存档 / 向量库）",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="跳过确认")
    parser.add_argument(
        "--dry-run", action="store_true", help="只列出将删除的内容，不实际删除"
    )
    args = parser.parse_args(argv)

    _load_env()

    db_path, db_note = _database_target()
    save_dir = _save_dir()
    memory_dir = _memory_store_dir()

    print("将要清理以下数据：")
    if db_path is None:
        print(f"  - 数据库: {db_note}")
    else:
        _describe("数据库", db_path, db_note)
    _describe("存档", save_dir)
    _describe("向量库", memory_dir)

    if args.dry_run:
        print("\n[dry-run] 未做任何修改。")
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            print("\n非交互环境请加 --yes 确认清空。", file=sys.stderr)
            return 1
        answer = input("\n确认清空以上全部数据？此操作不可恢复 [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("已取消。")
            return 1

    if db_path is not None:
        _remove_database(db_path)
    _clear_directory(save_dir)
    if memory_dir.exists():
        shutil.rmtree(memory_dir)

    print("\n✅ 已清空。重新启动后端（python app.py）即可从零开始。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
