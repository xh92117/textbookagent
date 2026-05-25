from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Set


ALWAYS_TOOLS = {"memory_search", "memory_get"}

TASK_TOOL_PROFILES: Dict[str, Set[str]] = {
    "textbook": {
        "textbook_chapter",
        "textbook_image",
        "knowledge_query",
        "memory_search",
        "memory_get",
        "read",
        "ls",
    },
    "frontend": {"read", "edit", "ls", "bash", "browser", "memory_search", "memory_get"},
    "research": {"web_search", "web_fetch", "knowledge_capture", "knowledge_query", "memory_search", "memory_get"},
    "config": {"env_config", "read", "edit", "ls", "memory_search", "memory_get"},
    "automation": {"scheduler", "memory_search", "memory_get"},
    "vision": {"vision", "read", "memory_search", "memory_get"},
    "file_edit": {"read", "edit", "write", "ls", "bash", "memory_search", "memory_get"},
    "general": {
        "read",
        "edit",
        "ls",
        "bash",
        "memory_search",
        "memory_get",
        "knowledge_query",
    },
}

ROUTING_HINTS = {
    "textbook": [
        "Use textbook_chapter for chapter Markdown; do not use bash/write/edit for textbook body text.",
        "Use knowledge_query before drafting when evidence or textbook continuity matters.",
        "Use textbook_image only for real diagrams/charts/assets, not prompt text inside images.",
    ],
    "frontend": [
        "Use read/edit for source changes, bash for focused tests/builds, browser for UI verification.",
        "Do not use web_search unless the task asks for external/current information.",
    ],
    "research": [
        "Use web_search to find sources, web_fetch to read selected pages, knowledge_capture only for durable reusable evidence.",
        "Do not repeat the same search/fetch after a successful result.",
    ],
    "config": [
        "Use env_config for model/API/skill configuration when available; use edit only for file-level configuration changes.",
    ],
    "automation": [
        "Use scheduler only for reminders, recurring jobs, delayed follow-ups, or monitoring tasks.",
    ],
    "vision": [
        "Use vision for image/OCR understanding; use read only for local metadata or adjacent files.",
    ],
    "file_edit": [
        "Use edit for existing files, write only for new files or explicit full replacement.",
        "Use bash only for verification, not for writing large Chinese content.",
    ],
    "general": [
        "Prefer the narrowest tool that directly answers the task.",
        "If a tool succeeds, summarize or proceed to the next distinct action instead of repeating it.",
    ],
}

KEYWORDS = {
    "textbook": ("教材", "章节", "大纲", "一键编写", "导出", "课程", "WritingSpec", "harness", "图表", "插图"),
    "frontend": ("前端", "界面", "按钮", "页面", "浏览器", "UI", "css", "html", "javascript", "bug"),
    "research": ("搜索", "联网", "网页", "链接", "文献", "资料", "总结", "读取这个链接", "http://", "https://"),
    "config": ("模型", "api", "配置", "技能", "上传技能", "settings", "config"),
    "automation": ("提醒", "定时", "自动", "监控", "每隔", "每天", "以后提醒"),
    "vision": ("图片", "截图", "OCR", "识别", "照片"),
    "file_edit": ("修改文件", "更新文件", "README", "readme", "修复", "实现", "代码", "测试"),
}


@dataclass
class ToolRoute:
    task_type: str
    allowed_tools: List[str]
    omitted_tools: List[str]
    prompt: str


def infer_task_type(user_message: str) -> str:
    text = user_message or ""
    scores = {}
    for task_type, words in KEYWORDS.items():
        score = 0
        low = text.lower()
        for word in words:
            if word.lower() in low:
                score += 1
        if score:
            scores[task_type] = score
    if not scores:
        return "general"
    priority = ["textbook", "frontend", "research", "config", "automation", "vision", "file_edit"]
    return max(scores, key=lambda k: (scores[k], -priority.index(k) if k in priority else -99))


def route_tools(
    user_message: str,
    tools: Mapping[str, object] | Sequence[object],
    enabled: bool = True,
) -> ToolRoute:
    names = _tool_names(tools)
    if not enabled:
        allowed = sorted(names)
        return ToolRoute("all", allowed, [], _format_prompt("all", allowed, [], ["All tools are visible."]))

    task_type = infer_task_type(user_message)
    profile = set(TASK_TOOL_PROFILES.get(task_type, TASK_TOOL_PROFILES["general"]))
    allowed_set = (profile | ALWAYS_TOOLS) & names
    if not allowed_set:
        allowed_set = names
    omitted = sorted(names - allowed_set)
    allowed = sorted(allowed_set)
    hints = ROUTING_HINTS.get(task_type, ROUTING_HINTS["general"])
    return ToolRoute(task_type, allowed, omitted, _format_prompt(task_type, allowed, omitted, hints))


def filter_tool_mapping(tools: Mapping[str, object], allowed_tools: Iterable[str]) -> Dict[str, object]:
    allowed = set(allowed_tools)
    return {name: tool for name, tool in tools.items() if name in allowed}


def _tool_names(tools: Mapping[str, object] | Sequence[object]) -> Set[str]:
    if isinstance(tools, Mapping):
        return set(tools.keys())
    names = set()
    for tool in tools:
        name = getattr(tool, "name", "")
        if name:
            names.add(name)
    return names


def _format_prompt(task_type: str, allowed: List[str], omitted: List[str], hints: List[str]) -> str:
    lines = [
        "[System: Tool routing policy]",
        f"Detected task type: {task_type}",
        "Visible tools for this turn: " + (", ".join(allowed) if allowed else "none"),
    ]
    if omitted:
        lines.append("Hidden tools this turn: " + ", ".join(omitted[:20]) + (" ..." if len(omitted) > 20 else ""))
    lines.append("Routing rules:")
    lines.extend(f"- {hint}" for hint in hints)
    lines.extend([
        "- Before each tool call, choose the narrowest tool that directly matches the next action.",
        "- Do not call the same tool with the same arguments after a success; proceed or answer.",
        "- After two similar failures, change strategy or ask the user instead of retrying.",
    ])
    return "\n".join(lines)
