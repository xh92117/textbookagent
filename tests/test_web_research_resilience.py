import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent.protocol.message_utils import (
    build_context_state_board,
    compress_turn_to_text_only,
    summarize_tool_result_content,
)
from agent.tools.web_fetch.web_fetch import WebFetch


def test_web_fetch_detects_search_engine_challenge_pages():
    tool = WebFetch()

    assert "blocked" in tool._detect_search_block(
        "https://www.baidu.com/s?wd=test",
        "百度安全验证",
        "网络不给力，请稍后重试 返回首页",
    )
    assert "blocked" in tool._detect_search_block(
        "https://duckduckgo.com/html/?q=test",
        "DuckDuckGo",
        "Please complete the following challenge to confirm this search was made by a human",
    )
    assert "blocked" in tool._detect_search_block(
        "https://www.google.com/search?q=test",
        "Google Search",
        "If you're having trouble accessing Google Search, please click here",
    )


def test_web_fetch_summary_keeps_url_title_and_failure_state():
    content = "Title: Useful Source\n\nContent:\n" + ("Agent framework architecture and RAG evidence. " * 80)
    summary = summarize_tool_result_content(
        content,
        "web_fetch",
        {"url": "https://example.edu/source"},
    )
    assert "https://example.edu/source" in summary
    assert "Useful Source" in summary
    assert "compressed" in summary

    failed = summarize_tool_result_content(
        "Error: Search engine access blocked or challenged for www.baidu.com.",
        "web_fetch",
        {"url": "https://www.baidu.com/s?wd=test"},
    )
    assert "web_fetch failed" in failed
    assert "www.baidu.com" in failed


def test_web_fetch_webpage_output_is_bounded(monkeypatch):
    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}
        content = b""
        encoding = "utf-8"
        text = "<html><head><title>Long Source</title></head><body>" + ("Agent RAG framework content. " * 2000) + "</body></html>"

        def raise_for_status(self):
            return None

    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("agent.tools.web_fetch.web_fetch.requests.get", fake_get)

    result = WebFetch().execute({"url": "https://example.edu/long-source"})

    assert result.status == "success"
    assert "Source URL: https://example.edu/long-source" in result.result
    assert "Content truncated for web research" in result.result
    assert "Agent RAG framework content" in result.result
    assert "showing 0 of 1 lines" not in result.result
    assert len(result.result.encode("utf-8")) < 15000


def test_web_fetch_formats_github_contents_api(monkeypatch):
    class FakeResponse:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        content = b"[]"
        encoding = "utf-8"
        text = "[]"

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "name": "Preface.md",
                    "path": "docs/Preface.md",
                    "type": "file",
                    "download_url": "https://raw.githubusercontent.com/datawhalechina/Hello-Agents/main/docs/Preface.md",
                    "html_url": "https://github.com/datawhalechina/Hello-Agents/blob/main/docs/Preface.md",
                },
                {
                    "name": "chapter1",
                    "path": "docs/chapter1",
                    "type": "dir",
                    "url": "https://api.github.com/repos/datawhalechina/Hello-Agents/contents/docs/chapter1?ref=main",
                    "html_url": "https://github.com/datawhalechina/Hello-Agents/tree/main/docs/chapter1",
                },
            ]

    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("agent.tools.web_fetch.web_fetch.requests.get", fake_get)

    result = WebFetch().execute({
        "url": "https://api.github.com/repos/datawhalechina/Hello-Agents/contents/docs"
    })

    assert result.status == "success"
    assert "Detected GitHub repository contents listing" in result.result
    assert "docs/Preface.md" in result.result
    assert "download_url: https://raw.githubusercontent.com/datawhalechina/Hello-Agents/main/docs/Preface.md" in result.result
    assert "api_url: https://api.github.com/repos/datawhalechina/Hello-Agents/contents/docs/chapter1?ref=main" in result.result


def test_web_fetch_raw_github_404_points_to_contents_api(monkeypatch):
    class FakeResponse:
        headers = {}
        status_code = 404
        content = b""

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("agent.tools.web_fetch.web_fetch.requests.get", fake_get)

    result = WebFetch().execute({
        "url": "https://raw.githubusercontent.com/datawhalechina/Hello-Agents/main/docs/chapter1/chapter1.md"
    })

    assert result.status == "error"
    assert "Do not keep guessing raw filenames" in result.result
    assert "https://api.github.com/repos/datawhalechina/Hello-Agents/contents/docs/chapter1?ref=main" in result.result


def test_compressed_turn_preserves_web_research_progress_ledger():
    turn = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "搜索并保存教材资料"}],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "fetch1",
                        "name": "web_fetch",
                        "input": {"url": "https://arxiv.org/abs/2210.03629"},
                    },
                    {
                        "type": "tool_use",
                        "id": "cap1",
                        "name": "knowledge_capture",
                        "input": {
                            "url": "https://arxiv.org/abs/2210.03629",
                            "title": "ReAct",
                        },
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "fetch1",
                        "content": "Title: ReAct\n\nContent:\nUseful paper content",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "cap1",
                        "content": '{"useful": true, "status": "saved"}',
                    },
                ],
            },
        ]
    }

    compressed = compress_turn_to_text_only(turn)
    text = "\n".join(
        block.get("text", "")
        for msg in compressed["messages"]
        for block in msg.get("content", [])
        if isinstance(block, dict)
    )
    assert "compressed tool progress ledger" in text
    assert "https://arxiv.org/abs/2210.03629" in text
    assert "knowledge_capture saved" in text


def test_context_state_board_preserves_operational_progress():
    turns = [{
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "编写第一章"}],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "read1",
                        "name": "read",
                        "input": {"path": "knowledge/tb_demo/_llm_wiki/chunks/chunk_001.md"},
                    },
                    {
                        "type": "tool_use",
                        "id": "fetch1",
                        "name": "web_fetch",
                        "input": {"url": "https://search.brave.com/search?q=test"},
                    },
                    {
                        "type": "tool_use",
                        "id": "cap1",
                        "name": "knowledge_capture",
                        "input": {"url": "https://arxiv.org/abs/2210.03629", "title": "ReAct"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "read1",
                        "content": '{"content": "# 第一章 智能体概述\\n正文"}',
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "fetch1",
                        "content": "Error: HTTP 429 for URL: https://search.brave.com/search?q=test",
                        "is_error": True,
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "cap1",
                        "content": '{"useful": true, "status": "saved"}',
                    },
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "资料已足够，下一步应写第一章。"}],
            },
        ]
    }]

    board = build_context_state_board(turns)

    assert "Current task state board" in board
    assert "编写第一章" in board
    assert "READ file" in board
    assert "HTTP 429" in board
    assert "SAVED knowledge" in board
    assert "write/save the chapter" in board
