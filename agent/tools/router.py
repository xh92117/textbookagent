from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Sequence, Set


ALWAYS_TOOLS = {"memory_search", "memory_get"}

TASK_TOOL_PROFILES: Dict[str, Set[str]] = {
    "textbook": {
        "create_textbook",
        "start_pipeline",
        "textbook_outline",
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
        "Use create_textbook when the user wants to create/register a textbook project without starting the full pipeline.",
        "Use start_pipeline when the user wants automatic full-book generation.",
        "Use textbook_outline for outline/catalog/terminology Markdown; do not use textbook_chapter for whole-book outlines.",
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
    "textbook": (
        "教材", "章节", "章", "大纲", "一键编写", "导出", "课程", "续写", "编写", "标记完成",
        "WritingSpec", "harness",
        "鏁欐潗", "绔犺妭", "澶х翰", "涓€閿紪鍐?", "瀵煎嚭", "璇剧▼", "鍥捐〃", "鎻掑浘",
    ),
    "frontend": (
        "前端", "界面", "按钮", "页面", "浏览器", "UI", "css", "html", "javascript", "bug",
        "鍓嶇", "鐣岄潰", "鎸夐挳", "椤甸潰", "娴忚鍣?",
    ),
    "research": (
        "搜索", "联网", "网页", "链接", "文献", "资料", "总结", "读取这个链接", "http://", "https://",
        "鎼滅储", "鑱旂綉", "缃戦〉", "閾炬帴", "鏂囩尞", "璧勬枡",
    ),
    "config": (
        "模型", "api", "配置", "技能", "上传技能", "settings", "config",
        "妯″瀷", "閰嶇疆", "鎶€鑳?",
    ),
    "automation": (
        "提醒", "定时", "自动", "监控", "每隔", "每天", "以后提醒",
        "鎻愰啋", "瀹氭椂", "鑷姩", "鐩戞帶",
    ),
    "vision": (
        "图片", "截图", "OCR", "识别", "照片",
        "鍥剧墖", "鎴浘", "璇嗗埆", "鐓х墖",
    ),
    "file_edit": (
        "修改文件", "更新文件", "README", "readme", "修复", "实现", "代码", "测试",
        "淇敼鏂囦欢", "鏇存柊鏂囦欢", "淇", "瀹炵幇", "浠ｇ爜", "娴嬭瘯",
    ),
}


@dataclass
class ToolRoute:
    task_type: str
    allowed_tools: List[str]
    omitted_tools: List[str]
    prompt: str
    mode: str = "guided"
    required_tools: List[str] = field(default_factory=list)
    recommended_tools: List[str] = field(default_factory=list)
    blocked_tools: List[str] = field(default_factory=list)
    reason: str = ""


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
        return ToolRoute(
            "all",
            allowed,
            [],
            _format_prompt("all", allowed, [], ["All tools are visible."], mode="free", reason="routing disabled"),
            mode="free",
            recommended_tools=allowed,
            reason="routing disabled",
        )

    task_type = infer_task_type(user_message)
    mode, required_tools, reason = _route_mode(task_type, user_message, names)
    profile = set(TASK_TOOL_PROFILES.get(task_type, TASK_TOOL_PROFILES["general"]))
    if mode == "free":
        allowed_set = set(names)
    else:
        allowed_set = (profile | ALWAYS_TOOLS | set(required_tools)) & names
    if mode == "strict" and required_tools:
        strict_support = {"knowledge_query", "memory_search", "memory_get", "read", "ls"}
        allowed_set = (set(required_tools) | strict_support) & names
    if not allowed_set:
        allowed_set = names
    omitted = sorted(names - allowed_set)
    allowed = sorted(allowed_set)
    blocked = omitted if mode == "strict" else []
    hints = ROUTING_HINTS.get(task_type, ROUTING_HINTS["general"])
    prompt = _format_prompt(
        task_type,
        allowed,
        omitted,
        hints,
        mode=mode,
        required=required_tools,
        reason=reason,
    )
    return ToolRoute(
        task_type,
        allowed,
        omitted,
        prompt,
        mode=mode,
        required_tools=required_tools,
        recommended_tools=allowed,
        blocked_tools=blocked,
        reason=reason,
    )


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


def _route_mode(task_type: str, user_message: str, names: Set[str]) -> tuple[str, List[str], str]:
    text = (user_message or "").lower()
    if task_type == "textbook" and "start_pipeline" in names:
        pipeline_markers = (
            "启动编制", "启动管线", "一键编写", "一键编制", "自动编制", "自动生成整本",
            "/pipeline", "/start_pipeline", "/一键编写", "start pipeline", "one-click compile",
            "automatic compilation",
        )
        if any(marker in text for marker in pipeline_markers):
            return "strict", ["start_pipeline"], "full textbook pipeline requires explicit user intent and confirmation"
    if task_type == "textbook" and "create_textbook" in names:
        create_markers = (
            "创建教材", "新建教材", "创建一本教材", "新建一本教材", "初始化教材", "教材项目",
            "create textbook", "new textbook", "initialize textbook",
        )
        pipeline_markers = ("生成完整", "自动生成", "启动流水线", "start pipeline", "generate full")
        if any(marker in text for marker in create_markers) and not any(marker in text for marker in pipeline_markers):
            return "strict", ["create_textbook"], "textbook project creation must use canonical metadata creation"
    if task_type == "textbook" and "textbook_outline" in names:
        outline_markers = (
            "大纲", "目录", "术语表", "术语", "outline", "catalog", "terminology", "glossary",
        )
        chapter_write_markers = ("第1章", "第2章", "第3章", "第4章", "chapter 1", "chapter 2")
        if any(marker in text for marker in outline_markers) and not any(marker in text for marker in chapter_write_markers):
            return "strict", ["textbook_outline"], "textbook outline artifacts have a dedicated canonical tool"
    if task_type == "textbook" and "textbook_chapter" in names:
        chapter_markers = (
            "章节", "第", "续写", "编写", "正文", "标记完成",
            "教材", "章节", "章", "续写", "编写", "正文", "标记完成",
            "chapter", "write", "continue", "complete",
        )
        if any(marker in text for marker in chapter_markers):
            return "strict", ["textbook_chapter"], "textbook chapter operations have a dedicated stateful tool"
    if task_type in {"frontend", "research", "file_edit", "config", "vision", "automation"}:
        return "guided", [], f"{task_type} task gets a recommended tool set"
    return "free", [], "general task keeps model autonomy"


def _format_prompt(
    task_type: str,
    allowed: List[str],
    omitted: List[str],
    hints: List[str],
    mode: str = "guided",
    required: List[str] = None,
    reason: str = "",
) -> str:
    required = required or []
    lines = [
        "[System: Tool routing policy]",
        f"Detected task type: {task_type}",
        f"Route mode: {mode}",
        f"Route reason: {reason}" if reason else "Route reason: n/a",
        "Visible tools for this turn: " + (", ".join(allowed) if allowed else "none"),
    ]
    if required:
        lines.append("Strict required tools: " + ", ".join(required))
    if omitted:
        lines.append("Hidden tools this turn: " + ", ".join(omitted[:20]) + (" ..." if len(omitted) > 20 else ""))
    lines.append("Routing rules:")
    lines.extend(f"- {hint}" for hint in hints)
    lines.extend([
        "- Strict mode: use the required tool for the exact task; use support tools only for context or verification.",
        "- Guided mode: prefer the visible tools, but choose the narrowest tool that directly matches the next action.",
        "- Free mode: answer without tools when sufficient; call tools only when external state, files, or verification matter.",
        "- Do not call the same tool with the same arguments after a success; proceed or answer.",
        "- After two similar failures, change strategy or ask the user instead of retrying.",
    ])
    return "\n".join(lines)
