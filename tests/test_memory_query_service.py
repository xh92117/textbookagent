import json

from agent.memory.conversation_store import ConversationStore
from agent.memory.query_service import MemoryQueryService
from agent.memory.realtime import RealtimeMemoryRecorder


def test_memory_query_service_combines_profile_process_and_history(tmp_path):
    store = ConversationStore(tmp_path / "memory" / "long-term" / "index.db")
    store.append_messages(
        "textbook_demo",
        [
            {"role": "user", "content": "write chapter 1"},
            {"role": "assistant", "content": "chapter 1 done"},
        ],
        channel_type="textbook",
    )

    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process("textbook_demo", "proc_demo", "write chapter 1", channel_type="textbook")
    recorder.finish_process("proc_demo", final_response="chapter 1 done")

    chat_dir = tmp_path / "chat_history"
    chat_dir.mkdir()
    (chat_dir / "textbook_demo.json").write_text(
        json.dumps([{"role": "user", "content": "legacy ui message"}]),
        encoding="utf-8",
    )

    service = MemoryQueryService(tmp_path, conversation_store=store)
    result = service.query(session_id="textbook_demo", process_id="proc_demo")

    assert result["process"]["process_id"] == "proc_demo"
    assert result["history"]["total"] == 2
    assert result["textbook_history"]["total"] == 1
    assert result["profile"]["recent_focus"]


def test_conversation_store_detects_recent_duplicate_text(tmp_path):
    store = ConversationStore(tmp_path / "memory" / "long-term" / "index.db")
    store.append_messages(
        "s1",
        [{"role": "user", "content": "same visible text"}],
        channel_type="textbook",
    )

    assert store.has_recent_text_message("s1", "user", "same visible text")
    assert not store.has_recent_text_message("s1", "assistant", "same visible text")


class _FakeProfileModel:
    def call(self, request):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "preferences": ["prefers concise progress updates"],
                            "goals": ["maintain durable project memory"],
                            "projects": ["textbook agent memory system"],
                            "facts": ["uses process-level memory"],
                        })
                    }
                }
            ]
        }


def test_process_profile_llm_distillation_merges_patch(tmp_path):
    recorder = RealtimeMemoryRecorder(str(tmp_path))
    recorder.start_process("s1", "p1", "please improve memory", channel_type="web")
    recorder.finish_process("p1", final_response="memory improved")

    assert recorder.distill_user_profile("p1", _FakeProfileModel())

    profile = json.loads((tmp_path / "memory" / "user_profile.json").read_text(encoding="utf-8"))
    assert "prefers concise progress updates" in profile["preferences"]
    assert "uses process-level memory" in profile["facts"]
