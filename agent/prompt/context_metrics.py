"""Quantifiable context-engine metrics for prompt assembly."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from agent.prompt import load_context_files
from agent.prompt.builder import PromptBuilder


def build_prompt_metrics(
    workspace_dir: str,
    tools: List[Any] | None = None,
    skill_manager: Any = None,
    memory_manager: Any = None,
    runtime_info: Dict[str, Any] | None = None,
    skill_filter=None,
) -> Dict[str, Any]:
    """Build section-level prompt metrics without sending anything to a model."""
    context_files = load_context_files(
        workspace_dir,
        files_to_load=["AGENT.md", "USER.md", "RULE.md", "BOOTSTRAP.md"],
    )
    result = PromptBuilder(workspace_dir=workspace_dir, language="zh").build_with_diagnostics(
        tools=tools or [],
        context_files=context_files,
        skill_manager=skill_manager,
        memory_manager=memory_manager,
        runtime_info=runtime_info or {},
        skill_filter=skill_filter,
    )
    diagnostics = dict(result.diagnostics)
    diagnostics["estimated_tokens"] = _estimate_text_tokens(result.prompt)
    diagnostics["has_available_skills"] = "<available_skills>" in result.prompt
    diagnostics["context_file_count"] = len(context_files)
    diagnostics["acceptance"] = {
        "prompt_chars_under_12000": diagnostics["total_chars"] <= 12000,
        "no_skill_route_hides_available_skills": (
            skill_filter != [] or not diagnostics["has_available_skills"]
        ),
        "runtime_sections_are_reported": bool(diagnostics.get("sections")),
    }
    return diagnostics


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    non_ascii = sum(1 for c in text if ord(c) > 127)
    ascii_count = len(text) - non_ascii
    return int(non_ascii * 1.5 + ascii_count * 0.25) + 1


def main() -> None:
    workspace = os.environ.get("TEXTBOOK_AGENT_WORKSPACE")
    if not workspace:
        from common.app_paths import ensure_active_workspace

        workspace = ensure_active_workspace()
    print(json.dumps(build_prompt_metrics(workspace, skill_filter=[]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
