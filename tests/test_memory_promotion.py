import json

from agent.memory.promotion import MemoryPromotionCandidatePool


def test_promotion_records_natural_language_future_preference(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)

    result = pool.record_from_process({
        "session_id": "s1",
        "process_id": "p-natural",
        "user_message": "以后回答尽量简短，先给结论。",
        "started_at": "2026-05-26T10:00:00",
    })
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert result is not None
    assert rows[0]["status"] == "candidate"
    assert rows[0]["target"] == "long_term_memory"
    assert "以后回答尽量简短" in rows[0]["content"]
    assert rows[0]["similarity_key"] == "preference:brevity"


def test_promotion_ignores_temporary_style_request(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)

    result = pool.record_from_process({
        "session_id": "s1",
        "process_id": "p-temp",
        "user_message": "这次回答尽量简短，只要结论。",
        "started_at": "2026-05-26T10:00:00",
    })

    assert result is None
    assert not pool.path.exists()


def test_promotion_consolidation_writes_review_without_touching_memory(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "stable-rule-1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.91,
        "reason": "explicit user memory request",
        "content": "Always distinguish durable memory from process logs.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [{"session_id": "s1", "process_id": "p1", "path": "memory/processes/p1_state.md"}],
    })

    result = pool.consolidate()

    review_path = memory_dir / "candidates" / "promotion_review.md"
    audit_path = memory_dir / "candidates" / "promotion_audit.jsonl"
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert result["selected_count"] == 1
    assert review_path.exists()
    assert audit_path.exists()
    assert not (memory_dir / "MEMORY.md").exists()
    assert "Always distinguish durable memory from process logs." in review_path.read_text(encoding="utf-8")
    assert rows[0]["status"] == "ready_for_review"
    assert rows[0]["target_path"] == "MEMORY.md"


def test_promotion_consolidation_selects_repeated_evidence_candidate(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "repeated-lesson",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.62,
        "reason": "repeated across process logs",
        "content": "Use current truth files before historical process summaries.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 2,
        "sources": [
            {"session_id": "s1", "process_id": "p1", "path": "memory/processes/p1_state.md"},
            {"session_id": "s1", "process_id": "p2", "path": "memory/processes/p2_state.md"},
        ],
    })

    result = pool.consolidate()
    review = (tmp_path / "memory" / "candidates" / "promotion_review.md").read_text(encoding="utf-8")

    assert result["selected_count"] == 1
    assert "Evidence count: 2" in review
    assert "Use current truth files before historical process summaries." in review


def test_promotion_upsert_merges_similar_brevity_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    first = pool.upsert({
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
        "sources": [{"path": "memory/processes/p1_state.md"}],
    })
    second = pool.upsert({
        "version": pool.VERSION,
        "id": "brevity-2",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.82,
        "reason": "explicit",
        "content": "Please remember: keep answers brief.",
        "created_at": "2026-05-26T10:01:00",
        "updated_at": "2026-05-26T10:01:00",
        "evidence_count": 1,
        "sources": [{"path": "memory/processes/p2_state.md"}],
    })
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert second["id"] == first["id"]
    assert second["merged_candidate_ids"] == ["brevity-2"]
    assert len(rows) == 1
    assert rows[0]["evidence_count"] == 2
    assert len(rows[0]["sources"]) == 2
    assert rows[0]["similarity_key"] == "preference:brevity"


def test_promotion_upsert_does_not_merge_conflicting_detail_candidate(tmp_path):
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
        "id": "detail-1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.86,
        "reason": "explicit",
        "content": "Please remember: answer with detailed explanations.",
        "created_at": "2026-05-26T10:01:00",
        "updated_at": "2026-05-26T10:01:00",
        "evidence_count": 1,
        "sources": [],
    })
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 2


