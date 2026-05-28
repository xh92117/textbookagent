import json
import os

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
        "allow_overwrite": True,
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


def test_textbook_chapter_requires_explicit_overwrite_for_existing_long_chapter(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    full_content = "# Chapter\n\n" + ("long section\n" * 300)
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 3,
        "content": full_content,
    }).status == "success"

    rewritten = "# Chapter\n\n" + ("replacement section\n" * 300)
    blocked = tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 3,
        "content": rewritten,
    })
    assert blocked.status == "error"
    assert "allow_overwrite=true" in str(blocked.result)
    assert bridge.get_chapter(book.id, 3) == full_content

    allowed = tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 3,
        "content": rewritten,
        "allow_overwrite": True,
    })
    assert allowed.status == "success"
    assert bridge.get_chapter(book.id, 3) == rewritten


def test_textbook_chapter_rewrite_replaces_existing_and_updates_index(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    old_content = (
        "# 第3章 原章节\n\n"
        "## 3.1 旧内容\n\n"
        + ("旧段落。\n" * 260)
        + "\n## 本章小结\n\n旧小结。\n\n## 3.4 残留尾巴\n\n不应保留。\n"
    )
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 3,
        "content": old_content,
    }).status == "success"

    new_content = (
        "# 第3章 智能体开发实践\n\n"
        "## 3.1 应用场景识别\n\n"
        + ("围绕岗位任务分析智能体能承担的资料整理、检查和辅助决策工作。\n" * 35)
        + "\n### 3.1.1 场景边界\n\n"
        + ("说明输入、输出、责任人和验收标准。\n" * 35)
        + "\n## 3.2 工作流设计\n\n"
        + ("把任务拆成资料收集、规则检查、结果复核三个步骤。\n" * 35)
        + "\n## 本章小结\n\n"
        + ("本章强调面向应用的设计流程。\n" * 25)
        + "\n## 习题\n\n1. 设计一个施工记录整理智能体。\n"
    )

    rewritten = tool.execute({
        "action": "rewrite_chapter",
        "book_id": book.id,
        "chapter_num": 3,
        "content": new_content,
        "completed": True,
    })
    assert rewritten.status == "success"
    assert rewritten.result["action"] == "rewritten"
    assert rewritten.result["structure"]["fatal_issues"] == []
    assert os.path.exists(rewritten.result["backup_path"])
    chapter = bridge.get_chapter(book.id, 3)
    assert "残留尾巴" not in chapter
    assert "应用场景识别" in chapter

    index_path = os.path.join(bridge.get_book_dir(book.id), "state", "chapter_index.json")
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)
    entry = index["chapters"]["3"]
    assert entry["status"] == "ok"
    assert entry["last_operation"] == "rewrite_chapter"
    assert entry["content_hash"] == rewritten.result["content_hash"]


def test_textbook_chapter_validate_structure_detects_tail_and_duplicate_headings(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    malformed = (
        "# \u7b2c3\u7ae0 \u7ed3\u6784\u6c61\u67d3\n\n"
        "## 3.1 \u6b63\u5e38\u5c0f\u8282\n\n"
        + ("\u5185\u5bb9\u3002\n" * 260)
        + "\n## \u672c\u7ae0\u5c0f\u7ed3\n\n\u5c0f\u7ed3\u3002\n\n"
        "## \u4e60\u9898\n\n\u7ec3\u4e60\u3002\n\n"
        "## 3.4 \u6b8b\u7559\u5c3e\u5df4\n\n\u6c61\u67d3\u5185\u5bb9\u3002\n\n"
        "## 3.4 \u6b8b\u7559\u5c3e\u5df4\n\n\u91cd\u590d\u5185\u5bb9\u3002\n\n"
        "### 3.5.1 \u9519\u4f4d\u4e09\u7ea7\u6807\u9898\n\n\u9519\u4f4d\u5185\u5bb9\u3002\n"
    )
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 3,
        "content": malformed,
    }).status == "success"

    report = tool.execute({
        "action": "validate_structure",
        "book_id": book.id,
        "chapter_num": 3,
    })
    assert report.status == "success"
    assert report.result["ok"] is False
    assert any("duplicate heading" in issue for issue in report.result["fatal_issues"])
    assert any("after summary/exercises" in issue for issue in report.result["fatal_issues"])

    completed = tool.execute({
        "action": "mark_completed",
        "book_id": book.id,
        "chapter_num": 3,
    })
    assert completed.status == "error"
    assert completed.result["structure"]["fatal_issues"]


