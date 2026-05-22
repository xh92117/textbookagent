import json
import os
import re
import time
from typing import Any, Dict, Tuple

from agent.tools.base_tool import BaseTool, ToolResult


class TextbookChapterTool(BaseTool):
    name: str = "textbook_chapter"
    description: str = (
        "UTF-8 safe textbook chapter tool. Use this instead of write/edit/bash when reading, "
        "writing, appending, replacing, or validating textbook chapter Markdown. It resolves "
        "the canonical book_id/textbooks/<id>/chapters path, preserves chapter metadata, and "
        "updates the textbook status board. Actions: read, write_chapter, append_section, "
        "replace_section, mark_completed, validate_encoding, status. To mark an existing "
        "chapter complete, use mark_completed; never call write_chapter with placeholder content."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of: read, write_chapter, append_section, replace_section, mark_completed, validate_encoding, status"
            },
            "book_id": {
                "type": "string",
                "description": "Textbook id, for example tb_3df776e0"
            },
            "chapter_num": {
                "type": "integer",
                "description": "Chapter number, for example 2"
            },
            "heading": {
                "type": "string",
                "description": "Markdown section heading to append/replace, for example ## 2.4 Prompt Engineering 入门"
            },
            "content": {
                "type": "string",
                "description": "UTF-8 Markdown content. Keep each call reasonably small; split very long chapters by section."
            },
            "completed": {
                "type": "boolean",
                "description": "Whether the chapter should be marked completed after write/append/replace"
            },
            "allow_overwrite": {
                "type": "boolean",
                "description": "Explicitly allow replacing an existing substantial chapter with a full new body. Prefer append_section/replace_section for edits."
            }
        },
        "required": ["action", "book_id", "chapter_num"]
    }

    MAX_CHUNK_CHARS = 12000
    WARN_CHUNK_CHARS = 12000
    MIN_COMPLETED_CHARS = 1000
    DANGEROUS_OVERWRITE_EXISTING_CHARS = 1000
    DANGEROUS_OVERWRITE_RATIO = 0.25
    PLACEHOLDER_VALUES = {"placeholder", "todo", "tbd", "待生成", "待补充", "占位符"}
    MOJIBAKE_MARKERS = ("锛", "绗", "鏂", "鍦", "涓", "瀹", "鎴", "鐨", "鏄")

    def __init__(self, config: dict = None):
        self.config = config or {}

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "")).strip()
        book_id = str(args.get("book_id", "")).strip()
        try:
            chapter_num = int(args.get("chapter_num"))
        except Exception:
            return ToolResult.fail("chapter_num must be an integer")
        if not action:
            return ToolResult.fail("action is required")
        if not book_id:
            return ToolResult.fail("book_id is required")

        try:
            from bridge.textbook_bridge import get_bridge

            bridge = get_bridge()
            if not bridge.get_textbook(book_id):
                return ToolResult.fail(f"Textbook not found: {book_id}")
            mgr = bridge._memory_manager.get_truth_manager(book_id)

            if action == "read":
                return self._read(mgr, book_id, chapter_num)
            if action == "status":
                return ToolResult.success(self._status_payload(mgr, book_id, chapter_num))
            if action == "validate_encoding":
                return ToolResult.success(self._validate(mgr, book_id, chapter_num))
            if action == "mark_completed":
                return self._mark_completed(mgr, book_id, chapter_num)
            if action in ("write_chapter", "append_section", "replace_section"):
                content = args.get("content", "")
                if not isinstance(content, str):
                    return ToolResult.fail("content must be a string")
                if action == "write_chapter":
                    return self._write_chapter(
                        mgr,
                        book_id,
                        chapter_num,
                        content,
                        bool(args.get("completed", False)),
                        bool(args.get("allow_overwrite", False)),
                    )
                heading = str(args.get("heading", "")).strip()
                if not heading:
                    return ToolResult.fail("heading is required for append_section/replace_section")
                if action == "append_section":
                    return self._append_section(mgr, book_id, chapter_num, heading, content, bool(args.get("completed", False)))
                return self._replace_section(mgr, book_id, chapter_num, heading, content, bool(args.get("completed", False)))

            return ToolResult.fail(f"unknown action: {action}")
        except Exception as exc:
            return ToolResult.fail(f"textbook_chapter error: {exc}")

    def _read(self, mgr, book_id: str, chapter_num: int) -> ToolResult:
        content = mgr.read_chapter(chapter_num)
        return ToolResult.success({
            "book_id": book_id,
            "chapter_num": chapter_num,
            "path": os.path.relpath(mgr._chapter_path(chapter_num), mgr.book_dir).replace("\\", "/"),
            "chars": len(content),
            "content": content,
            "encoding": self._validate_text(content),
        })

    def _write_chapter(self, mgr, book_id: str, chapter_num: int, content: str, completed: bool, allow_overwrite: bool = False) -> ToolResult:
        existing = mgr.read_chapter(chapter_num)
        safety_error = self._overwrite_safety_error(existing, content, completed, allow_overwrite)
        if safety_error:
            return ToolResult.fail(safety_error)
        backup_path = self._backup_existing_chapter(mgr, chapter_num, existing, content)
        mgr.write_chapter(chapter_num, content)
        self._write_metadata(mgr, chapter_num, content, completed)
        self._update_status(mgr, book_id, chapter_num, "persist_chapter" if completed else "write_chapter")
        payload = self._result_payload(mgr, book_id, chapter_num, "written", content, completed, source_chars=len(content))
        if backup_path:
            payload["backup_path"] = backup_path
        return ToolResult.success(payload)

    def _mark_completed(self, mgr, book_id: str, chapter_num: int) -> ToolResult:
        content = mgr.read_chapter(chapter_num)
        if len(content.strip()) < self.MIN_COMPLETED_CHARS:
            return ToolResult.fail(
                "Refusing to mark chapter completed because the existing chapter is too short. "
                "Write or append the chapter content first, then call mark_completed."
            )
        self._write_metadata(mgr, chapter_num, content, True)
        self._update_status(mgr, book_id, chapter_num, "persist_chapter")
        return ToolResult.success(self._result_payload(mgr, book_id, chapter_num, "completed", content, True))

    def _append_section(self, mgr, book_id: str, chapter_num: int, heading: str, content: str, completed: bool) -> ToolResult:
        existing = mgr.read_chapter(chapter_num)
        section = self._normalize_section(heading, content)
        if heading and self._find_heading(existing, heading)[0] >= 0:
            combined = self._append_to_existing_section(existing, heading, section)
            action = "appended_existing"
        else:
            combined = (existing.rstrip() + "\n\n" + section.rstrip() + "\n") if existing.strip() else section.rstrip() + "\n"
            action = "appended"
        mgr.write_chapter(chapter_num, combined)
        self._write_metadata(mgr, chapter_num, combined, completed)
        self._update_status(mgr, book_id, chapter_num, "persist_chapter" if completed else "write_chapter")
        return ToolResult.success(self._result_payload(mgr, book_id, chapter_num, action, combined, completed, heading, source_chars=len(content)))

    def _replace_section(self, mgr, book_id: str, chapter_num: int, heading: str, content: str, completed: bool) -> ToolResult:
        existing = mgr.read_chapter(chapter_num)
        start, end = self._find_section_bounds(existing, heading)
        if start < 0:
            return ToolResult.fail(f"section not found: {heading}. Use append_section if this is a new section.")
        section = self._normalize_section(heading, content).rstrip()
        updated = existing[:start].rstrip() + "\n\n" + section + "\n\n" + existing[end:].lstrip()
        mgr.write_chapter(chapter_num, updated)
        self._write_metadata(mgr, chapter_num, updated, completed)
        self._update_status(mgr, book_id, chapter_num, "persist_chapter" if completed else "write_chapter")
        return ToolResult.success(self._result_payload(mgr, book_id, chapter_num, "replaced", updated, completed, heading, source_chars=len(content)))

    def _validate(self, mgr, book_id: str, chapter_num: int) -> Dict[str, Any]:
        path = mgr._chapter_path(chapter_num)
        raw = b""
        if os.path.exists(path):
            with open(path, "rb") as f:
                raw = f.read()
        try:
            text = raw.decode("utf-8")
            decode_ok = True
            replacement_chars = text.count("\ufffd")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
            decode_ok = False
            replacement_chars = text.count("\ufffd")
        encoding = self._validate_text(text)
        return {
            "book_id": book_id,
            "chapter_num": chapter_num,
            "path": path,
            "bytes": len(raw),
            "chars": len(text),
            "utf8_decode_ok": decode_ok,
            "replacement_chars": replacement_chars,
            **encoding,
        }

    def _result_payload(
        self,
        mgr,
        book_id: str,
        chapter_num: int,
        action: str,
        content: str,
        completed: bool,
        heading: str = "",
        source_chars: int = 0,
    ) -> Dict[str, Any]:
        payload = {
            "book_id": book_id,
            "chapter_num": chapter_num,
            "action": action,
            "heading": heading,
            "path": mgr._chapter_path(chapter_num),
            "chars": len(content),
            "completed": completed,
            "encoding": self._validate_text(content),
            "message": "Chapter content saved through canonical UTF-8 textbook_chapter tool.",
        }
        if source_chars > self.WARN_CHUNK_CHARS:
            payload["warning"] = (
                f"Large content accepted ({source_chars} chars). "
                "For faster streaming, prefer subsection-sized calls next time."
            )
        return payload

    def _status_payload(self, mgr, book_id: str, chapter_num: int) -> Dict[str, Any]:
        return {
            "book_id": book_id,
            "chapter_num": chapter_num,
            "status": mgr.get_status(),
            "chapter_metadata": mgr.get_chapter_metadata(chapter_num),
            "chapter_chars": len(mgr.read_chapter(chapter_num)),
            "chapter_path": mgr._chapter_path(chapter_num),
        }

    def _write_metadata(self, mgr, chapter_num: int, content: str, completed: bool) -> None:
        meta = {
            "status": "completed" if completed else "draft",
            "content_hash": mgr.content_hash(content),
            "chars": len(content),
            "tool": self.name,
        }
        path = mgr.chapter_metadata_path(chapter_num)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _backup_existing_chapter(self, mgr, chapter_num: int, existing: str, new_content: str) -> str:
        if not existing.strip() or existing == new_content:
            return ""
        backup_dir = os.path.join(mgr.book_dir, "state", "chapter_backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = os.path.join(backup_dir, f"chapter_{chapter_num:03d}_{stamp}.md")
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(existing)
        return backup_path

    @classmethod
    def _overwrite_safety_error(cls, existing: str, content: str, completed: bool, allow_overwrite: bool = False) -> str:
        normalized = (content or "").strip()
        lowered = normalized.lower()
        if not normalized:
            return (
                "Refusing to write empty chapter content. Use append_section/replace_section for edits, "
                "or mark_completed to only update completion status."
            )
        if lowered in cls.PLACEHOLDER_VALUES:
            return (
                "Refusing to overwrite chapter with placeholder content. "
                "Use mark_completed to update status without changing the chapter body."
            )
        existing_len = len((existing or "").strip())
        content_len = len(normalized)
        if completed and content_len < cls.MIN_COMPLETED_CHARS:
            return (
                "Refusing to mark a very short write_chapter payload as completed. "
                "Use mark_completed for existing content, or provide the full chapter body."
            )
        if (
            existing_len >= cls.DANGEROUS_OVERWRITE_EXISTING_CHARS
            and content_len < existing_len * cls.DANGEROUS_OVERWRITE_RATIO
        ):
            return (
                f"Refusing dangerous full-chapter overwrite: existing chapter has {existing_len} chars, "
                f"new content has {content_len} chars. Use replace_section/append_section for partial edits, "
                "or provide a complete chapter body."
            )
        if existing_len >= cls.DANGEROUS_OVERWRITE_EXISTING_CHARS and not allow_overwrite:
            return (
                f"Refusing full-chapter overwrite of an existing chapter ({existing_len} chars). "
                "Use replace_section/append_section for partial edits, mark_completed for status-only updates, "
                "or pass allow_overwrite=true only for an intentional full rewrite."
            )
        return ""

    def _update_status(self, mgr, book_id: str, chapter_num: int, phase: str) -> None:
        total = 0
        try:
            from bridge.textbook_bridge import get_bridge
            config = get_bridge().get_textbook(book_id)
            total = int(getattr(config, "total_chapters", 0) or 0)
        except Exception:
            pass
        mgr.update_status(
            total_chapters=total,
            current_chapter=chapter_num,
            current_phase=phase,
            run_status="running",
            extra={"chapter_tool": self.name},
        )

    @classmethod
    def _normalize_section(cls, heading: str, content: str) -> str:
        body = (content or "").strip()
        if body.startswith(heading.strip()):
            return body
        return heading.strip() + "\n\n" + body

    @staticmethod
    def _heading_level(heading: str) -> int:
        return len(heading) - len(heading.lstrip("#"))

    @classmethod
    def _find_heading(cls, text: str, heading: str) -> Tuple[int, int]:
        normalized = heading.strip()
        for match in re.finditer(r"(?m)^#{1,6}\s+.*$", text or ""):
            if match.group(0).strip() == normalized:
                return match.start(), match.end()
        return -1, -1

    @classmethod
    def _find_section_bounds(cls, text: str, heading: str) -> Tuple[int, int]:
        start, heading_end = cls._find_heading(text, heading)
        if start < 0:
            return -1, -1
        level = cls._heading_level(heading.strip())
        end = len(text)
        for match in re.finditer(r"(?m)^#{1,6}\s+.*$", text[heading_end:]):
            found = match.group(0)
            if cls._heading_level(found) <= level:
                end = heading_end + match.start()
                break
        return start, end

    @classmethod
    def _append_to_existing_section(cls, existing: str, heading: str, section: str) -> str:
        start, end = cls._find_section_bounds(existing, heading)
        if start < 0:
            return (existing.rstrip() + "\n\n" + section.rstrip() + "\n") if existing.strip() else section.rstrip() + "\n"
        body = section.strip()
        if body.startswith(heading.strip()):
            body = body[len(heading.strip()):].strip()
        if not body:
            return existing
        prefix = existing[:end].rstrip()
        suffix = existing[end:].lstrip()
        updated = prefix + "\n\n" + body.rstrip() + "\n"
        if suffix:
            updated += "\n" + suffix
        return updated

    @classmethod
    def _validate_text(cls, text: str) -> Dict[str, Any]:
        marker_count = sum((text or "").count(marker) for marker in cls.MOJIBAKE_MARKERS)
        return {
            "replacement_chars": (text or "").count("\ufffd"),
            "mojibake_markers": marker_count,
            "likely_mojibake": marker_count >= 20 or "\ufffd" in (text or ""),
        }
