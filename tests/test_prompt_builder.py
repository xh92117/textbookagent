import inspect

from agent.prompt import builder


def test_build_agent_system_prompt_has_no_unreachable_legacy_builder_code():
    source = inspect.getsource(builder.build_agent_system_prompt)

    assert source.count("return _build_agent_system_prompt_result") == 1
    assert "sections = []" not in source
