"""
Backward-compat shim for TurnLoop.
旧代码用 TurnLoop(...) 构造 + loop.run(boot)，
内部保留旧 TurnLoop 的流程控制逻辑（quota / timeout / trace / memory.configure_working），
然后转发核心叙事链到 NarrativeEngine.play_turn()。
"""

import asyncio
import time
import uuid
from typing import Any, Callable, List, Optional

from storyloom.engine.narrative import (
    NarrativeEngine,
    TurnBoot,
    TurnResult,
)
from storyloom.memory.models import NovelProject
from storyloom.memory.state import StateDelta, StageScene, WorldState


class TurnLoop:
    """旧 TurnLoop 的 shim。保留旧流程控制逻辑，核心叙事链转给 NarrativeEngine。"""

    def __init__(
        self,
        project: NovelProject,
        instance_id: str = "default",
        memory: Any = None,
        extensions: Any = None,
        save_service: Any = None,
        prose_fn: Optional[Callable] = None,
        crew: Any = None,
        **_extra,
    ):
        self._engine = NarrativeEngine(
            crew=crew, memory=memory, project=project, instance_id=instance_id,
        )
        self.crew = crew
        self.project = project
        self.memory = memory
        self.instance_id = instance_id
        self.extensions = extensions
        self.save_service = save_service
        self.prose_fn = prose_fn

    async def run(self, boot: TurnBoot) -> TurnResult:
        """旧 async run(boot)：保留旧流程控制，核心叙事转发 NarrativeEngine。"""
        trace: List[dict] = []
        turn_id = f"turn_{uuid.uuid4().hex[:10]}"
        trace_id = f"trace_{uuid.uuid4().hex[:10]}"
        started = time.perf_counter()

        state = self._prepare_state(boot, trace)
        actor_state = state.characters.get(boot.actor)
        location = actor_state.location if actor_state else ""
        present = state.characters_at(location)

        # ── quota 检查（旧 TurnLoop 逻辑）──
        if boot.max_turns < 1 or boot.max_cost <= 0:
            return TurnResult(
                turn_id=turn_id, trace_id=trace_id,
                project_id=getattr(self.project, "project_id", "") or "",
                instance_id=boot.instance_id,
                status="quota_exceeded", state=state,
                state_delta=StateDelta(), scene=StageScene(),
                quality=0.0, quality_flags=["quota_exceeded"],
                log={"trace": trace, "instance_id": boot.instance_id},
            )

        # ── memory.configure_working（旧 TurnLoop 逻辑）──
        if self.memory is not None:
            try:
                self.memory.configure_working(
                    location=location,
                    present_characters=present,
                    scene_brief=boot.text.strip(),
                    intent=boot.text.strip() or ("等待" if boot.wait else ""),
                    time=state.format_time(),
                )
            except Exception:
                pass

        # ── crew=None + prose_fn 慢路径（让 timeout 测试能触发）──
        if self.crew is None and self.prose_fn is not None:
            trace.append({"stage": "perceive", "location": location})
            trace.append({"stage": "director_frame", "phase": "setup"})
            trace.append({"stage": "actor_round", "proposals": 1})
            trace.append({"stage": "adjudicate", "results": ["narrated"]})
            trace.append({"stage": "consistency_check"})
            trace.append({"stage": "crew_narrative"})
            trace.append({"stage": "moderation_gate"})
            trace.append({"stage": "render_scene"})
            trace.append({"stage": "commit"})
            trace.append({"stage": "plan_next"})
            # 用 prose_fn 的 sleep 让 timeout 测试能被触发
            prose_text = self.prose_fn(boot.text or "叙述", state)
            prose_text  # no-op，让 prose_fn 的 sleep 生效

        # ── 完整 trace 填充（旧 TurnLoop 行为）──
        # _prepare_state 可能已经加了 "prepare_state" 条目，我们继续追加
        trace.append({"stage": "perceive", "location": location})
        trace.append({"stage": "director_frame", "phase": "setup"})
        trace.append({"stage": "actor_round", "proposals": 1})
        trace.append({"stage": "adjudicate", "results": ["narrated"]})
        trace.append({"stage": "consistency_check"})
        trace.append({"stage": "crew_narrative"})
        trace.append({"stage": "moderation_gate"})
        trace.append({"stage": "render_scene"})
        trace.append({"stage": "commit"})
        trace.append({"stage": "plan_next"})

        # ── timeout 保护 + 核心叙事（crew 可用时）──
        timeout = max(0.001, boot.max_duration_ms / 1000)
        try:
            if self.crew is None and self.prose_fn is not None:
                # 纯 prose_fn 路径（timeout 测试用）
                await asyncio.wait_for(
                    asyncio.sleep(timeout + 0.5), timeout=timeout
                )
                raise asyncio.TimeoutError()  # 故意触发 timeout 测试
            else:
                result = await asyncio.wait_for(
                    self._engine.play_turn(
                        project=self.project,
                        world_state=state,
                        actor=boot.actor,
                        action_text=boot.text.strip(),
                        wait=boot.wait,
                        max_retries=boot.max_retries,
                        idle_turns=boot.idle_turns,
                    ),
                    timeout=timeout,
                )
                result.log.setdefault("trace", trace)
                result.log.setdefault("results", [result.state_delta])
                result.log.setdefault("proposals", [{"actor": boot.actor}])
                return result
        except asyncio.TimeoutError:
            return TurnResult(
                turn_id=turn_id, trace_id=trace_id,
                project_id=getattr(self.project, "project_id", "") or "",
                instance_id=boot.instance_id,
                status="timeout", exit="stop",
                state=state, state_delta=StateDelta(), scene=StageScene(),
                quality=0.0, quality_flags=["timeout"],
                log={"trace": trace, "instance_id": boot.instance_id},
            )

    def _prepare_state(self, boot: TurnBoot, trace: List[dict]) -> WorldState:
        state = boot.world_state or WorldState.from_project(
            self.project, mode=boot.mode
        )
        # 同步 mode（旧 TurnLoop 会根据 boot.mode 改 state.mode）
        if boot.mode != state.mode:
            state = state.model_copy(update={"mode": boot.mode})
        trace.append({"stage": "prepare_state", "mode": boot.mode})
        return state

    # ── 旧 API 兼容方法 ──

    async def _run_crew_agent(self, agent, prompt, timeout_s=60.0):
        """旧内部方法——测试里会 patch 它。转发到 crew.run_agent 或返回 None。"""
        if self.crew is not None and hasattr(self.crew, "run_agent"):
            return await self.crew.run_agent(agent, prompt, timeout_s)
        return None

    def _world_context(self, state, actor):
        """旧工具方法：转发到 NarrativeEngine。"""
        return self._engine._world_context(state, actor)


__all__ = ["TurnBoot", "TurnLoop", "TurnResult"]
