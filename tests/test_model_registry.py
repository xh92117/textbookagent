from models.model_registry import ModelRegistry


def test_model_registry_resolves_role_model_instances():
    cfg = {
        "ai_chat_models": [
            {
                "id": "chat",
                "name": "GLM via DashScope compatible",
                "provider": "dashscope",
                "model": "glm-5",
                "api_base": "https://coding.dashscope.aliyuncs.com/v1",
            },
            {
                "id": "review",
                "name": "DeepSeek reviewer",
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "api_base": "https://api.deepseek.com/v1",
            },
            {
                "id": "image",
                "name": "Qwen Image",
                "provider": "dashscope",
                "model": "qwen-image-2.0-pro",
                "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            },
        ],
        "active_chat_model_id": "chat",
        "review_model_id": "review",
        "image_model_id": "image",
        "dashscope_api_key": "dash-key",
        "deepseek_api_key": "deepseek-key",
        "dashscope_api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "deepseek_api_base": "https://api.deepseek.com/v1",
    }

    registry = ModelRegistry(cfg)

    chat = registry.resolve("chat")
    assert chat.model == "glm-5"
    assert chat.api_key == "dash-key"
    assert chat.runtime_bot_type == "custom"

    review = registry.resolve("review")
    assert review.model == "deepseek-v4-pro"
    assert review.api_key == "deepseek-key"
    assert review.runtime_bot_type == "deepseek"

    image = registry.resolve("image")
    assert image.model == "qwen-image-2.0-pro"
    assert image.api_key == "dash-key"
    assert "image" in image.capabilities


def test_model_registry_legacy_fallback():
    cfg = {
        "model": "gpt-4o",
        "bot_type": "openai",
        "open_ai_api_key": "openai-key",
        "open_ai_api_base": "https://api.openai.com/v1",
    }

    profile = ModelRegistry(cfg).resolve("writer")

    assert profile.model == "gpt-4o"
    assert profile.api_key == "openai-key"
    assert profile.runtime_bot_type == "chatGPT"


def test_missing_role_model_id_does_not_silently_use_first_model():
    registry = ModelRegistry({
        "ai_chat_models": [
            {"id": "chat", "provider": "dashscope", "model": "qwen-plus"},
        ],
        "review_model_id": "missing-review",
        "dashscope_api_key": "dash-key",
    })

    profile = registry.resolve("review")

    assert profile.id == "missing-review"
    assert profile.configured is False
    assert profile.model == ""
