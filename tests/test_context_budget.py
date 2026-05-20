from agent.protocol.agent_stream import AgentStreamExecutor


class _DummyAgent:
    max_context_tokens = 5_000_000

    def _get_model_context_window(self):
        return 128_000

    def _get_context_reserve_tokens(self):
        return 20_000

    def _estimate_message_tokens(self, message):
        content = message.get("content", "")
        if isinstance(content, str):
            return len(content)
        return 1


def test_effective_context_budget_clamps_oversized_config():
    executor = AgentStreamExecutor(
        agent=_DummyAgent(),
        model=None,
        system_prompt="system",
        tools=[],
    )

    max_allowed, reserve = executor._effective_context_budget()

    assert reserve == 20_000
    assert max_allowed == 108_000


def test_effective_context_budget_respects_smaller_config():
    agent = _DummyAgent()
    agent.max_context_tokens = 50_000
    executor = AgentStreamExecutor(
        agent=agent,
        model=None,
        system_prompt="system",
        tools=[],
    )

    max_allowed, reserve = executor._effective_context_budget()

    assert reserve == 20_000
    assert max_allowed == 50_000
