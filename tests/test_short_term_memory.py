import json

from agent.memory.short_term import ShortTermMemoryPool


def test_short_term_memory_detects_task_boundary_and_resets_active_state(tmp_path):
    pool = ShortTermMemoryPool(str(tmp_path / "system"), session_id="s1")
    pool.record_user_goal("Write textbook tb_alpha chapter 2")
    pool.record_tool_start("textbook_chapter", {"book_id": "tb_alpha", "chapter_num": 2, "action": "write"})
    pool.record_tool_end("textbook_chapter", {"book_id": "tb_alpha", "chapter_num": 2, "action": "write"}, "success", {"path": "chapters/chapter_002.md"})

    boundary = pool.maybe_record_task_boundary("Switch to memory profile optimization")

    payload = json.loads(pool.path.read_text(encoding="utf-8"))
    assert boundary["previous_domain"] == "textbook"
    assert boundary["new_domain"] == "memory"
    assert payload["active_book_id"] == ""
    assert payload["active_chapter"] == ""
    assert payload["written_files"] == []
    assert payload["events"][-1]["type"] == "task_boundary"


def test_short_term_memory_keeps_continuation_in_same_task(tmp_path):
    pool = ShortTermMemoryPool(str(tmp_path / "system"), session_id="s1")
    pool.record_user_goal("Write textbook tb_alpha chapter 2")

    boundary = pool.maybe_record_task_boundary("continue")

    assert boundary is None


def test_short_term_memory_skips_injected_textbook_context_block(tmp_path):
    pool = ShortTermMemoryPool(str(tmp_path / "system"), session_id="s1")
    injected = (
        "[Current textbook id: tb_3df776e0] "
        "[Current textbook: 土木工程智能体开发设计实务] "
        "[Canonical chapter directory: C:\\Users\\xh\\textbook_workspace\\textbooks\\tb_3df776e0\\chapters] "
        "[Tool rule: Use textbook_chapter for chapter read/write/append/replace/encoding validation.]"
    )

    pool.record_user_goal(injected)

    assert not pool.path.exists()


def test_short_term_memory_tool_result_summary_drops_raw_read_body(tmp_path):
    pool = ShortTermMemoryPool(str(tmp_path / "system"), session_id="s1")
    pool.record_tool_end(
        "read",
        {"path": "chapters/chapter_010.md"},
        "success",
        {"content": "# 第10章\n\n" + ("RAW_TOOL_BODY " * 300)},
    )

    data = json.loads(pool.path.read_text(encoding="utf-8"))
    summary = data["events"][-1]["summary"]

    assert "chapters/chapter_010.md" in summary
    assert "RAW_TOOL_BODY" not in summary
