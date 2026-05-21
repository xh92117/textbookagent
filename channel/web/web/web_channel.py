import time
import json
import logging
import os
import threading
import uuid
from queue import Queue, Empty
from typing import Tuple

import web

from bridge.context import *
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.chat_message import ChatMessage
from common.log import logger
from common.run_events import RunStateRecorder, normalize_event
from common.singleton import singleton
from config import conf
from channel.web.web.routes import get_urls
from channel.web.web.handlers_core import (
    RootHandler, AuthCheckHandler, AuthLoginHandler, AuthLogoutHandler, MessageHandler,
    UploadHandler, UploadsHandler, FileServeHandler, PollHandler, StreamHandler,
    ChatHandler, TextbookPageHandler, AssetsHandler, TextbookAssetsHandler,
)
from channel.web.web.handlers_config import ConfigHandler
from channel.web.web.handlers_channels import ChannelsHandler, WeixinQrHandler, FeishuRegisterHandler
from channel.web.web.handlers_admin import (
    ToolsHandler, SkillsHandler, WorkspaceHandler, MemoryHandler, MemoryContentHandler,
    MemoryQueryHandler, SchedulerHandler, SessionsHandler, SessionDetailHandler,
    SessionTitleHandler, SessionClearContextHandler, HistoryHandler, LogsHandler,
)
from channel.web.web.handlers_knowledge import (
    KnowledgeListHandler, KnowledgeReadHandler, KnowledgeGraphHandler, KnowledgeUploadHandler,
    KnowledgeSourcesHandler, KnowledgeStatusHandler, KnowledgeSkillLinkHandler,
    KnowledgeOrganizeHandler, KnowledgeKnowledgeGraphHandler,
)
from channel.web.web.handlers_textbook import (
    VersionHandler, TextbookHandler, TextbookDetailHandler, TextbookOutlineHandler,
    TextbookChaptersHandler, TextbookChapterDetailHandler, TextbookPipelineHandler,
    TextbookPipelineStreamHandler, TextbookExportHandler, SandboxExecuteHandler,
    SandboxChartHandler, TextbookOutlineVersionHandler, TextbookOutlineVersionDetailHandler,
    TextbookOutlineVersionRestoreHandler, TextbookReviewHandler, TextbookPreferencesHandler,
    ChatHistorySaveHandler, ChatHistoryLoadHandler, ChatSessionsHandler,
    ChatHistoryClearHandler, ChatCancelHandler,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".avi", ".mov", ".mkv"}

def _get_upload_dir() -> str:
    from common.app_paths import tmp_dir as app_tmp_dir
    tmp_dir = app_tmp_dir()
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


def _get_workspace_root():
    """Resolve the agent workspace directory."""
    from common.app_paths import ensure_active_workspace
    return ensure_active_workspace()


def _get_textbook_bridge():
    from bridge.textbook_bridge import get_bridge
    return get_bridge()


def _sanitize_upload_relative_path(relative_path: str) -> str:
    """Normalize relative upload path and reject escapes / absolute paths."""
    relative_path = (relative_path or "").replace("\\", "/").strip("/")
    if not relative_path:
        raise ValueError("Empty relative path")
    parts = []
    for part in relative_path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("Invalid relative path")
        parts.append(part)
    if not parts:
        raise ValueError("Invalid relative path")
    norm_path = "/".join(parts)
    if os.path.isabs(norm_path):
        raise ValueError("Invalid relative path")
    return norm_path


def _sanitize_upload_id(upload_id: str) -> str:
    """Allow only simple batch ids for directory uploads."""
    sanitized = "".join(ch for ch in (upload_id or "") if ch.isalnum() or ch in ("-", "_"))
    if not sanitized:
        raise ValueError("Invalid upload id")
    return sanitized[:80]


def _is_within_directory(root_path: str, target_path: str) -> bool:
    try:
        return os.path.commonpath([root_path, target_path]) == root_path
    except ValueError:
        return False


def _resolve_upload_path(upload_root: str, relative_path: str) -> Tuple[str, str]:
    """Resolve a relative upload path under upload_root and reject escapes."""
    safe_rel_path = _sanitize_upload_relative_path(relative_path)
    upload_root_real = os.path.realpath(upload_root)
    save_path = os.path.realpath(os.path.join(upload_root_real, *safe_rel_path.split("/")))
    if not _is_within_directory(upload_root_real, save_path):
        raise ValueError("Invalid directory upload path")
    return safe_rel_path, save_path


