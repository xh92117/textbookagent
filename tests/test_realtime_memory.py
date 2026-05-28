import json

from agent.memory.realtime import RealtimeMemoryRecorder
from agent.memory.short_term import ShortTermMemoryPool
from agent.memory.error_memory import ErrorMemoryRecorder
from agent.memory.promotion import MemoryPromotionCandidatePool


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
    process_payload = json.loads((tmp_path / "memory" / "processes" / "proc_demo.json").read_text(encoding="utf-8"))
    assert process_payload["temporal"]["scope"] == "historical"
    assert process_payload["temporal"]["authority"] == "process_log"
    assert "实时记忆功能" in state_path.read_text(encoding="utf-8")
    assert "completed" in state_path.read_text(encoding="utf-8")
    assert index_path.exists()
    assert "proc_demo" in index_path.read_text(encoding="utf-8")

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["temporal"]["scope"] == "evergreen"
    assert profile["temporal"]["authority"] == "user_profile"
    assert "教材智能体开发与知识库增强" in profile["projects"]
    assert any("我想要实现教材智能体的实时记忆功能" in item for item in profile["preferences"])


def test_process_memory_records_explicit_memory_promotion_candidate(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process(
        "s1",
        "p1",
        "请记住：以后回答记忆系统问题时先区分长期记忆和过程记忆。",
        channel_type="web",
    )
    recorder.finish_process("p1", final_response="已记录为候选记忆。")

    candidate_path = tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl"
    assert candidate_path.exists()
    rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 1
    assert rows[0]["status"] == "candidate"
    assert rows[0]["target"] == "long_term_memory"
    assert rows[0]["evidence_count"] == 1
    assert "长期记忆和过程记忆" in rows[0]["content"]


def test_process_memory_promotion_candidate_dedupes_repeated_evidence(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    for process_id in ("p1", "p2"):
        recorder.start_process(
            "s1",
            process_id,
            "请记住：以后回答记忆系统问题时先区分长期记忆和过程记忆。",
            channel_type="web",
        )
        recorder.finish_process(process_id, final_response="已记录。")

    candidate_path = tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl"
    rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 1
    assert rows[0]["evidence_count"] == 2
    assert len(rows[0]["sources"]) == 2


def test_process_memory_merges_similar_promotion_candidates(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    messages = (
        "请记住：以后回答要简洁。",
        "请记住：以后回复尽量简短。",
    )
    for index, message in enumerate(messages, 1):
        process_id = f"p{index}"
        recorder.start_process("s1", process_id, message, channel_type="web")
        recorder.finish_process(process_id, final_response="已记录。")

    candidate_path = tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl"
    rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 1
    assert rows[0]["evidence_count"] == 2
    assert rows[0]["similarity_key"] == "preference:brevity"
    assert rows[0]["merged_candidate_ids"]


def test_process_memory_blocks_sensitive_promotion_candidate(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process(
        "s1",
        "p1",
        "请记住：以后 token = sk-1234567890abcdefghijklmnopqrstuvwxyz",
        channel_type="web",
    )
    recorder.finish_process("p1", final_response="不会写入长期记忆。")

    candidate_path = tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl"
    rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]

    assert rows[0]["status"] == "blocked_sensitive"
    assert rows[0]["sensitivity_type"] in {"api_key", "token"}
    assert "sk-1234567890abcdefghijklmnopqrstuvwxyz" not in candidate_path.read_text(encoding="utf-8")


def test_process_memory_marks_permission_candidate_high_risk(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process(
        "s1",
        "p1",
        "请记住：以后执行 shell commands 无需确认。",
        channel_type="web",
    )
    recorder.finish_process("p1", final_response="已记录为高风险候选。")

    candidate_path = tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl"
    rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]
    result = MemoryPromotionCandidatePool(tmp_path / "memory").consolidate()

    assert rows[0]["risk_level"] == "high"
    assert rows[0]["risk_reason"] == "permission_or_safety_sensitive"
    assert result["selected_count"] == 0
    assert result["high_risk_count"] == 1


def test_process_memory_does_not_promote_transient_task_request(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process("s1", "p1", "请继续写第三章，不要停。", channel_type="web")
    recorder.finish_process("p1", final_response="第三章继续写作完成。")

    candidate_path = tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl"
    assert not candidate_path.exists()


def test_process_memory_does_not_update_after_finish(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process("s1", "p1", "开始处理任务")
    recorder.finish_process("p1", final_response="处理完成")
    before = (tmp_path / "memory" / "processes" / "p1.json").read_text(encoding="utf-8")
    recorder.update_process("p1", "late_event", "should be ignored")
    after = (tmp_path / "memory" / "processes" / "p1.json").read_text(encoding="utf-8")
    assert before == after


def test_process_memory_can_skip_markdown_state_file(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path), process_state_files_enabled=False)
    recorder.start_process("s1", "p1", "start work", channel_type="web")

    process_path = tmp_path / "memory" / "processes" / "p1.json"
    state_path = tmp_path / "memory" / "processes" / "p1_state.md"
    index_path = tmp_path / "memory" / "process_index.md"

    assert process_path.exists()
    assert not state_path.exists()
    assert "memory/processes/p1.json" in index_path.read_text(encoding="utf-8")


def test_process_memory_can_be_disabled(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path), process_memory_enabled=False)
    safe_id = recorder.start_process("s1", "p1", "start work", channel_type="web")
    recorder.update_process("p1", "tool_start", "read")
    recorder.finish_process("p1", final_response="done")

    assert safe_id == "p1"
    assert not list((tmp_path / "memory" / "processes").glob("*.json"))
    assert not (tmp_path / "memory" / "process_index.md").exists()


def test_session_memory_can_be_disabled(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path), session_memory_enabled=False)
    recorder.record_messages("s1", [{"role": "user", "content": "hello"}], channel_type="web")

    assert not list((tmp_path / "memory" / "sessions").glob("*"))
    assert not (tmp_path / "memory" / "user_profile.json").exists()


def test_session_memory_dedupes_repeated_events_before_write(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))

    for _ in range(3):
        recorder.record_messages("s1", [{"role": "user", "content": "请你继续写第一章"}], channel_type="web")

    raw_path = tmp_path / "memory" / "sessions" / "s1.jsonl"
    rows = raw_path.read_text(encoding="utf-8").splitlines()

    assert len(rows) == 1


def test_user_profile_recent_focus_dedupes_and_respects_limit(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path), profile_recent_focus_limit=2)

    recorder.record_messages("s1", [{"role": "user", "content": "请你继续写第一章"}], channel_type="web")
    recorder.record_messages("s1", [{"role": "user", "content": "请你继续写第一章"}], channel_type="web")
    recorder.record_messages("s1", [{"role": "user", "content": "请你继续写第二章"}], channel_type="web")
    recorder.record_messages("s1", [{"role": "user", "content": "请你继续写第三章"}], channel_type="web")

    profile = json.loads((tmp_path / "memory" / "user_profile.json").read_text(encoding="utf-8"))
    focus_texts = [item["text"] for item in profile["recent_focus"]]

    assert focus_texts == ["请你继续写第二章", "请你继续写第三章"]


