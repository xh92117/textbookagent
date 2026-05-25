import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import config
from agent.protocol.agent import Agent
from agent.harness.context_guard import ContextAnxietyGuard


def test_context_window_and_reserve_can_be_configured(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_model_context_window": 120000,
        "agent_context_reserve_tokens": 12000,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="deepseek-v4-pro"))

    assert agent._get_model_context_window() == 120000
    assert agent._get_context_reserve_tokens() == 12000


def test_deepseek_v4_uses_large_context_window(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_model_context_window": 0,
        "agent_context_reserve_tokens": 0,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="deepseek-v4-pro"))

    assert agent._get_model_context_window() == 1000000
    assert agent._get_context_reserve_tokens() == 100000


def test_context_anxiety_guard_writes_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "system_workspace": str(tmp_path),
        "workspace_split_enabled": True,
        "agent_model_context_window": 1000,
        "agent_context_reserve_tokens": 100,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="demo", session_id="s1"))
    executor = SimpleNamespace(
        agent=agent,
        system_prompt="system" * 100,
        messages=[{
            "role": "user",
            "content": [{"type": "text", "text": "中文" * 500}],
        }],
        _effective_context_budget=lambda: (900, 100),
    )

    result = ContextAnxietyGuard(threshold=0.1).maybe_checkpoint(executor, "继续写教材")

    assert result["created"] is True
    assert os.path.exists(result["path"])
    progress = tmp_path / "system" / "harness" / "PROGRESS.md"
    assert progress.exists()
    assert "Context Checkpoint" in progress.read_text(encoding="utf-8")
