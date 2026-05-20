from dataclasses import dataclass, field
from typing import List, Optional
import json

@dataclass
class OutlineNode:
    id: str = ""
    title: str = ""
    level: int = 0
    objective: str = ""
    key_results: List[str] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)
    key_concepts: List[str] = field(default_factory=list)
    cognitive_level: str = ""
    estimated_words: int = 0
    requires_chart: bool = False
    requires_code: bool = False
    children: List['OutlineNode'] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            'id': self.id,
            'title': self.title,
            'level': self.level,
            'objective': self.objective,
            'key_results': self.key_results,
            'prerequisites': self.prerequisites,
            'key_concepts': self.key_concepts,
            'cognitive_level': self.cognitive_level,
            'estimated_words': self.estimated_words,
            'requires_chart': self.requires_chart,
            'requires_code': self.requires_code,
            'children': [c.to_dict() for c in self.children]
        }
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> 'OutlineNode':
        children_data = data.pop('children', [])
        node = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        node.children = [cls.from_dict(c) for c in children_data]
        return node

    @classmethod
    def from_json(cls, json_str: str) -> 'OutlineNode':
        return cls.from_dict(json.loads(json_str))

    def find_by_id(self, node_id: str) -> Optional['OutlineNode']:
        if self.id == node_id:
            return self
        for child in self.children:
            found = child.find_by_id(node_id)
            if found:
                return found
        return None

    def get_all_chapters(self) -> List['OutlineNode']:
        result = []
        if self.level == 2:
            result.append(self)
        for child in self.children:
            result.extend(child.get_all_chapters())
        return result

    def count_descendants(self) -> int:
        return len(self.children) + sum(c.count_descendants() for c in self.children)
