import os

from agent.knowledge.service import KnowledgeService
from agent.tools.knowledge_query.knowledge_query import KnowledgeQueryTool


def test_knowledge_query_glob_hides_internal_chunks_and_reuses_index(tmp_path):
    svc = KnowledgeService(str(tmp_path))
    content = "# RAG\n\nRetrieval augmented generation uses chunk retrieval and evidence packs.\n" * 20
    source = tmp_path / "paper.md"
    source.write_text(content, encoding="utf-8")
    result = svc._build_llm_wiki(str(source), content, "tb")
    assert result["chunks"] >= 1
    assert os.path.exists(tmp_path / "knowledge" / "tb" / "_llm_wiki" / "index.json")

    tool = KnowledgeQueryTool({"cwd": str(tmp_path)})
    glob_result = tool.execute({"action": "glob", "book_id": "tb", "limit": 20})

    assert glob_result.status == "success"
    assert glob_result.result["stats"]["chunks"] >= 1
    assert glob_result.result["canonical_index"].endswith("_llm_wiki/index.json")
    assert all("_llm_wiki/chunks/" not in item["path"] for item in glob_result.result["files"])


def test_knowledge_query_search_peek_pack_and_read_range(tmp_path):
    svc = KnowledgeService(str(tmp_path))
    content = "# RAG\n\nRetrieval augmented generation uses chunk retrieval and evidence packs.\n" * 20
    source = tmp_path / "paper.md"
    source.write_text(content, encoding="utf-8")
    svc._build_llm_wiki(str(source), content, "tb")

    tool = KnowledgeQueryTool({"cwd": str(tmp_path)})
    search = tool.execute({"action": "search", "book_id": "tb", "query": "retrieval evidence", "limit": 3})
    assert search.status == "success"
    assert search.result["results"]
    assert "excerpt" not in search.result["results"][0]

    peek = tool.execute({"action": "peek", "book_id": "tb", "query": "retrieval evidence", "limit": 1})
    assert peek.status == "success"
    assert "excerpt" in peek.result["results"][0]

    pack = tool.execute({"action": "pack", "book_id": "tb", "query": "retrieval evidence", "limit": 3})
    assert pack.status == "success"
    assert "Knowledge Evidence Pack" in pack.result["evidence_pack"]

    chunk_id = search.result["results"][0]["chunk_id"]
    read = tool.execute({"action": "read_range", "book_id": "tb", "chunk_id": chunk_id, "max_chars": 300})
    assert read.status == "success"
    assert read.result["content"]
    assert read.result["total_chars"] >= len(read.result["content"])

    neighbors = tool.execute({"action": "read_neighbors", "book_id": "tb", "chunk_id": chunk_id, "radius": 1, "max_chars": 800})
    assert neighbors.status == "success"
    assert chunk_id in neighbors.result["chunk_ids"]
    assert neighbors.result["content"]

    section = tool.execute({"action": "read_section", "book_id": "tb", "chunk_id": chunk_id, "max_chars": 800})
    assert section.status == "success"
    assert chunk_id in section.result["chunk_ids"]
    assert section.result["content"]
