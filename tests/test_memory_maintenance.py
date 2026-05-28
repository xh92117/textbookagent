import json
from datetime import datetime, timedelta

from agent.memory.maintenance import MemoryMaintenance
from agent.memory.service import MemoryService
from agent.memory.startup_cleanup import run_startup_memory_cleanup


def test_memory_maintenance_dedupes_existing_user_profile(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "user_profile.json").write_text(json.dumps({
        "version": "user-profile-v1",
        "preferences": ["请你以后回答要简洁。", "请你 以后 回答 要 简洁", "请你以后用中文回答"],
        "goals": [],
        "projects": ["教材智能体开发与知识库增强", "教材 智能体 开发 与 知识库 增强"],
        "facts": [],
        "recent_focus": [
            {"session_id": "s1", "text": "写第一章", "time": "2026-05-27T10:00:00"},
            {"session_id": "s1", "text": "写第一章", "time": "2026-05-27T10:01:00"},
            {"session_id": "s1", "text": "写第二章", "time": "2026-05-27T10:02:00"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    result = MemoryMaintenance(memory_dir, profile_field_limit=2, recent_focus_limit=2).run()
    profile = json.loads((memory_dir / "user_profile.json").read_text(encoding="utf-8"))

    assert result["profile_items_removed"] == 3
    assert profile["preferences"] == ["请你以后回答要简洁。", "请你以后用中文回答"]
    assert profile["projects"] == ["教材智能体开发与知识库增强"]
    assert [item["text"] for item in profile["recent_focus"]] == ["写第一章", "写第二章"]


def test_memory_maintenance_dedupes_existing_session_files(tmp_path):
    session_dir = tmp_path / "memory" / "sessions"
    session_dir.mkdir(parents=True)
    rows = [
        {"role": "user", "content": "继续写第一章", "time": "2026-05-27T10:00:00"},
        {"role": "user", "content": "继续写第一章", "time": "2026-05-27T10:01:00"},
        {"role": "assistant", "content": "已完成", "time": "2026-05-27T10:02:00"},
    ]
    (session_dir / "s1.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    result = MemoryMaintenance(tmp_path / "memory").run()
    kept = [
        json.loads(line)
        for line in (session_dir / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["session_events_removed"] == 1
    assert [row["content"] for row in kept] == ["继续写第一章", "已完成"]


def test_memory_maintenance_removes_existing_process_state_files(tmp_path):
    process_dir = tmp_path / "memory" / "processes"
    process_dir.mkdir(parents=True)
    (process_dir / "p1.json").write_text("{}", encoding="utf-8")
    (process_dir / "p1_state.md").write_text("# duplicate view", encoding="utf-8")
    (tmp_path / "memory" / "process_index.md").write_text(
        "# Process Memory Index\n\n"
        "- `p1` [completed] -> `memory/processes/p1_state.md` (2026-05-27T10:00:00): demo\n",
        encoding="utf-8",
    )

    result = MemoryMaintenance(tmp_path / "memory", drop_process_state_files=True).run()

    assert result["process_state_files_removed"] == 1
    assert (process_dir / "p1.json").exists()
    assert not (process_dir / "p1_state.md").exists()
    assert "memory/processes/p1.json" in (tmp_path / "memory" / "process_index.md").read_text(encoding="utf-8")


def test_memory_service_dispatches_cleanup_runtime_memory(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "user_profile.json").write_text(json.dumps({
        "preferences": ["请你以后回答要简洁。", "请你 以后 回答 要 简洁"],
        "goals": [],
        "projects": [],
        "facts": [],
        "recent_focus": [],
    }, ensure_ascii=False), encoding="utf-8")

    result = MemoryService(str(tmp_path)).dispatch("cleanup_runtime_memory", {"profile_field_limit": 30})

    assert result["code"] == 200
    assert result["payload"]["profile_items_removed"] == 1


def test_memory_maintenance_run_if_due_skips_until_weekly_interval(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    profile_path = memory_dir / "user_profile.json"
    profile_path.write_text(json.dumps({
        "preferences": ["请你以后回答要简洁。", "请你 以后 回答 要 简洁"],
        "goals": [],
        "projects": [],
        "facts": [],
        "recent_focus": [],
    }, ensure_ascii=False), encoding="utf-8")

    maintainer = MemoryMaintenance(memory_dir)
    first = maintainer.run_if_due(interval_days=7, now=datetime(2026, 5, 27, 10, 0, 0))
    profile_path.write_text(json.dumps({
        "preferences": ["请你以后回答要简洁。", "请你 以后 回答 要 简洁"],
        "goals": [],
        "projects": [],
        "facts": [],
        "recent_focus": [],
    }, ensure_ascii=False), encoding="utf-8")
    second = maintainer.run_if_due(interval_days=7, now=datetime(2026, 5, 28, 10, 0, 0))

    assert first["skipped"] is False
    assert first["profile_items_removed"] == 1
    assert second["skipped"] is True
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert len(profile["preferences"]) == 2


def test_memory_maintenance_run_if_due_runs_after_weekly_interval(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    profile_path = memory_dir / "user_profile.json"
    profile_path.write_text(json.dumps({
        "preferences": ["请你以后回答要简洁。", "请你 以后 回答 要 简洁"],
        "goals": [],
        "projects": [],
        "facts": [],
        "recent_focus": [],
    }, ensure_ascii=False), encoding="utf-8")

    maintainer = MemoryMaintenance(memory_dir)
    maintainer.run_if_due(interval_days=7, now=datetime(2026, 5, 19, 10, 0, 0))
    profile_path.write_text(json.dumps({
        "preferences": ["请你以后回答要简洁。", "请你 以后 回答 要 简洁"],
        "goals": [],
        "projects": [],
        "facts": [],
        "recent_focus": [],
    }, ensure_ascii=False), encoding="utf-8")
    result = maintainer.run_if_due(interval_days=7, now=datetime(2026, 5, 27, 10, 0, 0))

    assert result["skipped"] is False
    assert result["profile_items_removed"] == 1


def test_startup_memory_cleanup_honors_config_and_weekly_state(tmp_path):
    system_root = tmp_path / "system"
    memory_dir = system_root / "memory"
    memory_dir.mkdir(parents=True)
    profile_path = memory_dir / "user_profile.json"
    profile_path.write_text(json.dumps({
        "preferences": ["请你以后回答要简洁。", "请你 以后 回答 要 简洁"],
        "goals": [],
        "projects": [],
        "facts": [],
        "recent_focus": [],
    }, ensure_ascii=False), encoding="utf-8")

    first = run_startup_memory_cleanup(str(system_root), {
        "memory_startup_cleanup_enabled": True,
        "memory_startup_cleanup_interval_days": 7,
    })
    profile_path.write_text(json.dumps({
        "preferences": ["请你以后回答要简洁。", "请你 以后 回答 要 简洁"],
        "goals": [],
        "projects": [],
        "facts": [],
        "recent_focus": [],
    }, ensure_ascii=False), encoding="utf-8")
    second = run_startup_memory_cleanup(str(system_root), {
        "memory_startup_cleanup_enabled": True,
        "memory_startup_cleanup_interval_days": 7,
    })

    assert first["skipped"] is False
    assert second["skipped"] is True