def _read_uploaded_file_bytes(file_obj) -> bytes:
    """Return uploaded content as bytes across web.py upload object variants."""
    if isinstance(file_obj, bytes):
        return file_obj
    if isinstance(file_obj, str):
        return file_obj.encode("utf-8")

    content = None

    if hasattr(file_obj, "file") and hasattr(file_obj.file, "read"):
        content = file_obj.file.read()
    elif hasattr(file_obj, "read"):
        content = file_obj.read()
    elif hasattr(file_obj, "value"):
        content = file_obj.value

    if content is None:
        raise ValueError("Unable to read uploaded file content")
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    raise TypeError(f"Unsupported uploaded content type: {type(content).__name__}")


def _raw_web_input():
    """Return unprocessed multipart form data when web.py exposes rawinput."""
    rawinput = getattr(getattr(web, "webapi", None), "rawinput", None)
    if not callable(rawinput):
        raise RuntimeError("web.py rawinput is not available")
    try:
        return rawinput(method="post")
    except TypeError:
        return rawinput()


def _upload_web_input():
    """Return multipart upload params while preserving file objects."""
    try:
        return _raw_web_input()
    except Exception:
        return web.input(file={})


def _ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _generate_session_title(user_message: str, assistant_reply: str = "") -> str:
    """Delegate to the shared SessionService implementation."""
    from agent.chat.session_service import generate_session_title
    return generate_session_title(user_message, assistant_reply)


class WebMessage(ChatMessage):
    def __init__(
            self,
            msg_id,
            content,
            ctype=ContextType.TEXT,
            from_user_id="User",
            to_user_id="Chatgpt",
            other_user_id="Chatgpt",
    ):
        self.msg_id = msg_id
        self.ctype = ctype
        self.content = content
        self.from_user_id = from_user_id
        self.to_user_id = to_user_id
        self.other_user_id = other_user_id


