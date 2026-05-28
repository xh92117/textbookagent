"""Session handoff artifacts for compact, isolated conversation memory."""

from __future__ import annotations

import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List


class HandoffService:
    """Create compact handoff files from recent session messages."""

    def __init__(self, system_root: str, ttl_hours: int = 168):
        self.system_root = Path(system_root)
        self.memory_dir = self.system_root / "memory"
        self.ttl_hours = max(1, int(ttl_hours or 168))

    def update_from_messages(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        now: str | None = None,
    ) -> Path:
        safe_session = self._safe_session_id(session_id)
        handoff_dir = self.memory_dir / "sessions" / safe_session
        handoff_dir.mkdir(parents=True, exist_ok=True)
        path = handoff_dir / "handoff.md"

        payload = self.build_from_messages(session_id, messages, now=now)
        path.write_text(self._format_handoff(payload), encoding="utf-8")
        return path

    def read_handoff(self, session_id: str, now: str | None = None) -> Dict[str, Any]:
        path = self.memory_dir / "sessions" / self._safe_session_id(session_id) / "handoff.md"
        if not path.exists():
            return {}
        content = path.read_text(encoding="utf-8")
        if self._content_expired(content, now=now):
            return {}
        return {"session_id": session_id, "path": str(path), "content": content}

    def archive_expired(self, now: str | None = None) -> Dict[str, Any]:
        sessions_dir = self.memory_dir / "sessions"
        archive_root = self.memory_dir / "sessions_archive"
        archived: List[str] = []
        if not sessions_dir.exists():
            return {"archived_count": 0, "archived": archived}
        for path in sessions_dir.glob("*/handoff.md"):
            content = path.read_text(encoding="utf-8")
            if not self._content_expired(content, now=now):
                continue
            session_id = path.parent.name
            updated = self._extract_header(content, "Updated") or self._now_iso()
            stamp = re.sub(r"[^0-9T]", "", updated)[:15] or self._now_iso().replace("-", "").replace(":", "")
            target_dir = archive_root / session_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"handoff_{stamp}.md"
            suffix = 1
            while target.exists():
                target = target_dir / f"handoff_{stamp}_{suffix}.md"
                suffix += 1
            shutil.move(str(path), str(target))
            archived.append(target.as_posix())
        return {"archived_count": len(archived), "archived": archived}

    def build_from_messages(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        now: str | None = None,
    ) -> Dict[str, Any]:
        texts = [self._message_text(msg) for msg in messages or []]
        texts = [self._redact(text) for text in texts if text.strip()]
        all_text = "\n".join(texts)
        user_texts = [
            self._redact(self._message_text(msg, include_tools=False))
            for msg in messages or []
            if msg.get("role") == "user" and self._message_text(msg, include_tools=False).strip()
        ]
        assistant_texts = [
            self._redact(self._message_text(msg, include_tools=False))
            for msg in messages or []
            if msg.get("role") == "assistant" and self._message_text(msg, include_tools=False).strip()
        ]
        task_text = "\n".join(user_texts + assistant_texts)
        goal = self._clip(user_texts[-1] if user_texts else (texts[-1] if texts else ""), 220)
        completed = self._bulletize(assistant_texts[-2:], max_items=3, max_chars=180)
        next_actions = self._next_actions(task_text)
        if not next_actions and goal:
            next_actions = [f"Continue current user goal: {self._clip(goal, 140)}"]
        refs = self._evidence_refs(all_text)
        retrieval = self._suggested_retrieval(goal, refs)
        updated_at = self._normalize_iso(now) or self._now_iso()
        expires_at = self._add_hours(updated_at, self.ttl_hours)
        return {
            "session_id": self._safe_session_id(session_id),
            "updated_at": updated_at,
            "current_goal": goal,
            "active_constraints": self._constraints(all_text),
            "current_done": completed or ["No completed work was captured before compaction."],
            "todo": next_actions or ["Continue from the current goal after verifying current state."],
            "completed_work": completed,
            "open_threads": self._open_threads(all_text),
            "next_actions": next_actions,
            "evidence_refs": refs,
            "suggested_retrieval": retrieval,
            "expires_at": expires_at,
        }

    def _format_handoff(self, payload: Dict[str, Any]) -> str:
        lines = [
            "# Session Handoff",
            "",
            f"Session: {payload.get('session_id', '')}",
            f"Updated: {payload.get('updated_at', '')}",
            "Aliases: 继续上次 接着做 resume previous handoff session",
            "",
            "## Current Goal",
            payload.get("current_goal", "") or "-",
            "",
            "## Active Constraints",
            *self._format_list(payload.get("active_constraints") or ["Keep this handoff compact and reference artifacts instead of copying full content."]),
            "",
            "## Current Done",
            *self._format_list(payload.get("current_done") or ["No completed work was captured before compaction."]),
            "",
            "## Todo",
            *self._format_list(payload.get("todo") or ["Continue from the current goal after verifying current state."]),
            "",
            "## Completed Work",
            *self._format_list(payload.get("completed_work") or ["-"]),
            "",
            "## Open Threads",
            *self._format_list(payload.get("open_threads") or ["-"]),
            "",
            "## Next Actions",
            *self._format_list(payload.get("next_actions") or ["Continue from the current goal."]),
            "",
            "## Evidence Refs",
            *self._format_list(payload.get("evidence_refs") or ["-"]),
            "",
            "## Suggested Retrieval",
            *self._format_list(payload.get("suggested_retrieval") or ["memory_search: query=\"继续上次\""]),
            "",
            "## Expires At",
            payload.get("expires_at", "") or "-",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_list(items: Iterable[str]) -> List[str]:
        result = []
        for item in items:
            text = str(item or "").strip()
            if not text:
                continue
            result.append(text if text.startswith("- ") else f"- {text}")
        return result or ["- -"]

    @classmethod
    def _message_text(cls, msg: Dict[str, Any], include_tools: bool = True) -> str:
        content = msg.get("content", "")
        if isinstance(content, str):
            return cls._strip_injected_boards(content).strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append(cls._strip_injected_boards(str(block.get("text", ""))))
                elif include_tools and block.get("type") == "tool_result":
                    raw = str(block.get("content", ""))
                    first = re.sub(r"\s+", " ", raw).strip()[:240]
                    parts.append(f"tool_result:{block.get('tool_use_id', '')} {first}")
                elif include_tools and block.get("type") == "tool_use":
                    parts.append(cls._clip(f"tool:{block.get('name', '')} {block.get('input', {})}", 320))
            return "\n".join(part for part in parts if part).strip()
        return ""

    @staticmethod
    def _strip_injected_boards(text: str) -> str:
        """Remove injected system boards before handoff goal/todo extraction."""
        value = str(text or "").strip()
        if not value:
            return ""
        board_markers = (
            "[System: Runtime Context Board]",
            "[System: Tool routing policy]",
            "[System: Short-term working memory]",
            "[System: Current task state board]",
            "[System: Context Compression Handoff]",
            "[System: Context Compression Summary]",
            "[Compacted Context Summary]",
        )
        changed = True
        while changed:
            changed = False
            stripped = value.lstrip()
            for marker in board_markers:
                if not stripped.startswith(marker):
                    continue
                separator = re.search(r"\n\s*---\s*\n", stripped)
                if separator:
                    value = stripped[separator.end():].strip()
                else:
                    lines = stripped.splitlines()
                    value = "\n".join(lines[1:]).strip()
                changed = True
                break
        return value

    @staticmethod
    def _safe_session_id(session_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "default")).strip("._")
        return safe[:80] or "default"

    @staticmethod
    def _clip(text: str, max_chars: int) -> str:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        return text if len(text) <= max_chars else text[: max_chars - 3].rstrip() + "..."

    @classmethod
    def _bulletize(cls, items: List[str], max_items: int, max_chars: int) -> List[str]:
        return [cls._clip(item, max_chars) for item in items if item.strip()][:max_items]

    @classmethod
    def _next_actions(cls, text: str) -> List[str]:
        pattern = r"下一步|接下来|待办|继续|开始|todo|next action|next step"
        actions = []
        for line in str(text or "").splitlines():
            stripped = line.strip(" -\t")
            if stripped and re.search(pattern, stripped, re.IGNORECASE):
                actions.append(cls._clip(stripped, 180))
        return actions[:5]

    @classmethod
    def _constraints(cls, text: str) -> List[str]:
        constraints = []
        for line in str(text or "").splitlines():
            stripped = line.strip(" -\t")
            if re.search(r"不要|必须|只能|不能|约束|忽略|跳过|constraint|must|never|only", stripped, re.IGNORECASE):
                constraints.append(cls._clip(stripped, 180))
        return constraints[:4]

    @classmethod
    def _open_threads(cls, text: str) -> List[str]:
        threads = []
        for line in str(text or "").splitlines():
            stripped = line.strip(" -\t")
            if re.search(r"待办|未完成|问题|风险|阻塞|blocker|risk|open", stripped, re.IGNORECASE):
                threads.append(cls._clip(stripped, 180))
        return threads[:4]

    @classmethod
    def _evidence_refs(cls, text: str) -> List[str]:
        refs = []
        for path in re.findall(r"(?<![\w/\\.-])[\w./\\-]+\.(?:py|md|json|jsonl|toml|yaml|yml|txt)", text or ""):
            refs.append(f"file: {path.replace('\\', '/')}")
        for commit in re.findall(r"\b[0-9a-f]{7,40}\b", text or "", re.IGNORECASE):
            refs.append(f"commit: {commit}")
        for command in re.findall(r"(pytest[^\n\r]*?(?:passed|failed|error|warnings?))", text or "", re.IGNORECASE):
            refs.append(f"test: {cls._clip(command, 160)}")
        for entity in re.findall(r"\b(?:textbook|session|memory|knowledge):[A-Za-z0-9:_./-]+", text or ""):
            refs.append(f"graph: {entity}")
        return cls._dedupe(refs)[:10]

    @classmethod
    def _suggested_retrieval(cls, goal: str, refs: List[str]) -> List[str]:
        query = cls._clip(goal or "继续上次", 80).replace('"', "'")
        suggestions = [
            f'memory_graph_context: query="{query}"',
            f'memory_search: query="{query}"',
        ]
        for ref in refs:
            if ref.startswith("file: "):
                suggestions.append(f"read: {ref[6:]}")
        return cls._dedupe(suggestions)[:6]

    @staticmethod
    def _dedupe(items: Iterable[str]) -> List[str]:
        seen = set()
        result = []
        for item in items:
            text = str(item or "").strip()
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    @staticmethod
    def _redact(text: str) -> str:
        value = str(text or "")
        patterns = [
            r"sk-[A-Za-z0-9_\-]{8,}",
            r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+",
        ]
        for pattern in patterns:
            value = re.sub(pattern, "[REDACTED]", value)
        return value

    @staticmethod
    def _now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S")

    @classmethod
    def _normalize_iso(cls, value: str | None) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(str(value)).replace(microsecond=0).isoformat()
        except Exception:
            return ""

    @classmethod
    def _add_hours(cls, value: str, hours: int) -> str:
        try:
            return (datetime.fromisoformat(value) + timedelta(hours=hours)).replace(microsecond=0).isoformat()
        except Exception:
            return ""

    @classmethod
    def _content_expired(cls, content: str, now: str | None = None) -> bool:
        expires_at = cls._extract_section_value(content, "Expires At")
        if not expires_at or expires_at == "-":
            return False
        current = cls._normalize_iso(now) or cls._now_iso()
        try:
            return datetime.fromisoformat(current) >= datetime.fromisoformat(expires_at)
        except Exception:
            return False

    @staticmethod
    def _extract_header(content: str, name: str) -> str:
        for line in str(content or "").splitlines():
            if line.startswith(f"{name}:"):
                return line.split(":", 1)[1].strip()
        return ""

    @staticmethod
    def _extract_section_value(content: str, section: str) -> str:
        lines = str(content or "").splitlines()
        for idx, line in enumerate(lines):
            if line.strip() != f"## {section}":
                continue
            for value in lines[idx + 1:]:
                stripped = value.strip()
                if stripped.startswith("## "):
                    return ""
                if stripped:
                    return stripped[2:].strip() if stripped.startswith("- ") else stripped
        return ""


def update_session_handoff_after_persist(
    system_root: str,
    session_id: str,
    messages: List[Dict[str, Any]],
    project_workspace: str = "",
) -> Path | None:
    if not session_id or not messages:
        return None
    ttl_hours = 168
    try:
        from config import conf

        ttl_hours = int(conf().get("session_handoff_ttl_hours", 168) or 168)
    except Exception:
        ttl_hours = 168
    service = HandoffService(system_root, ttl_hours=ttl_hours)
    archived = service.archive_expired()
    path = service.update_from_messages(session_id, messages)
    try:
        from agent.memory.graph import MemoryGraphService

        graph = MemoryGraphService(system_root, project_workspace=project_workspace)
        try:
            graph.mark_dirty(
                "session handoff updated",
                source_path=str(path),
                entity_key=f"session:{HandoffService._safe_session_id(session_id)}:handoff",
            )
            if archived.get("archived_count"):
                graph.mark_dirty("expired session handoff archived")
        finally:
            graph.close()
    except Exception:
        pass
    return path
