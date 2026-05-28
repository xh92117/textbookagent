import os
import time

from agent.memory.retention import MemoryRetentionPolicy


def _touch(path, offset_seconds):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.name, encoding="utf-8")
    stamp = time.time() + offset_seconds
    os.utime(path, (stamp, stamp))


def test_retention_prunes_process_pairs_by_max_files(tmp_path):
    memory_dir = tmp_path / "memory"
    _touch(memory_dir / "processes" / "old.json", -30)
    _touch(memory_dir / "processes" / "old_state.md", -30)
    _touch(memory_dir / "processes" / "new.json", -10)
    _touch(memory_dir / "processes" / "new_state.md", -10)

    result = MemoryRetentionPolicy(memory_dir, process_max_files=1).run()

    assert result["processes_removed"] == 2
    assert not (memory_dir / "processes" / "old.json").exists()
    assert not (memory_dir / "processes" / "old_state.md").exists()
    assert (memory_dir / "processes" / "new.json").exists()


def test_retention_prunes_session_and_error_files_by_max_files(tmp_path):
    memory_dir = tmp_path / "memory"
    _touch(memory_dir / "sessions" / "old.jsonl", -30)
    _touch(memory_dir / "sessions" / "new.jsonl", -10)
    _touch(memory_dir / "errors" / "old.json", -30)
    _touch(memory_dir / "errors" / "new.json", -10)

    result = MemoryRetentionPolicy(
        memory_dir,
        session_max_files=1,
        error_max_files=1,
    ).run()

    assert result["sessions_removed"] == 1
    assert result["errors_removed"] == 1
    assert not (memory_dir / "sessions" / "old.jsonl").exists()
    assert (memory_dir / "sessions" / "new.jsonl").exists()
    assert not (memory_dir / "errors" / "old.json").exists()
    assert (memory_dir / "errors" / "new.json").exists()
