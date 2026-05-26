import config as config_module


def test_env_override_logs_redact_sensitive_values(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPEN_AI_API_KEY", "sk-test-secret")

    info_messages = []
    monkeypatch.setattr(
        config_module.logger,
        "info",
        lambda msg, *args, **kwargs: info_messages.append(str(msg)),
    )
    monkeypatch.setattr(config_module.logger, "debug", lambda *args, **kwargs: None)
    monkeypatch.setattr(config_module.logger, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(config_module, "configure_logging", lambda cfg: None)

    config_module.load_config()

    joined = "\n".join(info_messages)
    assert "sk-test-secret" not in joined
    assert "open_ai_api_key=" in joined