@singleton
class WebChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = [ReplyType.VOICE]
    _instance = None

    # def __new__(cls):
    #     if cls._instance is None:
    #         cls._instance = super(WebChannel, cls).__new__(cls)
    #     return cls._instance

    def __init__(self):
        super().__init__()
        self.msg_id_counter = 0
        self.session_queues = {}  # session_id -> Queue (fallback polling)
        self.request_to_session = {}  # request_id -> session_id
        self.sse_queues = {}  # request_id -> Queue (SSE streaming)
        self._http_server = None

    def _generate_msg_id(self):
        """生成唯一的消息ID"""
        self.msg_id_counter += 1
        return str(int(time.time())) + str(self.msg_id_counter)

    def _generate_request_id(self):
        """生成唯一的请求ID"""
        return str(uuid.uuid4())

    def send(self, reply: Reply, context: Context):
        try:
            if reply.type in self.NOT_SUPPORT_REPLYTYPE:
                logger.warning(f"Web channel doesn't support {reply.type} yet")
                return

            if reply.type == ReplyType.IMAGE_URL:
                time.sleep(0.5)

            request_id = context.get("request_id", None)
            if not request_id:
                logger.error("No request_id found in context, cannot send message")
                return

            session_id = self.request_to_session.get(request_id)
            if not session_id:
                logger.error(f"No session_id found for request {request_id}")
                return

            # SSE mode: push events to SSE queue
            if request_id in self.sse_queues:
                content = reply.content if reply.content is not None else ""

                # Intermediate status lines (e.g. /install-browser phases) must NOT use "done",
                # or the frontend closes EventSource and drops subsequent events.
                if getattr(reply, "sse_phase", False):
                    self.sse_queues[request_id].put({
                        "type": "phase",
                        "content": content,
                        "request_id": request_id,
                        "timestamp": time.time(),
                    })
                    logger.debug(f"SSE phase for request {request_id}")
                    return

                # Files are already pushed via on_event (file_to_send) during agent execution.
                # Skip duplicate file pushes here; just let the done event through.
                if reply.type in (ReplyType.IMAGE_URL, ReplyType.FILE) and content.startswith("file://"):
                    text_content = getattr(reply, 'text_content', '')
                    if text_content:
                        self.sse_queues[request_id].put({
                            "type": "done",
                            "content": text_content,
                            "request_id": request_id,
                            "timestamp": time.time()
                        })
                    logger.debug(f"SSE skipped duplicate file for request {request_id}")
                    return

                # Skip http-URL FILE/IMAGE_URL replies produced by chat_channel's media extraction:
                # the text reply (already sent as "done") contains the URL and the frontend will
                # render it via renderMarkdown/injectVideoPlayers, so no separate SSE event needed.
                if reply.type in (ReplyType.FILE, ReplyType.IMAGE_URL) and content.startswith(("http://", "https://")):
                    logger.debug(f"SSE skipped http media reply for request {request_id}")
                    return

                self.sse_queues[request_id].put({
                    "type": "done",
                    "content": content,
                    "request_id": request_id,
                    "timestamp": time.time()
                })
                logger.debug(f"SSE done sent for request {request_id}")
                return

            # Fallback: polling mode
            if session_id in self.session_queues:
                content = reply.content if reply.content is not None else ""
                # Skip file:// IMAGE_URL/FILE replies originating from an SSE-enabled
                # request: they were already pushed via the `file_to_send` event during
                # agent execution. By the time the chat_channel sends the IMAGE_URL reply,
                # the SSE stream has typically closed (after the text "done") and the
                # request_id is gone from sse_queues, so we'd otherwise duplicate the file
                # as a polling bubble. Scheduler/push tasks have no on_event and must
                # still go through polling normally.
                if (
                    reply.type in (ReplyType.IMAGE_URL, ReplyType.FILE)
                    and content.startswith("file://")
                    and context.get("on_event") is not None
                ):
                    logger.debug(f"Polling skipped duplicate file reply for session {session_id}")
                    return
                response_data = {
                    "type": str(reply.type),
                    "content": content,
                    "timestamp": time.time(),
                    "request_id": request_id
                }
                self.session_queues[session_id].put(response_data)
                logger.debug(f"Response sent to poll queue for session {session_id}, request {request_id}")
            else:
                logger.warning(f"No response queue found for session {session_id}, response dropped")

        except Exception as e:
            logger.error(f"Error in send method: {e}")

    def _make_sse_callback(self, request_id: str):
        """Build an on_event callback that pushes agent stream events into the SSE queue."""

        # Cap reasoning bytes pushed to the frontend per request to avoid
        # browser stalls / crashes on very long chains-of-thought. Anything
        # beyond the cap is dropped from the stream (DB still persists a
        # truncated copy via _truncate_reasoning_for_storage).
        # Keep aligned with frontend REASONING_RENDER_CAP and backend
        # MAX_STORED_REASONING_CHARS.
        MAX_REASONING_STREAM_CHARS = 4 * 1024  # 4 KB
        # Use a single-element list as a mutable counter accessible from closure.
        reasoning_chars_sent = [0]
        reasoning_capped_notified = [False]
        run_events_dir = os.path.join(_get_workspace_root(), ".runs", "chat", request_id)
        run_recorder = RunStateRecorder(run_events_dir, run_id=request_id, source="chat")

        def on_event(event: dict):
            if request_id not in self.sse_queues:
                return
            q = self.sse_queues[request_id]
            event_type = event.get("type")
            data = event.get("data", {})
            normalized = run_recorder.record(event)
            q.put({"type": "run_event", "data": normalized})

            if event_type == "reasoning_update":
                delta = data.get("delta", "")
                if not delta:
                    return
                remaining = MAX_REASONING_STREAM_CHARS - reasoning_chars_sent[0]
                if remaining <= 0:
                    if not reasoning_capped_notified[0]:
                        reasoning_capped_notified[0] = True
                        q.put({
                            "type": "reasoning",
                            "content": "\n\n... [reasoning truncated for display] ...",
                        })
                    return
                if len(delta) > remaining:
                    delta = delta[:remaining]
                reasoning_chars_sent[0] += len(delta)
                q.put({"type": "reasoning", "content": delta})

            elif event_type == "message_update":
                delta = data.get("delta", "")
                if delta:
                    q.put({"type": "delta", "content": delta})

            elif event_type == "tool_execution_start":
                tool_name = data.get("tool_name", "tool")
                arguments = data.get("arguments", {})
                q.put({"type": "tool_start", "tool": tool_name, "arguments": arguments})

            elif event_type == "tool_execution_end":
                tool_name = data.get("tool_name", "tool")
                status = data.get("status", "success")
                result = data.get("result", "")
                exec_time = data.get("execution_time", 0)
                try:
                    result_str = json.dumps(result, ensure_ascii=False)
                except (TypeError, ValueError):
                    result_str = str(result)
                if len(result_str) > 2000:
                    result_str = result_str[:2000] + "…"
                q.put({
                    "type": "tool_end",
                    "tool": tool_name,
                    "status": status,
                    "result": result_str,
                    "execution_time": round(exec_time, 2)
                })

            elif event_type == "message_end":
                tool_calls = data.get("tool_calls", [])
                if tool_calls:
                    q.put({"type": "message_end", "has_tool_calls": True})

            elif event_type == "llm_thinking":
                elapsed = data.get("elapsed_seconds", 0)
                q.put({"type": "llm_thinking", "elapsed_seconds": elapsed})

            elif event_type in ("pipeline_start", "phase_start", "phase_complete", "pipeline_complete", "pipeline_error", "phase_progress"):
                q.put({"type": event_type, "data": data})

            elif event_type == "agent_end":
                # Safety net: if the agent finishes with an empty final_response,
                # chat_channel skips _send_reply (because reply.content is empty),
                # which means no "done" event is ever emitted and the SSE stream
                # would hang until the 10-min idle timeout. Push a fallback "done"
                # here so the frontend always gets closure.
                final_response = data.get("final_response", "")
                if not final_response or not str(final_response).strip():
                    logger.warning(
                        f"[WebChannel] agent_end with empty final_response for "
                        f"request {request_id}, sending fallback done"
                    )
                    q.put({
                        "type": "done",
                        "content": "(模型未返回任何内容，请重试或换一种方式描述你的需求)",
                        "request_id": request_id,
                        "timestamp": time.time(),
                    })

            elif event_type == "file_to_send":
                file_path = data.get("path", "")
                file_name = data.get("file_name", os.path.basename(file_path))
                file_type = data.get("file_type", "file")
                from urllib.parse import quote
                web_url = f"/api/file?path={quote(file_path)}"
                is_image = file_type == "image"
                q.put({
                    "type": "image" if is_image else "file",
                    "content": web_url,
                    "file_name": file_name,
                })

        return on_event

    def upload_file(self):
        """Handle file or directory upload via multipart/form-data."""
        try:
            params = _upload_web_input()
            file_obj = params.get("file")
            file_objs = params.get("files")
            session_id = params.get("session_id", "")
            relative_path = params.get("relative_path", "")
            relative_paths = params.get("relative_paths")
            upload_id = params.get("upload_id", "")

            directory_files = _ensure_list(file_objs)

            if not directory_files and file_obj and relative_path:
                directory_files = [file_obj]

            directory_rel_paths = _ensure_list(relative_paths)

            if not directory_rel_paths and relative_path:
                directory_rel_paths = [relative_path]

            is_directory_upload = bool(directory_files or directory_rel_paths or relative_path or upload_id)

            upload_dir = _get_upload_dir()
            if is_directory_upload:
                if not upload_id:
                    return json.dumps({"status": "error", "message": "Missing upload_id for directory upload"})
                if not directory_files:
                    return json.dumps({"status": "error", "message": "No files uploaded"})
                if len(directory_files) != len(directory_rel_paths):
                    return json.dumps({"status": "error", "message": "Directory upload payload mismatch"})

                safe_upload_id = _sanitize_upload_id(upload_id)
                upload_root = os.path.join(upload_dir, f"webdir_{safe_upload_id}")
                upload_root_real = os.path.realpath(upload_root)

                root_name = None
                saved_files = 0
                for file_obj, rel_path in zip(directory_files, directory_rel_paths):
                    if file_obj is None:
                        raise ValueError("Invalid uploaded file")
                    safe_rel_path, save_path = _resolve_upload_path(upload_root_real, rel_path)
                    current_root_name = safe_rel_path.split("/", 1)[0]
                    if root_name is None:
                        root_name = current_root_name
                    elif root_name != current_root_name:
                        raise ValueError("Directory upload must use a single root folder")
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    content_bytes = _read_uploaded_file_bytes(file_obj)
                    with open(save_path, "wb") as f:
                        f.write(content_bytes)
                    saved_files += 1

                if not root_name:
                    raise ValueError("Directory root path missing")

                root_path = os.path.realpath(os.path.join(upload_root_real, root_name))
                if not _is_within_directory(upload_root_real, root_path):
                    raise ValueError("Invalid directory upload path")

                logger.info(f"[WebChannel] Directory uploaded: {root_name} -> {root_path} ({saved_files} files)")
                return json.dumps({
                    "status": "success",
                    "file_path": root_path,
                    "file_name": root_name,
                    "file_type": "directory",
                    "file_count": saved_files,
                    "root_path": root_path,
                    "root_name": root_name,
                    "upload_type": "directory",
                }, ensure_ascii=False)

            if file_obj is None or not hasattr(file_obj, "filename") or not file_obj.filename:
                return json.dumps({"status": "error", "message": "No file uploaded"})

            original_name = os.path.basename(str(file_obj.filename).replace("\\", "/"))
            if not original_name:
                return json.dumps({"status": "error", "message": "No file uploaded"})
            ext = os.path.splitext(original_name)[1].lower()
            safe_name = f"web_{uuid.uuid4().hex[:8]}{ext}"
            save_path = os.path.join(upload_dir, safe_name)
            public_path = safe_name
            display_name = original_name

            content_bytes = _read_uploaded_file_bytes(file_obj)
            with open(save_path, "wb") as f:
                f.write(content_bytes)

            if ext in IMAGE_EXTENSIONS:
                file_type = "image"
            elif ext in VIDEO_EXTENSIONS:
                file_type = "video"
            else:
                file_type = "file"

            from urllib.parse import quote
            preview_url = f"/uploads/{quote(public_path, safe='/')}"

            logger.info(f"[WebChannel] File uploaded: {original_name} -> {save_path} ({file_type})")

            return json.dumps({
                "status": "success",
                "file_path": save_path,
                "file_name": display_name,
                "file_type": file_type,
                "preview_url": preview_url,
            }, ensure_ascii=False)

        except Exception as e:
            logger.error(f"[WebChannel] File upload error: {e}", exc_info=True)
            return json.dumps({"status": "error", "message": str(e)})

    def post_message(self):
        """
        Handle incoming messages from users via POST request.
        Returns a request_id for tracking this specific request.
        Supports optional attachments (file paths from /upload).
        """
        try:
            data = web.data()
            json_data = json.loads(data)
            session_id = json_data.get('session_id', f'session_{int(time.time())}')
            prompt = json_data.get('message', '')
            use_sse = json_data.get('stream', True)
            attachments = json_data.get('attachments', [])
            book_id = json_data.get('book_id', '')

            # Append file references to the prompt (same format as QQ channel)
            if attachments:
                file_refs = []
                for att in attachments:
                    ftype = att.get("file_type", "file")
                    fpath = att.get("file_path", "")
                    if not fpath:
                        continue
                    if ftype == "image":
                        file_refs.append(f"[图片: {fpath}]")
                    elif ftype == "video":
                        file_refs.append(f"[视频: {fpath}]")
                    elif ftype == "directory":
                        file_refs.append(f"[目录: {fpath}]")
                    else:
                        file_refs.append(f"[文件: {fpath}]")
                if file_refs:
                    prompt = prompt + "\n" + "\n".join(file_refs)
                    logger.info(f"[WebChannel] Attached {len(file_refs)} file(s) to message")

            request_id = self._generate_request_id()
            self.request_to_session[request_id] = session_id

            if session_id not in self.session_queues:
                self.session_queues[session_id] = Queue()

            if use_sse:
                self.sse_queues[request_id] = Queue()

            trigger_prefixs = conf().get("single_chat_prefix", [""])
            if check_prefix(prompt, trigger_prefixs) is None:
                if trigger_prefixs:
                    prompt = trigger_prefixs[0] + prompt
                    logger.debug(f"[WebChannel] Added prefix to message: {prompt}")

            msg = WebMessage(self._generate_msg_id(), prompt)
            msg.from_user_id = session_id

            context = self._compose_context(ContextType.TEXT, prompt, msg=msg, isgroup=False)

            if context is None:
                logger.warning(f"[WebChannel] Context is None for session {session_id}, message may be filtered")
                if request_id in self.sse_queues:
                    del self.sse_queues[request_id]
                return json.dumps({"status": "error", "message": "Message was filtered"})

            context["session_id"] = session_id
            context["receiver"] = session_id
            context["request_id"] = request_id
            if book_id:
                context["book_id"] = book_id
                try:
                    bridge = _get_textbook_bridge()
                    book = bridge.get_textbook(book_id)
                    if book:
                        outline = bridge.get_outline(book_id)
                        from common.app_paths import active_workspace
                        workspace_root = active_workspace()
                        book_dir = bridge.get_book_dir(book_id)
                        chapter_dir = os.path.join(book_dir, "chapters")
                        image_dir = os.path.join(book_dir, "assets", "images")
                        chart_dir = os.path.join(book_dir, "assets", "charts")
                        prompt = (
                            f"[Current textbook id: {book_id}]\n"
                            f"[Current textbook: {book.title} / {book.subject} / {book.level}]\n"
                            f"[Textbook workspace root: {workspace_root}]\n"
                            f"[Current textbook directory: {book_dir}]\n"
                            f"[Canonical chapter directory: {chapter_dir}]\n"
                            f"[Canonical image directory: {image_dir}]\n"
                            f"[Canonical chart directory: {chart_dir}]\n"
                            f"[Path rule: When writing this textbook, write chapter files ONLY under the canonical chapter directory. Do not create chapters/ directly under the workspace root. Use chapter_001.md style filenames unless an existing chapter file uses another compatible name.]\n"
                            f"[Tool rule: Use textbook_chapter for chapter read/write/append/replace/encoding validation. Do not use bash/PowerShell Add-Content/Set-Content/Out-File for Chinese chapter Markdown.]\n"
                            f"[State rule: If the current textbook already has outline/review or chapter progress, continue from the next unfinished section. Do not restart outline generation, outline review, or earlier completed stages unless the user explicitly asks.]\n"
                            f"[Visual rule: If the chapter text promises a figure, illustration, diagram, chart, or table visualization, create the corresponding asset with the image model or sandbox/chart tool and reference it from the chapter Markdown.]\n"
                            f"[Outline]\n{outline[:4000] if outline else 'No outline yet'}\n\n"
                            f"{prompt}"
                        )
                        context.content = prompt
                        context["content"] = prompt
                except Exception as ctx_err:
                    logger.warning(f"[WebChannel] Failed to attach textbook context: {ctx_err}")

            if use_sse:
                context["on_event"] = self._make_sse_callback(request_id)

            threading.Thread(target=self.produce, args=(context,)).start()

            return json.dumps({"status": "success", "request_id": request_id, "stream": use_sse})

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def stream_response(self, request_id: str):
        """
        SSE generator for a given request_id.
        Yields UTF-8 encoded bytes to avoid WSGI Latin-1 mangling.
        Supports client reconnection: the queue is only removed after a
        "done" event is consumed, so a new GET /stream with the same
        request_id can resume reading remaining events.
        """
        if request_id not in self.sse_queues:
            yield b"data: {\"type\": \"error\", \"message\": \"invalid request_id\"}\n\n"
            return

        q = self.sse_queues[request_id]
        idle_timeout = 600
        deadline = time.time() + idle_timeout
        done = False

        try:
            from bridge.textbook_bridge import get_bridge
            bridge = get_bridge()
            bridge.register_sse_queue(q)
        except Exception:
            pass

        try:
            while time.time() < deadline:
                try:
                    item = q.get(timeout=1)
                except Empty:
                    yield b": keepalive\n\n"
                    continue

                deadline = time.time() + idle_timeout

                payload = json.dumps(item, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")

                if item.get("type") == "done":
                    done = True
                    break
        finally:
            try:
                from bridge.textbook_bridge import get_bridge
                bridge = get_bridge()
                bridge.unregister_sse_queue(q)
            except Exception:
                pass
            if done:
                self.sse_queues.pop(request_id, None)

    def poll_response(self):
        """
        Poll for responses using the session_id.
        """
        try:
            data = web.data()
            json_data = json.loads(data)
            session_id = json_data.get('session_id')

            if not session_id or session_id not in self.session_queues:
                return json.dumps({"status": "error", "message": "Invalid session ID"})

            # 尝试从队列获取响应，不等待
            try:
                # 使用peek而不是get，这样如果前端没有成功处理，下次还能获取到
                response = self.session_queues[session_id].get(block=False)

                # 返回响应，包含请求ID以区分不同请求
                return json.dumps({
                    "status": "success",
                    "has_content": True,
                    "content": response["content"],
                    "request_id": response["request_id"],
                    "timestamp": response["timestamp"]
                })

            except Empty:
                # 没有新响应
                return json.dumps({"status": "success", "has_content": False})

        except Exception as e:
            logger.error(f"Error polling response: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def chat_page(self):
        """Serve the chat HTML page."""
        file_path = os.path.join(os.path.dirname(__file__), 'chat.html')  # 使用绝对路径
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    def startup(self):
        port = conf().get("web_port", 9899)
        host = conf().get("web_host", "127.0.0.1") or "127.0.0.1"
        public_hosts = {"0.0.0.0", "::", ""}
        if (
            host in public_hosts
            and not conf().get("web_password")
            and conf().get("web_require_password_on_public_host", True)
        ):
            raise RuntimeError(
                "Refusing to start an unauthenticated public web console. "
                "Set web_password, bind web_host to 127.0.0.1, or explicitly set "
                "web_require_password_on_public_host=false."
            )
        if host in public_hosts and not conf().get("web_password"):
            logger.warning("[WebChannel] Public web console is running without a password by explicit config.")

        # Print available channel hints.
        logger.info(
            "[WebChannel] Available channels: edit channel_type in config.json; "
            "separate multiple channels with commas."
        )
        logger.info("[WebChannel]   1. weixin           - WeChat")
        logger.info("[WebChannel]   2. web              - Web console")
        logger.info("[WebChannel]   3. terminal         - Terminal")
        logger.info("[WebChannel]   4. feishu           - Feishu")
        logger.info("[WebChannel]   5. dingtalk         - DingTalk")
        logger.info("[WebChannel]   6. wecom_bot        - WeCom bot")
        logger.info("[WebChannel]   7. wechatcom_app    - WeCom app")
        logger.info("[WebChannel]   8. wechatmp         - WeChat public account")
        logger.info("[WebChannel]   9. wechatmp_service - WeChat service account")
        logger.info("[WebChannel] Web console is running")
        logger.info(f"[WebChannel] Local access: http://localhost:{port}")
        if host == "0.0.0.0":
            logger.info(f"[WebChannel] Server access: http://YOUR_IP:{port} (replace YOUR_IP with the server IP)")

        try:
            import webbrowser
            webbrowser.open(f"http://localhost:{port}")
            logger.debug(f"[WebChannel] Opened browser at http://localhost:{port}")
        except Exception as e:
            logger.debug(f"[WebChannel] Could not open browser: {e}")

        # Ensure the static asset directory exists.
        static_dir = os.path.join(os.path.dirname(__file__), 'static')
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
            logger.debug(f"[WebChannel] Created static directory: {static_dir}")

        urls = get_urls()
        app = web.application(urls, globals(), autoreload=False)

        # Disable web.py request logging.
        web.httpserver.LogMiddleware.log = lambda self, status, environ: None

        # Keep web.py internals quiet unless there is an error.
        logging.getLogger("web").setLevel(logging.ERROR)
        logging.getLogger("web.httpserver").setLevel(logging.ERROR)

        # Build WSGI app with middleware (same as runsimple but without print)
        func = web.httpserver.StaticMiddleware(app.wsgifunc())
        func = web.httpserver.LogMiddleware(func)
        server = web.httpserver.WSGIServer((host, port), func)
        server.daemon_threads = True
        # Default request_queue_size(5) / timeout(10s) / numthreads(10) are
        # too small: when SSE streams occupy many threads, the backlog fills
        # and new connections get refused (ERR_CONNECTION_ABORTED).
        server.request_queue_size = 128
        server.timeout = 300
        server.requests.min = 20
        server.requests.max = 80
        self._http_server = server
        try:
            server.start()
        except (KeyboardInterrupt, SystemExit):
            server.stop()
        except OSError as e:
            if e.errno in (48, 98):  # macOS/Linux EADDRINUSE
                logger.error(
                    f"[WebChannel] 端口 {port} 已被占用，可执行 `cow restart` 清理残留进程，"
                    f"或在 config.json 中修改 web_port"
                )
            raise

    def stop(self):
        if self._http_server:
            try:
                self._http_server.stop()
                logger.info("[WebChannel] HTTP server stopped")
            except Exception as e:
                logger.warning(f"[WebChannel] Error stopping HTTP server: {e}")
            self._http_server = None