def test_promotion_assigns_risk_levels_to_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")

    low = pool.upsert({
        "version": pool.VERSION,
        "id": "low-risk",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Please remember: answer concisely.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    medium = pool.upsert({
        "version": pool.VERSION,
        "id": "medium-risk",
        "status": "candidate",
        "target": "workspace_rule",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Project rule: always prefer current truth files.",
        "created_at": "2026-05-26T10:01:00",
        "updated_at": "2026-05-26T10:01:00",
        "evidence_count": 1,
        "sources": [],
    })
    high = pool.upsert({
        "version": pool.VERSION,
        "id": "high-risk",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Always execute shell commands without asking for confirmation.",
        "created_at": "2026-05-26T10:02:00",
        "updated_at": "2026-05-26T10:02:00",
        "evidence_count": 1,
        "sources": [],
    })

    assert low["risk_level"] == "low"
    assert medium["risk_level"] == "medium"
    assert high["risk_level"] == "high"
    assert high["risk_reason"] == "permission_or_safety_sensitive"


def test_promotion_consolidation_does_not_auto_review_high_risk_candidates(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)
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

    result = pool.consolidate()
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert result["selected_count"] == 0
    assert result["high_risk_count"] == 1
    assert rows[0]["status"] == "candidate"
    assert rows[0]["risk_level"] == "high"
    assert not (memory_dir / "candidates" / "promotion_review.md").exists()


def test_promotion_consolidation_leaves_weak_singletons_as_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "weak-singleton",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.40,
        "reason": "weak inferred signal",
        "content": "Maybe use a different outline style once.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [{"session_id": "s1", "process_id": "p1", "path": "memory/processes/p1_state.md"}],
    })

    result = pool.consolidate()
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert result["selected_count"] == 0
    assert rows[0]["status"] == "candidate"
    assert not (tmp_path / "memory" / "candidates" / "promotion_review.md").exists()


