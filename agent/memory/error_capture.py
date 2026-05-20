"""Helpers for capturing operational errors into compact memory records."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from common.log import logger


_CORRECTION_PATTERNS = (
    r"不对",
    r"不是.*而是",
    r"你.*错",
    r"纠正",
    r"更正",
    r"应该是",
    r"应当是",
    r"不是这样",
    r"我说的是",
    r"你理解错",
    r"你搞错",
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

        ErrorMemoryRecorder(system_dir()).record_user_correction(
            _clip(text, 2000),
            metadata or {},
        )
    except Exception as exc:
        logger.debug(f"User correction memory capture skipped: {exc}")


def record_tool_error(tool_name: str, detail: Any, metadata: Dict[str, Any] | None = None) -> None:
    try:
        from common.app_paths import system_dir
        from agent.memory import ErrorMemoryRecorder

        ErrorMemoryRecorder(system_dir()).record_tool_error(
            tool_name or "unknown_tool",
            _stringify(detail, 4000),
            metadata or {},
        )
    except Exception as exc:
        logger.debug(f"Tool error memory capture skipped: {exc}")


def record_agent_error(detail: Any, metadata: Dict[str, Any] | None = None) -> None:
    try:
        from common.app_paths import system_dir
        from agent.memory import ErrorMemoryRecorder

        ErrorMemoryRecorder(system_dir()).record_agent_error(
            _stringify(detail, 4000),
            metadata or {},
        )
    except Exception as exc:
        logger.debug(f"Agent error memory capture skipped: {exc}")


def build_error_memory_context(max_items: int = 3, max_detail_chars: int = 220) -> str:
    """Build a compact one-shot index of recent error memories."""
    try:
        from common.app_paths import system_dir

        error_dir = system_dir()
        from pathlib import Path
        paths = sorted(
            (Path(error_dir) / "memory" / "errors").glob("*.json"),
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
