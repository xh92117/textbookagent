"""
Application path helpers for commercial workspace separation.

Definitions:
- system root: stable per-user directory for app state, memory, sessions,
  profile, logs, cache and jobs.
- active workspace: user-selected business workspace for textbooks,
  knowledge bases, exports and project assets.

Defaults stay backward compatible: if no active workspace is configured, the
legacy ``agent_workspace`` is used for business files too.
"""

from __future__ import annotations

import os
from pathlib import Path

from common.utils import expand_path


DEFAULT_LEGACY_ROOT = "~/textbook_workspace"


def _conf_get(key: str, default=None):
    try:
        from config import conf
        return conf().get(key, default)
    except Exception:
        return default


def legacy_root() -> str:
    return expand_path(_conf_get("agent_workspace", DEFAULT_LEGACY_ROOT))


def system_root() -> str:
    return expand_path(_conf_get("system_workspace", "") or legacy_root())


def system_dir() -> str:
    root = system_root()
    if _conf_get("workspace_split_enabled", True):
        return os.path.join(root, "system")
    return root


def active_workspace() -> str:
    return expand_path(
        _conf_get("active_workspace", "")
        or _conf_get("workspace_dir", "")
        or legacy_root()
    )


def textbooks_dir() -> str:
    return os.path.join(active_workspace(), "textbooks")


def knowledge_dir() -> str:
    return os.path.join(active_workspace(), "knowledge")


def exports_dir() -> str:
    return os.path.join(active_workspace(), "exports")


def assets_dir() -> str:
    return os.path.join(active_workspace(), "assets")


def tmp_dir() -> str:
    return os.path.join(active_workspace(), "tmp")


def chat_history_dir() -> str:
    return os.path.join(system_dir(), "chat_history")


def ensure_active_workspace() -> str:
    ws = active_workspace()
    for name in ("textbooks", "knowledge", "exports", "assets", "tmp"):
        os.makedirs(os.path.join(ws, name), exist_ok=True)
    manifest = Path(ws) / "workspace.json"
    if not manifest.exists():
        manifest.write_text(
            '{\n  "version": "textbook-workspace-v1"\n}\n',
            encoding="utf-8",
        )
    return ws


def ensure_system_dir() -> str:
    root = system_dir()
    for name in ("memory", "sessions", "logs", "cache", "jobs", "config", "chat_history"):
        os.makedirs(os.path.join(root, name), exist_ok=True)
    return root
