from dataclasses import dataclass, field, asdict
from typing import Optional
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
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = _new_textbook_id()
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

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

