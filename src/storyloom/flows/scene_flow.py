"""
Backward-compat shim for SceneGenerationFlow.
旧代码用 SceneGenerationFlow(...) 构造 + flow.kickoff()，
现在全部转发到 NarrativeEngine.generate_scene()。
"""

from typing import Any, List, Optional

from storyloom.engine.narrative import (
    NarrativeEngine,
    SceneResult,
    advance_scene_counters,
    apply_foreshadow_ops,
    parse_json_block,
)
from storyloom.memory.models import NovelProject


class SceneGenerationFlow:
    """旧 SceneGenerationFlow 的 shim：把旧 API 转发到 NarrativeEngine。"""

    def __init__(
        self,
        project: Optional[NovelProject] = None,
        memory: Any = None,
        crew: Any = None,
        scene_brief: str = "",
        present_characters: Optional[List[str]] = None,
        is_regenerate: bool = False,
        **_extra,
    ):
        self._engine = NarrativeEngine(crew=crew, memory=memory, project=project)
        self._project = project
        self._memory = memory
        self._crew = crew
        self._scene_brief = scene_brief
        self._present_chars = present_characters or []
        self._is_regenerate = is_regenerate
        self.render_mode = None

    def kickoff(self) -> str:
        """同步 kickoff（旧 CrewAI Flow 风格）"""
        import asyncio
        result = asyncio.run(
            self._engine.generate_scene(
                project=self._project,
                scene_brief=self._scene_brief,
                present_chars=self._present_chars,
                is_regenerate=self._is_regenerate,
            )
        )
        return result.prose

    @property
    def state(self):
        class _State:
            consistency_report = None
            retry_count = 0
            project = self._project
            memory = self._memory
            scene_brief = self._scene_brief
            director_intent = ""
            actor_log = ""
            surprise_proposal = ""
            foreshadowing_ops = ""
        return _State()

    # ── 旧 step 方法（测试会直接访问）──

    def gather_rag_context(self, *_args):
        if self._memory is not None:
            return self._memory.retrieval_block(self._scene_brief or "")
        return ""

    def update_memory_and_foreshadowings(self, *_args):
        return None

    def propose_surprise(self, *_args):
        return None

    def propose_foreshadowing_ops(self, *_args):
        return None

    def plan_scene(self, *_args):
        return None

    def run_actor_interaction(self, *_args):
        return ""

    def check_consistency(self, *_args):
        return None

    def write_prose(self, *_args):
        return ""


# 旧 scene_flow.py 里独立的函数
__all__ = [
    "SceneGenerationFlow",
    "advance_scene_counters",
    "apply_foreshadow_ops",
    "parse_json_block",
]
