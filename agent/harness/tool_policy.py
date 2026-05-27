from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Dict

from common.app_paths import ensure_system_dir
from common.log import logger


DEFAULT_TOOL_POLICY: Dict[str, Any] = {
    "version": "tool-policy-v1",
    "purpose": "Project-level guardrails for tool choice, writes, destructive operations, and verification.",
    "preferred_tools": {
        "create_textbook": "Create textbook projects through the canonical bridge so textbook.json is always written.",
        "textbook_outline": "Read and write textbook outlines and terminology through canonical outline files.",
        "textbook_chapter": "Read, write, append, replace, and mark textbook chapters while preserving metadata.",
        "memory_search": "Search system memory before answering history-dependent questions.",
        "memory_get": "Read known memory paths from the unified system memory directory.",
        "knowledge_query": "Retrieve reusable evidence from the structured knowledge base.",
        "knowledge_capture": "Save durable, reusable knowledge after value and boundary checks.",
        "env_config": "Update model and skill configuration through the supported configuration path.",
    },
    "write_rules": [
        "Inspect existing content before modifying generated textbook artifacts.",
        "Use append or targeted replace for chapter edits unless the user explicitly asks for full regeneration.",
        "Preserve a snapshot, checkpoint, or version when replacing outlines, reviewed chapters, exports, memory, or skills.",
        "Do not create or maintain workspace-level memory folders; agent memory belongs under system/memory.",
        "Do not restore the manually deleted 项目分析 folder unless the user explicitly requests that exact recovery.",
    ],
    "confirmation_required": [
        "Recursive delete or broad cleanup.",
        "Overwriting completed chapters or reviewed outlines.",
        "Deleting user-uploaded skills, assets, exports, or knowledge sources.",
        "Changing global model provider settings for all sessions.",
    ],
    "textbook_generation_rules": [
        "Load WritingSpec and the active textbook harness before writing or reviewing textbook content.",
        "All code snippets in generated textbook content must be fenced code blocks.",
        "Favor the current textbook's audience and use case over a fixed global writing template.",
        "Generated visuals must be real diagrams, charts, or illustrative assets, not prompt text placed inside an image.",
    ],
    "completion_checks": [
        "Run focused tests or compile checks for backend changes.",
        "Run browser checks for frontend changes when a local page is available.",
        "For export or document fixes, inspect or generate the affected export when feasible.",
        "Report skipped verification explicitly.",
    ],
}


def _policy_path() -> str:
    return os.path.join(ensure_system_dir(), "harness", "tool_policy.json")


def ensure_tool_policy() -> str:
    """Ensure the system-level tool policy exists and return its path."""
    path = _policy_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_TOOL_POLICY, f, ensure_ascii=False, indent=2)
        return path

    try:
        with open(path, "r", encoding="utf-8") as f:
            current = json.load(f)
        merged = _merge_defaults(current, DEFAULT_TOOL_POLICY)
        if merged != current:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"[Harness] Failed to read tool policy, rewriting default: {exc}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_TOOL_POLICY, f, ensure_ascii=False, indent=2)
    return path


def _merge_defaults(current: Any, default: Any) -> Any:
    if isinstance(current, dict) and isinstance(default, dict):
        merged = deepcopy(current)
        for key, value in default.items():
            merged[key] = _merge_defaults(merged.get(key), value) if key in merged else deepcopy(value)
        return merged
    if current is None:
        return deepcopy(default)
    return current


def load_tool_policy() -> Dict[str, Any]:
    path = ensure_tool_policy()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else deepcopy(DEFAULT_TOOL_POLICY)


def format_tool_policy_for_prompt(max_items: int = 6) -> str:
    """Return a compact prompt section for the active tool policy."""
    try:
        policy = load_tool_policy()
    except Exception as exc:
        logger.debug(f"[Harness] Tool policy prompt skipped: {exc}")
        return ""

    lines = [
        "## Harness Tool Policy",
        "",
        f"Policy file: `{_policy_path()}`",
        "",
        "Preferred tool routing:",
    ]
    preferred = policy.get("preferred_tools") or {}
    for name, desc in list(preferred.items())[:max_items]:
        lines.append(f"- `{name}`: {desc}")

    for title, key in [
        ("Write rules", "write_rules"),
        ("Confirmation required", "confirmation_required"),
        ("Textbook generation rules", "textbook_generation_rules"),
        ("Completion checks", "completion_checks"),
    ]:
        values = policy.get(key) or []
        if not values:
            continue
        lines.extend(["", f"{title}:"])
        for value in values[:max_items]:
            lines.append(f"- {value}")

    return "\n".join(lines).strip()
