import json
import os
import tempfile

from agent.knowledge.service import KnowledgeService


def test_knowledge_graph_projection_limits_and_focuses():
    with tempfile.TemporaryDirectory() as tmp:
        service = KnowledgeService(tmp)
        wiki_dir = os.path.join(tmp, "knowledge", "tb", "_llm_wiki")
        os.makedirs(wiki_dir, exist_ok=True)
        nodes = [{"id": f"n{i}", "label": f"Node {i}", "category": "concept"} for i in range(30)]
        edges = [{"source": f"n{i}", "target": f"n{i+1}", "label": "related"} for i in range(29)]
        with open(os.path.join(wiki_dir, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({"nodes": nodes, "edges": edges}, f)

        summary = service.get_knowledge_graph("tb", limit=10)
        assert summary["total_nodes"] == 30
        assert summary["returned_nodes"] <= 20
        assert summary["has_more"] is True

        focused = service.get_knowledge_graph("tb", limit=10, focus_id="n5")
        ids = {node["id"] for node in focused["nodes"]}
        assert "n5" in ids
        assert "n4" in ids or "n6" in ids
