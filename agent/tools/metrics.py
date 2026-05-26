from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class ToolBudget:
    mode: str
    task_type: str
    max_calls: int
    total_calls: int = 0
    label_counts: Dict[str, int] = field(default_factory=dict)
    tool_counts: Dict[str, int] = field(default_factory=dict)
    over_budget_calls: int = 0

    def record(self, tool_name: str, usefulness_label: str) -> Dict[str, Any]:
        self.total_calls += 1
        self.label_counts[usefulness_label] = self.label_counts.get(usefulness_label, 0) + 1
        self.tool_counts[tool_name] = self.tool_counts.get(tool_name, 0) + 1
        over_budget = self.total_calls > self.max_calls
        if over_budget:
            self.over_budget_calls += 1
        return {
            "budget_max_calls": self.max_calls,
            "budget_total_calls": self.total_calls,
            "over_budget": over_budget,
        }


def default_tool_budget(mode: str, task_type: str) -> ToolBudget:
    normalized_mode = mode or "guided"
    normalized_task = task_type or "general"
    if normalized_mode == "free":
        max_calls = 1
    elif normalized_mode == "strict":
        max_calls = 5
    else:
        max_calls = 6
    if normalized_task == "research":
        max_calls = max(max_calls, 10)
    elif normalized_task in {"frontend", "file_edit"}:
        max_calls = max(max_calls, 8)
    return ToolBudget(mode=normalized_mode, task_type=normalized_task, max_calls=max_calls)


def classify_tool_use(tool_name: str, status: str, repeat_count: int = 0) -> str:
    """Return a coarse usefulness label for first-pass tool governance."""
    normalized = (status or "").lower()
    if normalized == "blocked":
        return "blocked"
    if normalized not in {"success", "ok"}:
        return "failed"
    if repeat_count >= 2:
        return "waste"
    if tool_name in {"read", "ls", "web_fetch", "memory_search", "knowledge_query"}:
        return "support"
    return "hit"


def record_tool_metric(payload: Dict[str, Any], root_dir: str = "") -> Path:
    """Append one tool metric event to JSONL and return the written path."""
    if root_dir:
        base = Path(root_dir)
    else:
        from common.app_paths import ensure_system_dir

        base = Path(ensure_system_dir()) / "harness"
    base.mkdir(parents=True, exist_ok=True)
    path = base / "tool_metrics.jsonl"
    event = {
        "timestamp": time.time(),
        **(payload or {}),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return path
