"""Unified model profile resolution for chat, review, image, and knowledge roles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ModelProfile:
    role: str
    id: str
    name: str
    provider: str
    model: str
    api_key: str
    api_base: str
    runtime_bot_type: str
    capabilities: List[str]

    @property
    def configured(self) -> bool:
        return bool(self.model and self.api_key)


class ModelRegistry:
    """Resolve model instances from config without coupling callers to providers.

    The UI stores configured model instances in ``ai_chat_models`` and role
    selectors reference those instances by id. Legacy fields are still honored
    as fallbacks so older config files continue to run.
    """

    PROVIDER_KEYS = {
        "openai": ("open_ai_api_key", "open_ai_api_base"),
        "chatGPT": ("open_ai_api_key", "open_ai_api_base"),
        "deepseek": ("deepseek_api_key", "deepseek_api_base"),
        "dashscope": ("dashscope_api_key", "dashscope_api_base"),
        "claudeAPI": ("claude_api_key", "claude_api_base"),
        "claude": ("claude_api_key", "claude_api_base"),
        "gemini": ("gemini_api_key", "gemini_api_base"),
        "zhipu": ("zhipu_ai_api_key", "zhipu_ai_api_base"),
        "qianfan": ("qianfan_api_key", "qianfan_api_base"),
        "moonshot": ("moonshot_api_key", "moonshot_base_url"),
        "doubao": ("ark_api_key", "ark_base_url"),
        "modelscope": ("modelscope_api_key", "modelscope_base_url"),
        "linkai": ("linkai_api_key", "linkai_api_base"),
        "custom": ("custom_api_key", "custom_api_base"),
    }

    ROLE_ID_KEYS = {
        "chat": "active_chat_model_id",
        "writer": "active_chat_model_id",
        "review": "review_model_id",
        "image": "image_model_id",
        "knowledge": "knowledge_model_id",
    }

    ROLE_MODEL_KEYS = {
        "chat": ("model", "bot_type"),
        "writer": ("model", "bot_type"),
        "review": ("review_model", "review_bot_type"),
        "image": ("image_model", "image_bot_type"),
        "knowledge": ("knowledge_model", "knowledge_bot_type"),
    }

    DEFAULT_BASES = {
        "openai": "https://api.openai.com/v1",
        "chatGPT": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "claudeAPI": "https://api.anthropic.com/v1",
        "claude": "https://api.anthropic.com/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "qianfan": "https://qianfan.baidubce.com/v2",
        "moonshot": "https://api.moonshot.cn/v1",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
        "open_ai": "https://api.openai.com/v1",
        "custom": "https://api.openai.com/v1",
    }

    def __init__(self, config: Dict[str, Any] | None = None):
        if config is None:
            from config import conf

            config = conf()
        self.config = config

    def resolve(self, role: str = "chat") -> ModelProfile:
        role = role or "chat"
        selected = self._selected_model_item(role)
        if selected:
            return self._profile_from_item(role, selected)
        return self._profile_from_legacy(role)

    def _chat_models(self) -> List[dict]:
        models = self.config.get("ai_chat_models", [])
        return [m for m in models if isinstance(m, dict)]

    def _selected_model_item(self, role: str) -> dict:
        models = self._chat_models()
        if not models:
            return {}
        model_id = self.config.get(self.ROLE_ID_KEYS.get(role, "active_chat_model_id"), "")
        if not model_id and role != "chat":
            model_id = self.config.get("active_chat_model_id", "")
        for item in models:
            if item.get("id") == model_id:
                return item
        if model_id:
            return {
                "id": model_id,
                "name": "",
                "provider": "",
                "model": "",
                "api_base": "",
                "_error": f"Configured model id '{model_id}' for role '{role}' was not found",
            }
        return models[0]

    def _profile_from_item(self, role: str, item: dict) -> ModelProfile:
        provider = item.get("provider") or "custom"
        model = item.get("model") or item.get("name") or ""
        api_key = item.get("api_key") or self._provider_value(provider, 0)
        api_base = item.get("api_base") or self._provider_value(provider, 1) or self.DEFAULT_BASES.get(provider, "")
        runtime_bot_type = self._runtime_bot_type(provider, api_base)
        return ModelProfile(
            role=role,
            id=item.get("id", ""),
            name=item.get("name") or model,
            provider=provider,
            model=model,
            api_key=api_key,
            api_base=(api_base or "").rstrip("/"),
            runtime_bot_type=runtime_bot_type,
            capabilities=self._infer_capabilities(provider, model),
        )

    def _profile_from_legacy(self, role: str) -> ModelProfile:
        model_key, bot_key = self.ROLE_MODEL_KEYS.get(role, self.ROLE_MODEL_KEYS["chat"])
        model = self.config.get(model_key) or self.config.get("model", "")
        provider = self.config.get(bot_key) or self.config.get("bot_type", "") or "custom"
        provider = "openai" if provider == "chatGPT" else provider
        api_key = self.config.get(f"{role}_api_key", "") or self._provider_value(provider, 0)
        api_base = self.config.get(f"{role}_api_base", "") or self._provider_value(provider, 1) or self.DEFAULT_BASES.get(provider, "")
        return ModelProfile(
            role=role,
            id="legacy",
            name=model,
            provider=provider,
            model=model,
            api_key=api_key,
            api_base=(api_base or "").rstrip("/"),
            runtime_bot_type=self._runtime_bot_type(provider, api_base),
            capabilities=self._infer_capabilities(provider, model),
        )

    def _provider_value(self, provider: str, index: int) -> str:
        keys = self.PROVIDER_KEYS.get(provider) or self.PROVIDER_KEYS.get("custom")
        return self.config.get(keys[index], "") if keys else ""

    @staticmethod
    def _runtime_bot_type(provider: str, api_base: str) -> str:
        provider = provider or "custom"
        if provider == "openai":
            return "chatGPT"
        if provider == "dashscope":
            base = (api_base or "").lower()
            if base and not (
                base.startswith("https://dashscope.aliyuncs.com")
                or base.startswith("https://dashscope-intl.aliyuncs.com")
            ):
                return "custom"
        return provider

    @staticmethod
    def _infer_capabilities(provider: str, model: str) -> List[str]:
        text = f"{provider} {model}".lower()
        caps = ["chat"]
        if any(k in text for k in ("image", "dall-e", "wanx", "qwen-image")):
            caps.append("image")
        if any(k in text for k in ("vl", "vision", "omni", "qwen3.5", "qwen3.6")):
            caps.append("vision")
        if any(k in text for k in ("reason", "r1", "deepseek-v4")):
            caps.append("reasoning")
        return caps
