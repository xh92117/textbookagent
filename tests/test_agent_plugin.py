from pathlib import Path


def test_agent_plugin_default_team_fallback_uses_available_teams_method():
    source = Path("plugins/agent/agent.py").read_text(encoding="utf-8")

    assert "self.configself" not in source
    assert "self.get_available_teams()" in source
