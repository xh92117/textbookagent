import sys
import os
import json
import time
import tempfile
from unittest.mock import patch, MagicMock
from queue import Queue

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
        assert "chapter_01.md" in chapters
        assert "chapter_02.md" in chapters
        assert "chapter_03.md" in chapters


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
