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


def test_organize_knowledge_force_reprocesses_indexed_sources():
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        source_dir = os.path.join(tmp, "knowledge", "tb", "sources")
        os.makedirs(source_dir, exist_ok=True)
        path = os.path.join(source_dir, "paper.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Demo\n\nAlready indexed source.")

        calls = {"parse": 0}
        service._is_source_already_indexed = lambda fp, book_id="": True
        service.parse_document = lambda fp, book_id="": calls.__setitem__("parse", calls["parse"] + 1) or {
            "organized_count": 1,
            "chunks": 1,
            "entities": 0,
            "relations": 0,
        }
        service.build_knowledge_graph = lambda book_id="": {"edges": []}
        service._write_cross_references = lambda graph, book_id="": 0

        normal = service.organize_knowledge("tb", force=False)
        normal_calls = calls["parse"]
        forced = service.organize_knowledge("tb", force=True)

        assert normal["processed_files"] == 0
        assert normal["skipped_files"] == 1
        assert normal_calls == 0
        assert forced["processed_files"] == 1
        assert forced["skipped_files"] == 0
        assert forced["force"] is True
        assert calls["parse"] - normal_calls == 1


def test_get_status_reports_actual_wiki_chunk_counts():
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        wiki_dir = os.path.join(tmp, "knowledge", "tb", "_llm_wiki")
        os.makedirs(wiki_dir, exist_ok=True)
        with open(os.path.join(wiki_dir, "index.json"), "w", encoding="utf-8") as f:
            import json
            json.dump({
                "sources": [{"id": "src"}],
                "chunks": [{"id": "c1"}, {"id": "c2"}],
                "pages": [{"id": "p1"}],
                "entities": [{"id": "e1"}],
                "relations": [{"id": "r1"}],
            }, f)
        source_dir = os.path.join(tmp, "knowledge", "tb", "sources")
        os.makedirs(source_dir, exist_ok=True)
        with open(os.path.join(source_dir, "paper.md"), "w", encoding="utf-8") as f:
            f.write("# Demo\n")

        selected = service.get_status("tb")
        all_books = service.get_status("")

        assert selected["wiki"]["chunks"] == 2
        assert selected["wiki"]["pages"] == 1
        assert all_books["wiki"]["chunks"] == 2


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
def test_wiki_index_records_normalized_terms_for_recall():
    content = "# Smart Construction Workflow\n\nAI-agent based textbook knowledge retrieval workflow."

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        service._extract_wiki_items = lambda chunks, source_name: service._fallback_wiki_items(chunks, source_name)
        service._build_llm_wiki(os.path.join(tmp, "paper.md"), content, "tb")

        import json
        index_path = os.path.join(tmp, "knowledge", "tb", "_llm_wiki", "index.json")
        index = json.load(open(index_path, encoding="utf-8"))
        terms = index["chunks"][0].get("normalized_terms", [])

        assert "smart" in terms
        assert "construction" in terms

        retriever = KnowledgeRetriever(tmp, "tb")
        evidence = retriever.retrieve("smart-construction", limit=1)
        assert evidence
        assert evidence[0]["chunk_id"] == index["chunks"][0]["id"]


def test_retriever_reports_graph_reason_and_diagnostics():
    import json

    with tempfile.TemporaryDirectory() as tmp:
        wiki_dir = os.path.join(tmp, "knowledge", "tb", "_llm_wiki")
        chunk_dir = os.path.join(wiki_dir, "chunks")
        os.makedirs(chunk_dir, exist_ok=True)
        for name, body in {
            "c1.md": "# Planning\n\nAgent planning creates a task tree.",
            "c2.md": "# Memory\n\nMemory retrieval supports long-running agents.",
            "c3.md": "# Tools\n\nTool use connects agents with external systems.",
        }.items():
            with open(os.path.join(chunk_dir, name), "w", encoding="utf-8") as f:
                f.write(body)
        index = {
            "sources": [{"id": "s1", "title": "Agent paper"}],
            "entities": [{"id": "agent", "name": "Agent"}],
            "relations": [{"type": "supports", "source_chunk_ids": ["c1", "c2"]}],
            "chunks": [
                {
                    "id": "c1",
                    "title": "Planning",
                    "summary": "Agent planning",
                    "keywords": ["planning"],
                    "related_entities": ["Agent"],
                    "path": "chunks/c1.md",
                },
                {
                    "id": "c2",
                    "title": "Memory",
                    "summary": "Memory",
                    "keywords": ["memory"],
                    "related_entities": ["Agent"],
                    "path": "chunks/c2.md",
                },
                {
                    "id": "c3",
                    "title": "Tools",
                    "summary": "Tools",
                    "keywords": ["tools"],
                    "related_entities": [],
                    "path": "chunks/c3.md",
                },
            ],
        }
        with open(os.path.join(wiki_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)

        retriever = KnowledgeRetriever(tmp, "tb")
        evidence = retriever.retrieve("planning", limit=2, use_cache=False)
        diagnostics = retriever.diagnose("planning", limit=2)
        pack = retriever.format_evidence_pack("planning", limit=2)

        assert any(item.get("graph_reason") for item in evidence)
        assert diagnostics["chunk_count"] == 3
        assert diagnostics["graph_expanded_count"] >= 1
        assert diagnostics["top_chunks"]
        assert any(item.get("rerank_score", 0) > 0 for item in diagnostics["top_chunks"])
        assert "Rerank score:" in pack
        assert "Graph reason:" in pack


def test_extracted_asset_filter_skips_small_and_logo_like_images():
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)

        keep, reason = service._should_keep_extracted_asset(b"not an image", name="logo.png", width=400, height=300)
        assert keep is False
        assert "logo" in reason

        keep, reason = service._should_keep_extracted_asset(b"not an image", name="figure.png", width=40, height=40)
        assert keep is False
        assert "small image" in reason

        keep, reason = service._should_keep_extracted_asset(b"not an image", name="diagram.png", width=800, height=500)
        assert keep is True
