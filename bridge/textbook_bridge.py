import os
import sys
import json
import uuid
import time
import re
import threading
import asyncio
import inspect
from queue import Queue
from typing import Optional, List

from agent.textbook.models.textbook import TextbookConfig
from agent.textbook.state.manager import TextbookMemoryManager
from agent.textbook.state.truth_files import TruthFileManager
from agent.textbook.pipeline.runner import PipelineRunner

from common.log import logger
from common.run_events import RunStateRecorder, normalize_event
from common.stream_guard import iter_with_idle_guard

_bridge_instance = None
_bridge_lock = threading.Lock()


def get_bridge():
    global _bridge_instance
    with _bridge_lock:
        if _bridge_instance is None:
            from common.app_paths import textbooks_dir
            _bridge_instance = TextbookBridge(data_dir=textbooks_dir())
        return _bridge_instance


class _LightweightLLM:
    def __init__(self, role: str = "writer"):
        from config import conf
        from models.model_registry import ModelRegistry

        c = conf()
        role = role or "writer"
        profile = ModelRegistry(c).resolve(role)
        self._model = profile.model or c.get("model", "gpt-3.5-turbo")
        self._bot_type = profile.runtime_bot_type
        self._role = role
        self._api_key = profile.api_key
        self._api_base = (profile.api_base or "https://api.openai.com/v1").rstrip("/")
        self._proxy = c.get("proxy")
        try:
            self._request_timeout = int(c.get("request_timeout", 180) or 180)
        except (TypeError, ValueError):
            self._request_timeout = 180

        if not self._api_key:
            logger.warning(
                f"[TextbookBridge] API key is empty for role={role}, "
                f"provider={profile.provider}, model={self._model}; LLM calls will fail"
            )

    def call(self, messages, cancel_event=None, **kwargs):
        logger.info(f"[TextbookBridge] _LightweightLLM.call() invoked, role={self._role}, model={self._model}, api_base={self._api_base}, has_key={bool(self._api_key)}, messages_count={len(messages)}")
        if not self._api_key:
            logger.error(f"[TextbookBridge] API key is empty, cannot call LLM")
            return "[ERROR] API key not configured. Please check config.json and set the correct API key for your bot_type."
        try:
            import requests as req_lib
            url = f"{self._api_base}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "Connection": "close",
            }
            payload = {
                "model": self._model,
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.7),
                "stream": False,
            }
            proxies = None
            if self._proxy:
                proxies = {"http": self._proxy, "https": self._proxy}
            logger.info(f"[TextbookBridge] Sending request to {url}, model={self._model}")

            if self._role == "knowledge" and kwargs.get("stream", True) is not False:
                return self._call_streaming_chat_completions(
                    req_lib=req_lib,
                    url=url,
                    headers=headers,
                    payload=payload,
                    proxies=proxies,
                )

            if cancel_event is not None:
                result_box = [None]
                error_box = [None]
                start_time = time.time()

                def _do_post():
                    try:
                        resp = req_lib.post(
                            url,
                            json=payload,
                            headers=headers,
                            timeout=(30, self._request_timeout),
                            proxies=proxies,
                        )
                        resp.raise_for_status()
                        result_box[0] = resp
                    except Exception as exc:
                        error_box[0] = exc

                t = threading.Thread(target=_do_post, daemon=True)
                t.start()

                wait_log_interval = 10
                wait_log_next = time.time() + wait_log_interval
                while t.is_alive():
                    if cancel_event.is_set():
                        logger.info(f"[TextbookBridge] LLM call cancelled by cancel_event")
                        sys.stdout.flush()
                        sys.stderr.flush()
                        return "[CANCELLED] LLM call was cancelled by user"
                    t.join(timeout=0.5)
                    now = time.time()
                    if now >= wait_log_next:
                        elapsed = int(now - start_time)
                        logger.info(f"[TextbookBridge] LLM call still waiting... ({elapsed}s elapsed)")
                        sys.stdout.flush()
                        sys.stderr.flush()
                        wait_log_next = now + wait_log_interval

                if cancel_event.is_set():
                    return "[CANCELLED] LLM call was cancelled by user"

                if error_box[0] is not None:
                    raise error_box[0]

                resp = result_box[0]
            else:
                resp = req_lib.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=(30, self._request_timeout),
                    proxies=proxies,
                )
                resp.raise_for_status()

            data = resp.json()
            logger.info(f"[TextbookBridge] LLM response received, status={resp.status_code}, has_choices={bool(data.get('choices'))}")
            if "error" in data:
                err_msg = data["error"] if isinstance(data["error"], str) else data["error"].get("message", str(data["error"]))
                logger.error(f"[TextbookBridge] LLM API error: {err_msg}")
                return f"[ERROR] LLM API error: {err_msg}"
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                if content:
                    return content
                reasoning = choices[0].get("message", {}).get("reasoning_content", "")
                if reasoning:
                    return reasoning
            logger.error(f"[TextbookBridge] Unexpected LLM response: {str(data)[:500]}")
            return "[ERROR] Empty response from LLM API"
        except req_lib.exceptions.Timeout:
            return f"[ERROR] LLM API request timed out ({self._request_timeout}s). The model may be overloaded."
        except req_lib.exceptions.ConnectionError as e:
            return f"[ERROR] Cannot connect to LLM API at {self._api_base}: {e}"
        except req_lib.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "unknown"
            body = ""
            try:
                body = e.response.text[:500] if e.response else ""
            except Exception:
                pass
            return f"[ERROR] LLM API HTTP {status}: {body}"
        except Exception as e:
            logger.error(f"[TextbookBridge] LLM call failed: {e}", exc_info=True)
            return f"[ERROR] LLM call failed: {e}"

    def _call_streaming_chat_completions(self, req_lib, url: str, headers: dict, payload: dict, proxies=None) -> str:
        payload = dict(payload)
        payload["stream"] = True
        try:
            from config import conf
            idle_timeout = float(conf().get("knowledge_stream_idle_timeout", conf().get("agent_stream_idle_timeout", 30)) or 30)
            first_chunk_timeout = float(
                conf().get("knowledge_stream_first_chunk_timeout", conf().get("request_timeout", self._request_timeout)) or self._request_timeout
            )
        except Exception:
            idle_timeout = 30
            first_chunk_timeout = self._request_timeout

        response = req_lib.post(
            url,
            json=payload,
            headers=headers,
            timeout=(30, max(int(first_chunk_timeout), self._request_timeout)),
            proxies=proxies,
            stream=True,
        )
        if response.status_code != 200:
            return f"[ERROR] LLM API HTTP {response.status_code}: {response.text[:500]}"

        content_parts = []
        reasoning_parts = []
        last_error = ""

        def _sse_lines():
            try:
                for raw_line in response.iter_lines():
                    if raw_line:
                        yield raw_line
            finally:
                try:
                    response.close()
                except Exception:
                    pass

        try:
            for raw_line in iter_with_idle_guard(
                _sse_lines(),
                idle_timeout=idle_timeout,
                first_chunk_timeout=first_chunk_timeout,
                logger=logger,
                label=f"Knowledge LLM stream ({self._model})",
            ):
                line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
                if line.startswith("data: "):
                    data_str = line[6:]
                elif line.startswith("data:"):
                    data_str = line[5:]
                else:
                    continue
                data_str = data_str.strip()
                if not data_str:
                    continue
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    err = chunk.get("error")
                    last_error = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    break
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                    if delta.get("reasoning_content"):
                        reasoning_parts.append(delta["reasoning_content"])
                    message = choice.get("message") or {}
                    if message.get("content"):
                        content_parts.append(message["content"])
                    if message.get("reasoning_content"):
                        reasoning_parts.append(message["reasoning_content"])
        except TimeoutError as exc:
            if not content_parts and not reasoning_parts:
                return f"[ERROR] {exc}"
            logger.warning(f"[TextbookBridge] Knowledge stream timed out after partial output: {exc}")

        content = "".join(content_parts).strip()
        if content:
            logger.info(f"[TextbookBridge] Knowledge stream response received, chars={len(content)}")
            return content
        reasoning = "".join(reasoning_parts).strip()
        if reasoning:
            return reasoning
        if last_error:
            return f"[ERROR] LLM API error: {last_error}"
        return "[ERROR] Empty response from LLM stream"


