import json

from agent.memory.conversation_store import ConversationStore
from agent.memory.query_service import MemoryQueryService
from agent.memory.realtime import RealtimeMemoryRecorder
from agent.memory.manager import MemoryManager
from agent.memory.config import MemoryConfig
from agent.memory.storage import SearchResult
from agent.tools.memory.memory_search import MemorySearchTool


def test_memory_query_service_combines_profile_process_and_history(tmp_path):
    store = ConversationStore(tmp_path / "memory" / "long-term" / "index.db")
    store.append_messages(
        "textbook_demo",
        [
            {"role": "user", "content": "write chapter 1"},
            {"role": "assistant", "content": "chapter 1 done"},
        ],
        channel_type="textbook",
    )

    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process("textbook_demo", "proc_demo", "write chapter 1", channel_type="textbook")
    recorder.finish_process("proc_demo", final_response="chapter 1 done")

    chat_dir = tmp_path / "chat_history"
    chat_dir.mkdir()
    (chat_dir / "textbook_demo.json").write_text(
        json.dumps([{"role": "user", "content": "legacy ui message"}]),
        encoding="utf-8",
    )

    service = MemoryQueryService(tmp_path, conversation_store=store)
    result = service.query(session_id="textbook_demo", process_id="proc_demo")

    assert result["process"]["process_id"] == "proc_demo"
    assert result["history"]["total"] == 2
    assert result["textbook_history"]["total"] == 1
    assert result["profile"]["recent_focus"]


def test_conversation_store_detects_recent_duplicate_text(tmp_path):
    store = ConversationStore(tmp_path / "memory" / "long-term" / "index.db")
    store.append_messages(
        "s1",
        [{"role": "user", "content": "same visible text"}],
        channel_type="textbook",
    )

    assert store.has_recent_text_message("s1", "user", "same visible text")
    assert not store.has_recent_text_message("s1", "assistant", "same visible text")


class _FakeProfileModel:
    def call(self, request):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "preferences": ["prefers concise progress updates"],
                            "goals": ["maintain durable project memory"],
                            "projects": ["textbook agent memory system"],
                            "facts": ["uses process-level memory"],
                        })
                    }
                }
            ]
        }


def test_process_profile_llm_distillation_merges_patch(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process("s1", "p1", "please improve memory", channel_type="web")
    recorder.finish_process("p1", final_response="memory improved")

    assert recorder.distill_user_profile("p1", _FakeProfileModel())

    profile = json.loads((tmp_path / "memory" / "user_profile.json").read_text(encoding="utf-8"))
    assert "prefers concise progress updates" in profile["preferences"]
    assert "uses process-level memory" in profile["facts"]


def test_memory_manager_classifies_reranks_and_compresses_results(tmp_path):
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(tmp_path)))
    try:
        textbook = SearchResult(
            path="textbooks/tb_demo/harness.md",
            start_line=1,
            end_line=10,
            score=0.5,
            snippet="教材 Harness " + ("很长内容 " * 100),
            source="textbook",
            metadata=MemoryManager._classify_memory("textbooks/tb_demo/harness.md", "textbook"),
        )
        generic = SearchResult(
            path="memory/2026-05-25.md",
            start_line=1,
            end_line=3,
            score=0.5,
            snippet="普通记忆",
            source="memory",
            metadata=MemoryManager._classify_memory("memory/2026-05-25.md", "memory"),
        )

        ranked = manager._rerank_results("tb_demo 教材 harness", [generic, textbook])
        compressed = manager._compress_search_result(ranked[0])

        assert ranked[0].path == "textbooks/tb_demo/harness.md"
        assert ranked[0].metadata["memory_layer"] == "textbook"
        assert ranked[0].metadata["temporal_scope"] == "current"
        assert ranked[0].metadata["authority"] == "truth_file"
        assert len(compressed.snippet) <= 323
    finally:
        manager.close()


