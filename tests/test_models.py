import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent.textbook.models import (
    TextbookConfig, OutlineNode, Chapter, Exercise,
    ChartReq, ImageReq, ReviewResult, DimensionResult, Issue,
    WritingSpec,
)


def test_textbook_config_creation():
    config = TextbookConfig(title="高等数学", subject="数学", level="本科")
    assert config.id.startswith("tb_"), f"id 应以 tb_ 开头，实际为 {config.id}"
    assert len(config.id) > 3, "id 不应为空"
    assert config.title == "高等数学"
    assert config.subject == "数学"
    assert config.level == "本科"
    assert config.created_at != "", "created_at 应自动生成"
    assert config.updated_at != "", "updated_at 应自动生成"
    assert config.updated_at == config.created_at
    assert config.status == "planning"
    assert config.language == "zh"
    assert config.chapter_word_count == 5000
    assert config.style == "学术"


def test_textbook_config_serialization():
    config = TextbookConfig(
        title="线性代数", subject="数学", level="本科",
        total_chapters=10, curriculum_standard="GB-2024"
    )
    json_str = config.to_json()
    restored = TextbookConfig.from_json(json_str)
    assert restored.title == config.title
    assert restored.subject == config.subject
    assert restored.level == config.level
    assert restored.total_chapters == config.total_chapters
    assert restored.curriculum_standard == config.curriculum_standard
    assert restored.id == config.id
    assert restored.created_at == config.created_at

    d = config.to_dict()
    restored2 = TextbookConfig.from_dict(d)
    assert restored2.title == config.title
    assert restored2.id == config.id


def test_textbook_config_generates_audience_specific_writing_spec():
    config = TextbookConfig(
        title="工程实训教材",
        target_audience="高职学生",
        level="基础",
        style="应用实训",
    )

    spec = config.ensure_writing_spec()

    assert spec.learning_orientation == "应用型/实训型"
    assert spec.content_ratio.code == 5
    assert "任务场景" in spec.chapter_structure
    assert spec.visual_policy.min_assets_per_chapter == 2


def test_writing_spec_round_trips_from_dict():
    spec = WritingSpec.default_for("研究生", "高级", "理论")
    restored = WritingSpec.from_dict(spec.to_dict())

    assert restored.learning_orientation == "理论研究型"
    assert restored.content_ratio.theory == 45
    assert restored.visual_policy.preferred_types == spec.visual_policy.preferred_types


def test_outline_node_tree():
    root = OutlineNode(
        id="root", title="教材", level=0,
        children=[
            OutlineNode(
                id="part1", title="第一篇 基础", level=1,
                key_concepts=["概念A", "概念B"],
                children=[
                    OutlineNode(id="ch1", title="第一章", level=2, estimated_words=3000),
                    OutlineNode(id="ch2", title="第二章", level=2, estimated_words=4000),
                ]
            ),
            OutlineNode(
                id="part2", title="第二篇 进阶", level=1,
                children=[
                    OutlineNode(id="ch3", title="第三章", level=2, estimated_words=5000),
                ]
            ),
        ]
    )
    json_str = root.to_json()
    restored = OutlineNode.from_json(json_str)
    assert restored.id == "root"
    assert restored.title == "教材"
    assert len(restored.children) == 2
    assert len(restored.children[0].children) == 2
    assert restored.children[0].children[0].title == "第一章"
    assert restored.children[0].key_concepts == ["概念A", "概念B"]
    assert restored.children[1].children[0].estimated_words == 5000


def test_outline_node_find_by_id():
    root = OutlineNode(
        id="root", title="教材", level=0,
        children=[
            OutlineNode(id="p1", title="篇1", level=1, children=[
                OutlineNode(id="c1", title="章1", level=2),
                OutlineNode(id="c2", title="章2", level=2),
            ]),
            OutlineNode(id="p2", title="篇2", level=1, children=[
                OutlineNode(id="c3", title="章3", level=2),
            ]),
        ]
    )
    found = root.find_by_id("c2")
    assert found is not None
    assert found.title == "章2"
    assert found.level == 2

    not_found = root.find_by_id("nonexistent")
    assert not_found is None