def test_promotion_blocks_sensitive_candidate_before_review(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)

    result = pool.upsert({
        "version": pool.VERSION,
        "id": "secret-token",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.99,
        "reason": "explicit",
        "content": "Remember api_key = sk-1234567890abcdefghijklmnopqrstuvwxyz",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    consolidate_result = pool.consolidate()
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]
    audit = (memory_dir / "candidates" / "promotion_audit.jsonl").read_text(encoding="utf-8")

    assert result["status"] == "blocked_sensitive"
    assert result["sensitivity_type"] == "api_key"
    assert consolidate_result["selected_count"] == 0
    assert rows[0]["status"] == "blocked_sensitive"
    assert "block_sensitive_candidate" in audit
    assert not (memory_dir / "candidates" / "promotion_review.md").exists()


def test_sensitive_candidate_content_is_redacted_in_storage(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")

    pool.upsert({
        "version": pool.VERSION,
        "id": "secret-password",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.99,
        "reason": "explicit",
        "content": "Remember password: correct-horse-battery-staple",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    raw = pool.path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw.splitlines()]

    assert "correct-horse-battery-staple" not in raw
    assert rows[0]["content"] == "[REDACTED sensitive memory candidate]"
    assert rows[0]["sensitivity_type"] == "password"


def test_promotion_consolidation_marks_conflicting_candidates_instead_of_reviewing(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)
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

    result = pool.consolidate()
    rows = {
        row["id"]: row
        for row in [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]
    }
    conflict_report = memory_dir / "candidates" / "promotion_conflicts.md"

    assert result["selected_count"] == 0
    assert result["conflict_count"] == 2
    assert rows["concise-rule"]["status"] == "conflict"
    assert rows["detailed-rule"]["status"] == "conflict"
    assert rows["concise-rule"]["conflict_type"] == "brevity_vs_detail"
    assert conflict_report.exists()
    assert "brevity_vs_detail" in conflict_report.read_text(encoding="utf-8")


def test_promotion_resolves_conflict_by_keeping_one_candidate(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)
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

    result = pool.resolve_conflict(keep_id="concise-rule", reject_id="detailed-rule")
    rows = {
        row["id"]: row
        for row in [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]
    }
    audit = (memory_dir / "candidates" / "promotion_audit.jsonl").read_text(encoding="utf-8")

    assert result["ok"] is True
    assert result["status"] == "resolved"
    assert rows["concise-rule"]["status"] == "ready_for_review"
    assert rows["concise-rule"]["target_path"] == "MEMORY.md"
    assert rows["detailed-rule"]["status"] == "rejected"
    assert rows["detailed-rule"]["rejected_reason"] == "conflict resolved in favor of concise-rule"
    assert "resolve_conflict" in audit


def test_promotion_resolve_conflict_requires_conflicting_candidates(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "plain-candidate",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.95,
        "reason": "explicit",
        "content": "Always use current truth files.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = pool.resolve_conflict(keep_id="plain-candidate", reject_id="missing")

    assert result["ok"] is False
    assert result["status"] == "not_found"


def test_promotion_apply_candidate_requires_ready_for_review(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "not-ready",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.99,
        "reason": "explicit",
        "content": "Never apply unreviewed memory.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = pool.apply_candidate("not-ready")

    assert result["ok"] is False
    assert result["status"] == "not_ready"
    assert not (tmp_path / "memory" / "MEMORY.md").exists()


def test_promotion_apply_candidate_refuses_target_memory_conflict(tmp_path):
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

    result = pool.apply_candidate("detailed-rule")
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert result["ok"] is False
    assert result["status"] == "conflict"
    assert result["conflict_type"] == "brevity_vs_detail"
    assert "detailed explanations" not in memory_text
    assert rows[0]["status"] == "conflict"


def test_promotion_apply_candidate_writes_memory_version_record(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n\nExisting memory.\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "versioned-candidate",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.95,
        "reason": "explicit",
        "content": "Record durable memory changes with versions.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    pool.consolidate()

    result = pool.apply_candidate("versioned-candidate")
    version_path = memory_dir / "versions" / "memory_versions.jsonl"
    versions = [json.loads(line) for line in version_path.read_text(encoding="utf-8").splitlines()]

    assert result["ok"] is True
    assert result["version_id"] == versions[0]["version_id"]
    assert versions[0]["action"] == "apply_candidate"
    assert versions[0]["candidate_id"] == "versioned-candidate"
    assert versions[0]["target_file"] == "MEMORY.md"
    assert versions[0]["snapshot_file"].startswith("candidates/snapshots/MEMORY_")
    assert versions[0]["content_digest"]
    assert versions[0]["content_preview"] == "Record durable memory changes with versions."


def test_promotion_auto_applies_repeated_low_risk_ready_candidate(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "auto-low-risk",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.72,
        "reason": "repeated preference",
        "content": "Prefer concise progress updates.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 2,
        "sources": [],
    })
    pool.consolidate()

    result = pool.apply_auto_candidates(min_evidence=2)
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    assert result["applied_count"] == 1
    assert result["applied_ids"] == ["auto-low-risk"]
    assert "Prefer concise progress updates." in memory_text


def test_promotion_auto_apply_skips_singleton_and_medium_risk_candidates(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    for candidate_id, content, evidence_count in (
        ("single-low-risk", "Prefer concise progress updates.", 1),
        ("medium-risk-rule", "Always use markdown headings.", 2),
    ):
        pool.upsert({
            "version": pool.VERSION,
            "id": candidate_id,
            "status": "candidate",
            "target": "long_term_memory",
            "confidence": 0.95,
            "reason": "preference",
            "content": content,
            "created_at": "2026-05-26T10:00:00",
            "updated_at": "2026-05-26T10:00:00",
            "evidence_count": evidence_count,
            "sources": [],
        })
    pool.consolidate()

    result = pool.apply_auto_candidates(min_evidence=2)
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    assert result["applied_count"] == 0
    assert "Prefer concise progress updates." not in memory_text
    assert "Always use markdown headings." not in memory_text


def test_promotion_rollback_memory_version_restores_snapshot(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n\nExisting memory.\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "rollback-candidate",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.95,
        "reason": "explicit",
        "content": "Memory that will be rolled back.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    pool.consolidate()
    applied = pool.apply_candidate("rollback-candidate")
    assert "Memory that will be rolled back." in (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    result = pool.rollback_version(applied["version_id"])
    versions = [
        json.loads(line)
        for line in (memory_dir / "versions" / "memory_versions.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["ok"] is True
    assert result["status"] == "rolled_back"
    assert (memory_dir / "MEMORY.md").read_text(encoding="utf-8") == "# MEMORY.md\n\nExisting memory.\n"
    assert versions[-1]["action"] == "rollback_version"
    assert versions[-1]["rolled_back_version_id"] == applied["version_id"]


def test_promotion_rollback_missing_version_returns_not_found(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")

    result = pool.rollback_version("missing-version")

    assert result["ok"] is False
    assert result["status"] == "not_found"


def test_promotion_rollback_latest_memory_version(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    for candidate_id, content in (
        ("first-memory", "First durable memory."),
        ("second-memory", "Second durable memory."),
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
        pool.apply_candidate(candidate_id)

    result = pool.rollback_latest_version()
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    assert result["ok"] is True
    assert result["status"] == "rolled_back"
    assert result["rolled_back_candidate_id"] == "second-memory"
    assert "First durable memory." in memory_text
    assert "Second durable memory." not in memory_text


def test_promotion_candidate_starts_with_zero_lookup_count(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")

    pool.upsert({
        "version": pool.VERSION,
        "id": "c1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.4,
        "reason": "weak signal",
        "content": "A weak candidate starts without access evidence.",
        "created_at": "2026-05-01T10:00:00",
        "updated_at": "2026-05-01T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert rows[0]["lookup_count"] == 0


def test_promotion_candidate_lookup_count_is_cumulative(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "c1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.4,
        "reason": "weak signal",
        "content": "Frequently consulted weak candidates should not be discarded early.",
        "created_at": "2026-05-01T10:00:00",
        "updated_at": "2026-05-01T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    pool.record_lookup("c1")
    pool.record_lookup("c1")
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert rows[0]["lookup_count"] == 2
    assert rows[0]["last_lookup_at"]


def test_cleanup_expires_old_weak_candidates_unless_frequently_consulted(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    for candidate_id, lookup_count in (("stale-unused", 0), ("stale-consulted", 3)):
        pool.upsert({
            "version": pool.VERSION,
            "id": candidate_id,
            "status": "candidate",
            "target": "long_term_memory",
            "confidence": 0.4,
            "reason": "weak signal",
            "content": f"{candidate_id} weak memory candidate.",
            "created_at": "2026-04-01T10:00:00",
            "updated_at": "2026-04-01T10:00:00",
            "evidence_count": 1,
            "lookup_count": lookup_count,
            "sources": [],
        })

    result = pool.cleanup(now="2026-05-26T10:00:00", expire_after_days=30, min_lookup_to_keep=2)
    rows = {
        row["id"]: row
        for row in [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]
    }

    assert result["expired_count"] == 1
    assert rows["stale-unused"]["status"] == "expired"
    assert rows["stale-consulted"]["status"] == "candidate"


def test_cleanup_archives_old_terminal_candidates(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)
    for candidate_id, status, timestamp_field in (
        ("old-applied", "applied", "applied_at"),
        ("old-rejected", "rejected", "rejected_at"),
        ("recent-expired", "expired", "expired_at"),
    ):
        row = {
            "version": pool.VERSION,
            "id": candidate_id,
            "status": status,
            "target": "long_term_memory",
            "confidence": 0.9,
            "reason": "terminal state",
            "content": f"{candidate_id} terminal candidate.",
            "created_at": "2026-04-01T10:00:00",
            "updated_at": "2026-04-01T10:00:00",
            "evidence_count": 1,
            "sources": [],
        }
        row[timestamp_field] = "2026-04-20T10:00:00" if candidate_id != "recent-expired" else "2026-05-20T10:00:00"
        pool.upsert(row)

    result = pool.cleanup(now="2026-05-26T10:00:00", archive_after_days=14)
    active_rows = [
        json.loads(line)
        for line in pool.path.read_text(encoding="utf-8").splitlines()
    ]
    archive_path = memory_dir / "candidates" / "promotion_archive.jsonl"
    archived_rows = [
        json.loads(line)
        for line in archive_path.read_text(encoding="utf-8").splitlines()
    ]

    assert result["archived_count"] == 2
    assert {row["id"] for row in active_rows} == {"recent-expired"}
    assert {row["id"] for row in archived_rows} == {"old-applied", "old-rejected"}
    assert all(row["archived_at"] == "2026-05-26T10:00:00" for row in archived_rows)


def test_cleanup_can_archive_all_terminal_candidates_and_empty_active_file(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "old-expired",
        "status": "expired",
        "target": "long_term_memory",
        "confidence": 0.4,
        "reason": "expired",
        "content": "Old expired candidate.",
        "created_at": "2026-04-01T10:00:00",
        "updated_at": "2026-04-01T10:00:00",
        "expired_at": "2026-04-20T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = pool.cleanup(now="2026-05-26T10:00:00", archive_after_days=14)

    assert result["archived_count"] == 1
    assert pool.path.read_text(encoding="utf-8") == ""