def test_memory_temporal_defaults_cover_all_main_layers(tmp_path):
    cases = {
        "textbooks/tb_demo/state/status.json": ("current", "truth_file"),
        "textbooks/tb_demo/snapshots/s1/state/status.json": ("historical", "truth_file"),
        "memory/processes/p1_state.md": ("historical", "process_log"),
        "memory/sessions/s1_state.md": ("historical", "conversation"),
        "memory/short_term/s1.json": ("active", "short_term"),
        "memory/errors/e1.json": ("historical", "error_log"),
        "memory/candidates/promotion_candidates.jsonl": ("active", "promotion_candidate"),
        "memory/2026-05-25.md": ("historical", "daily_summary"),
        "memory/user_profile.md": ("evergreen", "user_profile"),
        "RULE.md": ("evergreen", "workspace_rule"),
        "knowledge/concepts/demo.md": ("evergreen", "knowledge"),
    }

    for path, expected in cases.items():
        metadata = MemoryManager._classify_memory(path, "knowledge" if path.startswith("knowledge/") else "memory")
        assert (metadata["temporal_scope"], metadata["authority"]) == expected


def test_memory_rerank_prefers_current_over_historical(tmp_path):
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(tmp_path)))
    try:
        current = SearchResult(
            path="textbooks/tb_demo/state/status.json",
            start_line=1,
            end_line=1,
            score=0.5,
            snippet="current status",
            source="textbook",
            metadata=MemoryManager._classify_memory("textbooks/tb_demo/state/status.json", "textbook"),
        )
        historical = SearchResult(
            path="memory/processes/p1_state.md",
            start_line=1,
            end_line=1,
            score=0.5,
            snippet="old process status",
            source="memory",
            metadata=MemoryManager._classify_memory("memory/processes/p1_state.md", "memory"),
        )

        ranked = manager._rerank_results("tb_demo 教材 status", [historical, current])

        assert ranked[0].path == "textbooks/tb_demo/state/status.json"
    finally:
        manager.close()


def test_memory_rerank_prefers_current_truth_over_error_noise_for_normal_queries(tmp_path):
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(tmp_path)))
    try:
        current = SearchResult(
            path="textbooks/tb_demo/state/status.json",
            start_line=1,
            end_line=1,
            score=0.55,
            snippet="current textbook status",
            source="textbook",
            metadata=MemoryManager._classify_memory("textbooks/tb_demo/state/status.json", "textbook"),
        )
        error = SearchResult(
            path="memory/errors/20260525_textbook_chapter_failed.json",
            start_line=1,
            end_line=1,
            score=0.70,
            snippet="old chapter failure",
            source="memory",
            metadata=MemoryManager._classify_memory("memory/errors/20260525_textbook_chapter_failed.json", "memory"),
        )

        ranked = manager._rerank_results("tb_demo latest chapter status", [error, current])

        assert ranked[0].path == "textbooks/tb_demo/state/status.json"
    finally:
        manager.close()


def test_memory_rerank_prefers_evergreen_profile_over_process_log(tmp_path):
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(tmp_path)))
    try:
        profile = SearchResult(
            path="memory/user_profile.md",
            start_line=1,
            end_line=4,
            score=0.60,
            snippet="stable user working style",
            source="memory",
            metadata=MemoryManager._classify_memory("memory/user_profile.md", "memory"),
        )
        process = SearchResult(
            path="memory/processes/proc_demo_state.md",
            start_line=1,
            end_line=4,
            score=0.78,
            snippet="transient process log mentions working style once",
            source="memory",
            metadata=MemoryManager._classify_memory("memory/processes/proc_demo_state.md", "memory"),
        )

        ranked = manager._rerank_results("working style", [process, profile])

        assert ranked[0].path == "memory/user_profile.md"
    finally:
        manager.close()


