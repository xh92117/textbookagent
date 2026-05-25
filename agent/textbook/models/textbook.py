from dataclasses import dataclass, field, asdict
from typing import Optional, List
import json
import re
import uuid
from datetime import datetime

def _new_textbook_id() -> str:
    return f"tb_{uuid.uuid4().hex[:8]}"


def _slugify(title: str) -> str:
    if not title:
        return _new_textbook_id()
    slug = title.strip()
    slug = re.sub(r'[\\/:*?"<>|]', '', slug)
    slug = re.sub(r'\s+', '_', slug)
    slug = slug[:60]
    if not slug:
        return _new_textbook_id()
    return slug


@dataclass
class ContentRatio:
    theory: int = 25
    case: int = 25
    procedure: int = 20
    practice: int = 20
    code: int = 10


@dataclass
class VisualPolicy:
    min_assets_per_chapter: int = 1
    preferred_types: List[str] = field(default_factory=lambda: ["流程图", "结构图", "对比表", "场景图"])


@dataclass
class StylePolicy:
    tone: str = "教材式、清晰、直接"
    avoid: List[str] = field(default_factory=lambda: ["过度比喻", "自造概念", "频繁双引号", "口号化表达"])
    citation_style: str = "简洁来源说明"


@dataclass
class WordCountPolicy:
    metric: str = "正文有效中文字符数"
    exclude: List[str] = field(default_factory=lambda: ["JSON", "Markdown标记", "代码块", "图表标记"])
    tolerance: float = 0.15


@dataclass
class WritingSpec:
    """Project-level writing contract shared by all textbook agents."""

    audience: str = ""
    learning_orientation: str = "应用型"
    difficulty: str = ""
    content_ratio: ContentRatio = field(default_factory=ContentRatio)
    chapter_structure: List[str] = field(default_factory=lambda: ["学习目标", "知识讲解", "案例分析", "实践任务", "本章小结", "习题"])
    visual_policy: VisualPolicy = field(default_factory=VisualPolicy)
    style_policy: StylePolicy = field(default_factory=StylePolicy)
    word_count_policy: WordCountPolicy = field(default_factory=WordCountPolicy)
    additional_notes: str = ""

    @classmethod
    def default_for(cls, target_audience: str = "", level: str = "", style: str = "") -> "WritingSpec":
        text = " ".join([target_audience or "", level or "", style or ""]).lower()
        spec = cls(audience=target_audience or "", difficulty=level or "")
        if any(token in text for token in ["高职", "职业", "中职", "技校", "实训", "应用"]):
            spec.learning_orientation = "应用型/实训型"
            spec.content_ratio = ContentRatio(theory=15, case=30, procedure=25, practice=25, code=5)
            spec.chapter_structure = ["学习目标", "任务场景", "知识准备", "操作流程", "应用案例", "实训任务", "本章小结", "习题"]
            spec.visual_policy = VisualPolicy(min_assets_per_chapter=2, preferred_types=["流程图", "场景图", "操作步骤图", "对比表"])
        elif any(token in text for token in ["研究生", "高级", "理论", "学术", "论文"]):
            spec.learning_orientation = "理论研究型"
            spec.content_ratio = ContentRatio(theory=45, case=15, procedure=10, practice=10, code=20)
            spec.chapter_structure = ["学习目标", "理论基础", "方法原理", "案例或实验", "拓展阅读", "本章小结", "习题"]
            spec.visual_policy = VisualPolicy(min_assets_per_chapter=1, preferred_types=["机制图", "模型结构图", "对比表"])
        elif any(token in text for token in ["编程", "程序", "开发", "代码", "软件"]):
            spec.learning_orientation = "项目开发型"
            spec.content_ratio = ContentRatio(theory=20, case=20, procedure=20, practice=20, code=20)
            spec.chapter_structure = ["学习目标", "项目场景", "知识准备", "实现步骤", "代码示例", "调试与拓展", "本章小结", "习题"]
            spec.visual_policy = VisualPolicy(min_assets_per_chapter=1, preferred_types=["架构图", "流程图", "时序图"])
        return spec

    @classmethod
    def from_dict(cls, data: dict) -> "WritingSpec":
        if not isinstance(data, dict):
            return cls()
        return cls(
            audience=data.get("audience", ""),
            learning_orientation=data.get("learning_orientation", "应用型"),
            difficulty=data.get("difficulty", ""),
            content_ratio=ContentRatio(**{**asdict(ContentRatio()), **(data.get("content_ratio") or {})}),
            chapter_structure=list(data.get("chapter_structure") or cls().chapter_structure),
            visual_policy=VisualPolicy(**{**asdict(VisualPolicy()), **(data.get("visual_policy") or {})}),
            style_policy=StylePolicy(**{**asdict(StylePolicy()), **(data.get("style_policy") or {})}),
            word_count_policy=WordCountPolicy(**{**asdict(WordCountPolicy()), **(data.get("word_count_policy") or {})}),
            additional_notes=data.get("additional_notes", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class TextbookConfig:
    id: str = ""
    title: str = ""
    subject: str = ""
    target_audience: str = ""
    level: str = ""
    total_chapters: int = 0
    chapter_word_count: int = 5000
    style: str = "学术"
    curriculum_standard: str = ""
    status: str = "planning"
    language: str = "zh"
    writing_spec: WritingSpec = field(default_factory=WritingSpec)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = _new_textbook_id()
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
        if isinstance(self.writing_spec, dict):
            self.writing_spec = WritingSpec.from_dict(self.writing_spec)
        try:
            self.total_chapters = int(self.total_chapters or 0)
        except (TypeError, ValueError):
            raise ValueError("total_chapters must be an integer")
        try:
            self.chapter_word_count = int(self.chapter_word_count if self.chapter_word_count not in (None, "") else 5000)
        except (TypeError, ValueError):
            raise ValueError("chapter_word_count must be an integer")
        if self.total_chapters < 0 or self.total_chapters > 200:
            raise ValueError("total_chapters must be between 0 and 200")
        if self.chapter_word_count < 100 or self.chapter_word_count > 100000:
            raise ValueError("chapter_word_count must be between 100 and 100000")
        self.language = str(self.language or "zh").strip()[:16] or "zh"
        if self.writing_spec == WritingSpec():
            self.writing_spec = WritingSpec.default_for(self.target_audience, self.level, self.style)
        if not self.writing_spec.audience:
            self.writing_spec.audience = self.target_audience
        if not self.writing_spec.difficulty:
            self.writing_spec.difficulty = self.level

    def ensure_writing_spec(self) -> WritingSpec:
        if not isinstance(self.writing_spec, WritingSpec):
            self.writing_spec = WritingSpec.from_dict(self.writing_spec)
        if self.writing_spec == WritingSpec():
            self.writing_spec = WritingSpec.default_for(self.target_audience, self.level, self.style)
        if not self.writing_spec.audience:
            self.writing_spec.audience = self.target_audience
        if not self.writing_spec.difficulty:
            self.writing_spec.difficulty = self.level
        return self.writing_spec

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> 'TextbookConfig':
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    @classmethod
    def from_json(cls, json_str: str) -> 'TextbookConfig':
        return cls.from_dict(json.loads(json_str))

    def save(self, filepath: str):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, filepath: str) -> 'TextbookConfig':
        with open(filepath, 'r', encoding='utf-8') as f:
            return cls.from_json(f.read())

