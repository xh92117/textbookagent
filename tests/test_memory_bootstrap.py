from agent.memory.bootstrap import MemoryBootstrap
from agent.memory.error_memory import ErrorMemoryRecorder
from agent.memory.error_capture import build_error_memory_context, is_user_correction
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.base_tool import BaseTool, ToolResult


def test_memory_bootstrap_creates_compact_startup_context(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    bootstrap = MemoryBootstrap(str(tmp_path / "system"), project_workspace=str(project))

    context = bootstrap.build_startup_context(session_id="s1")

    assert "System Memory Bootstrap" in context
    assert "User Profile" in context
    assert (tmp_path / "system" / "memory" / "user_profile.md").exists()
    assert (tmp_path / "system" / "memory" / "process_index.md").exists()


def test_error_memory_recorder_writes_metadata(tmp_path):
    recorder = ErrorMemoryRecorder(str(tmp_path / "system"))
    path = recorder.record_tool_error("read", "file not found", {"path": "x.md"})

    text = path.read_text(encoding="utf-8")
    assert "tool_error" in text
    assert "file not found" in text


def test_user_correction_detection_is_selective():
    assert is_user_correction("不对，我说的是按照章节切块")
    assert is_user_correction("不是全部整理，而是只整理未整理文件")
    assert not is_user_correction("请继续编写第四章内容")


def test_tool_failure_is_captured_as_error_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("common.app_paths.system_dir", lambda: str(tmp_path / "system"))

    class FailingTool(BaseTool):
        name = "demo_fail"
        description = "demo"
        params = {"type": "object", "properties": {}}

        def execute(self, params):
            return ToolResult.fail("file not found")

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
    assert "missing.md" in text

    context = build_error_memory_context()
    assert "Recent error memory index" in context
    assert "demo_fail failed" in context
