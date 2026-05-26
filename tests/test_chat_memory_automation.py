import json

from agent.chat.service import ChatService
from agent.memory.promotion import MemoryPromotionCandidatePool


def test_chat_service_auto_consolidates_memory_candidates(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "c1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Automatic maintenance should prepare review packets.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = ChatService._auto_consolidate_memory(str(tmp_path))
    rows = [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]

    assert result["selected_count"] == 1
    assert (memory_dir / "candidates" / "promotion_review.md").exists()
    assert rows[0]["status"] == "ready_for_review"


def test_chat_service_auto_applies_repeated_low_risk_memory_candidates(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "auto-progress",
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

    result = ChatService._auto_consolidate_memory(str(tmp_path))

    assert result["auto_apply"]["applied_count"] == 1
    assert "Prefer concise progress updates." in (memory_dir / "MEMORY.md").read_text(encoding="utf-8")


def test_chat_service_auto_maintenance_reports_decay_and_health(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)
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

    result = ChatService._auto_consolidate_memory(str(tmp_path), now="2026-05-26T10:00:00")

    assert result["decay"]["decayed_count"] == 1
    assert result["health"]["total"] == 1
    assert result["health"]["health_score"] <= 100


def test_chat_service_auto_maintenance_cleans_stale_candidates_with_lookup_policy(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)
    for candidate_id, lookup_count in (("unused", 0), ("consulted", 3)):
        pool.upsert({
            "version": pool.VERSION,
            "id": candidate_id,
            "status": "candidate",
            "target": "long_term_memory",
            "confidence": 0.4,
            "reason": "weak signal",
            "content": f"{candidate_id} stale candidate.",
            "created_at": "2026-04-01T10:00:00",
            "updated_at": "2026-04-01T10:00:00",
            "evidence_count": 1,
            "lookup_count": lookup_count,
            "sources": [],
        })

    result = ChatService._auto_consolidate_memory(str(tmp_path), now="2026-05-26T10:00:00")
    rows = {
        row["id"]: row
        for row in [json.loads(line) for line in pool.path.read_text(encoding="utf-8").splitlines()]
    }

    assert result["cleanup"]["expired_count"] == 1
    assert result["cleanup"]["kept_by_lookup_count"] == 1
    assert rows["unused"]["status"] == "expired"
    assert rows["consulted"]["status"] == "candidate"


def test_chat_service_auto_maintenance_archives_terminal_candidates(tmp_path):
    memory_dir = tmp_path / "memory"
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "old-applied",
        "status": "applied",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "terminal",
        "content": "Old applied candidate.",
        "created_at": "2026-04-01T10:00:00",
        "updated_at": "2026-04-20T10:00:00",
        "applied_at": "2026-04-20T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = ChatService._auto_consolidate_memory(str(tmp_path), now="2026-05-26T10:00:00")
    archive_path = memory_dir / "candidates" / "promotion_archive.jsonl"

    assert result["cleanup"]["archived_count"] == 1
    assert "old-applied" in archive_path.read_text(encoding="utf-8")


def test_chat_service_formats_recent_memory_rollback_for_users():
    text = ChatService._format_memory_action_result({
        "action": "rollback_latest_version",
        "code": 200,
        "payload": {"rolled_back_candidate_id": "wrong-memory"},
    })

    assert "已撤销最近写入的记忆" in text
    assert "wrong-memory" in text


def test_chat_service_formats_candidate_cleanup_for_users():
    text = ChatService._format_memory_action_result({
        "action": "cleanup_candidates",
        "code": 200,
        "payload": {"expired_count": 2, "archived_count": 1, "kept_by_lookup_count": 3},
    })

    assert "已清理候选记忆" in text
    assert "过期 2 条" in text
    assert "归档 1 条" in text
    assert "因常被查阅保留 3 条" in text


def test_chat_service_formats_targeted_forget_for_users():
    text = ChatService._format_memory_action_result({
        "action": "forget_memory",
        "code": 200,
        "payload": {"removed_count": 1, "removed_previews": ["用户偏好：回答尽量简短"]},
    })

    assert "已忘掉匹配的记忆 1 条" in text
    assert "回答尽量简短" in text
