"""API 路由测试共用的运行时夹具。"""

import pytest

from storyloom.db import get_repository, reset_engines, reset_repositories
from storyloom.memory.checkpoint import SaveService


def fake_prose(prompt: str, state) -> str:
    """伪装 prose 模型：原样返回 prompt 里已裁决的「事实」，不访问网络。"""
    for line in prompt.splitlines():
        if line.startswith("事实："):
            return line[len("事实："):]
    return ""


async def fake_crew_run(self, agent, prompt, timeout_s=60.0):
    """伪装统一 JSON Agent：裁决放行、正文为空、无一致性问题。"""
    return '{"decision": "allow", "prose": "", "choices": [], "issues": []}'


@pytest.fixture
def apis(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STORYLOOM_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}"
    )
    reset_repositories()
    reset_engines()

    from storyloom.api.engine import engine
    from storyloom.api.routers import extensions, game, memory
    from storyloom.crews.scene_crew.crew import SceneCrew

    # 游戏回合的叙述润色改为假模型返回，避免真实 LLM 调用导致超时
    monkeypatch.setattr(engine, "_game_prose_fn", fake_prose)
    # 记忆压缩同样走确定性兜底
    monkeypatch.setattr(
        engine, "_memory_compress_fn",
        lambda project_id, prompt, scope=None: "",
    )
    # Crew 叙事增强层整体关闭（一致性 / 意外 / 伏笔 / 导演 / 润色）
    # NarrativeEngine._kickoff 优先走 crew.run_agent，直接 patch SceneCrew 即可
    monkeypatch.setattr(SceneCrew, "run_agent", fake_crew_run)
    engine._project_runtime.clear()
    engine.memories.clear()
    engine.game_states.clear()
    engine.last_turns.clear()
    engine.save_service = SaveService(root=str(tmp_path / "saves"))

    repo = get_repository()
    repo.create_project("api_demo", "API Demo", "film_narrative")
    repo.upsert_character(
        "api_demo", "玩家", "primary", "冷静", "查明真相", "秘密身份"
    )
    repo.upsert_character(
        "api_demo", "侍卫长", "secondary", "忠诚", "保护", "认识父亲"
    )
    repo.upsert_location("api_demo", "旅店", "潮湿")
    repo.upsert_location("api_demo", "码头", "有雾")

    yield game, memory, extensions

    reset_repositories()
    reset_engines()
