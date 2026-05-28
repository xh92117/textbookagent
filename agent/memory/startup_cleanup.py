"""Startup hook for weekly runtime-memory maintenance."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from common.log import logger


def run_startup_memory_cleanup(system_root: str, config: Mapping[str, Any]) -> dict:
    if not bool(config.get("memory_startup_cleanup_enabled", True)):
        return {"skipped": True, "reason": "disabled"}

    from agent.memory.maintenance import MemoryMaintenance

    memory_dir = Path(system_root) / "memory"
    result = MemoryMaintenance(
        memory_dir,
        profile_field_limit=int(config.get("memory_profile_field_limit", 30) or 30),
        recent_focus_limit=int(config.get("memory_profile_recent_focus_limit", 10) or 10),
        drop_process_state_files=bool(config.get("memory_startup_cleanup_drop_process_state_files", True)),
        run_retention=bool(config.get("memory_retention_enabled", True)),
        process_retention_days=int(config.get("memory_process_retention_days", 7) or 7),
        process_max_files=int(config.get("memory_process_max_files", 60) or 60),
        session_retention_days=int(config.get("memory_session_retention_days", 14) or 14),
        session_max_files=int(config.get("memory_session_max_files", 80) or 80),
        error_retention_days=int(config.get("memory_error_retention_days", 30) or 30),
        error_max_files=int(config.get("memory_error_max_files", 80) or 80),
    ).run_if_due(interval_days=int(config.get("memory_startup_cleanup_interval_days", 7) or 7))
    logger.info(f"[MemoryStartupCleanup] result={result}")
    return result
