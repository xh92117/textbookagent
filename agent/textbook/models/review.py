from dataclasses import dataclass, field
from typing import List, Optional
import json

@dataclass
class DimensionResult:
    name: str = ""
    score: float = 0.0
    comment: str = ""

@dataclass
class Issue:
    level: str = ""
    dimension: str = ""
    description: str = ""
    suggestion: str = ""
    location: str = ""

@dataclass
class ReviewResult:
    passed: bool = False
    score: float = 0.0
    dimensions: List[DimensionResult] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'passed': self.passed,
            'score': self.score,
            'dimensions': [{'name': d.name, 'score': d.score, 'comment': d.comment} for d in self.dimensions],
            'issues': [{'level': i.level, 'dimension': i.dimension, 'description': i.description, 'suggestion': i.suggestion, 'location': i.location} for i in self.issues],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> 'ReviewResult':
        dimensions = [DimensionResult(**d) for d in data.pop('dimensions', [])]
        issues = [Issue(**i) for i in data.pop('issues', [])]
        r = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        r.dimensions = dimensions
        r.issues = issues
        return r

    @classmethod
    def from_json(cls, json_str: str) -> 'ReviewResult':
        return cls.from_dict(json.loads(json_str))

    def get_critical_issues(self) -> List[Issue]:
        return [i for i in self.issues if i.level == 'critical']

    def get_warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == 'warning']
