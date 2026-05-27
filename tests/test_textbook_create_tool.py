import json
from pathlib import Path
from unittest.mock import patch

from agent.tools.textbook_create.textbook_create import CreateTextbookTool
from bridge.textbook_bridge import TextbookBridge


def test_create_textbook_tool_uses_canonical_bridge_and_writes_config(tmp_path):
    bridge = TextbookBridge(data_dir=str(tmp_path))

    with patch("bridge.textbook_bridge.get_bridge", return_value=bridge):
        result = CreateTextbookTool().execute({
            "title": "AI Created Textbook",
            "subject": "AI",
            "target_audience": "本科生",
            "total_chapters": 6,
        })

    assert result.status == "success"
    book_id = result.result["book_id"]
    config_path = Path(tmp_path) / book_id / "textbook.json"
    assert config_path.exists()

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["id"] == book_id
    assert saved["title"] == "AI Created Textbook"
    assert saved["total_chapters"] == 6


def test_create_textbook_tool_reuses_existing_title(tmp_path):
    bridge = TextbookBridge(data_dir=str(tmp_path))

    with patch("bridge.textbook_bridge.get_bridge", return_value=bridge):
        first = CreateTextbookTool().execute({"title": "Existing"})
        second = CreateTextbookTool().execute({"title": "Existing"})

    assert first.status == "success"
    assert second.status == "success"
    assert second.result["created"] is False
    assert second.result["book_id"] == first.result["book_id"]
