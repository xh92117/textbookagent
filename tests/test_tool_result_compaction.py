from agent.protocol.message_utils import (
    compact_current_tool_result_content,
    compact_historical_tool_result_content,
)


def test_compact_current_read_result_keeps_headings_and_path():
    content = "# Title\n\n" + "\n".join(f"line {idx}" for idx in range(300)) + "\n## Tail"

    compacted = compact_current_tool_result_content(
        content,
        tool_name="read",
        tool_args={"path": "docs/demo.md"},
        status="success",
        max_chars=2000,
    )

    assert len(compacted) <= 2000
    assert "current read result compacted" in compacted
    assert "docs/demo.md" in compacted
    assert "Title" in compacted


def test_compact_current_read_result_does_not_expand_small_outputs():
    content = "short line\n" * 20

    compacted = compact_current_tool_result_content(
        content,
        tool_name="read",
        tool_args={"path": "docs/small.md"},
        status="success",
        max_chars=4000,
    )

    assert compacted == content


def test_compact_current_textbook_chapter_result_keeps_metadata():
    content = (
        '{"status":"success","chapter_path":"textbooks/tb_demo/chapters/chapter_001.md",'
        '"content":"' + ("正文" * 5000) + '"}'
    )

    compacted = compact_current_tool_result_content(
        content,
        tool_name="textbook_chapter",
        status="success",
        max_chars=3000,
    )

    assert "current textbook_chapter result compacted" in compacted
    assert "chapter_path" in compacted
    assert "正文" not in compacted


def test_tool_result_compaction_uses_type_specific_budgets():
    long_output = "\n".join(f"row {idx}: value" for idx in range(1000))

    compacted = compact_current_tool_result_content(
        long_output,
        tool_name="bash",
        tool_args={"command": "run-long-report"},
        status="success",
        max_chars=5000,
        tool_budget_chars={"bash": 1200},
    )

    assert len(compacted) <= 1200
    assert "output compacted" in compacted
    assert "row 0" in compacted
    assert "row 999" in compacted


def test_compact_textbook_chapter_result_respects_max_chars_with_large_structure():
    warnings = ",".join(f'"warning {idx}"' for idx in range(1000))
    content = (
        '{"status":"success","chapter_path":"textbooks/tb_demo/chapters/chapter_001.md",'
        '"chars":78135,"structure":{"warnings":[' + warnings + ']}}'
    )

    compacted = compact_current_tool_result_content(
        content,
        tool_name="textbook_chapter",
        status="success",
        max_chars=1200,
    )

    assert len(compacted) <= 1200
    assert "current textbook_chapter result compacted" in compacted
    assert "chapter_path" in compacted


def test_historical_read_result_keeps_state_not_body():
    content = "# Title\n\n" + "\n".join(f"SECRET_BODY_LINE_{idx}" for idx in range(300))

    compacted = compact_historical_tool_result_content(
        content,
        tool_name="read",
        tool_args={"path": "docs/large.md"},
        status="success",
        max_chars=900,
    )

    assert len(compacted) <= 900
    assert "historical read result summarized" in compacted
    assert "docs/large.md" in compacted
    assert "Title" in compacted
    assert "SECRET_BODY_LINE_299" not in compacted
    assert "SECRET_BODY_LINE_1" not in compacted
