import json

from config import Config


def test_app_paths_default_to_legacy_workspace(monkeypatch, tmp_path):
    import config as config_module
    from common import app_paths

    cfg = Config({
        "agent_workspace": str(tmp_path / "legacy"),
        "workspace_split_enabled": True,
    })
    monkeypatch.setattr(config_module, "config", cfg)

    assert app_paths.active_workspace() == str(tmp_path / "legacy")
    assert app_paths.system_root() == str(tmp_path / "legacy")
    assert app_paths.system_dir() == str(tmp_path / "legacy" / "system")
    assert app_paths.textbooks_dir() == str(tmp_path / "legacy" / "textbooks")
    assert app_paths.knowledge_dir() == str(tmp_path / "legacy" / "knowledge")


def test_app_paths_support_selected_business_workspace(monkeypatch, tmp_path):
    import config as config_module
    from common import app_paths

    cfg = Config({
        "agent_workspace": str(tmp_path / "system-root"),
        "active_workspace": str(tmp_path / "business-workspace"),
        "workspace_split_enabled": True,
    })
    monkeypatch.setattr(config_module, "config", cfg)

    workspace = app_paths.ensure_active_workspace()
    system = app_paths.ensure_system_dir()

    assert workspace == str(tmp_path / "business-workspace")
    assert (tmp_path / "business-workspace" / "textbooks").exists()
    assert (tmp_path / "business-workspace" / "knowledge").exists()
    assert (tmp_path / "business-workspace" / "workspace.json").exists()
    assert system == str(tmp_path / "system-root" / "system")
    assert (tmp_path / "system-root" / "system" / "memory").exists()


def test_config_user_datas_use_json(monkeypatch, tmp_path):
    import config as config_module

    cfg = Config({"agent_workspace": str(tmp_path), "workspace_split_enabled": True})
    monkeypatch.setattr(config_module, "config", cfg)
    cfg.user_datas = {"user1": {"role": "teacher"}}
    cfg.save_user_datas()

    data_path = tmp_path / "system" / "user_datas.json"
    assert data_path.exists()
    assert json.loads(data_path.read_text(encoding="utf-8"))["user1"]["role"] == "teacher"

    cfg.user_datas = {}
    cfg.load_user_datas()
    assert cfg.user_datas["user1"]["role"] == "teacher"


def test_parse_env_value_does_not_eval_code():
    from config import _parse_env_value

    assert _parse_env_value("true") is True
    assert _parse_env_value("123") == 123
    assert _parse_env_value('["a", "b"]') == ["a", "b"]
    dangerous = "__import__('os').system('echo unsafe')"
    assert _parse_env_value(dangerous) == dangerous


def test_textbook_memory_manager_distinguishes_workspace_root(tmp_path):
    from agent.textbook.state.manager import TextbookMemoryManager

    workspace = tmp_path / "business"
    manager = TextbookMemoryManager(str(workspace / "textbooks"))

    assert manager.workspace_dir == str(workspace / "textbooks")
    assert manager.textbooks_dir == str(workspace / "textbooks")
    assert manager.workspace_root == str(workspace)
    assert manager._get_book_dir("tb") == str(workspace / "textbooks" / "tb")
