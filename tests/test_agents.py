import sys
import os
import asyncio
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent.textbook.agents.base import TextbookBaseAgent
from agent.textbook.agents.outliner import OutlinerAgent
from agent.textbook.agents.composer import ComposerAgent
from agent.textbook.agents.writer import WriterAgent
from agent.textbook.agents.reviewer import ReviewerAgent
from agent.textbook.agents.reviser import ReviserAgent
from agent.textbook.agents.polisher import PolisherAgent


def test_base_agent_interface():
    with pytest.raises(TypeError):
        TextbookBaseAgent()


def test_outliner_agent_type():
    agent = OutlinerAgent()
    assert agent.get_agent_type() == "outliner"


def test_outliner_build_prompt():
    agent = OutlinerAgent()
    prompt = agent._build_user_prompt({
        'title': '高等数学',
        'subject': '数学',
        'target_audience': '本科生',
        'level': '本科',
        'total_chapters': 10,
        'chapter_word_count': 5000,
        'style': '学术',
        'curriculum_standard': 'GB-2024',
    })
    assert '高等数学' in prompt
    assert '数学' in prompt
    assert '本科生' in prompt
    assert '本科' in prompt


def test_writer_agent_type():
    agent = WriterAgent()
    assert agent.get_agent_type() == "writer"


def test_writer_parse_output():
    agent = WriterAgent()
    llm_output = "### PRE_WRITE_CHECK\n| 检查项 | 状态 |\n\n### CHAPTER_CONTENT\n## 第一章 函数\n\n[图表: 函数图像]\n\n[插图: 极限示意图]\n\n正文内容"
    result = agent._parse_output(llm_output, {'chapter_number': 1, 'chapter_title': '函数'})
    assert result['chapter_number'] == 1
    assert result['chapter_title'] == '函数'
    assert '函数' in result['content']
    assert len(result['chart_requirements']) == 1
    assert result['chart_requirements'][0]['chart_type'] == 'auto'
    assert len(result['image_requirements']) == 1
    assert result['image_requirements'][0]['image_type'] == 'illustration'
    assert result['word_count'] > 0


def test_reviewer_agent_modes():
    agent = ReviewerAgent()
    agent.set_review_mode('outline')
    assert '大纲' in agent.get_system_prompt()
    agent.set_review_mode('chapter')
    assert '章节' in agent.get_system_prompt()


def test_reviewer_parse_json():
    agent = ReviewerAgent()
    json_output = json.dumps({
        'passed': True,
        'score': 85,
        'dimensions': [{'name': '知识准确性', 'score': 90, 'comment': '准确'}],
        'issues': [{'level': 'warning', 'description': '个别措辞', 'suggestion': '微调'}],
    })
    result = agent._parse_output(json_output, {})
    assert result['passed'] is True
    assert result['score'] == 85
    assert len(result['dimensions']) == 1
    assert len(result['issues']) == 1

    markdown_json_output = "```json\n" + json_output + "\n```"
    result2 = agent._parse_output(markdown_json_output, {})
    assert result2['passed'] is True
    assert result2['score'] == 85


def test_reviewer_parse_invalid_json():
    agent = ReviewerAgent()
    result = agent._parse_output("this is not json", {})
    assert result['passed'] is False
    assert result['score'] == 0
    assert len(result['issues']) == 1
    assert result['issues'][0]['level'] == 'critical'


def test_reviser_agent_type():
    agent = ReviserAgent()
    assert agent.get_agent_type() == "reviser"


def test_polisher_agent_type():
    agent = PolisherAgent()
    assert agent.get_agent_type() == "polisher"


def test_agent_no_llm():
    agent = OutlinerAgent()
    result = asyncio.run(agent.run({'title': '测试'}))
    assert result['status'] == 'failed'
    assert 'LLM model not configured' in result['error']


def test_agent_empty_llm_response_is_failed():
    class EmptyLLM:
        def call(self, messages, cancel_event=None):
            return ""

    agent = OutlinerAgent(llm_model=EmptyLLM())
    result = asyncio.run(agent.run({'title': '测试'}))
    assert result['status'] == 'failed'
    assert 'empty response' in result['error']


def test_agent_error_response_is_failed():
    class ErrorLLM:
        def call(self, messages, cancel_event=None):
            return "[ERROR] upstream failed"

    agent = OutlinerAgent(llm_model=ErrorLLM())
    result = asyncio.run(agent.run({'title': '测试'}))
    assert result['status'] == 'failed'
    assert 'upstream failed' in result['error']


def test_agent_emit_event():
    events = []

    def on_event(event):
        events.append(event)

    agent = OutlinerAgent(on_event=on_event)
    agent.emit_event('test_event', {'key': 'value'})
    assert len(events) == 1
    assert events[0]['type'] == 'test_event'
    assert events[0]['agent'] == 'OutlinerAgent'
    assert events[0]['data']['key'] == 'value'


def test_agent_emit_event_on_run():
    events = []

    def on_event(event):
        events.append(event)

    agent = OutlinerAgent(on_event=on_event)
    result = asyncio.run(agent.run({'title': '测试'}))
    assert result['status'] == 'failed'
    call_events = [e for e in events if e['type'] == 'agent_call']
    assert len(call_events) == 1
    assert call_events[0]['agent'] == 'OutlinerAgent'


def test_composer_build_prompt():
    agent = ComposerAgent()
    prompt = agent._build_user_prompt({
        'outline': '大纲内容',
        'chapter_summaries': '摘要内容',
        'terminology': {'极限': 'limit', '连续': 'continuous'},
        'current_chapter': '第一章',
    })
    assert '大纲内容' in prompt
    assert '摘要内容' in prompt
    assert '极限' in prompt
    assert 'limit' in prompt
    assert '第一章' in prompt


def test_reviser_build_prompt():
    agent = ReviserAgent()
    prompt = agent._build_user_prompt({
        'content': '原文内容',
        'score': 65,
        'issues': [
            {'level': 'critical', 'description': '公式有误', 'suggestion': '修正公式'},
            {'level': 'warning', 'description': '措辞不当', 'suggestion': '调整措辞'},
        ],
        'mode': 'spot-fix',
    })
    assert '原文内容' in prompt
    assert '65' in prompt
    assert 'critical' in prompt
    assert '公式有误' in prompt

def test_reviser_build_prompt_accepts_quality_gate_message_field():
    agent = ReviserAgent()
    prompt = agent._build_user_prompt({
        'content': 'draft',
        'score': 70,
        'issues': [
            {'level': 'warning', 'message': 'missing evidence', 'code': 'missing_evidence'},
        ],
    })

    assert 'missing evidence' in prompt


def test_polisher_build_prompt():
    agent = PolisherAgent()
    prompt = agent._build_user_prompt({
        'content': '待润色内容',
        'style': '学术',
    })
    assert '待润色内容' in prompt
    assert '学术' in prompt