def test_memory_rerank_lets_current_detail_request_override_concise_preference(tmp_path):
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(tmp_path)))
    try:
        concise_preference = SearchResult(
            path="memory/user_profile.md",
            start_line=1,
            end_line=3,
            score=0.90,
            snippet="User preference: always answer concisely.",
            source="memory",
            metadata=MemoryManager._classify_memory("memory/user_profile.md", "memory"),
        )
        relevant_detail = SearchResult(
            path="knowledge/calculus.md",
            start_line=1,
            end_line=6,
            score=0.60,
            snippet="Detailed derivation notes for calculus explanations.",
            source="knowledge",
            metadata=MemoryManager._classify_memory("knowledge/calculus.md", "knowledge"),
        )

        ranked = manager._rerank_results("这次请详细解释推导过程", [concise_preference, relevant_detail])

        assert ranked[0].path == "knowledge/calculus.md"
        assert concise_preference.metadata["temporary_override"] == "detail_overrides_brevity"
    finally:
        manager.close()


def test_memory_rerank_lets_current_brief_request_override_detail_preference(tmp_path):
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(tmp_path)))
    try:
        detailed_preference = SearchResult(
            path="memory/user_profile.md",
            start_line=1,
            end_line=3,
            score=0.90,
            snippet="User preference: always answer with detailed explanations.",
            source="memory",
            metadata=MemoryManager._classify_memory("memory/user_profile.md", "memory"),
        )
        relevant_summary = SearchResult(
            path="knowledge/summary.md",
            start_line=1,
            end_line=4,
            score=0.60,
            snippet="Short summary notes for the current topic.",
            source="knowledge",
            metadata=MemoryManager._classify_memory("knowledge/summary.md", "knowledge"),
        )

        ranked = manager._rerank_results("这次请简短回答，只要结论", [detailed_preference, relevant_summary])

        assert ranked[0].path == "knowledge/summary.md"
        assert detailed_preference.metadata["temporary_override"] == "brevity_overrides_detail"
    finally:
        manager.close()


class _FakeMemoryManager:
    async def search(self, **kwargs):
        return [
            SearchResult(
                path="textbooks/tb_demo/state/status.json",
                start_line=1,
                end_line=3,
                score=0.9,
                snippet="status current",
                source="textbook",
                metadata=MemoryManager._with_temporal_metadata(
                    "textbooks/tb_demo/state/status.json",
                    "textbook",
                    MemoryManager._classify_memory("textbooks/tb_demo/state/status.json", "textbook"),
                    observed_at="2026-05-25T10:00:00",
                ),
            )
        ]


def test_memory_search_outputs_temporal_metadata():
    tool = MemorySearchTool(_FakeMemoryManager())
    result = tool.execute({"query": "tb_demo status"})

    assert result.status == "success"
    assert "Entity: textbook:tb_demo:state:status.json" in result.result
    assert "Temporal: current" in result.result
    assert "Authority: truth_file" in result.result
    assert "Observed: 2026-05-25T10:00:00" in result.result
    assert "Valid: 2026-05-25T10:00:00 -> present" in result.result
    assert "Hit reason:" in result.result
    assert "Matched terms:" in result.result
    assert "Confidence:" in result.result


class _ConflictMemoryManager:
    async def search(self, **kwargs):
        current = MemoryManager._classify_memory("textbooks/tb_demo/state/status.json", "textbook")
        historical = MemoryManager._classify_memory("textbooks/tb_demo/snapshots/s1/state/status.json", "textbook")
        return [
            SearchResult(
                path="textbooks/tb_demo/state/status.json",
                start_line=1,
                end_line=3,
                score=0.9,
                snippet="current status",
                source="textbook",
                metadata=current,
            ),
            SearchResult(
                path="textbooks/tb_demo/snapshots/s1/state/status.json",
                start_line=1,
                end_line=3,
                score=0.7,
                snippet="old status",
                source="textbook",
                metadata=historical,
            ),
        ]


def test_memory_search_warns_when_current_and_historical_textbook_memory_coexist():
    tool = MemorySearchTool(_ConflictMemoryManager())
    result = tool.execute({"query": "tb_demo status"})

    assert result.status == "success"
    assert "Conflict notes:" in result.result
    assert "Prefer current" in result.result