def test_outline_node_get_all_chapters():
    root = OutlineNode(
        id="root", title="教材", level=0,
        children=[
            OutlineNode(id="p1", title="篇1", level=1, children=[
                OutlineNode(id="c1", title="章1", level=2),
                OutlineNode(id="c2", title="章2", level=2),
            ]),
            OutlineNode(id="p2", title="篇2", level=1, children=[
                OutlineNode(id="c3", title="章3", level=2),
                OutlineNode(id="s1", title="节1", level=3),
            ]),
        ]
    )
    chapters = root.get_all_chapters()
    assert len(chapters) == 3
    assert all(c.level == 2 for c in chapters)
    chapter_ids = {c.id for c in chapters}
    assert chapter_ids == {"c1", "c2", "c3"}


def test_chapter_with_exercises():
    ch = Chapter(
        number=1,
        title="函数与极限",
        outline_node_id="ch1",
        content="本章介绍函数与极限的基本概念...",
        key_points=["函数定义", "极限概念", "连续性"],
        terminology={"极限": "limit", "连续": "continuous"},
        exercises=[
            Exercise(question="求 lim(x→0) sin(x)/x", exercise_type="计算题", difficulty="中等", answer="1", hint="使用洛必达法则"),
            Exercise(question="证明连续函数的性质", exercise_type="证明题", difficulty="困难", answer="略", hint="利用ε-δ定义"),
        ],
        chart_requirements=[
            ChartReq(description="函数图像", chart_type="line", data_description="y=sin(x) 在 [0, 2π] 上的图像"),
        ],
        image_requirements=[
            ImageReq(description="极限示意图", image_type="diagram", prompt_hint="展示x趋近于a时f(x)趋近于L", size="landscape_4_3"),
        ],
        summary="本章讲解了函数与极限的核心概念",
        word_count=5200,
        status="draft",
    )
    json_str = ch.to_json()
    restored = Chapter.from_json(json_str)
    assert restored.number == 1
    assert restored.title == "函数与极限"
    assert len(restored.exercises) == 2
    assert restored.exercises[0].question == "求 lim(x→0) sin(x)/x"
    assert restored.exercises[0].exercise_type == "计算题"
    assert restored.exercises[1].difficulty == "困难"
    assert len(restored.chart_requirements) == 1
    assert restored.chart_requirements[0].chart_type == "line"
    assert len(restored.image_requirements) == 1
    assert restored.image_requirements[0].size == "landscape_4_3"
    assert restored.terminology["极限"] == "limit"
    assert restored.key_points == ["函数定义", "极限概念", "连续性"]
    assert restored.word_count == 5200


def test_review_result():
    review = ReviewResult(
        passed=False,
        score=72.5,
        dimensions=[
            DimensionResult(name="内容准确性", score=85.0, comment="内容基本准确"),
            DimensionResult(name="逻辑连贯性", score=60.0, comment="部分章节逻辑跳跃"),
        ],
        issues=[
            Issue(level="critical", dimension="内容准确性", description="公式(3.2)有误", suggestion="修正公式", location="第3章"),
            Issue(level="warning", dimension="逻辑连贯性", description="第2章到第3章过渡生硬", suggestion="增加过渡段落", location="第2章末尾"),
            Issue(level="warning", dimension="语言表达", description="部分表述不够严谨", suggestion="使用更规范的学术用语", location="第1章"),
        ],
    )
    assert review.passed is False
    assert review.score == 72.5
    assert len(review.dimensions) == 2

    critical = review.get_critical_issues()
    assert len(critical) == 1
    assert critical[0].level == "critical"
    assert critical[0].description == "公式(3.2)有误"

    warnings = review.get_warnings()
    assert len(warnings) == 2
    assert all(w.level == "warning" for w in warnings)


def test_review_result_serialization():
    review = ReviewResult(
        passed=True,
        score=90.0,
        dimensions=[
            DimensionResult(name="内容准确性", score=92.0, comment="准确"),
            DimensionResult(name="逻辑连贯性", score=88.0, comment="连贯"),
        ],
        issues=[
            Issue(level="warning", dimension="语言表达", description="个别措辞", suggestion="微调", location="附录"),
        ],
    )
    json_str = review.to_json()
    restored = ReviewResult.from_json(json_str)
    assert restored.passed is True
    assert restored.score == 90.0
    assert len(restored.dimensions) == 2
    assert restored.dimensions[0].name == "内容准确性"
    assert restored.dimensions[0].score == 92.0
    assert len(restored.issues) == 1
    assert restored.issues[0].level == "warning"
