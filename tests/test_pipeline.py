import sys
import os
import asyncio
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent.textbook.pipeline.scheduler import ChapterScheduler
from agent.textbook.pipeline.chapter_persistence import ChapterPersistence
from agent.textbook.pipeline.runner import PipelineRunner
from agent.textbook.pipeline.context_builder import ContextPackageBuilder
from agent.textbook.pipeline.orchestrator import ChapterOrchestrator, PipelineCheckpointStore
from agent.textbook.models.textbook import TextbookConfig
from agent.textbook.state.manager import TextbookMemoryManager


def test_scheduler_progress():
    scheduler = ChapterScheduler(total_chapters=5)
    assert scheduler.get_progress()['completed'] == 0
    assert scheduler.get_progress()['total'] == 5
    assert scheduler.get_progress()['percentage'] == 0.0

    scheduler.mark_completed(1)
    assert scheduler.get_progress()['completed'] == 1
    assert scheduler.get_progress()['percentage'] == 20.0

    scheduler.mark_completed(2)
    scheduler.mark_completed(3)
    assert scheduler.get_progress()['completed'] == 3
    assert scheduler.get_progress()['percentage'] == 60.0


def test_scheduler_pending():
    scheduler = ChapterScheduler(total_chapters=4)
    assert scheduler.get_pending_chapters() == [1, 2, 3, 4]

    scheduler.mark_completed(2)
    assert scheduler.get_pending_chapters() == [1, 3, 4]

    scheduler.mark_completed(1)
    scheduler.mark_completed(4)
    assert scheduler.get_pending_chapters() == [3]


def test_scheduler_get_next():
    progress_calls = []
    scheduler = ChapterScheduler(total_chapters=3, on_progress=lambda c, t: progress_calls.append((c, t)))

    assert scheduler.get_next_chapter() == 1
    assert scheduler.get_next_chapter() == 2
    assert scheduler.get_next_chapter() == 3
    assert scheduler.get_next_chapter() is None

    assert len(progress_calls) == 3
    assert progress_calls[0] == (1, 3)
    assert progress_calls[2] == (3, 3)


def test_persistence_save_load():
    with tempfile.TemporaryDirectory() as tmp:
        persistence = ChapterPersistence(os.path.join(tmp, 'book1'))
        content = "# 第一章 函数\n\n本章介绍函数的基本概念。"
        persistence.save_chapter(1, content)

        loaded = persistence.load_chapter(1)
        assert loaded == content


def test_persistence_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        persistence = ChapterPersistence(os.path.join(tmp, 'book1'))
        content = "# 第二章 极限"
        metadata = {'word_count': 5200, 'review_score': 85, 'status': 'completed'}
        persistence.save_chapter(2, content, metadata=metadata)

        loaded_content = persistence.load_chapter(2)
        assert loaded_content == content

        loaded_meta = persistence.load_chapter_metadata(2)
        assert loaded_meta['word_count'] == 5200
        assert loaded_meta['review_score'] == 85
        assert loaded_meta['status'] == 'completed'


def test_persistence_list():
    with tempfile.TemporaryDirectory() as tmp:
        persistence = ChapterPersistence(os.path.join(tmp, 'book1'))
        persistence.save_chapter(1, "第一章")
        persistence.save_chapter(3, "第三章")
        persistence.save_chapter(5, "第五章")

        chapters = persistence.list_chapters()
        assert chapters == [1, 3, 5]


def test_persistence_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        persistence = ChapterPersistence(os.path.join(tmp, 'book1'))
        persistence.save_chapter(1, "第一章内容")
        persistence.save_chapter(2, "第二章内容")

        snapshot_dir = persistence.create_snapshot('v1')
        assert os.path.exists(os.path.join(snapshot_dir, 'chapters', 'chapter_001.md'))
        assert os.path.exists(os.path.join(snapshot_dir, 'chapters', 'chapter_002.md'))

        with open(os.path.join(snapshot_dir, 'chapters', 'chapter_001.md'), 'r', encoding='utf-8') as f:
            assert f.read() == "第一章内容"
        with open(os.path.join(snapshot_dir, 'chapters', 'chapter_002.md'), 'r', encoding='utf-8') as f:
            assert f.read() == "第二章内容"


