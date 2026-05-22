import inspect
import json

from channel.web.web.routes import get_urls
import channel.web.web.web_channel as web_channel
from channel.web.web import handlers_admin, handlers_channels, handlers_config, handlers_core
from channel.web.web import handlers_knowledge, handlers_textbook


def _route_handler_names():
    urls = get_urls()
    return [urls[i + 1] for i in range(0, len(urls), 2)]


def test_all_route_handlers_are_imported_into_web_channel_namespace():
    missing = [name for name in _route_handler_names() if not hasattr(web_channel, name)]
    assert missing == []


def test_route_handler_names_are_unique():
    names = _route_handler_names()
    assert len(names) == len(set(names))


def test_web_handler_modules_do_not_redefine_shared_wrappers():
    modules = [
        handlers_admin,
        handlers_channels,
        handlers_config,
        handlers_core,
        handlers_knowledge,
        handlers_textbook,
    ]
    forbidden = {"_require_auth", "_get_config_path", "_get_workspace_root"}
    for module in modules:
        defined = {
            name
            for name, value in vars(module).items()
            if inspect.isfunction(value) and value.__module__ == module.__name__
        }
        assert not (defined & forbidden), f"{module.__name__} defines {defined & forbidden}"


def test_web_channel_refuses_public_unauthenticated_console(monkeypatch):
    monkeypatch.setattr(
        web_channel,
        "conf",
        lambda: {
            "web_port": 9899,
            "web_host": "0.0.0.0",
            "web_password": "",
            "web_require_password_on_public_host": True,
        },
    )

    channel = web_channel.WebChannel()
    try:
        channel.startup()
    except RuntimeError as exc:
        assert "unauthenticated public web console" in str(exc)
    else:
        raise AssertionError("startup should reject public unauthenticated console")


def test_config_handler_can_switch_active_chat_model(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "ai_chat_models": [
            {"id": "m1", "name": "Model 1", "provider": "deepseek", "model": "deepseek-chat"},
            {"id": "m2", "name": "Model 2", "provider": "deepseek", "model": "deepseek-reasoner"},
        ],
        "active_chat_model_id": "m1",
    }, ensure_ascii=False), encoding="utf-8-sig")
    local_config = {
        "ai_chat_models": [
            {"id": "m1", "name": "Model 1", "provider": "deepseek", "model": "deepseek-chat"},
            {"id": "m2", "name": "Model 2", "provider": "deepseek", "model": "deepseek-reasoner"},
        ],
        "active_chat_model_id": "m1",
    }

    monkeypatch.setattr(handlers_config, "require_auth", lambda: None)
    monkeypatch.setattr(handlers_config, "conf", lambda: local_config)
    monkeypatch.setattr(handlers_config, "get_config_path", lambda: str(config_path))
    monkeypatch.setattr(handlers_config.web, "data", lambda: json.dumps({"updates": {"active_chat_model_id": "m2"}}).encode("utf-8"))
    monkeypatch.setattr(handlers_config.web, "header", lambda *args, **kwargs: None)

    response = json.loads(handlers_config.ConfigHandler().POST())
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert response["status"] == "success"
    assert response["applied"]["active_chat_model_id"] == "m2"
    assert response["applied"]["model"] == "deepseek-reasoner"
    assert saved["active_chat_model_id"] == "m2"
    assert saved["model"] == "deepseek-reasoner"
