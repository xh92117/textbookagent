import asyncio
import json

from agent.memory import MemoryConfig, MemoryManager
from agent.tools.memory.memory_get import MemoryGetTool
from agent.tools.memory.memory_search import MemorySearchTool


def test_memory_get_reads_workspace_root_and_textbook_files(tmp_path):
    (tmp_path / "MEMORY.md").write_text("# Memory\nremember textbook workflow", encoding="utf-8")
    status_path = tmp_path / "textbooks" / "tb_demo" / "state" / "status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({"title": "土木工程教材", "status": "idle"}, ensure_ascii=False), encoding="utf-8")

    manager = MemoryManager(MemoryConfig(workspace_root=str(tmp_path)), embedding_provider=None)
    tool = MemoryGetTool(manager)

    root_result = tool.execute({"path": "MEMORY.md"})
    assert root_result.status == "success"
    assert "remember textbook workflow" in root_result.result

    textbook_result = tool.execute({"path": "textbooks/tb_demo/state/status.json"})
    assert textbook_result.status == "success"
    assert "土木工程教材" in textbook_result.result
    manager.close()


def test_memory_sync_indexes_textbook_truth_files(tmp_path):
    status_path = tmp_path / "textbooks" / "tb_demo" / "state" / "status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({"title": "土木工程教材", "phase": "persist_chapter"}, ensure_ascii=False), encoding="utf-8")

    async def run():
        manager = MemoryManager(MemoryConfig(workspace_root=str(tmp_path)), embedding_provider=None)
        await manager.sync(force=True)
        results = await manager.search("土木工程教材", max_results=5, min_score=0.0)
        manager.close()
        return results

    results = asyncio.run(run())
    assert any(result.path == "textbooks/tb_demo/state/status.json" for result in results)


def test_memory_search_tool_works_inside_running_event_loop(tmp_path):
    memory_file = tmp_path / "MEMORY.md"
    memory_file.write_text("长期记忆：土木工程智能体需要读取状态文件。", encoding="utf-8")

    async def run():
        manager = MemoryManager(MemoryConfig(workspace_root=str(tmp_path)), embedding_provider=None)
        await manager.sync(force=True)
        tool = MemorySearchTool(manager)
        result = tool.execute({"query": "土木工程状态文件", "max_results": 5, "min_score": 0.0})
        manager.close()
        return result

    result = asyncio.run(run())
    assert result.status == "success"
    assert "MEMORY.md" in result.result
