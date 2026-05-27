import os
from typing import Any, Dict

from agent.tools.base_tool import BaseTool, ToolResult


class TextbookOutlineTool(BaseTool):
    name: str = "textbook_outline"
    description: str = (
        "Canonical textbook outline tool. Use this instead of write/edit/bash/textbook_chapter "
        "when reading, writing, or replacing a textbook outline or terminology table. It writes "
        "outline content only to outline/outline.md and terminology only to outline/terminology.md."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of: read, write_outline, write_terminology",
            },
            "book_id": {
                "type": "string",
                "description": "Textbook id, for example tb_3df776e0",
            },
            "content": {
                "type": "string",
                "description": "UTF-8 Markdown content for write_outline or write_terminology.",
            },
        },
        "required": ["action", "book_id"],
    }

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "") or "").strip()
        book_id = str(args.get("book_id", "") or "").strip()
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
                return ToolResult.success({
                    "book_id": book_id,
                    "outline": mgr.read("outline"),
                    "terminology": mgr.read("terminology"),
                    "outline_path": "outline/outline.md",
                    "terminology_path": "outline/terminology.md",
                })

            content = args.get("content", "")
            if not isinstance(content, str):
                return ToolResult.fail("content must be a string")

            if action == "write_outline":
                bridge.update_outline(book_id, content)
                self._update_status(mgr, bridge, book_id, "outline")
                return ToolResult.success(self._payload(mgr, book_id, "outline", content))

            if action == "write_terminology":
                mgr.write("terminology", content)
                self._update_status(mgr, bridge, book_id, "outline")
                return ToolResult.success(self._payload(mgr, book_id, "terminology", content))

            return ToolResult.fail(f"unknown action: {action}")
        except Exception as exc:
            return ToolResult.fail(f"textbook_outline error: {exc}")

    def _payload(self, mgr, book_id: str, file_key: str, content: str) -> Dict[str, Any]:
        rel_path = mgr.TRUTH_FILES[file_key].replace("\\", "/")
        return {
            "book_id": book_id,
            "action": f"write_{file_key}",
            "path": rel_path,
            "absolute_path": os.path.join(mgr.book_dir, rel_path),
            "chars": len(content),
            "content_hash": mgr.content_hash(content),
            "message": "Textbook outline artifact saved through canonical textbook_outline tool.",
        }

    @staticmethod
    def _update_status(mgr, bridge, book_id: str, phase: str) -> None:
        config = bridge.get_textbook(book_id)
        total = int(getattr(config, "total_chapters", 0) or 0) if config else 0
        mgr.update_status(
            total_chapters=total,
            current_chapter=None,
            current_phase=phase,
            run_status="running",
            extra={"outline_tool": TextbookOutlineTool.name},
        )
