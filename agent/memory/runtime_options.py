"""Config mapping for memory runtime components."""

from __future__ import annotations

from typing import Any, Mapping


def realtime_memory_enabled(config: Mapping[str, Any]) -> bool:
    return bool(config.get("realtime_memory_enabled", True))


def realtime_recorder_options(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "process_memory_enabled": bool(config.get("realtime_process_memory_enabled", True)),
        "session_memory_enabled": bool(config.get("realtime_session_memory_enabled", True)),
        "process_state_files_enabled": bool(config.get("realtime_process_state_files_enabled", False)),
        "candidate_auto_record_enabled": bool(config.get("memory_candidate_auto_record_enabled", False)),
        "retention_enabled": bool(config.get("memory_retention_enabled", True)),
        "process_retention_days": int(config.get("memory_process_retention_days", 7) or 7),
        "process_max_files": int(config.get("memory_process_max_files", 60) or 60),
        "session_retention_days": int(config.get("memory_session_retention_days", 14) or 14),
        "session_max_files": int(config.get("memory_session_max_files", 80) or 80),
        "error_retention_days": int(config.get("memory_error_retention_days", 30) or 30),
        "error_max_files": int(config.get("memory_error_max_files", 80) or 80),
        "retention_interval_hours": int(config.get("memory_retention_interval_hours", 24) or 24),
        "session_dedupe_window": int(config.get("memory_session_dedupe_window", 20) or 20),
        "profile_recent_focus_limit": int(config.get("memory_profile_recent_focus_limit", 10) or 10),
        "profile_field_limit": int(config.get("memory_profile_field_limit", 30) or 30),
    }
