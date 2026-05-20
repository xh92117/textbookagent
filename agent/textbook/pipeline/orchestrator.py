import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import List


@dataclass
class ChapterAction:
    name: str
    label: str
    status: str = "pending"
    reason: str = ""
    required: bool = True
    inputs: dict = field(default_factory=dict)
    output_summary: str = ""
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0


class ChapterOrchestrator:
    """Semantic action planner for chapter production.

    This is intentionally deterministic by default: it gives us the shape of an
    agent-selected skill workflow without adding another model request. Later,
    a model planner can replace ``plan`` while the executor/checkpoint contract
    stays stable.
    """

    def plan(self, chapter_number: int, outline_text: str = "", has_knowledge: bool = True) -> List[ChapterAction]:
        actions = [
            ChapterAction("read_outline", "读取当前章节大纲", reason="anchor chapter in the global textbook outline"),
            ChapterAction("retrieve_knowledge", "检索知识库证据", reason="ground chapter with LLM-WIKI metadata", required=has_knowledge),
            ChapterAction("build_context", "组装低上下文写作包", reason="preserve all previous chapter continuity with budgets"),
            ChapterAction("write_chapter", "调用写作子智能体", reason="draft chapter content"),
            ChapterAction("route_visual_assets", "路由图表与插图资产", reason="prefer code/knowledge assets before image model"),
            ChapterAction("review_chapter", "调用教材审核子智能体", reason="score correctness and continuity"),
            ChapterAction("revise_chapter", "按需修订章节", reason="only run if review detects issues", required=False),
            ChapterAction("polish_chapter", "调用润色子智能体", reason="normalize style and readability"),
            ChapterAction("persist_chapter", "保存章节与更新状态", reason="checkpoint durable output"),
        ]
        return actions


class PipelineCheckpointStore:
    def __init__(self, book_dir: str):
        self.book_dir = book_dir
        self.dir = os.path.join(book_dir, "state", "pipeline_checkpoints")
        os.makedirs(self.dir, exist_ok=True)

    def save(self, chapter_number: int, actions: List[ChapterAction], extra: dict = None):
        payload = {
            "chapter_number": chapter_number,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "actions": [asdict(action) for action in actions],
            "extra": extra or {},
        }
        path = os.path.join(self.dir, f"chapter_{chapter_number:02d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def mark(actions: List[ChapterAction], name: str, status: str, output_summary: str = "", error: str = ""):
        now = time.time()
        for action in actions:
            if action.name == name:
                if status == "running":
                    action.started_at = action.started_at or now
                if status in ("completed", "skipped", "failed"):
                    action.completed_at = now
                action.status = status
                action.output_summary = output_summary
                action.error = error
                break
