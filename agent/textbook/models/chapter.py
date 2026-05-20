from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json

@dataclass
class Exercise:
    question: str = ""
    exercise_type: str = ""
    difficulty: str = ""
    answer: str = ""
    hint: str = ""

@dataclass
class ChartReq:
    description: str = ""
    chart_type: str = ""
    data_description: str = ""
    code_snippet: str = ""

@dataclass
class ImageReq:
    description: str = ""
    image_type: str = ""
    prompt_hint: str = ""
    size: str = "landscape_4_3"

@dataclass
class Chapter:
    number: int = 0
    title: str = ""
    outline_node_id: str = ""
    content: str = ""
    key_points: List[str] = field(default_factory=list)
    terminology: Dict[str, str] = field(default_factory=dict)
    exercises: List[Exercise] = field(default_factory=list)
    chart_requirements: List[ChartReq] = field(default_factory=list)
    image_requirements: List[ImageReq] = field(default_factory=list)
    summary: str = ""
    word_count: int = 0
    status: str = "draft"
    review_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            'number': self.number,
            'title': self.title,
            'outline_node_id': self.outline_node_id,
            'content': self.content,
            'key_points': self.key_points,
            'terminology': self.terminology,
            'exercises': [{'question': e.question, 'exercise_type': e.exercise_type, 'difficulty': e.difficulty, 'answer': e.answer, 'hint': e.hint} for e in self.exercises],
            'chart_requirements': [{'description': c.description, 'chart_type': c.chart_type, 'data_description': c.data_description, 'code_snippet': c.code_snippet} for c in self.chart_requirements],
            'image_requirements': [{'description': i.description, 'image_type': i.image_type, 'prompt_hint': i.prompt_hint, 'size': i.size} for i in self.image_requirements],
            'summary': self.summary,
            'word_count': self.word_count,
            'status': self.status,
            'review_score': self.review_score,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> 'Chapter':
        exercises = [Exercise(**e) for e in data.pop('exercises', [])]
        charts = [ChartReq(**c) for c in data.pop('chart_requirements', [])]
        images = [ImageReq(**i) for i in data.pop('image_requirements', [])]
        ch = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        ch.exercises = exercises
        ch.chart_requirements = charts
        ch.image_requirements = images
        return ch

    @classmethod
    def from_json(cls, json_str: str) -> 'Chapter':
        return cls.from_dict(json.loads(json_str))
