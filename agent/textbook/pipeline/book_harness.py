from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from ..models.textbook import TextbookConfig, WritingSpec


class BookHarness:
    """Per-textbook execution constraints derived from config and WritingSpec."""

    FILENAME = "harness.md"

    def __init__(self, book_dir: str):
        self.book_dir = book_dir

    @property
    def path(self) -> str:
        return os.path.join(self.book_dir, self.FILENAME)

    def ensure(self, book_config: TextbookConfig, writing_spec: Optional[WritingSpec] = None) -> str:
        writing_spec = writing_spec or book_config.ensure_writing_spec()
        content = self.render(book_config, writing_spec)
        existing = self.read()
        if self._managed_body(existing) == self._managed_body(content):
            return existing or content
        os.makedirs(self.book_dir, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)
        return content

    def read(self) -> str:
        if not os.path.exists(self.path):
            return ""
        with open(self.path, "r", encoding="utf-8") as f:
            return f.read()

    def prompt_section(self) -> str:
        text = self.read().strip()
        if not text:
            return ""
        return "## 当前教材 Harness\n\n" + text

    def compact_prompt_section(self, max_chars: int = 2200) -> str:
        text = self.read().strip()
        if not text:
            return ""
        return "## 当前教材 Harness 摘要\n\n" + self.compact_text(text, max_chars=max_chars)

    @staticmethod
    def compact_text(text: str, max_chars: int = 2200) -> str:
        keep_sections = {
            "## 教材身份",
            "## 内容比例",
            "## 章节结构",
            "## 视觉策略",
            "## 风格边界",
            "## 代码与 Markdown",
            "## 字数统计",
            "## 用户补充备注",
        }
        lines = []
        current_keep = False
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                current_keep = stripped in keep_sections
            if current_keep and stripped:
                lines.append(line.rstrip())
        compact = "\n".join(lines).strip()
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars].rstrip() + "\n...[harness truncated]"

    @staticmethod
    def render(book_config: TextbookConfig, writing_spec: WritingSpec) -> str:
        ratio = writing_spec.content_ratio
        visual = writing_spec.visual_policy
        style = writing_spec.style_policy
        word_count = writing_spec.word_count_policy
        structure = "\n".join(f"- {item}" for item in writing_spec.chapter_structure)
        avoid = "\n".join(f"- {item}" for item in style.avoid)
        preferred_visuals = "、".join(visual.preferred_types)
        notes = writing_spec.additional_notes.strip() or "无"
        return (
            "# 教材 Harness\n\n"
            "<!-- managed-by: TextBookAgent BookHarness v1 -->\n\n"
            "本文件记录当前教材的执行约束。项目级安全、记忆、工具和状态规则优先级更高；"
            "本文件只补充当前教材的写作与生成要求。\n\n"
            "## 教材身份\n\n"
            f"- 教材 ID: {book_config.id}\n"
            f"- 教材名称: {book_config.title}\n"
            f"- 学科方向: {book_config.subject}\n"
            f"- 目标读者: {writing_spec.audience or book_config.target_audience}\n"
            f"- 难度层次: {writing_spec.difficulty or book_config.level}\n"
            f"- 教材定位: {writing_spec.learning_orientation}\n"
            f"- 总章节数: {book_config.total_chapters}\n"
            f"- 每章目标字数: {book_config.chapter_word_count}\n"
            f"- 更新时间: {datetime.now().isoformat()}\n\n"
            "## 内容比例\n\n"
            f"- 理论: {ratio.theory}%\n"
            f"- 案例: {ratio.case}%\n"
            f"- 流程: {ratio.procedure}%\n"
            f"- 实践: {ratio.practice}%\n"
            f"- 代码: {ratio.code}%\n\n"
            "## 章节结构\n\n"
            f"{structure}\n\n"
            "## 视觉策略\n\n"
            f"- 每章最少视觉资产: {visual.min_assets_per_chapter}\n"
            f"- 优先图表类型: {preferred_visuals}\n"
            "- 图片和图表必须表达真实结构、流程、数据关系或教学场景，不允许只是把提示词放进图片。\n\n"
            "## 风格边界\n\n"
            f"- 语气: {style.tone}\n"
            f"- 引用说明: {style.citation_style}\n"
            "- 避免项:\n"
            f"{avoid}\n"
            "- 普通概念不要频繁加双引号，不要为了显得独特而自造术语。\n\n"
            "## 代码与 Markdown\n\n"
            "- 所有代码必须使用 fenced code block 包裹，例如 ```python。\n"
            "- 未包裹的 `# 注释` 不应出现在正文中；需要解释代码时用自然语言或 fenced code block。\n\n"
            "## 字数统计\n\n"
            f"- 统计口径: {word_count.metric}\n"
            f"- 排除内容: {'、'.join(word_count.exclude)}\n"
            f"- 允许误差: {word_count.tolerance}\n\n"
            "## 用户补充备注\n\n"
            f"{notes}\n\n"
            "## 运行要求\n\n"
            "- 编写前读取当前大纲、章节状态、已有章节摘要和知识库证据。\n"
            "- 已完成章节不得被重新生成；确需修改时使用追加、局部替换或版本化保存。\n"
            "- 审查、修订、润色必须以本文件和 WritingSpec 为依据。\n"
        )

    @staticmethod
    def _managed_body(text: str) -> str:
        lines = []
        for line in (text or "").splitlines():
            if line.startswith("- 更新时间:"):
                continue
            lines.append(line.rstrip())
        return "\n".join(lines).strip()
