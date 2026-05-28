"""Shared allow-list policy for memory search indexes."""

from __future__ import annotations

import re
from pathlib import Path


class MemoryIndexPolicy:
    """Decide whether a local memory/workspace file may enter search indexes."""

    SKIP_PARTS = {
        "graph",
        "versions",
        "cache",
        "sessions_archive",
        "maintenance_backups",
        "__pycache__",
    }
    SKIP_MEMORY_PARTS = {
        "processes",
        "errors",
        "short_term",
        "candidates",
        "transactions",
        "quarantine",
        "usage",
    }
    ROOT_PROFILE_FILES = {"agent.md", "user.md", "rule.md", "memory.md"}

    @classmethod
    def should_index_path(cls, path: str | Path) -> bool:
        normalized = str(path).replace("\\", "/").lower()
        parts = [part for part in normalized.split("/") if part]
        name = parts[-1] if parts else ""
        if any(part in cls.SKIP_PARTS for part in parts):
            return False
        if name in {"memory_graph.db", "process_index.md", "maintenance_state.json", "retention_state.json"}:
            return False
        if "memory" in parts:
            idx = parts.index("memory")
            memory_parts = parts[idx + 1 :]
            if not memory_parts:
                return False
            first = memory_parts[0]
            if first in cls.SKIP_MEMORY_PARTS:
                return False
            if first == "sessions":
                return name == "handoff.md"
            if name in {"memory.md", "user_profile.md", "user_profile.json"}:
                return True
            if len(memory_parts) == 1 and (cls._is_dated_memory_name(name) or name.endswith((".md", ".json"))):
                return True
            return False
        if name in cls.ROOT_PROFILE_FILES:
            return True
        if "textbooks" in parts:
            return not any(part in {"assets", "__pycache__"} for part in parts)
        if "knowledge" in parts:
            return True
        return False

    @staticmethod
    def _is_dated_memory_name(name: str) -> bool:
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}\.md$", name or ""))
