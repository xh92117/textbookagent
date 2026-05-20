import json
import os

from agent.tools.knowledge_capture.knowledge_capture import KnowledgeCapture


def test_knowledge_capture_saves_useful_web_content(tmp_path):
    content = "Civil engineering AI agent design requires traceable data, workflow states, and review checkpoints. " * 8
    tool = KnowledgeCapture({"cwd": str(tmp_path)})

    result = tool.execute({
        "url": "https://example.edu/civil-ai-agents",
        "title": "Civil AI Agents",
        "content": content,
        "reason": "Use when writing textbook sections about civil engineering agent workflow design.",
        "book_id": "tb_demo",
        "tags": ["civil engineering", "agent workflow"],
    })

    assert result.status == "success"
    payload = json.loads(result.result)
    assert payload["useful"] is True
    assert payload["status"] == "saved"
    assert payload["path"].startswith("tb_demo/sources/web_")

    saved_path = tmp_path / "knowledge" / payload["path"]
    saved = saved_path.read_text(encoding="utf-8")
    assert "source_type: web" in saved
    assert "https://example.edu/civil-ai-agents" in saved
    assert "Use when writing textbook sections" in saved
    assert os.path.isfile(tmp_path / "knowledge" / "tb_demo" / "index.json")


def test_knowledge_capture_skips_search_results_and_short_content(tmp_path):
    tool = KnowledgeCapture({"cwd": str(tmp_path)})

    search_result = tool.execute({
        "url": "https://www.google.com/search?q=civil+ai",
        "title": "Google Search",
        "content": "Search result " * 80,
        "reason": "Use when writing textbook sections about civil engineering AI agents.",
    })
    short_result = tool.execute({
        "url": "https://example.edu/short",
        "title": "Short Source",
        "content": "Too short",
        "reason": "Use when writing textbook sections about civil engineering AI agents.",
    })

    assert json.loads(search_result.result)["useful"] is False
    assert "Search result pages" in json.loads(search_result.result)["reason"]
    assert json.loads(short_result.result)["useful"] is False
    assert not (tmp_path / "knowledge" / "sources").exists()


def test_knowledge_capture_saves_concise_high_signal_extraction(tmp_path):
    tool = KnowledgeCapture({"cwd": str(tmp_path)})
    concise = (
        "Reflexion proposes verbal self-reflection for language agents: an actor executes tasks, "
        "an evaluator scores outcomes, and self-reflection converts feedback into memory for later trials. "
        "Use it to explain reflection-style agent improvement."
    )

    result = tool.execute({
        "url": "https://arxiv.org/abs/2303.11366",
        "title": "Reflexion",
        "content": concise,
        "reason": "Use when writing the textbook section about Reflexion and agent self-improvement.",
        "book_id": "tb_demo",
        "tags": ["Reflexion", "agent pattern"],
    })

    payload = json.loads(result.result)
    assert payload["useful"] is True
    assert payload["status"] == "saved"
