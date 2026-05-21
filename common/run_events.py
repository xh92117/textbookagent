# encoding:utf-8

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, Optional

from common.log import logger


def normalize_event(
    event: Dict[str, Any],
    run_id: str = "",
    source: str = "",
    phase: str = "",
    status: str = "",
    message: str = "",
) -> Dict[str, Any]:
    """Return a stable event envelope while preserving the original payload."""
    event = event or {}
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    event_type = str(event.get("type") or data.get("type") or "event")
    resolved_status = status or _status_from_type(event_type, data)
    resolved_phase = phase or str(data.get("phase") or data.get("current_phase") or "")
    resolved_message = message or _message_from_event(event_type, data)
    resolved_run_id = (
        run_id
        or str(event.get("run_id") or event.get("pipeline_id") or data.get("run_id") or data.get("pipeline_id") or "")
    )
    return {
        "event_id": str(event.get("event_id") or uuid.uuid4()),
        "run_id": resolved_run_id,
        "source": source or str(event.get("source") or data.get("source") or ""),
        "type": event_type,
        "phase": resolved_phase,
        "status": resolved_status,
        "message": resolved_message,
        "started_at": data.get("started_at") or event.get("started_at") or None,
        "ended_at": data.get("ended_at") or event.get("ended_at") or None,
        "timestamp": float(event.get("timestamp") or data.get("timestamp") or time.time()),
        "error": data.get("error") or event.get("error") or None,
        "payload": data,
    }


class RunStateRecorder:
    """Append-only JSONL recorder for resumable/debuggable run state."""

    def __init__(self, root_dir: str, run_id: str, source: str = ""):
        self.root_dir = root_dir
        self.run_id = run_id or "default"
        self.source = source
        self.path = os.path.join(root_dir, "run_events.jsonl")
        os.makedirs(root_dir, exist_ok=True)

    def record(self, event: Dict[str, Any]) -> Dict[str, Any]:
        normalized = normalize_event(event, run_id=self.run_id, source=self.source)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception as exc:
            logger.debug(f"Failed to record run event {self.path}: {exc}")
        return normalized


def _status_from_type(event_type: str, data: Dict[str, Any]) -> str:
    explicit = data.get("status") or data.get("run_status")
    if explicit:
        return str(explicit)
    lowered = (event_type or "").lower()
    if "error" in lowered or "failed" in lowered:
        return "error"
    if "complete" in lowered or lowered in ("done", "message_end"):
        return "completed"
    if "start" in lowered:
        return "running"
    if "progress" in lowered or "thinking" in lowered:
        return "running"
    return "event"


def _message_from_event(event_type: str, data: Dict[str, Any]) -> str:
    for key in ("message", "result_summary", "item_label", "phase_label", "summary"):
        value = data.get(key)
        if value:
            return str(value)
    if data.get("tool_name"):
        return str(data.get("tool_name"))
    if data.get("error"):
        return str(data.get("error"))
    return str(event_type or "event")
