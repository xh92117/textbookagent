import json

from agent.memory.realtime import RealtimeMemoryRecorder
from agent.memory.service import MemoryService
from agent.tools.memory.memory_search import MemorySearchTool


class _FailIfSearchedMemoryManager:
    async def search(self, **kwargs):
        raise AssertionError("recent activity queries should not fall through to generic search")


def test_memory_service_routes_recent_activity_question_to_process_logs(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path), process_state_files_enabled=False)
    recorder.start_process(
        "s1",
        "p1",
        "\u624b\u52a8\u66f4\u65b0\u6559\u6750\u72b6\u6001\uff0c\u5e76\u6e05\u7406\u8bb0\u5fc6\u7d22\u5f15",
        channel_type="web",
    )
    recorder.finish_process(
        "p1",
        final_response="\u5df2\u5c06\u6559\u6750\u72b6\u6001\u66f4\u65b0\u4e3a 100%\uff0c\u5e76\u79fb\u9664\u65e7\u8fd0\u884c\u65e5\u5fd7\u7d22\u5f15\u3002",
    )

    result = MemoryService(str(tmp_path)).dispatch(
        "natural_language",
        {"text": "\u4f60\u521a\u624d\u505a\u4e86\u4ec0\u4e48\uff1f"},
    )

    assert result["action"] == "recent_activity"
    assert result["code"] == 200
    activities = result["payload"]["activities"]
    assert activities
    assert activities[0]["process_id"] == "p1"
    assert "\u6559\u6750\u72b6\u6001" in activities[0]["summary"]
    assert activities[0]["path"] == "memory/processes/p1.json"


def test_memory_search_short_circuits_recent_activity_questions(tmp_path):
    memory_dir = tmp_path / "memory"
    process_dir = memory_dir / "processes"
    process_dir.mkdir(parents=True)
    (process_dir / "p2.json").write_text(
        json.dumps(
            {
                "process_id": "p2",
                "status": "completed",
                "user_message": "\u4fee\u590d\u8bb0\u5fc6\u8bfb\u53d6\u4fa7\u7684\u6700\u8fd1\u6d3b\u52a8\u53ec\u56de",
                "final_response": "\u5df2\u8865\u5145\u6700\u8fd1\u6d3b\u52a8\u53ec\u56de\u901a\u9053\u3002",
                "updated_at": "2026-05-27T18:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    tool = MemorySearchTool(_FailIfSearchedMemoryManager(), system_root=str(tmp_path))
    result = tool.execute({"query": "\u4f60\u4e4b\u524d\u505a\u4e86\u4ec0\u4e48\uff1f"})

    assert result.status == "success"
    assert "Recent activity" in result.result
    assert "memory/processes/p2.json" in result.result
    assert "\u6700\u8fd1\u6d3b\u52a8\u53ec\u56de" in result.result


def test_recent_activity_summary_strips_injected_context_lines(tmp_path):
    process_dir = tmp_path / "memory" / "processes"
    process_dir.mkdir(parents=True)
    (process_dir / "p3.json").write_text(
        json.dumps(
            {
                "process_id": "p3",
                "status": "completed",
                "user_message": (
                    "[Current textbook id: tb1]\n"
                    "[Path rule: When writing this textbook, write chapter files ONLY under the canonical directory and do not create duplicates]\n"
                    "[Outline]\n"
                    "# \u6559\u6750\u5927\u7eb2\n"
                    "\u8fd9\u662f\u6ce8\u5165\u7684\u5927\u7eb2\u5185\u5bb9\n"
                    "\u8bf7\u68c0\u67e5\u6559\u6750\u5b8c\u6210\u72b6\u6001"
                ),
                "final_response": "\u6559\u6750\u5df2\u5168\u90e8\u5b8c\u6210\u3002",
                "updated_at": "2026-05-27T18:10:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = MemoryService(str(tmp_path)).dispatch("recent_activity", {"limit": 1})
    summary = result["payload"]["activities"][0]["summary"]

    assert "Path rule" not in summary
    assert "Current textbook" not in summary
    assert "\u6559\u6750\u5927\u7eb2" not in summary
    assert "\u6559\u6750\u5df2\u5168\u90e8\u5b8c\u6210" in summary
