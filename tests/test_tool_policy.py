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


def test_record_tool_metric_event_updates_soft_budget(monkeypatch):
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

    executor._record_tool_metric_event("read", {"path": "a.md"}, {"status": "success", "result": "ok"})
    executor._record_tool_metric_event("bash", {"command": "echo ok"}, {"status": "success", "result": "ok"})

    assert captured[0]["over_budget"] is False
    assert captured[1]["over_budget"] is True


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
