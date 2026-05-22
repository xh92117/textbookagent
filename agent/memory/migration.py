"""Compatibility migration for legacy workspace memory files."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def migrate_legacy_memory_files(system_root: str | Path, project_workspace: str | Path | None = None) -> Dict:
    """Copy legacy memory files into the system memory tree.

    The migration is intentionally non-destructive. Legacy workspace files may
    contain user-written notes, so sources are left in place and a report is
    written under ``system/memory/migrations``.
    """

    system_root = Path(system_root)
    memory_root = system_root / "memory"
    memory_root.mkdir(parents=True, exist_ok=True)
    migrations_dir = memory_root / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)

    report: Dict[str, object] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "system_root": str(system_root),
        "project_workspace": str(project_workspace) if project_workspace else None,
        "copied": [],
        "skipped": [],
    }

    copied: List[Dict[str, str]] = report["copied"]  # type: ignore[assignment]
    skipped: List[Dict[str, str]] = report["skipped"]  # type: ignore[assignment]

    main_memory = memory_root / "MEMORY.md"
    legacy_system_main = system_root / "MEMORY.md"
    if legacy_system_main.exists() and legacy_system_main.is_file():
        _copy_if_changed(legacy_system_main, main_memory, copied, skipped)

    if project_workspace:
        project_root = Path(project_workspace)
        import_root = memory_root / "imported" / _safe_name(project_root)

        legacy_project_main = project_root / "MEMORY.md"
        if legacy_project_main.exists() and legacy_project_main.is_file():
            _copy_if_changed(legacy_project_main, import_root / "MEMORY.md", copied, skipped)

        legacy_project_memory_dir = project_root / "memory"
        if legacy_project_memory_dir.exists() and legacy_project_memory_dir.is_dir():
            for source in legacy_project_memory_dir.rglob("*.md"):
                if any(part.startswith(".") for part in source.relative_to(legacy_project_memory_dir).parts):
                    continue
                target = import_root / "memory" / source.relative_to(legacy_project_memory_dir)
                _copy_if_changed(source, target, copied, skipped)

    report_path = migrations_dir / "memory_migration_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _copy_if_changed(source: Path, target: Path, copied: List[Dict[str, str]], skipped: List[Dict[str, str]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_text = source.read_text(encoding="utf-8")
    if target.exists() and target.read_text(encoding="utf-8") == source_text:
        skipped.append({"source": str(source), "target": str(target), "reason": "unchanged"})
        return
    shutil.copy2(source, target)
    copied.append({"source": str(source), "target": str(target)})


def _safe_name(path: Path) -> str:
    name = path.name or "workspace"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)
