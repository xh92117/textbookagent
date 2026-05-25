import json
import os
from typing import Any, Dict

import web

from config import conf
from channel.web.web.security import create_session_token, verify_session_token


def json_response(payload: Dict[str, Any], *, ensure_ascii: bool = False) -> str:
    web.header('Content-Type', 'application/json; charset=utf-8')
    return json.dumps(payload, ensure_ascii=ensure_ascii)


def json_success(**payload: Any) -> str:
    return json_response({"status": "success", **payload})


def json_error(message: Any, **payload: Any) -> str:
    return json_response({"status": "error", "message": str(message), **payload})


def read_json_body(default=None):
    raw = web.data()
    if not raw or not raw.strip():
        return {} if default is None else default
    return json.loads(raw)


def is_password_enabled() -> bool:
    return bool(conf().get("web_password_hash", "") or conf().get("web_password", ""))


def session_expire_seconds() -> int:
    return int(conf().get("web_session_expire_days", 30)) * 86400


def create_auth_token() -> str:
    return create_session_token(conf().get("web_password_hash", "") or conf().get("web_password", ""))


def verify_auth_token(token) -> bool:
    stored = conf().get("web_password_hash", "") or conf().get("web_password", "")
    return verify_session_token(token, stored, session_expire_seconds())


def check_auth() -> bool:
    if not is_password_enabled():
        return True
    return verify_auth_token(web.cookies().get("cow_auth_token", ""))


def require_auth():
    if not check_auth():
        raise web.HTTPError(
            "401 Unauthorized",
            {"Content-Type": "application/json; charset=utf-8"},
            json.dumps({"status": "error", "message": "Unauthorized"}),
        )


def get_workspace_root() -> str:
    from common.app_paths import ensure_active_workspace
    return ensure_active_workspace()


def get_upload_dir() -> str:
    from common.app_paths import tmp_dir as app_tmp_dir
    tmp_dir = app_tmp_dir()
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


def get_project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def get_config_path() -> str:
    return os.path.join(get_project_root(), "config.json")


def reset_workspace_dependent_singletons() -> None:
    try:
        import bridge.textbook_bridge as tb
        tb._bridge_instance = None
    except Exception:
        pass
    try:
        import agent.memory.conversation_store as conversation_store
        conversation_store._store_instance = None
    except Exception:
        pass
    try:
        import agent.memory.config as memory_config
        memory_config._global_memory_config = None
    except Exception:
        pass
