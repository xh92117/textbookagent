from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from agent.skills.types import SkillEntry


@dataclass
class SkillRoute:
    task_type: str
    selected_skills: List[str]
    omitted_skills: List[str]
    confidence: float
    prompt: str


SKILL_KEYWORDS = {
    "textbook-chapter": (
        "chapter", "section", "draft", "write", "rewrite", "continue",
        "第", "章", "章节", "编写", "续写", "继续写", "写第", "重写", "改写", "修复", "正文", "小节", "重复标题", "标题重复",
        "章节", "编写", "续写", "接着写", "继续写", "改写", "正文", "小节", "后半部分",
    ),
    "textbook-fullbook": (
        "full book", "one click", "all chapters", "batch write",
        "整本", "全书", "全教材", "全部章节", "所有章节", "一键", "一键编写", "启动编制", "启动管线", "自动编制", "自动生成整本", "批量编写",
        "一键", "全书", "整本", "全部章节", "所有章", "全套", "自动编写", "自动成稿", "批量编写",
    ),
    "textbook-outline": (
        "outline", "toc", "structure", "catalog",
        "大纲", "目录", "结构", "章目", "术语表", "优化大纲", "审查大纲",
        "大纲", "目录", "结构", "章目录", "优化大纲", "审查大纲",
    ),
    "textbook-review": (
        "review", "audit", "check", "quality", "evaluate",
        "审查", "评审", "检查", "质量", "审核", "评价", "修改建议",
        "审查", "评审", "检查", "质量", "审阅", "评价", "修改建议",
    ),
    "textbook-imagegen": (
        "image", "figure", "diagram", "chart", "visual",
        "图片", "插图", "图表", "流程图", "示意图", "架构图", "生成图",
    ),
    "textbook-wordgen": (
        "word", "docx", "export", "pdf", "document",
        "导出", "文档", "格式", "排版", "下载", "封面", "目录页",
    ),
    "textbook-knowledge-organizer": (
        "knowledge", "organize", "wiki", "source",
        "知识库", "知识整理", "资料整理", "知识图谱", "证据", "素材", "知识素材", "沉淀", "复用",
    ),
    "multi-search-engine": (
        "search", "web", "internet", "source", "paper", "reference", "url",
        "搜索", "联网", "网页", "链接", "文献", "资料", "引用", "来源",
    ),
    "textbook-sandbox": (
        "sandbox", "python", "execute", "code", "plot", "data",
        "沙盒", "代码执行", "运行代码", "生成图表", "数据", "可视化",
    ),
}

NEGATIVE_KEYWORDS = {
    "textbook-fullbook": ("不要整本", "不是整本", "别整本", "无需整本", "不要全书", "不是全书"),
    "multi-search-engine": ("沉淀成", "整理成知识", "复用的知识", "知识素材"),
}

TASK_HINTS = {
    "chapter": [
        "Use the selected chapter skill only when chapter-writing workflow details are needed.",
        "For textbook body edits, follow textbook_chapter/status rules before reading extra skill files.",
    ],
    "fullbook": [
        "Use full-book skill for batch or one-click writing, not for a single chapter edit.",
    ],
    "outline": [
        "Use outline skill for structure, versioning, or outline review tasks.",
    ],
    "review": [
        "Use review skill when the task is quality inspection, audit, rubric, or revision advice.",
    ],
    "image": [
        "Use image skill for actual visual asset requirements; verify that images are not prompt text screenshots.",
    ],
    "export": [
        "Use export/document skill for Word/PDF/docx layout and export behavior.",
    ],
    "research": [
        "Use search/knowledge skills only when external evidence or reusable knowledge is actually needed.",
    ],
    "sandbox": [
        "Use sandbox skill for executable experiments, computed charts, or data processing.",
    ],
    "general": [
        "No specific skill is selected; use ordinary tools and do not read SKILL.md unless the user asks for a skill.",
    ],
}


