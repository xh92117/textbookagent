from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


class ShortTermMemoryPool:
    """Session-scoped working memory for recovering active task state.

    It stores structured events on disk, keeps recent details, and rolls older
    events into a compact summary. Only the compact state is injected into the
    model context.
    """

    VERSION = "short-term-memory-v1"

    def __init__(
        self,
        system_root: str,
        session_id: str,
        max_events: int = 200,
        keep_events: int = 50,
        retention_days: int = 14,
        max_files: int = 30,
    ):
        self.system_root = Path(system_root)
        self.session_id = session_id or "default"
        self.max_events = max(20, int(max_events or 200))
        self.keep_events = max(10, int(keep_events or 50))
        self.retention_days = max(1, int(retention_days or 14))
        self.max_files = max(5, int(max_files or 30))
        self.root = self.system_root / "memory" / "short_term"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / f"{self._safe_id(self.session_id)}.json"
        self._cleanup_old_files()

    def record_user_goal(self, text: str, channel_type: str = "") -> None:
        payload = self._load()
        payload["session_id"] = self.session_id
        if channel_type:
            payload["channel_type"] = channel_type
        if text:
            payload["current_goal"] = self._clip(text, 800)
        self._append_event(payload, {
            "type": "user_goal",
            "summary": self._first_line(text, 300),
            "text": self._clip(text, 1200),
        })
        self._save(payload)

    def record_tool_start(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        payload = self._load()
        self._append_event(payload, {
            "type": "tool_start",
            "tool": tool_name,
            "summary": self._summarize_tool_args(tool_name, arguments),
        })
        self._update_from_tool(payload, tool_name, arguments, status="started")
        self._save(payload)

    def record_tool_end(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        status: str,
        result: Any,
    ) -> None:
        payload = self._load()
        result_summary = self._summarize_result(tool_name, result, status)
        event_type = "failure" if status != "success" else "tool_end"
        self._append_event(payload, {
            "type": event_type,
            "tool": tool_name,
            "status": status,
            "summary": result_summary,
        })
        self._update_from_tool(payload, tool_name, arguments, status=status, result=result)
        self._save(payload)

    def record_final_response(self, text: str) -> None:
        payload = self._load()
        if text:
            payload["latest_assistant"] = self._clip(text, 1000)
            self._append_event(payload, {
                "type": "assistant_final",
                "summary": self._first_line(text, 300),
            })
        self._save(payload)

    def compact_prompt(self, max_events: int = 12) -> str:
        payload = self._load()
        if not payload.get("events") and not payload.get("summary"):
            return ""
        state = {
            "session_id": self.session_id,
            "current_goal": payload.get("current_goal", ""),
            "active_book_id": payload.get("active_book_id", ""),
            "active_chapter": payload.get("active_chapter", ""),
            "next_step": payload.get("next_step", "continue from the latest unfinished action"),
            "read_files": payload.get("read_files", [])[-8:],
            "written_files": payload.get("written_files", [])[-8:],
            "failures": payload.get("failures", [])[-6:],
        }
        lines = [
            "[System: Short-term working memory]",
            "This is the current session's working memory. Use it to preserve local task continuity without re-reading old chat turns.",
            "```json",
            json.dumps(state, ensure_ascii=False, indent=2),
            "```",
        ]
        if payload.get("summary"):
            lines.extend(["Rolled-up prior events:", payload["summary"]])
        events = payload.get("events", [])[-max_events:]
        if events:
            lines.append("Recent working events:")
            for event in events:
                bits = [
                    event.get("time", ""),
                    event.get("type", ""),
                    event.get("tool", ""),
                    event.get("status", ""),
                    event.get("summary", ""),
                ]
                lines.append("- " + " | ".join(str(x) for x in bits if x))
        return "\n".join(lines)

    def _load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("version", self.VERSION)
                    data.setdefault("events", [])
                    return data
            except Exception:
                pass
        now = datetime.now().isoformat()
        return {
            "version": self.VERSION,
            "session_id": self.session_id,
            "created_at": now,
            "updated_at": now,
            "current_goal": "",
            "latest_assistant": "",
            "active_book_id": "",
            "active_chapter": "",
            "next_step": "continue from the latest unfinished action",
            "read_files": [],
            "written_files": [],
            "failures": [],
            "summary": "",
            "events": [],
        }

    def _save(self, payload: Dict[str, Any]) -> None:
        payload["updated_at"] = datetime.now().isoformat()
        events = payload.get("events", [])
        if len(events) > self.max_events:
            archive = events[:-self.keep_events]
            payload["events"] = events[-self.keep_events:]
            payload["summary"] = self._rollup_summary(payload.get("summary", ""), archive)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_event(self, payload: Dict[str, Any], event: Dict[str, Any]) -> None:
        event["time"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        payload.setdefault("events", []).append(event)

    def _update_from_tool(
        self,
        payload: Dict[str, Any],
        tool_name: str,
        arguments: Dict[str, Any],
        status: str = "",
        result: Any = None,
    ) -> None:
        arguments = arguments or {}
        book_id = str(arguments.get("book_id") or "")
        chapter = str(arguments.get("chapter_num") or arguments.get("chapter_number") or "")
        if book_id:
            payload["active_book_id"] = book_id
        if chapter:
            payload["active_chapter"] = chapter
        path = str(arguments.get("path") or arguments.get("file_path") or "")
        if tool_name in ("read", "file_read") and path:
            self._append_unique(payload, "read_files", path, 40)
        if tool_name in ("write", "edit", "file_write") and path:
            self._append_unique(payload, "written_files", path, 40)
        if tool_name == "textbook_chapter":
            action = str(arguments.get("action") or "")
            if action:
                payload["next_step"] = f"textbook_chapter {action} completed; continue next unfinished chapter action"
            result_path = self._extract_path_from_result(result)
            if result_path:
                self._append_unique(payload, "written_files", result_path, 40)
        if status and status != "success":
            failure = f"{tool_name}: {self._summarize_result(tool_name, result, status)}"
            self._append_unique(payload, "failures", failure, 30)

    @staticmethod
    def _append_unique(payload: Dict[str, Any], key: str, value: str, limit: int) -> None:
        items = payload.setdefault(key, [])
        if value and value not in items:
            items.append(value)
        payload[key] = items[-limit:]

    @classmethod
    def _rollup_summary(cls, existing: str, events: List[Dict[str, Any]]) -> str:
        lines = [line for line in (existing or "").splitlines() if line.strip()]
        for event in events[-80:]:
            summary = event.get("summary") or ""
            if summary:
                lines.append(f"- {event.get('time', '')} {event.get('type', '')}: {cls._clip(summary, 180)}")
        return "\n".join(lines[-80:])

    @classmethod
    def _summarize_tool_args(cls, tool_name: str, arguments: Dict[str, Any]) -> str:
        arguments = arguments or {}
        if tool_name in ("read", "file_read", "write", "edit", "file_write"):
            return f"{tool_name}: {arguments.get('path') or arguments.get('file_path') or ''}"
        if tool_name == "textbook_chapter":
            return (
                f"textbook_chapter action={arguments.get('action', '')} "
                f"book={arguments.get('book_id', '')} ch={arguments.get('chapter_num', '')}"
            )
        if tool_name == "bash":
            return cls._clip(str(arguments.get("command", "")), 300)
        if tool_name in ("web_fetch", "web_search"):
            return cls._clip(str(arguments.get("url") or arguments.get("query") or arguments), 300)
        return cls._clip(json.dumps(arguments, ensure_ascii=False), 300)

    @classmethod
    def _summarize_result(cls, tool_name: str, result: Any, status: str = "") -> str:
        if isinstance(result, (dict, list)):
            text = json.dumps(result, ensure_ascii=False)
        else:
            text = str(result or "")
        first = cls._first_line(text, 300)
        if tool_name == "textbook_chapter":
            path = cls._extract_path_from_result(result)
            return f"{status}: {path or first}"
        return f"{status}: {first}" if status else first

    @staticmethod
    def _extract_path_from_result(result: Any) -> str:
        if isinstance(result, dict):
            for key in ("path", "file_path", "chapter_path", "output_path"):
                value = result.get(key)
                if value:
                    return str(value)
        text = result if isinstance(result, str) else ""
        match = re.search(r"([A-Za-z]:\\[^\\/:*?\"<>|\r\n]+(?:\\[^\\/:*?\"<>|\r\n]+)+)", text)
        return match.group(1) if match else ""

    def _cleanup_old_files(self) -> None:
        files = [p for p in self.root.glob("*.json") if p.is_file()]
        now = time.time()
        cutoff = now - self.retention_days * 86400
        for path in files:
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except Exception:
                pass
        files = sorted(
            [p for p in self.root.glob("*.json") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in files[self.max_files:]:
            try:
                path.unlink()
            except Exception:
                pass

    @staticmethod
    def _safe_id(session_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id or "default").strip("._")
        return safe or "default"

    @staticmethod
    def _first_line(text: str, max_chars: int = 180) -> str:
        for line in str(text or "").splitlines():
            line = line.strip()
            if line:
                return ShortTermMemoryPool._clip(line, max_chars)
        return ""

    @staticmethod
    def _clip(text: str, max_chars: int) -> str:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        return text if len(text) <= max_chars else text[:max_chars].rstrip() + "..."
