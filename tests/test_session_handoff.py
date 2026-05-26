import json

from agent.memory.graph import MemoryGraphService
from agent.memory.handoff import HandoffService, update_session_handoff_after_persist
from agent.prompt.builder import PromptBuilder
from agent.protocol.message_utils import build_context_state_board
from agent.tools.memory.memory_search import MemorySearchTool


class _EmptyMemoryManager:
    async def search(self, **kwargs):
        return []


def test_session_handoff_writes_compact_refs_and_redacts_secrets(tmp_path):
    service = HandoffService(str(tmp_path / "system"))
    path = service.update_from_messages(
        "session-a",
        [
            {"role": "user", "content": "继续优化 MemoryGraph fallback，下一步补 README。"},
            {
                "role": "assistant",
                "content": "已修改 agent/tools/memory/memory_search.py，commit aa5d199，pytest -q => 455 passed，token=sk-secret123456789",
            },
        ],
    )

    text = path.read_text(encoding="utf-8")
    assert "Current Goal" in text
    assert "继续优化 MemoryGraph fallback" in text
    assert "agent/tools/memory/memory_search.py" in text
    assert "commit: aa5d199" in text
    assert "pytest -q => 455 passed" in text
    assert "sk-secret" not in text
    assert len(text) < 1600


def test_session_handoff_is_indexed_by_memory_graph(tmp_path):
    service = HandoffService(str(tmp_path / "system"))
    service.update_from_messages(
        "session-a",
        [
            {"role": "user", "content": "继续上次 MemoryGraph fallback 工作"},
            {"role": "assistant", "content": "下一步读取 tests/test_memory_graph.py 并运行 pytest tests/test_memory_graph.py -q"},
        ],
    )

    graph = MemoryGraphService(str(tmp_path / "system"))
    graph.sync_changed()
    context = graph.context("继续上次")

    assert "session:session-a:handoff" in context["matched_entities"]
    assert context["recommended_reads"][0]["source_path"].endswith("memory/sessions/session-a/handoff.md")
    node = context["authoritative_nodes"][0]
    assert node["authority"] == "session_handoff"
    assert node["temporal_scope"] == "active"
    graph.close()


def test_memory_search_falls_back_to_session_handoff_when_old_index_is_empty(tmp_path):
    service = HandoffService(str(tmp_path / "system"))
    service.update_from_messages(
        "session-a",
        [
            {"role": "user", "content": "继续上次 MemoryGraph fallback 工作"},
            {"role": "assistant", "content": "下一步读取 agent/memory/graph.py"},
        ],
    )

    tool = MemorySearchTool(_EmptyMemoryManager(), system_root=str(tmp_path / "system"))
    result = tool.execute({"query": "继续上次", "graph_mode": "compact"})

    assert result.status == "success"
    assert "MemoryGraph fallback" in result.result
    assert "memory/sessions/session-a/handoff.md" in result.result
    assert "session:session-a:handoff" in result.result


def test_handoff_update_marks_memory_graph_dirty(tmp_path):
    system_root = str(tmp_path / "system")
    graph = MemoryGraphService(system_root)
    graph.sync_changed()
    assert graph.status()["graph_dirty"] is False
    graph.close()

    path = update_session_handoff_after_persist(
        system_root,
        "session-a",
        [{"role": "user", "content": "继续上次 handoff 测试"}],
    )

    graph = MemoryGraphService(system_root)
    status = graph.status()
    assert path is not None
    assert status["graph_dirty"] is True
    assert status["dirty_source_count"] == 1
    assert status["dirty_entity_count"] == 1
    graph.close()


