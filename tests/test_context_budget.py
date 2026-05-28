import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import config
from agent.prompt.builder import ContextFile, PromptBuilder
from agent.prompt.context_metrics import build_prompt_metrics
from agent.protocol.agent import Agent
from agent.protocol.agent_stream import AgentStreamExecutor
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


def test_runtime_context_board_unifies_route_short_term_and_task_state(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_model_context_window": 120000,
        "agent_context_reserve_tokens": 12000,
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
            "content": [{"type": "text", "text": "write chapter"}],
        }],
    )
    executor.tool_route = SimpleNamespace(prompt="[System: Tool routing policy]\nVisible tools for this turn: read")
    executor.short_term_memory = SimpleNamespace(
        compact_prompt=lambda max_events=12: "[System: Short-term working memory]\ncurrent_goal: write chapter"
    )

    turns = executor._identify_complete_turns()
    executor._inject_runtime_context_board(turns, reason="test")
    text = executor.messages[0]["content"][0]["text"]

    assert "[System: Runtime Context Board]" in text
    assert "## Tool Route" in text
    assert "## Short-Term State" in text
    assert "## Task Checkpoint" in text
    assert "[System: Tool routing policy]" not in text
    assert "[System: Short-term working memory]" not in text
    assert len(text.split("\n\n---\n\n", 1)[0]) <= 2400


def test_context_diagnostics_reports_runtime_context_and_tool_results(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_model_context_window": 120000,
        "agent_context_reserve_tokens": 12000,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="demo"))
    executor = AgentStreamExecutor(
        agent=agent,
        model=agent.model,
        system_prompt="SYSTEM_MEMORY_BOOTSTRAP.md\nsystem",
        tools=[],
        messages=[
            {
                "role": "user",
                "content": [{"type": "text", "text": "[System: Runtime Context Board]\nstate\n\n---\n\nhello"}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "[current tool result compacted] data"}],
            },
        ],
    )

    diag = executor.context_diagnostics()

    assert diag["message_count"] == 2
    assert diag["runtime_board_chars"] > 0
    assert diag["tool_result_chars"] > 0
    assert diag["compressed_blocks"] == 1
    assert diag["memory_bootstrap_loaded"] is True


def test_prompt_builder_reports_section_diagnostics_and_clips_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "config", config.Config({
        "knowledge": False,
        "agent_prompt_section_budgets": {
            "context_files": 900,
            "workspace": 1200,
        },
    }))
    builder = PromptBuilder(workspace_dir=str(tmp_path), language="zh")

    result = builder.build_with_diagnostics(
        tools=[],
        context_files=[
            ContextFile(path="AGENT.md", content="agent rules\n" + ("A" * 2000)),
            ContextFile(path="RULE.md", content="workspace rules\n" + ("B" * 2000)),
        ],
        skill_filter=[],
    )

    prompt = result.prompt
    sections = {item["name"]: item for item in result.diagnostics["sections"]}

    assert len(prompt) < 3500
    assert sections["context_files"]["clipped"] is True
    assert sections["context_files"]["chars"] <= 900
    assert result.diagnostics["total_chars"] == len(prompt)
    assert "available_skills" not in prompt


def test_context_summary_callback_is_structured_and_marks_verification(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_model_context_window": 120000,
        "agent_context_reserve_tokens": 12000,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="demo"))
    executor = AgentStreamExecutor(
        agent=agent,
        model=agent.model,
        system_prompt="system",
        tools=[],
        messages=[],
    )

    callback = executor._build_context_summary_callback(
        discarded_turns=[{"messages": [{"role": "user", "content": [{"type": "text", "text": "old request"}]}]}],
        kept_turns=[{"messages": [{"role": "user", "content": [{"type": "text", "text": "new request"}]}]}],
    )
    callback("User asked for chapter 1. Assistant drafted outline.")

    injected = executor.messages[-1]["content"][0]["text"]

    assert "[Compacted Context Summary]" in injected
    assert "source_turns:" in injected
    assert "confirmed_facts:" in injected
    assert "must_verify_before_use:" in injected
    assert "User asked for chapter 1" in injected


def test_context_summary_handoff_file_contains_todo_and_is_injected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "system_workspace": str(tmp_path / "system"),
        "workspace_split_enabled": True,
        "agent_model_context_window": 120000,
        "agent_context_reserve_tokens": 12000,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="demo", session_id="session-a"))
    executor = AgentStreamExecutor(
        agent=agent,
        model=agent.model,
        system_prompt="system",
        tools=[],
        messages=[{
            "role": "user",
            "content": [{"type": "text", "text": "修复第3章审查意见的前两个问题"}],
        }],
    )
    discarded_turns = [{
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "审查第三章"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "已给出第三章审查意见：1. 修复代码截断 2. 补全3.5.7 3. 字数偏多"}]},
        ]
    }]
    kept_turns = executor._identify_complete_turns()

    handoff = executor._persist_context_handoff(discarded_turns, kept_turns, reason="trim")
    executor._inject_context_handoff_summary(handoff)

    handoff_text = handoff["content"]
    injected = executor.messages[0]["content"][0]["text"]

    assert "## Current Done" in handoff_text
    assert "## Todo" in handoff_text
    assert "Todo:" in injected
    assert str(handoff["path"]) in injected


