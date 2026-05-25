from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TextbookStateSnapshot:
    book_id: str
    title: str = ""
    status: str = "planning"
    total_chapters: int = 0
    completed_chapters: int = 0
    completed_chapter_numbers: List[int] = field(default_factory=list)
    progress: float = 0.0
    latest_completed_chapter: Optional[int] = None
    current_chapter: Optional[int] = None
    current_phase: str = ""
    source: str = "truth_files"
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "book_id": self.book_id,
            "title": self.title,
            "status": self.status,
            "total_chapters": self.total_chapters,
            "completed_chapters": self.completed_chapters,
            "completed_chapter_numbers": self.completed_chapter_numbers,
            "progress": self.progress,
            "latest_completed_chapter": self.latest_completed_chapter,
            "current_chapter": self.current_chapter,
            "current_phase": self.current_phase,
            "state_source": self.source,
            "state_warnings": self.warnings,
        }


class TextbookStateResolver:
    """Resolve textbook state from one authoritative source: truth files on disk.

    Status files can become stale when chapters are edited manually or restored.
    The resolver treats chapter files plus their metadata as the current source
    of completion truth, then uses status.json only for runtime phase details.
    """

    def __init__(self, truth_manager, min_chapter_chars: int = 50):
        self.truth_manager = truth_manager
        self.min_chapter_chars = min_chapter_chars

    def resolve(self, config=None, book_id: str = "") -> TextbookStateSnapshot:
        book_id = book_id or getattr(config, "id", "") or ""
        title = getattr(config, "title", "") if config is not None else ""
        total = self._safe_int(getattr(config, "total_chapters", 0) if config is not None else 0)
        configured_status = getattr(config, "status", "") if config is not None else ""

        completed_numbers, chapter_warnings = self._resolved_completed_chapters()
        completed = len(completed_numbers)
        progress = round((completed / total) * 100, 1) if total > 0 else 0.0
        status_payload = self.truth_manager.get_status()
        progress_payload = self.truth_manager.get_progress()
        warnings: List[str] = list(chapter_warnings)

        recorded_completed = self._safe_int(progress_payload.get("completed_chapters", 0))
        if progress_payload and recorded_completed != completed:
            warnings.append(
                f"progress_file_completed={recorded_completed}, resolved_completed={completed}"
            )

        status = configured_status or status_payload.get("status") or "planning"
        if total > 0 and completed >= total:
            status = "completed" if status in ("completed", "published") else "reviewing"
        elif completed > 0 and status in ("planning", "outline", "created", ""):
            status = "writing"

        return TextbookStateSnapshot(
            book_id=book_id,
            title=title,
            status=status,
            total_chapters=total,
            completed_chapters=completed,
            completed_chapter_numbers=completed_numbers,
            progress=progress,
            latest_completed_chapter=completed_numbers[-1] if completed_numbers else None,
            current_chapter=status_payload.get("current_chapter"),
            current_phase=status_payload.get("current_phase", ""),
            warnings=warnings,
        )

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _resolved_completed_chapters(self) -> tuple[List[int], List[str]]:
        completed: List[int] = []
        warnings: List[str] = []
        for filename in self.truth_manager.list_chapters():
            try:
                import re
                match = re.match(r"^chapter_0*(\d+)\.md$", str(filename), re.IGNORECASE)
                chapter_num = int(match.group(1)) if match else None
            except (AttributeError, ValueError):
                chapter_num = None
            if chapter_num is None:
                continue
            content = self.truth_manager.read_chapter(chapter_num) or ""
            if len(content.strip()) < self.min_chapter_chars:
                continue
            completed.append(chapter_num)
            meta = self.truth_manager.get_chapter_metadata(chapter_num)
            if meta:
                content_hash = meta.get("content_hash")
                if meta.get("status") and meta.get("status") != "completed":
                    warnings.append(f"chapter_{chapter_num}_metadata_status={meta.get('status')}")
                if content_hash and content_hash != self.truth_manager.content_hash(content):
                    warnings.append(f"chapter_{chapter_num}_metadata_hash_stale")
        return sorted(set(completed)), warnings
