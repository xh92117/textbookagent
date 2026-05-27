import logging
from typing import Any, Dict

from agent.tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class CreateTextbookTool(BaseTool):
    name: str = "create_textbook"
    description: str = (
        "Create a textbook project through the same canonical backend path used by the web textbook workspace. "
        "Use this when the user asks to create, initialize, or register a textbook project without starting the "
        "full generation pipeline. The tool writes textbook.json and returns the generated book_id."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Textbook title."},
            "subject": {"type": "string", "description": "Subject or discipline of the textbook."},
            "target_audience": {"type": "string", "description": "Target readers."},
            "level": {"type": "string", "description": "Difficulty level."},
            "total_chapters": {"type": "integer", "description": "Planned chapter count. Defaults to 10."},
            "chapter_word_count": {"type": "integer", "description": "Target words per chapter. Defaults to 5000."},
            "style": {"type": "string", "description": "Writing style."},
        },
        "required": ["title"],
    }

    @staticmethod
    def _tb_get(textbook, key: str, default=None):
        if isinstance(textbook, dict):
            return textbook.get(key, default)
        return getattr(textbook, key, default)

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        try:
            from agent.textbook.models.textbook import TextbookConfig
            from bridge.textbook_bridge import get_bridge

            bridge = get_bridge()
            title = str(args.get("title", "") or "").strip()
            if not title:
                return ToolResult.fail("title is required")

            for existing in bridge.list_textbooks():
                existing_title = self._tb_get(existing, "title", "")
                existing_id = self._tb_get(existing, "id", "")
                if existing_title == title or existing_id == title:
                    return ToolResult.success({
                        "book_id": existing_id,
                        "title": existing_title or title,
                        "textbook": existing.to_dict() if hasattr(existing, "to_dict") else existing,
                        "created": False,
                        "message": "Textbook already exists; using the existing canonical project.",
                    })

            config = TextbookConfig(
                title=title,
                subject=args.get("subject", ""),
                target_audience=args.get("target_audience", ""),
                level=args.get("level", ""),
                total_chapters=args.get("total_chapters", 10),
                chapter_word_count=args.get("chapter_word_count", 5000),
                style=args.get("style", "学术"),
            )
            saved = bridge.create_textbook(config)
            logger.info("[CreateTextbookTool] Created textbook book_id=%s title=%s", saved.id, saved.title)
            return ToolResult.success({
                "book_id": saved.id,
                "title": saved.title,
                "textbook": saved.to_dict(),
                "created": True,
                "message": "Textbook project created through canonical TextbookBridge.create_textbook.",
                "next_step": "Use textbook_chapter for chapter content, or start_pipeline when full automatic generation is requested.",
            })
        except Exception as exc:
            logger.error("[CreateTextbookTool] Error: %s", exc, exc_info=True)
            return ToolResult.fail(f"Failed to create textbook: {exc}")
