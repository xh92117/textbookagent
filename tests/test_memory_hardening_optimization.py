import json
import threading

from agent.chat.service import ChatService
from agent.memory.promotion import MemoryPromotionCandidatePool
from agent.memory.service import MemoryService


def _memory(memory_dir, body):
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "MEMORY.md").write_text(body, encoding="utf-8")


def test_atomic_usage_writes_survive_parallel_updates(tmp_path):
    service = MemoryService(str(tmp_path))

    threads = [
        threading.Thread(target=service.dispatch, args=("record_usage", {"memory_key": "concise", "query": f"q{i}"}))
        for i in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    usage = json.loads((tmp_path / "memory" / "usage" / "long_term_usage.json").read_text(encoding="utf-8"))

    assert usage["concise"]["use_count"] == 8
    assert not list((tmp_path / "memory" / "usage").glob("*.tmp"))


def test_sensitive_scan_redacts_long_term_and_quarantine_files(tmp_path):
    memory_dir = tmp_path / "memory"
    _memory(
        memory_dir,
        "# MEMORY.md\n\n## Promoted Memory - 2026-05-26 10:00\n\n"
        "- Remember api_key = sk-1234567890abcdefghijklmnopqrstuvwxyz\n",
    )
    quarantine = memory_dir / "quarantine"
    quarantine.mkdir()
    (quarantine / "disabled_memories.jsonl").write_text(
        json.dumps({"content": "password: correct-horse-battery-staple"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = MemoryService(str(tmp_path)).dispatch("scan_sensitive", {})
    memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    quarantine_text = (quarantine / "disabled_memories.jsonl").read_text(encoding="utf-8")

    assert result["payload"]["redacted_count"] == 2
    assert "sk-1234567890" not in memory_text
    assert "correct-horse" not in quarantine_text
    assert "[REDACTED api_key]" in memory_text
    assert "[REDACTED password]" in quarantine_text


def test_governance_report_is_generated_for_developers(tmp_path):
    memory_dir = tmp_path / "memory"
    _memory(memory_dir, "# MEMORY.md\n")
    service = MemoryService(str(tmp_path))
    service.dispatch("record_usage", {"memory_key": "paper", "query": "写论文"})
    service.dispatch("scan_sensitive", {})

    result = service.dispatch("governance_report", {})
    report = (memory_dir / "governance_report.md").read_text(encoding="utf-8")

    assert result["code"] == 200
    assert "Memory Governance Report" in report
    assert "usage_keys: paper" in report


def test_governance_config_controls_auto_compression_threshold(tmp_path):
    memory_dir = tmp_path / "memory"
    _memory(
        memory_dir,
        "# MEMORY.md\n\n## Promoted Memory - 2026-05-26 10:00\n\n- 用户偏好：回答尽量简短。\n",
    )
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
    MemoryService(str(tmp_path)).dispatch("governance_config", {"auto_compress_health_threshold": 95})

    result = ChatService._auto_consolidate_memory(str(tmp_path))

    assert result["health_actions"]["compressed"] is True


def test_transaction_log_records_failed_and_successful_governance_actions(tmp_path):
    service = MemoryService(str(tmp_path))

    missing = service.dispatch("modify_memory", {"query": "missing", "replacement": "new"})
    service.dispatch("record_usage", {"memory_key": "paper", "query": "写论文"})
    rows = [
        json.loads(line)
        for line in (tmp_path / "memory" / "transactions" / "governance_transactions.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert missing["code"] == 404
    assert any(row["action"] == "modify_memory" and row["status"] == "failed" for row in rows)
    assert any(row["action"] == "record_usage" and row["status"] == "completed" for row in rows)


def test_chinese_synonym_matching_blocks_quarantined_memory(tmp_path):
    memory_dir = tmp_path / "memory"
    quarantine = memory_dir / "quarantine"
    quarantine.mkdir(parents=True)
    (quarantine / "disabled_memories.jsonl").write_text(
        json.dumps({"content": "用户偏好：回答尽量简短，先给结论。"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = MemoryPromotionCandidatePool(memory_dir).upsert({
        "version": MemoryPromotionCandidatePool.VERSION,
        "id": "less-noise",
        "status": "candidate",
        "target": "long_term_memory",
        "confidence": 0.9,
        "reason": "explicit",
        "content": "以后回答少废话，直接说结论。",
        "created_at": "2026-05-26T10:00:00",
        "updated_at": "2026-05-26T10:00:00",
        "evidence_count": 1,
        "sources": [],
    })

    assert result["status"] == "blocked_quarantined"


def test_compression_quality_check_reports_conflicts_after_compress(tmp_path):
    memory_dir = tmp_path / "memory"
    _memory(
        memory_dir,
        "# MEMORY.md\n\n"
        "## Promoted Memory - 2026-05-26 10:00\n\n- 用户偏好：回答尽量简短。\n\n"
        "## Promoted Memory - 2026-05-26 10:01\n\n- 用户偏好：回答要详细展开。\n",
    )

    result = MemoryService(str(tmp_path)).dispatch("compress_long_term", {"quality_check": True})

    assert result["payload"]["quality"]["conflict_count"] == 1


def test_real_chat_memory_management_routes_explain_without_agent(tmp_path):
    memory_dir = tmp_path / "memory"
    _memory(memory_dir, "# MEMORY.md\n\n## Promoted Memory - 2026-05-26 10:00\n\n- 用户偏好：回答尽量简短。\n")

    result = MemoryService(str(tmp_path)).dispatch("natural_language", {"text": "为什么你这样回答"})

    assert result["action"] == "explain"
    assert result["code"] == 200


def test_recover_transactions_restores_latest_snapshot(tmp_path):
    memory_dir = tmp_path / "memory"
    _memory(memory_dir, "# MEMORY.md\n\nOriginal\n")
    service = MemoryService(str(tmp_path))
    compressed = service.dispatch("compress_long_term", {})
    (memory_dir / "MEMORY.md").write_text("corrupted", encoding="utf-8")

    result = service.dispatch("recover_transactions", {})

    assert result["payload"]["recovered"] is True
    assert (memory_dir / "MEMORY.md").read_text(encoding="utf-8") != "corrupted"
