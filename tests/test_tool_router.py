from types import SimpleNamespace

from agent.tools.router import filter_tool_mapping, infer_task_type, route_tools


def test_tool_router_detects_textbook_and_limits_tools():
    tools = {
        "textbook_chapter": object(),
        "textbook_image": object(),
        "knowledge_query": object(),
        "memory_search": object(),
        "bash": object(),
        "web_search": object(),
        "browser": object(),
    }

    route = route_tools("请继续编写教材第2章，不要覆盖已有章节", tools)
    filtered = filter_tool_mapping(tools, route.allowed_tools)

    assert route.task_type == "textbook"
    assert "textbook_chapter" in filtered
    assert "knowledge_query" in filtered
    assert "bash" not in filtered
    assert "web_search" not in filtered
    assert "Tool routing policy" in route.prompt


def test_tool_router_detects_frontend_and_keeps_browser():
    route = route_tools(
        "修复前端按钮 bug 并用浏览器验证",
        {
            "read": object(),
            "edit": object(),
            "bash": object(),
            "browser": object(),
            "textbook_chapter": object(),
        },
    )

    assert route.task_type == "frontend"
    assert "browser" in route.allowed_tools
    assert "textbook_chapter" in route.omitted_tools


def test_infer_general_when_no_keyword():
    assert infer_task_type("你好，帮我看一下这个问题") == "general"
