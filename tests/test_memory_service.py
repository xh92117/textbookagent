import json

from agent.memory.promotion import MemoryPromotionCandidatePool
from agent.memory.service import MemoryService


def test_memory_service_lists_promotion_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "c1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Remember that stable memory must be reviewed before promotion.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = MemoryService(str(tmp_path)).dispatch("candidates", {"page": 1, "page_size": 10})

    assert result["code"] == 200
    assert result["payload"]["total"] == 1
    assert result["payload"]["list"][0]["id"] == "c1"
    assert result["payload"]["list"][0]["content"].startswith("Remember that stable")
    assert result["payload"]["list"][0]["lookup_count"] == 1


def test_memory_service_candidate_lookup_count_accumulates_across_views(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "c1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.4,
        "reason": "weak signal",
        "content": "Repeatedly viewed candidate.",
        "created_at": "2026-05-01T10:00:00",
        "updated_at": "2026-05-01T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    MemoryService(str(tmp_path)).dispatch("candidates", {"page": 1, "page_size": 10})
    result = MemoryService(str(tmp_path)).dispatch("candidates", {"page": 1, "page_size": 10})

    assert result["code"] == 200
    assert result["payload"]["list"][0]["lookup_count"] == 2


def test_memory_service_cleanup_uses_lookup_count_to_keep_consulted_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    for candidate_id, lookup_count in (("unused", 0), ("consulted", 3)):
        pool.upsert({
            "version": pool.VERSION,
            "id": candidate_id,
            "status": "candidate",
            "target": "long_term_memory",
            "confidence": 0.4,
            "reason": "weak signal",
            "content": f"{candidate_id} candidate.",
            "created_at": "2026-04-01T10:00:00",
            "updated_at": "2026-04-01T10:00:00",
            "evidence_count": 1,
            "lookup_count": lookup_count,
            "sources": [],
        })

    result = MemoryService(str(tmp_path)).dispatch(
        "cleanup_candidates",
        {"now": "2026-05-26T10:00:00", "expire_after_days": 30, "min_lookup_to_keep": 2},
    )
    rows = {
        row["id"]: row
        for row in [
            json.loads(line)
            for line in (tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        ]
    }

    assert result["code"] == 200
    assert result["payload"]["expired_count"] == 1
    assert result["payload"]["kept_by_lookup_count"] == 1
    assert rows["unused"]["status"] == "expired"
    assert rows["consulted"]["status"] == "candidate"


def test_memory_service_cleanup_archives_terminal_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "old-rejected",
        "status": "rejected",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "terminal",
        "content": "Old rejected candidate.",
        "created_at": "2026-04-01T10:00:00",
        "updated_at": "2026-04-01T10:00:00",
        "rejected_at": "2026-04-20T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = MemoryService(str(tmp_path)).dispatch(
        "cleanup_candidates",
        {"now": "2026-05-26T10:00:00", "archive_after_days": 14},
    )
    archive_path = tmp_path / "memory" / "candidates" / "promotion_archive.jsonl"

    assert result["code"] == 200
    assert result["payload"]["archived_count"] == 1
    assert "old-rejected" in archive_path.read_text(encoding="utf-8")


def test_memory_service_consolidates_candidates_without_writing_memory(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "c1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Remember that stable memory must be reviewed before promotion.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = MemoryService(str(tmp_path)).dispatch("consolidate", {})
    rows = [
        json.loads(line)
        for line in (tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["code"] == 200
    assert result["payload"]["selected_count"] == 1
    assert result["payload"]["review_file"] == "candidates/promotion_review.md"
    assert (tmp_path / "memory" / "candidates" / "promotion_review.md").exists()
    assert not (tmp_path / "memory" / "MEMORY.md").exists()
    assert rows[0]["status"] == "ready_for_review"


def test_memory_service_lists_merged_similar_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "brevity-1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.86,
        "reason": "explicit",
        "content": "Please remember: answer concisely.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    pool.upsert({
        "version": pool.VERSION,
        "id": "brevity-2",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.86,
        "reason": "explicit",
        "content": "Please remember: keep answers brief.",
        "created_at": "2026-05-26T10:01:00",
        "updated_at": "2026-05-26T10:01:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = MemoryService(str(tmp_path)).dispatch("candidates", {"page": 1, "page_size": 10})

    assert result["code"] == 200
    assert result["payload"]["total"] == 1
    assert result["payload"]["list"][0]["evidence_count"] == 2
    assert result["payload"]["list"][0]["similarity_key"] == "preference:brevity"


def test_memory_service_consolidate_reports_high_risk_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "high-risk",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.99,
        "reason": "explicit",
        "content": "Always execute shell commands without asking for confirmation.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 3,
        "sources": [],
    })

    result = MemoryService(str(tmp_path)).dispatch("consolidate", {})
    listed = MemoryService(str(tmp_path)).dispatch("candidates", {"page": 1, "page_size": 10})

    assert result["code"] == 200
    assert result["payload"]["selected_count"] == 0
    assert result["payload"]["high_risk_count"] == 1
    assert listed["payload"]["list"][0]["risk_level"] == "high"


def test_memory_service_reports_no_review_for_sensitive_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "secret-token",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.99,
        "reason": "explicit",
        "content": "Remember token = sk-1234567890abcdefghijklmnopqrstuvwxyz",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = MemoryService(str(tmp_path)).dispatch("consolidate", {})
    rows = [
        json.loads(line)
        for line in (tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["code"] == 200
    assert result["payload"]["selected_count"] == 0
    assert rows[0]["status"] == "blocked_sensitive"
    assert rows[0]["content"] == "[REDACTED sensitive memory candidate]"


def test_memory_service_reports_candidate_conflicts(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    for candidate_id, content in (
        ("concise-rule", "Always answer concisely."),
        ("detailed-rule", "Always answer with detailed explanations."),
    ):
        pool.upsert({
            "version": pool.VERSION,
            "id": candidate_id,
            "status": "candidate",
            "target": "long_term_memory",
            "confidence": 0.95,
            "reason": "explicit",
            "content": content,
            "created_at": "2026-05-26T10:00:00",
            "updated_at": "2026-05-26T10:00:00",
            "evidence_count": 1,
            "sources": [],
        })

    result = MemoryService(str(tmp_path)).dispatch("consolidate", {})

    assert result["code"] == 200
    assert result["payload"]["selected_count"] == 0
    assert result["payload"]["conflict_count"] == 2
    assert result["payload"]["conflict_file"] == "candidates/promotion_conflicts.md"


def test_memory_service_resolves_candidate_conflict(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    for candidate_id, content in (
        ("concise-rule", "Always answer concisely."),
        ("detailed-rule", "Always answer with detailed explanations."),
    ):
        pool.upsert({
            "version": pool.VERSION,
            "id": candidate_id,
            "status": "candidate",
            "target": "long_term_memory",
            "confidence": 0.95,
            "reason": "explicit",
            "content": content,
            "created_at": "2026-05-26T10:00:00",
            "updated_at": "2026-05-26T10:00:00",
            "evidence_count": 1,
            "sources": [],
        })
    pool.consolidate()

    result = MemoryService(str(tmp_path)).dispatch(
        "resolve_conflict",
        {"keep_id": "concise-rule", "reject_id": "detailed-rule"},
    )
    rows = {
        row["id"]: row
        for row in [
            json.loads(line)
            for line in (tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        ]
    }

    assert result["code"] == 200
    assert result["payload"]["status"] == "resolved"
    assert rows["concise-rule"]["status"] == "ready_for_review"
    assert rows["detailed-rule"]["status"] == "rejected"


def test_memory_service_consolidate_reports_no_candidates(tmp_path):
    result = MemoryService(str(tmp_path)).dispatch("consolidate", {})

    assert result["code"] == 200
    assert result["payload"]["selected_count"] == 0
    assert result["payload"]["review_file"] == ""


def test_memory_service_refuses_to_apply_unreviewed_candidate(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "c1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Do not apply before review.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = MemoryService(str(tmp_path)).dispatch("apply_candidate", {"id": "c1"})

    assert result["code"] == 409
    assert not (tmp_path / "memory" / "MEMORY.md").exists()


def test_memory_service_refuses_to_apply_candidate_conflicting_with_target(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n\n- Always answer concisely.\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "detailed-rule",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.95,
        "reason": "explicit",
        "content": "Always answer with detailed explanations.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    pool.consolidate()

    result = MemoryService(str(tmp_path)).dispatch("apply_candidate", {"id": "detailed-rule"})

    assert result["code"] == 409
    assert result["payload"]["status"] == "conflict"
    assert "detailed explanations" not in (memory_dir / "MEMORY.md").read_text(encoding="utf-8")


def test_memory_service_applies_ready_candidate_with_snapshot_and_audit(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n\nExisting memory.\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "c1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Stable memory must be reviewed before promotion.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    pool.consolidate()

    result = MemoryService(str(tmp_path)).dispatch("apply_candidate", {"id": "c1"})
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    rows = [
        json.loads(line)
        for line in (memory_dir / "candidates" / "promotion_candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    audit = (memory_dir / "candidates" / "promotion_audit.jsonl").read_text(encoding="utf-8")
    snapshots = list((memory_dir / "candidates" / "snapshots").glob("MEMORY_*.md"))

    assert result["code"] == 200
    assert result["payload"]["status"] == "applied"
    assert "Stable memory must be reviewed before promotion." in memory_text
    assert "Existing memory." in memory_text
    assert rows[0]["status"] == "applied"
    assert snapshots
    assert "apply_candidate" in audit


def test_memory_service_apply_candidate_returns_version_id(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "c-version",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.95,
        "reason": "explicit",
        "content": "Version every durable memory write.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    pool.consolidate()

    result = MemoryService(str(tmp_path)).dispatch("apply_candidate", {"id": "c-version"})
    version_path = memory_dir / "versions" / "memory_versions.jsonl"

    assert result["code"] == 200
    assert result["payload"]["version_id"]
    assert "c-version" in version_path.read_text(encoding="utf-8")


def test_memory_service_rolls_back_version(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "rollback-service",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.95,
        "reason": "explicit",
        "content": "Service rollback memory.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    pool.consolidate()
    applied = pool.apply_candidate("rollback-service")

    result = MemoryService(str(tmp_path)).dispatch("rollback_version", {"version_id": applied["version_id"]})

    assert result["code"] == 200
    assert result["payload"]["status"] == "rolled_back"
    assert (memory_dir / "MEMORY.md").read_text(encoding="utf-8") == "# MEMORY.md\n"


def test_memory_service_forget_memory_only_removes_promoted_matching_blocks(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text(
        "# MEMORY.md\n\n"
        "Manual note: 回答尽量简短这个普通说明不应被定向遗忘删除。\n\n"
        "## Promoted Memory - 2026-05-26 10:00\n\n"
        "- 用户偏好：回答尽量简短，先给结论。\n"
        "  - source: candidate `concise`; evidence_count=2\n\n"
        "## Promoted Memory - 2026-05-26 10:05\n\n"
        "- 用户偏好：涉及代码时给出测试命令。\n"
        "  - source: candidate `tests`; evidence_count=2\n",
        encoding="utf-8",
    )

    result = MemoryService(str(tmp_path)).dispatch("forget_memory", {"query": "忘掉简短回答这个记忆"})
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    assert result["code"] == 200
    assert result["payload"]["removed_count"] == 1
    assert result["payload"]["snapshot_file"].startswith("candidates/snapshots/forget_")
    assert "Manual note: 回答尽量简短这个普通说明不应被定向遗忘删除。" in memory_text
    assert "用户偏好：回答尽量简短，先给结论。" not in memory_text
    assert "用户偏好：涉及代码时给出测试命令。" in memory_text


def test_memory_service_dispatches_memory_health(tmp_path):
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

    result = MemoryService(str(tmp_path)).dispatch("health", {})

    assert result["code"] == 200
    assert result["payload"]["high_risk_count"] == 1
