import sys
import os
import json
import time
import tempfile
from unittest.mock import patch, MagicMock
from queue import Queue

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bridge.textbook_bridge import TextbookBridge
from agent.textbook.models.textbook import TextbookConfig


def _make_bridge(tmp_dir):
    return TextbookBridge(data_dir=tmp_dir)


def _make_config(**kwargs):
    defaults = {
        "title": "测试教材",
        "subject": "数学",
        "target_audience": "本科生",
        "level": "本科",
        "total_chapters": 3,
        "chapter_word_count": 5000,
        "style": "学术",
    }
    defaults.update(kwargs)
    return TextbookConfig(**defaults)


def test_determine_resume_point_requires_current_outline_review():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(total_chapters=3))
        mgr = bridge._memory_manager.get_truth_manager(created.id)
        outline = "# Outline\n\n## Chapter 1\n"
        mgr.write('outline', outline)

        assert bridge._determine_resume_point(created.id, created) == "review_outline"

        mgr.mark_outline_reviewed(outline, {'score': 90, 'issues': []})
        assert bridge._determine_resume_point(created.id, created) == "compose"

        mgr.write('outline', outline + "\n## Chapter 2\n")
        assert bridge._determine_resume_point(created.id, created) == "review_outline"


def test_determine_resume_point_does_not_return_to_outline_after_chapters():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(total_chapters=3))
        mgr = bridge._memory_manager.get_truth_manager(created.id)
        mgr.write('outline', "# Outline\n\n## Chapter 1\n")
        mgr.write_chapter(1, "chapter content long enough to be counted as completed " * 2)

        assert bridge._determine_resume_point(created.id, created) == "compose"


def test_create_textbook():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        result = bridge.create_textbook(config)
        assert result.id.startswith("tb_")
        assert result.title == "测试教材"
        assert result.created_at != ""
        config_path = os.path.join(tmp, result.id, "textbook.json")
        assert os.path.exists(config_path)


def test_get_textbook():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)
        loaded = bridge.get_textbook(created.id)
        assert loaded is not None
        assert loaded.title == "测试教材"
        assert loaded.subject == "数学"


def test_get_textbook_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.get_textbook("nonexistent_id")
        assert result is None


def test_get_textbook_from_disk():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)
        bridge2 = _make_bridge(tmp)
        loaded = bridge2.get_textbook(created.id)
        assert loaded is not None
        assert loaded.title == "测试教材"

def test_list_textbooks_uses_directory_id_when_config_id_mismatches():
    with tempfile.TemporaryDirectory() as tmp:
        folder_id = "textbook_202605270001"
        book_dir = os.path.join(tmp, folder_id)
        os.makedirs(book_dir)
        config = _make_config()
        config.id = "tb_wrong"
        config.save(os.path.join(book_dir, "textbook.json"))

        bridge = _make_bridge(tmp)
        books = bridge.list_textbooks()

        assert len(books) == 1
        assert books[0].id == folder_id
        assert bridge.get_textbook(folder_id) is not None
        assert bridge.get_textbook("tb_wrong") is None


def test_list_textbooks_recovers_orphan_textbook_directory_without_config():
    with tempfile.TemporaryDirectory() as tmp:
        folder_id = "textbook_202605270002"
        outline_dir = os.path.join(tmp, folder_id, "outline")
        os.makedirs(outline_dir)
        with open(os.path.join(outline_dir, "outline.md"), "w", encoding="utf-8") as f:
            f.write("# AI 创建的教材\n\n## 第一章 绪论\n\n## 第二章 方法\n")
        with open(os.path.join(outline_dir, "terminology.md"), "w", encoding="utf-8") as f:
            f.write("# Terminology\n\n| 术语 | 解释 |\n")

        bridge = _make_bridge(tmp)
        books = bridge.list_textbooks()

        assert len(books) == 1
        assert books[0].id == folder_id
        assert books[0].title == "AI 创建的教材"
        assert books[0].total_chapters == 2
        assert os.path.exists(os.path.join(tmp, folder_id, "textbook.json"))
        assert bridge.get_textbook(folder_id) is not None


