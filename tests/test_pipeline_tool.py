import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent.textbook.models.textbook import TextbookConfig
from agent.tools.pipeline.pipeline_tool import StartPipeline


class FakeBridge:
    def __init__(self):
        self.started = []
        self.textbooks = [
            TextbookConfig(
                id="tb_existing",
                title="Existing Book",
                subject="AI",
                target_audience="本科生",
                level="中级",
                total_chapters=8,
                chapter_word_count=3000,
                style="实务",
            )
        ]

    def get_textbook(self, book_id):
        return next((tb for tb in self.textbooks if tb.id == book_id), None)

    def list_textbooks(self):
        return self.textbooks

    def start_pipeline(self, book_id, sse_queue=None, requirement=""):
        self.started.append(book_id)
        return {"status": "running", "started_at": "now", "resume_from": "compose"}


def test_start_pipeline_finds_existing_textbook_config_by_title():
    bridge = FakeBridge()
    with patch("bridge.textbook_bridge.get_bridge", return_value=bridge):
        result = StartPipeline().execute({"title": "Existing Book", "confirm_pipeline_risk": True})

    assert result.status == "success"
    assert result.result["book_id"] == "tb_existing"
    assert result.result["pipeline_status"]["resume_from"] == "compose"
    assert bridge.started == ["tb_existing"]


def test_start_pipeline_requires_explicit_user_confirmation():
    bridge = FakeBridge()
    with patch("bridge.textbook_bridge.get_bridge", return_value=bridge):
        result = StartPipeline().execute({"title": "Existing Book"})

    assert result.status == "error"
    assert "confirm_pipeline_risk" in result.result
    assert bridge.started == []
