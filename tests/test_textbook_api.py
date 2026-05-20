import sys
import os
import json
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
        "title": "API测试教材",
        "subject": "计算机科学",
        "target_audience": "研究生",
        "level": "研究生",
        "total_chapters": 3,
        "chapter_word_count": 5000,
        "style": "学术",
    }
    defaults.update(kwargs)
    return TextbookConfig(**defaults)


def test_api_list_textbooks_empty():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.list_textbooks()
        assert result == []


def test_api_list_textbooks_after_create():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        bridge.create_textbook(_make_config(title="教材X"))
        bridge.create_textbook(_make_config(title="教材Y"))
        books = bridge.list_textbooks()
        assert len(books) == 2
        titles = [b.title for b in books]
        assert "教材X" in titles
        assert "教材Y" in titles


def test_api_create_textbook():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config(title="新建教材", subject="物理")
        result = bridge.create_textbook(config)
        assert result.id.startswith("tb_")
        assert result.title == "新建教材"
        assert result.subject == "物理"
        assert result.status == "planning"
        assert result.created_at != ""
        assert result.updated_at != ""


def test_api_create_textbook_with_id():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config(title="指定ID教材")
        config.id = "tb_custom001"
        result = bridge.create_textbook(config)
        assert result.id == "tb_custom001"


def test_api_get_textbook():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(title="获取测试"))
        loaded = bridge.get_textbook(created.id)
        assert loaded is not None
        assert loaded.title == "获取测试"
        assert loaded.subject == "计算机科学"


def test_api_get_textbook_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.get_textbook("nonexistent")
        assert result is None


def test_api_update_textbook():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(title="原始标题"))
        updated = bridge.update_textbook(created.id, {"title": "更新标题", "total_chapters": 10})
        assert updated is not None
        assert updated.title == "更新标题"
        assert updated.total_chapters == 10
        assert updated.updated_at != ""


def test_api_update_textbook_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.update_textbook("nonexistent", {"title": "xxx"})
        assert result is None


def test_api_delete_textbook():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(title="删除测试"))
        book_dir = os.path.join(tmp, created.id)
        assert os.path.exists(book_dir)
        result = bridge.delete_textbook(created.id)
        assert result is True
        assert not os.path.exists(book_dir)


def test_api_delete_textbook_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.delete_textbook("nonexistent")
        assert result is False


def test_api_outline_read_write():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        outline = "# 教材大纲\n\n第一章 绪论\n第二章 方法"
        bridge.update_outline(created.id, outline)
        loaded = bridge.get_outline(created.id)
        assert loaded == outline


def test_api_outline_empty():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        loaded = bridge.get_outline(created.id)
        assert loaded == ""


def test_api_chapter_read_write():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        content = "# 第一章 绪论\n\n本章介绍基本概念。"
        bridge.update_chapter(created.id, 1, content)
        loaded = bridge.get_chapter(created.id, 1)
        assert loaded == content


def test_api_chapter_empty():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        loaded = bridge.get_chapter(created.id, 1)
        assert loaded == ""


def test_api_chapter_num_conversion():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        num_str = "2"
        content = "# 第二章 方法\n\n方法介绍。"
        bridge.update_chapter(created.id, int(num_str), content)
        loaded = bridge.get_chapter(created.id, int(num_str))
        assert loaded == content


def test_api_list_chapters():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        bridge.update_chapter(created.id, 1, "第一章")
        bridge.update_chapter(created.id, 2, "第二章")
        bridge.update_chapter(created.id, 3, "第三章")
        chapters = bridge.list_chapters(created.id)
        assert len(chapters) == 3
        assert "chapter_001.md" in chapters
        assert "chapter_002.md" in chapters
        assert "chapter_003.md" in chapters


def test_api_list_chapters_empty():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        chapters = bridge.list_chapters(created.id)
        assert chapters == []


def test_api_pipeline_status_none():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        status = bridge.get_pipeline_status(created.id)
        assert status["status"] == "none"
        assert status["book_id"] == created.id


def test_api_pipeline_start():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        mock_runner = MagicMock()
        mock_runner.pipeline_id = "test-pipeline"
        mock_runner._paused = False
        mock_runner._cancelled = False
        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            info = bridge.start_pipeline(created.id, sse_queue=None)
            assert info["book_id"] == created.id
            assert info["status"] == "running"
            assert "started_at" in info


def test_api_pipeline_start_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.start_pipeline("nonexistent")
        assert "error" in result


def test_api_pipeline_pause():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        mock_runner = MagicMock()
        mock_runner._paused = False
        mock_runner._cancelled = False
        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            bridge.start_pipeline(created.id)
            result = bridge.pause_pipeline(created.id)
            assert result is True
            status = bridge.get_pipeline_status(created.id)
            assert status["status"] == "paused"