def test_update_textbook():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)
        updated = bridge.update_textbook(created.id, {"title": "更新后教材", "total_chapters": 5})
        assert updated is not None
        assert updated.title == "更新后教材"
        assert updated.total_chapters == 5
        assert updated.updated_at != ""


def test_update_preferences_updates_global_writing_spec():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(target_audience="高职学生", style="应用实训"))

        result = bridge.update_preferences(created.id, {
            "chapter_word_count": 8000,
            "style": "工程实践风格",
            "learning_orientation": "应用型/实训型",
            "content_ratio": {
                "theory": 10,
                "case": 35,
                "procedure": 25,
                "practice": 25,
                "code": 5,
            },
            "min_visual_assets": 2,
            "additional_notes": "减少大段代码，增加岗位任务。",
            "auto_optimize": "启用",
        })

        config = bridge.get_textbook(created.id)
        prefs = bridge.get_preferences(created.id)

        assert result["preferences"]["auto_optimize"] is True
        assert config.chapter_word_count == 8000
        assert config.writing_spec.learning_orientation == "应用型/实训型"
        assert config.writing_spec.content_ratio.case == 35
        assert config.writing_spec.visual_policy.min_assets_per_chapter == 2
        assert config.writing_spec.additional_notes == "减少大段代码，增加岗位任务。"
        assert prefs["writing_spec"]["additional_notes"] == "减少大段代码，增加岗位任务。"


def test_update_textbook_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.update_textbook("nonexistent_id", {"title": "xxx"})
        assert result is None


def test_delete_textbook():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)
        book_dir = os.path.join(tmp, created.id)
        assert os.path.exists(book_dir)
        result = bridge.delete_textbook(created.id)
        assert result is True
        assert not os.path.exists(book_dir)
        assert bridge.get_textbook(created.id) is None


def test_delete_textbook_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.delete_textbook("nonexistent_id")
        assert result is False


def test_list_textbooks():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        bridge.create_textbook(_make_config(title="教材A"))
        bridge.create_textbook(_make_config(title="教材B"))
        bridge.create_textbook(_make_config(title="教材C"))
        books = bridge.list_textbooks()
        assert len(books) == 3
        titles = [b.title for b in books]
        assert "教材A" in titles
        assert "教材B" in titles
        assert "教材C" in titles


def test_list_textbooks_empty():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        books = bridge.list_textbooks()
        assert books == []


def test_outline_read_write():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)
        outline = "# 教材大纲\n\n第一章 函数与极限\n第二章 导数"
        result = bridge.update_outline(created.id, outline)
        assert result is True
        loaded = bridge.get_outline(created.id)
        assert loaded == outline


def test_outline_versions_preserve_previous_and_new_content():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        bridge.update_outline(created.id, "# V0\n\n旧大纲")

        result = bridge.save_outline_version(created.id, "# V1\n\n新大纲", "调整章节顺序")
        versions = bridge.list_outline_versions(created.id)

        assert result["version_id"] == "v2_0"
        assert [v["label"] for v in versions] == ["V1.0", "V2.0"]
        assert bridge.get_outline_version(created.id, "v1_0") == "# V0\n\n旧大纲"
        assert bridge.get_outline_version(created.id, "v2_0") == "# V1\n\n新大纲"
        assert "调整章节顺序" in versions[-1]["summary"]
        assert bridge.get_outline(created.id) == "# V1\n\n新大纲"


def test_outline_version_not_saved_when_content_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        outline = "# V0\n\n旧大纲"
        bridge.update_outline(created.id, outline)

        result = bridge.save_outline_version(created.id, outline, "未修改")

        assert result["unchanged"] is True
        assert result["saved_versions"] == []
        assert bridge.list_outline_versions(created.id) == []


