"""Startup memory bootstrap for compact, one-time context injection."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List


class MemoryBootstrap:
    """Build a compact memory pack loaded only when a session starts."""

    MAX_STARTUP_CHARS = 7000
    USER_PROFILE_CHARS = 1800
    WORKSPACE_FILE_BUDGETS = {
        "AGENT.md": 900,
        "USER.md": 900,
        "RULE.md": 1100,
        "MEMORY.md": 1600,
    }
    PROCESS_INDEX_LIMIT = 7

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

    def build_startup_context(self, session_id: str = "", include_workspace_profile: bool = True) -> str:
        self.ensure_layout()
        sections = [
            "# System Memory Bootstrap",
            "",
            "This compact profile context is loaded once on the first request of a session. Use memory tools for details when needed.",
            "",
        ]
        sections.extend(self._budget_section())
        sections.extend(self._profile_section())
        if include_workspace_profile:
            sections.extend(self._workspace_profile_section())
        sections.extend(self._process_index_section())
        sections.extend(self._on_demand_section())
        return self._fit_startup_budget("\n".join(sections).strip()) + "\n"

    def _budget_section(self) -> List[str]:
        return [
            "## Startup memory budget",
            "",
            f"- Hard cap: {self.MAX_STARTUP_CHARS} characters for this startup pack.",
            "- Long files are head/tail clipped; use memory_get for full content.",
            "- Process and error memories remain on demand unless directly relevant.",
            "",
        ]

    def _profile_section(self) -> List[str]:
        profile_md = self.memory_dir / "user_profile.md"
        profile_json = self.memory_dir / "user_profile.json"
        content = ""
        if profile_md.exists():
            content = self._read_budgeted(profile_md, self.USER_PROFILE_CHARS)
        elif profile_json.exists():
            content = self._read_budgeted(profile_json, self.USER_PROFILE_CHARS)
        return ["## User Profile", "", content or "No user profile available.", ""]

    def _workspace_profile_section(self) -> List[str]:
        if not self.project_workspace:
            return []
        rows: List[str] = []
        for filename, title in (
            ("AGENT.md", "Agent Operating Notes"),
            ("USER.md", "Workspace User Notes"),
            ("RULE.md", "Workspace Rules"),
            ("MEMORY.md", "Workspace Long-term Memory"),
        ):
            path = self.project_workspace / filename
            if not path.exists() or not path.is_file():
                continue
            content = self._read_budgeted(
                path,
                self.WORKSPACE_FILE_BUDGETS[filename],
                tail=filename in {"USER.md"},
            )
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

    def _process_index_section(self) -> List[str]:
        index_path = self.memory_dir / "process_index.md"
        if not index_path.exists():
            return []
        try:
            lines = index_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        rows = [line.strip() for line in lines if line.strip().startswith("- ")]
        if not rows:
            return []
        recent = rows[-self.PROCESS_INDEX_LIMIT:]
        if len(rows) > self.PROCESS_INDEX_LIMIT:
            recent.insert(0, f"- ...({len(rows) - self.PROCESS_INDEX_LIMIT} older process index entries omitted; use memory_get on memory/process_index.md)")
        return [
            "## Recent Process Index",
            "",
            "Bounded index only; load individual process state files on demand.",
            "",
            *recent,
            "",
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

    def _read_budgeted(self, path: Path, max_chars: int, tail: bool = True) -> str:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
        if tail:
            return self._clip_head_tail(text, max_chars, f"{path.name} truncated; use memory_get for full content")
        if len(text) <= max_chars:
            return text
        notice = f"\n\n...({path.name} truncated; use memory_get for full content)..."
        return (text[: max(200, max_chars - len(notice))].rstrip() + notice).strip()

    @staticmethod
    def _clip_head_tail(text: str, max_chars: int, notice: str) -> str:
        if len(text) <= max_chars:
            return text
        notice_text = f"\n\n...({notice})...\n\n"
        budget = max(200, max_chars - len(notice_text))
        head_chars = max(100, int(budget * 0.58))
        tail_chars = max(80, budget - head_chars)
        return (text[:head_chars].rstrip() + notice_text + text[-tail_chars:].lstrip()).strip()

    def _fit_startup_budget(self, context: str) -> str:
        if len(context) <= self.MAX_STARTUP_CHARS:
            return context
        return self._clip_head_tail(
            context,
            self.MAX_STARTUP_CHARS,
            "startup pack truncated; use memory_search or memory_get for omitted details",
        )

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
