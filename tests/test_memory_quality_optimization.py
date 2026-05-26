import json

from agent.memory.promotion import MemoryPromotionCandidatePool
from agent.memory.manager import MemoryManager
from agent.memory.storage import SearchResult
from agent.tools.memory.memory_search import MemorySearchTool


def test_candidate_confidence_decays_when_old_unused_and_weak(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "old-unused",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.8,
        "reason": "weak",
        "content": "Prefer concise updates.",
        "created_at": "2026-04-01T10:00:00",
        "updated_at": "2026-04-01T10:00:00",
        "evidence_count": 1,
        "lookup_count": 0,
        "sources": [],
    })

    result = pool.decay_confidence(now="2026-05-26T10:00:00")
    row = json.loads(pool.path.read_text(encoding="utf-8").splitlines()[0])

    assert result["decayed_count"] == 1
    assert row["confidence"] < 0.8
    assert row["decay_count"] == 1


def test_similar_memory_merge_adds_canonical_preference(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    first = pool.upsert({
        "version": pool.VERSION,
        "id": "brief",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.7,
        "reason": "explicit",
        "content": "Please answer briefly.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    second = pool.upsert({
        "version": pool.VERSION,
        "id": "concise",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.7,
        "reason": "explicit",
        "content": "Give concise answers and lead with the conclusion.",
        "created_at": "2026-05-26T10:01:00",
        "updated_at": "2026-05-26T10:01:00",
        "evidence_count": 1,
        "sources": [],
    })

    assert first["id"] == second["id"]
    assert second["canonical_preference"] == "brevity"
    assert second["evidence_count"] == 2


def test_negative_feedback_lowers_related_candidate_confidence(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "brief",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Prefer concise answers.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 2,
        "sources": [],
    })

    result = pool.record_negative_feedback("不是这样，以后别按简短回答这个偏好来")
    row = json.loads(pool.path.read_text(encoding="utf-8").splitlines()[0])

    assert result["adjusted_count"] == 1
    assert row["confidence"] < 0.9
    assert row["negative_feedback_count"] == 1


def test_process_candidate_gets_context_tags(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")

    result = pool.record_from_process({
        "session_id": "s1",
        "process_id": "p1",
        "user_message": "写论文时请详细严谨，保留引用线索。",
        "started_at": "2026-05-26T10:00:00",
    })

    assert result["context_tags"] == ["paper"]


class _TemporaryOverrideMemoryManager:
    async def search(self, **kwargs):
        return [
            SearchResult(
                path="memory/user_profile.md",
                start_line=1,
                end_line=3,
                score=0.7,
                snippet="User preference: answer concisely.",
                source="memory",
                metadata={
                    **MemoryManager._classify_memory("memory/user_profile.md", "memory"),
                    "temporary_override": "detail_overrides_brevity",
                },
            )
        ]


def test_memory_search_reports_temporary_override_note():
    result = MemorySearchTool(_TemporaryOverrideMemoryManager()).execute({"query": "这次详细解释"})

    assert result.status == "success"
    assert "Memory note:" in result.result
    assert "temporarily ignored" in result.result


def test_health_report_counts_memory_risks(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
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
    pool.upsert({
        "version": pool.VERSION,
        "id": "expired",
        "status": "expired",
        "target": "long_term_memory",
        "confidence": 0.2,
        "reason": "old",
        "content": "Old weak preference.",
        "created_at": "2026-04-01T10:00:00",
        "updated_at": "2026-04-01T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    report = pool.health_report()

    assert report["high_risk_count"] == 1
    assert report["expired_count"] == 1
    assert report["health_score"] < 100


def test_memory_search_budget_limits_total_snippet_size():
    rows = [
        SearchResult(
            path=f"memory/MEMORY_{index}.md",
            start_line=1,
            end_line=2,
            score=0.9 - index * 0.01,
            snippet="x" * 120,
            source="memory",
            metadata=MemoryManager._classify_memory("memory/MEMORY.md", "memory"),
        )
        for index in range(5)
    ]

    selected = MemorySearchTool._select_results_for_context("status", rows, max_results=5, max_chars=250)

    assert len(selected) == 2
