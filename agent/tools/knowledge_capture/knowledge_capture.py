"""Tool for saving useful web evidence into knowledge source files."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from agent.knowledge.service import KnowledgeService
from agent.tools.base_tool import BaseTool, ToolResult


class KnowledgeCapture(BaseTool):
    """Save judged-useful web content as a Markdown source in the knowledge base."""

    name: str = "knowledge_capture"
    description: str = (
        "Save useful web content into the knowledge source directory as a Markdown file. "
        "Use after web_fetch opens an original source URL and the content is relevant to the current textbook task."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Original source URL, not a search-result page."},
            "title": {"type": "string", "description": "Source title."},
            "content": {"type": "string", "description": "Extracted source content from web_fetch or a faithful concise extraction."},
            "reason": {"type": "string", "description": "Why this source is useful and when future agents should use it."},
            "book_id": {"type": "string", "description": "Optional textbook/knowledge base id."},
            "tags": {"type": "array", "description": "Optional topic tags for future retrieval."},
            "force": {"type": "boolean", "description": "Override basic usefulness guards for trusted short official sources."},
        },
        "required": ["url", "content", "reason"],
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.memory_manager = self.config.get("memory_manager", None)

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        url = (args.get("url") or "").strip()
        content = args.get("content") or ""
        reason = (args.get("reason") or "").strip()
        title = (args.get("title") or "").strip() or self._guess_title(content, url)
        book_id = (args.get("book_id") or "").strip()
        tags = args.get("tags") or []
        force = bool(args.get("force", False))

        if not url:
            return ToolResult.fail("Error: url parameter is required")
        if not str(content).strip():
            return ToolResult.fail("Error: content parameter is required")
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.split(",") if item.strip()]
        if not isinstance(tags, list):
            return ToolResult.fail("Error: tags must be an array or comma-separated string")

        try:
            result = KnowledgeService(self.cwd).save_web_source(
                url=url,
                title=title,
                content=str(content),
                reason=reason,
                book_id=book_id,
                tags=tags,
                force=force,
            )
            if result.get("useful") and self.memory_manager:
                try:
                    self.memory_manager.mark_dirty()
                except Exception:
                    pass
            return ToolResult.success(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            return ToolResult.fail(f"Error saving web knowledge source: {e}")

    def _guess_title(self, content: str, url: str) -> str:
        first_line = (content or "").strip().splitlines()[0:1]
        if first_line:
            line = re.sub(r"^#+\s*", "", first_line[0]).strip()
            if line:
                return line[:80]
        return url.rstrip("/").split("/")[-1] or "Web source"
