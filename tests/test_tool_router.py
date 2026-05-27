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


def test_tool_router_marks_textbook_writing_as_strict_with_required_tool():
    tools = {
        "textbook_chapter": object(),
        "knowledge_query": object(),
        "read": object(),
        "write": object(),
        "edit": object(),
        "bash": object(),
        "memory_search": object(),
        "memory_get": object(),
    }

    route = route_tools("继续编写教材第2章，并标记完成", tools)

    assert route.mode == "strict"
    assert route.required_tools == ["textbook_chapter"]
    assert "textbook_chapter" in route.allowed_tools
    assert "bash" in route.blocked_tools
    assert "write" in route.blocked_tools
    assert "edit" in route.blocked_tools
    assert "Strict required tools" in route.prompt


def test_tool_router_routes_textbook_project_creation_to_create_textbook():
    tools = {
        "create_textbook": object(),
        "start_pipeline": object(),
        "textbook_chapter": object(),
        "write": object(),
        "edit": object(),
        "bash": object(),
        "memory_search": object(),
        "memory_get": object(),
    }

    route = route_tools("请创建教材项目《机器学习导论》", tools)

    assert route.mode == "strict"
    assert route.required_tools == ["create_textbook"]
    assert "create_textbook" in route.allowed_tools
    assert "textbook_chapter" not in route.allowed_tools
    assert "write" in route.blocked_tools
    assert "edit" in route.blocked_tools


def test_tool_router_routes_textbook_outline_to_textbook_outline():
    tools = {
        "create_textbook": object(),
        "textbook_outline": object(),
        "textbook_chapter": object(),
        "write": object(),
        "edit": object(),
        "bash": object(),
        "memory_search": object(),
        "memory_get": object(),
    }

    route = route_tools("请为这本教材生成大纲和术语表", tools)

    assert route.mode == "strict"
    assert route.required_tools == ["textbook_outline"]
    assert "textbook_outline" in route.allowed_tools
    assert "textbook_chapter" not in route.allowed_tools
    assert "write" in route.blocked_tools
    assert "edit" in route.blocked_tools


def test_tool_router_routes_single_chapter_writing_away_from_pipeline():
    tools = {
        "start_pipeline": object(),
        "textbook_chapter": object(),
        "textbook_outline": object(),
        "write": object(),
        "edit": object(),
        "bash": object(),
        "memory_search": object(),
        "memory_get": object(),
    }

    route = route_tools("写第一章", tools)

    assert route.mode == "strict"
    assert route.required_tools == ["textbook_chapter"]
    assert "start_pipeline" not in route.allowed_tools
    assert "textbook_chapter" in route.allowed_tools


def test_tool_router_routes_explicit_pipeline_start_to_start_pipeline():
    tools = {
        "start_pipeline": object(),
        "create_textbook": object(),
        "textbook_chapter": object(),
        "textbook_outline": object(),
        "memory_search": object(),
        "memory_get": object(),
    }

    route = route_tools("请启动编制这本教材", tools)

    assert route.mode == "strict"
    assert route.required_tools == ["start_pipeline"]
    assert "start_pipeline" in route.allowed_tools
    assert "textbook_chapter" not in route.allowed_tools


def test_tool_router_keeps_general_tasks_free_not_strict():
    tools = {"read": object(), "bash": object(), "knowledge_query": object()}

    route = route_tools("帮我分析一下这个工具系统设计的利弊", tools)

    assert route.mode == "free"
    assert route.required_tools == []
    assert "bash" in route.allowed_tools


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
