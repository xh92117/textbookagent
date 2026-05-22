import json
import os
import re
import shutil
import time
import zipfile
import tempfile
from pathlib import Path

import web

from common.log import get_log_path, logger
from config import conf
from channel.web.web.utils import (
    get_config_path, get_workspace_root, json_error, json_response, json_success,
    read_json_body, require_auth, reset_workspace_dependent_singletons,
)


def _generate_session_title(user_message: str, assistant_reply: str = "") -> str:
    from agent.chat.session_service import generate_session_title
    return generate_session_title(user_message, assistant_reply)


def _safe_skill_name(name: str) -> str:
    name = re.sub(r"\.zip$", "", os.path.basename(name or ""), flags=re.IGNORECASE)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip(".-")
    return name or "uploaded-skill"


def _safe_extract_zip(zip_path: str, extract_dir: str) -> None:
    extract_root = Path(extract_dir).resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            target = (extract_root / member.filename).resolve()
            try:
                target.relative_to(extract_root)
            except ValueError:
                raise ValueError("zip contains unsafe path")
        zf.extractall(extract_root)


def _find_uploaded_skill_dirs(extract_dir: str, fallback_name: str) -> list:
    root = Path(extract_dir)
    if (root / "SKILL.md").is_file():
        return [(fallback_name, root)]

    found = []
    for skill_md in root.rglob("SKILL.md"):
        skill_dir = skill_md.parent
        if any(part.startswith(".") for part in skill_dir.relative_to(root).parts):
            continue
        found.append((_safe_skill_name(skill_dir.name), skill_dir))
    return found


def _install_uploaded_skill_zip(zip_path: str, filename: str, custom_dir: str) -> list:
    fallback_name = _safe_skill_name(filename)
    installed = []
    os.makedirs(custom_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="skill_upload_") as tmp_dir:
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        _safe_extract_zip(zip_path, extract_dir)

        skill_dirs = _find_uploaded_skill_dirs(extract_dir, fallback_name)
        if not skill_dirs:
            raise ValueError("压缩包中未找到包含 SKILL.md 的技能目录")

        for skill_name, src_dir in skill_dirs:
            dst_dir = os.path.join(custom_dir, skill_name)
            dst_resolved = Path(dst_dir).resolve()
            custom_resolved = Path(custom_dir).resolve()
            try:
                dst_resolved.relative_to(custom_resolved)
            except ValueError:
                raise ValueError(f"invalid skill name: {skill_name}")
            if os.path.exists(dst_resolved):
                shutil.rmtree(dst_resolved)
            shutil.copytree(src_dir, dst_resolved)
            installed.append(skill_name)

    return installed


def _refresh_running_agent_skills() -> int:
    try:
        from bridge.bridge import Bridge
        return Bridge().get_agent_bridge().refresh_all_skills()
    except Exception as e:
        logger.debug(f"[WebChannel] refresh running skills skipped: {e}")
        return 0


class ToolsHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.tools.tool_manager import ToolManager
            tm = ToolManager()
            if not tm.tool_classes:
                tm.load_tools()
            tools = []
            for name, cls in tm.tool_classes.items():
                try:
                    instance = cls()
                    tools.append({
                        "name": name,
                        "description": instance.description,
                    })
                except Exception:
                    tools.append({"name": name, "description": ""})
            return json.dumps({"status": "success", "tools": tools}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Tools API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SkillsHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.skills.service import SkillService
            from agent.skills.manager import SkillManager
            workspace_root = get_workspace_root()
            manager = SkillManager(custom_dir=os.path.join(workspace_root, "skills"))
            service = SkillService(manager)
            skills = service.query()
            for s in skills:
                s['source'] = s.get('source', 'builtin')
            return json.dumps({"status": "success", "skills": skills}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Skills API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        require_auth()
        try:
            from agent.skills.service import SkillService
            from agent.skills.manager import SkillManager
            workspace_root = get_workspace_root()
            content_type = web.ctx.env.get('CONTENT_TYPE', '')

            if 'multipart/form-data' in content_type:
                web.header('Content-Type', 'application/json; charset=utf-8')
                import shutil
                import tempfile
                import zipfile
                x = web.input(file={})
                uploaded = x.get('file')
                if not getattr(uploaded, 'filename', None):
                    return json.dumps({"status": "error", "message": "请选择要上传的文件"}, ensure_ascii=False)

                filename = uploaded.filename
                if not filename.lower().endswith('.zip'):
                    return json.dumps({"status": "error", "message": "仅支持 .zip 压缩文件格式"}, ensure_ascii=False)

                custom_dir = os.path.join(workspace_root, "skills")
                os.makedirs(custom_dir, exist_ok=True)
                tmp_dir = tempfile.mkdtemp(prefix="skill_upload_")
                try:
                    zip_path = os.path.join(tmp_dir, os.path.basename(filename))
                    with open(zip_path, 'wb') as f:
                        f.write(uploaded.file.read())

                    installed = _install_uploaded_skill_zip(zip_path, filename, custom_dir)
                    manager = SkillManager(custom_dir=custom_dir)
                    manager.refresh_skills()
                    refreshed = _refresh_running_agent_skills()
                    service = SkillService(manager)
                    skills = service.query()
                    for s in skills:
                        s['source'] = s.get('source', 'builtin')
                    return json.dumps({
                        "status": "success",
                        "message": f"成功安装/更新: {', '.join(installed)}；已同步 skills_config.json；已刷新 {refreshed} 个运行中的智能体",
                        "installed": installed,
                        "skills": skills,
                    }, ensure_ascii=False)
                except zipfile.BadZipFile:
                    return json.dumps({"status": "error", "message": "压缩文件已损坏，无法解压"}, ensure_ascii=False)
                except ValueError as e:
                    return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

            if 'multipart/form-data' in content_type:
                web.header('Content-Type', 'application/json; charset=utf-8')
                import zipfile
                import tempfile
                import shutil
                x = web.input(file={})
                uploaded = x.get('file')
                if not getattr(uploaded, 'filename', None):
                    return json.dumps({"status": "error", "message": "请选择要上传的文件"}, ensure_ascii=False)

                filename = uploaded.filename
                if not filename.lower().endswith('.zip'):
                    return json.dumps({"status": "error", "message": "仅支持 .zip 压缩文件格式"}, ensure_ascii=False)

                custom_dir = os.path.join(workspace_root, "skills")
                os.makedirs(custom_dir, exist_ok=True)

                tmp_dir = tempfile.mkdtemp(prefix="skill_upload_")
                try:
                    zip_path = os.path.join(tmp_dir, filename)
                    with open(zip_path, 'wb') as f:
                        f.write(uploaded.file.read())

                    try:
                        with zipfile.ZipFile(zip_path, 'r') as zf:
                            zf.extractall(tmp_dir)
                    except zipfile.BadZipFile:
                        return json.dumps({"status": "error", "message": "压缩文件已损坏，无法解压"}, ensure_ascii=False)

                    skill_dirs = []
                    for item in os.listdir(tmp_dir):
                        item_path = os.path.join(tmp_dir, item)
                        if item == filename or not os.path.isdir(item_path):
                            continue
                        if os.path.isfile(os.path.join(item_path, "SKILL.md")):
                            skill_dirs.append(item_path)

                    if not skill_dirs:
                        for item in os.listdir(tmp_dir):
                            item_path = os.path.join(tmp_dir, item)
                            if item == filename or not os.path.isdir(item_path):
                                continue
                            for sub in os.listdir(item_path):
                                sub_path = os.path.join(item_path, sub)
                                if os.path.isdir(sub_path) and os.path.isfile(os.path.join(sub_path, "SKILL.md")):
                                    skill_dirs.append(sub_path)

                    if not skill_dirs:
                        return json.dumps({"status": "error", "message": "压缩包中未找到包含 SKILL.md 的技能目录。请确保压缩包结构为: 技能名/SKILL.md"}, ensure_ascii=False)

                    installed = []
                    skipped = []
                    for src_dir in skill_dirs:
                        skill_name = os.path.basename(src_dir)
                        dst_dir = os.path.join(custom_dir, skill_name)
                        if os.path.exists(dst_dir):
                            skipped.append(skill_name)
                            continue
                        shutil.copytree(src_dir, dst_dir)
                        installed.append(skill_name)

                    manager = SkillManager(custom_dir=custom_dir)
                    manager.refresh_skills()

                    msg_parts = []
                    if installed:
                        msg_parts.append(f"成功安装: {', '.join(installed)}")
                    if skipped:
                        msg_parts.append(f"已跳过(同名存在): {', '.join(skipped)}")
                    return json.dumps({"status": "success", "message": '; '.join(msg_parts)}, ensure_ascii=False)
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

            web.header('Content-Type', 'application/json; charset=utf-8')
            body = json.loads(web.data())
            action = body.get("action")
            manager = SkillManager(custom_dir=os.path.join(workspace_root, "skills"))
            service = SkillService(manager)

            if action == "open":
                name = body.get("name")
                if not name:
                    return json.dumps({"status": "error", "message": "name is required"})
                service.open({"name": name})
                _refresh_running_agent_skills()
            elif action == "close":
                name = body.get("name")
                if not name:
                    return json.dumps({"status": "error", "message": "name is required"})
                service.close({"name": name})
                _refresh_running_agent_skills()
            elif action == "refresh":
                manager.refresh_skills()
                _refresh_running_agent_skills()
                skills = service.query()
                for s in skills:
                    s['source'] = s.get('source', 'builtin')
                return json.dumps({"status": "success", "skills": skills}, ensure_ascii=False)
            elif action == "delete":
                name = body.get("name")
                if not name:
                    return json.dumps({"status": "error", "message": "name is required"})
                entry = manager.get_skill(name)
                if entry and entry.skill.source == 'builtin':
                    return json.dumps({"status": "error", "message": "内置技能不可删除"}, ensure_ascii=False)
                service.delete({"name": name})
                _refresh_running_agent_skills()
                return json.dumps({"status": "success", "message": f"技能 '{name}' 已删除"}, ensure_ascii=False)
            else:
                return json.dumps({"status": "error", "message": f"unknown action: {action}"})
            return json.dumps({"status": "success"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Skills POST error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class WorkspaceHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from common.app_paths import active_workspace, ensure_active_workspace, ensure_system_dir, system_dir, system_root
            ensure_active_workspace()
            ensure_system_dir()
            return json.dumps({
                "status": "success",
                "active_workspace": active_workspace(),
                "system_root": system_root(),
                "system_dir": system_dir(),
                "workspace_split_enabled": bool(conf().get("workspace_split_enabled", True)),
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Workspace API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data() or b"{}")
            active = str(body.get("active_workspace", "") or body.get("workspace_dir", "")).strip()
            split_enabled = body.get("workspace_split_enabled", None)
            if not active:
                return json.dumps({"status": "error", "message": "active_workspace is required"}, ensure_ascii=False)
            active = os.path.abspath(os.path.expanduser(active))
            from common.app_paths import system_root
            if os.path.normcase(active) == os.path.normcase(system_root()):
                return json.dumps({"status": "error", "message": "工作区不能直接选择系统区根目录"}, ensure_ascii=False)
            os.makedirs(active, exist_ok=True)

            local_config = conf()
            local_config["active_workspace"] = active
            if split_enabled is not None:
                local_config["workspace_split_enabled"] = bool(split_enabled)

            config_path = get_config_path()
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    file_cfg = json.load(f)
            else:
                file_cfg = {}
            file_cfg["active_workspace"] = active
            if split_enabled is not None:
                file_cfg["workspace_split_enabled"] = bool(split_enabled)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(file_cfg, f, ensure_ascii=False, indent=2)

            from common.app_paths import ensure_active_workspace, ensure_system_dir, system_dir
            ensure_active_workspace()
            ensure_system_dir()
            reset_workspace_dependent_singletons()
            return json.dumps({
                "status": "success",
                "active_workspace": active,
                "system_dir": system_dir(),
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Workspace update error: {e}", exc_info=True)
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


class MemoryHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.memory.service import MemoryService
            from common.app_paths import system_dir
            params = web.input(page='1', page_size='20', category='memory')
            workspace_root = system_dir()
            service = MemoryService(workspace_root)
            result = service.list_files(
                page=int(params.page), page_size=int(params.page_size),
                category=params.category,
            )
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Memory API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class MemoryContentHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.memory.service import MemoryService
            from common.app_paths import system_dir
            params = web.input(filename='', category='memory')
            if not params.filename:
                return json.dumps({"status": "error", "message": "filename required"})
            workspace_root = system_dir()
            service = MemoryService(workspace_root)
            result = service.get_content(params.filename, category=params.category)
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except ValueError:
            return json.dumps({"status": "error", "message": "invalid filename"})
        except FileNotFoundError:
            return json.dumps({"status": "error", "message": "file not found"})
        except Exception as e:
            logger.error(f"[WebChannel] Memory content API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class MemoryQueryHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.memory import MemoryQueryService
            from common.app_paths import system_dir
            params = web.input(
                session_id='',
                process_id='',
                page='1',
                page_size='20',
                include_textbook_history='1',
            )
            service = MemoryQueryService(system_dir())
            result = service.query(
                session_id=params.session_id,
                process_id=params.process_id,
                page=int(params.page),
                page_size=int(params.page_size),
                include_textbook_history=str(params.include_textbook_history) != '0',
            )
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Memory query API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SchedulerHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from agent.tools.scheduler.task_store import TaskStore
            from common.app_paths import system_dir
            store_path = os.path.join(system_dir(), "scheduler", "tasks.json")
            store = TaskStore(store_path)
            tasks = store.list_tasks()
            return json.dumps({"status": "success", "tasks": tasks}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Scheduler API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SessionsHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(page='1', page_size='50')
            from agent.memory import get_conversation_store
            store = get_conversation_store()
            result = store.list_sessions(
                channel_type="web",
                page=int(params.page),
                page_size=int(params.page_size),
            )
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Sessions API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SessionDetailHandler:
    def DELETE(self, session_id: str):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        logger.info(f"[WebChannel] DELETE session request: {session_id}")
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            from agent.memory import get_conversation_store
            store = get_conversation_store()
            store.clear_session(session_id)

            # Also remove the Agent instance from AgentBridge if exists
            try:
                from bridge.bridge import Bridge
                ab = Bridge().get_agent_bridge()
                if session_id in ab.agents:
                    del ab.agents[session_id]
                    logger.info(f"[WebChannel] Removed agent instance for session {session_id}")
            except Exception:
                pass

            from channel.web.web.web_channel import WebChannel
            channel = WebChannel()
            channel.session_queues.pop(session_id, None)

            logger.info(f"[WebChannel] Session deleted: {session_id}")
            return json.dumps({"status": "success"})
        except Exception as e:
            logger.error(f"[WebChannel] Session delete error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def PUT(self, session_id: str):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})
            body = json.loads(web.data())
            title = body.get("title", "").strip()
            if not title:
                return json.dumps({"status": "error", "message": "title required"})

            from agent.memory import get_conversation_store
            store = get_conversation_store()
            found = store.rename_session(session_id, title)
            if not found:
                return json.dumps({"status": "error", "message": "session not found"})
            return json.dumps({"status": "success"})
        except Exception as e:
            logger.error(f"[WebChannel] Session rename error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SessionTitleHandler:
    def POST(self, session_id: str):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            body = json.loads(web.data())
            user_message = body.get("user_message", "")
            assistant_reply = body.get("assistant_reply", "")
            if not user_message:
                return json.dumps({"status": "error", "message": "user_message required"})

            title = _generate_session_title(user_message, assistant_reply)

            from agent.memory import get_conversation_store
            store = get_conversation_store()
            updated = store.rename_session(session_id, title)
            logger.info(f"[WebChannel] Session title set: sid={session_id}, title='{title}', db_updated={updated}")

            return json.dumps({"status": "success", "title": title}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Title generation error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class SessionClearContextHandler:
    def POST(self, session_id: str):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            from agent.memory import get_conversation_store
            store = get_conversation_store()
            new_seq = store.clear_context(session_id)

            # Delete the agent instance so a fresh one is created on the next message
            try:
                from bridge.bridge import Bridge
                bridge = Bridge()
                ab = bridge.get_agent_bridge()
                if session_id in ab.agents:
                    del ab.agents[session_id]
                    logger.info(f"[WebChannel] Cleared agent instance for session {session_id}")
            except Exception:
                pass

            return json.dumps({"status": "success", "context_start_seq": new_seq})
        except Exception as e:
            logger.error(f"[WebChannel] Clear context error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class HistoryHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        web.header('Access-Control-Allow-Origin', '*')
        try:
            params = web.input(session_id='', page='1', page_size='20')
            session_id = params.session_id.strip()
            if not session_id:
                return json.dumps({"status": "error", "message": "session_id required"})

            from agent.memory import get_conversation_store
            store = get_conversation_store()
            result = store.load_history_page(
                session_id=session_id,
                page=int(params.page),
                page_size=int(params.page_size),
            )
            return json.dumps({"status": "success", **result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] History API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class LogsHandler:
    def GET(self):
        require_auth()
        web.header('Content-Type', 'text/event-stream; charset=utf-8')
        web.header('Cache-Control', 'no-cache')
        web.header('X-Accel-Buffering', 'no')

        log_path = get_log_path()

        def generate():
            if not os.path.isfile(log_path):
                yield b"data: {\"type\": \"error\", \"message\": \"log file not found\"}\n\n"
                return

            # Read last 200 lines for initial display
            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
                tail_lines = lines[-200:]
                chunk = ''.join(tail_lines)
                payload = json.dumps({"type": "init", "content": chunk}, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode('utf-8')
            except Exception as e:
                yield f"data: {{\"type\": \"error\", \"message\": \"{e}\"}}\n\n".encode('utf-8')
                return

            # Tail new lines
            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(0, 2)  # seek to end
                    deadline = time.time() + 600  # 10 min max
                    while time.time() < deadline:
                        line = f.readline()
                        if line:
                            payload = json.dumps({"type": "line", "content": line}, ensure_ascii=False)
                            yield f"data: {payload}\n\n".encode('utf-8')
                        else:
                            yield b": keepalive\n\n"
                            time.sleep(1)
            except GeneratorExit:
                return
            except Exception:
                return

        return generate()