def test_list_textbook_cards_counts_written_chapters_even_with_stale_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(total_chapters=2, status="writing"))
        mgr = bridge._memory_manager.get_truth_manager(created.id)
        mgr.write_chapter(1, "# 第一章\n\n" + "正文内容" * 30)
        mgr.write_chapter(2, "# 第二章\n\n" + "正文内容" * 30)
        with open(mgr.chapter_metadata_path(2), "w", encoding="utf-8") as f:
            json.dump({"status": "draft", "content_hash": "stale"}, f)

        card = bridge.list_textbook_cards()[0]

        assert card["completed_chapters"] == 2
        assert card["completed_chapter_numbers"] == [1, 2]
        assert card["progress"] == 100
        assert card["status"] == "reviewing"
        assert card["state_source"] == "truth_files"


def test_resolve_textbook_state_prefers_chapter_files_over_stale_progress():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(total_chapters=3, status="writing"))
        mgr = bridge._memory_manager.get_truth_manager(created.id)
        mgr.write_chapter(1, "# Chapter 1\n\n" + "body " * 30)
        mgr.write_chapter(2, "# Chapter 2\n\n" + "body " * 30)
        mgr.write("progress", json.dumps({
            "completed_chapters": 0,
            "total_chapters": 3,
            "percentage": 0,
        }))

        state = bridge.resolve_textbook_state(created.id)

        assert state["completed_chapters"] == 2
        assert state["completed_chapter_numbers"] == [1, 2]
        assert state["progress"] == 66.7
        assert state["state_warnings"]


def test_recent_activity_returns_multiple_items_for_one_textbook():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(total_chapters=5))
        mgr = bridge._memory_manager.get_truth_manager(created.id)
        bridge.update_outline(created.id, "# 大纲")
        for num in range(1, 6):
            mgr.write_chapter(num, f"# 第{num}章\n\n" + "正文内容" * 30)
            path = os.path.join(mgr.book_dir, "chapters", f"chapter_{num:03d}.md")
            os.utime(path, (time.time() + num, time.time() + num))

        activities = bridge.list_recent_activity(limit=5)

        assert len(activities) == 5
        assert all(item["book_id"] == created.id for item in activities)
        assert all(item["kind"] == "chapter" for item in activities)
        assert [item["chapter_num"] for item in activities] == [5, 4, 3, 2, 1]


def test_outline_empty():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)
        loaded = bridge.get_outline(created.id)
        assert loaded == ""


def test_chapter_read_write():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)
        content = "# 第一章 函数\n\n本章介绍函数的基本概念。"
        result = bridge.update_chapter(created.id, 1, content)
        assert result is True
        loaded = bridge.get_chapter(created.id, 1)
        assert loaded == content


def test_chapter_empty():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)
        loaded = bridge.get_chapter(created.id, 1)
        assert loaded == ""


def test_list_chapters():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)
        bridge.update_chapter(created.id, 1, "第一章内容")
        bridge.update_chapter(created.id, 2, "第二章内容")
        bridge.update_chapter(created.id, 3, "第三章内容")
        chapters = bridge.list_chapters(created.id)
        assert len(chapters) == 3
        assert "chapter_001.md" in chapters
        assert "chapter_002.md" in chapters
        assert "chapter_003.md" in chapters


def test_pipeline_start():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)

        mock_runner = MagicMock()
        mock_runner.pipeline_id = "test-pipeline-id"
        mock_runner._paused = False
        mock_runner._cancelled = False

        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            sse_queue = Queue()
            info = bridge.start_pipeline(created.id, sse_queue=sse_queue)
            assert info["book_id"] == created.id
            assert info["status"] == "running"
            assert "started_at" in info


def test_pipeline_status_is_persisted_and_reloaded():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        status_path = os.path.join(tmp, created.id, "state", "pipeline_status.json")
        os.makedirs(os.path.dirname(status_path), exist_ok=True)
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump({
                "book_id": created.id,
                "status": "running",
                "started_at": "2026-01-01T00:00:00",
                "progress": 0.5,
            }, f)

        reloaded = _make_bridge(tmp).get_pipeline_status(created.id)

        assert reloaded["status"] == "interrupted"
        assert reloaded["progress"] == 0.5


