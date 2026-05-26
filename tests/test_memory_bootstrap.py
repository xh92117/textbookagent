from agent.memory.bootstrap import MemoryBootstrap
from agent.memory.error_memory import ErrorMemoryRecorder
from agent.memory.error_capture import (
    build_error_memory_context,
    is_user_correction,
    record_tool_error,
    should_record_tool_error,
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


def test_memory_bootstrap_can_skip_workspace_profile_when_context_files_loaded(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "RULE.md").write_text("workspace rule should not duplicate", encoding="utf-8")
    bootstrap = MemoryBootstrap(str(tmp_path / "system"), project_workspace=str(project))

    context = bootstrap.build_startup_context(session_id="s1", include_workspace_profile=False)

    assert "Workspace Profile Files" not in context
    assert "workspace rule should not duplicate" not in context
    assert "On-demand Memory Stores" in context


def test_memory_bootstrap_caps_large_profile_and_workspace_memory(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "user_profile.md").write_text(
        "# User Profile\n\n" + "\n".join(f"stable preference {i}: " + ("x" * 80) for i in range(120)),
        encoding="utf-8",
    )
    (project / "MEMORY.md").write_text(
        "# Workspace Memory\n\n" + "\n".join(f"workspace memory {i}: " + ("y" * 80) for i in range(160)),
        encoding="utf-8",
    )

    bootstrap = MemoryBootstrap(str(tmp_path / "system"), project_workspace=str(project))
    context = bootstrap.build_startup_context(session_id="s1")

    assert len(context) <= 7000
    assert "Startup memory budget" in context
    assert "truncated; use memory_get" in context
    assert "stable preference 0" in context
    assert "stable preference 119" in context
    assert "workspace memory 0" in context
    assert "workspace memory 159" not in context


def test_memory_bootstrap_includes_bounded_process_index(tmp_path):
    memory_dir = tmp_path / "system" / "memory"
    memory_dir.mkdir(parents=True)
    rows = ["# Process Memory Index", ""]
    for i in range(80):
        rows.append(f"- `proc-{i}` [completed] -> `memory/processes/proc-{i}_state.md` (2026-05-25 10:{i:02d}): task {i}")
    (memory_dir / "process_index.md").write_text("\n".join(rows), encoding="utf-8")

    bootstrap = MemoryBootstrap(str(tmp_path / "system"))
    context = bootstrap.build_startup_context(session_id="s1")

    assert "Recent Process Index" in context
    assert "proc-79" in context
    assert "proc-78" in context
    assert "proc-0" not in context
    assert context.count("memory/processes/") <= 8


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


def test_web_fetch_transient_error_is_filtered_but_durable_errors_remain():
    assert not should_record_tool_error("web_fetch", "HTTP 404 for URL", {"error_type": "exception"})
    assert not should_record_tool_error("web_fetch", "connection reset by peer", {"error_type": "exception"})
    assert should_record_tool_error("write", "permission denied: chapters/01.md", {})
    assert should_record_tool_error("knowledge_capture", "invalid JSON schema for metadata", {})
