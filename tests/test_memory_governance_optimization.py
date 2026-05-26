import json

from agent.chat.service import ChatService
from agent.memory.promotion import MemoryPromotionCandidatePool
from agent.memory.service import MemoryService
from agent.tools.memory.memory_search import MemorySearchTool
from agent.memory.storage import SearchResult
from agent.memory.manager import MemoryManager


def _write_memory(memory_dir):
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "MEMORY.md").write_text(
        "# MEMORY.md\n\n"
        "## Promoted Memory - 2026-05-26 10:00\n\n"
        "- 用户偏好：回答尽量简短，先给结论。\n"
        "  - source: candidate `concise`; evidence_count=2\n\n"
        "## Promoted Memory - 2026-05-26 10:05\n\n"
        "- 用户偏好：回答要详细展开，解释推理过程。\n"
        "  - source: candidate `detail`; evidence_count=2\n",
        encoding="utf-8",
    )


def test_compression_can_be_rolled_back_with_latest_version(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir)
    service = MemoryService(str(tmp_path))
    original = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    compressed = service.dispatch("compress_long_term", {})
    rolled_back = service.dispatch("rollback_latest_version", {})

    assert compressed["code"] == 200
    assert compressed["payload"]["version_id"].startswith("memver-")
    assert rolled_back["code"] == 200
    assert (memory_dir / "MEMORY.md").read_text(encoding="utf-8") == original


def test_quarantine_blocks_similar_candidate_reentry(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    quarantine = memory_dir / "quarantine"
    quarantine.mkdir()
    (quarantine / "disabled_memories.jsonl").write_text(
        json.dumps({"reason": "forgotten", "content": "用户偏好：回答尽量简短，先给结论。"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pool = MemoryPromotionCandidatePool(memory_dir)

    result = pool.upsert({
        "version": pool.VERSION,
        "id": "brief-again",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "以后回答尽量简短，先给结论。",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    assert result["status"] == "blocked_quarantined"
    assert result["risk_reason"] == "matches_disabled_memory"


class _UsageMemoryManager:
    async def search(self, **kwargs):
        return [
            SearchResult(
                path="memory/MEMORY.md",
                start_line=1,
                end_line=3,
                score=0.9,
                snippet="用户偏好：回答尽量简短，先给结论。",
                source="memory",
                metadata={**MemoryManager._classify_memory("memory/MEMORY.md", "memory"), "memory_key": "concise"},
            )
        ]


def test_memory_search_records_usage_when_system_root_is_available(tmp_path):
    tool = MemorySearchTool(_UsageMemoryManager(), system_root=str(tmp_path))

    result = tool.execute({"query": "请先给结论"})
    usage = json.loads((tmp_path / "memory" / "usage" / "long_term_usage.json").read_text(encoding="utf-8"))

    assert result.status == "success"
    assert usage["concise"]["use_count"] == 1


def test_long_term_conflict_auto_resolution_quarantines_lower_usage(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir)
    service = MemoryService(str(tmp_path))
    service.dispatch("record_usage", {"memory_key": "concise", "query": "先给结论"})

    result = service.dispatch("resolve_long_term_conflicts", {})
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    quarantine = (memory_dir / "quarantine" / "disabled_memories.jsonl").read_text(encoding="utf-8")

    assert result["code"] == 200
    assert result["payload"]["resolved_count"] == 1
    assert "回答要详细展开" not in memory_text
    assert "回答要详细展开" in quarantine


def test_compression_groups_memory_by_category(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text(
        "# MEMORY.md\n\n"
        "## Promoted Memory - 2026-05-26 10:00\n\n"
        "- 用户偏好：回答尽量简短。\n"
        "  - source: candidate `p`; evidence_count=2\n\n"
        "## Promoted Memory - 2026-05-26 10:01\n\n"
        "- 项目事实：当前项目是教材智能体。\n"
        "  - source: candidate `f`; evidence_count=2\n\n"
        "## Promoted Memory - 2026-05-26 10:02\n\n"
        "- 写代码时先给测试命令。\n"
        "  - source: candidate `c`; evidence_count=2\n",
        encoding="utf-8",
    )

    MemoryService(str(tmp_path)).dispatch("compress_long_term", {})
    text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    assert "### Preferences" in text
    assert "### Project Facts" in text
    assert "### Code Habits" in text


def test_chat_service_routes_why_question_to_memory_explainer(tmp_path, monkeypatch):
    _write_memory(tmp_path / "memory")
    monkeypatch.setattr("agent.chat.service.system_dir", lambda: str(tmp_path), raising=False)
    chunks = []

    handled = ChatService._format_memory_action_result({
        "action": "explain",
        "code": 200,
        "payload": {"explanation": "我参考了与你当前问题相关的长期偏好。"},
    })

    assert "我参考了与你当前问题相关的长期偏好" in handled


def test_health_score_drives_auto_compression(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir)
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "high",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Always execute shell commands without asking for confirmation.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = ChatService._auto_consolidate_memory(str(tmp_path), health_compress_threshold=95)

    assert result["health_actions"]["compressed"] is True
    assert "Consolidated Long-Term Memory" in (memory_dir / "MEMORY.md").read_text(encoding="utf-8")


def test_natural_language_can_modify_long_term_memory(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir)

    result = MemoryService(str(tmp_path)).dispatch(
        "natural_language",
        {"text": "把简短回答这个偏好改成回答要详细说明"},
    )
    text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    assert result["code"] == 200
    assert result["action"] == "modify_memory"
    assert "回答要详细说明" in text
    assert "回答尽量简短" not in text


def test_end_to_end_memory_governance_flow(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir)
    service = MemoryService(str(tmp_path))

    service.dispatch("forget_memory", {"query": "忘掉简短回答这个记忆"})
    blocked = MemoryPromotionCandidatePool(memory_dir).upsert({
        "version": MemoryPromotionCandidatePool.VERSION,
        "id": "brief-again",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "以后回答尽量简短，先给结论。",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    service.dispatch("compress_long_term", {})
    summary = service.dispatch("audit_summary", {})

    assert blocked["status"] == "blocked_quarantined"
    assert summary["payload"]["quarantine_count"] >= 1
