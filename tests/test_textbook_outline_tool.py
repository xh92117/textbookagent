import json
from pathlib import Path
from unittest.mock import patch

from agent.textbook.models.textbook import TextbookConfig
from bridge.textbook_bridge import TextbookBridge


def test_textbook_outline_tool_writes_outline_to_canonical_outline_path(tmp_path):
    from agent.tools.textbook_outline.textbook_outline import TextbookOutlineTool

    bridge = TextbookBridge(data_dir=str(tmp_path))
    book = bridge.create_textbook(TextbookConfig(title="Outline Book", total_chapters=2))
    outline = "# Outline Book\n\n## 第一章 绪论\n\n## 第二章 方法\n"

    with patch("bridge.textbook_bridge.get_bridge", return_value=bridge):
        result = TextbookOutlineTool().execute({
            "action": "write_outline",
            "book_id": book.id,
            "content": outline,
        })

    assert result.status == "success"
    assert result.result["path"] == "outline/outline.md"
    assert (Path(tmp_path) / book.id / "outline" / "outline.md").read_text(encoding="utf-8") == outline
    assert not (Path(tmp_path) / book.id / "chapters" / "chapter_001.md").exists()

    review_state = json.loads((Path(tmp_path) / book.id / "state" / "outline_review.json").read_text(encoding="utf-8"))
    assert review_state["status"] == "stale"


def test_textbook_outline_tool_writes_terminology_to_canonical_outline_path(tmp_path):
    from agent.tools.textbook_outline.textbook_outline import TextbookOutlineTool

    bridge = TextbookBridge(data_dir=str(tmp_path))
    book = bridge.create_textbook(TextbookConfig(title="Terms Book"))
    terminology = "# Terminology\n\n| 术语 | 解释 |\n|---|---|\n| 智能体 | 可调用工具的模型程序 |\n"

    with patch("bridge.textbook_bridge.get_bridge", return_value=bridge):
        result = TextbookOutlineTool().execute({
            "action": "write_terminology",
            "book_id": book.id,
            "content": terminology,
        })

    assert result.status == "success"
    assert result.result["path"] == "outline/terminology.md"
    assert (Path(tmp_path) / book.id / "outline" / "terminology.md").read_text(encoding="utf-8") == terminology


def test_textbook_outline_tool_reads_outline_and_terminology(tmp_path):
    from agent.tools.textbook_outline.textbook_outline import TextbookOutlineTool

    bridge = TextbookBridge(data_dir=str(tmp_path))
    book = bridge.create_textbook(TextbookConfig(title="Read Book"))
    bridge.update_outline(book.id, "# Outline\n")
    mgr = bridge._memory_manager.get_truth_manager(book.id)
    mgr.write("terminology", "# Terms\n")

    with patch("bridge.textbook_bridge.get_bridge", return_value=bridge):
        result = TextbookOutlineTool().execute({
            "action": "read",
            "book_id": book.id,
        })

    assert result.status == "success"
    assert result.result["outline"] == "# Outline\n"
    assert result.result["terminology"] == "# Terms\n"


def test_textbook_outline_tool_is_registered_in_tool_manager():
    from agent.tools import ToolManager

    manager = ToolManager()
    manager.load_tools()

    assert "textbook_outline" in manager.tool_classes
