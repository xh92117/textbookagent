"""Error memory capture for tool failures, agent errors, and user corrections."""

from __future__ import annotations

import json
import re
import hashlib
import time
from pathlib import Path
from typing import Any, Dict


class ErrorMemoryRecorder:
    """Append compact error/correction records under system memory."""

    def __init__(self, system_root: str, max_files: int = 80):
        self.system_root = Path(system_root)
        self.error_dir = self.system_root / "memory" / "errors"
        self.max_files = max(1, int(max_files or 80))
        self.error_dir.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, title: str, detail: str, metadata: Dict[str, Any] | None = None) -> Path:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        safe_title = self._safe_slug(title or kind or "error")
        fingerprint = self._fingerprint(kind, title, detail, metadata)
        existing = self._find_existing(fingerprint)
        if existing:
            payload = self._load_payload(existing)
            payload["count"] = int(payload.get("count") or 1) + 1
            payload["last_seen_at"] = now
            payload["detail"] = (detail or "").strip()[:4000]
            payload["metadata"] = metadata or payload.get("metadata") or {}
            payload.setdefault("fingerprint", fingerprint)
            existing.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return existing

        path = self.error_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_title}_{fingerprint[:8]}.json"
        payload = {
            "kind": kind or "error",
            "title": title or kind or "error",
            "detail": (detail or "").strip()[:4000],
            "metadata": metadata or {},
            "fingerprint": fingerprint,
            "count": 1,
            "last_seen_at": now,
            "temporal": {
                "scope": "historical",
                "authority": "error_log",
                "observed_at": now,
                "valid_from": now,
                "valid_until": "",
                "supersedes": [],
                "superseded_by": "",
            },
            "date": now,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._prune()
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

    def _fingerprint(self, kind: str, title: str, detail: str, metadata: Dict[str, Any] | None = None) -> str:
        base = {
            "kind": kind or "error",
            "title": title or kind or "error",
            "detail": (detail or "").strip()[:4000],
            "metadata": metadata or {},
        }
        text = json.dumps(base, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _find_existing(self, fingerprint: str) -> Path | None:
        for path in self.error_dir.glob("*.json"):
            payload = self._load_payload(path)
            if payload.get("fingerprint") == fingerprint:
                return path
        return None

    def _load_payload(self, path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _prune(self) -> None:
        files = sorted(self.error_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[self.max_files:]:
            try:
                path.unlink()
            except OSError:
                continue
