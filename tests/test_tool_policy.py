from agent.protocol.agent_stream import AgentStreamExecutor


def _executor(route=None):
    executor = object.__new__(AgentStreamExecutor)
    executor.tool_route = route
    return executor


def test_preflight_blocks_web_fetch_search_result_pages():
    executor = _executor()

    result = executor._preflight_tool_policy_check(
        "web_fetch",
        {"url": "https://www.bing.com/search?q=agent+tools"},
    )

    assert result["status"] == "blocked"
    assert "search result pages" in result["result"]


def test_preflight_blocks_bash_chapter_writes_when_textbook_route_is_strict():
    class Route:
        mode = "strict"
        task_type = "textbook"

    executor = _executor(Route())

    result = executor._preflight_tool_policy_check(
        "bash",
        {
            "command": (
                "powershell -Command \"Get-Content tmp.md | "
                "Add-Content -Path textbooks/tb_demo/chapters/chapter_001.md\""
            )
        },
    )

    assert result["status"] == "blocked"
    assert "textbook_chapter" in result["result"]


def test_preflight_blocks_bash_chapter_writes_when_textbook_route_is_repair():
    class Route:
        mode = "repair"
        task_type = "textbook"

    executor = _executor(Route())

    result = executor._preflight_tool_policy_check(
        "bash",
        {
            "command": (
                "powershell -Command \"Get-Content tmp.md | "
                "Add-Content -Path textbooks/tb_demo/chapters/chapter_001.md\""
            )
        },
    )

    assert result["status"] == "blocked"
    assert "repair mode" in result["result"]
    assert "textbook_chapter" in result["result"]


def test_record_tool_metric_event_includes_route_and_repeat_count(monkeypatch):
    captured = []

    def fake_record(payload):
        captured.append(payload)

    monkeypatch.setattr("agent.tools.metrics.record_tool_metric", fake_record)

    class Route:
        mode = "strict"
        task_type = "textbook"

    executor = _executor(Route())
    executor.tool_failure_history = [("read", "same", True), ("read", "same", True)]
    monkeypatch.setattr(executor, "_hash_args", lambda args: "same")

    executor._record_tool_metric_event(
        "read",
        {"path": "demo.md"},
        {"status": "success", "result": "ok", "execution_time": 0.01},
    )

    assert captured[0]["tool_name"] == "read"
    assert captured[0]["route_mode"] == "strict"
    assert captured[0]["task_type"] == "textbook"
    assert captured[0]["repeat_count"] == 2
    assert captured[0]["usefulness_label"] == "waste"


def test_record_tool_metric_event_updates_30_call_soft_budget(monkeypatch):
    captured = []

    def fake_record(payload):
        captured.append(payload)

    monkeypatch.setattr("agent.tools.metrics.record_tool_metric", fake_record)

    class Route:
        mode = "free"
        task_type = "general"

    executor = _executor(Route())
    executor.tool_failure_history = []
    executor.tool_budget = None

    for idx in range(30):
        executor._record_tool_metric_event("read", {"path": f"{idx}.md"}, {"status": "success", "result": "ok"})
    executor._record_tool_metric_event("bash", {"command": "echo ok"}, {"status": "success", "result": "ok"})

    assert captured[0]["over_budget"] is False
    assert captured[29]["over_budget"] is False
    assert captured[30]["over_budget"] is True


def test_execute_tool_blocks_when_budget_is_exhausted(monkeypatch):
    from agent.tools.metrics import ToolBudget

    class Route:
        mode = "repair"
        task_type = "textbook"

    class Tool:
        name = "read"

        def execute_tool(self, _arguments):
            raise AssertionError("tool should not execute after budget exhaustion")

    captured = []
    monkeypatch.setattr("agent.tools.metrics.record_tool_metric", lambda payload: captured.append(payload))

    executor = _executor(Route())
    executor.tools = {"read": Tool()}
    executor.tool_budget = ToolBudget(mode="repair", task_type="textbook", max_calls=6, total_calls=6)
    executor.tool_failure_history = []
    executor.tool_metric_events = []
    executor.on_event = lambda event: None
    executor._record_short_term_tool_start = lambda *args, **kwargs: None
    executor._record_short_term_tool_end = lambda *args, **kwargs: None

    result = executor._execute_tool({
        "id": "t1",
        "name": "read",
        "arguments": {"path": "chapter.md"},
    })

    assert result["status"] == "blocked"
    assert "tool budget" in result["result"].lower()
    assert captured[-1]["usefulness_label"] == "blocked"
    assert executor.tool_budget_exhausted is True


def test_duplicate_segment_read_is_blocked_after_full_chapter_read(monkeypatch):
    class Route:
        mode = "repair"
        task_type = "textbook"

    executor = _executor(Route())
    executor.tool_failure_history = []
    executor.tool_metric_events = []
    executor.tool_budget = None
    executor.on_event = lambda event: None
    executor.tools = {}
    executor._record_short_term_tool_start = lambda *args, **kwargs: None
    executor._record_short_term_tool_end = lambda *args, **kwargs: None
    monkeypatch.setattr("agent.tools.metrics.record_tool_metric", lambda payload: None)

    executor._record_successful_tool_read(
        "textbook_chapter",
        {"action": "read", "book_id": "tb_demo", "chapter_num": 14},
        {
            "book_id": "tb_demo",
            "chapter_num": 14,
            "path": "chapters/chapter_014.md",
            "chars": 23807,
            "content": "# 第14章 Agentic-RL\n\n正文",
        },
    )

    result = executor._execute_tool({
        "id": "t2",
        "name": "read",
        "arguments": {
            "path": "C:\\workspace\\textbooks\\tb_demo\\chapters\\chapter_014.md",
            "offset": 600,
            "limit": 100,
        },
    })

    assert result["status"] == "blocked"
    assert "already been fully read" in result["result"]
    assert result["count_budget"] is False


