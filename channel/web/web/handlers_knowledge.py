import json
import os
import threading
import time
import uuid

import web

from common.log import logger
from common.upload_limits import UploadLimitError, get_upload_limits, validate_file_upload
from common.run_events import RunStateRecorder
from channel.web.web.utils import (
    get_upload_dir, get_workspace_root, json_error, json_response, json_success, read_json_body, require_auth,
)


class KnowledgeListHandler:
    def GET(self):
        require_auth()
        try:
            from agent.knowledge.service import KnowledgeService
            params = web.input(book_id='', offset='', limit='', query='', path_prefix='', mode='page')
            svc = KnowledgeService(get_workspace_root())
            if params.mode == 'tree':
                result = svc.list_tree(book_id=params.book_id)
            else:
                result = svc.list_files_page(
                    book_id=params.book_id,
                    offset=int(params.offset or 0),
                    limit=int(params.limit or 80),
                    query=params.query,
                    path_prefix=params.path_prefix,
                )
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Knowledge list error: {e}")
            return json_error(e)


class KnowledgeReadHandler:
    def GET(self):
        require_auth()
        try:
            from agent.knowledge.service import KnowledgeService
            params = web.input(path='', book_id='')
            svc = KnowledgeService(get_workspace_root())
            result = svc.read_file(params.path, book_id=params.book_id)
            return json_success(**result)
        except (ValueError, FileNotFoundError) as e:
            return json_error(e)
        except Exception as e:
            logger.error(f"[WebChannel] Knowledge read error: {e}")
            return json_error(e)


class KnowledgeGraphHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.knowledge.service import KnowledgeService
            params = web.input(book_id='', limit='140', focus_id='', depth='1', query='', min_confidence='0')
            svc = KnowledgeService(get_workspace_root())
            return json.dumps(svc.build_graph(
                book_id=params.book_id,
                limit=int(params.limit or 140),
                focus_id=params.focus_id,
                depth=int(params.depth or 1),
                query=params.query,
                min_confidence=float(params.min_confidence or 0),
            ), ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Knowledge graph error: {e}")
            return json.dumps({"nodes": [], "links": []})


class KnowledgeUploadHandler:
    def POST(self):
        require_auth()
        try:
            from agent.knowledge.service import KnowledgeService
            x = web.input(file={}, book_id='', category='sources')
            file_obj = x.get('file')
            category = x.get('category', 'sources') or 'sources'
            book_id = x.get('book_id', '') or ''
            if not getattr(file_obj, 'filename', None):
                return json_error("No file uploaded")
            content_bytes = file_obj.file.read()
            original_name = file_obj.filename
            validate_file_upload(original_name, len(content_bytes), get_upload_limits("knowledge_upload"))
            upload_dir = get_upload_dir()
            os.makedirs(upload_dir, exist_ok=True)
            tmp_path = os.path.join(upload_dir, f"knowledge_{uuid.uuid4().hex[:8]}_{original_name}")
            with open(tmp_path, "wb") as f:
                f.write(content_bytes)
            try:
                svc = KnowledgeService(get_workspace_root())
                result = svc.upload_document(tmp_path, category=category, book_id=book_id)
                return json_success(source=result)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        except UploadLimitError as e:
            logger.warning(f"[WebChannel] Knowledge upload rejected: {e}")
            return json_error(e)
        except Exception as e:
            logger.error(f"[WebChannel] Knowledge upload error: {e}", exc_info=True)
            return json_error(e)


class KnowledgeSourcesHandler:
    def GET(self):
        require_auth()
        try:
            from agent.knowledge.service import KnowledgeService
            params = web.input(book_id='')
            svc = KnowledgeService(get_workspace_root())
            result = svc.list_sources(book_id=params.book_id)
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Knowledge sources error: {e}")
            return json_error(e)


class KnowledgeStatusHandler:
    def GET(self):
        require_auth()
        try:
            from agent.knowledge.service import KnowledgeService
            params = web.input(book_id='')
            svc = KnowledgeService(get_workspace_root())
            result = svc.get_status(book_id=params.book_id)
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Knowledge status error: {e}")
            return json_error(e)


class KnowledgeSkillLinkHandler:
    def POST(self):
        require_auth()
        try:
            from agent.knowledge.service import KnowledgeService
            body = read_json_body()
            skill_name = body.get("skill_name", "")
            source_paths = body.get("source_paths", [])
            if not skill_name:
                return json_error("skill_name is required")
            if not source_paths:
                return json_error("source_paths is required")
            svc = KnowledgeService(get_workspace_root())
            result = svc.link_to_skill(skill_name, source_paths)
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Knowledge skill link error: {e}")
            return json_error(e)


_organize_status = {}


class KnowledgeOrganizeHandler:
    def POST(self):
        require_auth()
        try:
            body = read_json_body()
            book_id = body.get("book_id", "")
            force_value = body.get("force", body.get("force_rebuild", False))
            force = str(force_value).strip().lower() not in ("0", "false", "no", "off")
            status_key = book_id or "__global__"
            if _organize_status.get(status_key, {}).get("running"):
                return json_success(status="already_running", message="整理正在进行中，请稍候")
            logger.info(f"[WebChannel] Knowledge organize requested: book_id={status_key}, force={force}")
            started_at = time.time()
            run_id = f"knowledge_{status_key}_{int(started_at)}"
            run_recorder = RunStateRecorder(
                os.path.join(get_workspace_root(), ".runs", "knowledge", status_key, run_id),
                run_id=run_id,
                source="knowledge_organize",
            )
            _organize_status[status_key] = {
                "run_id": run_id,
                "running": True,
                "progress": "starting",
                "stage": "starting",
                "message": "准备整理知识库",
                "result": None,
                "error": None,
                "force": force,
                "started_at": started_at,
                "updated_at": started_at,
                "events": [],
            }

            def _on_progress(payload):
                info = _organize_status.setdefault(status_key, {})
                normalized_event = run_recorder.record({
                    "type": "knowledge_organize_progress",
                    "data": {
                        **payload,
                        "phase": payload.get("stage", "processing"),
                        "status": "running",
                    },
                    "timestamp": time.time(),
                })
                info.update({
                    "progress": payload.get("stage", info.get("progress", "processing")),
                    "stage": payload.get("stage", info.get("stage", "")),
                    "message": payload.get("message", info.get("message", "")),
                    "updated_at": time.time(),
                })
                for key, value in payload.items():
                    if key not in ("stage", "message"):
                        info[key] = value
                events = info.setdefault("events", [])
                events.append(normalized_event)
                if len(events) > 30:
                    del events[:-30]

            def _do_organize():
                try:
                    from agent.knowledge.service import KnowledgeService
                    svc = KnowledgeService(get_workspace_root(), on_progress=_on_progress)
                    _on_progress({"stage": "processing", "message": "知识库整理中", "force": force})
                    result = svc.organize_knowledge(book_id=book_id, force=force)
                    done_event = run_recorder.record({
                        "type": "knowledge_organize_complete",
                        "data": {
                            **result,
                            "phase": "done",
                            "status": "completed",
                            "message": result.get("message", "整理完成"),
                        },
                        "timestamp": time.time(),
                    })
                    _organize_status[status_key]["result"] = result
                    _organize_status[status_key]["progress"] = "done"
                    _organize_status[status_key]["stage"] = "done"
                    _organize_status[status_key]["message"] = result.get("message", "整理完成")
                    _organize_status[status_key].setdefault("events", []).append(done_event)
                except Exception as ex:
                    logger.error(f"[WebChannel] Knowledge organize background error: {ex}", exc_info=True)
                    error_event = run_recorder.record({
                        "type": "knowledge_organize_error",
                        "data": {
                            "phase": "error",
                            "status": "error",
                            "error": str(ex),
                            "message": str(ex),
                        },
                        "timestamp": time.time(),
                    })
                    _organize_status[status_key]["error"] = str(ex)
                    _organize_status[status_key]["progress"] = "error"
                    _organize_status[status_key]["stage"] = "error"
                    _organize_status[status_key]["message"] = str(ex)
                    _organize_status[status_key].setdefault("events", []).append(error_event)
                finally:
                    _organize_status[status_key]["running"] = False
                    _organize_status[status_key]["finished_at"] = time.time()

            import threading
            t = threading.Thread(target=_do_organize, daemon=True)
            t.start()
            return json_success(status="started", message="整理已开始，请轮询状态")
        except Exception as e:
            logger.error(f"[WebChannel] Knowledge organize error: {e}")
            return json_error(e)

    def GET(self):
        require_auth()
        try:
            params = web.input(book_id='')
            status_key = params.book_id or "__global__"
            info = _organize_status.get(status_key, {})
            if not info:
                try:
                    from agent.knowledge.service import KnowledgeService
                    svc = KnowledgeService(get_workspace_root())
                    task_status = svc.get_organize_task_status(book_id=params.book_id)
                    sources = task_status.get("sources") or {}
                    processing = [s for s in sources.values() if s.get("status") == "processing"]
                    failed = [s for s in sources.values() if s.get("status") in ("failed", "interrupted")]
                    indexed = [s for s in sources.values() if s.get("status") == "indexed"]
                    if processing or failed or indexed:
                        info = {
                            "running": bool(processing),
                            "progress": "processing" if processing else ("error" if failed and not indexed else "done"),
                            "stage": "processing" if processing else ("interrupted" if failed and not indexed else "done"),
                            "message": (
                                f"{len(processing)} processing, {len(indexed)} indexed, {len(failed)} failed/interrupted"
                            ),
                            "updated_at": time.time(),
                            "result": {
                                "processed_files": len(indexed),
                                "failed_files": len(failed),
                                "processing_files": len(processing),
                            },
                            "error": failed[-1].get("error") if failed else None,
                        }
                except Exception:
                    info = {}
            return json_response({
                "status": info.get("progress", "idle"),
                "running": info.get("running", False),
                "stage": info.get("stage", "idle"),
                "message": info.get("message", ""),
                "started_at": info.get("started_at"),
                "updated_at": info.get("updated_at"),
                "finished_at": info.get("finished_at"),
                "current_file": info.get("current_file"),
                "current_file_index": info.get("current_file_index"),
                "total_files": info.get("total_files"),
                "skipped_files": info.get("skipped_files", 0),
                "force": info.get("force", False),
                "current_chunks": info.get("current_chunks"),
                "total_chunks": info.get("total_chunks"),
                "current_batch": info.get("current_batch"),
                "total_batches": info.get("total_batches"),
                "events": info.get("events", []),
                "result": info.get("result"),
                "error": info.get("error"),
            })
        except Exception as e:
            return json_error(e)


class KnowledgeKnowledgeGraphHandler:
    def GET(self):
        require_auth()
        try:
            from agent.knowledge.service import KnowledgeService
            params = web.input(book_id='', limit='140', focus_id='', depth='1', query='', min_confidence='0')
            svc = KnowledgeService(get_workspace_root())
            result = svc.get_knowledge_graph(
                book_id=params.book_id,
                limit=int(params.limit or 140),
                focus_id=params.focus_id,
                depth=int(params.depth or 1),
                query=params.query,
                min_confidence=float(params.min_confidence or 0),
            )
            return json_success(**result)
        except Exception as e:
            logger.error(f"[WebChannel] Knowledge knowledge-graph error: {e}")
            return json_error(e, nodes=[], edges=[])


