import json

from agent.memory.intent import MemoryIntentRouter
from agent.memory.promotion import MemoryPromotionCandidatePool
from agent.memory.service import MemoryService


def test_memory_intent_router_detects_candidate_actions():
    assert MemoryIntentRouter.route("查看候选记忆")["action"] == "candidates"
    assert MemoryIntentRouter.route("整理候选记忆")["action"] == "consolidate"
    assert MemoryIntentRouter.route("应用所有待审查记忆")["action"] == "apply_ready_candidates"
    assert MemoryIntentRouter.route("把候选 c1 写入长期记忆") == {
        "action": "apply_candidate",
        "payload": {"id": "c1"},
    }
    assert MemoryIntentRouter.route("继续写第三章") is None


def test_memory_service_handles_natural_language_candidate_query(tmp_path):
    pool = MemoryPromotionCandidatePool(tmp_path / "memory")
    pool.upsert({
        "version": pool.VERSION,
        "id": "c1",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "Review stable memory before promotion.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    result = MemoryService(str(tmp_path)).dispatch("natural_language", {"text": "查看候选记忆"})

    assert result["code"] == 200
    assert result["action"] == "candidates"
    assert result["payload"]["total"] == 1


def test_memory_service_applies_all_ready_candidates_from_natural_language(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    for candidate_id, content in (
        ("c1", "First reviewed memory."),
        ("c2", "Second reviewed memory."),
    ):
        pool.upsert({
            "version": pool.VERSION,
            "id": candidate_id,
            "status": "candidate",
            "target": "long_term_memory",
            "confidence": 0.9,
            "reason": "explicit",
            "content": content,
            "created_at": "2026-05-26T10:00:00",
            "updated_at": "2026-05-26T10:00:00",
            "evidence_count": 1,
            "sources": [],
        })
    pool.consolidate()

    result = MemoryService(str(tmp_path)).dispatch("natural_language", {"text": "应用所有待审查记忆"})
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    rows = [
        json.loads(line)
        for line in (memory_dir / "candidates" / "promotion_candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["code"] == 200
    assert result["action"] == "apply_ready_candidates"
    assert result["payload"]["applied_count"] == 2
    assert "First reviewed memory." in memory_text
    assert "Second reviewed memory." in memory_text
    assert {row["status"] for row in rows} == {"applied"}


def test_memory_service_ignores_unrelated_natural_language(tmp_path):
    result = MemoryService(str(tmp_path)).dispatch("natural_language", {"text": "继续写第三章"})

    assert result["code"] == 204
    assert result["payload"] is None


def test_memory_intent_router_detects_candidate_cleanup():
    assert MemoryIntentRouter.route("清理候选记忆")["action"] == "cleanup_candidates"


def test_memory_intent_router_detects_conflict_resolution():
    assert MemoryIntentRouter.route("keep candidate concise-rule reject candidate detailed-rule") == {
        "action": "resolve_conflict",
        "payload": {"keep_id": "concise-rule", "reject_id": "detailed-rule"},
    }


def test_memory_service_resolves_conflict_from_natural_language(tmp_path):
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
        "natural_language",
        {"text": "keep candidate concise-rule reject candidate detailed-rule"},
    )
    rows = {
        row["id"]: row
        for row in [
            json.loads(line)
            for line in (tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        ]
    }

    assert result["code"] == 200
    assert result["action"] == "resolve_conflict"
    assert rows["concise-rule"]["status"] == "ready_for_review"
    assert rows["detailed-rule"]["status"] == "rejected"


def test_memory_intent_router_detects_version_rollback():
    assert MemoryIntentRouter.route("rollback version memver-202605261200000000-c1") == {
        "action": "rollback_version",
        "payload": {"version_id": "memver-202605261200000000-c1"},
    }


def test_memory_service_rolls_back_version_from_natural_language(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "rollback-nl",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.95,
        "reason": "explicit",
        "content": "Rollback from natural language.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    pool.consolidate()
    applied = pool.apply_candidate("rollback-nl")

    result = MemoryService(str(tmp_path)).dispatch(
        "natural_language",
        {"text": f"rollback version {applied['version_id']}"},
    )

    assert result["code"] == 200
    assert result["action"] == "rollback_version"
    assert (memory_dir / "MEMORY.md").read_text(encoding="utf-8") == "# MEMORY.md\n"


def test_memory_intent_router_detects_recent_memory_correction():
    assert MemoryIntentRouter.route("你记错了，删掉刚才那条记忆") == {
        "action": "rollback_latest_version",
        "payload": {},
    }


def test_memory_service_rolls_back_latest_version_from_correction_language(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    pool = MemoryPromotionCandidatePool(memory_dir)
    pool.upsert({
        "version": pool.VERSION,
        "id": "wrong-memory",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.95,
        "reason": "explicit",
        "content": "Wrong durable memory.",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })
    pool.consolidate()
    pool.apply_candidate("wrong-memory")

    result = MemoryService(str(tmp_path)).dispatch(
        "natural_language",
        {"text": "你记错了，删掉刚才那条记忆"},
    )

    assert result["code"] == 200
    assert result["action"] == "rollback_latest_version"
    assert (memory_dir / "MEMORY.md").read_text(encoding="utf-8") == "# MEMORY.md\n"


def test_memory_intent_router_detects_targeted_forget_request():
    assert MemoryIntentRouter.route("忘掉简短回答这个记忆") == {
        "action": "forget_memory",
        "payload": {"query": "忘掉简短回答这个记忆"},
    }


def test_memory_service_forgets_matching_promoted_memory_from_natural_language(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text(
        "# MEMORY.md\n\n"
        "## Promoted Memory - 2026-05-26 10:00\n\n"
        "- 用户偏好：回答尽量简短，先给结论。\n"
        "  - source: candidate `concise`; evidence_count=2\n\n"
        "## Promoted Memory - 2026-05-26 10:05\n\n"
        "- 用户偏好：涉及代码时给出测试命令。\n"
        "  - source: candidate `tests`; evidence_count=2\n",
        encoding="utf-8",
    )

    result = MemoryService(str(tmp_path)).dispatch(
        "natural_language",
        {"text": "忘掉简短回答这个记忆"},
    )
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    assert result["code"] == 200
    assert result["action"] == "forget_memory"
    assert result["payload"]["removed_count"] == 1
    assert "回答尽量简短" not in memory_text
    assert "涉及代码时给出测试命令" in memory_text
