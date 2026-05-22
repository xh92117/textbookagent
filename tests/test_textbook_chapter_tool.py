from agent.textbook.models.textbook import TextbookConfig
from agent.tools.textbook_chapter.textbook_chapter import TextbookChapterTool
from bridge.textbook_bridge import TextbookBridge


def _bridge(tmp_path):
    return TextbookBridge(data_dir=str(tmp_path))


def _book(bridge):
    return bridge.create_textbook(TextbookConfig(
        title="教材",
        subject="土木工程",
        target_audience="本科生",
        level="入门",
        total_chapters=3,
    ))


def test_textbook_chapter_append_replace_and_validate(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    result = tool.execute({
        "action": "append_section",
        "book_id": book.id,
        "chapter_num": 2,
        "heading": "## 2.1 环境准备",
        "content": "安装 Python，并配置虚拟环境。",
    })
    assert result.status == "success"
    assert "环境准备" in bridge.get_chapter(book.id, 2)

    result = tool.execute({
        "action": "replace_section",
        "book_id": book.id,
        "chapter_num": 2,
        "heading": "## 2.1 环境准备",
        "content": "安装 Python 3.12，并配置虚拟环境。",
        "completed": True,
    })
    assert result.status == "success"
    content = bridge.get_chapter(book.id, 2)
    assert "Python 3.12" in content
    assert "安装 Python，并配置" not in content

    validation = tool.execute({
        "action": "validate_encoding",
        "book_id": book.id,
        "chapter_num": 2,
    })
    assert validation.status == "success"
    assert validation.result["utf8_decode_ok"] is True
    assert validation.result["likely_mojibake"] is False

    status = bridge._memory_manager.get_truth_manager(book.id).get_status()
    assert status["current_chapter"] == 2
    assert status["current_phase"] == "persist_chapter"


def test_textbook_chapter_appends_duplicate_heading_and_accepts_large_chunks(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    first = tool.execute({
        "action": "append_section",
        "book_id": book.id,
        "chapter_num": 1,
        "heading": "## 1.1 绪论",
        "content": "内容",
    })
    assert first.status == "success"

    duplicate = tool.execute({
        "action": "append_section",
        "book_id": book.id,
        "chapter_num": 1,
        "heading": "## 1.1 绪论",
        "content": "重复内容",
    })
    assert duplicate.status == "success"
    assert duplicate.result["action"] == "appended_existing"
    chapter = bridge.get_chapter(book.id, 1)
    assert "内容" in chapter
    assert "重复内容" in chapter

    huge = tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 1,
        "content": "太长" * 7000,
    })
    assert huge.status == "success"
    assert huge.result["warning"].startswith("Large content accepted")


def test_textbook_chapter_rejects_placeholder_overwrite_and_marks_completed(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    full_content = "# Chapter\n\n" + ("safe content\n" * 300)
    written = tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 1,
        "content": full_content,
    })
    assert written.status == "success"

    blocked = tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 1,
        "content": "placeholder",
        "completed": True,
    })
    assert blocked.status == "error"
    assert "placeholder" in str(blocked.result)
    assert bridge.get_chapter(book.id, 1) == full_content

    completed = tool.execute({
        "action": "mark_completed",
        "book_id": book.id,
        "chapter_num": 1,
    })
    assert completed.status == "success"
    assert completed.result["action"] == "completed"
    assert bridge.get_chapter(book.id, 1) == full_content
    meta = bridge._memory_manager.get_truth_manager(book.id).get_chapter_metadata(1)
    assert meta["status"] == "completed"


def test_textbook_chapter_rejects_short_full_overwrite_of_existing_long_chapter(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    full_content = "# Chapter\n\n" + ("long section\n" * 300)
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 2,
        "content": full_content,
    }).status == "success"

    blocked = tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 2,
        "content": "# Chapter\n\nshort",
    })
    assert blocked.status == "error"
    assert "dangerous full-chapter overwrite" in str(blocked.result)
    assert bridge.get_chapter(book.id, 2) == full_content
