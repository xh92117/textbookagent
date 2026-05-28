"""One-shot maintenance for existing runtime memory files."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List

from agent.memory.realtime import RealtimeMemoryRecorder
from agent.memory.retention import MemoryRetentionPolicy


class MemoryMaintenance:
    """Compact already-written memory files using the current slim rules."""

    def __init__(
        self,
        memory_dir: str | Path,
        profile_field_limit: int = 30,
        recent_focus_limit: int = 10,
        drop_process_state_files: bool = False,
        run_retention: bool = True,
        process_retention_days: int = 7,
        process_max_files: int = 60,
        session_retention_days: int = 14,
        session_max_files: int = 80,
        error_retention_days: int = 30,
        error_max_files: int = 80,
    ):
        self.memory_dir = Path(memory_dir)
        self.profile_field_limit = max(1, int(profile_field_limit or 30))
        self.recent_focus_limit = max(1, int(recent_focus_limit or 10))
        self.drop_process_state_files = bool(drop_process_state_files)
        self.run_retention_enabled = bool(run_retention)
        self.retention = MemoryRetentionPolicy(
            self.memory_dir,
            process_retention_days=process_retention_days,
            process_max_files=process_max_files,
            session_retention_days=session_retention_days,
            session_max_files=session_max_files,
            error_retention_days=error_retention_days,
            error_max_files=error_max_files,
        )

    def run(self) -> Dict[str, int]:
        result = {
            "skipped": False,
            "profile_items_removed": self._cleanup_user_profile(),
            "session_events_removed": self._cleanup_sessions(),
            "process_state_files_removed": self._cleanup_process_state_files(),
            "processes_removed": 0,
            "sessions_removed": 0,
            "errors_removed": 0,
        }
        if self.run_retention_enabled:
            result.update(self.retention.run())
        return result

    def run_if_due(self, interval_days: int = 7, now: datetime | None = None) -> Dict[str, Any]:
        now = now or datetime.now()
        interval = timedelta(days=max(1, int(interval_days or 7)))
        state_path = self.memory_dir / "maintenance_state.json"
        last_run = self._read_last_run_at(state_path)
        if last_run and now - last_run < interval:
            return {
                "skipped": True,
                "reason": "not_due",
                "last_run_at": last_run.strftime("%Y-%m-%dT%H:%M:%S"),
                "next_run_at": (last_run + interval).strftime("%Y-%m-%dT%H:%M:%S"),
            }
        result = self.run()
        result["last_run_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "last_run_at": result["last_run_at"],
            "interval_days": max(1, int(interval_days or 7)),
            "result": result,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _cleanup_user_profile(self) -> int:
        path = self.memory_dir / "user_profile.json"
        profile = self._load_json(path)
        if not profile:
            return 0
        removed = 0
        for key in ("preferences", "goals", "projects", "facts"):
            original = profile.get(key) or []
            compacted = self._dedupe_strings(original, self.profile_field_limit)
            removed += max(0, len(original) - len(compacted))
            profile[key] = compacted
        original_focus = profile.get("recent_focus") or []
        compacted_focus = self._dedupe_recent_focus(original_focus, self.recent_focus_limit)
        removed += max(0, len(original_focus) - len(compacted_focus))
        profile["recent_focus"] = compacted_focus
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        return removed

    def _cleanup_sessions(self) -> int:
        session_dir = self.memory_dir / "sessions"
        if not session_dir.exists():
            return 0
        removed = 0
        for path in session_dir.glob("*.jsonl"):
            rows = self._read_jsonl(path)
            kept = []
            seen = set()
            for row in rows:
                key = self._event_key(row)
                if key and key in seen:
                    removed += 1
                    continue
                if key:
                    seen.add(key)
                kept.append(row)
            if len(kept) != len(rows):
                path.write_text(
                    "\n".join(json.dumps(row, ensure_ascii=False) for row in kept) + ("\n" if kept else ""),
                    encoding="utf-8",
                )
        return removed

    def _cleanup_process_state_files(self) -> int:
        if not self.drop_process_state_files:
            return 0
        process_dir = self.memory_dir / "processes"
        if not process_dir.exists():
            return 0
        removed = 0
        for path in process_dir.glob("*_state.md"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        self._rewrite_process_index()
        return removed

    def _rewrite_process_index(self) -> None:
        index_path = self.memory_dir / "process_index.md"
        if not index_path.exists():
            return
        lines = []
        changed = False
        pattern = re.compile(r"`memory/processes/([^`]+)_state\.md`")
        for line in index_path.read_text(encoding="utf-8").splitlines():
            match = pattern.search(line)
            if match:
                json_path = self.memory_dir / "processes" / f"{match.group(1)}.json"
                if json_path.exists():
                    line = pattern.sub(f"`memory/processes/{match.group(1)}.json`", line)
                    changed = True
                else:
                    changed = True
                    continue
            lines.append(line)
        if changed:
            index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _dedupe_strings(self, values: Iterable[Any], limit: int) -> List[str]:
        kept: List[str] = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            key = RealtimeMemoryRecorder._normalize_profile_value(text)
            if not text or not key or key in seen:
                continue
            seen.add(key)
            kept.append(text)
        return kept[-limit:]

    def _dedupe_recent_focus(self, values: Iterable[Any], limit: int) -> List[Dict[str, Any]]:
        kept: List[Dict[str, Any]] = []
        seen = set()
        for item in values:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            key = RealtimeMemoryRecorder._normalize_for_dedupe(text)
            if not text or not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            kept.append(item)
        return kept[-limit:]

    def _event_key(self, row: Dict[str, Any]) -> str:
        role = str(row.get("role", "")).strip().lower()
        content = RealtimeMemoryRecorder._normalize_for_dedupe(str(row.get("content", "")))
        return f"{role}:{content}" if role and content else ""

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _read_last_run_at(self, path: Path) -> datetime | None:
        payload = self._load_json(path)
        raw = str(payload.get("last_run_at", "")).strip()
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
