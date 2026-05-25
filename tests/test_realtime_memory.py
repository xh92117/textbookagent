import json

from agent.memory.realtime import RealtimeMemoryRecorder
from agent.memory.short_term import ShortTermMemoryPool


def test_process_memory_records_state_and_profile(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path), max_session_events=10, compact_keep_events=4)
    recorder.start_process(
        "textbook_demo",
        "proc_demo",
        "我想要实现教材智能体的实时记忆功能，以后不要丢失工作进度。",
        channel_type="textbook",
    )
    recorder.update_process("proc_demo", "tool_start", "read status")
    recorder.finish_process("proc_demo", final_response="已完成实时记忆设计。")

    state_path = tmp_path / "memory" / "processes" / "proc_demo_state.md"
    profile_path = tmp_path / "memory" / "user_profile.json"
    index_path = tmp_path / "memory" / "process_index.md"

    assert state_path.exists()
    assert "实时记忆功能" in state_path.read_text(encoding="utf-8")
    assert "completed" in state_path.read_text(encoding="utf-8")
    assert index_path.exists()
    assert "proc_demo" in index_path.read_text(encoding="utf-8")

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert "教材智能体开发与知识库增强" in profile["projects"]
    assert any("我想要实现教材智能体的实时记忆功能" in item for item in profile["preferences"])


def test_process_memory_does_not_update_after_finish(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process("s1", "p1", "开始处理任务")
    recorder.finish_process("p1", final_response="处理完成")
    before = (tmp_path / "memory" / "processes" / "p1.json").read_text(encoding="utf-8")
    recorder.update_process("p1", "late_event", "should be ignored")
    after = (tmp_path / "memory" / "processes" / "p1.json").read_text(encoding="utf-8")
    assert before == after


def test_legacy_session_memory_compacts_long_session(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path), max_session_events=5, compact_keep_events=2)
    for idx in range(6):
        recorder.record_messages("s1", [{"role": "user", "content": f"第{idx}轮对话"}])

    summary_path = tmp_path / "memory" / "sessions" / "s1_summary.md"
    raw_path = tmp_path / "memory" / "sessions" / "s1.jsonl"

    assert summary_path.exists()
    assert "Auto Compact" in summary_path.read_text(encoding="utf-8")
    assert len(raw_path.read_text(encoding="utf-8").splitlines()) == 2


def test_short_term_memory_pool_records_and_compacts_prompt(tmp_path):
    pool = ShortTermMemoryPool(str(tmp_path), "session/demo", max_events=20, keep_events=2)
    pool.record_user_goal("请继续编写 tb_demo 第2章，并避免覆盖已有章节。")
    pool.record_tool_start("textbook_chapter", {
        "action": "append_section",
        "book_id": "tb_demo",
        "chapter_num": 2,
    })
    pool.record_tool_end("textbook_chapter", {
        "action": "append_section",
        "book_id": "tb_demo",
        "chapter_num": 2,
    }, "success", {"chapter_path": "textbooks/tb_demo/chapters/chapter_002.md"})
    for idx in range(24):
        pool.record_tool_end("read", {"path": f"file_{idx}.md"}, "success", f"# file {idx}")

    prompt = pool.compact_prompt()
    path = tmp_path / "memory" / "short_term" / "session_demo.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["active_book_id"] == "tb_demo"
    assert data["active_chapter"] == "2"
    assert data["summary"]
    assert len(data["events"]) <= 20
    assert "Short-term working memory" in prompt
    assert "file_23.md" in prompt
