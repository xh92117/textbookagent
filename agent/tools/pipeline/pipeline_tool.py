import json
import logging
from typing import Dict, Any

from agent.tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class StartPipeline(BaseTool):
    name: str = "start_pipeline"
    description: str = (
        "Start the textbook generation pipeline. This tool launches a multi-agent pipeline "
        "that automatically generates a complete textbook with outline, chapters, review, and revision. "
        "Use this tool only when the user explicitly asks to start the full automatic compilation pipeline, "
        "one-click compile the whole textbook, or invokes a pipeline/start skill. Do not use it for ordinary "
        "textbook creation, outline editing, or single-chapter writing. The pipeline runs asynchronously in the background."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "book_id": {
                "type": "string",
                "description": "ID of an existing textbook to continue writing. If provided, the pipeline will resume from the current state of this textbook instead of creating a new one. Always prefer using book_id when the user mentions an existing textbook."
            },
            "title": {
                "type": "string",
                "description": "Title of the textbook. Used to find an existing textbook or create a new one."
            },
            "subject": {
                "type": "string",
                "description": "Subject or discipline of the textbook (e.g. '土木工程', '计算机科学')"
            },
            "target_audience": {
                "type": "string",
                "description": "Target audience (e.g. '本科生', '研究生', '从业者')"
            },
            "level": {
                "type": "string",
                "description": "Difficulty level: '入门', '中级', '高级', '中高级'"
            },
            "total_chapters": {
                "type": "integer",
                "description": "Number of chapters to generate (default: 10)"
            },
            "chapter_word_count": {
                "type": "integer",
                "description": "Target word count per chapter (default: 5000)"
            },
            "style": {
                "type": "string",
                "description": "Writing style (e.g. '学术+实务', '通俗', '严谨学术')"
            },
            "research_evidence": {
                "type": "string",
                "description": "Optional compact Web Evidence Pack created with the multi-search-engine skill and web_fetch before starting the pipeline."
            },
            "confirm_pipeline_risk": {
                "type": "boolean",
                "description": (
                    "Must be true only after the assistant has explained that automatic pipeline compilation quality is "
                    "not controlled and can be affected by context, and the user explicitly agrees to start it."
                )
            }
        },
        "required": []
    }

    def __init__(self, config: dict = None):
        self.config = config or {}

    @staticmethod
    def _tb_get(textbook, key: str, default=None):
        if isinstance(textbook, dict):
            return textbook.get(key, default)
        return getattr(textbook, key, default)

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        try:
            from bridge.textbook_bridge import get_bridge
            from agent.textbook.models.textbook import TextbookConfig

            bridge = get_bridge()
            research_evidence = args.get("research_evidence", "")
            if args.get("confirm_pipeline_risk") is not True:
                return ToolResult.fail(
                    "confirm_pipeline_risk is required before starting the pipeline. "
                    "Explain to the user that automatic compilation quality is not controlled and can be affected by context, "
                    "then ask them to reply with an explicit phrase such as '同意启动编制' before calling start_pipeline again."
                )

            title = args.get("title", "").strip()
            book_id = args.get("book_id", "").strip()

            if book_id:
                existing = bridge.get_textbook(book_id)
                if existing:
                    logger.info(f"[StartPipeline] Using existing textbook: book_id={book_id}, title={existing.title}")
                    result = bridge.start_pipeline(book_id, sse_queue=None, requirement=research_evidence)
                    if "error" in result:
                        return ToolResult.fail(result["error"])
                    return ToolResult.success({
                        "book_id": book_id,
                        "title": existing.title,
                        "status": result.get("status", "running"),
                        "message": f"教材《{existing.title}》编制管线已启动，共{existing.total_chapters}章。管线将在后台自动执行，从当前教材状态继续编制。",
                        "pipeline_status": {
                            "book_id": book_id,
                            "status": result.get("status", "running"),
                            "started_at": result.get("started_at", ""),
                            "resume_from": result.get("resume_from", ""),
                        }
                    })

            if title:
                textbooks = bridge.list_textbooks()
                for tb in textbooks:
                    tb_title = self._tb_get(tb, "title", "")
                    tb_id = self._tb_get(tb, "id", "")
                    if tb_title == title or tb_id == title:
                        found_id = tb_id
                        logger.info(f"[StartPipeline] Found existing textbook by title: book_id={found_id}")
                        result = bridge.start_pipeline(found_id, sse_queue=None, requirement=research_evidence)
                        if "error" in result:
                            return ToolResult.fail(result["error"])
                        return ToolResult.success({
                            "book_id": found_id,
                            "title": tb_title or title,
                            "status": result.get("status", "running"),
                            "message": f"教材《{tb_title or title}》编制管线已启动，共{self._tb_get(tb, 'total_chapters', 10)}章。管线将在后台自动执行，从当前教材状态继续编制。",
                            "pipeline_status": {
                                "book_id": found_id,
                                "status": result.get("status", "running"),
                                "started_at": result.get("started_at", ""),
                                "resume_from": result.get("resume_from", ""),
                            }
                        })

            if not title:
                return ToolResult.fail("title or book_id is required")

            config = TextbookConfig(
                title=title,
                subject=args.get("subject", ""),
                target_audience=args.get("target_audience", "本科生"),
                level=args.get("level", "中级"),
                total_chapters=args.get("total_chapters", 10),
                chapter_word_count=args.get("chapter_word_count", 5000),
                style=args.get("style", "学术+实务"),
            )

            logger.info(f"[StartPipeline] Creating new textbook: title={title}, chapters={config.total_chapters}")

            saved = bridge.create_textbook(config)
            book_id = saved.id

            result = bridge.start_pipeline(book_id, sse_queue=None, requirement=research_evidence)

            if "error" in result:
                return ToolResult.fail(result["error"])

            return ToolResult.success({
                "book_id": book_id,
                "title": title,
                "status": result.get("status", "running"),
                "message": f"新教材《{title}》已创建并启动编制管线，共{config.total_chapters}章，预计每章{config.chapter_word_count}字。管线将在后台自动执行。",
                "pipeline_status": {
                    "book_id": book_id,
                    "status": result.get("status", "running"),
                    "started_at": result.get("started_at", ""),
                }
            })

        except Exception as e:
            logger.error(f"[StartPipeline] Error: {e}", exc_info=True)
            return ToolResult.fail(f"Failed to start pipeline: {e}")
