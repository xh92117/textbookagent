import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import config
from agent.protocol.agent import Agent


def test_context_window_and_reserve_can_be_configured(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_model_context_window": 120000,
        "agent_context_reserve_tokens": 12000,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="deepseek-v4-pro"))

    assert agent._get_model_context_window() == 120000
    assert agent._get_context_reserve_tokens() == 12000


def test_deepseek_default_reserve_is_not_overly_conservative(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_model_context_window": 0,
        "agent_context_reserve_tokens": 0,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="deepseek-v4-pro"))

    assert agent._get_model_context_window() == 64000
    assert agent._get_context_reserve_tokens() == 6400
