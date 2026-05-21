# encoding:utf-8

import time

import pytest

import bridge.agent_bridge as agent_bridge
import bridge.textbook_bridge as textbook_bridge
import config as config_module
from bridge.agent_bridge import AgentLLMModel
from bridge.textbook_bridge import _LightweightLLM
from agent.protocol.agent_stream import AgentStreamExecutor


def test_stream_guard_returns_after_idle_when_provider_never_finishes(monkeypatch):
    monkeypatch.setattr(
        agent_bridge,
        "conf",
        lambda: {
            "agent_stream_idle_timeout": 1,
            "agent_stream_first_chunk_timeout": 5,
        },
    )

    def stuck_stream():
        yield {"choices": [{"delta": {"content": "ok"}}]}
        time.sleep(5)

    model = AgentLLMModel(bridge=None)
    started = time.time()
    chunks = list(model._iter_stream_with_idle_guard(stuck_stream()))

    assert chunks == [{"choices": [{"delta": {"content": "ok"}}]}]
    assert time.time() - started < 3


def test_stream_guard_times_out_before_first_chunk(monkeypatch):
    monkeypatch.setattr(
        agent_bridge,
        "conf",
        lambda: {
            "agent_stream_idle_timeout": 1,
            "agent_stream_first_chunk_timeout": 2,
        },
    )

    def silent_stream():
        time.sleep(5)
        yield {"choices": [{"delta": {"content": "late"}}]}

    model = AgentLLMModel(bridge=None)

    with pytest.raises(TimeoutError):
        list(model._iter_stream_with_idle_guard(silent_stream()))


def test_agent_executor_stream_idle_guard_returns_partial_chunks():
    def stuck_stream():
        yield {"choices": [{"delta": {"content": "ok"}}]}
        time.sleep(5)

    executor = object.__new__(AgentStreamExecutor)
    started = time.time()
    chunks = []
    with pytest.raises(TimeoutError):
        for chunk in executor._iter_stream_with_idle_timeout(stuck_stream(), 1):
            chunks.append(chunk)
    assert chunks == [{"choices": [{"delta": {"content": "ok"}}]}]
    assert time.time() - started < 3


def test_knowledge_stream_guard_returns_partial_sse_when_done_is_missing(monkeypatch):
    monkeypatch.setattr(
        config_module,
        "conf",
        lambda: {
            "knowledge_stream_idle_timeout": 1,
            "knowledge_stream_first_chunk_timeout": 5,
            "request_timeout": 5,
        },
    )

    class FakeResponse:
        status_code = 200
        text = ""

        def iter_lines(self):
            yield b'data: {"choices":[{"delta":{"content":"{\\"pages\\":[]}"}}]}'
            time.sleep(5)

        def close(self):
            pass

    class FakeRequests:
        def post(self, *args, **kwargs):
            return FakeResponse()

    llm = object.__new__(_LightweightLLM)
    llm._model = "fake"
    llm._request_timeout = 5
    result = llm._call_streaming_chat_completions(
        req_lib=FakeRequests(),
        url="http://example.test/v1/chat/completions",
        headers={},
        payload={"model": "fake", "messages": [], "stream": False},
    )
    assert result == '{"pages":[]}'
