from agent.memory.bootstrap import MemoryBootstrap
from agent.memory.error_memory import ErrorMemoryRecorder
from agent.memory.error_capture import (
    build_error_memory_context,
    is_user_correction,
    record_tool_error,
)
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.base_tool import BaseTool, ToolResult


def test_memory_bootstrap_creates_compact_startup_context(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "USER.md").write_text(
        "\u7528\u6237\u504f\u597d\uff1a\u62a5\u544a\u8981\u50cf\u79d1\u7814\u8bba\u6587\u3002",
        encoding="utf-8",
    )
    (project / "MEMORY.md").write_text(
        "\u957f\u671f\u8bb0\u5fc6\uff1a\u6559\u6750\u751f\u6210\u8d28\u91cf\u4f18\u5148\u3002",
        encoding="utf-8",
    )
    bootstrap = MemoryBootstrap(str(tmp_path / "system"), project_workspace=str(project))

    context = bootstrap.build_startup_context(session_id="s1")

    assert "System Memory Bootstrap" in context
    assert "User Profile" in context
    assert "Workspace Profile Files" in context
    assert "\u6559\u6750\u751f\u6210\u8d28\u91cf\u4f18\u5148" in context
    assert (tmp_path / "system" / "memory" / "user_profile.md").exists()
    assert (tmp_path / "system" / "memory" / "process_index.md").exists()


def test_error_memory_recorder_writes_metadata(tmp_path):
    recorder = ErrorMemoryRecorder(str(tmp_path / "system"))
    path = recorder.record_tool_error("read", "file not found", {"path": "x.md"})

    text = path.read_text(encoding="utf-8")
    assert "tool_error" in text
    assert "file not found" in text


def test_user_correction_detection_is_selective():
    assert is_user_correction("\u4e0d\u5bf9\uff0c\u6211\u8bf4\u7684\u662f\u6309\u7167\u7ae0\u8282\u5207\u5757")
    assert is_user_correction("\u4e0d\u662f\u5168\u90e8\u6574\u7406\uff0c\u800c\u662f\u53ea\u6574\u7406\u672a\u6574\u7406\u6587\u4ef6")
    assert not is_user_correction("\u8bf7\u7ee7\u7eed\u7f16\u5199\u7b2c\u56db\u7ae0\u5185\u5bb9")


def test_tool_failure_is_captured_as_error_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("common.app_paths.system_dir", lambda: str(tmp_path / "system"))

    class FailingTool(BaseTool):
        name = "demo_fail"
        description = "demo"
        params = {"type": "object", "properties": {}}

        def execute(self, params):
            return ToolResult.fail("invalid JSON schema for tool arguments")

    class FakeAgent:
        name = "fake"

    class FakeModel:
        model = "fake-model"
        session_id = "s1"
        channel_type = "web"

    executor = AgentStreamExecutor(
        agent=FakeAgent(),
        model=FakeModel(),
        system_prompt="",
        tools=[FailingTool()],
    )

    result = executor._execute_tool({
        "id": "tc1",
        "name": "demo_fail",
        "arguments": {"path": "missing.md"},
    })

    assert result["status"] == "error"
    error_files = list((tmp_path / "system" / "memory" / "errors").glob("*.json"))
    assert len(error_files) == 1
    text = error_files[0].read_text(encoding="utf-8")
    assert "tool_error" in text
    assert "invalid JSON schema" in text

    context = build_error_memory_context()
    assert "Recent error memory index" in context
    assert "demo_fail failed" in context


def test_noisy_tool_error_is_not_captured(tmp_path, monkeypatch):
    monkeypatch.setattr("common.app_paths.system_dir", lambda: str(tmp_path / "system"))

    record_tool_error("demo_fail", "file not found", {"error_type": "tool_result_error"})

    error_dir = tmp_path / "system" / "memory" / "errors"
    assert not error_dir.exists() or not list(error_dir.glob("*.json"))
