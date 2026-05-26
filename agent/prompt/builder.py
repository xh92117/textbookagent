"""
System Prompt Builder - 系统提示词构建器

实现模块化的系统提示词构建，支持工具、技能、记忆等多个子系统
"""

from __future__ import annotations
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from common.log import logger
from config import conf


@dataclass
class ContextFile:
    """上下文文件"""
    path: str
    content: str


@dataclass
class PromptBuildResult:
    """Prompt text plus section-level diagnostics."""
    prompt: str
    diagnostics: Dict[str, Any]


class PromptBuilder:
    """提示词构建器"""
    
    def __init__(self, workspace_dir: str, language: str = "zh"):
        """
        初始化提示词构建器
        
        Args:
            workspace_dir: 工作空间目录
            language: 语言 ("zh" 或 "en")
        """
        self.workspace_dir = workspace_dir
        self.language = language
    
    def build(
        self,
        base_persona: Optional[str] = None,
        user_identity: Optional[Dict[str, str]] = None,
        tools: Optional[List[Any]] = None,
        context_files: Optional[List[ContextFile]] = None,
        skill_manager: Any = None,
        memory_manager: Any = None,
        runtime_info: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        构建完整的系统提示词
        
        Args:
            base_persona: 基础人格描述（会被context_files中的AGENT.md覆盖）
            user_identity: 用户身份信息
            tools: 工具列表
            context_files: 上下文文件列表（AGENT.md, USER.md, RULE.md, BOOTSTRAP.md等）
            skill_manager: 技能管理器
            memory_manager: 记忆管理器
            runtime_info: 运行时信息
            **kwargs: 其他参数
            
        Returns:
            完整的系统提示词
        """
        return build_agent_system_prompt(
            workspace_dir=self.workspace_dir,
            language=self.language,
            base_persona=base_persona,
            user_identity=user_identity,
            tools=tools,
            context_files=context_files,
            skill_manager=skill_manager,
            memory_manager=memory_manager,
            runtime_info=runtime_info,
            **kwargs
        )

    def build_with_diagnostics(
        self,
        base_persona: Optional[str] = None,
        user_identity: Optional[Dict[str, str]] = None,
        tools: Optional[List[Any]] = None,
        context_files: Optional[List[ContextFile]] = None,
        skill_manager: Any = None,
        memory_manager: Any = None,
        runtime_info: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> PromptBuildResult:
        return _build_agent_system_prompt_result(
            workspace_dir=self.workspace_dir,
            language=self.language,
            base_persona=base_persona,
            user_identity=user_identity,
            tools=tools,
            context_files=context_files,
            skill_manager=skill_manager,
            memory_manager=memory_manager,
            runtime_info=runtime_info,
            **kwargs
        )


def build_agent_system_prompt(
    workspace_dir: str,
    language: str = "zh",
    base_persona: Optional[str] = None,
    user_identity: Optional[Dict[str, str]] = None,
    tools: Optional[List[Any]] = None,
    context_files: Optional[List[ContextFile]] = None,
    skill_manager: Any = None,
    memory_manager: Any = None,
    runtime_info: Optional[Dict[str, Any]] = None,
    **kwargs
) -> str:
    """
    构建Agent系统提示词
    
    顺序说明（按重要性和逻辑关系排列）:
    1. 工具系统 - 核心能力，最先介绍
    2. 技能系统 - 紧跟工具，因为技能需要用 read 工具读取
    3. 记忆系统 - 记忆检索与写入引导
    3.5 知识系统 - 结构化知识库（knowledge/index.md 注入）
    4. 工作空间 - 工作环境说明
    5. 用户身份 - 用户信息（可选）
    6. 项目上下文 - AGENT.md, USER.md, RULE.md, MEMORY.md, BOOTSTRAP.md
    7. 运行时信息 - 元信息（时间、模型等）
    
    Args:
        workspace_dir: 工作空间目录
        language: 语言 ("zh" 或 "en")
        base_persona: 基础人格描述（已废弃，由AGENT.md定义）
        user_identity: 用户身份信息
        tools: 工具列表
        context_files: 上下文文件列表
        skill_manager: 技能管理器
        memory_manager: 记忆管理器
        runtime_info: 运行时信息
        **kwargs: 其他参数
        
    Returns:
        完整的系统提示词
    """
    return _build_agent_system_prompt_result(
        workspace_dir=workspace_dir,
        language=language,
        base_persona=base_persona,
        user_identity=user_identity,
        tools=tools,
        context_files=context_files,
        skill_manager=skill_manager,
        memory_manager=memory_manager,
        runtime_info=runtime_info,
        **kwargs,
    ).prompt

    sections = []
    skill_filter = kwargs.get("skill_filter")
    skill_route_prompt = kwargs.get("skill_route_prompt") or ""
    sections.extend(_build_language_policy_section(language))
    
    # 1. 工具系统（最重要，放在最前面）
    if tools:
        sections.extend(_build_tooling_section(tools, language))
        sections.extend(_build_harness_tool_policy_section(language))
    
    # 2. 技能系统（紧跟工具，因为需要用 read 工具）
    if skill_manager:
        if skill_route_prompt:
            sections.extend([skill_route_prompt, ""])
        sections.extend(_build_skills_section(skill_manager, tools, language, skill_filter=skill_filter))
    
    # 3. 记忆系统（独立的记忆能力）
    if memory_manager:
        sections.extend(_build_memory_section(memory_manager, tools, language))

    # 3.5 知识系统（结构化知识库）
    if conf().get("knowledge", True):
        sections.extend(_build_knowledge_section(workspace_dir, language))
    
    # 4. 工作空间（工作环境说明）
    sections.extend(_build_workspace_section(workspace_dir, language))
    
    # 5. 用户身份（如果有）
    if user_identity:
        sections.extend(_build_user_identity_section(user_identity, language))
    
    # 6. 项目上下文文件（AGENT.md, USER.md, RULE.md - 定义人格）
    if context_files:
        sections.extend(_build_context_files_section(context_files, language))
    
    # 7. 运行时信息（元信息，放在最后）
    if runtime_info:
        sections.extend(_build_runtime_section(runtime_info, language))
    
    return "\n".join(sections)


def _build_agent_system_prompt_result(
    workspace_dir: str,
    language: str = "zh",
    base_persona: Optional[str] = None,
    user_identity: Optional[Dict[str, str]] = None,
    tools: Optional[List[Any]] = None,
    context_files: Optional[List[ContextFile]] = None,
    skill_manager: Any = None,
    memory_manager: Any = None,
    runtime_info: Optional[Dict[str, Any]] = None,
    **kwargs
) -> PromptBuildResult:
    section_texts: List[str] = []
    section_records: List[Dict[str, Any]] = []
    skill_filter = kwargs.get("skill_filter")
    skill_route_prompt = kwargs.get("skill_route_prompt") or ""

    def add_section(name: str, lines: List[str]):
        text = "\n".join(lines or []).strip("\n")
        if not text:
            return
        original_chars = len(text)
        budget = _prompt_section_budget(name)
        clipped = False
        if budget and original_chars > budget:
            text = _clip_prompt_section(text, budget, name)
            clipped = True
        section_texts.append(text)
        section_records.append({
            "name": name,
            "chars": len(text),
            "original_chars": original_chars,
            "budget_chars": budget,
            "clipped": clipped,
        })

    add_section("language_policy", _build_language_policy_section(language))

    if tools:
        add_section("tooling", _build_tooling_section(tools, language))
        add_section("harness_tool_policy", _build_harness_tool_policy_section(language))

    if skill_manager:
        if skill_route_prompt:
            add_section("skill_route", [skill_route_prompt])
        add_section("skills", _build_skills_section(skill_manager, tools, language, skill_filter=skill_filter))

    if memory_manager:
        add_section("memory", _build_memory_section(memory_manager, tools, language))

    if conf().get("knowledge", True):
        add_section("knowledge", _build_knowledge_section(workspace_dir, language))

    add_section("workspace", _build_workspace_section(workspace_dir, language))

    if user_identity:
        add_section("user_identity", _build_user_identity_section(user_identity, language))

    if context_files:
        add_section("context_files", _build_context_files_section(context_files, language))

    if runtime_info:
        add_section("session_handoff", _build_session_handoff_section(runtime_info, language))

    if runtime_info:
        add_section("runtime", _build_runtime_section(runtime_info, language))

    prompt = "\n\n".join(section_texts)
    return PromptBuildResult(
        prompt=prompt,
        diagnostics={
            "total_chars": len(prompt),
            "sections": section_records,
            "clipped_sections": [s["name"] for s in section_records if s["clipped"]],
        },
    )


def _prompt_section_budget(name: str) -> int:
    defaults = {
        "tooling": 1500,
        "harness_tool_policy": 1400,
        "skills": 2800,
        "memory": 1200,
        "knowledge": 1800,
        "workspace": 1200,
        "context_files": 4000,
        "session_handoff": 900,
        "runtime": 1600,
    }
    try:
        budgets = conf().get("agent_prompt_section_budgets", {}) or {}
        if isinstance(budgets, dict):
            if name in budgets:
                return max(0, int(budgets.get(name) or 0))
    except Exception:
        pass
    return defaults.get(name, 0)


def _clip_prompt_section(text: str, max_chars: int, name: str) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    notice = (
        f"\n\n[Section clipped: {name}, original_chars={len(text)}, "
        f"budget_chars={max_chars}. Use read/memory tools for full details.]\n\n"
    )
    budget = max(200, max_chars - len(notice))
    head_chars = max(120, int(budget * 0.65))
    tail_chars = max(60, budget - head_chars)
    return (text[:head_chars].rstrip() + notice + text[-tail_chars:].lstrip())[:max_chars]


def _build_session_handoff_section(runtime_info: Dict[str, Any], language: str) -> List[str]:
    handoff = ""
    try:
        getter = runtime_info.get("_get_session_handoff")
        if callable(getter):
            handoff = str(getter() or "")
        else:
            handoff = str(runtime_info.get("session_handoff", "") or "")
    except Exception:
        handoff = ""
    if not handoff.strip():
        return []
    compact = _compact_session_handoff_text(handoff)
    lines = [
        "## Session Handoff",
        "",
        "Use this compact handoff as the active session state. Prefer its evidence refs over copied conversation details.",
        "",
    ]
    lines.extend(compact.strip().splitlines())
    lines.append("")
    return lines


def _compact_session_handoff_text(handoff: str) -> str:
    text = str(handoff or "").strip()
    if not text:
        return ""
    wanted = {"Current Goal", "Next Actions", "Evidence Refs", "Suggested Retrieval"}
    current = ""
    sections: Dict[str, List[str]] = {name: [] for name in wanted}
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            continue
        if current in wanted and line.strip():
            sections[current].append(line.strip())
    lines: List[str] = []
    for name in ("Current Goal", "Next Actions", "Evidence Refs", "Suggested Retrieval"):
        values = sections.get(name) or []
        if not values:
            continue
        lines.append(f"### {name}")
        lines.extend(values[:4])
        lines.append("")
    return "\n".join(lines).strip() or text


def _build_language_policy_section(language: str) -> List[str]:
    if str(language or "zh").lower().startswith("en"):
        return [
            "## Response Language Policy",
            "",
            "- Reply to the user in English unless the user explicitly asks for another language.",
            "- Tool names, code, logs, file paths, API fields, and quoted source text may stay in their original language.",
            "- Do not let English tool outputs, skill instructions, or runtime boards change the user-facing reply language.",
            "",
        ]
    return [
        "## 回答语言规则",
        "",
        "- 默认始终使用简体中文回答用户，包括总结、解释、进度说明、错误说明和最终结论。",
        "- 只有当用户明确要求使用英文或要求提供英文版内容时，才切换为英文。",
        "- 工具名、代码、日志、文件路径、API 字段、命令输出和原文引用可以保留原语言，但面向用户的说明必须用中文。",
        "- 不要被英文工具结果、英文技能说明、Runtime Context Board 或英文系统片段带偏回答语言。",
        "",
    ]


def _build_harness_tool_policy_section(language: str) -> List[str]:
    """Inject compact Harness tool policy from system/harness/tool_policy.json."""
    try:
        from agent.harness import format_tool_policy_for_prompt

        section = format_tool_policy_for_prompt()
        return [section, ""] if section else []
    except Exception as e:
        logger.debug(f"[PromptBuilder] Harness tool policy skipped: {e}")
        return []


def _build_identity_section(base_persona: Optional[str], language: str) -> List[str]:
    """构建基础身份section - 不再需要，身份由AGENT.md定义"""
    # 不再生成基础身份section，完全由AGENT.md定义
    return []


def _build_tooling_section(tools: List[Any], language: str) -> List[str]:
    """Build tooling section with concise tool list and call style guide."""
    # One-line summaries for known tools (details are in the tool schema)
    core_summaries = {
        "read": "读取文件内容",
        "write": "创建或覆盖文件",
        "edit": "精确编辑文件",
        "ls": "列出目录内容",
        "grep": "搜索文件内容",
        "find": "按模式查找文件",
        "bash": "执行shell命令",
        "terminal": "管理后台进程",
        "web_search": "网络搜索",
        "web_fetch": "获取URL内容",
        "textbook_chapter": "教材章节专用读写/追加/替换/编码检查工具",
        "browser": "控制浏览器（关键结果或需要协助可截图发送给用户）",
        "memory_search": "搜索记忆",
        "memory_get": "读取记忆内容",
        "env_config": "管理API密钥和技能配置",
        "scheduler": "管理定时任务和提醒",
        "send": "发送本地文件给用户（仅限本地文件，URL直接放在回复文本中）",
        "vision": "分析图片内容（识别、描述、OCR文字提取等）",
    }

    # Preferred display order
    tool_order = [
        "read", "write", "edit", "ls", "grep", "find",
        "bash", "terminal",
        "web_search", "web_fetch", "textbook_chapter", "browser",
        "memory_search", "memory_get",
        "env_config", "scheduler", "send", "vision",
    ]

    # Build name -> summary mapping for available tools
    available = {}
    for tool in tools:
        name = tool.name if hasattr(tool, 'name') else str(tool)
        available[name] = core_summaries.get(name, "")

    # Generate tool lines: ordered tools first, then extras
    tool_lines = []
    for name in tool_order:
        if name in available:
            summary = available.pop(name)
            tool_lines.append(f"- {name}: {summary}" if summary else f"- {name}")
    for name in sorted(available):
        summary = available[name]
        tool_lines.append(f"- {name}: {summary}" if summary else f"- {name}")

    lines = [
        "## 🔧 工具系统",
        "",
        "可用工具（名称大小写敏感，严格按列表调用）:",
        "\n".join(tool_lines),
        "",
        "工具调用风格：",
        "",
        "- 多步骤任务、复杂决策、敏感操作时，应简要说明当前在做什么、为什么这样做，让用户了解关键进展",
        "- 持续推进直到任务完成，完成后向用户报告结果",
        "- 回复中涉及密钥、令牌等敏感信息必须脱敏",
        "- URL链接直接放在回复文本中即可，系统会自动处理和渲染。无需下载后使用send工具发送",
        "- Windows 命令/PowerShell 只用于执行程序、列目录、检查状态等操作；命令文本和输出字段尽量使用 ASCII/英文，拿到结果后再用中文向用户解释。不要把大段中文正文、章节内容或提示词直接塞进 shell 命令。",
        "- 写入中文教材文件时，优先使用 write 或 edit 工具；追加内容用 edit 且 oldText 为空。不要用 bash 调用 PowerShell Add-Content/Set-Content/Out-File 写中文文件，避免 Windows 编码破坏。",
        "- 单次工具参数保持短小。大段章节内容必须按小节或更小块分批写入，每块建议不超过 6000 字符；JSON 参数解析失败后，应缩小块大小并继续，不要改用 shell 拼接长字符串。",
        "- 编写、续写、替换或检查教材章节时，优先使用 textbook_chapter 工具。它会自动定位教材ID目录、按UTF-8保存、更新章节元数据和状态，避免手写路径或用shell拼接文件。",
        "- 教材章节写完后如只需标记完成，必须调用 textbook_chapter action=mark_completed；不要用 write_chapter 传 placeholder、空内容或短文本来更新状态，否则会覆盖原文。",
        "- 教材任务必须遵守状态板：已完成的大纲/审查/已写章节不得重新生成；如果状态显示正在写某章，只能继续该章的下一小节、校验或保存，除非用户明确要求回退。",
        "",
    ]

    return lines


def _build_skills_section(skill_manager: Any, tools: Optional[List[Any]], language: str, skill_filter=None) -> List[str]:
    """构建技能系统section"""
    if not skill_manager:
        return []
    if skill_filter == []:
        return [
            "## 技能系统（mandatory）",
            "",
            "Skill routing did not select a specific skill for this turn. Do not read any SKILL.md unless the user explicitly asks for a skill workflow.",
            "",
        ]
    
    # 获取read工具名称
    read_tool_name = "read"
    if tools:
        for tool in tools:
            tool_name = tool.name if hasattr(tool, 'name') else str(tool)
            if tool_name.lower() == "read":
                read_tool_name = tool_name
                break
    
    lines = [
        "## 🧩 技能系统（mandatory）",
        "",
        "在回复之前：扫描下方 <available_skills> 中每个技能的 <description>。",
        "",
        f"- 如果有技能的描述与用户需求匹配：使用 `{read_tool_name}` 工具读取其 <location> 路径的 SKILL.md 文件，然后严格遵循文件中的指令。"
        "当有匹配的技能时，应优先使用技能",
        "- 如果多个技能都适用则选择最匹配的一个，然后读取并遵循。",
        "- 如果没有技能明确适用：不要读取任何 SKILL.md，直接使用通用工具。",
        "",
        f"**重要**: 技能不是工具，不能直接调用。使用技能的唯一方式是用 `{read_tool_name}` 读取 SKILL.md 文件，然后按文件内容操作。"
        "永远不要一次性读取多个技能，只在选择后再读取。",
        "",
        "以下是可用技能："
    ]
    
    # 添加技能列表（通过skill_manager获取）
    try:
        skills_prompt = skill_manager.build_skills_prompt(skill_filter=skill_filter)
        logger.debug(f"[PromptBuilder] Skills prompt length: {len(skills_prompt) if skills_prompt else 0}")
        if skills_prompt:
            lines.append(skills_prompt.strip())
            lines.append("")
        else:
            logger.warning("[PromptBuilder] No skills prompt generated - skills_prompt is empty")
    except Exception as e:
        logger.warning(f"Failed to build skills prompt: {e}")
        import traceback
        logger.debug(f"Skills prompt error traceback: {traceback.format_exc()}")
    
    return lines


def _build_memory_section(memory_manager: Any, tools: Optional[List[Any]], language: str) -> List[str]:
    """Build memory-system instructions without eagerly loading memory files."""
    if not memory_manager:
        return []

    has_memory_tools = False
    if tools:
        tool_names = [tool.name if hasattr(tool, 'name') else str(tool) for tool in tools]
        has_memory_tools = any(name in ['memory_search', 'memory_get'] for name in tool_names)

    if not has_memory_tools:
        return []

    from datetime import datetime
    today_file = datetime.now().strftime("%Y-%m-%d") + ".md"

    return [
        "## 记忆系统",
        "",
        "### 加载策略",
        "",
        "- 用户画像、全局记忆、会话记忆、以及工作区根目录 AGENT.md/USER.md/RULE.md/MEMORY.md 只会在本会话首次请求中通过 SYSTEM_MEMORY_BOOTSTRAP 注入一次。",
        "- 后续轮次不要假设完整记忆仍在上下文中；需要时必须用 memory_search / memory_get 按需读取。",
        f"- 每日记忆文件：memory/{today_file}；进程记忆：memory/processes/；会话记忆：memory/sessions/。",
        "- 进程记忆、每日记忆、错误记忆默认按需检索，由智能体根据任务相关性决定是否读取。",
        "",
        "### 何时检索",
        "",
        "- 用户询问过去事件、偏好、规则、项目决策、待办、会话历史，或你不确定上下文时，先检索记忆再回答。",
        "- 不确定位置时用 memory_search；已知路径时用 memory_get。",
        "- search 无结果但任务明显依赖历史时，优先读取 MEMORY.md、memory/process_index.md、最近每日记忆或相关 process state。",
        "",
        "### 写入记忆",
        "",
        "- 统一规则：智能体记忆只允许写入系统记忆目录 `system/memory/`；不要在教材工作区创建或更新 `memory/` 文件夹。",
        "- 使用 `write` 或 `edit` 写入 `MEMORY.md`、`memory/YYYY-MM-DD.md`、`memory/processes/...` 时，工具会自动解析到系统记忆目录。",
        "- 用户明确要求记住、以后总是/不要、偏好、规则、长期目标时，优先写入 MEMORY.md；只有用户明确修改身份信息或工作区规则时，才更新 USER.md/RULE.md。",
        f"- 当天进展、阶段性结论和临时记录写入 memory/{today_file}。",
        "- 完成复杂任务后的过程状态由进程记忆自动记录；不要把低价值流水账重复写入长期记忆。",
        "- 禁止写入敏感信息，例如 API key、token、密码。",
        "",
    ]

def _build_knowledge_section(workspace_dir: str, language: str) -> List[str]:
    """Build knowledge wiki section. Injects knowledge/index.md when present."""
    index_path = os.path.join(workspace_dir, "knowledge", "index.md")
    if not os.path.exists(index_path):
        return []

    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            index_content = f.read().strip()
    except Exception:
        return []

    lines = [
        "## 📚 知识系统",
        "",
        "你拥有结构化知识库 `knowledge/`，用于保存可复用资料、结论、实体和方法。",
        "",
        "### 使用边界",
        "",
        "- 需要资料依据、历史结论、项目知识或用户明确要求查知识库时，先检索或读取相关知识页。",
        "- 写入知识库只保存长期有价值的内容，不保存闲聊、重复日志、临时失败、敏感信息。",
        "- 证据不足时说明缺口，不要编造来源、数据、标准或结论。",
        "",
        "### 写入规则",
        "",
        "以下场景可以写入知识库：",
        "1. 用户明确要求保存资料、结论或文档。",
        "2. 用户上传/分享了与当前项目长期相关的文章、链接或文档。",
        "3. 深度讨论形成了可复用方案、规则、实体资料或方法论。",
        "4. 教材/项目资料需要成为后续检索证据。",
        "",
        "写入后同步更新 `knowledge/index.md`。不要为了凑知识库而保存低价值内容。",
        "",
    ]

    if index_content:
        lines.extend([
            "### 当前知识索引",
            "",
            index_content,
            "",
        ])

    lines.extend([
        "**知识库查询方式**：优先使用 `knowledge_query`，按 `glob -> search -> peek -> pack -> read_neighbors/read_section -> read_range` 分层访问。",
        "- `glob` 只看知识库概览、来源文档和主题页；不要枚举 `_llm_wiki/chunks/` 内部分块文件。",
        "- `search`/`peek` 基于现有 `_llm_wiki/index.json` 的元数据检索，并只返回少量命中片段，不返回正文全文。",
        "- `pack` 生成教材写作用证据包，优先用于章节写作。",
        "- `read_neighbors` 用于读取命中块周边上下文；`read_section` 用于读取同一章节/小节的局部内容。",
        "- `read_range` 只能在需要核对定义、公式、数据、表格、页码或精确引用时按 `chunk_id/path + offset + max_chars` 读取更窄内容。",
        "- 禁止因为关键词命中文档就整篇 `read` PDF/论文/长 Markdown；分块是检索底层，不是上下文注入清单。",
        "",
    ])

    return lines


def _build_user_identity_section(user_identity: Dict[str, str], language: str) -> List[str]:
    """构建用户身份section"""
    if not user_identity:
        return []
    
    lines = [
        "## 👤 用户身份",
        "",
    ]
    
    if user_identity.get("name"):
        lines.append(f"**用户姓名**: {user_identity['name']}")
    if user_identity.get("nickname"):
        lines.append(f"**称呼**: {user_identity['nickname']}")
    if user_identity.get("timezone"):
        lines.append(f"**时区**: {user_identity['timezone']}")
    if user_identity.get("notes"):
        lines.append(f"**备注**: {user_identity['notes']}")
    
    lines.append("")
    
    return lines


def _build_docs_section(workspace_dir: str, language: str) -> List[str]:
    """构建文档路径section - 已移除，不再需要"""
    # 不再生成文档section
    return []


def _build_workspace_section(workspace_dir: str, language: str) -> List[str]:
    """构建工作空间section"""
    lines = [
        "## 📂 工作空间",
        "",
        f"你的工作目录是: `{workspace_dir}`",
        "",
        "**路径使用规则** (非常重要):",
        "",
        f"1. **相对路径的基准目录**: 所有相对路径都是相对于 `{workspace_dir}` 而言的",
        f"   - ✅ 正确: 访问工作空间内的文件用相对路径，如 `AGENT.md`",
        f"   - ❌ 错误: 用相对路径访问其他目录的文件 (如果它不在 `{workspace_dir}` 内)",
        "",
        "2. **访问其他目录**: 如果要访问工作空间之外的目录（如项目代码、系统文件），**必须使用绝对路径**",
        f"   - ✅ 正确: 例如 `~/chatgpt-on-wechat`、`/usr/local/`",
        f"   - ❌ 错误: 假设相对路径会指向其他目录",
        "",
        "3. **路径解析示例**:",
        "   - 记忆路径 `MEMORY.md` 和 `memory/...` → 系统目录 `system/memory/`，不是教材工作区。",
        f"   - 绝对路径 `~/chatgpt-on-wechat/docs/` → 实际路径 `~/chatgpt-on-wechat/docs/`",
        "",
        "4. **不确定时**: 先用 `bash pwd` 确认当前目录，或用 `ls .` 查看当前位置",
        "",
        "**重要说明 - 文件已自动加载**:",
        "",
        "以下文件在会话启动时**已经自动加载**到系统提示词中，你**无需再用 read 工具读取**：",
        "",
        "- ✅ `AGENT.md`: 已加载 - 你的人格和灵魂设定，请严格遵循。当你的名字、性格或交流风格发生变化时，主动用 `edit` 更新此文件",
        "- ✅ `USER.md`: 已加载 - 用户的身份信息。当用户修改称呼、姓名等身份信息时，用 `edit` 更新此文件",
        "- ✅ `RULE.md`: 已加载 - 工作空间使用指南和规则，请严格遵循",
        "- ✅ `MEMORY.md`: 已加载 - 长期记忆索引",
        "",
        "**💬 交流规范**:",
        "",
        "- 记忆相关操作无需暴露文件名，用自然语言表达即可。例如说「我已记住」而非「已更新 MEMORY.md」",
        "- 任务执行过程中的关键决策和步骤应该告知用户，让用户了解你在做什么、为什么这么做",
        "- 做真正有帮助的助手，而不是表演式的客套，尽可能帮忙解决问题",
        "- 回复应结构清晰、重点突出。善用 **加粗**、列表、分段等格式让信息一目了然",
        "- 作为教材编制专业助手，回复应专业严谨，不使用 emoji，保持学术风格",
        "",
    ]

    # Cloud deployment: inject websites directory info and access URL
    cloud_website_lines = _build_cloud_website_section(workspace_dir)
    if cloud_website_lines:
        lines.extend(cloud_website_lines)
    
    return lines


def _build_cloud_website_section(workspace_dir: str) -> List[str]:
    """Build cloud website access prompt when cloud deployment is configured."""
    try:
        from common.cloud_client import build_website_prompt
        return build_website_prompt(workspace_dir)
    except Exception:
        return []


def _build_context_files_section(context_files: List[ContextFile], language: str) -> List[str]:
    """构建项目上下文文件section"""
    if not context_files:
        return []
    
    # 检查是否有AGENT.md
    has_agent = any(
        f.path.lower().endswith('agent.md') or 'agent.md' in f.path.lower()
        for f in context_files
    )
    
    lines = [
        "# 📋 项目上下文",
        "",
        "以下项目上下文文件已被加载：",
        "",
    ]
    
    if has_agent:
        lines.append("**`AGENT.md` 是你的灵魂文件** 🪞：严格遵循其中定义的人格、语气和设定，做真实的自己，避免僵硬、模板化的回复。")
        lines.append("当用户通过对话透露了对你性格、风格、职责、能力边界的新期望，你应该主动用 `edit` 更新 AGENT.md 以反映这些演变。")
        lines.append("")
    
    # 添加每个文件的内容
    for file in context_files:
        lines.append(f"## {file.path}")
        lines.append("")
        lines.append(file.content)
        lines.append("")
    
    return lines


def _build_runtime_section(runtime_info: Dict[str, Any], language: str) -> List[str]:
    """构建运行时信息section - 支持动态时间"""
    if not runtime_info:
        return []
    
    lines = [
        "## ⚙️ 运行时信息",
        "",
    ]
    
    # Add current time if available
    # Support dynamic time via callable function
    if callable(runtime_info.get("_get_current_time")):
        try:
            time_info = runtime_info["_get_current_time"]()
            time_line = f"当前时间: {time_info['time']} {time_info['weekday']} ({time_info['timezone']})"
            lines.append(time_line)
            lines.append("")
        except Exception as e:
            logger.warning(f"[PromptBuilder] Failed to get dynamic time: {e}")
    elif runtime_info.get("current_time"):
        # Fallback to static time for backward compatibility
        time_str = runtime_info["current_time"]
        weekday = runtime_info.get("weekday", "")
        timezone = runtime_info.get("timezone", "")
        
        time_line = f"当前时间: {time_str}"
        if weekday:
            time_line += f" {weekday}"
        if timezone:
            time_line += f" ({timezone})"
        
        lines.append(time_line)
        lines.append("")
    
    # Add other runtime info
    runtime_parts = []
    # Support dynamic model via callable, fallback to static value
    if callable(runtime_info.get("_get_model")):
        try:
            runtime_parts.append(f"模型={runtime_info['_get_model']()}")
        except Exception:
            if runtime_info.get("model"):
                runtime_parts.append(f"模型={runtime_info['model']}")
    elif runtime_info.get("model"):
        runtime_parts.append(f"模型={runtime_info['model']}")
    if runtime_info.get("workspace"):
        runtime_parts.append(f"工作空间={runtime_info['workspace']}")
    # Only add channel if it's not the default "web"
    if runtime_info.get("channel") and runtime_info.get("channel") != "web":
        runtime_parts.append(f"渠道={runtime_info['channel']}")
    
    if runtime_parts:
        lines.append("运行时: " + " | ".join(runtime_parts))
        lines.append("")
    
    if callable(runtime_info.get("_get_work_state")):
        try:
            work_state_text = runtime_info["_get_work_state"]()
            if work_state_text:
                lines.append("## 📋 工作状态（上次会话延续）")
                lines.append("")
                for ws_line in work_state_text.split("\n"):
                    if ws_line.strip():
                        lines.append(ws_line)
                lines.append("")
        except Exception:
            pass

    return lines
