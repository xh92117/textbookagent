"""
Unified read-only memory query service.

The memory system currently has several useful stores:
- process memories under ``memory/processes``
- user profile files under ``memory/user_profile.*``
- SQLite conversation history through ``ConversationStore``
- legacy textbook chat JSON files under ``chat_history``

This service keeps those sources queryable through one small API without
injecting the full history back into model context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory.conversation_store import ConversationStore, get_conversation_store


class MemoryQueryService:
    def __init__(
        self,
        workspace_root: str | Path,
        conversation_store: Optional[ConversationStore] = None,
    ):
        self.workspace_root = Path(workspace_root)
        self.memory_dir = self.workspace_root / "memory"
        self.process_dir = self.memory_dir / "processes"
        self.chat_history_dir = self.workspace_root / "chat_history"
        self.conversation_store = conversation_store or get_conversation_store()

    def query(
        self,
        session_id: str = "",
        process_id: str = "",
        page: int = 1,
        page_size: int = 20,
        include_textbook_history: bool = True,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "profile": self.load_profile(),
            "processes": self.list_processes(limit=20),
        }
        if process_id:
            result["process"] = self.get_process(process_id)
        if session_id:
            result["history"] = self.conversation_store.load_history_page(
                session_id=session_id,
                page=page,
                page_size=page_size,
            )
            if include_textbook_history:
                result["textbook_history"] = self.load_textbook_chat_history(
                    session_id=session_id,
                    page=page,
                    page_size=page_size,
                )
        return result

    def load_profile(self) -> Dict[str, Any]:
        return self._read_json(self.memory_dir / "user_profile.json", default={})

    def list_processes(self, limit: int = 20) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if not self.process_dir.exists():
            return items
        for path in self.process_dir.glob("*.json"):
            payload = self._read_json(path, default={})
            if not payload:
                continue
            items.append({
                "process_id": payload.get("process_id", path.stem),
                "session_id": payload.get("session_id", ""),
                "status": payload.get("status", ""),
                "started_at": payload.get("started_at", ""),
                "updated_at": payload.get("updated_at", ""),
                "ended_at": payload.get("ended_at", ""),
                "summary": self._first_line(payload.get("user_message", "")),
                "event_count": len(payload.get("events") or []),
            })
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return items[: max(1, limit)]

    def get_process(self, process_id: str) -> Dict[str, Any]:
        if not process_id:
            return {}
        safe = self._safe_id(process_id)
        direct = self.process_dir / f"{safe}.json"
        if direct.exists():
            return self._read_json(direct, default={})
        if not self.process_dir.exists():
            return {}
        for path in self.process_dir.glob("*.json"):
            payload = self._read_json(path, default={})
            if payload.get("process_id") == process_id:
                return payload
        return {}

    def load_textbook_chat_history(
        self,
        session_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        path = self.chat_history_dir / f"{session_id}.json"
        messages = self._read_json(path, default=[])
        if not isinstance(messages, list):
            messages = []
        page = max(1, page)
        page_size = max(1, min(200, page_size))
        total = len(messages)
        offset = (page - 1) * page_size
        page_items = list(reversed(messages))[offset: offset + page_size]
        page_items = list(reversed(page_items))
        return {
            "messages": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        }

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    @staticmethod
    def _safe_id(value: str) -> str:
        import re
        import time

        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "default").strip("._")
        return safe or f"session_{int(time.time())}"

    @staticmethod
    def _first_line(text: str, max_chars: int = 180) -> str:
        for line in (text or "").splitlines():
            line = line.strip()
            if line:
                return line if len(line) <= max_chars else line[:max_chars].rstrip() + "..."
        return ""
