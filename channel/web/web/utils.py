import json
import hashlib
import hmac
import time
from typing import Any, Dict

import web

from config import conf


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
    return bool(conf().get("web_password", ""))


def session_expire_seconds() -> int:
    return int(conf().get("web_session_expire_days", 30)) * 86400


def create_auth_token() -> str:
    ts = format(int(time.time()), "x")
    sig = hmac.new(
        conf().get("web_password", "").encode(),
        ts.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{ts}.{sig}"


def verify_auth_token(token) -> bool:
    if not token or "." not in token:
        return False
    ts_hex, sig = token.split(".", 1)
    try:
        ts = int(ts_hex, 16)
    except ValueError:
        return False
    if time.time() - ts > session_expire_seconds():
        return False
    expected = hmac.new(
        conf().get("web_password", "").encode(),
        ts_hex.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


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