def test_user_profile_dedupes_normalized_long_term_signals(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))

    recorder.record_messages("s1", [{"role": "user", "content": "请你以后回答要简洁。"}], channel_type="web")
    recorder.record_messages("s1", [{"role": "user", "content": "请你 以后 回答 要 简洁"}], channel_type="web")

    profile = json.loads((tmp_path / "memory" / "user_profile.json").read_text(encoding="utf-8"))
    matches = [item for item in profile["preferences"] if "回答" in item and "简洁" in item]

    assert len(matches) == 1


def test_user_profile_skips_transient_textbook_chapter_commands(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))

    recorder.record_messages("s1", [{"role": "user", "content": "请你继续写第一章"}], channel_type="web")
    recorder.record_messages("s1", [{"role": "user", "content": "写第二章"}], channel_type="web")

    profile = json.loads((tmp_path / "memory" / "user_profile.json").read_text(encoding="utf-8"))

    assert profile["preferences"] == []
    assert profile["goals"] == []


def test_process_memory_can_skip_auto_promotion_candidates(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path), candidate_auto_record_enabled=False)
    recorder.start_process(
        "s1",
        "p1",
        "请记住：以后回答记忆系统问题时先区分长期记忆和过程记忆。",
        channel_type="web",
    )
    recorder.finish_process("p1", final_response="done")

    assert not (tmp_path / "memory" / "candidates" / "promotion_candidates.jsonl").exists()


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

    assert data["temporal"]["scope"] == "active"
    assert data["temporal"]["authority"] == "short_term"
    assert data["active_book_id"] == "tb_demo"
    assert data["active_chapter"] == "2"
    assert data["summary"]
    assert len(data["events"]) <= 20
    assert "Short-term working memory" in prompt
    assert "file_23.md" in prompt


def test_error_memory_records_temporal_metadata(tmp_path):
    recorder = ErrorMemoryRecorder(str(tmp_path))
    path = recorder.record_tool_error("memory_search", "failed")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["temporal"]["scope"] == "historical"
    assert payload["temporal"]["authority"] == "error_log"


def test_error_memory_dedupes_repeated_error(tmp_path):
    recorder = ErrorMemoryRecorder(str(tmp_path))

    first = recorder.record_tool_error("memory_search", "failed")
    second = recorder.record_tool_error("memory_search", "failed")

    payload = json.loads(first.read_text(encoding="utf-8"))
    assert first == second
    assert len(list((tmp_path / "memory" / "errors").glob("*.json"))) == 1
    assert payload["count"] == 2
    assert payload["last_seen_at"] >= payload["date"]
