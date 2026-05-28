from agent.memory.write_router import MemoryWriteRouter


def test_write_router_rejects_system_injected_context_for_user_profile():
    text = (
        "[Current textbook id: tb_3df776e0] "
        "[Current textbook: 土木工程智能体开发设计实务] "
        "[Canonical chapter directory: C:\\book\\chapters] "
        "[Tool rule: Use textbook_chapter]"
    )

    decision = MemoryWriteRouter.route_user_profile_signal(text, source_type="system")

    assert decision.should_write is False
    assert decision.reason == "non_user_source"


def test_write_router_rejects_transient_chapter_commands():
    decision = MemoryWriteRouter.route_user_profile_signal("请你继续写第一章", source_type="user")

    assert decision.should_write is False
    assert decision.reason == "transient_task"


def test_write_router_accepts_stable_user_preference_and_normalizes():
    decision = MemoryWriteRouter.route_user_profile_signal("请你 以后 回答 要 简洁。", source_type="user")

    assert decision.should_write is True
    assert decision.normalized_key == "请你以后回答要简洁"
