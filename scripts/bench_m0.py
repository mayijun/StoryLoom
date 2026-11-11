"""M0 性能基线压测。

用法：
    uv run python scripts/bench_m0.py
    uv run python scripts/bench_m0.py --turns 50 --concurrency 100 --docs 1000

说明：
- 「单 turn」与「并发」使用确定性链路（GM + 渲染），不含真实 LLM 调用；
  §2.6 的 10s 目标是含 LLM 的上限，这里给出可回归的下限基线；
- 记忆检索在临时 SQLite 中写入 1k 条 archive 记录后测 P95；
- 冷启动通过子进程测量 `import storyloom.api.main` 的耗时。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def measure_cold_start_ms() -> float:
    code = (
        "import time;t=time.perf_counter();"
        "import storyloom.api.main;"
        "print(round((time.perf_counter()-t)*1000,1))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    proc.check_returncode()
    return float(proc.stdout.strip().splitlines()[-1])


def build_project():
    from storyloom.models import CharacterAsset, LocationAsset, NovelProject

    return NovelProject(
        project_id="bench",
        title="压测项目",
        style="冷硬悬疑",
        characters=[
            CharacterAsset(
                name="玩家",
                importance_tier="primary",
                persona="冷静、寡言",
                motivation="查明真相",
            ),
            CharacterAsset(
                name="旅店老板",
                importance_tier="secondary",
                persona="多疑",
                motivation="守住旅店",
            ),
        ],
        locations=[
            LocationAsset(name="旅店", description="潮湿的木楼"),
            LocationAsset(name="码头", description="终年有雾"),
        ],
    )


async def bench_turns(rounds: int) -> list[float]:
    from storyloom.flows.turn_flow import TurnBoot, TurnLoop
    from storyloom.world.state import WorldState

    project = build_project()
    state = WorldState.from_project(project)
    loop = TurnLoop(project)
    inputs = ["观察四周", "前往码头", "等待", "和旅店老板交谈"]
    latencies: list[float] = []

    for index in range(rounds):
        boot = TurnBoot(
            project_id="bench",
            instance_id="bench",
            text=inputs[index % len(inputs)],
            world_state=state,
        )
        started = time.perf_counter()
        result = await loop.run(boot)
        latencies.append((time.perf_counter() - started) * 1000)
        assert result.status == "ok", result.status
        state = result.state

    return latencies


async def bench_concurrency(count: int) -> tuple[int, float]:
    from storyloom.flows.turn_flow import TurnBoot, TurnLoop
    from storyloom.world.state import WorldState

    async def one(index: int) -> bool:
        project = build_project()
        loop = TurnLoop(project)
        boot = TurnBoot(
            project_id="bench",
            instance_id=f"c{index}",
            text="观察四周",
            world_state=WorldState.from_project(project),
        )
        result = await loop.run(boot)
        return result.status == "ok"

    started = time.perf_counter()
    results = await asyncio.gather(*(one(i) for i in range(count)))
    elapsed = (time.perf_counter() - started) * 1000
    return sum(1 for ok in results if ok), elapsed


def bench_memory(docs: int, rounds: int) -> float:
    from storyloom.db.repository import CrewConfigRepository
    from storyloom.memory.core import LayeredMemory

    with tempfile.TemporaryDirectory() as tmp:
        repo = CrewConfigRepository(f"sqlite:///{tmp}/bench.db")
        repo.create_all()
        memory = LayeredMemory("bench", repo=repo)
        for index in range(docs):
            if index % 5 == 0:
                text = f"第{index}份航海图记录：雾港码头与灯塔的暗号"
            else:
                text = f"背景条目 {index}：城镇、河流与日常琐事"
            memory.add_archive_item(
                f"doc:{index}", text, scene_index=index
            )

        queries = ["航海图", "灯塔", "码头", "第500份"]
        latencies: list[float] = []
        for index in range(rounds):
            started = time.perf_counter()
            memory.retrieve(
                queries[index % len(queries)], current_scene=docs
            )
            latencies.append((time.perf_counter() - started) * 1000)

        repo.engine.dispose()
        return p95(latencies)


def main() -> int:
    parser = argparse.ArgumentParser(description="M0 性能基线压测")
    parser.add_argument("--turns", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--docs", type=int, default=1000)
    parser.add_argument("--memory-rounds", type=int, default=30)
    args = parser.parse_args()

    cold = measure_cold_start_ms()
    latencies = asyncio.run(bench_turns(args.turns))
    ok_count, concurrent_ms = asyncio.run(
        bench_concurrency(args.concurrency)
    )
    memory_p95 = bench_memory(args.docs, args.memory_rounds)

    rows = [
        ("冷启动（import api.main）", f"{cold:.1f}ms", "≤ 3000ms", cold <= 3000),
        (
            f"单 turn P95（确定性，{args.turns} 次）",
            f"{p95(latencies):.1f}ms",
            "≤ 10000ms（含 LLM）",
            p95(latencies) <= 10000,
        ),
        (
            f"并发 {args.concurrency} turn",
            f"{ok_count}/{args.concurrency} 成功，{concurrent_ms:.1f}ms",
            "≥ 100",
            ok_count >= args.concurrency,
        ),
        (
            f"记忆检索 P95（fts，{args.docs} 条）",
            f"{memory_p95:.1f}ms",
            "≤ 200ms",
            memory_p95 <= 200,
        ),
    ]

    print("\nM0 性能基线（本机）")
    print("-" * 68)
    for name, value, target, passed in rows:
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {name}: {value}（目标 {target}）")
    print("-" * 68)
    print("注：未配置 LLM Key，单 turn 仅覆盖确定性链路。")

    return 0 if all(row[3] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
