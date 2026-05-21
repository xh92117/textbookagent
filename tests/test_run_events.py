import json

from common.run_events import RunStateRecorder, normalize_event


def test_normalize_event_builds_stable_envelope():
    event = {
        "type": "phase_complete",
        "pipeline_id": "p1",
        "data": {"phase": "outline", "result_summary": "outline done"},
        "timestamp": 123.0,
    }

    normalized = normalize_event(event, source="pipeline")

    assert normalized["run_id"] == "p1"
    assert normalized["source"] == "pipeline"
    assert normalized["type"] == "phase_complete"
    assert normalized["phase"] == "outline"
    assert normalized["status"] == "completed"
    assert normalized["message"] == "outline done"
    assert normalized["payload"]["phase"] == "outline"


def test_run_state_recorder_writes_jsonl(tmp_path):
    recorder = RunStateRecorder(str(tmp_path / "runs" / "r1"), run_id="r1", source="chat")

    event = recorder.record({"type": "llm_thinking", "data": {"elapsed_seconds": 15}})

    assert event["run_id"] == "r1"
    path = tmp_path / "runs" / "r1" / "run_events.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["source"] == "chat"
    assert rows[0]["status"] == "running"