def test_api_pipeline_resume():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        mock_runner = MagicMock()
        mock_runner._paused = False
        mock_runner._cancelled = False
        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            bridge.start_pipeline(created.id)
            bridge.pause_pipeline(created.id)
            result = bridge.resume_pipeline(created.id)
            assert result is True
            status = bridge.get_pipeline_status(created.id)
            assert status["status"] == "running"


def test_api_pipeline_cancel():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config())
        mock_runner = MagicMock()
        mock_runner._paused = False
        mock_runner._cancelled = False
        with patch("bridge.textbook_bridge.PipelineRunner", return_value=mock_runner):
            bridge.start_pipeline(created.id)
            result = bridge.cancel_pipeline(created.id)
            assert result is True
            status = bridge.get_pipeline_status(created.id)
            assert status["status"] == "cancelled"


def test_api_pipeline_pause_not_running():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.pause_pipeline("nonexistent")
        assert result is False


def test_api_pipeline_resume_not_running():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.resume_pipeline("nonexistent")
        assert result is False


def test_api_pipeline_cancel_not_running():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.cancel_pipeline("nonexistent")
        assert result is False


def test_api_export_word():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(title="导出API测试"))
        bridge.update_outline(created.id, "# 大纲\n\n第一章 概述")
        bridge.update_chapter(created.id, 1, "# 第一章 概述\n\n内容。")
        output_path = bridge.export_word(created.id)
        assert output_path != ""
        assert os.path.exists(output_path)
        assert output_path.endswith(".docx")
        assert os.path.getsize(output_path) > 0


def test_api_export_word_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.export_word("nonexistent")
        assert result == ""


def test_api_export_word_with_template():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(title="模板导出测试"))
        bridge.update_chapter(created.id, 1, "# 第一章\n\n内容")
        output_path = bridge.export_word(created.id, template_name="academic")
        assert os.path.exists(output_path)


def test_api_export_word_specific_chapters():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        created = bridge.create_textbook(_make_config(title="章节导出API测试"))
        bridge.update_chapter(created.id, 1, "# 第一章\n\n内容1")
        bridge.update_chapter(created.id, 2, "# 第二章\n\n内容2")
        bridge.update_chapter(created.id, 3, "# 第三章\n\n内容3")
        output_path = bridge.export_word(created.id, chapter_numbers=[1, 3])
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0


def test_api_sandbox_execute():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.execute_sandbox("print(1 + 1)")
        assert result["success"] is True
        assert "2" in result["stdout"]
        assert result["exit_code"] == 0


def test_api_sandbox_execute_with_timeout():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.execute_sandbox("print('hello')", timeout=10)
        assert result["success"] is True
        assert "hello" in result["stdout"]


def test_api_sandbox_execute_failure():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.execute_sandbox("import os\nprint('hello')")
        assert result["success"] is False


def test_api_chart_generation_line():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        data = {
            "x": "[1, 2, 3, 4, 5]",
            "y": "[10, 20, 15, 25, 30]",
            "title": "折线图",
            "xlabel": "X",
            "ylabel": "Y",
        }
        result = bridge.generate_chart("line", data, filename="test_line.png")
        assert result["success"] is True


def test_api_chart_generation_bar():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        data = {
            "categories": "['A', 'B', 'C']",
            "values": "[10, 20, 15]",
            "title": "柱状图",
        }
        result = bridge.generate_chart("bar", data)
        assert result["success"] is True


def test_api_chart_generation_pie():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        data = {
            "labels": "['A', 'B', 'C']",
            "sizes": "[30, 50, 20]",
            "title": "饼图",
        }
        result = bridge.generate_chart("pie", data)
        assert result["success"] is True


def test_api_chart_generation_unsupported():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        result = bridge.generate_chart("radar", {})
        assert result["success"] is False
        assert "Unsupported" in result["error"]


def test_api_crud_full_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config(title="完整生命周期", subject="数学", total_chapters=5)
        created = bridge.create_textbook(config)
        assert created.id.startswith("tb_")

        loaded = bridge.get_textbook(created.id)
        assert loaded.title == "完整生命周期"

        updated = bridge.update_textbook(created.id, {"title": "更新后", "total_chapters": 8})
        assert updated.title == "更新后"
        assert updated.total_chapters == 8

        books = bridge.list_textbooks()
        assert len(books) == 1
        assert books[0].title == "更新后"

        deleted = bridge.delete_textbook(created.id)
        assert deleted is True
        assert bridge.get_textbook(created.id) is None


def test_api_textbook_config_serialization():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = _make_bridge(tmp)
        config = _make_config(title="序列化测试")
        created = bridge.create_textbook(config)
        loaded = bridge.get_textbook(created.id)
        d = loaded.to_dict()
        assert "id" in d
        assert "title" in d
        assert "subject" in d
        assert "total_chapters" in d
        assert "status" in d
        assert d["title"] == "序列化测试"
        assert d["subject"] == "计算机科学"