class _NoisyMemoryManager:
    async def search(self, **kwargs):
        rows = [
            ("textbooks/tb_demo/state/status.json", "textbook", "current status", 0.92),
            ("memory/user_profile.md", "memory", "stable profile", 0.88),
            ("memory/processes/p1_state.md", "memory", "process one", 0.86),
            ("memory/processes/p2_state.md", "memory", "process two", 0.85),
            ("memory/processes/p3_state.md", "memory", "process three", 0.84),
            ("memory/errors/e1.json", "memory", "old error one", 0.83),
            ("memory/errors/e2.json", "memory", "old error two", 0.82),
        ]
        return [
            SearchResult(
                path=path,
                start_line=1,
                end_line=2,
                score=score,
                snippet=snippet,
                source=source,
                metadata=MemoryManager._classify_memory(path, source),
            )
            for path, source, snippet, score in rows
        ]


def test_memory_search_caps_process_and_error_noise_for_normal_queries():
    tool = MemorySearchTool(_NoisyMemoryManager())
    result = tool.execute({"query": "tb_demo status", "max_results": 7})

    assert result.status == "success"
    assert "memory/processes/p1_state.md" in result.result
    assert "memory/processes/p2_state.md" not in result.result
    assert "memory/errors/e1.json" not in result.result
    assert "memory/errors/e2.json" not in result.result


def test_memory_search_keeps_error_memory_for_debug_queries():
    tool = MemorySearchTool(_NoisyMemoryManager())
    result = tool.execute({"query": "fix old error", "max_results": 7})

    assert result.status == "success"
    assert "memory/errors/e1.json" in result.result


def test_memory_authority_resolver_marks_historical_same_entity_as_superseded(tmp_path):
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(tmp_path)))
    try:
        current = SearchResult(
            path="textbooks/tb_demo/state/status.json",
            start_line=1,
            end_line=1,
            score=0.5,
            snippet="current status",
            source="textbook",
            metadata=MemoryManager._classify_memory("textbooks/tb_demo/state/status.json", "textbook"),
        )
        historical = SearchResult(
            path="textbooks/tb_demo/snapshots/s1/state/status.json",
            start_line=1,
            end_line=1,
            score=0.5,
            snippet="old status",
            source="textbook",
            metadata=MemoryManager._classify_memory("textbooks/tb_demo/snapshots/s1/state/status.json", "textbook"),
        )

        resolved = manager._resolve_authoritative_results("tb_demo 当前状态", [historical, current])
        old = next(item for item in resolved if item.path.startswith("textbooks/tb_demo/snapshots/"))

        assert old.metadata["entity_key"] == "textbook:tb_demo:state:status.json"
        assert old.metadata["superseded_by"] == "textbooks/tb_demo/state/status.json"
        assert old.score < current.score
    finally:
        manager.close()


def test_memory_authority_resolver_keeps_historical_score_for_history_queries(tmp_path):
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(tmp_path)))
    try:
        current = SearchResult(
            path="textbooks/tb_demo/state/status.json",
            start_line=1,
            end_line=1,
            score=0.5,
            snippet="current status",
            source="textbook",
            metadata=MemoryManager._classify_memory("textbooks/tb_demo/state/status.json", "textbook"),
        )
        historical = SearchResult(
            path="textbooks/tb_demo/snapshots/s1/state/status.json",
            start_line=1,
            end_line=1,
            score=0.5,
            snippet="old status",
            source="textbook",
            metadata=MemoryManager._classify_memory("textbooks/tb_demo/snapshots/s1/state/status.json", "textbook"),
        )

        resolved = manager._resolve_authoritative_results("tb_demo 历史状态记录", [historical, current])
        old = next(item for item in resolved if item.path.startswith("textbooks/tb_demo/snapshots/"))

        assert old.metadata["superseded_by"] == "textbooks/tb_demo/state/status.json"
        assert old.score == 0.5
    finally:
        manager.close()