def test_get_chapter_with_hash_avoids_web_private_state_access():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        bridge.update_chapter(created.id, 1, "# Chapter\n\nbody text")

        payload = bridge.get_chapter_with_hash(created.id, 1)

        assert payload["chapter_num"] == 1
        assert payload["content"] == "# Chapter\n\nbody text"
        assert payload["content_hash"]


def test_pipeline_status():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)

        status = bridge.get_pipeline_status(created.id)
        assert status["status"] == "none"

        mock_runner = MagicMock()
        mock_runner.pipeline_id = "test-pipeline-id"
        mock_runner._paused = False
        mock_runner._cancelled = False

        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            bridge.start_pipeline(created.id)
            status = bridge.get_pipeline_status(created.id)
            assert status["status"] == "running"


def test_pipeline_pause():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)

        mock_runner = MagicMock()
        mock_runner.pipeline_id = "test-pipeline-id"
        mock_runner._paused = False
        mock_runner._cancelled = False

        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            bridge.start_pipeline(created.id)
            result = bridge.pause_pipeline(created.id)
            assert result is True
            mock_runner.pause.assert_called_once()
            status = bridge.get_pipeline_status(created.id)
            assert status["status"] == "paused"


def test_pipeline_resume():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)

        mock_runner = MagicMock()
        mock_runner.pipeline_id = "test-pipeline-id"
        mock_runner._paused = False
        mock_runner._cancelled = False

        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            bridge.start_pipeline(created.id)
            bridge.pause_pipeline(created.id)
            result = bridge.resume_pipeline(created.id)
            assert result is True
            mock_runner.resume.assert_called_once()
            status = bridge.get_pipeline_status(created.id)
            assert status["status"] == "running"


def test_pipeline_cancel():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)

        mock_runner = MagicMock()
        mock_runner.pipeline_id = "test-pipeline-id"
        mock_runner._paused = False
        mock_runner._cancelled = False

        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            bridge.start_pipeline(created.id)
            result = bridge.cancel_pipeline(created.id)
            assert result is True
            mock_runner.cancel.assert_called_once()
            status = bridge.get_pipeline_status(created.id)
            assert status["status"] == "cancelled"


def test_pipeline_pause_not_running():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.pause_pipeline("nonexistent_id")
        assert result is False


def test_pipeline_resume_not_running():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.resume_pipeline("nonexistent_id")
        assert result is False


def test_pipeline_cancel_not_running():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.cancel_pipeline("nonexistent_id")
        assert result is False


def test_pipeline_start_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.start_pipeline("nonexistent_id")
        assert "error" in result


def test_pipeline_start_already_running():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)

        mock_runner = MagicMock()
        mock_runner.pipeline_id = "test-pipeline-id"
        mock_runner._paused = False
        mock_runner._cancelled = False

        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            bridge.start_pipeline(created.id)
            result = bridge.start_pipeline(created.id)
            assert "error" in result


def test_pipeline_sse_events():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)

        captured_events = []

        class FakeRunner:
            def __init__(self_self, llm_model=None, memory_manager=None, on_event=None):
                self_self.llm_model = llm_model
                self_self.memory_manager = memory_manager
                self_self.on_event = on_event
                self_self.pipeline_id = ""
                self_self._paused = False
                self_self._cancelled = False
                captured_events.append(on_event)

            async def run_full_pipeline(self_self, book_config, requirement=""):
                return {}

            def pause(self_self):
                self_self._paused = True

            def resume(self_self):
                self_self._paused = False

            def cancel(self_self):
                self_self._cancelled = True

        with patch("bridge.textbook_bridge.PipelineRunner", FakeRunner):
            sse_queue = Queue()
            bridge.start_pipeline(created.id, sse_queue=sse_queue)
            assert len(captured_events) == 1
            on_event = captured_events[0]
            on_event({"type": "pipeline_start", "data": {"book_id": created.id}})
            event = sse_queue.get(timeout=2)
            assert event["type"] == "pipeline_start"