def test_duplicate_segment_read_does_not_consume_tool_budget(monkeypatch):
    from agent.tools.metrics import ToolBudget

    class Route:
        mode = "repair"
        task_type = "textbook"

    captured = []
    monkeypatch.setattr("agent.tools.metrics.record_tool_metric", lambda payload: captured.append(payload))

    executor = _executor(Route())
    executor.tool_failure_history = []
    executor.tool_metric_events = []
    executor.tool_budget = ToolBudget(mode="repair", task_type="textbook", max_calls=12, total_calls=4)
    executor.on_event = lambda event: None
    executor.tools = {}
    executor._record_short_term_tool_start = lambda *args, **kwargs: None
    executor._record_short_term_tool_end = lambda *args, **kwargs: None

    executor._record_successful_tool_read(
        "textbook_chapter",
        {"action": "read", "book_id": "tb_demo", "chapter_num": 15},
        {
            "book_id": "tb_demo",
            "chapter_num": 15,
            "path": "chapters/chapter_015.md",
            "chars": 1200,
            "content": "# Chapter 15\n\ncontent",
        },
    )

    result = executor._execute_tool({
        "id": "t3",
        "name": "read",
        "arguments": {"path": "C:\\workspace\\textbooks\\tb_demo\\chapters\\chapter_015.md"},
    })

    assert result["status"] == "blocked"
    assert executor.tool_budget.total_calls == 4
    assert captured[-1]["budget_total_calls"] == 4
    assert captured[-1]["over_budget"] is False


def test_budget_block_should_stop_next_llm_turn():
    executor = _executor()
    executor.tool_budget_exhausted = True

    assert executor._should_stop_after_tool_results([
        {"status": "blocked", "result": "Tool budget exhausted for this turn (12/12)."},
    ]) is True


def test_review_stage_closes_tool_phase_after_chapter_and_checklist_evidence():
    executor = _executor()
    executor.tool_budget_exhausted = False
    executor.tool_phase_state = {
        "intent": "chapter_review",
        "chapter_read": True,
        "review_checklist_read": True,
    }

    assert executor._should_close_tool_phase_after_results([
        {"status": "success", "result": "review checklist loaded"},
    ]) is True
    assert executor.tool_phase_stop_reason == "review_evidence_ready"


def test_budget_exhaustion_feedback_is_visible_assistant_message():
    events = []
    executor = _executor()
    executor.on_event = lambda event: events.append(event)
    executor.tool_budget = type("Budget", (), {"total_calls": 8, "max_calls": 8})()
    executor.messages = []

    message = executor._tool_budget_exhausted_final_response([])
    executor._emit_visible_assistant_message(message, stop_reason="tool_budget_exhausted")

    assert [event["type"] for event in events] == ["message_start", "message_update", "message_end"]
    assert events[1]["data"]["delta"] == message
    assert events[2]["data"]["content"] == message
    assert events[2]["data"]["tool_calls"] == []
    assert events[2]["data"]["stop_reason"] == "tool_budget_exhausted"
    assert executor._deterministic_feedback_emitted is True


def test_emit_tool_diagnostics_reports_budget_and_labels():
    events = []
    executor = _executor()
    executor.on_event = lambda event: events.append(event)
    executor.tool_metric_events = [
        {"usefulness_label": "support", "over_budget": False},
        {"usefulness_label": "blocked", "over_budget": True},
    ]

    executor._emit_tool_diagnostics()

    assert events[0]["type"] == "tool_diagnostics"
    data = events[0]["data"]
    assert data["total_calls"] == 2
    assert data["label_counts"]["blocked"] == 1
    assert data["over_budget_calls"] == 1


def test_strict_textbook_route_reports_hidden_tool_as_stop_condition():
    class Route:
        mode = "strict"
        task_type = "textbook"
        required_tools = ["textbook_chapter"]

    class Agent:
        skill_manager = None

    executor = _executor(Route())
    executor.tools = {"read": object(), "textbook_chapter": object(), "memory_search": object()}
    executor.agent = Agent()

    message = executor._build_tool_not_found_message("write")

    assert "not visible in the current strict textbook route" in message
    assert "textbook_chapter" in message
    assert "stop and explain the limitation" in message


def test_repair_textbook_route_reports_hidden_tool_as_stop_condition():
    class Route:
        mode = "repair"
        task_type = "textbook"
        required_tools = ["textbook_chapter"]

    class Agent:
        skill_manager = None

    executor = _executor(Route())
    executor.tools = {"read": object(), "textbook_chapter": object(), "edit": object(), "write": object()}
    executor.agent = Agent()

    message = executor._build_tool_not_found_message("bash")

    assert "current textbook repair route" in message
    assert "textbook_chapter" in message
    assert "never use bash" in message
