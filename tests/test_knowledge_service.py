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


def test_wiki_chunking_uses_top_level_sections_by_default():
    content = "\n\n".join(
        [
            "# Chapter 1\n\n" + ("A" * 12000),
            "## Section 1.1\n\nNested content",
            "# Chapter 2\n\nSecond chapter",
        ]
    )

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        chunks = service._chunk_for_wiki(content)

    assert len(chunks) == 2
    assert chunks[0]["title"] == "Chapter 1"
    assert "Section 1.1" in chunks[0]["text"]
    assert len(chunks[0]["text"]) > 12000


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
        assert index["chunks"][0]["path"].startswith("chunks/paper_")
        assert index["chunks"][0]["path"].endswith(".md")


def test_secondary_graph_filters_noise_and_keeps_section_evidence():
    content = """# 第八章 记忆与检索

# 8.1 RAG 与向量数据库

RAG（检索增强生成）通过查询 Qdrant 向量数据库召回证据，再交给 LLM 生成答案。
图片 9f2c0d1ab7396e001122334455667788.jpg 不应成为实体。

# 8.2 记忆系统

长期记忆依赖向量检索，短期记忆依赖上下文窗口。
"""
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        chunks = service._chunk_for_wiki(content)
        extracted = service._fallback_section_graph_items(service._section_graph_windows(chunks))
        filtered = service._dedupe_extracted_wiki(service._filter_graph_items(extracted))

    names = {item["name"] for item in filtered["entities"]}
    assert "RAG" in names
    assert "Qdrant" in names
    assert not any("9f2c0d1ab7396e001122334455667788" in name for name in names)
    assert all(rel.get("evidence") for rel in filtered["relations"])


