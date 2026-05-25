import os
from urllib.parse import urlparse


class ConfigValidationError(ValueError):
    pass


INT_RANGES = {
    "agent_max_context_tokens": (0, 2_000_000),
    "agent_max_context_turns": (1, 500),
    "agent_model_context_window": (0, 2_000_000),
    "agent_context_reserve_tokens": (0, 1_000_000),
    "agent_max_steps": (1, 500),
    "request_timeout": (1, 7200),
    "log_max_bytes": (1024, 1_073_741_824),
    "log_backup_count": (0, 100),
    "mineru_timeout_seconds": (1, 86_400),
    "mineru_poll_interval_seconds": (1, 3600),
    "knowledge_chunk_target_chars": (200, 200_000),
    "knowledge_chunk_max_chars": (200, 500_000),
    "knowledge_chunk_overlap_chars": (0, 100_000),
    "knowledge_secondary_graph_max_sections": (0, 10_000),
    "knowledge_secondary_graph_sample_chars": (100, 200_000),
    "web_upload_max_file_mb": (1, 2048),
    "web_upload_max_files": (1, 20_000),
    "web_upload_max_dir_depth": (1, 100),
}

BOOL_KEYS = {
    "use_linkai",
    "enable_thinking",
    "workspace_split_enabled",
    "web_require_password_on_public_host",
    "mineru_enable_formula",
    "mineru_enable_table",
    "mineru_enable_ocr",
    "knowledge_secondary_graph_enabled",
}

URL_KEYS = {
    "open_ai_api_base",
    "deepseek_api_base",
    "qianfan_api_base",
    "claude_api_base",
    "gemini_api_base",
    "dashscope_api_base",
    "zhipu_ai_api_base",
    "moonshot_base_url",
    "ark_base_url",
    "custom_api_base",
    "mineru_api_base",
}

PATH_KEYS = {
    "active_workspace",
    "workspace_dir",
    "system_workspace",
    "textbooks_storage_dir",
    "log_dir",
}


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return bool(value)


def _coerce_int(key, value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ConfigValidationError(f"{key} must be an integer")
    low, high = INT_RANGES[key]
    if parsed < low or parsed > high:
        raise ConfigValidationError(f"{key} must be between {low} and {high}")
    return parsed


def _validate_url(key, value):
    value = str(value or "").strip()
    if not value:
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigValidationError(f"{key} must be a valid http(s) URL")
    return value.rstrip("/")


def _normalize_path(key, value):
    value = str(value or "").strip()
    if not value:
        return value
    expanded = os.path.expandvars(os.path.expanduser(value))
    if "\x00" in expanded:
        raise ConfigValidationError(f"{key} contains an invalid path character")
    return os.path.normpath(expanded)


def validate_config_update(key, value):
    if key in INT_RANGES:
        return _coerce_int(key, value)
    if key in BOOL_KEYS:
        return _coerce_bool(value)
    if key in URL_KEYS:
        return _validate_url(key, value)
    if key in PATH_KEYS:
        return _normalize_path(key, value)
    if key == "web_password":
        return str(value or "")
    return value