def test_prompt_builder_injects_budgeted_session_handoff(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "config", config.Config({
        "knowledge": False,
        "agent_prompt_section_budgets": {"session_handoff": 520},
    }))
    handoff = HandoffService(str(tmp_path / "system")).update_from_messages(
        "session-a",
        [
            {"role": "user", "content": "继续上次 MemoryGraph fallback 工作，下一步补 README 与测试。"},
            {"role": "assistant", "content": "已修改 agent/tools/memory/memory_search.py；commit aa5d199；pytest -q => 455 passed。"},
        ],
    )
    text = handoff.read_text(encoding="utf-8")
    builder = PromptBuilder(workspace_dir=str(tmp_path), language="zh")

    result = builder.build_with_diagnostics(
        tools=[],
        runtime_info={"session_handoff": text},
        skill_filter=[],
    )
    sections = {item["name"]: item for item in result.diagnostics["sections"]}

    assert "## Session Handoff" in result.prompt
    assert "Current Goal" in result.prompt
    assert "agent/tools/memory/memory_search.py" in result.prompt
    assert sections["session_handoff"]["chars"] <= 520


def test_session_handoff_sets_expiry_and_read_hides_expired(tmp_path):
    service = HandoffService(str(tmp_path / "system"), ttl_hours=24)
    service.update_from_messages(
        "session-a",
        [{"role": "user", "content": "continue handoff expiry test"}],
        now="2026-05-26T10:00:00",
    )

    active = service.read_handoff("session-a", now="2026-05-27T09:59:00")
    expired = service.read_handoff("session-a", now="2026-05-27T10:01:00")

    assert "Expires At\n2026-05-27T10:00:00" in active["content"]
    assert expired == {}


def test_archive_expired_handoffs_moves_file_out_of_active_sessions(tmp_path):
    service = HandoffService(str(tmp_path / "system"), ttl_hours=1)
    active_path = service.update_from_messages(
        "session-a",
        [{"role": "user", "content": "continue archive test"}],
        now="2026-05-26T10:00:00",
    )

    result = service.archive_expired(now="2026-05-26T11:30:00")

    assert result["archived_count"] == 1
    assert not active_path.exists()
    assert result["archived"][0].endswith("memory/sessions_archive/session-a/handoff_20260526T100000.md")
    assert service.read_handoff("session-a", now="2026-05-26T11:30:00") == {}


def test_archived_handoff_is_not_returned_by_active_graph_fallback(tmp_path):
    service = HandoffService(str(tmp_path / "system"), ttl_hours=1)
    service.update_from_messages(
        "session-a",
        [{"role": "user", "content": "continue archived graph test"}],
        now="2026-05-26T10:00:00",
    )
    service.archive_expired(now="2026-05-26T11:30:00")

    graph = MemoryGraphService(str(tmp_path / "system"))
    graph.sync_changed()
    context = graph.context("continue archived graph test")
    graph.close()

    assert "session:session-a:handoff" not in context["matched_entities"]


def test_handoff_intent_prioritizes_session_handoff_in_memory_search(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("继续上次 means check long-term memory first.", encoding="utf-8")
    HandoffService(str(tmp_path / "system")).update_from_messages(
        "session-a",
        [{"role": "user", "content": "继续上次 handoff priority test"}],
    )

    tool = MemorySearchTool(_EmptyMemoryManager(), system_root=str(tmp_path / "system"))
    result = tool.execute({"query": "继续上次", "graph_mode": "compact"})

    assert result.status == "success"
    assert result.result.index("memory/sessions/session-a/handoff.md") < result.result.index("memory/MEMORY.md")


def test_context_state_board_uses_handoff_pointer_when_active_handoff_exists():
    turn = {
        "session_handoff": {
            "path": "memory/sessions/session-a/handoff.md",
            "entity_key": "session:session-a:handoff",
        },
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "继续处理工具密集任务"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "read", "input": {"path": "agent/memory/graph.py"}},
                    {"type": "text", "text": "已读取文件，下一步修改。"},
                ],
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "large result"}]},
        ],
    }

    board = build_context_state_board([turn])

    assert "Session handoff pointer" in board
    assert "memory/sessions/session-a/handoff.md" in board
    assert "Structured task checkpoint" not in board