class TextbookBridge:

    def __init__(self, data_dir=None):
        workspace_root = None
        if data_dir is None:
            from common.app_paths import active_workspace, textbooks_dir
            workspace_root = active_workspace()
            data_dir = textbooks_dir()
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.textbooks = {}
        self.active_pipelines = {}
        self._memory_manager = TextbookMemoryManager(self.data_dir, workspace_root=workspace_root)
        self._sse_broadcast_queues = []
        self._sse_lock = threading.Lock()

    @staticmethod
    def _flush_stdio():
        for stream in (sys.stdout, sys.stderr):
            try:
                if stream:
                    stream.flush()
            except Exception:
                pass

    def _determine_resume_point(self, book_id, config):
        book_dir = self._book_dir(book_id)
        if not os.path.exists(book_dir):
            return "outline"
        mgr = self._memory_manager.get_truth_manager(book_id)
        outline_text = mgr.read("outline")
        has_outline = bool(outline_text.strip()) and len(outline_text.strip()) > 10
        existing_chapters = []
        for num in mgr.list_completed_chapter_numbers(min_chars=50):
            existing_chapters.append(num)
        existing_chapters.sort()
        total = config.total_chapters or 1
        if not has_outline:
            return "outline"
        if len(existing_chapters) >= total:
            return "persist"
        # Once chapter writing has started, the outline is treated as locked for
        # this pipeline run. Going back to outline review mid-book is more
        # disruptive than continuing from the last completed chapter.
        if existing_chapters:
            return "compose"
        if not mgr.is_outline_review_current(outline_text):
            if not mgr.infer_outline_review_from_reports():
                return "review_outline"
        return "compose"

    def _book_dir(self, book_id):
        return os.path.join(self.data_dir, book_id)

    def get_book_dir(self, book_id):
        return self._book_dir(book_id)

    def _config_path(self, book_id):
        return os.path.join(self._book_dir(book_id), "textbook.json")

    def _load_config(self, book_id):
        path = self._config_path(book_id)
        if os.path.exists(path):
            return TextbookConfig.load(path)
        return None

    def _save_config(self, config):
        book_dir = self._book_dir(config.id)
        os.makedirs(book_dir, exist_ok=True)
        config.save(self._config_path(config.id))

    def create_textbook(self, config):
        if not config.id:
            config.id = f"tb_{uuid.uuid4().hex[:8]}"
        if config.id in self.textbooks or os.path.exists(self._book_dir(config.id)):
            config.id = config.id + "_" + uuid.uuid4().hex[:4]
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not config.created_at:
            config.created_at = now
        if not config.updated_at:
            config.updated_at = now
        self._save_config(config)
        self.textbooks[config.id] = config
        return config

    def get_textbook(self, book_id):
        if book_id in self.textbooks:
            return self.textbooks[book_id]
        config = self._load_config(book_id)
        if config:
            self.textbooks[book_id] = config
        return config

    def update_textbook(self, book_id, updates):
        config = self.get_textbook(book_id)
        if config is None:
            return None
        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)
        config.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._save_config(config)
        self.textbooks[book_id] = config
        return config

    def delete_textbook(self, book_id):
        book_dir = self._book_dir(book_id)
        if not os.path.exists(book_dir):
            return False
        import shutil
        shutil.rmtree(book_dir)
        self.textbooks.pop(book_id, None)
        self.active_pipelines.pop(book_id, None)
        return True

    def list_textbooks(self):
        textbooks = []
        if not os.path.exists(self.data_dir):
            return textbooks
        for name in os.listdir(self.data_dir):
            config_path = os.path.join(self.data_dir, name, "textbook.json")
            if os.path.exists(config_path):
                config = TextbookConfig.load(config_path)
                textbooks.append(config)
                self.textbooks[config.id] = config
        return textbooks

    def get_outline(self, book_id):
        mgr = self._memory_manager.get_truth_manager(book_id)
        return mgr.read("outline")

    def update_outline(self, book_id, outline_content):
        mgr = self._memory_manager.get_truth_manager(book_id)
        mgr.write("outline", outline_content)
        mgr.invalidate_outline_review("outline_updated_via_bridge")
        return True

    def get_chapter(self, book_id, chapter_num):
        mgr = self._memory_manager.get_truth_manager(book_id)
        return mgr.read_chapter(chapter_num)

    def update_chapter(self, book_id, chapter_num, content):
        mgr = self._memory_manager.get_truth_manager(book_id)
        mgr.write_chapter(chapter_num, content)
        return True

    def list_chapters(self, book_id):
        mgr = self._memory_manager.get_truth_manager(book_id)
        return mgr.list_chapters()

    @staticmethod
    def _chapter_number_from_filename(filename):
        match = re.match(r"^chapter_0*(\d+)\.md$", str(filename), re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _safe_export_filename(name):
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name or "textbook")).strip()
        return cleaned.strip(" .") or "textbook"

    def _existing_chapter_numbers(self, mgr):
        chapter_numbers = []
        for filename in mgr.list_chapters():
            num = self._chapter_number_from_filename(filename)
            if num is not None:
                chapter_numbers.append(num)
        return sorted(set(chapter_numbers))

    def start_pipeline(self, book_id, sse_queue=None, requirement: str = ""):
        logger.info(f"[TextbookBridge] start_pipeline called for book_id={book_id}")
        config = self.get_textbook(book_id)
        if config is None:
            logger.warning(f"[TextbookBridge] Textbook {book_id} not found")
            return {"error": f"Textbook {book_id} not found"}
        logger.info(f"[TextbookBridge] Config loaded: title={config.title}, chapters={config.total_chapters}")

        if book_id in self.active_pipelines:
            info = self.active_pipelines[book_id]
            if info.get("status") in ("running", "paused") and info.get("thread") and info["thread"].is_alive():
                return {"error": f"Pipeline already running for {book_id}"}
            else:
                del self.active_pipelines[book_id]

        resume_from = self._determine_resume_point(book_id, config)
        logger.info(f"[TextbookBridge] Resume point for {book_id}: {resume_from}")
        book_dir = self._book_dir(book_id)

        if requirement:
            try:
                mgr = self._memory_manager.get_truth_manager(book_id)
                mgr.write("research_evidence", requirement)
            except Exception as e:
                logger.warning(f"[TextbookBridge] Failed to save research evidence for {book_id}: {e}")

        pipeline_info = {
            "book_id": book_id,
            "status": "running",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "current_phase": "",
            "phases_completed": [],
            "progress": 0.0,
            "phase_details": {},
            "phase_steps": {},
            "chapter_actions": {},
            "error": None,
            "runner": None,
            "thread": None,
            "resume_from": resume_from,
            "events": [],
        }
        event_recorder = RunStateRecorder(
            os.path.join(book_dir, "state", "runs", pipeline_info.get("started_at", "").replace(":", "-")),
            run_id="",
            source="textbook_pipeline",
        )

        def on_event(event):
            normalized = normalize_event(event, run_id=event.get("pipeline_id", ""), source="textbook_pipeline")
            if not event_recorder.run_id and normalized.get("run_id"):
                event_recorder.run_id = normalized["run_id"]
            normalized = event_recorder.record(event)
            pipeline_info.setdefault("events", []).append(normalized)
            if len(pipeline_info["events"]) > 100:
                del pipeline_info["events"][:-100]
            if sse_queue is not None:
                sse_queue.put(event)
                sse_queue.put({"type": "run_event", "data": normalized})
            with self._sse_lock:
                for q in self._sse_broadcast_queues:
                    try:
                        q.put(event)
                        q.put({"type": "run_event", "data": normalized})
                    except Exception:
                        pass
            event_type = event.get("type", "")
            if event_type == "pipeline_complete":
                pipeline_info["status"] = "completed"
                pipeline_info["progress"] = 1.0
                threading.Timer(5.0, lambda: self.active_pipelines.pop(book_id, None)).start()
            elif event_type == "pipeline_error":
                pipeline_info["status"] = "error"
                err_data = event.get("data", {})
                pipeline_info["error"] = err_data.get("error", "Unknown error")
                threading.Timer(5.0, lambda: self.active_pipelines.pop(book_id, None)).start()
            elif event_type == "phase_start":
                phase = event.get("data", {}).get("phase", "")
                pipeline_info["current_phase"] = phase
                if phase:
                    pipeline_info["phase_steps"][phase] = {
                        "status": "running",
                        "started_at": time.strftime("%H:%M:%S"),
                        "steps": [],
                    }
            elif event_type == "phase_complete":
                phase = event.get("data", {}).get("phase", "")
                if phase and phase not in pipeline_info["phases_completed"]:
                    pipeline_info["phases_completed"].append(phase)
                score = event.get("data", {}).get("score")
                summary = event.get("data", {}).get("result_summary", "")
                if phase:
                    if phase not in pipeline_info["phase_steps"]:
                        pipeline_info["phase_steps"][phase] = {"status": "completed", "steps": []}
                    pipeline_info["phase_steps"][phase]["status"] = "completed"
                    pipeline_info["phase_steps"][phase]["completed_at"] = time.strftime("%H:%M:%S")
                    detail = {}
                    if score:
                        detail["score"] = score
                        pipeline_info["phase_details"][phase] = {"score": score}
                    if summary:
                        detail["summary"] = summary
                        if phase in pipeline_info["phase_details"]:
                            pipeline_info["phase_details"][phase]["summary"] = summary
                        else:
                            pipeline_info["phase_details"][phase] = {"summary": summary}
                completed_count = len(pipeline_info["phases_completed"])
                pipeline_info["progress"] = min(completed_count / 7.0, 1.0)
            elif event_type == "phase_progress":
                data = event.get("data", {})
                phase = data.get("phase", "")
                current_item = data.get("current_item", 0)
                total_items = max(data.get("total_items", 1), 1)
                item_label = data.get("item_label", "")
                pipeline_info["phase_details"][phase] = {
                    "current_chapter": str(current_item),
                    "current_title": item_label,
                    "total_items": total_items,
                }
                if phase not in pipeline_info["phase_steps"]:
                    pipeline_info["phase_steps"][phase] = {"status": "running", "steps": []}
                pipeline_info["phase_steps"][phase]["current_item"] = item_label
                pipeline_info["phase_steps"][phase]["current_item_num"] = current_item
                pipeline_info["phase_steps"][phase]["total_items"] = total_items
                completed_count = len(pipeline_info["phases_completed"])
                phase_frac = current_item / total_items
                pipeline_info["progress"] = min((completed_count + phase_frac) / 7.0, 1.0)
            elif event_type == "chapter_actions_planned":
                data = event.get("data", {})
                ch = str(data.get("chapter_number", ""))
                if ch:
                    pipeline_info["chapter_actions"][ch] = data.get("actions", [])
            elif event_type == "agent_event":
                agent_name = event.get("agent_name", "")
                agent_data = event.get("data", {})
                cur_phase = pipeline_info.get("current_phase", "")
                if cur_phase and cur_phase in pipeline_info["phase_steps"]:
                    step_desc = agent_data.get("description", "") or agent_data.get("action", "")
                    if not step_desc and agent_name:
                        step_desc = f"{agent_name} 处理中"
                    if step_desc:
                        steps = pipeline_info["phase_steps"][cur_phase]["steps"]
                        if not steps or steps[-1].get("desc") != step_desc:
                            steps.append({"desc": step_desc, "time": time.strftime("%H:%M:%S"), "agent": agent_name})
                            if len(steps) > 20:
                                pipeline_info["phase_steps"][cur_phase]["steps"] = steps[-20:]
            self._flush_stdio()

        llm_model = _LightweightLLM(role="writer")
        review_llm_model = _LightweightLLM(role="review")
        logger.info(f"[TextbookBridge] LLM initialized: bot_type={llm_model._bot_type}, model={llm_model._model}, api_base={llm_model._api_base}, has_key={bool(llm_model._api_key)}")
        logger.info(f"[TextbookBridge] Review LLM initialized: bot_type={review_llm_model._bot_type}, model={review_llm_model._model}, api_base={review_llm_model._api_base}, has_key={bool(review_llm_model._api_key)}")
        runner_kwargs = {"llm_model": llm_model, "memory_manager": self._memory_manager, "on_event": on_event}
        try:
            if "review_llm_model" in inspect.signature(PipelineRunner).parameters:
                runner_kwargs["review_llm_model"] = review_llm_model
        except (TypeError, ValueError):
            runner_kwargs["review_llm_model"] = review_llm_model
        runner = PipelineRunner(**runner_kwargs)
        logger.info(f"[TextbookBridge] PipelineRunner created successfully")
        pipeline_info["runner"] = runner

        def run():
            logger.info(f"[TextbookBridge] Pipeline thread started for {book_id}")
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                logger.info(f"[TextbookBridge] Event loop created, starting run_full_pipeline for {book_id}")
                maybe_coro = runner.run_full_pipeline(config, requirement=requirement, resume_from=resume_from)
                if asyncio.iscoroutine(maybe_coro) or hasattr(maybe_coro, "__await__"):
                    result = loop.run_until_complete(maybe_coro)
                else:
                    result = maybe_coro
                loop.close()
                logger.info(f"[TextbookBridge] Pipeline completed for {book_id}, result keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
            except Exception as e:
                pipeline_info["status"] = "error"
                pipeline_info["error"] = str(e)
                logger.error(f"[TextbookBridge] Pipeline error for {book_id}: {e}", exc_info=True)
                if sse_queue is not None:
                    sse_queue.put({"type": "pipeline_error", "data": {"error": str(e)}})
            finally:
                if sse_queue is not None:
                    sse_queue.put({"type": "done"})
                logger.info(f"[TextbookBridge] Pipeline thread exiting for {book_id}, final status: {pipeline_info['status']}")

        thread = threading.Thread(target=run, daemon=True)
        pipeline_info["thread"] = thread
        self.active_pipelines[book_id] = pipeline_info
        thread.start()
        return {
            "book_id": pipeline_info["book_id"],
            "status": pipeline_info["status"],
            "started_at": pipeline_info["started_at"],
            "current_phase": pipeline_info["current_phase"],
            "phases_completed": pipeline_info["phases_completed"],
            "progress": pipeline_info["progress"],
            "phase_details": pipeline_info["phase_details"],
            "chapter_actions": pipeline_info.get("chapter_actions", {}),
            "error": pipeline_info["error"],
            "resume_from": resume_from,
        }

    def get_pipeline_status(self, book_id):
        info = self.active_pipelines.get(book_id)
        if info is None:
            return {"book_id": book_id, "status": "none"}
        result = {
            "book_id": info["book_id"],
            "status": info["status"],
            "started_at": info.get("started_at", ""),
            "current_phase": info.get("current_phase", ""),
            "phases_completed": info.get("phases_completed", []),
            "progress": info.get("progress", 0.0),
            "phase_details": info.get("phase_details", {}),
            "phase_steps": info.get("phase_steps", {}),
            "chapter_actions": info.get("chapter_actions", {}),
        }
        if info.get("error"):
            result["error"] = info["error"]
        return result

    def register_sse_queue(self, q):
        with self._sse_lock:
            if q not in self._sse_broadcast_queues:
                self._sse_broadcast_queues.append(q)

    def unregister_sse_queue(self, q):
        with self._sse_lock:
            if q in self._sse_broadcast_queues:
                self._sse_broadcast_queues.remove(q)

    def pause_pipeline(self, book_id):
        info = self.active_pipelines.get(book_id)
        if info is None or info.get("runner") is None:
            return False
        info["runner"].pause()
        info["status"] = "paused"
        return True

    def resume_pipeline(self, book_id):
        info = self.active_pipelines.get(book_id)
        if info is None or info.get("runner") is None:
            return False
        info["runner"].resume()
        info["status"] = "running"
        return True

    def cancel_pipeline(self, book_id):
        info = self.active_pipelines.get(book_id)
        if info is None or info.get("runner") is None:
            return False
        info["runner"].cancel()
        info["status"] = "cancelled"
        threading.Timer(3.0, lambda: self.active_pipelines.pop(book_id, None)).start()
        return True

    def export_word(self, book_id, template_name="academic", chapter_numbers=None):
        from agent.textbook.docgen.word_generator import MarkdownToWordConverter
        from agent.textbook.docgen.style_template import get_template
        from agent.textbook.docgen.image_handler import ImageHandler

        config = self.get_textbook(book_id)
        if config is None:
            return ""

        mgr = self._memory_manager.get_truth_manager(book_id)
        template = get_template(template_name)
        converter = MarkdownToWordConverter(template=template)
        requested_specific_chapters = chapter_numbers is not None
        existing_chapters = self._existing_chapter_numbers(mgr)

        if requested_specific_chapters:
            normalized = []
            for raw in chapter_numbers or []:
                try:
                    num = int(raw)
                except (TypeError, ValueError):
                    continue
                if num > 0 and num not in normalized:
                    normalized.append(num)
            missing = [num for num in normalized if num not in existing_chapters]
            if missing:
                raise ValueError(f"Requested chapter not found: {', '.join(str(n) for n in missing)}")
            chapter_numbers = normalized
        else:
            chapter_numbers = existing_chapters

        if not requested_specific_chapters:
            converter.add_title(config.title)
            outline_text = mgr.read("outline")
            if outline_text:
                converter.add_heading("目录", 1)
                converter.convert_markdown(outline_text)
        else:
            if len(chapter_numbers) == 1:
                converter.add_title(f"{config.title} - 第{chapter_numbers[0]}章")
            else:
                converter.add_title(config.title)

        chapter_snapshots = {num: mgr.read_chapter(num) for num in chapter_numbers}

        img_output_dir = os.path.join(self._book_dir(book_id), "output", "images")
        os.makedirs(img_output_dir, exist_ok=True)

        converted_count = 0
        for ch_num in chapter_numbers:
            content = chapter_snapshots.get(ch_num) or ""
            if content:
                for match in re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', content):
                    img_path = match.group(2)
                    resolved_img_path = img_path
                    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', img_path) and not os.path.isabs(img_path):
                        resolved_img_path = os.path.join(self._book_dir(book_id), img_path.replace("/", os.sep))
                    if os.path.exists(resolved_img_path):
                        resized_path = os.path.join(img_output_dir, os.path.basename(resolved_img_path))
                        ImageHandler.resize_image(resolved_img_path, resized_path)
                        content = content.replace(img_path, resized_path)
                converter.convert_markdown(content)
                converted_count += 1

        if not converted_count and requested_specific_chapters:
            raise ValueError("Selected chapter has no content to export.")
        if not converted_count and not mgr.read("outline"):
            raise ValueError("No outline or chapter content to export.")

        output_dir = os.path.join(self._book_dir(book_id), "output")
        os.makedirs(output_dir, exist_ok=True)
        safe_title = self._safe_export_filename(config.title)
        if requested_specific_chapters and len(chapter_numbers) == 1:
            filename = f"{safe_title}_第{chapter_numbers[0]}章"
        else:
            filename = safe_title
        output_path = os.path.join(output_dir, f"{filename}.docx")
        converter.save(output_path)
        for ch_num, before_content in chapter_snapshots.items():
            if mgr.read_chapter(ch_num) != before_content:
                raise RuntimeError(f"Export unexpectedly modified chapter_{ch_num:03d}.md")
        if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
            raise RuntimeError("Word export produced an empty file.")
        return output_path

    def execute_sandbox(self, code, timeout=30):
        from agent.textbook.sandbox.executor import SandboxExecutor

        executor = SandboxExecutor(timeout=timeout)
        result = executor.execute(code, timeout=timeout)
        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "output_files": result.output_files,
            "execution_time": result.execution_time,
        }

    def generate_chart(self, chart_type, data, filename=""):
        from agent.textbook.sandbox.executor import SandboxExecutor
        from agent.textbook.sandbox.chart_generator import ChartGenerator

        executor = SandboxExecutor()
        chart = ChartGenerator(executor=executor)

        if not filename:
            filename = f"{chart_type}_chart.png"

        chart_methods = {
            "line": chart.generate_line_chart,
            "bar": chart.generate_bar_chart,
            "pie": chart.generate_pie_chart,
            "scatter": chart.generate_scatter_chart,
            "network": chart.generate_network_graph,
        }

        method = chart_methods.get(chart_type)
        if method is None:
            return {"success": False, "error": f"Unsupported chart type: {chart_type}"}

        if chart_type == "line":
            result = method(
                x_data=data.get("x", "[]"),
                y_data=data.get("y", "[]"),
                title=data.get("title", ""),
                xlabel=data.get("xlabel", ""),
                ylabel=data.get("ylabel", ""),
                filename=filename,
            )
        elif chart_type == "bar":
            result = method(
                categories=data.get("categories", "[]"),
                values=data.get("values", "[]"),
                title=data.get("title", ""),
                xlabel=data.get("xlabel", ""),
                ylabel=data.get("ylabel", ""),
                filename=filename,
            )
        elif chart_type == "pie":
            result = method(
                labels=data.get("labels", "[]"),
                sizes=data.get("sizes", "[]"),
                title=data.get("title", ""),
                filename=filename,
            )
        elif chart_type == "scatter":
            result = method(
                x_data=data.get("x", "[]"),
                y_data=data.get("y", "[]"),
                title=data.get("title", ""),
                xlabel=data.get("xlabel", ""),
                ylabel=data.get("ylabel", ""),
                filename=filename,
            )
        elif chart_type == "network":
            result = method(
                nodes_code=data.get("nodes_code", "G.add_node('Node')"),
                edges_code=data.get("edges_code", ""),
                title=data.get("title", ""),
                filename=filename,
            )

        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "output_files": result.output_files,
        }

    def save_outline_version(self, book_id: str, content: str, message: str = "") -> dict:
        versions_dir = os.path.join(self._book_dir(book_id), "outline", "versions")
        os.makedirs(versions_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        version_id = f"v_{timestamp}"
        version_file = os.path.join(versions_dir, f"{version_id}.md")
        with open(version_file, "w", encoding="utf-8") as f:
            f.write(content)
        metadata_path = os.path.join(versions_dir, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        else:
            metadata = {"versions": []}
        version_info = {
            "version_id": version_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "message": message,
            "size": len(content.encode("utf-8")),
        }
        metadata["versions"].append(version_info)
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        self.update_outline(book_id, content)
        return {"version_id": version_id, "timestamp": version_info["timestamp"], "message": message}

    def list_outline_versions(self, book_id: str) -> list:
        versions_dir = os.path.join(self._book_dir(book_id), "outline", "versions")
        metadata_path = os.path.join(versions_dir, "metadata.json")
        if not os.path.exists(metadata_path):
            return []
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        return metadata.get("versions", [])

    def get_outline_version(self, book_id: str, version_id: str) -> str:
        versions_dir = os.path.join(self._book_dir(book_id), "outline", "versions")
        version_file = os.path.join(versions_dir, f"{version_id}.md")
        if not os.path.exists(version_file):
            return ""
        with open(version_file, "r", encoding="utf-8") as f:
            return f.read()

    def restore_outline_version(self, book_id: str, version_id: str) -> dict:
        content = self.get_outline_version(book_id, version_id)
        if not content:
            return {"version_id": version_id, "restored": False}
        self.update_outline(book_id, content)
        return {"version_id": version_id, "restored": True}

    def review_content(self, book_id: str, level: str, target: str = "") -> dict:
        from agent.textbook.models.review import ReviewResult
        config = self.get_textbook(book_id)
        if config is None:
            return ReviewResult().to_dict()
        mgr = self._memory_manager.get_truth_manager(book_id)
        review_content_text = ""
        scope_desc = ""
        if level == "outline":
            review_content_text = mgr.read("outline") or ""
            scope_desc = "大纲"
        elif level == "chapter":
            if target:
                try:
                    chapter_num = int(target)
                    review_content_text = mgr.read_chapter(chapter_num) or ""
                    scope_desc = f"第{chapter_num}章"
                except ValueError:
                    review_content_text = ""
                    scope_desc = f"章节{target}"
            else:
                review_content_text = ""
                scope_desc = "章节"
        elif level == "section":
            if target:
                parts = target.split(".")
                if len(parts) >= 2:
                    try:
                        chapter_num = int(parts[0])
                        chapter_content = mgr.read_chapter(chapter_num) or ""
                        review_content_text = chapter_content
                        scope_desc = f"第{target}节"
                    except ValueError:
                        review_content_text = ""
                        scope_desc = f"节{target}"
                else:
                    review_content_text = ""
                    scope_desc = f"节{target}"
            else:
                review_content_text = ""
                scope_desc = "节"
        elif level == "full":
            parts = []
            outline = mgr.read("outline") or ""
            if outline:
                parts.append(f"【大纲】\n{outline[:6000]}")
            chapters = mgr.list_chapters()
            for fname in chapters:
                try:
                    num = int(fname.replace("chapter_", "").replace(".md", ""))
                    ch_content = mgr.read_chapter(num) or ""
                    if ch_content:
                        parts.append(f"【第{num}章摘要】\n{self._chapter_review_digest(ch_content)}")
                except ValueError:
                    pass
            review_content_text = "\n\n".join(parts)
            scope_desc = "全部内容"
        else:
            return ReviewResult().to_dict()

        if not review_content_text.strip():
            return ReviewResult().to_dict()

        prompt = f"""你是教材审查智能体。请只审查以下教材{scope_desc}，不要重写内容。

## 审查维度（0-100分）
1. 内容完整性：是否覆盖主题和目标读者需要的核心内容
2. 逻辑结构：结构是否清晰、递进合理、无明显跳跃
3. 语言表达：是否准确、流畅、适合教材
4. 学术规范：术语、引用、格式是否规范
5. 实用性：案例、练习、方法是否有实际价值

## 边界
- 只根据给定内容判断，不要虚构事实、来源、章节或标准。
- 问题定位要具体，建议要可执行。
- 严格返回 JSON 对象，不要 Markdown 代码块或额外文字。

JSON 格式：
{{
  "passed": true或false（综合评分>=70为通过），
  "score": 综合评分（0-100的浮点数），
  "dimensions": [
    {{"name": "内容完整性", "score": 分数, "comment": "评语"}},
    {{"name": "逻辑结构", "score": 分数, "comment": "评语"}},
    {{"name": "语言表达", "score": 分数, "comment": "评语"}},
    {{"name": "学术规范", "score": 分数, "comment": "评语"}},
    {{"name": "实用性", "score": 分数, "comment": "评语"}}
  ],
  "issues": [
    {{"level": "critical或warning或info", "dimension": "维度名", "description": "问题描述", "suggestion": "修改建议", "location": "问题位置"}}
  ]
}}

待审查的{scope_desc}内容：

{review_content_text}"""

        llm = _LightweightLLM(role="review")
        messages = [{"role": "user", "content": prompt}]
        response = llm.call(messages, temperature=0.3)

        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result_data = json.loads(json_match.group())
                review_result = ReviewResult.from_dict(result_data)
                return review_result.to_dict()
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"[TextbookBridge] Failed to parse review result: {e}")

        return ReviewResult().to_dict()

    def update_preferences(self, book_id: str, preferences: dict) -> dict:
        pref_path = os.path.join(self._book_dir(book_id), "preferences.json")
        with open(pref_path, "w", encoding="utf-8") as f:
            json.dump(preferences, f, ensure_ascii=False, indent=2)
        config = self.get_textbook(book_id)
        if config is not None:
            pref_mapping = {
                "chapter_word_count": "chapter_word_count",
                "style": "style",
            }
            for pref_key, config_key in pref_mapping.items():
                if pref_key in preferences:
                    if hasattr(config, config_key):
                        setattr(config, config_key, preferences[pref_key])
            if "example_count" in preferences:
                config.chapter_word_count = config.chapter_word_count
            if "auto_optimize" in preferences:
                val = preferences["auto_optimize"]
                if isinstance(val, str):
                    preferences["auto_optimize"] = val == "启用"
            config.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._save_config(config)
            self.textbooks[book_id] = config
        return {"preferences": preferences}

    def _chapter_review_digest(self, content: str, max_chars: int = 1800) -> str:
        """Build a bounded chapter digest for full-book review prompts."""
        text = content or ""
        heading = ""
        for line in text.splitlines():
            if line.startswith("#"):
                heading = line.strip()
                break
        summary = ""
        match = re.search(r"(?ms)^##\s*本章小结\s*(.*?)(?=^##\s+|\Z)", text)
        if match:
            summary = match.group(1).strip()
        exercises = ""
        ex_match = re.search(r"(?ms)^##\s*本章习题\s*(.*?)(?=^##\s+|\Z)", text)
        if ex_match:
            exercises = ex_match.group(1).strip()
        body = re.sub(r"```[\s\S]*?```", "[代码示例略]", text)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        digest_parts = [part for part in [heading, "小结:\n" + summary if summary else "", "习题概览:\n" + exercises[:500] if exercises else "", "正文摘录:\n" + body[:900]] if part]
        digest = "\n\n".join(digest_parts)
        return digest[:max_chars].rstrip()

    def get_preferences(self, book_id: str) -> dict:
        pref_path = os.path.join(self._book_dir(book_id), "preferences.json")
        if os.path.exists(pref_path):
            with open(pref_path, "r", encoding="utf-8") as f:
                return json.load(f)
        default_preferences = {
            "chapter_word_count": 5000,
            "style": "学术",
            "example_count": 3,
            "model": "",
            "review_strictness": "normal",
            "auto_optimize": False,
        }
        return default_preferences

    def save_chat_message(self, session_id: str, role: str, content: str, tool_calls: list = None) -> dict:
        from common.app_paths import chat_history_dir
        chat_dir = chat_history_dir()
        os.makedirs(chat_dir, exist_ok=True)
        chat_file = os.path.join(chat_dir, f"{session_id}.json")
        message = {
            "role": role,
            "content": content,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "tool_calls": tool_calls or [],
        }
        if os.path.exists(chat_file):
            with open(chat_file, "r", encoding="utf-8") as f:
                messages = json.load(f)
        else:
            messages = []
        messages.append(message)
        with open(chat_file, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        try:
            from agent.memory import get_conversation_store

            store = get_conversation_store()
            if not store.has_recent_text_message(session_id, role, content, within_seconds=600):
                store.append_messages(
                    session_id,
                    [{"role": role, "content": content}],
                    channel_type="textbook",
                )
        except Exception:
            pass
        return {"saved": True, "session_id": session_id, "count": len(messages)}

    def load_chat_history(self, session_id: str) -> list:
        from common.app_paths import chat_history_dir
        chat_dir = chat_history_dir()
        chat_file = os.path.join(chat_dir, f"{session_id}.json")
        if not os.path.exists(chat_file):
            return []
        with open(chat_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_chat_sessions(self) -> list:
        from common.app_paths import chat_history_dir
        chat_dir = chat_history_dir()
        if not os.path.exists(chat_dir):
            return []
        sessions = []
        for fname in os.listdir(chat_dir):
            if not fname.endswith(".json"):
                continue
            session_id = fname[:-5]
            chat_file = os.path.join(chat_dir, fname)
            try:
                mtime = os.path.getmtime(chat_file)
                with open(chat_file, "r", encoding="utf-8") as f:
                    messages = json.load(f)
                sessions.append({
                    "session_id": session_id,
                    "message_count": len(messages),
                    "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)),
                })
            except Exception:
                continue
        sessions.sort(key=lambda x: x["last_updated"], reverse=True)
        return sessions

    def clear_chat_history(self, session_id: str) -> dict:
        from common.app_paths import chat_history_dir
        chat_dir = chat_history_dir()
        chat_file = os.path.join(chat_dir, f"{session_id}.json")
        if os.path.exists(chat_file):
            os.remove(chat_file)
        return {"cleared": True, "session_id": session_id}
