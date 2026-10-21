"""记忆层单元测试（无需 API Key）"""

from memory.manager import CoreMemory, SimpleRAGMemory


def test_core_memory_prompt_block():
    memory = CoreMemory(
        current_location="雾港旅店",
        characters_present=["林夏", "阿泽"],
        recent_scene_summaries=["场景一", "场景二", "场景三", "场景四"],
    )
    block = memory.as_prompt_block()

    assert "雾港旅店" in block
    assert "林夏, 阿泽" in block
    # 只保留最近 3 条摘要
    assert "场景一" not in block
    assert "场景二" in block
    assert "场景四" in block


def test_add_scene_summary_truncates():
    memory = CoreMemory()
    memory.add_scene_summary("甲" * 500, limit=200)
    assert len(memory.recent_scene_summaries) == 1
    assert memory.recent_scene_summaries[0] == "甲" * 200 + "..."


def test_rag_fallback_returns_matching_docs():
    rag = SimpleRAGMemory("test_project")
    # 未安装 chromadb 时会走内存关键词检索
    if rag.collection is not None:
        return

    rag.add("d1", "雾港常年被海雾笼罩", {"type": "lore"})
    rag.add("d2", "旅店墙上挂着航海图", {"type": "lore"})
    results = rag.query("航海图", n_results=2)

    assert results
    assert any("航海图" in r for r in results)