def test_parse_document_resumes_missing_secondary_graph_without_rebuilding():
    import json

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        source_dir = os.path.join(tmp, "knowledge", "tb", "sources")
        wiki_dir = os.path.join(tmp, "knowledge", "tb", "_llm_wiki")
        os.makedirs(os.path.join(wiki_dir, "chunks"), exist_ok=True)
        os.makedirs(os.path.join(wiki_dir, "pages"), exist_ok=True)
        source_path = os.path.join(source_dir, "paper.md")
        os.makedirs(source_dir, exist_ok=True)
        with open(source_path, "w", encoding="utf-8") as f:
            f.write("# 第八章 记忆与检索\n\nRAG 与 Qdrant。")
        signature = service._source_file_signature(source_path)
        source_id = "paper_source"
        chunk_id = source_id + "_001"
        with open(os.path.join(wiki_dir, "chunks", "paper_第八章_记忆与检索.md"), "w", encoding="utf-8") as f:
            f.write("---\nid: paper_source_001\n---\n\n# 第八章 记忆与检索\n\n## 8.1 RAG\n\nRAG 调用 Qdrant。")
        index = {
            "version": "llm-wiki-v1",
            "sources": [{
                "id": source_id,
                "name": "paper.md",
                "path": source_path,
                **signature,
                "pipeline_stages": {
                    "chunk": {"status": "done", "version": service._pipeline_versions()["chunk"]},
                    "primary_metadata": {"status": "done", "version": service._pipeline_versions()["primary_metadata"]},
                },
            }],
            "chunks": [{
                "id": chunk_id,
                "source_id": source_id,
                "title": "第八章 记忆与检索",
                "section": "第八章 记忆与检索",
                "path": "chunks/paper_第八章_记忆与检索.md",
                "summary": "RAG",
                "use_when": "RAG",
                "keywords": ["RAG"],
                "related_entities": [],
                "chars": 20,
            }],
            "pages": [{
                "id": "page/rag",
                "title": "RAG",
                "path": "pages/rag.md",
                "summary": "RAG",
                "source_id": source_id,
                "source_chunk_ids": [chunk_id],
            }],
            "entities": [],
            "relations": [],
        }
        with open(os.path.join(wiki_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)

        service._build_llm_wiki = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should resume instead of rebuilding"))
        service._extract_secondary_graph_items = lambda chunks, source_name: {
            "pages": [],
            "chunk_metadata": [],
            "entities": [{
                "name": "RAG",
                "type": "method",
                "description": "检索增强生成",
                "source_chunk_ids": [0],
                "section_title": "8.1 RAG",
                "evidence": "RAG 调用 Qdrant",
            }],
            "relations": [{
                "source": "RAG",
                "target": "Qdrant",
                "relation": "calls",
                "source_chunk_ids": [0],
                "section_title": "8.1 RAG",
                "evidence": "RAG 调用 Qdrant",
                "confidence": 0.8,
            }],
        }

        result = service.parse_document(source_path, "tb")
        updated = service._load_wiki_index("tb")

        assert result["resumed"] is True
        assert updated["sources"][0]["pipeline_stages"]["secondary_graph"]["version"] == service._pipeline_versions()["secondary_graph"]
        assert updated["entities"][0]["source_chunk_ids"] == [chunk_id]
        assert updated["relations"][0]["source_chunk_ids"] == [chunk_id]


def test_graph_normalization_migration_normalizes_types_and_relations():
    import json

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        wiki_dir = os.path.join(tmp, "knowledge", "tb", "_llm_wiki")
        os.makedirs(wiki_dir, exist_ok=True)
        index = {
            "version": "llm-wiki-v1",
            "sources": [],
            "chunks": [],
            "pages": [],
            "entities": [
                {"name": "openai", "type": "平台", "description": "OpenAI 平台", "source_chunk_ids": ["c1"]},
                {"name": "OpenAI", "type": "platform", "description": "OpenAI", "source_chunk_ids": ["c1"], "sections": ["s1"]},
                {"name": "9f2c0d1ab7396e001122334455667788", "type": "concept", "source_chunk_ids": ["c1"]},
            ],
            "relations": [
                {"source": "HelloAgentsLLM", "target": "openai", "relation": "依赖关系", "source_chunk_ids": ["c1"], "evidence": "client = OpenAI(...)"},
                {"source": "HelloAgentsLLM", "target": "OpenAI", "relation": "depends_on", "source_chunk_ids": ["c2"], "evidence": "client = OpenAI(...)", "section_title": "s1"},
                {"source": "source", "target": "OpenAI", "relation": "包含", "source_chunk_ids": ["c3"], "evidence": "noise"},
            ],
        }
        with open(os.path.join(wiki_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)

        result = service.migrate_graph_normalization("tb")
        migrated = service._load_wiki_index("tb")

    assert result["status"] == "success"
    names = {e["name"]: e for e in migrated["entities"]}
    assert "OpenAI" in names
    assert names["OpenAI"]["type"] == "platform"
    assert not any("9f2c0d1ab7396e001122334455667788" == name for name in names)
    assert all(r["relation"] in {"depends_on", "contains"} for r in migrated["relations"])
    assert any(r["relation"] == "depends_on" and r["target"] == "OpenAI" for r in migrated["relations"])


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


def test_list_files_page_paginates_and_filters_without_tree_payload():
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        source_dir = os.path.join(tmp, "knowledge", "tb", "sources")
        chunk_dir = os.path.join(tmp, "knowledge", "tb", "_llm_wiki", "chunks")
        os.makedirs(source_dir, exist_ok=True)
        os.makedirs(chunk_dir, exist_ok=True)
        for i in range(7):
            folder = source_dir if i < 3 else chunk_dir
            with open(os.path.join(folder, f"file_{i:03d}.md"), "w", encoding="utf-8") as f:
                f.write(f"# File {i}\n\ncontent")

        page = service.list_files_page("tb", offset=2, limit=3)
        assert page["total"] == 7
        assert len(page["files"]) == 3
        assert page["has_more"] is True
        assert "tree" not in page

        filtered = service.list_files_page("tb", query="file_006")
        assert filtered["total"] == 1
        assert filtered["files"][0]["name"] == "file_006.md"


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
    from config import conf
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        chunks = [{"title": f"Section {i}", "text": "桥梁结构 智能体 知识库 " * 80, "section": f"Section {i}", "part": 1} for i in range(25)]
        called = {"llm": False}

        def fail_llm():
            called["llm"] = True
            raise AssertionError("LLM should not be called for fast large-source metadata")

        service._get_llm = fail_llm
        old_threshold = conf().get("knowledge_fast_chunk_threshold", 200)
        conf()["knowledge_fast_chunk_threshold"] = 20
        try:
            result = service._extract_wiki_items(chunks, "paper.md")
        finally:
            conf()["knowledge_fast_chunk_threshold"] = old_threshold
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


def test_pdf_parse_prefers_mineru_when_configured():
    from config import conf

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        source_dir = os.path.join(tmp, "knowledge", "tb", "sources")
        os.makedirs(source_dir, exist_ok=True)
        path = os.path.join(source_dir, "paper.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF demo")

        old_key = conf().get("mineru_api_key", "")
        conf()["mineru_api_key"] = "token"
        captured = {}
        try:
            service._extract_pdf_with_mineru = lambda fp, book_id="": "# MinerU Parsed\n\nclean markdown"
            service._extract_pdf_local = lambda fp: (_ for _ in ()).throw(AssertionError("local parser should not be used"))
            def fake_build(fp, content, book_id=""):
                captured["content"] = content
                return {"organized_count": 1, "chunks": 1}

            service._build_llm_wiki = fake_build
            result = service.parse_document(path, "tb")
        finally:
            conf()["mineru_api_key"] = old_key

        assert result["chunks"] == 1
        assert "MinerU Parsed" in captured["content"]


def test_pdf_parse_falls_back_when_mineru_returns_empty():
    from config import conf

    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        source_dir = os.path.join(tmp, "knowledge", "tb", "sources")
        os.makedirs(source_dir, exist_ok=True)
        path = os.path.join(source_dir, "paper.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF demo")

        old_key = conf().get("mineru_api_key", "")
        conf()["mineru_api_key"] = "token"
        captured = {}
        try:
            service._extract_pdf_with_mineru = lambda fp, book_id="": ""
            service._extract_pdf_local = lambda fp: "# Local Parsed\n\nfallback markdown"
            def fake_build(fp, content, book_id=""):
                captured["content"] = content
                return {"organized_count": 1, "chunks": 1}

            service._build_llm_wiki = fake_build
            result = service.parse_document(path, "tb")
        finally:
            conf()["mineru_api_key"] = old_key

        assert result["chunks"] == 1
        assert "Local Parsed" in captured["content"]
