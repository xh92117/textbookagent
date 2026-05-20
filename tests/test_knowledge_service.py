import os
import tempfile

from agent.knowledge.service import KnowledgeService
from agent.knowledge.retriever import KnowledgeRetriever


def test_wiki_chunking_prefers_sections_and_preserves_markdown_blocks():
    content = """# 第一章 绪论

这里介绍研究背景。

| 参数 | 数值 |
| --- | --- |
| 跨径 | 20m |

$$M = ql^2 / 8$$

# 第二章 设计计算

""" + "\n".join(["主梁计算内容。"] * 500)

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        chunks = service._chunk_for_wiki(content, max_tokens=120, overlap_tokens=10)

    assert any("绪论" in chunk["section"] for chunk in chunks)
    assert any("设计计算" in chunk["section"] for chunk in chunks)
    assert any("| 参数 | 数值 |" in chunk["text"] for chunk in chunks)
    assert any("$$M = ql^2 / 8$$" in chunk["text"] for chunk in chunks)
    assert len([chunk for chunk in chunks if "设计计算" in chunk["section"]]) > 1


def test_build_llm_wiki_fallback_records_chunk_metadata_and_graph_evidence():
    content = """# 第一章 桥梁概况

预应力混凝土简支T梁桥位于都江堰柏条河，采用公路-Ⅰ级汽车荷载。
主梁配置预应力钢束，并进行承载力验算。
"""

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        service._extract_wiki_items = lambda chunks, source_name: service._fallback_wiki_items(chunks, source_name)
        result = service._build_llm_wiki(os.path.join(tmp, "paper.md"), content, "tb")
        index_path = os.path.join(tmp, "knowledge", "tb", "_llm_wiki", "index.json")
        graph_path = os.path.join(tmp, "knowledge", "tb", "_llm_wiki", "graph.json")

        assert result["chunks"] >= 1
        assert os.path.isfile(index_path)
        assert os.path.isfile(graph_path)

        import json
        index = json.load(open(index_path, encoding="utf-8"))
        assert index["chunks"][0]["summary"]
        assert index["chunks"][0]["use_when"]
        assert "source_quote" in index["chunks"][0]


def test_organize_knowledge_skips_unchanged_indexed_sources():
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        service._extract_wiki_items = lambda chunks, source_name: service._fallback_wiki_items(chunks, source_name)
        source_dir = os.path.join(tmp, "knowledge", "tb", "sources")
        os.makedirs(source_dir, exist_ok=True)
        path = os.path.join(source_dir, "paper.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 第一章\n\n预应力混凝土简支T梁桥。")

        first = service.organize_knowledge("tb")
        second = service.organize_knowledge("tb")

        assert first["processed_files"] == 1
        assert second["processed_files"] == 0
        assert second["skipped_files"] == 1

        status_path = os.path.join(tmp, "knowledge", "tb", "_llm_wiki", "tasks", "organize_status.json")
        assert os.path.isfile(status_path)


def test_large_wiki_uses_fast_local_metadata(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        chunks = [{"title": f"Section {i}", "text": "桥梁结构 智能体 知识库 " * 80, "section": f"Section {i}", "part": 1} for i in range(25)]
        called = {"llm": False}

        def fail_llm():
            called["llm"] = True
            raise AssertionError("LLM should not be called for fast large-source metadata")

        service._get_llm = fail_llm
        result = service._extract_wiki_items(chunks, "paper.md")
        assert called["llm"] is False
        assert result["pages"]
        assert result["entities"]


def test_stale_organize_task_is_marked_interrupted():
    import tempfile
    import time
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7200))
        service._save_task_status("tb", {
            "sources": {
                "src": {"status": "processing", "updated_at": old}
            }
        })
        status = service.get_organize_task_status("tb", stale_after_seconds=60)
        source = status["sources"]["src"]
        assert source["status"] == "interrupted"
        assert "Previous organize task" in source["error"]


def test_compat_index_is_file_level_not_chunk_dump():
    content = "# 第一章\n\n预应力混凝土简支T梁桥。"

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        service._extract_wiki_items = lambda chunks, source_name: service._fallback_wiki_items(chunks, source_name)
        service._build_llm_wiki(os.path.join(tmp, "paper.md"), content, "tb")

        import json
        compat_path = os.path.join(tmp, "knowledge", "tb", "index.json")
        root_path = os.path.join(tmp, "knowledge", "index.json")
        compat = json.load(open(compat_path, encoding="utf-8"))
        root = json.load(open(root_path, encoding="utf-8"))

        assert "files" in compat
        assert "chunks" not in compat
        assert "pages" not in compat
        assert compat["files"][0]["canonical_index"] == "tb/_llm_wiki/index.json"
        assert compat["files"][0]["content_hash"]
        assert root["files"][0]["book_id"] == "tb"


def test_embedding_manifest_is_reserved_and_retriever_returns_evidence_pack():
    content = """# 第一章 向量检索

向量检索用于从教材知识库中召回相关分块。BM25 可以作为无 embedding 的第一阶段召回。
"""

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        service._extract_wiki_items = lambda chunks, source_name: service._fallback_wiki_items(chunks, source_name)
        service._build_llm_wiki(os.path.join(tmp, "paper.md"), content, "tb")

        emb_path = os.path.join(tmp, "knowledge", "tb", "_llm_wiki", "embeddings", "index.json")
        assert os.path.isfile(emb_path)

        retriever = KnowledgeRetriever(tmp, "tb")
        pack = retriever.format_evidence_pack("向量检索 知识库", limit=2)

        assert "Knowledge Evidence Pack" in pack
        assert "Citation: knowledge/_llm_wiki/chunks/" in pack
        assert "向量检索" in pack
