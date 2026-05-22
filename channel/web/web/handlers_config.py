"""Configuration API handlers for the web channel."""

import json
import os
import uuid
from collections import OrderedDict

import web

from common import const
from common.log import logger
from config import conf
from channel.web.web.utils import get_config_path, require_auth, reset_workspace_dependent_singletons


class ConfigHandler:

    _RECOMMENDED_MODELS = [
        const.DEEPSEEK_V4_FLASH, const.DEEPSEEK_V4_PRO, const.DEEPSEEK_CHAT, const.DEEPSEEK_REASONER,
        const.MINIMAX_M2_7_HIGHSPEED, const.MINIMAX_M2_7, const.MINIMAX_M2_5, const.MINIMAX_M2_1, const.MINIMAX_M2_1_LIGHTNING,
        const.CLAUDE_4_6_SONNET, const.CLAUDE_4_7_OPUS, const.CLAUDE_4_6_OPUS, const.CLAUDE_4_5_SONNET,
        const.GEMINI_31_FLASH_LITE_PRE, const.GEMINI_31_PRO_PRE, const.GEMINI_3_FLASH_PRE,
        const.GPT_54, const.GPT_54_MINI, const.GPT_54_NANO, const.GPT_5, const.GPT_41, const.GPT_4o,
        const.GLM_5_1, const.GLM_5_TURBO, const.GLM_5, const.GLM_4_7,
        const.QWEN36_PLUS, const.QWEN35_PLUS, const.QWEN3_MAX,
        const.DOUBAO_SEED_2_PRO, const.DOUBAO_SEED_2_CODE,
        const.KIMI_K2_6, const.KIMI_K2_5, const.KIMI_K2,
        const.ERNIE_5_1, const.ERNIE_5, const.ERNIE_X1_1, const.ERNIE_45_TURBO_128K, const.ERNIE_45_TURBO_32K,
    ]

    # Generic placeholder hints surfaced in the web console. We deliberately
    # show the version-path tail (e.g. "/v1") so users are reminded to type
    # the full base URL. The form is intentionally vague (`...../v1`) so it
    # never looks like a real default a user might paste verbatim — and we
    # never auto-rewrite anything on the server side.
    _PLACEHOLDER_V1 = "https://...../v1"
    _PLACEHOLDER_QIANFAN = "https://...../v2"
    _PLACEHOLDER_ZHIPU = "https://...../api/paas/v4"
    _PLACEHOLDER_DOUBAO = "https://...../api/v3"
    _PLACEHOLDER_GEMINI = "https://....."

    PROVIDER_MODELS = OrderedDict([
        ("deepseek", {
            "label": "DeepSeek",
            "api_key_field": "deepseek_api_key",
            "api_base_key": "deepseek_api_base",
            "api_base_default": "https://api.deepseek.com/v1",
            "api_base_placeholder": _PLACEHOLDER_V1,
            "models": [const.DEEPSEEK_V4_FLASH, const.DEEPSEEK_V4_PRO, const.DEEPSEEK_CHAT, const.DEEPSEEK_REASONER],
        }),
        ("minimax", {
            "label": "MiniMax",
            "api_key_field": "minimax_api_key",
            "api_base_key": None,
            "api_base_default": None,
            "api_base_placeholder": "",
            "models": [const.MINIMAX_M2_7, const.MINIMAX_M2_7_HIGHSPEED, const.MINIMAX_M2_5, const.MINIMAX_M2_1, const.MINIMAX_M2_1_LIGHTNING],
        }),
        ("claudeAPI", {
            "label": "Claude",
            "api_key_field": "claude_api_key",
            "api_base_key": "claude_api_base",
            "api_base_default": "https://api.anthropic.com/v1",
            "api_base_placeholder": _PLACEHOLDER_V1,
            "models": [const.CLAUDE_4_6_SONNET, const.CLAUDE_4_7_OPUS, const.CLAUDE_4_6_OPUS, const.CLAUDE_4_5_SONNET],
        }),
        ("gemini", {
            "label": "Gemini",
            "api_key_field": "gemini_api_key",
            "api_base_key": "gemini_api_base",
            "api_base_default": "https://generativelanguage.googleapis.com",
            "api_base_placeholder": _PLACEHOLDER_GEMINI,
            "models": [const.GEMINI_31_FLASH_LITE_PRE, const.GEMINI_31_PRO_PRE, const.GEMINI_3_FLASH_PRE],
        }),
        ("openai", {
            "label": "OpenAI",
            "api_key_field": "open_ai_api_key",
            "api_base_key": "open_ai_api_base",
            "api_base_default": "https://api.openai.com/v1",
            "api_base_placeholder": _PLACEHOLDER_V1,
            "models": [const.GPT_54, const.GPT_54_MINI, const.GPT_54_NANO, const.GPT_5, const.GPT_41, const.GPT_4o],
        }),
        ("zhipu", {
            "label": "智谱AI",
            "api_key_field": "zhipu_ai_api_key",
            "api_base_key": "zhipu_ai_api_base",
            "api_base_default": "https://open.bigmodel.cn/api/paas/v4",
            "api_base_placeholder": _PLACEHOLDER_ZHIPU,
            "models": [const.GLM_5_1, const.GLM_5_TURBO, const.GLM_5, const.GLM_4_7],
        }),
        ("dashscope", {
            "label": "通义千问",
            "api_key_field": "dashscope_api_key",
            "api_base_key": "dashscope_api_base",
            "api_base_default": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_base_placeholder": _PLACEHOLDER_V1,
            "models": [const.QWEN36_PLUS, const.QWEN35_PLUS, const.QWEN3_MAX, const.DEEPSEEK_CHAT, const.DEEPSEEK_REASONER, const.DEEPSEEK_V4_FLASH],
        }),
        ("doubao", {
            "label": "豆包",
            "api_key_field": "ark_api_key",
            "api_base_key": "ark_base_url",
            "api_base_default": "https://ark.cn-beijing.volces.com/api/v3",
            "api_base_placeholder": _PLACEHOLDER_DOUBAO,
            "models": [const.DOUBAO_SEED_2_PRO, const.DOUBAO_SEED_2_CODE],
        }),
        ("moonshot", {
            "label": "Kimi",
            "api_key_field": "moonshot_api_key",
            "api_base_key": "moonshot_base_url",
            "api_base_default": "https://api.moonshot.cn/v1",
            "api_base_placeholder": _PLACEHOLDER_V1,
            "models": [const.KIMI_K2_6, const.KIMI_K2_5, const.KIMI_K2],
        }),
        ("qianfan", {
            "label": "百度千帆",
            "api_key_field": "qianfan_api_key",
            "api_base_key": "qianfan_api_base",
            "api_base_default": "https://qianfan.baidubce.com/v2",
            "api_base_placeholder": _PLACEHOLDER_QIANFAN,
            "models": [const.ERNIE_5_1, const.ERNIE_5, const.ERNIE_X1_1, const.ERNIE_45_TURBO_128K, const.ERNIE_45_TURBO_32K],
        }),
        ("modelscope", {
            "label": "ModelScope",
            "api_key_field": "modelscope_api_key",
            "api_base_key": None,
            "api_base_default": None,
            "api_base_placeholder": "",
            "models": [const.QWEN3_5_27B, const.QWEN3_235B_A22B_INSTRUCT_2507],
        }),
        ("linkai", {
            "label": "LinkAI",
            "api_key_field": "linkai_api_key",
            "api_base_key": None,
            "api_base_default": None,
            "api_base_placeholder": "",
            "models": _RECOMMENDED_MODELS,
        }),
        ("custom", {
            "label": "自定义",
            "api_key_field": "custom_api_key",
            "api_base_key": "custom_api_base",
            "api_base_default": "",
            "api_base_placeholder": _PLACEHOLDER_V1,
            "models": _RECOMMENDED_MODELS,
        }),
    ])

    EDITABLE_KEYS = {
        "model", "bot_type", "review_model", "review_bot_type", "image_model", "image_bot_type",
        "knowledge_model", "knowledge_bot_type", "knowledge_api_key", "knowledge_api_base",
        "ai_chat_models", "active_chat_model_id", "review_model_id", "image_model_id", "knowledge_model_id", "use_linkai",
        "open_ai_api_base", "deepseek_api_base", "qianfan_api_base", "claude_api_base", "gemini_api_base", "dashscope_api_base",
        "zhipu_ai_api_base", "moonshot_base_url", "ark_base_url", "custom_api_base",
        "open_ai_api_key", "deepseek_api_key", "qianfan_api_key", "claude_api_key", "gemini_api_key",
        "zhipu_ai_api_key", "dashscope_api_key", "moonshot_api_key",
        "ark_api_key", "minimax_api_key", "linkai_api_key", "custom_api_key",
        "agent_max_context_tokens", "agent_max_context_turns", "agent_model_context_window",
        "agent_context_reserve_tokens", "agent_max_steps", "request_timeout",
        "knowledge_organize_mode", "knowledge_fast_chunk_threshold", "knowledge_extract_assets",
        "knowledge_chunk_strategy", "knowledge_chunk_target_chars", "knowledge_chunk_max_chars", "knowledge_chunk_overlap_chars",
        "knowledge_secondary_graph_enabled", "knowledge_secondary_graph_max_sections", "knowledge_secondary_graph_sample_chars",
        "knowledge_skip_logo_watermark_assets", "knowledge_min_asset_width",
        "knowledge_min_asset_height", "knowledge_min_asset_area",
        "mineru_api_key", "mineru_api_base", "mineru_model_version", "mineru_language",
        "mineru_enable_formula", "mineru_enable_table", "mineru_enable_ocr",
        "mineru_timeout_seconds", "mineru_poll_interval_seconds",
        "enable_thinking", "web_password", "web_require_password_on_public_host",
        "log_dir", "log_file", "log_max_bytes", "log_backup_count",
        "active_workspace", "system_workspace", "workspace_split_enabled", "textbooks_storage_dir",
    }

    @staticmethod
    def _mask_key(value: str) -> str:
        """Mask the middle part of an API key for display."""
        if not value or len(value) <= 8:
            return value
        return value[:4] + "*" * (len(value) - 8) + value[-4:]

    @staticmethod
    def _provider_to_bot_type(provider_id: str) -> str:
        return "chatGPT" if provider_id == "openai" else (provider_id or "")

    @staticmethod
    def _bot_type_to_provider(bot_type: str) -> str:
        return "openai" if bot_type == "chatGPT" else (bot_type or "")

    def _provider_secret_keys(self, provider_id: str):
        pinfo = self.PROVIDER_MODELS.get(provider_id, {})
        return pinfo.get("api_key_field"), pinfo.get("api_base_key")

    def _runtime_bot_type_for_model(self, model_item: dict) -> str:
        try:
            from models.model_registry import ModelRegistry

            return ModelRegistry._runtime_bot_type(
                model_item.get("provider", ""),
                model_item.get("api_base", ""),
            )
        except Exception:
            return self._provider_to_bot_type(model_item.get("provider", ""))

    def _configured_chat_models(self, local_config: dict) -> list:
        models = local_config.get("ai_chat_models")
        if isinstance(models, list):
            hydrated = []
            for item in models:
                if not isinstance(item, dict):
                    continue
                filled = dict(item)
                key_field, base_key = self._provider_secret_keys(filled.get("provider", ""))
                if key_field and not filled.get("api_key"):
                    filled["api_key"] = local_config.get(key_field, "")
                if base_key and not filled.get("api_base"):
                    filled["api_base"] = local_config.get(base_key, "")
                hydrated.append(filled)
            if hydrated:
                return hydrated
        provider = self._bot_type_to_provider(local_config.get("bot_type", ""))
        if not provider:
            provider = "custom" if local_config.get("custom_api_base") else "openai"
        key_field, base_key = self._provider_secret_keys(provider)
        model_name = local_config.get("model", "")
        if not model_name:
            return []
        return [{
            "id": "default",
            "name": model_name,
            "provider": provider,
            "model": model_name,
            "api_key": local_config.get(key_field, "") if key_field else "",
            "api_base": local_config.get(base_key, "") if base_key else "",
        }]

    def _public_chat_models(self, models: list) -> list:
        result = []
        for item in models:
            public = dict(item)
            public["provider_key_configured"] = bool(public.get("api_key"))
            public.pop("api_key", None)
            result.append(public)
        return result

    def _find_chat_model(self, models: list, model_id: str) -> dict:
        for item in models:
            if item.get("id") == model_id:
                return item
        return models[0] if models else {}

    def GET(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            local_config = conf()
            use_agent = local_config.get("agent", False)
            title = "TextbookAgent" if use_agent else "AI Assistant"

            api_bases = {}
            api_keys_masked = {}
            for pid, pinfo in self.PROVIDER_MODELS.items():
                base_key = pinfo.get("api_base_key")
                if base_key:
                    api_bases[base_key] = local_config.get(base_key, pinfo["api_base_default"])
                key_field = pinfo.get("api_key_field")
                if key_field and key_field not in api_keys_masked:
                    raw = local_config.get(key_field, "")
                    api_keys_masked[key_field] = self._mask_key(raw) if raw else ""

            providers = {}
            for pid, p in self.PROVIDER_MODELS.items():
                providers[pid] = {
                    "label": p["label"],
                    "models": p["models"],
                    "api_base_key": p["api_base_key"],
                    "api_base_default": p["api_base_default"],
                    "api_base_placeholder": p.get("api_base_placeholder", ""),
                    "api_key_field": p.get("api_key_field"),
                }

            raw_pwd = local_config.get("web_password", "")
            masked_pwd = ("*" * len(raw_pwd)) if raw_pwd else ""

            chat_models = self._configured_chat_models(local_config)
            active_model_id = local_config.get("active_chat_model_id") or (chat_models[0].get("id") if chat_models else "")
            review_model_id = local_config.get("review_model_id") or active_model_id
            image_model_id = local_config.get("image_model_id") or active_model_id
            knowledge_model_id = local_config.get("knowledge_model_id") or active_model_id

            return json.dumps({
                "status": "success",
                "use_agent": use_agent,
                "title": title,
                "model": local_config.get("model", ""),
                "review_model": local_config.get("review_model", local_config.get("model", "")),
                "image_model": local_config.get("image_model", local_config.get("model", "")),
                "knowledge_model": local_config.get("knowledge_model", local_config.get("model", "")),
                "bot_type": "openai" if local_config.get("bot_type") == "chatGPT" else local_config.get("bot_type", ""),
                "review_bot_type": "openai" if local_config.get("review_bot_type", local_config.get("bot_type")) == "chatGPT" else local_config.get("review_bot_type", local_config.get("bot_type", "")),
                "image_bot_type": "openai" if local_config.get("image_bot_type", local_config.get("bot_type")) == "chatGPT" else local_config.get("image_bot_type", local_config.get("bot_type", "")),
                "ai_chat_models": self._public_chat_models(chat_models),
                "active_chat_model_id": active_model_id,
                "review_model_id": review_model_id,
                "image_model_id": image_model_id,
                "knowledge_model_id": knowledge_model_id,
                "use_linkai": bool(local_config.get("use_linkai", False)),
                "channel_type": local_config.get("channel_type", ""),
                "agent_max_context_tokens": local_config.get("agent_max_context_tokens", 50000),
                "agent_max_context_turns": local_config.get("agent_max_context_turns", 20),
                "agent_model_context_window": local_config.get("agent_model_context_window", 0),
                "agent_context_reserve_tokens": local_config.get("agent_context_reserve_tokens", 0),
                "agent_max_steps": local_config.get("agent_max_steps", 20),
                "enable_thinking": bool(local_config.get("enable_thinking", False)),
                "web_require_password_on_public_host": bool(local_config.get("web_require_password_on_public_host", True)),
                "log_dir": local_config.get("log_dir", "logs"),
                "log_file": local_config.get("log_file", "run.log"),
                "log_max_bytes": local_config.get("log_max_bytes", 5242880),
                "log_backup_count": local_config.get("log_backup_count", 5),
                "api_bases": api_bases,
                "api_keys": api_keys_masked,
                "providers": providers,
                "mineru": {
                    "api_key": self._mask_key(local_config.get("mineru_api_key", "")) if local_config.get("mineru_api_key", "") else "",
                    "api_base": local_config.get("mineru_api_base", "https://mineru.net"),
                    "model_version": local_config.get("mineru_model_version", "vlm"),
                    "language": local_config.get("mineru_language", "auto"),
                    "enable_formula": bool(local_config.get("mineru_enable_formula", True)),
                    "enable_table": bool(local_config.get("mineru_enable_table", True)),
                    "enable_ocr": bool(local_config.get("mineru_enable_ocr", True)),
                    "timeout_seconds": local_config.get("mineru_timeout_seconds", 1800),
                    "poll_interval_seconds": local_config.get("mineru_poll_interval_seconds", 5),
                },
                "web_password_masked": masked_pwd,
                "workspace": self._workspace_payload(),
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    @staticmethod
    def _workspace_payload():
        from common.app_paths import active_workspace, system_dir, system_root, textbooks_dir
        return {
            "active_workspace": active_workspace(),
            "textbooks_storage_dir": textbooks_dir(),
            "system_root": system_root(),
            "system_dir": system_dir(),
            "workspace_split_enabled": bool(conf().get("workspace_split_enabled", True)),
        }

    def POST(self):
        require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            data = json.loads(web.data())
            updates = data.get("updates", {})
            if not updates:
                return json.dumps({"status": "error", "message": "no updates provided"})

            local_config = conf()
            previous_chat_models = self._configured_chat_models(local_config)
            applied = {}
            for key, value in updates.items():
                if key not in self.EDITABLE_KEYS:
                    continue
                if key in (
                    "agent_max_context_tokens", "agent_max_context_turns",
                    "agent_model_context_window", "agent_context_reserve_tokens",
                    "agent_max_steps", "log_max_bytes", "log_backup_count",
                    "mineru_timeout_seconds", "mineru_poll_interval_seconds",
                    "knowledge_chunk_target_chars", "knowledge_chunk_max_chars", "knowledge_chunk_overlap_chars",
                    "knowledge_secondary_graph_max_sections", "knowledge_secondary_graph_sample_chars",
                ):
                    value = int(value)
                if key in (
                    "use_linkai", "enable_thinking", "workspace_split_enabled",
                    "web_require_password_on_public_host", "mineru_enable_formula",
                    "mineru_enable_table", "mineru_enable_ocr", "knowledge_secondary_graph_enabled",
                ):
                    value = bool(value)
                local_config[key] = value
                applied[key] = value

            if "ai_chat_models" in applied:
                clean_models = []
                old_by_id = {m.get("id"): m for m in previous_chat_models if m.get("id")}
                for raw in applied["ai_chat_models"] if isinstance(applied["ai_chat_models"], list) else []:
                    if not isinstance(raw, dict):
                        continue
                    provider = raw.get("provider", "custom")
                    model_name = str(raw.get("model", "")).strip()
                    if not model_name:
                        continue
                    item_id = str(raw.get("id") or uuid.uuid4().hex[:10])
                    clean_item = {
                        "id": item_id,
                        "name": str(raw.get("name") or model_name).strip(),
                        "provider": provider,
                        "model": model_name,
                        "api_base": str(raw.get("api_base", "") or "").strip(),
                    }
                    raw_key = str(raw.get("api_key", "") or "").strip()
                    # Preserve model-instance credentials when the UI sends a
                    # real key. Ignore masked display values such as sk-***1234.
                    if raw_key and "*" not in raw_key:
                        clean_item["api_key"] = raw_key
                    elif item_id in old_by_id and old_by_id[item_id].get("api_key"):
                        clean_item["api_key"] = old_by_id[item_id]["api_key"]
                    clean_models.append(clean_item)
                local_config["ai_chat_models"] = clean_models
                applied["ai_chat_models"] = clean_models

            chat_models = self._configured_chat_models(local_config)
            active_id = local_config.get("active_chat_model_id") or (chat_models[0].get("id") if chat_models else "")
            active_item = self._find_chat_model(chat_models, active_id)
            if active_item:
                provider = active_item.get("provider", "")
                key_field, base_key = self._provider_secret_keys(provider)
                local_config["model"] = active_item.get("model", "")
                local_config["bot_type"] = self._runtime_bot_type_for_model(active_item)
                applied["model"] = local_config["model"]
                applied["bot_type"] = local_config["bot_type"]
                if key_field and active_item.get("api_key"):
                    local_config[key_field] = active_item["api_key"]
                    applied[key_field] = active_item["api_key"]
                if base_key and active_item.get("api_base"):
                    local_config[base_key] = active_item["api_base"]
                    applied[base_key] = active_item["api_base"]
                if local_config["bot_type"] == "custom" and provider != "custom":
                    provider_key = active_item.get("api_key") or (local_config.get(key_field, "") if key_field else "")
                    if provider_key:
                        local_config["custom_api_key"] = provider_key
                        applied["custom_api_key"] = provider_key
                    if active_item.get("api_base"):
                        local_config["custom_api_base"] = active_item["api_base"]
                        applied["custom_api_base"] = active_item["api_base"]

            review_item = self._find_chat_model(chat_models, local_config.get("review_model_id", active_id))
            if review_item:
                local_config["review_model"] = review_item.get("model", "")
                local_config["review_bot_type"] = self._runtime_bot_type_for_model(review_item)
                applied["review_model"] = local_config["review_model"]
                applied["review_bot_type"] = local_config["review_bot_type"]

            image_item = self._find_chat_model(chat_models, local_config.get("image_model_id", active_id))
            if image_item:
                local_config["image_model"] = image_item.get("model", "")
                local_config["image_bot_type"] = self._runtime_bot_type_for_model(image_item)
                applied["image_model"] = local_config["image_model"]
                applied["image_bot_type"] = local_config["image_bot_type"]

            knowledge_item = self._find_chat_model(chat_models, local_config.get("knowledge_model_id", active_id))
            if knowledge_item:
                provider = knowledge_item.get("provider", "")
                key_field, _base_key = self._provider_secret_keys(provider)
                local_config["knowledge_model"] = knowledge_item.get("model", "")
                local_config["knowledge_bot_type"] = self._runtime_bot_type_for_model(knowledge_item)
                applied["knowledge_model"] = local_config["knowledge_model"]
                applied["knowledge_bot_type"] = local_config["knowledge_bot_type"]
                if local_config["knowledge_bot_type"] == "custom":
                    provider_key = knowledge_item.get("api_key") or (local_config.get(key_field, "") if key_field else "")
                    if provider_key:
                        local_config["knowledge_api_key"] = provider_key
                        applied["knowledge_api_key"] = provider_key
                    if knowledge_item.get("api_base"):
                        local_config["knowledge_api_base"] = knowledge_item["api_base"]
                        applied["knowledge_api_base"] = knowledge_item["api_base"]

            if not applied:
                return json.dumps({"status": "error", "message": "no valid keys to update"})

            config_path = get_config_path()
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8-sig") as f:
                    file_cfg = json.load(f)
            else:
                file_cfg = {}
            file_cfg.update(applied)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(file_cfg, f, indent=4, ensure_ascii=False)

            logger.info(f"[WebChannel] Config updated: {list(applied.keys())}")

            # Reset Bridge so that bot routing reflects the new config.
            # Without this, Bridge keeps its cached bot instance (e.g. LinkAIBot)
            # even after the user switches bot_type / use_linkai / model in UI.
            bridge_routing_keys = {"bot_type", "use_linkai", "model", "review_bot_type", "review_model", "knowledge_bot_type", "knowledge_model", "ai_chat_models", "active_chat_model_id"}
            if any(k in applied for k in bridge_routing_keys):
                try:
                    from bridge.bridge import Bridge
                    Bridge().reset_bot()
                    logger.info("[WebChannel] Bridge bot routing reset due to config change")
                except Exception as reset_err:
                    logger.warning(f"[WebChannel] Failed to reset bridge: {reset_err}")

            workspace_keys = {"active_workspace", "workspace_dir", "system_workspace", "workspace_split_enabled", "textbooks_storage_dir"}
            if any(k in applied for k in workspace_keys):
                from common.app_paths import ensure_active_workspace, ensure_system_dir
                ensure_active_workspace()
                ensure_system_dir()
                reset_workspace_dependent_singletons()

            log_keys = {"log_dir", "log_file", "log_max_bytes", "log_backup_count"}
            if any(k in applied for k in log_keys):
                from common.log import configure_logging
                configure_logging(local_config)

            return json.dumps({"status": "success", "applied": applied}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error updating config: {e}")
            return json.dumps({"status": "error", "message": str(e)})
