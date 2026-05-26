import json

from agent.memory.graph import MemoryGraphService
from agent.memory import MemoryConfig, MemoryManager
from agent.memory.storage import SearchResult
from agent.tools.memory.memory_graph import MemoryGraphContextTool, MemoryGraphStatusTool
from agent.tools.memory.memory_search import MemorySearchTool


def test_memory_graph_sync_is_idempotent_and_indexes_sources(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "user_profile.md").write_text("User prefers concise progress updates.", encoding="utf-8")

    service = MemoryGraphService(str(tmp_path / "system"))
    first = service.sync_changed()
    second = service.sync_changed()
    status = service.status()

    assert first["indexed"] >= 1
    assert second["indexed"] == 0
    assert status["source_count"] == 1
    assert status["node_count"] == 1
    assert status["edge_count"] == 0

def test_memory_graph_default_sync_indexes_all_changed_sources(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    for idx in range(250):
        (memory_dir / f"note_{idx:03d}.md").write_text(
            f"Memory note {idx}", encoding="utf-8"
        )

    service = MemoryGraphService(str(tmp_path / "system"))
    result = service.sync_changed()
    status = service.status()

    assert result["indexed"] == 250
    assert status["source_count"] == 250
    assert status["graph_dirty"] is False


def test_memory_graph_updates_modified_source_without_duplicate_nodes(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    profile = memory_dir / "user_profile.md"
    profile.write_text("User prefers concise updates.", encoding="utf-8")
    service = MemoryGraphService(str(tmp_path / "system"))
    service.sync_changed()
    before = service.status()["node_count"]

    profile.write_text("User prefers detailed implementation notes.", encoding="utf-8")
    service.sync_changed()
    context = service.context("detailed implementation")

    assert service.status()["node_count"] == before
    assert context["matched_entities"]
    assert "detailed implementation" in context["authoritative_nodes"][0]["summary"]


def test_memory_graph_marks_deleted_sources_hidden(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    profile = memory_dir / "user_profile.md"
    profile.write_text("User prefers concise updates.", encoding="utf-8")
    service = MemoryGraphService(str(tmp_path / "system"))
    service.sync_changed()

    profile.unlink()
    service.sync_changed()
    context = service.context("concise updates")

    assert context["matched_entities"] == []
    assert service.status()["deleted_source_count"] == 1


def test_memory_graph_prefers_current_textbook_state_over_snapshot(tmp_path):
    project = tmp_path / "workspace"
    current = project / "textbooks" / "tb_demo" / "state"
    snapshot = project / "textbooks" / "tb_demo" / "snapshots" / "s1" / "state"
    current.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    (current / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")
    (snapshot / "status.json").write_text(json.dumps({"title": "Old Book", "status": "outline"}), encoding="utf-8")

    service = MemoryGraphService(str(tmp_path / "system"), project_workspace=str(project))
    service.sync_changed()
    context = service.context("tb_demo status")

    assert context["authoritative_nodes"][0]["source_path"].endswith("textbooks/tb_demo/state/status.json")
    assert context["historical_nodes"]
    assert context["conflicts"]
    assert context["recommended_reads"][0]["source_path"].endswith("textbooks/tb_demo/state/status.json")


def test_memory_graph_tools_return_short_navigation(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "user_profile.md").write_text("User prefers concise progress updates.", encoding="utf-8")

    context_tool = MemoryGraphContextTool(str(tmp_path / "system"))
    status_tool = MemoryGraphStatusTool(str(tmp_path / "system"))
    context = context_tool.execute({"query": "concise progress"})
    status = status_tool.execute({})

    assert context.status == "success"
    assert "MemoryGraph context" in context.result
    assert "Recommended reads" in context.result
    assert len(context.result) < 2500
    assert status.status == "success"
    assert "node_count" in status.result


class _FakeMemoryManager:
    async def search(self, **kwargs):
        return [
            SearchResult(
                path="memory/user_profile.md",
                start_line=1,
                end_line=1,
                score=0.8,
                snippet="User prefers concise progress updates.",
                source="memory",
                metadata={"authority": "user_profile", "temporal_scope": "evergreen"},
            )
        ]


class _PlannerAwareMemoryManager:
    def __init__(self):
        self.queries = []

    async def search(self, **kwargs):
        query = kwargs.get("query", "")
        self.queries.append(query)
        if "textbook:tb_demo:state:status.json" not in query:
            return [
                SearchResult(
                    path="textbooks/tb_demo/snapshots/s1/state/status.json",
                    start_line=1,
                    end_line=1,
                    score=0.9,
                    snippet="Old Book outline",
                    source="textbook",
                    metadata={"authority": "snapshot", "temporal_scope": "historical"},
                )
            ]
        return [
            SearchResult(
                path="textbooks/tb_demo/snapshots/s1/state/status.json",
                start_line=1,
                end_line=1,
                score=0.9,
                snippet="Old Book outline",
                source="textbook",
                metadata={"authority": "snapshot", "temporal_scope": "historical"},
            ),
            SearchResult(
                path="textbooks/tb_demo/state/status.json",
                start_line=1,
                end_line=1,
                score=0.5,
                snippet="Current Book writing",
                source="textbook",
                metadata={"authority": "truth_file", "temporal_scope": "current"},
            ),
        ]


class _EmptyMemoryManager:
    async def search(self, **kwargs):
        return []


def test_memory_search_includes_graph_navigation_when_available(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "user_profile.md").write_text("User prefers concise progress updates.", encoding="utf-8")

    tool = MemorySearchTool(_FakeMemoryManager(), system_root=str(tmp_path / "system"))
    result = tool.execute({"query": "concise progress", "graph_mode": "full"})

    assert result.status == "success"
    assert "Graph navigation:" in result.result
    assert "authoritative" in result.result.lower()


def test_memory_search_defaults_to_compact_graph_output(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "user_profile.md").write_text("User prefers concise progress updates.", encoding="utf-8")

    tool = MemorySearchTool(_FakeMemoryManager(), system_root=str(tmp_path / "system"))
    result = tool.execute({"query": "concise progress"})

    assert result.status == "success"
    assert "Graph planner:" in result.result
    assert "Graph navigation:" not in result.result


def test_memory_search_degrades_when_graph_fails():
    tool = MemorySearchTool(_FakeMemoryManager(), system_root="Z:/missing/<>")
    result = tool.execute({"query": "concise progress"})

    assert result.status == "success"
    assert "Found 1 relevant memories" in result.result


def test_memory_search_uses_graph_as_query_planner_before_old_index(tmp_path):
    project = tmp_path / "workspace"
    current = project / "textbooks" / "tb_demo" / "state"
    snapshot = project / "textbooks" / "tb_demo" / "snapshots" / "s1" / "state"
    current.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    (current / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")
    (snapshot / "status.json").write_text(json.dumps({"title": "Old Book", "status": "outline"}), encoding="utf-8")

    manager = _PlannerAwareMemoryManager()
    manager.config = type("Config", (), {"get_project_workspace": lambda self: project})()
    tool = MemorySearchTool(manager, system_root=str(tmp_path / "system"))
    result = tool.execute({"query": "tb_demo status", "max_results": 2})

    assert result.status == "success"
    assert "textbook:tb_demo:state:status.json" in manager.queries[0]
    assert result.result.index("textbooks/tb_demo/state/status.json") < result.result.index("textbooks/tb_demo/snapshots/s1/state/status.json")
    assert "Graph planner:" in result.result


def test_memory_search_does_not_rewrite_old_index_query_when_graph_misses(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    manager = _PlannerAwareMemoryManager()
    tool = MemorySearchTool(manager, system_root=str(tmp_path / "system"))
    result = tool.execute({"query": "unknown preference"})

    assert result.status == "success"
    assert manager.queries == ["unknown preference"]


def test_memory_search_returns_graph_fallback_when_old_index_has_no_results(tmp_path):
    project = tmp_path / "workspace"
    current = project / "textbooks" / "tb_demo" / "state"
    current.mkdir(parents=True)
    (current / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")

    manager = _EmptyMemoryManager()
    manager.config = type("Config", (), {"get_project_workspace": lambda self: project})()
    tool = MemorySearchTool(manager, system_root=str(tmp_path / "system"))
    result = tool.execute({"query": "tb_demo status"})

    assert result.status == "success"
    assert "No old-index result" in result.result
    assert "Graph recommended reads:" in result.result
    assert "textbooks/tb_demo/state/status.json" in result.result


def test_memory_search_compact_fallback_limits_recommended_reads(tmp_path):
    project = tmp_path / "workspace"
    state = project / "textbooks" / "tb_demo" / "state"
    chapters = project / "textbooks" / "tb_demo" / "chapters"
    state.mkdir(parents=True)
    chapters.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"title": "Demo", "status": "writing"}), encoding="utf-8")
    for index in range(1, 6):
        (chapters / f"chapter_{index:03}.md").write_text(
            f"# Chapter {index}\n\nThis tb_demo status chapter covers graph fallback compression.\n",
            encoding="utf-8",
        )

    manager = _EmptyMemoryManager()
    manager.config = type("Config", (), {"get_project_workspace": lambda self: project})()
    tool = MemorySearchTool(manager, system_root=str(tmp_path / "system"))
    result = tool.execute({"query": "tb_demo status", "graph_mode": "compact"})

    assert result.status == "success"
    assert result.result.count("- textbooks/") == 3
    assert "Graph notes:" not in result.result
    assert len(result.result) < 420


def test_memory_search_full_fallback_keeps_more_graph_explanation(tmp_path):
    project = tmp_path / "workspace"
    state = project / "textbooks" / "tb_demo" / "state"
    chapters = project / "textbooks" / "tb_demo" / "chapters"
    state.mkdir(parents=True)
    chapters.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"title": "Demo", "status": "writing"}), encoding="utf-8")
    for index in range(1, 6):
        (chapters / f"chapter_{index:03}.md").write_text(
            f"# Chapter {index}\n\nThis tb_demo status chapter covers graph fallback explanation.\n",
            encoding="utf-8",
        )

    manager = _EmptyMemoryManager()
    manager.config = type("Config", (), {"get_project_workspace": lambda self: project})()
    tool = MemorySearchTool(manager, system_root=str(tmp_path / "system"))
    compact = tool.execute({"query": "tb_demo status", "graph_mode": "compact"})
    full = tool.execute({"query": "tb_demo status", "graph_mode": "full"})

    assert full.status == "success"
    assert full.result.count("- textbooks/") > compact.result.count("- textbooks/")
    assert len(compact.result) < len(full.result) * 0.8


def test_memory_search_reuses_graph_plan_cache_until_dirty(tmp_path, monkeypatch):
    project = tmp_path / "workspace"
    current = project / "textbooks" / "tb_demo" / "state"
    current.mkdir(parents=True)
    (current / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")

    manager = _PlannerAwareMemoryManager()
    manager.config = type("Config", (), {"get_project_workspace": lambda self: project})()
    tool = MemorySearchTool(manager, system_root=str(tmp_path / "system"))

    calls = {"count": 0}
    original_context = MemoryGraphService.context

    def counted_context(self, *args, **kwargs):
        calls["count"] += 1
        return original_context(self, *args, **kwargs)

    monkeypatch.setattr(MemoryGraphService, "context", counted_context)
    tool.execute({"query": "tb_demo status", "max_results": 2})
    tool.execute({"query": "tb_demo status", "max_results": 2})

    assert calls["count"] == 1

    service = MemoryGraphService(str(tmp_path / "system"), project_workspace=str(project))
    service.mark_dirty("test update")
    service.close()
    (current / "status.json").write_text(json.dumps({"title": "Current Book", "status": "reviewing"}), encoding="utf-8")

    tool.execute({"query": "tb_demo status", "max_results": 2})
    assert calls["count"] == 2


def test_memory_manager_mark_dirty_marks_memory_graph_dirty(tmp_path):
    manager = MemoryManager(MemoryConfig(workspace_root=str(tmp_path / "system")), embedding_provider=None)
    service = MemoryGraphService(str(tmp_path / "system"))
    service.sync_changed()
    assert service.status()["graph_dirty"] is False
    service.close()

    manager.mark_dirty()

    service = MemoryGraphService(str(tmp_path / "system"))
    assert service.status()["graph_dirty"] is True
    service.close()
    manager.close()


def test_memory_graph_v1_extracts_line_anchors_and_belongs_to_edges(tmp_path):
    project = tmp_path / "workspace"
    state = project / "textbooks" / "tb_demo" / "state"
    chapters = project / "textbooks" / "tb_demo" / "chapters"
    state.mkdir(parents=True)
    chapters.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")
    (chapters / "chapter_01.md").write_text("# Chapter One\n\nKey concept: graph memory.\n", encoding="utf-8")

    service = MemoryGraphService(str(tmp_path / "system"), project_workspace=str(project))
    service.sync_changed()
    context = service.context("chapter 1 graph memory")
    status = service.status()

    chapter = next(node for node in context["authoritative_nodes"] if node["entity_key"] == "textbook:tb_demo:chapter:1")
    assert chapter["start_line"] == 1
    assert chapter["end_line"] >= 3
    assert "Chapter One" in chapter["evidence"]
    assert status["edge_type_counts"]["belongs_to"] >= 1


def test_memory_search_history_query_boosts_historical_graph_nodes(tmp_path):
    project = tmp_path / "workspace"
    current = project / "textbooks" / "tb_demo" / "state"
    snapshot = project / "textbooks" / "tb_demo" / "snapshots" / "s1" / "state"
    current.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    (current / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")
    (snapshot / "status.json").write_text(json.dumps({"title": "Old Book", "status": "outline"}), encoding="utf-8")

    manager = _PlannerAwareMemoryManager()
    manager.config = type("Config", (), {"get_project_workspace": lambda self: project})()
    tool = MemorySearchTool(manager, system_root=str(tmp_path / "system"))
    result = tool.execute({"query": "tb_demo historical status", "max_results": 2})

    assert result.status == "success"
    assert result.result.index("textbooks/tb_demo/snapshots/s1/state/status.json") < result.result.index("textbooks/tb_demo/state/status.json")
    assert "temporal intent: history" in result.result


def test_memory_graph_status_reports_cache_metrics_and_benchmark(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "user_profile.md").write_text("User prefers concise progress updates.", encoding="utf-8")

    MemorySearchTool.clear_graph_plan_cache()
    tool = MemorySearchTool(_FakeMemoryManager(), system_root=str(tmp_path / "system"))
    tool.execute({"query": "concise progress"})
    tool.execute({"query": "concise progress"})

    status = MemoryGraphStatusTool(str(tmp_path / "system")).execute({"benchmark_query": "concise progress"})

    assert status.status == "success"
    data = json.loads(status.result)
    assert data["graph_cache"]["entries"] >= 1
    assert data["graph_cache"]["hits"] >= 1
    assert "benchmark" in data
    assert data["benchmark"]["query"] == "concise progress"
    assert data["benchmark"]["elapsed_ms"] >= 0


def test_memory_search_compact_graph_mode_reduces_output_tokens(tmp_path):
    project = tmp_path / "workspace"
    current = project / "textbooks" / "tb_demo" / "state"
    snapshot = project / "textbooks" / "tb_demo" / "snapshots" / "s1" / "state"
    current.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    (current / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")
    (snapshot / "status.json").write_text(json.dumps({"title": "Old Book", "status": "outline"}), encoding="utf-8")

    manager = _PlannerAwareMemoryManager()
    manager.config = type("Config", (), {"get_project_workspace": lambda self: project})()
    MemorySearchTool.clear_graph_plan_cache()
    tool = MemorySearchTool(manager, system_root=str(tmp_path / "system"))
    full = tool.execute({"query": "tb_demo status", "max_results": 2, "graph_mode": "full"})
    compact = tool.execute({"query": "tb_demo status", "max_results": 2, "graph_mode": "compact"})

    assert compact.status == "success"
    assert "Graph planner:" in compact.result
    assert "Graph navigation:" not in compact.result
    assert len(compact.result) < len(full.result) * 0.8


def test_memory_graph_tracks_dirty_source_and_entity(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    source = memory_dir / "user_profile.md"
    source.write_text("User prefers concise progress updates.", encoding="utf-8")

    service = MemoryGraphService(str(tmp_path / "system"))
    service.sync_changed()
    service.mark_dirty("profile changed", source_path=str(source), entity_key="user:profile")
    status = service.status()

    assert status["dirty_source_count"] == 1
    assert status["dirty_entity_count"] == 1
    service.sync_changed()
    status = service.status()
    assert status["dirty_source_count"] == 0
    assert status["dirty_entity_count"] == 0


def test_memory_graph_v1_extracts_extended_relation_edges(tmp_path):
    project = tmp_path / "workspace"
    state = project / "textbooks" / "tb_demo" / "state"
    chapters = project / "textbooks" / "tb_demo" / "chapters"
    snapshot = project / "textbooks" / "tb_demo" / "snapshots" / "s1" / "state"
    state.mkdir(parents=True)
    chapters.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")
    (snapshot / "status.json").write_text(json.dumps({"title": "Old Book", "status": "outline"}), encoding="utf-8")
    (chapters / "chapter_01.md").write_text("# Chapter One\n\nKey concept: graph memory.\n", encoding="utf-8")
    (chapters / "chapter_02.md").write_text(
        "# Chapter Two\n\nDepends on: chapter_01\nDerived from: chapter_01\nMentions: chapter_01\n",
        encoding="utf-8",
    )

    service = MemoryGraphService(str(tmp_path / "system"), project_workspace=str(project))
    service.sync_changed()
    status = service.status()

    assert status["edge_type_counts"]["depends_on"] >= 1
    assert status["edge_type_counts"]["derived_from"] >= 1
    assert status["edge_type_counts"]["mentions"] >= 1
    assert status["edge_type_counts"]["conflicts_with"] >= 1
    assert status["edge_evidence_count"] >= 4


def test_memory_graph_extracts_chinese_relation_edges(tmp_path):
    project = tmp_path / "workspace"
    state = project / "textbooks" / "tb_demo" / "state"
    chapters = project / "textbooks" / "tb_demo" / "chapters"
    state.mkdir(parents=True)
    chapters.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")
    (chapters / "chapter_01.md").write_text("# 第一章\n\n基础内容。\n", encoding="utf-8")
    (chapters / "chapter_02.md").write_text(
        "# 第二章\n\n依赖：chapter_01\n来源：chapter_01\n提到：chapter_01\n",
        encoding="utf-8",
    )

    service = MemoryGraphService(str(tmp_path / "system"), project_workspace=str(project))
    service.sync_changed()
    status = service.status()

    assert status["edge_type_counts"]["depends_on"] >= 1
    assert status["edge_type_counts"]["derived_from"] >= 1
    assert status["edge_type_counts"]["mentions"] >= 1


def test_memory_graph_extracts_real_textbook_chapter_reference_patterns(tmp_path):
    project = tmp_path / "workspace"
    state = project / "textbooks" / "tb_demo" / "state"
    chapters = project / "textbooks" / "tb_demo" / "chapters"
    state.mkdir(parents=True)
    chapters.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")
    (chapters / "chapter_01.md").write_text("# 第1章 智能体概述\n\n基础内容。\n", encoding="utf-8")
    (chapters / "chapter_02.md").write_text(
        "# 第2章 开发环境搭建\n\n"
        "第1章建立了智能体的概念框架。\n"
        "提示：第4章实现ReAct范式时会使用异步模式。\n"
        "下一章将深入大语言模型的基础原理。\n",
        encoding="utf-8",
    )
    (chapters / "chapter_03.md").write_text("# 第3章 大语言模型基础\n\n基础内容。\n", encoding="utf-8")
    (chapters / "chapter_04.md").write_text("# 第4章 ReAct智能体\n\n基础内容。\n", encoding="utf-8")

    service = MemoryGraphService(str(tmp_path / "system"), project_workspace=str(project))
    service.sync_changed()
    status = service.status()

    assert status["edge_type_counts"]["depends_on"] >= 1
    assert status["edge_type_counts"]["mentions"] >= 2
    assert status["edge_evidence_count"] >= 3


def test_memory_graph_does_not_extract_chapter_relations_from_error_logs(tmp_path):
    memory_errors = tmp_path / "system" / "memory" / "errors"
    project = tmp_path / "workspace"
    chapters = project / "textbooks" / "tb_demo" / "chapters"
    state = project / "textbooks" / "tb_demo" / "state"
    memory_errors.mkdir(parents=True)
    chapters.mkdir(parents=True)
    state.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"title": "Current Book", "status": "writing"}), encoding="utf-8")
    (chapters / "chapter_02.md").write_text("# 第2章\n\n正文。\n", encoding="utf-8")
    (memory_errors / "error.json").write_text(
        json.dumps({"command": "findstr /n \"第2章\" outline.md"}),
        encoding="utf-8",
    )

    service = MemoryGraphService(str(tmp_path / "system"), project_workspace=str(project))
    service.sync_changed()
    status = service.status()

    assert status["edge_type_counts"].get("depends_on", 0) == 0
    assert status["edge_type_counts"].get("mentions", 0) == 0


def test_memory_graph_indexes_project_knowledge_sources(tmp_path):
    project = tmp_path / "workspace"
    knowledge = project / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "graph.md").write_text("# Graph Memory\n\nKnowledge note about memorygraph.", encoding="utf-8")

    service = MemoryGraphService(str(tmp_path / "system"), project_workspace=str(project))
    service.sync_changed()
    context = service.context("memorygraph knowledge")

    assert context["matched_entities"]
    assert any(node["source_path"].endswith("knowledge/graph.md") for node in context["authoritative_nodes"])


def test_memory_graph_status_tool_can_rebuild_index(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "user_profile.md").write_text("User prefers concise progress updates.", encoding="utf-8")
    service = MemoryGraphService(str(tmp_path / "system"))
    service.sync_changed()
    service.close()

    result = MemoryGraphStatusTool(str(tmp_path / "system")).execute({"action": "rebuild"})

    assert result.status == "success"
    data = json.loads(result.result)
    assert data["action"] == "rebuild"
    assert data["source_count"] == 1
    assert data["node_count"] == 1
