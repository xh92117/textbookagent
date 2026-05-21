import sys
import os
import shutil
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent.textbook.state.truth_files import TruthFileManager
from agent.textbook.state.manager import TextbookMemoryManager


def _make_book_dir(tmp_path, name="test_book"):
    book_dir = os.path.join(str(tmp_path), name)
    os.makedirs(book_dir, exist_ok=True)
    return book_dir


def test_truth_file_read_write():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        content = "# 教材大纲\n\n第一章 函数与极限"
        mgr.write('outline', content)
        result = mgr.read('outline')
        assert result == content, f"写入后读取内容不一致: {result!r}"


def test_truth_file_chapter():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        chapter_content = "# 第一章 函数\n\n本章介绍函数的基本概念。"
        mgr.write_chapter(1, chapter_content)
        result = mgr.read_chapter(1)
        assert result == chapter_content, f"章节写入后读取不一致: {result!r}"


def test_truth_file_list_chapters():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        mgr.write_chapter(1, "第一章内容")
        mgr.write_chapter(2, "第二章内容")
        mgr.write_chapter(3, "第三章内容")
        chapters = mgr.list_chapters()
        assert len(chapters) == 3, f"应有3个章节文件，实际为 {len(chapters)}"
        assert chapters == ['chapter_001.md', 'chapter_002.md', 'chapter_003.md']


def test_truth_file_chapter_number_ignores_leading_zeroes():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        book_dir = os.path.join(tmp, "book1")
        os.makedirs(os.path.join(book_dir, "chapters"), exist_ok=True)
        with open(os.path.join(book_dir, "chapters", "chapter_00010.md"), "w", encoding="utf-8") as f:
            f.write("# chapter ten")
        mgr = TruthFileManager(book_dir)
        assert mgr.read_chapter(10) == "# chapter ten"
        assert mgr.list_chapters() == ["chapter_00010.md"]


def test_truth_file_snapshot():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        mgr.write('outline', "# 大纲内容")
        mgr.write('current_state', "# 当前状态")
        mgr.save_snapshot("v1")
        snapshot_dir = os.path.join(tmp, "book1", "snapshots", "v1")
        assert os.path.exists(os.path.join(snapshot_dir, 'outline', 'outline.md'))
        assert os.path.exists(os.path.join(snapshot_dir, 'state', 'current_state.md'))
        with open(os.path.join(snapshot_dir, 'outline', 'outline.md'), 'r', encoding='utf-8') as f:
            assert f.read() == "# 大纲内容"


def test_truth_file_progress():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        mgr.update_progress(3, 10)
        progress = mgr.get_progress()
        assert progress['completed_chapters'] == 3
        assert progress['total_chapters'] == 10
        assert progress['percentage'] == 30.0
        status = mgr.get_status()
        assert status['version'] == 'textbook-status-v1'
        assert status['current_phase'] == 'progress_updated'
        assert status['total_chapters'] == 10
        assert status['progress']['completed_chapters'] == 3
        assert os.path.exists(os.path.join(tmp, "book1", "state", "status.json"))


def test_truth_file_status_tracks_completed_chapters():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        mgr.write_chapter(1, "chapter one")
        mgr.write_chapter(3, "chapter three")
        status = mgr.update_status(
            total_chapters=5,
            current_chapter=3,
            current_phase='persist_chapter',
            extra={'pipeline_id': 'pipe-test'},
        )
        assert status['completed_chapters'] == [1, 3]
        assert status['latest_completed_chapter'] == 3
        assert status['current_chapter'] == 3
        assert status['current_phase'] == 'persist_chapter'
        assert status['pipeline_id'] == 'pipe-test'


def test_truth_file_status_blocks_same_chapter_phase_regression():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        mgr.write_chapter(1, "chapter one " * 8)
        first = mgr.update_status(
            total_chapters=3,
            current_chapter=1,
            current_phase='review_chapter',
            run_status='running',
        )
        regressed = mgr.update_status(
            total_chapters=3,
            current_chapter=1,
            current_phase='write_chapter',
            run_status='running',
        )
        assert first['current_phase'] == 'review_chapter'
        assert regressed['current_phase'] == 'review_chapter'
        assert regressed['regression_blocked'] is True


def test_truth_file_status_allows_next_chapter_restart():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        mgr.update_status(total_chapters=3, current_chapter=1, current_phase='persist_chapter')
        next_chapter = mgr.update_status(total_chapters=3, current_chapter=2, current_phase='read_outline')
        assert next_chapter['current_chapter'] == 2
        assert next_chapter['current_phase'] == 'read_outline'
        assert next_chapter['regression_blocked'] is False


def test_outline_review_state_tracks_outline_hash():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        outline = "# Outline\n\n## Chapter 1\n"
        mgr.write('outline', outline)
        assert not mgr.is_outline_review_current()

        state = mgr.mark_outline_reviewed(outline, {'score': 91, 'issues': []})
        assert state['status'] == 'reviewed'
        assert state['score'] == 91
        assert mgr.is_outline_review_current()

        mgr.write('outline', outline + "\n## Chapter 2\n")
        assert not mgr.is_outline_review_current()

        stale = mgr.invalidate_outline_review("test_update")
        assert stale['status'] == 'stale'
        assert stale['reason'] == 'test_update'


def test_chapter_complete_requires_matching_metadata_hash_when_present():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        content = "chapter body " * 8
        mgr.write_chapter(1, content)
        assert mgr.is_chapter_complete(1, min_chars=50)

        meta_path = mgr.chapter_metadata_path(1)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump({
                'status': 'completed',
                'content_hash': TruthFileManager.content_hash(content),
            }, f)
        assert mgr.is_chapter_complete(1, min_chars=50)

        mgr.write_chapter(1, content + " changed")
        assert not mgr.is_chapter_complete(1, min_chars=50)

        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump({'status': 'draft'}, f)
        assert not mgr.is_chapter_complete(1, min_chars=50)


def test_truth_file_terminology():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = TruthFileManager(os.path.join(tmp, "book1"))
        terms = {"极限": "描述函数值趋近的趋势", "连续": "函数无间断的性质"}
        mgr.update_terminology(terms)
        result = mgr.get_terminology()
        assert result["极限"] == "描述函数值趋近的趋势"
        assert result["连续"] == "函数无间断的性质"
        new_terms = {"导数": "函数变化率"}
        mgr.update_terminology(new_terms)
        result = mgr.get_terminology()
        assert len(result) == 3
        assert result["导数"] == "函数变化率"
        assert result["极限"] == "描述函数值趋近的趋势"


def test_textbook_memory_manager():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mem_mgr = TextbookMemoryManager(tmp)
        state = {
            'current_state': '# 编写中\n正在编写第三章',
            'progress': {'completed_chapters': 2, 'total_chapters': 8, 'percentage': 25.0},
        }
        mem_mgr.save_textbook_state('book_abc', state)
        loaded = mem_mgr.load_textbook_state('book_abc')
        assert loaded['current_state'] == '# 编写中\n正在编写第三章'
        assert loaded['progress']['completed_chapters'] == 2
        assert loaded['progress']['total_chapters'] == 8


def test_textbook_memory_terminology():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mem_mgr = TextbookMemoryManager(tmp)
        terms = {"矩阵": "矩形的数表", "行列式": "方阵的标量函数"}
        mem_mgr.update_terminology('book_xyz', terms)
        result = mem_mgr.get_terminology('book_xyz')
        assert result["矩阵"] == "矩形的数表"
        assert result["行列式"] == "方阵的标量函数"
