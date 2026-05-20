import os
import re
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ChapterPlan:
    number: int
    title: str = ""
    objective: str = ""
    key_results: str = ""
    cognitive_level: str = ""
    prerequisites: str = ""
    key_concepts: List[str] = field(default_factory=list)
    raw_outline: str = ""

    def key_concepts_text(self) -> str:
        return "、".join(self.key_concepts)


class ContextPackageBuilder:
    """Deterministic, budgeted context assembly for long textbook projects."""

    DEFAULT_BUDGETS = {
        "outline_skeleton": 3500,
        "current_chapter_outline": 2200,
        "all_previous_summaries": 4200,
        "recent_chapters": 2600,
        "knowledge": 3600,
        "research": 2200,
        "terminology": 1200,
    }

    def __init__(self, memory_manager=None, budgets: Dict[str, int] = None):
        self.memory_manager = memory_manager
        self.budgets = {**self.DEFAULT_BUDGETS, **(budgets or {})}

    def build(
        self,
        book_id: str,
        chapter_number: int,
        outline_text: str = "",
        research_evidence: str = "",
        wiki_context: str = "",
        terminology=None,
    ) -> str:
        parts = []
        outline_skeleton = self._outline_skeleton(outline_text)
        current_outline = self._current_chapter_outline(outline_text, chapter_number)
        if outline_skeleton:
            parts.append("## 全书大纲骨架\n" + self._clip(outline_skeleton, "outline_skeleton"))
        if current_outline:
            parts.append(f"## 当前章节大纲（第{chapter_number}章）\n" + self._clip(current_outline, "current_chapter_outline"))

        previous = self._previous_summaries(book_id, chapter_number)
        if previous:
            parts.append("## 前序所有章节短摘要\n" + self._clip(previous, "all_previous_summaries"))

        recent = self._recent_chapter_context(book_id, chapter_number)
        if recent:
            parts.append("## 最近章节衔接材料\n" + self._clip(recent, "recent_chapters"))

        if wiki_context:
            parts.append("## 知识库精选证据\n" + self._clip(wiki_context, "knowledge"))
        if research_evidence:
            parts.append("## Web Evidence Pack / 已保存研究证据\n" + self._clip(research_evidence, "research"))

        terms = self._format_terms(terminology)
        if terms:
            parts.append("## 术语表（精选）\n" + self._clip(terms, "terminology"))

        parts.append(
            "## 写作连续性要求\n"
            "- 本章必须承接前序章节术语、架构和案例，不要重置全书叙事。\n"
            "- 如与前序章节概念重复，应使用交叉引用而不是大段重讲。\n"
            "- 优先补齐当前章节独有的方法、工程流程、测试标准和案例。"
        )
        return "\n\n".join(part for part in parts if part.strip())

    def _outline_skeleton(self, outline_text: str) -> str:
        lines = []
        for line in (outline_text or "").splitlines():
            stripped = line.strip()
            if re.match(r"^#{1,4}\s+", stripped):
                lines.append(stripped)
            elif stripped.startswith("- 教学目标") or stripped.startswith("- 核心概念") or stripped.startswith("- 需要图表"):
                lines.append(stripped)
        return "\n".join(lines)

    def _current_chapter_outline(self, outline_text: str, chapter_number: int) -> str:
        if not outline_text:
            return ""
        patterns = [
            rf"(?m)^##\s*第\s*{chapter_number}\s*章[^\n]*",
            rf"(?m)^##\s*第{chapter_number}章[^\n]*",
            rf"(?m)^##\s*Chapter\s+{chapter_number}\b[^\n]*",
        ]
        starts = []
        for pattern in patterns:
            match = re.search(pattern, outline_text, re.I)
            if match:
                starts.append(match.start())
        if not starts:
            return ""
        start = min(starts)
        next_match = re.search(r"(?m)^##\s*(?:第\s*\d+\s*章|第[一二三四五六七八九十百]+章|Chapter\s+\d+\b)", outline_text[start + 1:], re.I)
        end = start + 1 + next_match.start() if next_match else len(outline_text)
        return outline_text[start:end].strip()

    def extract_chapter_plan(self, outline_text: str, chapter_number: int) -> ChapterPlan:
        raw = self._current_chapter_outline(outline_text, chapter_number)
        plan = ChapterPlan(number=chapter_number, raw_outline=raw)
        if not raw:
            plan.title = f"第{chapter_number}章"
            return plan

        lines = [line.rstrip() for line in raw.splitlines()]
        heading = next((line.strip() for line in lines if line.lstrip().startswith("##")), "")
        if heading:
            title = re.sub(r"^#+\s*", "", heading).strip()
            title = re.sub(rf"^第\s*{chapter_number}\s*章\s*[:：、.-]?\s*", "", title).strip() or title
            title = re.sub(rf"^Chapter\s+{chapter_number}\b\s*[:：、.-]?\s*", "", title, flags=re.I).strip() or title
            plan.title = title
        else:
            plan.title = f"第{chapter_number}章"

        field_patterns = {
            "objective": ("教学目标", "学习目标", "目标"),
            "key_results": ("关键结果", "学习成果", "预期成果", "产出"),
            "cognitive_level": ("认知层次", "能力层次", "布鲁姆"),
            "prerequisites": ("前置知识", "先修知识", "基础要求"),
            "key_concepts": ("核心概念", "关键概念", "重点概念", "术语"),
        }
        for line in lines:
            stripped = line.strip().lstrip("-*0123456789.、 ").strip()
            for field_name, labels in field_patterns.items():
                label_re = "|".join(re.escape(label) for label in labels)
                match = re.match(rf"^(?:{label_re})\s*[:：]\s*(.+)$", stripped)
                if not match:
                    continue
                value = match.group(1).strip()
                if field_name == "key_concepts":
                    plan.key_concepts.extend(self._split_concepts(value))
                else:
                    setattr(plan, field_name, value)

        if not plan.key_concepts:
            concept_terms = []
            for line in lines:
                for match in re.finditer(r"\*\*([^*]{2,30})\*\*", line):
                    concept_terms.append(match.group(1).strip())
            plan.key_concepts = list(dict.fromkeys(concept_terms))[:12]
        return plan

    @staticmethod
    def _split_concepts(value: str) -> List[str]:
        parts = re.split(r"[、,，;/；]\s*", value or "")
        return [p.strip(" -_*`") for p in parts if p.strip(" -_*`")][:20]

    def _previous_summaries(self, book_id: str, chapter_number: int) -> str:
        mgr = self._truth(book_id)
        if not mgr:
            return ""
        existing = mgr.read("chapter_summaries")
        if existing.strip():
            return self._only_previous_summary_entries(existing, chapter_number)
        entries = []
        for i in range(1, chapter_number):
            text = mgr.read_chapter(i)
            if not text:
                continue
            title = self._first_heading(text) or f"第{i}章"
            summary = self._extract_summary(text) or self._plain_excerpt(text, 260)
            entries.append(f"### 第{i}章 {title}\n{summary}")
        return "\n\n".join(entries)

    def _recent_chapter_context(self, book_id: str, chapter_number: int, count: int = 2) -> str:
        mgr = self._truth(book_id)
        if not mgr:
            return ""
        blocks = []
        start = max(1, chapter_number - count)
        for i in range(start, chapter_number):
            text = mgr.read_chapter(i)
            if text:
                blocks.append(f"### 第{i}章衔接摘录\n{self._plain_excerpt(text[-1800:], 900)}")
        return "\n\n".join(blocks)

    def _truth(self, book_id: str):
        if not self.memory_manager:
            return None
        try:
            return self.memory_manager.get_truth_manager(book_id)
        except Exception:
            return None

    def _only_previous_summary_entries(self, text: str, chapter_number: int) -> str:
        blocks = re.split(r"(?m)(?=^##\s*第\s*\d+\s*章|^##\s*第\d+章)", text or "")
        kept = []
        for block in blocks:
            match = re.search(r"第\s*(\d+)\s*章|第(\d+)章", block)
            if match:
                num = int(match.group(1) or match.group(2))
                if num < chapter_number:
                    kept.append(block.strip())
        return "\n\n".join(kept) if kept else text

    def _extract_summary(self, text: str) -> str:
        lines = text.splitlines()
        out = []
        capture = False
        for line in lines:
            if "本章小结" in line or re.match(r"^##\s*小结", line):
                capture = True
                continue
            if capture and line.startswith("## ") and "小结" not in line:
                break
            if capture:
                out.append(line)
        return self._plain_excerpt("\n".join(out), 360)

    def _first_heading(self, text: str) -> str:
        for line in text.splitlines():
            if line.startswith("#"):
                return line.lstrip("#").strip()
        return ""

    def _format_terms(self, terminology) -> str:
        if not terminology:
            return ""
        if isinstance(terminology, dict):
            rows = []
            for idx, (key, value) in enumerate(sorted(terminology.items()), start=1):
                if idx > 40:
                    break
                rows.append(f"- {key}: {value}")
            return "\n".join(rows)
        return str(terminology)

    def _plain_excerpt(self, text: str, max_chars: int) -> str:
        text = re.sub(r"```[\s\S]*?```", "[代码示例略]", text or "")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text[:max_chars].rstrip() + ("..." if len(text) > max_chars else "")

    def _clip(self, text: str, budget_key: str) -> str:
        max_chars = self.budgets.get(budget_key, 2000)
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n...[已按上下文预算截断]"
