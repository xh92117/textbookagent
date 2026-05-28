from pathlib import Path

from agent.memory.index_policy import MemoryIndexPolicy


def test_index_policy_skips_runtime_logs_and_caches():
    skipped = [
        "memory/processes/p1.json",
        "memory/processes/p1_state.md",
        "memory/process_index.md",
        "memory/errors/e1.json",
        "memory/short_term/s1.json",
        "memory/candidates/promotion_candidates.jsonl",
        "memory/graph/memory_graph.db",
        "memory/cache/tmp.json",
        "system/maintenance_backups/old/memory/user_profile.json",
    ]

    for path in skipped:
        assert MemoryIndexPolicy.should_index_path(Path(path)) is False


def test_index_policy_allows_authoritative_memory_and_project_sources():
    allowed = [
        "memory/MEMORY.md",
        "memory/user_profile.json",
        "memory/user_profile.md",
        "memory/2026-05-25.md",
        "memory/sessions/s1/handoff.md",
        "textbooks/tb_demo/state/status.json",
        "textbooks/tb_demo/snapshots/s1/state/status.json",
        "textbooks/tb_demo/outline/outline.md",
        "textbooks/tb_demo/chapters/chapter_001.md",
        "knowledge/tb_demo/chunks/k1.md",
        "USER.md",
        "RULE.md",
    ]

    for path in allowed:
        assert MemoryIndexPolicy.should_index_path(Path(path)) is True
