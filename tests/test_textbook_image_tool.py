import os

from agent.textbook.models.textbook import TextbookConfig
from agent.tools.textbook_image.textbook_image import TextbookImageTool
from bridge.textbook_bridge import TextbookBridge


def test_textbook_image_tool_creates_local_fallback(tmp_path, monkeypatch):
    bridge = TextbookBridge(data_dir=str(tmp_path))
    book = bridge.create_textbook(TextbookConfig(
        title="Textbook",
        subject="Civil engineering",
        target_audience="Students",
        level="Intro",
        total_chapters=1,
    ))
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    result = TextbookImageTool().execute({
        "book_id": book.id,
        "description": "A clear process diagram for textbook testing",
        "chapter_num": 1,
        "figure_num": 1,
        "title": "Figure 1-1 Test Diagram",
        "generate_remote": False,
    })

    assert result.status == "success"
    assert result.result["source"] == "local_fallback"
    assert result.result["relative_path"].startswith("assets/images/")
    assert result.result["markdown"].startswith("![Figure 1-1")
    assert "prompt" in result.result
    assert "prompt_path" not in result.result
    assert os.path.exists(result.result["path"])


def test_textbook_image_tool_returns_prompt_note_when_fallback_fails(tmp_path, monkeypatch):
    bridge = TextbookBridge(data_dir=str(tmp_path))
    book = bridge.create_textbook(TextbookConfig(
        title="Textbook",
        subject="Civil engineering",
        target_audience="Students",
        level="Intro",
        total_chapters=1,
    ))
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    def fail_placeholder(self, path, title, description):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(TextbookImageTool, "_create_placeholder", fail_placeholder)
    result = TextbookImageTool().execute({
        "book_id": book.id,
        "description": "A clear process diagram for textbook testing",
        "chapter_num": 1,
        "figure_num": 1,
        "title": "Figure 1-1 Test Diagram",
        "generate_remote": False,
    })

    assert result.status == "success"
    assert result.result["status"] == "prompt_only"
    assert result.result["source"] == "prompt_note"
    assert "prompt_note_markdown" in result.result
    assert "生成提示词" in result.result["prompt_note_markdown"]