def test_near_max_turn_persists_resume_handoff_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "system_workspace": str(tmp_path / "system"),
        "workspace_split_enabled": True,
        "agent_model_context_window": 120000,
        "agent_context_reserve_tokens": 12000,
    }))
    events = []
    agent = Agent(system_prompt="", model=SimpleNamespace(model="demo", session_id="session-a"))
    executor = AgentStreamExecutor(
        agent=agent,
        model=agent.model,
        system_prompt="system",
        tools=[],
        max_turns=50,
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "继续修复第六章前两个问题"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "已完成第六章审查，正在修复问题1。下一步：修复问题2并验证章节。"}]},
        ],
        on_event=lambda event: events.append(event),
    )

    handoff = executor._maybe_persist_near_max_turn_handoff(
        turn=49,
        final_response="已完成第六章审查，正在修复问题1。",
        tool_calls=[{"name": "textbook_chapter", "arguments": {"action": "replace_exact"}}],
    )

    content = handoff["content"]

    assert handoff["reason"] == "near-max-turn"
    assert "## Todo" in content
    assert "继续下一轮对话" in content
    assert "修复问题2并验证章节" in content
    assert any(event["type"] == "session_handoff_saved" for event in events)


def test_default_context_and_tool_noise_thresholds_are_tighter():
    assert config.available_setting["agent_context_compress_ratio"] <= 0.7
    assert config.available_setting["agent_context_midrun_trim_ratio"] <= 0.8
    assert config.available_setting["agent_current_tool_result_context_chars"] <= 5000
    assert config.available_setting["agent_historical_tool_result_context_chars"] <= 1500
    assert config.available_setting["agent_tool_result_context_budgets"]["textbook_chapter"] <= 3000


def test_midrun_tool_result_guard_compacts_current_turn_when_noise_is_high(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_midrun_tool_result_chars": 1000,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="demo"))
    executor = AgentStreamExecutor(
        agent=agent,
        model=agent.model,
        system_prompt="system",
        tools=[],
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "修复第六章"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "read", "input": {"path": "a.md"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "A" * 900}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "read", "input": {"path": "b.md"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "B" * 900}]},
        ],
    )

    before = executor._total_tool_result_chars()
    changed = executor._compress_current_turn_tool_results_if_needed()
    after = executor._total_tool_result_chars()

    assert before > 1000
    assert changed is True
    assert after < before
    assert executor.messages[-1]["content"][0]["content"] == "B" * 900


def test_final_response_compacts_tool_results_for_history(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_historical_tool_result_context_chars": 900,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="demo"))
    executor = AgentStreamExecutor(
        agent=agent,
        model=agent.model,
        system_prompt="system",
        tools=[],
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "审查第六章"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "read", "input": {"path": "chapter_006.md"}}]},
            {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "# 第六章\n\n" + ("RAW_CHAPTER_BODY " * 2000),
                }],
            },
        ],
    )

    changed = executor._compact_tool_results_after_final_response()
    stored = executor.messages[-1]["content"][0]["content"]

    assert changed is True
    assert "historical read result summarized" in stored
    assert "chapter_006.md" in stored
    assert "RAW_CHAPTER_BODY" not in stored


def test_prompt_metrics_expose_quantifiable_acceptance(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "config", config.Config({"knowledge": False}))
    (tmp_path / "AGENT.md").write_text("agent", encoding="utf-8")
    (tmp_path / "RULE.md").write_text("rule", encoding="utf-8")

    metrics = build_prompt_metrics(str(tmp_path), skill_filter=[])

    assert metrics["total_chars"] > 0
    assert metrics["estimated_tokens"] > 0
    assert metrics["has_available_skills"] is False
    assert metrics["acceptance"]["prompt_chars_under_12000"] is True
    assert metrics["acceptance"]["no_skill_route_hides_available_skills"] is True


def test_prompt_builder_applies_default_section_budgets(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "config", config.Config({"knowledge": False}))
    builder = PromptBuilder(workspace_dir=str(tmp_path), language="zh")

    result = builder.build_with_diagnostics(
        context_files=[
            ContextFile(path="AGENT.md", content="agent\n" + ("A" * 6000)),
            ContextFile(path="RULE.md", content="rule\n" + ("B" * 6000)),
        ],
    )
    sections = {item["name"]: item for item in result.diagnostics["sections"]}

    assert sections["context_files"]["budget_chars"] == 4000
    assert sections["context_files"]["clipped"] is True
    assert sections["context_files"]["chars"] <= 4000


def test_context_compression_debounce_is_reported(monkeypatch):
    monkeypatch.setattr(config, "config", config.Config({
        "agent_model_context_window": 120000,
        "agent_context_reserve_tokens": 12000,
        "agent_context_compression_debounce_limit": 2,
    }))
    agent = Agent(system_prompt="", model=SimpleNamespace(model="demo"))
    executor = AgentStreamExecutor(
        agent=agent,
        model=agent.model,
        system_prompt="system",
        tools=[],
        messages=[],
    )

    executor._record_context_compression("tool_results", saved_chars=100)
    executor._record_context_compression("turn_summary", saved_chars=200)

    diag = executor.context_diagnostics()

    assert diag["recent_compression_count"] == 2
    assert diag["compression_debounce_active"] is True
    assert diag["last_compression_kind"] == "turn_summary"
