"""Startup memory bootstrap for compact, one-time context injection."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List


class MemoryBootstrap:
    """Build a compact memory pack loaded only when a session starts."""

    def __init__(self, system_root: str, project_workspace: str = ""):
        self.system_root = Path(system_root)
        self.project_workspace = Path(project_workspace) if project_workspace else None
        self.memory_dir = self.system_root / "memory"

    def ensure_layout(self) -> None:
        for name in ("memory", "sessions", "logs", "cache", "jobs", "config", "chat_history"):
            (self.system_root / name).mkdir(parents=True, exist_ok=True)
        for name in ("processes", "sessions", "long-term", "errors"):
            (self.memory_dir / name).mkdir(parents=True, exist_ok=True)
        user_profile = self.memory_dir / "user_profile.md"
        if not user_profile.exists():
            user_profile.write_text("# User Profile\n\nNo stable profile yet.\n", encoding="utf-8")
        process_index = self.memory_dir / "process_index.md"
        if not process_index.exists():
            process_index.write_text("# Process Memory Index\n\nNo process memories yet.\n", encoding="utf-8")

    def build_startup_context(self, session_id: str = "") -> str:
        self.ensure_layout()
        sections = [
            "# System Memory Bootstrap",
            "",
            "This compact profile context is loaded once on the first request of a session. Use memory tools for details when needed.",
            "",
        ]
        sections.extend(self._profile_section())
        sections.extend(self._workspace_profile_section())
        sections.extend(self._on_demand_section())
        return "\n".join(sections).strip() + "\n"

    def _profile_section(self) -> List[str]:
        profile_md = self.memory_dir / "user_profile.md"
        profile_json = self.memory_dir / "user_profile.json"
        content = ""
        if profile_md.exists():
            content = self._read_head(profile_md, 1200)
        elif profile_json.exists():
            content = self._read_head(profile_json, 1200)
        return ["## User Profile", "", content or "No user profile available.", ""]

    def _workspace_profile_section(self) -> List[str]:
        if not self.project_workspace:
            return []
        rows: List[str] = []
        for filename, title, max_chars in (
            ("AGENT.md", "Agent Operating Notes", 900),
            ("USER.md", "Workspace User Notes", 900),
            ("RULE.md", "Workspace Rules", 900),
            ("MEMORY.md", "Workspace Long-term Memory", 1400),
        ):
            path = self.project_workspace / filename
            if not path.exists() or not path.is_file():
                continue
            content = self._read_head(path, max_chars)
            if not content or self._looks_like_template(content):
                continue
            rows.extend([f"### {title} ({filename})", "", content, ""])
        if not rows:
            return []
        return [
            "## Workspace Profile Files",
            "",
            "These workspace-root files are fused into startup memory once; use memory_get/read for full content later.",
            "",
            *rows,
        ]

    def _process_section(self, session_id: str) -> List[str]:
        processes_dir = self.memory_dir / "processes"
        rows = []
        for path in self._recent_files(processes_dir, ("*.json", "*.md"), limit=8):
            meta = self._metadata_for(path)
            if session_id and meta.get("session_id") == session_id:
                continue
            rows.append(f"- {meta.get('date', '')} {meta.get('title') or path.stem}: {path.relative_to(self.system_root).as_posix()}")
        return ["## Recent Process Memories", "", *(rows or ["No process memory available."]), ""]

    def _error_section(self) -> List[str]:
        errors_dir = self.memory_dir / "errors"
        rows = []
        for path in self._recent_files(errors_dir, ("*.json", "*.md"), limit=6):
            meta = self._metadata_for(path)
            rows.append(f"- {meta.get('date', '')} {meta.get('title') or path.stem}: {path.relative_to(self.system_root).as_posix()}")
        return ["## Error Memory Index", "", *(rows or ["No error memory available."]), ""]

    def _project_section(self) -> List[str]:
        if not self.project_workspace:
            return []
        textbooks = self.project_workspace / "textbooks"
        rows = []
        if textbooks.exists():
            for path in sorted(textbooks.glob("*/state/status.json"))[:12]:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
                book_dir = path.parents[1]
                title = data.get("title") or book_dir.name
                rows.append(f"- {title}: {path.relative_to(self.project_workspace).as_posix()}")
        return ["## Textbook State Index", "", *(rows or ["No textbook state index available."]), ""]

    def _on_demand_section(self) -> List[str]:
        return [
            "## On-demand Memory Stores",
            "",
            "- Process memories: `memory/processes/` (load only when task depends on prior process state).",
            "- Daily memories: `memory/YYYY-MM-DD.md` (load only when date-specific history matters).",
            "- Session memories: `memory/sessions/` (load only when current/previous session context matters).",
            "- Error memories: `memory/errors/` (load only when debugging repeated or similar failures).",
            "",
        ]

    def _recent_files(self, root: Path, patterns: tuple[str, ...], limit: int) -> List[Path]:
        if not root.exists():
            return []
        files: List[Path] = []
        for pattern in patterns:
            files.extend(p for p in root.glob(pattern) if p.is_file())
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

    def _metadata_for(self, path: Path) -> Dict[str, Any]:
        stat = path.stat()
        meta: Dict[str, Any] = {
            "title": path.stem,
            "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
        }
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    meta.update({k: v for k, v in data.items() if k in ("title", "date", "session_id", "summary")})
            except Exception:
                pass
        return meta

    def _read_head(self, path: Path, max_chars: int) -> str:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
        return text[:max_chars].rstrip()

    @staticmethod
    def _looks_like_template(content: str) -> bool:
        markers = (
            "No stable profile yet.",
            "在这里记录",
            "填写",
            "TODO",
            "todo",
            "placeholder",
        )
        sample = content[:500]
        return any(marker in sample for marker in markers)
