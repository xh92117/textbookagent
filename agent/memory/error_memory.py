"""Error memory capture for tool failures, agent errors, and user corrections."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict


class ErrorMemoryRecorder:
    """Append compact error/correction records under system memory."""

    def __init__(self, system_root: str):
        self.system_root = Path(system_root)
        self.error_dir = self.system_root / "memory" / "errors"
        self.error_dir.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, title: str, detail: str, metadata: Dict[str, Any] | None = None) -> Path:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        safe_title = self._safe_slug(title or kind or "error")
        path = self.error_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_title}.json"
        payload = {
            "kind": kind or "error",
            "title": title or kind or "error",
            "detail": (detail or "").strip()[:4000],
            "metadata": metadata or {},
            "date": now,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def record_tool_error(self, tool_name: str, detail: str, metadata: Dict[str, Any] | None = None) -> Path:
        return self.record("tool_error", f"{tool_name} failed", detail, metadata)

    def record_agent_error(self, detail: str, metadata: Dict[str, Any] | None = None) -> Path:
        return self.record("agent_error", "Agent error", detail, metadata)

    def record_user_correction(self, detail: str, metadata: Dict[str, Any] | None = None) -> Path:
        return self.record("user_correction", "User correction", detail, metadata)

    def _safe_slug(self, text: str) -> str:
        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text, flags=re.UNICODE).strip("_").lower()
        return (slug or "error")[:60]
