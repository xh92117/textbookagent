"""
ChatService - Wraps the Agent stream execution to produce CHAT protocol chunks.

Translates agent events (message_update, message_end, tool_execution_end, etc.)
into the CHAT socket protocol format (content chunks with segment_id, tool_calls chunks).
"""

import time
from typing import Callable, Optional

from common.log import logger


class ChatService:
    """
    High-level service that runs an Agent for a given query and streams
    the results as CHAT protocol chunks via a callback.

    Usage:
        svc = ChatService(agent_bridge)
        svc.run(query, session_id, send_chunk_fn)
    """

    def __init__(self, agent_bridge):
        """
        :param agent_bridge: AgentBridge instance (manages agent lifecycle)
        """
        self.agent_bridge = agent_bridge

    def run(self, query: str, session_id: str, send_chunk_fn: Callable[[dict], None],
            channel_type: str = ""):
        """
        Run the agent for *query* and stream results back via *send_chunk_fn*.

        The method blocks until the agent finishes. After it returns the SDK
        will automatically send the final (streaming=false) message.

        :param query: user query text
        :param session_id: session identifier for agent isolation
        :param send_chunk_fn: callable(chunk_data: dict) to send a streaming chunk
        :param channel_type: source channel (e.g. "web", "feishu") for persistence
        """
        agent = self.agent_bridge.get_agent(session_id=session_id)
        if agent is None:
            raise RuntimeError("Failed to initialise agent for the session")

        # Pass context metadata to model for downstream API requests
        if hasattr(agent, 'model'):
            agent.model.channel_type = channel_type or ""
            agent.model.session_id = session_id or ""

        if self._handle_memory_natural_language(query, send_chunk_fn):
            return

        process_id = f"{session_id}_{int(time.time() * 1000)}"
        process_recorder = None
        try:
            from agent.memory import RealtimeMemoryRecorder
            from common.app_paths import active_workspace, system_dir
            process_recorder = RealtimeMemoryRecorder(
                system_dir(),
                project_workspace=getattr(agent, "workspace_dir", None) or active_workspace(),
            )
            process_recorder.start_process(session_id, process_id, query, channel_type=channel_type)
        except Exception as e:
            logger.debug(f"[ChatService] realtime process memory start skipped: {e}")

        try:
            from agent.memory import record_user_correction_if_needed
            record_user_correction_if_needed(query, {
                "session_id": session_id,
                "channel_type": channel_type,
                "source": "chat_service",
            })
        except Exception as e:
            logger.debug(f"[ChatService] user correction memory skipped: {e}")

        # State shared between the event callback and this method
        state = _StreamState()

        def on_event(event: dict):
            """Translate agent events into CHAT protocol chunks."""
            event_type = event.get("type")
            data = event.get("data", {})

            if event_type == "reasoning_update":
                delta = data.get("delta", "")
                if delta:
                    send_chunk_fn({
                        "chunk_type": "reasoning",
                        "delta": delta,
                        "segment_id": state.segment_id,
                    })

            elif event_type == "message_update":
                # Incremental text delta
                delta = data.get("delta", "")
                if delta:
                    send_chunk_fn({
                        "chunk_type": "content",
                        "delta": delta,
                        "segment_id": state.segment_id,
                    })

            elif event_type == "message_end":
                # A content segment finished.
                tool_calls = data.get("tool_calls", [])
                if tool_calls:
                    # After tool_calls are executed the next content will be
                    # a new segment; collect tool results until turn_end.
                    state.pending_tool_results = []

            elif event_type == "file_to_send":
                url = data.get("url") or ""
                if url:
                    fname = data.get("file_name") or "file"
                    ft = data.get("file_type") or "file"
                    if ft == "image":
                        link = f"![{fname}]({url})"
                    else:
                        link = f"[{fname}]({url})"
                    send_chunk_fn({
                        "chunk_type": "content",
                        "delta": "\n\n" + link + "\n\n",
                        "segment_id": state.segment_id,
                    })
                    # Remove url so the model won't repeat it in its reply
                    data.pop("url", None)

            elif event_type == "tool_execution_start":
                # Notify the client that a tool is about to run (with its input args)
                tool_name = data.get("tool_name", "")
                arguments = data.get("arguments", {})
                # Cache arguments keyed by tool_call_id so tool_execution_end can include them
                tool_call_id = data.get("tool_call_id", tool_name)
                state.pending_tool_arguments[tool_call_id] = arguments
                send_chunk_fn({
                    "chunk_type": "tool_start",
                    "tool": tool_name,
                    "arguments": arguments,
                })
                if process_recorder:
                    process_recorder.update_process(process_id, "tool_start", tool_name, tool=tool_name)

            elif event_type == "tool_execution_end":
                tool_name = data.get("tool_name", "")
                tool_call_id = data.get("tool_call_id", tool_name)
                # Retrieve cached arguments from the matching tool_execution_start event
                arguments = state.pending_tool_arguments.pop(tool_call_id, data.get("arguments", {}))
                result = data.get("result", "")
                status = data.get("status", "unknown")
                execution_time = data.get("execution_time", 0)
                elapsed_str = f"{execution_time:.2f}s"

                # Serialise result to string if needed
                if not isinstance(result, str):
                    import json
                    try:
                        result = json.dumps(result, ensure_ascii=False)
                    except Exception:
                        result = str(result)

                tool_info = {
                    "name": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "status": status,
                    "elapsed": elapsed_str,
                }

                if state.pending_tool_results is not None:
                    state.pending_tool_results.append(tool_info)
                if process_recorder:
                    process_recorder.update_process(
                        process_id,
                        "tool_end",
                        f"{tool_name}: {status}",
                        tool=tool_name,
                        status=status,
                    )

            elif event_type == "turn_end":
                has_tool_calls = data.get("has_tool_calls", False)
                if has_tool_calls and state.pending_tool_results:
                    # Flush collected tool results as a single tool_calls chunk
                    send_chunk_fn({
                        "chunk_type": "tool_calls",
                        "tool_calls": state.pending_tool_results,
                    })
                    state.pending_tool_results = None
                    # Next content belongs to a new segment
                    state.segment_id += 1

        # Run the agent with our event callback ---------------------------
        logger.info(f"[ChatService] Starting agent run: session={session_id}, query={query[:80]}")

        from config import conf
        max_context_turns = conf().get("agent_max_context_turns", 20)

        # Get full system prompt with routed skills
        routed_skill_filter, skill_route_prompt = agent.route_skills_for_message(query)
        full_system_prompt = agent.get_full_system_prompt(
            skill_filter=routed_skill_filter,
            skill_route_prompt=skill_route_prompt,
        )

        # Create a copy of messages for this execution
        with agent.messages_lock:
            messages_copy = agent.messages.copy()
            original_length = len(agent.messages)

        from agent.protocol.agent_stream import AgentStreamExecutor

        executor = AgentStreamExecutor(
            agent=agent,
            model=agent.model,
            system_prompt=full_system_prompt,
            tools=agent.tools,
            max_turns=agent.max_steps,
            on_event=on_event,
            messages=messages_copy,
            max_context_turns=max_context_turns,
        )

        try:
            response = executor.run_stream(query)
        except Exception:
            # If executor cleared messages (context overflow), sync back
            if len(executor.messages) == 0:
                with agent.messages_lock:
                    agent.messages.clear()
                    logger.info("[ChatService] Cleared agent message history after executor recovery")
            if process_recorder:
                process_recorder.finish_process(process_id, status="error", error="Agent execution failed")
            try:
                from agent.memory import record_agent_error
                record_agent_error("Agent execution failed", {
                    "session_id": session_id,
                    "channel_type": channel_type,
                    "source": "chat_service",
                    "query": query[:1000] if isinstance(query, str) else "",
                })
            except Exception as e:
                logger.debug(f"[ChatService] agent error memory skipped: {e}")
            raise

        # Sync executor messages back to agent (thread-safe).
        # The executor may have trimmed context, making its list shorter than
        # original_length. In that case we must replace entirely — just
        # appending would leave stale pre-trim messages in agent.messages
        # and cause the same trim to fire on every subsequent request.
        with agent.messages_lock:
            trimmed = len(executor.messages) < original_length
            if trimmed:
                # Context was trimmed: the executor appended the new user
                # query *before* trimming, so the new messages (user +
                # assistant + tools) sit at the tail of the trimmed list.
                # We cannot simply slice at original_length (it exceeds the
                # list length).  Instead, count how many messages the
                # executor added on top of the post-trim baseline.
                #
                # Timeline inside executor.run_stream:
                #   1. messages had `original_length` items
                #   2. append user query  → original_length + 1
                #   3. _trim_messages()   → some smaller number (includes the
                #      user query because it belongs to the last turn)
                #   4. LLM replies / tool calls appended
                #
                # The user query message is always the first message of the
                # last turn (it cannot be trimmed away), so we locate it to
                # find where "new" messages begin.
                new_start = original_length  # fallback
                for idx in range(len(executor.messages) - 1, -1, -1):
                    msg = executor.messages[idx]
                    if msg.get("role") == "user":
                        content = msg.get("content", [])
                        is_user_query = False
                        if isinstance(content, list):
                            has_text = any(
                                isinstance(b, dict) and b.get("type") == "text"
                                for b in content
                            )
                            has_tool_result = any(
                                isinstance(b, dict) and b.get("type") == "tool_result"
                                for b in content
                            )
                            is_user_query = has_text and not has_tool_result
                        elif isinstance(content, str):
                            is_user_query = True
                        if is_user_query:
                            new_start = idx
                            break
                new_messages = list(executor.messages[new_start:])
            else:
                new_messages = list(executor.messages[original_length:])
            agent.messages = list(executor.messages)

        # Persist new messages to SQLite so they survive restarts and
        # can be queried via the HISTORY interface.
        if new_messages:
            self._persist_messages(session_id, list(new_messages), channel_type)

        # Store executor reference for files_to_send access
        agent.stream_executor = executor

        # Execute post-process tools
        agent._execute_post_process_tools()

        logger.info(f"[ChatService] Agent run completed: session={session_id}")
        if process_recorder:
            process_recorder.finish_process(process_id, final_response=response, status="completed")
            self._auto_consolidate_memory()
            try:
                from config import conf
                if conf().get("memory_profile_llm_enabled", True):
                    process_recorder.distill_user_profile_async(process_id, getattr(agent, "model", None))
            except Exception:
                pass



    def _handle_memory_natural_language(self, query: str, send_chunk_fn: Callable[[dict], None]) -> bool:
        try:
            from common.app_paths import system_dir
            from agent.memory.service import MemoryService

            result = MemoryService(system_dir()).dispatch("natural_language", {"text": query})
            if result.get("code") == 204:
                return False
            send_chunk_fn({
                "chunk_type": "content",
                "delta": self._format_memory_action_result(result),
                "segment_id": 0,
            })
            return True
        except Exception as exc:
            logger.debug(f"[ChatService] memory natural-language action skipped: {exc}")
            return False

    @staticmethod
    def _auto_consolidate_memory(system_root: str = "", now: str | None = None, health_compress_threshold: int = 0) -> dict:
        try:
            from common.app_paths import system_dir
            from agent.memory.service import MemoryService

            root = system_root or system_dir()
            service = MemoryService(root)
            consolidate_result = service.dispatch("consolidate", {})
            from agent.memory.promotion import MemoryPromotionCandidatePool
            pool = MemoryPromotionCandidatePool(service.memory_dir)
            decay_result = pool.decay_confidence(now=now)
            auto_apply_result = pool.apply_auto_candidates(min_evidence=2)
            cleanup_payload = {"now": now} if now else {}
            cleanup_result = service.dispatch("cleanup_candidates", cleanup_payload)
            payload = consolidate_result.get("payload") or {}
            payload["decay"] = decay_result
            payload["auto_apply"] = auto_apply_result
            payload["cleanup"] = cleanup_result.get("payload") or {}
            payload["health"] = pool.health_report()
            payload["health_actions"] = {"compressed": False}
            if not health_compress_threshold:
                health_compress_threshold = int((service.governance_config() or {}).get("auto_compress_health_threshold", 0) or 0)
            if health_compress_threshold and payload["health"].get("health_score", 100) < health_compress_threshold:
                compress_result = service.dispatch("compress_long_term", {})
                payload["health_actions"] = {
                    "compressed": compress_result.get("code") == 200,
                    "compress": compress_result.get("payload") or {},
                }
            return payload
        except Exception as exc:
            logger.debug(f"[ChatService] memory auto-consolidation skipped: {exc}")
            return {}

    @staticmethod
    def _format_memory_action_result(result: dict) -> str:
        action = result.get("action", "")
        code = result.get("code", 0)
        payload = result.get("payload") or {}
        if code >= 400:
            return f"记忆操作未完成：{result.get('message', 'unknown error')}"
        if action == "candidates":
            total = payload.get("total", 0)
            rows = payload.get("list", [])[:5]
            lines = [f"候选记忆共 {total} 条。"]
            for item in rows:
                lines.append(f"- `{item.get('id', '')}` [{item.get('status', '')}] {item.get('content', '')}")
            return "\n".join(lines)
        if action == "consolidate":
            return f"已整理候选记忆 {payload.get('selected_count', 0)} 条，审查文件：{payload.get('review_file', '') or '无'}"
        if action == "apply_candidate":
            return f"已应用候选记忆：{payload.get('candidate_id', '')}，快照：{payload.get('snapshot_file', '')}"
        if action == "apply_ready_candidates":
            return f"已应用待审查候选记忆 {payload.get('applied_count', 0)} 条。"
        if action == "cleanup_candidates":
            return (
                "已清理候选记忆："
                f"过期 {payload.get('expired_count', 0)} 条，"
                f"归档 {payload.get('archived_count', 0)} 条，"
                f"因常被查阅保留 {payload.get('kept_by_lookup_count', 0)} 条。"
            )
        if action == "resolve_conflict":
            return f"已处理记忆冲突：保留 {payload.get('kept_id', '')}，拒绝 {payload.get('rejected_id', '')}。"
        if action == "rollback_version":
            return f"已回滚记忆版本：{payload.get('version_id', '')}。"
        if action == "rollback_latest_version":
            candidate_id = payload.get("rolled_back_candidate_id", "") or "最近一条"
            return f"已撤销最近写入的记忆：{candidate_id}。"
        if action == "forget_memory":
            previews = payload.get("removed_previews", []) or []
            suffix = f"\n- {previews[0]}" if previews else ""
            return f"已忘掉匹配的记忆 {payload.get('removed_count', 0)} 条。{suffix}"
        if action == "explain":
            return payload.get("explanation", "我会优先遵循你当前这句话的要求。")
        if action == "modify_memory":
            return f"已修改匹配的记忆 {payload.get('modified_count', 0)} 条。"
        return "记忆操作已完成。"

    @staticmethod
    def _persist_messages(session_id: str, new_messages: list, channel_type: str = ""):
        try:
            from config import conf
            if not conf().get("conversation_persistence", True):
                return
        except Exception:
            pass
        try:
            from agent.memory import get_conversation_store
            get_conversation_store().append_messages(
                session_id, new_messages, channel_type=channel_type
            )
        except Exception as e:
            logger.warning(
                f"[ChatService] Failed to persist messages for session={session_id}: {e}"
            )


class _StreamState:
    """Mutable state shared between the event callback and the run method."""

    def __init__(self):
        self.segment_id: int = 0
        # None means we are not accumulating tool results right now.
        # A list means we are in the middle of a tool-execution phase.
        self.pending_tool_results: Optional[list] = None
        # Maps tool_call_id -> arguments captured from tool_execution_start,
        # so that tool_execution_end can attach the correct input args.
        self.pending_tool_arguments: dict = {}
