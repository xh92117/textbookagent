"""Recent process-memory recall for activity/history questions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


class RecentActivityMemory:
    """Read recent process logs without adding them to the generic search index."""

    @staticmethod
    def is_activity_query(text: str) -> bool:
        value = re.sub(r"\s+", "", str(text or "").lower())
        if not value:
            return False
        recent_markers = (
            "recent",
            "previous",
            "last",
            "earlier",
            "\u521a\u624d",
            "\u521a\u521a",
            "\u4e4b\u524d",
            "\u4e0a\u6b21",
            "\u6700\u8fd1",
            "\u524d\u9762",
        )
        activity_markers = (
            "whatdidyoudo",
            "whatwasdone",
            "done",
            "\u505a\u4e86\u4ec0\u4e48",
            "\u505a\u8fc7\u4ec0\u4e48",
            "\u5e72\u4e86\u4ec0\u4e48",
            "\u5b8c\u6210\u4e86\u4ec0\u4e48",
            "\u4fee\u6539\u4e86\u4ec0\u4e48",
            "\u66f4\u65b0\u4e86\u4ec0\u4e48",
            "\u5904\u7406\u4e86\u4ec0\u4e48",
            "\u54ea\u4e9b\u4e8b",
            "\u54ea\u4e9b\u5de5\u4f5c",
        )
        return any(marker in value for marker in recent_markers) and any(marker in value for marker in activity_markers)

    def __init__(self, system_root: str | Path):
        self.system_root = Path(system_root)
        self.memory_dir = self.system_root / "memory"
        self.process_dir = self.memory_dir / "processes"

    def list_recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.process_dir.exists():
            return []
        files = sorted(
            self.process_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[: max(1, int(limit or 5))]
        activities = []
        for path in files:
            item = self._load_process(path)
            if item:
                activities.append(item)
        return activities

    def answer(self, query: str, limit: int = 5) -> str:
        activities = self.list_recent(limit=limit)
        if not activities:
            return f"No recent process activity found for '{query}'."
        lines = ["Recent activity from process memory:"]
        for index, item in enumerate(activities, 1):
            lines.append(
                f"{index}. [{item.get('status') or 'unknown'}] {item.get('summary') or '(no summary)'}"
            )
            if item.get("updated_at"):
                lines.append(f"   Updated: {item['updated_at']}")
            if item.get("path"):
                lines.append(f"   Source: {item['path']}")
        return "\n".join(lines)

    def _load_process(self, path: Path) -> Dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        task = self._clean_user_message(str(data.get("user_message") or ""))
        final = self._first_line(str(data.get("final_response") or ""), 180)
        summary = task
        if final and final not in summary:
            summary = f"{summary} -> {final}" if summary else final
        return {
            "process_id": data.get("process_id") or path.stem,
            "session_id": data.get("session_id") or "",
            "status": data.get("status") or "",
            "updated_at": data.get("updated_at") or data.get("completed_at") or "",
            "summary": self._first_line(summary, 260),
            "path": f"memory/processes/{path.name}",
            "event_count": len(data.get("events") or []),
        }

    @classmethod
    def _clean_user_message(cls, text: str) -> str:
        kept = []
        injected_section = False
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in {"[Outline]", "[Textbook outline]", "[Context]", "[Injected context]"}:
                injected_section = True
                continue
            if stripped.startswith("["):
                continue
            if injected_section:
                continue
            if stripped in {"---", "***"}:
                continue
            kept.append(stripped)
            if len(" ".join(kept)) >= 220:
                break
        return cls._first_line(" ".join(kept), 220)

    @staticmethod
    def _first_line(text: str, limit: int = 160) -> str:
        compact = re.sub(r"\s+", " ", text or "").strip()
        if len(compact) <= limit:
            return compact
        return compact[: max(0, limit - 3)].rstrip() + "..."
