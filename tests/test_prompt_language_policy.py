import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from agent.prompt.builder import build_agent_system_prompt
from agent.protocol.agent import Agent
from agent.protocol.agent_stream import AgentStreamExecutor


def test_system_prompt_starts_with_chinese_language_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "config", config.Config({"knowledge": False}))

    prompt = build_agent_system_prompt(str(tmp_path), language="zh")

    assert prompt.startswith("## 回答语言规则")
    assert "默认始终使用简体中文回答用户" in prompt
    assert "Runtime Context Board" in prompt


def test_runtime_context_board_keeps_chinese_reply_guard(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_runtime_board_max_chars": 2400,
        "agent_runtime_board_max_events": 6,
        "short_term_memory_enabled": False,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="demo"))
    executor = AgentStreamExecutor(
        agent=agent,
        model=agent.model,
        system_prompt="system",
        tools=[],
        messages=[{
            "role": "user",
            "content": [{"type": "text", "text": "继续优化"}],
        }],
    )

    board = executor._build_runtime_context_board(
        executor._identify_complete_turns(),
        reason="test",
    )

    assert "User-facing replies must stay in Simplified Chinese" in board
