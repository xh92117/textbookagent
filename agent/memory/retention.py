"""Retention helpers for bounded local memory storage."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Iterable, List


class MemoryRetentionPolicy:
    """Prune high-churn memory files while keeping durable profile files."""

    def __init__(
        self,
        memory_dir: str | Path,
        process_retention_days: int = 7,
        process_max_files: int = 60,
        session_retention_days: int = 14,
        session_max_files: int = 80,
        error_retention_days: int = 30,
        error_max_files: int = 80,
    ):
        self.memory_dir = Path(memory_dir)
        self.process_retention_days = max(0, int(process_retention_days or 0))
        self.process_max_files = max(0, int(process_max_files or 0))
        self.session_retention_days = max(0, int(session_retention_days or 0))
        self.session_max_files = max(0, int(session_max_files or 0))
        self.error_retention_days = max(0, int(error_retention_days or 0))
        self.error_max_files = max(0, int(error_max_files or 0))

    def run(self) -> Dict[str, int]:
        return {
            "processes_removed": self._prune_processes(),
            "sessions_removed": self._prune_plain_files(
                self.memory_dir / "sessions",
                ("*.jsonl", "*_state.md", "*_summary.md"),
                self.session_retention_days,
                self.session_max_files,
            ),
            "errors_removed": self._prune_plain_files(
                self.memory_dir / "errors",
                ("*.json",),
                self.error_retention_days,
                self.error_max_files,
            ),
        }

    def run_if_due(self, interval_hours: int = 24) -> Dict[str, int]:
        state_path = self.memory_dir / "retention_state.json"
        interval_seconds = max(1, int(interval_hours or 24)) * 3600
        now = time.time()
        if state_path.exists():
            try:
                if now - state_path.stat().st_mtime < interval_seconds:
                    return {"processes_removed": 0, "sessions_removed": 0, "errors_removed": 0}
            except OSError:
                pass
        result = self.run()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(str(int(now)), encoding="utf-8")
        return result

    def _prune_processes(self) -> int:
        process_dir = self.memory_dir / "processes"
        process_files = self._sorted_files(process_dir, ("*.json",))
        stale = self._select_stale(process_files, self.process_retention_days, self.process_max_files)
        removed = 0
        for path in stale:
            removed += self._unlink(path)
            removed += self._unlink(path.with_name(f"{path.stem}_state.md"))
        return removed

    def _prune_plain_files(
        self,
        directory: Path,
        patterns: Iterable[str],
        retention_days: int,
        max_files: int,
    ) -> int:
        files = self._sorted_files(directory, patterns)
        stale = self._select_stale(files, retention_days, max_files)
        return sum(self._unlink(path) for path in stale)

    def _select_stale(self, files: List[Path], retention_days: int, max_files: int) -> List[Path]:
        stale: List[Path] = []
        if retention_days:
            cutoff = time.time() - retention_days * 86400
            stale.extend(path for path in files if self._mtime(path) < cutoff)
        if max_files and len(files) > max_files:
            stale.extend(files[max_files:])
        return list(dict.fromkeys(stale))

    def _sorted_files(self, directory: Path, patterns: Iterable[str]) -> List[Path]:
        if not directory.exists():
            return []
        files: List[Path] = []
        for pattern in patterns:
            files.extend(path for path in directory.glob(pattern) if path.is_file())
        return sorted(files, key=self._mtime, reverse=True)

    def _mtime(self, path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def _unlink(self, path: Path) -> int:
        try:
            if path.exists():
                path.unlink()
                return 1
        except OSError:
            return 0
        return 0
