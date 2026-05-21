import json
from typing import Any, Dict

import web


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