def test_textbook_chapter_validate_structure_ignores_fenced_code_comments(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    content = (
        "# 第2章 环境搭建\n\n"
        "## 2.1 Python 环境\n\n"
        + ("通过安装、检查和运行示例完成环境搭建。\n" * 80)
        + "\n```python\n# 这只是代码注释\nprint('hello')\n# 这不是标题\n```\n\n"
        "## 本章小结\n\n"
        + ("代码块中的井号注释不能污染标题结构。\n" * 35)
    )
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 2,
        "content": content,
    }).status == "success"

    report = tool.execute({
        "action": "validate_structure",
        "book_id": book.id,
        "chapter_num": 2,
    })
    assert report.status == "success"
    assert report.result["fatal_issues"] == []
    heading_text = "\n".join(h["text"] for h in report.result["headings"])
    assert "这只是代码注释" not in heading_text


def test_textbook_chapter_replace_section_ignores_headings_inside_code_fences(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    content = (
        "# 第4章 智能体范式\n\n"
        "## 4.1 ReAct 模式\n\n"
        + ("应用说明。\n" * 180)
        + "\n```python\n# ==== System Prompt 模板 ====\nSYSTEM_PROMPT = 'demo'\n```\n\n"
        "## 4.2 Plan-and-Solve 模式\n\n"
        + ("后续内容必须保留。\n" * 180)
        + "\n## 本章小结\n\n"
        + ("总结内容。\n" * 80)
    )
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 4,
        "content": content,
    }).status == "success"

    blocked = tool.execute({
        "action": "replace_section",
        "book_id": book.id,
        "chapter_num": 4,
        "heading": "# ==== System Prompt 模板 ====",
        "content": "<!-- System Prompt 模板代码 -->",
    })

    assert blocked.status == "error"
    assert "level-1 headings" in str(blocked.result) or "section not found" in str(blocked.result)
    saved = bridge.get_chapter(book.id, 4)
    assert saved == content
    assert "## 4.2 Plan-and-Solve 模式" in saved
    assert "后续内容必须保留" in saved


def test_textbook_chapter_replace_section_rejects_large_accidental_shrink(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    content = (
        "# 第4章 智能体范式\n\n"
        "## 4.1 ReAct 模式\n\n"
        + ("较长内容。\n" * 500)
        + "\n## 4.2 Plan-and-Solve 模式\n\n"
        + ("后续内容。\n" * 500)
    )
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 4,
        "content": content,
    }).status == "success"

    blocked = tool.execute({
        "action": "replace_section",
        "book_id": book.id,
        "chapter_num": 4,
        "heading": "## 4.1 ReAct 模式",
        "content": "## 4.1 ReAct 模式\n\n短替换。",
    })

    assert blocked.status == "error"
    assert "large portion" in str(blocked.result)
    assert bridge.get_chapter(book.id, 4) == content


def test_textbook_chapter_lists_and_restores_backup_without_full_content_payload(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    clean = "# Chapter 1\n\n## 1.1 Clean\n\n" + ("clean line\n" * 200)
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 1,
        "content": clean,
    }).status == "success"

    damaged = "# Chapter 1\n\n## 1.1 Damaged\n\n" + ("broken line\n" * 120)
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 1,
        "content": damaged,
        "allow_overwrite": True,
    }).status == "success"

    backups = tool.execute({
        "action": "list_backups",
        "book_id": book.id,
        "chapter_num": 1,
    })
    assert backups.status == "success"
    assert backups.result["backups"]
    backup_id = backups.result["backups"][0]["backup_id"]

    restored = tool.execute({
        "action": "restore_backup",
        "book_id": book.id,
        "chapter_num": 1,
        "backup_id": backup_id,
    })
    assert restored.status == "success"
    assert restored.result["action"] == "restored_backup"
    assert bridge.get_chapter(book.id, 1) == clean


