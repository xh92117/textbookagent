import json

from agent.memory.realtime import RealtimeMemoryRecorder
from agent.memory.workspace_profile_updater import WorkspaceProfileUpdater


def test_workspace_profile_updater_applies_explicit_file_update(tmp_path):
    (tmp_path / "USER.md").write_text("# USER.md\n", encoding="utf-8")
    updater = WorkspaceProfileUpdater(tmp_path)

    applied = updater.update_from_events(
        [{"role": "user", "content": "请把这条写入 USER.md：我的主要工作是高职教材建设。"}],
        session_id="s1",
    )

    assert len(applied) == 1
    assert applied[0].file == "USER.md"
    assert "高职教材建设" in (tmp_path / "USER.md").read_text(encoding="utf-8")
    assert list((tmp_path / ".workspace_profile_versions").glob("USER_*.md"))
    log = (tmp_path / ".workspace_profile_versions" / "profile_update_log.jsonl").read_text(encoding="utf-8")
    assert "USER.md" in log


def test_workspace_profile_updater_ignores_textbook_specific_preferences(tmp_path):
    updater = WorkspaceProfileUpdater(tmp_path)

    applied = updater.update_from_events(
        [{"role": "user", "content": "本教材偏好是应用导向，案例多一点。"}],
        session_id="s1",
    )

    assert applied == []
    assert not (tmp_path / "USER.md").exists()


def test_realtime_memory_updates_workspace_profile_when_project_workspace_is_set(tmp_path):
    system_root = tmp_path / "system"
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "RULE.md").write_text("# RULE.md\n", encoding="utf-8")
    recorder = RealtimeMemoryRecorder(str(system_root), project_workspace=str(project_root))

    recorder.record_messages(
        "s1",
        [{"role": "user", "content": "请把这个作为工作区规则：导出前必须检查标题层级。"}],
    )

    assert "标题层级" in (project_root / "RULE.md").read_text(encoding="utf-8")
    profile = json.loads((system_root / "memory" / "user_profile.json").read_text(encoding="utf-8"))
    assert profile["recent_focus"]
