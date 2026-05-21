import json
import mimetypes
import os
import re
from queue import Queue, Empty

import web

from common.log import logger
from channel.web.web.utils import json_error, json_response, json_success, read_json_body, require_auth


def _require_auth():
    return require_auth()


def _get_textbook_bridge():
    from bridge.textbook_bridge import get_bridge
    return get_bridge()


class VersionHandler:
    def GET(self):
        from cli import __version__
        return json_response({"version": __version__})


class TextbookHandler:
    def GET(self):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            textbooks = bridge.list_textbooks()
            return json_success(textbooks=[t.to_dict() for t in textbooks])
        except Exception as e:
            logger.error(f"[WebChannel] Textbook list error: {e}")
            return json_error(e)

    def POST(self):
        _require_auth()
        try:
            body = read_json_body()
            from agent.textbook.models.textbook import TextbookConfig
            config = TextbookConfig.from_dict(body)
            bridge = _get_textbook_bridge()
            result = bridge.create_textbook(config)
            return json_success(textbook=result.to_dict())
        except Exception as e:
            logger.error(f"[WebChannel] Textbook create error: {e}")
            return json_error(e)


class TextbookDetailHandler:
    def GET(self, book_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            config = bridge.get_textbook(book_id)
            if config is None:
                return json_error("Textbook not found")
            return json_success(textbook=config.to_dict())
        except Exception as e:
            logger.error(f"[WebChannel] Textbook get error: {e}")
            return json_error(e)

    def PUT(self, book_id):
        _require_auth()
        try:
            body = read_json_body()
            bridge = _get_textbook_bridge()
            result = bridge.update_textbook(book_id, body)
            if result is None:
                return json_error("Textbook not found")
            return json_success(textbook=result.to_dict())
        except Exception as e:
            logger.error(f"[WebChannel] Textbook update error: {e}")
            return json_error(e)

    def DELETE(self, book_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            result = bridge.delete_textbook(book_id)
            if not result:
                return json_error("Textbook not found")
            return json_success()
        except Exception as e:
            logger.error(f"[WebChannel] Textbook delete error: {e}")
            return json_error(e)


class TextbookOutlineHandler:
    def GET(self, book_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            outline = bridge.get_outline(book_id)
            return json_success(outline=outline)
        except Exception as e:
            logger.error(f"[WebChannel] Outline get error: {e}")
            return json_error(e)

    def PUT(self, book_id):
        _require_auth()
        try:
            body = read_json_body()
            outline_content = body.get("outline_content", "")
            bridge = _get_textbook_bridge()
            bridge.update_outline(book_id, outline_content)
            return json_success()
        except Exception as e:
            logger.error(f"[WebChannel] Outline update error: {e}")
            return json_error(e)


class TextbookChaptersHandler:
    def GET(self, book_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            chapter_files = bridge.list_chapters(book_id)
            chapters = []
            for idx, fname in enumerate(chapter_files):
                try:
                    match = re.match(r"^chapter_0*(\d+)\.md$", str(fname), re.IGNORECASE)
                    num = int(match.group(1)) if match else idx + 1
                except (AttributeError, ValueError):
                    num = idx + 1
                content = bridge.get_chapter(book_id, num)
                title = f"第{num}章"
                first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
                if first_line.startswith("#"):
                    title = first_line.lstrip("#").strip() or title
                chapters.append({
                    "chapter_num": num,
                    "title": title,
                    "word_count": len(content),
                    "status": "completed" if content.strip() else "pending",
                    "file": fname,
                })
            return json_success(chapters=chapters)
        except Exception as e:
            logger.error(f"[WebChannel] Chapters list error: {e}")
            return json_error(e)


class TextbookChapterDetailHandler:
    def GET(self, book_id, num):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            content = bridge.get_chapter(book_id, int(num))
            return json_success(chapter_num=int(num), content=content)
        except Exception as e:
            logger.error(f"[WebChannel] Chapter get error: {e}")
            return json_error(e)

    def PUT(self, book_id, num):
        _require_auth()
        try:
            body = read_json_body()
            content = body.get("content", "")
            bridge = _get_textbook_bridge()
            bridge.update_chapter(book_id, int(num), content)
            return json_success()
        except Exception as e:
            logger.error(f"[WebChannel] Chapter update error: {e}")
            return json_error(e)


class TextbookPipelineHandler:
    def GET(self, book_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            status = bridge.get_pipeline_status(book_id)
            return json_success(pipeline=status)
        except Exception as e:
            logger.error(f"[WebChannel] Pipeline status error: {e}")
            return json_error(e)

    def POST(self, book_id):
        _require_auth()
        try:
            body = read_json_body()
            action = body.get("action")
            logger.info(f"[WebChannel] Pipeline POST: book_id={book_id}, action={action}")
            bridge = _get_textbook_bridge()
            logger.info(f"[WebChannel] Bridge obtained: data_dir={bridge.data_dir}")
            if action == "pause":
                result = bridge.pause_pipeline(book_id)
                return json_success(paused=result)
            elif action == "resume":
                result = bridge.resume_pipeline(book_id)
                return json_success(resumed=result)
            elif action == "cancel":
                result = bridge.cancel_pipeline(book_id)
                return json_success(cancelled=result)
            else:
                logger.info(f"[WebChannel] Calling bridge.start_pipeline({book_id})")
                info = bridge.start_pipeline(book_id, sse_queue=None)
                logger.info(f"[WebChannel] start_pipeline returned: status={info.get('status')}, error={info.get('error')}")
                logger.info(f"[WebChannel] info keys: {list(info.keys())}, types: {[(k, type(v).__name__) for k, v in info.items()]}")
                if info.get("error"):
                    return json_error(info["error"])
                return json_success(
                    pipeline={
                        "book_id": info["book_id"],
                        "status": info["status"],
                        "started_at": info.get("started_at", ""),
                    },
                )
        except Exception as e:
            import traceback
            logger.error(f"[WebChannel] Pipeline start error: {e}\n{traceback.format_exc()}")
            return json_error(str(e) or repr(e) or "Unknown error")


class TextbookPipelineStreamHandler:
    def GET(self, book_id):
        _require_auth()
        web.header('Content-Type', 'text/event-stream; charset=utf-8')
        web.header('Cache-Control', 'no-cache')
        web.header('X-Accel-Buffering', 'no')
        q = Queue()
        bridge = _get_textbook_bridge()
        bridge.register_sse_queue(q)

        def _iter():
            try:
                status = bridge.get_pipeline_status(book_id)
                yield f"data: {json.dumps({'type': 'pipeline_status', 'data': status}, ensure_ascii=False)}\n\n".encode("utf-8")
                while True:
                    try:
                        item = q.get(timeout=20)
                    except Empty:
                        status = bridge.get_pipeline_status(book_id)
                        yield f"data: {json.dumps({'type': 'pipeline_status', 'data': status}, ensure_ascii=False)}\n\n".encode("utf-8")
                        if status.get("status") in ("completed", "error", "cancelled", "none"):
                            break
                        continue
                    if not isinstance(item, dict):
                        continue
                    data = item.get("data", {})
                    event_book_id = data.get("book_id") or item.get("book_id")
                    if event_book_id and event_book_id != book_id:
                        continue
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode("utf-8")
                    if item.get("type") in ("pipeline_complete", "pipeline_error"):
                        break
            finally:
                bridge.unregister_sse_queue(q)

        return _iter()


class TextbookExportHandler:
    def GET(self, book_id):
        _require_auth()
        try:
            params = web.input(template="academic", chapters="", format="word", range="all", chapter="")
            export_format = (params.format or "word").lower()
            if export_format != "word":
                return json_error("PDF export is not supported yet; please export Word first.")
            template = params.template
            chapters_param = params.chapters
            if not chapters_param and params.range == "chapter" and params.chapter:
                chapters_param = params.chapter
            chapter_numbers = None
            if chapters_param:
                chapter_numbers = [int(c.strip()) for c in chapters_param.split(",") if c.strip()]
            bridge = _get_textbook_bridge()
            output_path = bridge.export_word(book_id, template_name=template, chapter_numbers=chapter_numbers)
            if not output_path:
                return json_error("Export failed")
            from urllib.parse import quote
            import os as _os
            file_url = f"/api/file?path={quote(output_path)}"
            filename = _os.path.basename(output_path)
            return json_success(file_url=file_url, file_path=output_path, filename=filename)
        except Exception as e:
            logger.error(f"[WebChannel] Export error: {e}")
            return json_error(e)


class SandboxExecuteHandler:
    def POST(self):
        _require_auth()
        try:
            body = read_json_body()
            code = body.get("code", "")
            timeout = body.get("timeout", 30)
            bridge = _get_textbook_bridge()
            result = bridge.execute_sandbox(code, timeout=timeout)
            return json_success(result=result)
        except Exception as e:
            logger.error(f"[WebChannel] Sandbox execute error: {e}")
            return json_error(e)


class SandboxChartHandler:
    def POST(self):
        _require_auth()
        try:
            body = read_json_body()
            chart_type = body.get("chart_type", "")
            data = body.get("data", {})
            filename = body.get("filename", "")
            bridge = _get_textbook_bridge()
            result = bridge.generate_chart(chart_type, data, filename=filename)
            return json_success(result=result)
        except Exception as e:
            logger.error(f"[WebChannel] Chart generation error: {e}")
            return json_error(e)


class TextbookOutlineVersionHandler:
    def GET(self, book_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            versions = bridge.list_outline_versions(book_id)
            return json_success(versions=versions)
        except Exception as e:
            logger.error(f"[WebChannel] Outline versions list error: {e}")
            return json_error(e)

    def POST(self, book_id):
        _require_auth()
        try:
            body = read_json_body()
            content = body.get("content", "")
            message = body.get("message", "")
            bridge = _get_textbook_bridge()
            result = bridge.save_outline_version(book_id, content, message)
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Outline version save error: {e}")
            return json_error(e)


class TextbookOutlineVersionDetailHandler:
    def GET(self, book_id, version_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            content = bridge.get_outline_version(book_id, version_id)
            return json_success(version_id=version_id, content=content)
        except Exception as e:
            logger.error(f"[WebChannel] Outline version get error: {e}")
            return json_error(e)


class TextbookOutlineVersionRestoreHandler:
    def POST(self, book_id, version_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            result = bridge.restore_outline_version(book_id, version_id)
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Outline version restore error: {e}")
            return json_error(e)


class TextbookReviewHandler:
    def POST(self, book_id):
        _require_auth()
        try:
            body = read_json_body()
            level = body.get("level", "outline")
            target = body.get("target", "")
            bridge = _get_textbook_bridge()
            result = bridge.review_content(book_id, level, target)
            return json_success(result=result)
        except Exception as e:
            logger.error(f"[WebChannel] Review error: {e}")
            return json_error(e)


class TextbookPreferencesHandler:
    def GET(self, book_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            preferences = bridge.get_preferences(book_id)
            return json_success(preferences=preferences)
        except Exception as e:
            logger.error(f"[WebChannel] Preferences get error: {e}")
            return json_error(e)

    def PUT(self, book_id):
        _require_auth()
        try:
            body = read_json_body()
            bridge = _get_textbook_bridge()
            result = bridge.update_preferences(book_id, body)
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Preferences update error: {e}")
            return json_error(e)


class ChatHistorySaveHandler:
    def POST(self):
        _require_auth()
        try:
            body = read_json_body()
            session_id = body.get("session_id", "")
            role = body.get("role", "")
            content = body.get("content", "")
            tool_calls = body.get("tool_calls", [])
            bridge = _get_textbook_bridge()
            result = bridge.save_chat_message(session_id, role, content, tool_calls)
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Chat history save error: {e}")
            return json_error(e)


class ChatHistoryLoadHandler:
    def GET(self, session_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            messages = bridge.load_chat_history(session_id)
            return json_success(messages=messages)
        except Exception as e:
            logger.error(f"[WebChannel] Chat history load error: {e}")
            return json_error(e)


class ChatSessionsHandler:
    def GET(self):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            sessions = bridge.list_chat_sessions()
            return json_success(sessions=sessions)
        except Exception as e:
            logger.error(f"[WebChannel] Chat sessions list error: {e}")
            return json_error(e)


class ChatHistoryClearHandler:
    def DELETE(self, session_id):
        _require_auth()
        try:
            bridge = _get_textbook_bridge()
            result = bridge.clear_chat_history(session_id)
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Chat history clear error: {e}")
            return json_error(e)


class ChatCancelHandler:
    def POST(self):
        _require_auth()
        try:
            body = read_json_body()
            session_id = body.get("session_id", "")
            if not session_id:
                return json_error("session_id is required")

            from bridge.bridge import Bridge
            ab = Bridge().get_agent_bridge()
            agent = ab.agents.get(session_id)
            if agent:
                agent.cancel()
                logger.info(f"[WebChannel] Agent for session {session_id} cancel event set")

            return json_success(message="Chat cancelled")
        except Exception as e:
            logger.error(f"[WebChannel] Chat cancel error: {e}")
            return json_error(e)