def route_skills(
    user_message: str,
    entries: Sequence[SkillEntry],
    max_skills: int = 2,
    min_confidence: float = 1.0,
    enabled: bool = True,
) -> SkillRoute:
    visible_entries = [entry for entry in entries if _is_visible(entry)]
    names = [entry.skill.name for entry in visible_entries]
    if not enabled:
        return SkillRoute(
            task_type="all",
            selected_skills=names,
            omitted_skills=[],
            confidence=0.0,
            prompt=_format_prompt("all", names, [], 0.0, ["Skill routing is disabled; all enabled skills are visible."]),
        )

    always = [
        entry.skill.name
        for entry in visible_entries
        if entry.metadata and entry.metadata.always
    ]
    scored = _score_entries(user_message, visible_entries)
    ranked = [
        (name, score)
        for name, score in sorted(scored.items(), key=lambda item: (-item[1], item[0]))
        if score >= min_confidence
    ]

    selected: List[str] = []
    for name in always:
        if name not in selected:
            selected.append(name)
    for name, _score in ranked:
        if name not in selected:
            selected.append(name)
        if len(selected) >= max(1, max_skills):
            break

    selected = selected[: max(0, max_skills)]
    best_score = ranked[0][1] if ranked else 0.0
    task_type = _infer_task_type(selected, user_message)
    omitted = [name for name in names if name not in selected]
    prompt = _format_prompt(
        task_type,
        selected,
        omitted,
        best_score,
        TASK_HINTS.get(task_type, TASK_HINTS["general"]),
    )
    return SkillRoute(task_type, selected, omitted, float(best_score), prompt)


def _score_entries(user_message: str, entries: Sequence[SkillEntry]) -> dict[str, float]:
    text = (user_message or "").lower()
    scores: dict[str, float] = {}
    for entry in entries:
        skill = entry.skill
        name = skill.name
        haystack = " ".join([
            name,
            skill.description or "",
            str(skill.frontmatter.get("triggers", "")) if isinstance(skill.frontmatter, dict) else "",
        ]).lower()
        score = 0.0

        for word in SKILL_KEYWORDS.get(name, ()):
            if word.lower() in text:
                score += 2.0
        for word in NEGATIVE_KEYWORDS.get(name, ()):
            if word.lower() in text:
                score -= 4.0
        if name == "textbook-fullbook" and any(
            word in text
            for word in ("不要整本", "不是整本", "别整本", "无需整本", "不要全书", "不是全书", "不要重写整本", "单章", "只修复", "只修改")
        ):
            score -= 4.0
        for token in _tokens(text):
            if len(token) >= 3 and token in haystack:
                score += 0.25

        if name in text:
            score += 4.0
        if score > 0:
            scores[name] = score
    return scores


def _infer_task_type(selected: Sequence[str], user_message: str) -> str:
    selected_set = set(selected)
    if "textbook-fullbook" in selected_set:
        return "fullbook"
    if "textbook-outline" in selected_set:
        return "outline"
    if "textbook-wordgen" in selected_set:
        return "export"
    if "textbook-imagegen" in selected_set:
        return "image"
    if "textbook-review" in selected_set:
        return "review"
    if "multi-search-engine" in selected_set or "textbook-knowledge-organizer" in selected_set:
        return "research"
    if "textbook-sandbox" in selected_set:
        return "sandbox"
    if "textbook-chapter" in selected_set:
        return "chapter"
    if "skill" in (user_message or "").lower() or "技能" in (user_message or ""):
        return "general"
    return "general"


def _tokens(text: str) -> Iterable[str]:
    return re.findall(r"[a-z0-9_\-]{3,}", text.lower())


def _is_visible(entry: SkillEntry) -> bool:
    return bool(entry and entry.skill and not entry.skill.disable_model_invocation)


def _format_prompt(
    task_type: str,
    selected: Sequence[str],
    omitted: Sequence[str],
    confidence: float,
    hints: Sequence[str],
) -> str:
    lines = [
        "[System: Skill routing policy]",
        f"Detected skill task type: {task_type}",
        f"Route confidence: {confidence:.2f}",
        "Visible skills for this turn: " + (", ".join(selected) if selected else "none"),
    ]
    if omitted:
        hidden = ", ".join(list(omitted)[:20])
        if len(omitted) > 20:
            hidden += " ..."
        lines.append("Hidden skills this turn: " + hidden)
    lines.append("Routing rules:")
    lines.extend(f"- {hint}" for hint in hints)
    lines.extend([
        "- Before calling task tools, read the selected SKILL.md and follow its allowed-tool and stop rules.",
        "- At most one selected SKILL.md should be read unless the user asks for a multi-skill workflow.",
        "- Do not read unselected SKILL.md files in this turn.",
        "- Tool routing and textbook status rules take priority over skill suggestions.",
    ])
    return "\n".join(lines)