def test_runner_phases():
    assert PipelineRunner.PHASES == ['outline', 'review_outline', 'compose', 'write', 'review_chapter', 'revise', 'persist']
    assert PipelineRunner.PHASE_LABELS['outline'] == '大纲编制'
    assert PipelineRunner.PHASE_LABELS['review_outline'] == '大纲审查'
    assert PipelineRunner.PHASE_LABELS['compose'] == '上下文组装'
    assert PipelineRunner.PHASE_LABELS['write'] == '章节编写'
    assert PipelineRunner.PHASE_LABELS['review_chapter'] == '教材审查'
    assert PipelineRunner.PHASE_LABELS['revise'] == '修订润色'
    assert PipelineRunner.PHASE_LABELS['persist'] == '持久化'


def test_runner_loads_llm_wiki_chunk_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        memory_manager = TextbookMemoryManager(tmp)
        book_id = "tb_wiki"
        wiki_dir = os.path.join(tmp, "knowledge", book_id, "_llm_wiki")
        os.makedirs(os.path.join(wiki_dir, "chunks"), exist_ok=True)
        with open(os.path.join(wiki_dir, "chunks", "chunk_001.md"), "w", encoding="utf-8") as f:
            f.write("---\nid: chunk_001\n---\n\n# 向量检索\n\n教材知识库会读取 chunk 正文摘录。")
        with open(os.path.join(wiki_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump({
                "chunks": [{
                    "id": "chunk_001",
                    "title": "向量检索",
                    "path": "chunks/chunk_001.md",
                    "summary": "介绍向量检索和教材知识库召回。",
                    "use_when": "Use when writing about vector retrieval.",
                    "keywords": ["向量检索", "知识库"],
                    "content_type": "concept",
                }]
            }, f, ensure_ascii=False)

        runner = PipelineRunner(memory_manager=memory_manager)
        context = runner._load_wiki_context(book_id, "向量检索 知识库")

        assert "Knowledge Evidence Pack" in context
        assert "Use when writing about vector retrieval" in context
        assert "knowledge/_llm_wiki/chunks/chunk_001.md" in context
        assert "chunk 正文摘录" in context


def test_context_builder_keeps_global_outline_and_all_previous_summaries():
    with tempfile.TemporaryDirectory() as tmp:
        memory_manager = TextbookMemoryManager(tmp)
        book_id = "tb_context"
        mgr = memory_manager.get_truth_manager(book_id)
        mgr.write("chapter_summaries", "## 第1章 基础\n摘要1\n\n## 第2章 架构\n摘要2\n\n## 第3章 应用\n摘要3\n\n")
        mgr.write_chapter(2, "## 第2章 架构\n\n正文\n\n## 本章小结\n第2章详细衔接。")
        mgr.write_chapter(3, "## 第3章 应用\n\n正文\n\n## 本章小结\n第3章详细衔接。")
        outline = "\n".join([
            "## 第1章 基础",
            "- 教学目标: A",
            "## 第2章 架构",
            "- 教学目标: B",
            "## 第3章 应用",
            "- 教学目标: C",
            "## 第4章 部署",
            "- 教学目标: D",
            "### 4.1 测试",
        ])

        context = ContextPackageBuilder(memory_manager).build(
            book_id=book_id,
            chapter_number=4,
            outline_text=outline,
            wiki_context="知识库证据",
            terminology={"智能体": "可调用工具的模型程序"},
        )

        assert "全书大纲骨架" in context
        assert "第1章 基础" in context
        assert "第4章 部署" in context
        assert "前序所有章节短摘要" in context
        assert "摘要1" in context and "摘要2" in context and "摘要3" in context
        assert "最近章节衔接材料" in context
        assert "第3章详细衔接" in context
        assert "知识库证据" in context


def test_context_builder_extracts_chapter_plan():
    outline = "\n".join([
        "## 第2章 智能体工具调用",
        "- 教学目标: 理解工具调用的决策流程",
        "- 关键结果: 能设计一个可恢复的工具链",
        "- 认知层次: 分析",
        "- 前置知识: Python 基础、HTTP API",
        "- 核心概念: 工具调用、状态机、错误恢复",
        "### 2.1 工具协议",
    ])

    plan = ContextPackageBuilder().extract_chapter_plan(outline, 2)

    assert plan.title == "智能体工具调用"
    assert plan.objective == "理解工具调用的决策流程"
    assert plan.key_results == "能设计一个可恢复的工具链"
    assert plan.cognitive_level == "分析"
    assert "HTTP API" in plan.prerequisites
    assert plan.key_concepts == ["工具调用", "状态机", "错误恢复"]


def test_runner_quality_gate_can_skip_polish():
    runner = PipelineRunner(llm_model=object())

    assert runner._should_polish_chapter("合格正文" * 200, {"score": 90, "issues": []}, "学术") is False
    assert runner._should_polish_chapter("正文" * 1000, {"score": 75, "issues": [{"level": "warning"}]}, "学术") is True


def test_chapter_orchestrator_plans_semantic_actions_and_checkpoints():
    actions = ChapterOrchestrator().plan(3, outline_text="## 第3章", has_knowledge=True)
    names = [a.name for a in actions]
    assert names == [
        "read_outline",
        "retrieve_knowledge",
        "build_context",
        "write_chapter",
        "route_visual_assets",
        "review_chapter",
        "revise_chapter",
        "polish_chapter",
        "persist_chapter",
    ]
    PipelineCheckpointStore.mark(actions, "write_chapter", "running")
    PipelineCheckpointStore.mark(actions, "write_chapter", "completed", "1000 chars")
    with tempfile.TemporaryDirectory() as tmp:
        store = PipelineCheckpointStore(tmp)
        path = store.save(3, actions, {"stage": "write_chapter"})
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["chapter_number"] == 3
        assert data["extra"]["stage"] == "write_chapter"
        write_action = [a for a in data["actions"] if a["name"] == "write_chapter"][0]
        assert write_action["status"] == "completed"
        assert write_action["output_summary"] == "1000 chars"


def test_runner_events():
    events = []

    def on_event(event):
        events.append(event)

    with tempfile.TemporaryDirectory() as tmp:
        memory_manager = TextbookMemoryManager(tmp)
        runner = PipelineRunner(memory_manager=memory_manager, on_event=on_event)

        config = TextbookConfig(
            title='测试教材',
            subject='数学',
            target_audience='本科生',
            level='本科',
            total_chapters=1,
            chapter_word_count=1000,
            style='学术',
        )

        result = asyncio.run(runner.run_full_pipeline(config))

        pipeline_event_types = [e['type'] for e in events]

        assert 'pipeline_start' in pipeline_event_types
        assert 'phase_start' in pipeline_event_types
        assert 'phase_complete' in pipeline_event_types
        assert 'phase_progress' in pipeline_event_types
        assert 'pipeline_complete' in pipeline_event_types

        start_events = [e for e in events if e['type'] == 'pipeline_start']
        assert len(start_events) == 1
        assert start_events[0]['data']['book_id'] == config.id
        assert start_events[0]['data']['total_phases'] == len(PipelineRunner.PHASES)

        phase_start_events = [e for e in events if e['type'] == 'phase_start']
        phase_names = [e['data']['phase'] for e in phase_start_events]
        assert 'outline' in phase_names
        assert 'review_outline' in phase_names
        assert 'persist' in phase_names

        phase_complete_events = [e for e in events if e['type'] == 'phase_complete']
        complete_phases = [e['data']['phase'] for e in phase_complete_events]
        assert 'outline' in complete_phases
        assert 'review_outline' in complete_phases
        assert 'persist' in complete_phases

        progress_events = [e for e in events if e['type'] == 'phase_progress']
        assert len(progress_events) >= 1
        assert progress_events[0]['data']['current_item'] == 1
        assert progress_events[0]['data']['total_items'] == 1

        complete_events = [e for e in events if e['type'] == 'pipeline_complete']
        assert len(complete_events) == 1
        assert complete_events[0]['data']['total_chapters'] == 1

        assert 'outline' in result
        assert 'review_outline' in result
        assert 'chapters' in result
        assert len(result['chapters']) == 1