def test_export_word():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config(title="导出测试教材")
        created = bridge.create_textbook(config)
        bridge.update_outline(created.id, "# 大纲\n\n第一章 概述")
        bridge.update_chapter(created.id, 1, "# 第一章 概述\n\n这是第一章的内容。")

        output_path = bridge.export_word(created.id)
        assert output_path != ""
        assert os.path.exists(output_path)
        assert output_path.endswith(".docx")
        assert os.path.getsize(output_path) > 0


def test_export_word_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.export_word("nonexistent_id")
        assert result == ""


def test_export_word_specific_chapters():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config(title="章节导出测试")
        created = bridge.create_textbook(config)
        bridge.update_chapter(created.id, 1, "# 第一章\n\n内容1")
        bridge.update_chapter(created.id, 2, "# 第二章\n\n内容2")
        bridge.update_chapter(created.id, 3, "# 第三章\n\n内容3")

        output_path = bridge.export_word(created.id, chapter_numbers=[1, 3])
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0


def test_export_word_specific_chapter_does_not_mutate_source():
    from docx import Document

    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(title="Export Safety"))
        original = "# Chapter 2\n\nThis chapter must remain unchanged after export."
        bridge.update_outline(created.id, "# Textbook Outline\n\n# Chapter 1 Overview")
        bridge.update_chapter(created.id, 2, original)

        output_path = bridge.export_word(created.id, chapter_numbers=[2])

        assert os.path.exists(output_path)
        assert bridge.get_chapter(created.id, 2) == original
        paragraphs = [p.text for p in Document(output_path).paragraphs if p.text.strip()]
        assert any("Chapter 2" in text for text in paragraphs)
        assert not any("Textbook Outline" in text for text in paragraphs)


def test_export_word_rejects_missing_selected_chapter():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(title="Export Missing Chapter"))
        bridge.update_outline(created.id, "# Textbook Outline")
        bridge.update_chapter(created.id, 2, "# Chapter 2\n\nExisting content.")

        with pytest.raises(ValueError, match="Requested chapter not found"):
            bridge.export_word(created.id, chapter_numbers=[1])

        assert bridge.get_chapter(created.id, 2) == "# Chapter 2\n\nExisting content."


def test_sandbox_execute():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.execute_sandbox("print(1 + 1)")
        assert result["success"] is True
        assert "2" in result["stdout"]
        assert result["exit_code"] == 0


def test_sandbox_execute_failure():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.execute_sandbox("import os\nprint('hello')")
        assert result["success"] is False
        assert "forbidden" in result["stderr"].lower()


def test_chart_generation():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        data = {
            "x": "[1, 2, 3, 4, 5]",
            "y": "[10, 20, 15, 25, 30]",
            "title": "测试折线图",
            "xlabel": "X轴",
            "ylabel": "Y轴",
        }
        result = bridge.generate_chart("line", data, filename="test_line.png")
        assert result["success"] is True


def test_chart_generation_bar():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        data = {
            "categories": "['A', 'B', 'C']",
            "values": "[10, 20, 15]",
            "title": "测试柱状图",
        }
        result = bridge.generate_chart("bar", data)
        assert result["success"] is True


def test_chart_generation_unsupported():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.generate_chart("radar", {})
        assert result["success"] is False
        assert "Unsupported" in result["error"]


def test_delete_cleans_pipeline():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config()
        created = bridge.create_textbook(config)

        mock_runner = MagicMock()
        mock_runner.pipeline_id = "test-pipeline-id"
        mock_runner._paused = False
        mock_runner._cancelled = False

        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            bridge.start_pipeline(created.id)
            assert created.id in bridge.active_pipelines

        bridge.delete_textbook(created.id)
        assert created.id not in bridge.active_pipelines
