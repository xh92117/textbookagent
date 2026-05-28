from agent.memory.runtime_options import realtime_memory_enabled, realtime_recorder_options


def test_realtime_recorder_options_default_to_slim_process_logs():
    options = realtime_recorder_options({})

    assert options["process_memory_enabled"] is True
    assert options["session_memory_enabled"] is True
    assert options["process_state_files_enabled"] is False
    assert options["candidate_auto_record_enabled"] is False
    assert options["retention_enabled"] is True
    assert options["process_max_files"] == 60
    assert options["session_dedupe_window"] == 20
    assert options["profile_recent_focus_limit"] == 10
    assert options["profile_field_limit"] == 30


def test_realtime_memory_enabled_honors_global_switch():
    assert realtime_memory_enabled({"realtime_memory_enabled": False}) is False
    assert realtime_memory_enabled({}) is True