def test_textbook_chapter_rename_heading_changes_only_heading_line(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    content = "# Chapter 2\n\n## 2.1 Old Title\n\nbody stays\n\n### 2.1.1 Child\n\nchild stays\n"
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 2,
        "content": content,
    }).status == "success"

    result = tool.execute({
        "action": "rename_heading",
        "book_id": book.id,
        "chapter_num": 2,
        "heading": "## 2.1 Old Title",
        "new_heading": "## 2.1 New Title",
    })
    assert result.status == "success"
    saved = bridge.get_chapter(book.id, 2)
    assert "## 2.1 New Title" in saved
    assert "## 2.1 Old Title" not in saved
    assert "body stays" in saved
    assert "### 2.1.1 Child" in saved


def test_textbook_chapter_delete_section_removes_section_instead_of_reinserting_heading(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    content = "# Chapter 3\n\n## 3.1 Keep\n\nkeep\n\n### 3.1.1 Duplicate\n\nremove me\n\n### 3.1.2 Next\n\nnext\n"
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 3,
        "content": content,
    }).status == "success"

    result = tool.execute({
        "action": "delete_section",
        "book_id": book.id,
        "chapter_num": 3,
        "heading": "### 3.1.1 Duplicate",
    })
    assert result.status == "success"
    saved = bridge.get_chapter(book.id, 3)
    assert "### 3.1.1 Duplicate" not in saved
    assert "remove me" not in saved
    assert "## 3.1 Keep" in saved
    assert "### 3.1.2 Next" in saved


def test_textbook_chapter_replace_exact_requires_unique_match(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    content = "# Chapter 1\n\n## 1.1 A\n\nold phrase\n\n## 1.2 B\n\nold phrase\n"
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 1,
        "content": content,
    }).status == "success"

    duplicate = tool.execute({
        "action": "replace_exact",
        "book_id": book.id,
        "chapter_num": 1,
        "old_text": "old phrase",
        "new_text": "new phrase",
    })
    assert duplicate.status == "error"
    assert "unique" in str(duplicate.result)

    result = tool.execute({
        "action": "replace_exact",
        "book_id": book.id,
        "chapter_num": 1,
        "old_text": "## 1.2 B\n\nold phrase",
        "new_text": "## 1.2 B\n\nnew phrase",
    })
    assert result.status == "success"
    saved = bridge.get_chapter(book.id, 1)
    assert "## 1.1 A\n\nold phrase" in saved
    assert "## 1.2 B\n\nnew phrase" in saved


def test_textbook_chapter_backups_are_not_overwritten_within_same_second(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    book = _book(bridge)
    monkeypatch.setattr("bridge.textbook_bridge.get_bridge", lambda: bridge)

    tool = TextbookChapterTool()
    original = "# Chapter 1\n\n## 1.1 A\n\n" + ("first\n" * 100)
    second = "# Chapter 1\n\n## 1.1 B\n\n" + ("second\n" * 100)
    third = "# Chapter 1\n\n## 1.1 C\n\n" + ("third\n" * 100)

    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 1,
        "content": original,
    }).status == "success"
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 1,
        "content": second,
        "allow_overwrite": True,
    }).status == "success"
    assert tool.execute({
        "action": "write_chapter",
        "book_id": book.id,
        "chapter_num": 1,
        "content": third,
        "allow_overwrite": True,
    }).status == "success"

    backups = tool.execute({
        "action": "list_backups",
        "book_id": book.id,
        "chapter_num": 1,
    })
    assert backups.status == "success"
    assert backups.result["backup_count"] >= 2
    backup_ids = [item["backup_id"] for item in backups.result["backups"]]
    assert len(backup_ids) == len(set(backup_ids))
