from agent.protocol.message_utils import compact_current_tool_result_content


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
