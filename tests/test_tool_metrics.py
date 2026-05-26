import json

from agent.tools.metrics import ToolBudget, classify_tool_use, default_tool_budget, record_tool_metric


def test_classify_tool_use_marks_blocked_and_failed_calls():
    assert classify_tool_use("web_fetch", "blocked", repeat_count=0) == "blocked"
    assert classify_tool_use("read", "error", repeat_count=0) == "failed"


def test_classify_tool_use_marks_repeated_success_as_waste():
    assert classify_tool_use("read", "success", repeat_count=2) == "waste"


def test_record_tool_metric_writes_jsonl(tmp_path):
    path = record_tool_metric(
        {
            "tool_name": "read",
            "status": "success",
            "route_mode": "free",
            "usefulness_label": "support",
        },
        root_dir=str(tmp_path),
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["tool_name"] == "read"
    assert payload["usefulness_label"] == "support"


def test_default_tool_budget_is_tighter_for_free_than_guided():
    free = default_tool_budget("free", "general")
    guided = default_tool_budget("guided", "frontend")

    assert free.max_calls < guided.max_calls
    assert free.mode == "free"
    assert guided.task_type == "frontend"


def test_tool_budget_tracks_counts_and_soft_excess():
    budget = ToolBudget(mode="free", task_type="general", max_calls=1)

    first = budget.record("read", "support")
    second = budget.record("bash", "hit")

    assert first["over_budget"] is False
    assert second["over_budget"] is True
    assert budget.total_calls == 2
    assert budget.label_counts["hit"] == 1
