"""Helpers for capturing useful operational errors into compact memory records."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from common.log import logger


_CORRECTION_PATTERNS = (
    r"\u4e0d\u5bf9",
    r"\u4e0d\u662f.*\u800c\u662f",
    r"\u4f60.*\u9519",
    r"\u7ea0\u6b63",
    r"\u66f4\u6b63",
    r"\u5e94\u8be5\u662f",
    r"\u5e94\u5f53\u662f",
    r"\u4e0d\u662f\u8fd9\u6837",
    r"\u6211\u8bf4\u7684\u662f",
    r"\u4f60\u7406\u89e3\u9519",
    r"\u4f60\u641e\u9519",
)

_SIGNIFICANT_ERROR_TYPES = {
    "parse_error",
    "retry_protection",
    "exception",
    "post_process_tool_error",
    "agent_error",
    "user_correction",
}

_SIGNIFICANT_TOOLS = {
    "write",
    "edit",
    "bash",
    "browser",
    "memory_get",
    "memory_search",
    "knowledge_capture",
    "create_textbook",
    "textbook_outline",
    "start_pipeline",
    "pipeline",
}

_TRANSIENT_ERROR_PATTERNS = (
    r"\b404\b",
    r"\b429\b",
    r"\brate limit\b",
    r"\btemporary\b",
    r"\btimeout\b",
    r"\btimed out\b",
    r"\bconnection reset\b",
    r"\bnetwork\b",
    r"\bnot found\b",
    r"\bfile not found\b",
    r"\bno such file\b",
)

_LOW_VALUE_ERROR_PATTERNS = (
    r"\bskipped\b",
    r"\balready exists\b",
    r"\bempty result\b",
    r"\bno results?\b",
)

_PERMISSION_ERROR_PATTERNS = (
    r"\bpermission denied\b",
)


def is_user_correction(text: str) -> bool:
    """Return True when the user appears to correct prior agent behavior."""
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    return any(re.search(pattern, compact) for pattern in _CORRECTION_PATTERNS)


def record_user_correction_if_needed(text: str, metadata: Dict[str, Any] | None = None) -> None:
    if not is_user_correction(text):
        return
    try:
        from common.app_paths import system_dir
        from agent.memory import ErrorMemoryRecorder
        from config import conf

        ErrorMemoryRecorder(system_dir(), max_files=int(conf().get("memory_error_max_files", 80) or 80)).record_user_correction(
            _clip(text, 2000),
            metadata or {},
        )
    except Exception as exc:
        logger.debug(f"User correction memory capture skipped: {exc}")


def record_tool_error(tool_name: str, detail: Any, metadata: Dict[str, Any] | None = None) -> None:
    metadata = metadata or {}
    if not should_record_tool_error(tool_name, detail, metadata):
        logger.debug(
            f"Tool error memory skipped by filter: tool={tool_name}, "
            f"type={metadata.get('error_type', '')}"
        )
        return
    try:
        from common.app_paths import system_dir
        from agent.memory import ErrorMemoryRecorder
        from config import conf

        ErrorMemoryRecorder(system_dir(), max_files=int(conf().get("memory_error_max_files", 80) or 80)).record_tool_error(
            tool_name or "unknown_tool",
            _stringify(detail, 4000),
            metadata,
        )
    except Exception as exc:
        logger.debug(f"Tool error memory capture skipped: {exc}")


def record_agent_error(detail: Any, metadata: Dict[str, Any] | None = None) -> None:
    metadata = metadata or {}
    if not should_record_agent_error(detail, metadata):
        logger.debug("Agent error memory skipped by filter")
        return
    try:
        from common.app_paths import system_dir
        from agent.memory import ErrorMemoryRecorder
        from config import conf

        ErrorMemoryRecorder(system_dir(), max_files=int(conf().get("memory_error_max_files", 80) or 80)).record_agent_error(
            _stringify(detail, 4000),
            metadata,
        )
    except Exception as exc:
        logger.debug(f"Agent error memory capture skipped: {exc}")


def build_error_memory_context(max_items: int = 3, max_detail_chars: int = 220) -> str:
    """Build a compact one-shot index of recent error memories."""
    try:
        from common.app_paths import system_dir
        from pathlib import Path

        paths = sorted(
            (Path(system_dir()) / "memory" / "errors").glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:max(1, max_items)]
        rows = []
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows.append(
                "- "
                + "; ".join([
                    f"kind={payload.get('kind', '')}",
                    f"date={payload.get('date', '')}",
                    f"title={payload.get('title', '')}",
                    f"detail={_clip(payload.get('detail', ''), max_detail_chars)}",
                    f"path={path.as_posix()}",
                ])
            )
        if not rows:
            return ""
        return "Recent error memory index:\n" + "\n".join(rows)
    except Exception as exc:
        logger.debug(f"Error memory context build skipped: {exc}")
        return ""


def should_record_tool_error(tool_name: str, detail: Any, metadata: Dict[str, Any] | None = None) -> bool:
    """Return True only for errors that are useful as future lessons."""
    metadata = metadata or {}
    error_type = str(metadata.get("error_type", "")).lower()
    tool = (tool_name or "").lower()
    text = _stringify(detail, 1200).lower()

    if metadata.get("critical") or metadata.get("repeat_count", 0):
        return True

    durable_patterns = (
        r"\bapi key\b",
        r"\bauthentication\b",
        r"\bauthorization\b",
        r"\binvalid json\b",
        r"\bschema\b",
        r"\btool_use\b",
        r"\btool_result\b",
        r"\bcontext overflow\b",
        r"\bmessage format\b",
    )
    if any(re.search(pattern, text) for pattern in durable_patterns):
        return True
    if tool in ("write", "edit", "bash") and any(re.search(pattern, text) for pattern in _PERMISSION_ERROR_PATTERNS):
        return True
    if any(re.search(pattern, text) for pattern in _TRANSIENT_ERROR_PATTERNS):
        return False
    if any(re.search(pattern, text) for pattern in _LOW_VALUE_ERROR_PATTERNS):
        return False
    if error_type in _SIGNIFICANT_ERROR_TYPES:
        return True
    if tool in _SIGNIFICANT_TOOLS:
        return True
    return False


def should_record_agent_error(detail: Any, metadata: Dict[str, Any] | None = None) -> bool:
    metadata = metadata or {}
    text = _stringify(detail, 1200).lower()
    if metadata.get("critical"):
        return True
    if any(token in text for token in ("context overflow", "message format", "tool_use", "tool_result")):
        return True
    if any(token in text for token in ("api key", "authentication", "authorization", "invalid json")):
        return True
    if any(re.search(pattern, text) for pattern in _TRANSIENT_ERROR_PATTERNS):
        return False
    if any(re.search(pattern, text) for pattern in _LOW_VALUE_ERROR_PATTERNS):
        return False
    return bool(text and len(text) > 80)


def _stringify(value: Any, max_chars: int) -> str:
    if isinstance(value, str):
        return _clip(value, max_chars)
    try:
        return _clip(json.dumps(value, ensure_ascii=False), max_chars)
    except Exception:
        return _clip(str(value), max_chars)


def _clip(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[truncated: {len(text)} chars total]"
