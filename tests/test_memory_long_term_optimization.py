import json

from agent.memory.manager import MemoryManager
from agent.memory.service import MemoryService
from agent.memory.storage import SearchResult
from agent.tools.memory.memory_search import MemorySearchTool


def _write_memory(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "MEMORY.md").write_text(
        "# MEMORY.md\n\n"
        "## Promoted Memory - 2026-05-26 10:00\n\n"
        "- 用户偏好：回答尽量简短，先给结论。\n"
        "  - source: candidate `concise`; evidence_count=2\n\n"
        "## Promoted Memory - 2026-05-26 10:05\n\n"
        "- 用户偏好：回答要详细展开，解释推理过程。\n"
        "  - source: candidate `detail`; evidence_count=2\n\n"
        "## Promoted Memory - 2026-05-26 10:10\n\n"
        "- 写论文时请保持严谨并保留引用线索。\n"
        "  - source: candidate `paper`; evidence_count=2\n",
        encoding="utf-8",
    )


def test_long_term_memory_usage_stats_are_incremented(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir)

    result = MemoryService(str(tmp_path)).dispatch(
        "record_usage",
        {"memory_key": "concise", "query": "请先给结论"},
    )
    usage = json.loads((memory_dir / "usage" / "long_term_usage.json").read_text(encoding="utf-8"))

    assert result["code"] == 200
    assert usage["concise"]["use_count"] == 1
    assert usage["concise"]["last_query"] == "请先给结论"


def test_long_term_memory_conflict_detection_finds_written_conflicts(tmp_path):
    _write_memory(tmp_path / "memory")

    result = MemoryService(str(tmp_path)).dispatch("detect_long_term_conflicts", {})

    assert result["code"] == 200
    assert result["payload"]["conflict_count"] == 1
    assert result["payload"]["conflicts"][0]["type"] == "brevity_vs_detail"


def test_memory_explainer_describes_relevant_memory_without_paths(tmp_path):
    _write_memory(tmp_path / "memory")

    result = MemoryService(str(tmp_path)).dispatch("explain", {"query": "为什么你先给结论"})

    assert result["code"] == 200
    assert "我参考了与你当前问题相关的长期偏好" in result["payload"]["explanation"]
    assert "MEMORY.md" not in result["payload"]["explanation"]


def test_long_term_memory_compression_rewrites_promoted_blocks(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir)

    result = MemoryService(str(tmp_path)).dispatch("compress_long_term", {})
    text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

    assert result["code"] == 200
    assert result["payload"]["compressed_count"] == 3
    assert "## Consolidated Long-Term Memory" in text
    assert text.count("用户偏好：回答尽量简短") == 1
    assert result["payload"]["snapshot_file"].startswith("candidates/snapshots/compress_")


def test_context_tagged_memory_is_prioritized_for_matching_tasks():
    paper = SearchResult(
        path="memory/MEMORY.md",
        start_line=1,
        end_line=3,
        score=0.5,
        snippet="写论文时请保持严谨并保留引用线索。",
        source="memory",
        metadata={
            **MemoryManager._classify_memory("memory/MEMORY.md", "memory"),
            "context_tags": ["paper"],
        },
    )
    code = SearchResult(
        path="memory/MEMORY.md",
        start_line=5,
        end_line=7,
        score=0.55,
        snippet="写代码时先给测试命令。",
        source="memory",
        metadata={
            **MemoryManager._classify_memory("memory/MEMORY.md", "memory"),
            "context_tags": ["code"],
        },
    )

    ranked = MemoryManager._prioritize_context_tags("请帮我写论文摘要", [code, paper])

    assert ranked[0].metadata["context_tags"] == ["paper"]


def test_forgotten_memory_is_written_to_quarantine(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir)

    MemoryService(str(tmp_path)).dispatch("forget_memory", {"query": "忘掉简短回答这个记忆"})
    quarantine = (memory_dir / "quarantine" / "disabled_memories.jsonl").read_text(encoding="utf-8")

    assert "回答尽量简短" in quarantine
    assert "forgotten" in quarantine


def test_memory_audit_summary_reports_recent_changes(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir)
    service = MemoryService(str(tmp_path))
    service.dispatch("forget_memory", {"query": "忘掉简短回答这个记忆"})
    service.dispatch("record_usage", {"memory_key": "paper", "query": "写论文"})

    result = service.dispatch("audit_summary", {})

    assert result["code"] == 200
    assert result["payload"]["quarantine_count"] == 1
    assert result["payload"]["usage_keys"] == ["paper"]
