"""
Agent Stream Execution Module - Multi-turn reasoning based on tool-call

Provides streaming output, event system, and complete tool-call loop
"""
import json
import os
import re
import time
import queue
import threading
from typing import List, Dict, Any, Optional, Callable, Tuple

from agent.protocol.models import LLMRequest, LLMModel
from agent.protocol.message_utils import (
    sanitize_claude_messages,
    compress_turn_to_text_only,
    build_context_state_board,
    compact_current_tool_result_content,
    compact_historical_tool_result_content,
)
from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger
from agent.harness import ContextAnxietyGuard


# Maximum number of characters of model "reasoning / thinking" content to persist
# in conversation history. The full reasoning is still streamed to the UI in real
# time (subject to its own SSE / rendering limits); this bound only controls what
# is stored in DB and replayed in history. Long reasoning is not useful for later
# context (the LLM never sees thinking blocks anyway) and bloats DB.
# Keep aligned with the frontend REASONING_RENDER_CAP and the SSE
# MAX_REASONING_STREAM_CHARS so that storage / stream / display all match.
MAX_STORED_REASONING_CHARS = 4 * 1024  # 4 KB
DEFAULT_LLM_STREAM_IDLE_TIMEOUT_SECONDS = 180

# Marker inserted between head and tail when reasoning is truncated.
_REASONING_TRUNCATE_MARKER = "\n\n... [reasoning truncated, {omitted} chars omitted] ...\n\n"


def _truncate_reasoning_for_storage(text: str) -> str:
    """Trim long reasoning to head + tail with an omission marker.

    Keeps the first and last halves of MAX_STORED_REASONING_CHARS so both the
    initial chain-of-thought and the final conclusions are preserved for UI
    replay, without storing the entire (often very large) middle.
    """
    if not text:
        return text
    if len(text) <= MAX_STORED_REASONING_CHARS:
        return text
    half = MAX_STORED_REASONING_CHARS // 2
    head = text[:half]
    tail = text[-half:]
    omitted = len(text) - len(head) - len(tail)
    return head + _REASONING_TRUNCATE_MARKER.format(omitted=omitted) + tail


class AgentStreamExecutor:
    """
    Agent Stream Executor
    
    Handles multi-turn reasoning loop based on tool-call:
    1. LLM generates response (may include tool calls)
    2. Execute tools
    3. Return results to LLM
    4. Repeat until no more tool calls
    """

    def __init__(
            self,
            agent,  # Agent instance
            model: LLMModel,
            system_prompt: str,
            tools: List[BaseTool],
            max_turns: int = 50,
            on_event: Optional[Callable] = None,
            messages: Optional[List[Dict]] = None,
            max_context_turns: int = 30,
            cancel_event = None
    ):
        """
        Initialize stream executor
        
        Args:
            agent: Agent instance (for accessing context)
            model: LLM model
            system_prompt: System prompt
            tools: List of available tools
            max_turns: Maximum number of turns
            on_event: Event callback function
            messages: Optional existing message history (for persistent conversations)
            max_context_turns: Maximum number of conversation turns to keep in context
            cancel_event: threading.Event to signal cancellation
        """
        self.agent = agent
        self.model = model
        self.system_prompt = system_prompt
        # Convert tools list to dict
        self.tools = {tool.name: tool for tool in tools} if isinstance(tools, list) else tools
        self.max_turns = max_turns
        self.on_event = on_event
        self.max_context_turns = max_context_turns
        self.cancel_event = cancel_event

        # Message history - use provided messages or create new list
        self.messages = messages if messages is not None else []
        
        # Tool failure tracking for retry protection
        self.tool_failure_history = []  # List of (tool_name, args_hash, success) tuples
        self.tool_failure_details = []  # Compact failure records for Runtime Context Board
        
        # Track files to send (populated by read tool)
        self.files_to_send = []  # List of file metadata dicts
        self.short_term_memory = None
        self.tool_route = None
        self.context_compression_history = []
        self.tool_budget = None
        self.tool_metric_events = []
        self._near_max_turn_handoff_saved = False
        self.tool_budget_exhausted = False
        self.chapter_read_cache = {}
        self._deterministic_feedback_emitted = False
        self.tool_phase_state = {}
        self.tool_phase_stop_reason = ""

    def _emit_event(self, event_type: str, data: dict = None):
        """Emit event"""
        if self.on_event:
            try:
                self.on_event({
                    "type": event_type,
                    "timestamp": time.time(),
                    "data": data or {}
                })
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    def _emit_visible_assistant_message(self, content: str, stop_reason: str = "deterministic_stop") -> None:
        """Emit a normal assistant message so SSE/frontends can show deterministic stops."""
        content = (content or "").strip()
        if not content:
            return
        self._emit_event("message_start", {"role": "assistant", "synthetic": True})
        self._emit_event("message_update", {"delta": content})
        self._emit_event("message_end", {
            "content": content,
            "tool_calls": [],
            "stop_reason": stop_reason,
            "synthetic": True,
        })
        self._deterministic_feedback_emitted = True
    
    def _is_thinking_enabled(self) -> bool:
        """Whether deep-thinking mode is on at the model layer.

        Mirrors the global toggle used by ``bridge.agent_bridge`` when deciding
        whether to send ``thinking={"type": "enabled"}`` to the model. Used for
        logging and reasoning-update event emission across all channels.
        """
        from config import conf
        return bool(conf().get("enable_thinking", False))

    def _should_render_thinking_inline(self) -> bool:
        """Whether ``<think>...</think>`` blocks embedded directly in ``content``
        (MiniMax, some third-party proxies) should be surfaced to the channel.

        Only the Web console can render them in a collapsible panel. IM channels
        (WeChat/WeCom/DingTalk/Feishu) must strip them, otherwise users see raw
        XML tags in their chat.
        """
        from config import conf
        channel_type = getattr(self.model, 'channel_type', '') or ''
        return conf().get("enable_thinking", False) and channel_type == 'web'

    def _filter_think_tags(self, text: str) -> str:
        """
        Handle <think>...</think> blocks in content returned by some LLM providers
        (e.g., MiniMax).

        - When inline thinking rendering is allowed (Web + thinking enabled):
          remove only the tags, keep the content inside.
        - Otherwise (IM channels, or thinking disabled globally): remove both
          the tags and the content entirely.
        """
        if not text:
            return text
        import re
        if self._should_render_thinking_inline():
            text = re.sub(r'<think>', '', text)
            text = re.sub(r'</think>', '', text)
        else:
            text = re.sub(r'<think>[\s\S]*?</think>', '', text)
            # Also strip unclosed <think> tag at the end (streaming partial)
            text = re.sub(r'<think>[\s\S]*$', '', text)
        return text

    def _stream_idle_timeout_seconds(self) -> int:
        """Maximum seconds to wait for the next model stream chunk.

        Some providers keep the HTTP stream open after content has already been
        emitted. Without an idle guard, the agent appears stuck until the
        process receives Ctrl+C. The guard is conservative and configurable.
        """
        try:
            from config import conf
            value = int(conf().get("agent_stream_idle_timeout_seconds", DEFAULT_LLM_STREAM_IDLE_TIMEOUT_SECONDS) or 0)
            return max(30, value) if value > 0 else 0
        except Exception:
            return DEFAULT_LLM_STREAM_IDLE_TIMEOUT_SECONDS

    def _tool_call_stall_timeout_seconds(self) -> int:
        """Maximum seconds to wait for a finished-looking tool call tail packet.

        Some OpenAI-compatible providers keep sending heartbeat/empty chunks
        after a complete tool call has already streamed. The lower-level idle
        guard cannot catch that because chunks are still arriving, so we stop
        once the accumulated tool call arguments are stable and parseable.
        """
        try:
            from config import conf
            value = int(conf().get("agent_stream_tool_call_stall_timeout_seconds", 60) or 0)
            return max(1, value) if value > 0 else 0
        except Exception:
            return 60

    def _partial_tool_call_timeout_seconds(self) -> int:
        """Maximum seconds to wait for a non-parseable tool-call tail.

        A provider can stream part of a very large tool call and then keep the
        HTTP stream alive with empty chunks. Waiting forever is worse than
        returning a parse error to the model, because the next turn can recover
        with a smaller tool call.
        """
        try:
            from config import conf
            value = int(conf().get("agent_stream_partial_tool_call_timeout_seconds", 90) or 0)
            return max(1, value) if value > 0 else 0
        except Exception:
            return 90

    @staticmethod
    def _tool_calls_parseable(tool_calls_buffer: Dict[int, Dict[str, str]]) -> bool:
        if not tool_calls_buffer:
            return False
        for tc in tool_calls_buffer.values():
            if not tc.get("name"):
                return False
            args_str = tc.get("arguments") or ""
            if not args_str.strip():
                return False
            try:
                json.loads(args_str)
            except Exception:
                return False
        return True

    def _iter_stream_with_idle_timeout(self, stream, timeout_seconds: int):
        if not timeout_seconds:
            yield from stream
            return

        q: "queue.Queue" = queue.Queue(maxsize=128)
        sentinel = object()

        def producer():
            try:
                for item in stream:
                    q.put(("chunk", item))
                q.put(("done", sentinel))
            except Exception as exc:
                q.put(("error", exc))

        thread = threading.Thread(target=producer, name="llm-stream-reader", daemon=True)
        thread.start()
        while True:
            try:
                kind, payload = q.get(timeout=timeout_seconds)
            except queue.Empty:
                raise TimeoutError(
                    f"LLM stream idle for {timeout_seconds}s; closing partial stream to prevent executor hang"
                )
            if kind == "chunk":
                yield payload
            elif kind == "error":
                raise payload
            else:
                return

    def _hash_args(self, args: dict) -> str:
        """Generate a simple hash for tool arguments"""
        import hashlib
        # Sort keys for consistent hashing
        args_str = json.dumps(args, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(args_str.encode()).hexdigest()[:8]

    def _latest_assistant_text_excerpt(self, limit: int = 800) -> str:
        for msg in reversed(self.messages):
            if msg.get("role") != "assistant":
                continue
            parts = msg.get("content", [])
            if isinstance(parts, str):
                text = parts.strip()
            elif isinstance(parts, list):
                text = "\n".join(
                    part.get("text", "").strip()
                    for part in parts
                    if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
                ).strip()
            else:
                text = ""
            if text:
                return text[:limit] + ("..." if len(text) > limit else "")
        return ""
    
    def _check_consecutive_failures(self, tool_name: str, args: dict) -> Tuple[bool, str, bool]:
        """
        Check if tool has failed too many times consecutively or called repeatedly with same args
        
        Returns:
            (should_stop, reason, is_critical)
            - should_stop: Whether to stop tool execution
            - reason: Reason for stopping
            - is_critical: Whether to abort entire conversation (True for 8+ failures)
        """
        args_hash = self._hash_args(args)
        
        # Count consecutive calls (both success and failure) for same tool + args
        # This catches infinite loops where tool succeeds but LLM keeps calling it
        same_args_calls = 0
        for name, ahash, success in reversed(self.tool_failure_history):
            if name == tool_name and ahash == args_hash:
                same_args_calls += 1
            else:
                break  # Different tool or args, stop counting
        
        # Stop at 5 consecutive calls with same args (whether success or failure)
        same_args_limit = self._tool_same_args_repeat_limit()
        if same_args_calls >= same_args_limit:
            return True, f"工具 '{tool_name}' 使用相同参数已被调用 {same_args_calls} 次，停止执行以防止无限循环。如果需要查看配置，结果已在之前的调用中返回。", False
        
        # Count consecutive failures for same tool + args
        same_args_failures = 0
        for name, ahash, success in reversed(self.tool_failure_history):
            if name == tool_name and ahash == args_hash:
                if not success:
                    same_args_failures += 1
                else:
                    break  # Stop at first success
            else:
                break  # Different tool or args, stop counting
        
        failure_limit = self._tool_failure_repeat_limit()
        if same_args_failures >= failure_limit:
            return True, f"工具 '{tool_name}' 使用相同参数连续失败 {same_args_failures} 次，停止执行以防止无限循环", False
        
        # Count consecutive failures for same tool (any args)
        same_tool_failures = 0
        for name, ahash, success in reversed(self.tool_failure_history):
            if name == tool_name:
                if not success:
                    same_tool_failures += 1
                else:
                    break  # Stop at first success
            else:
                break  # Different tool, stop counting
        
        # Hard stop at 8 failures - abort with critical message
        if same_tool_failures >= 8:
            return True, f"抱歉，我没能完成这个任务。可能是我理解有误或者当前方法不太合适。\n\n建议你：\n• 换个方式描述需求试试\n• 把任务拆分成更小的步骤\n• 或者换个思路来解决", True
        
        # Warning at 6 failures
        if same_tool_failures >= 6:
            return True, f"工具 '{tool_name}' 连续失败 {same_tool_failures} 次（使用不同参数），停止执行以防止无限循环", False
        
        return False, "", False
    
    def _record_tool_result(self, tool_name: str, args: dict, success: bool):
        """Record tool execution result for failure tracking"""
        if not hasattr(self, "tool_failure_history"):
            self.tool_failure_history = []
        args_hash = self._hash_args(args)
        self.tool_failure_history.append((tool_name, args_hash, success))
        # Keep only last 50 records to avoid memory bloat
        if len(self.tool_failure_history) > 50:
            self.tool_failure_history = self.tool_failure_history[-50:]

    def _record_tool_failure_detail(self, tool_name: str, args: dict, error: Any) -> None:
        if not hasattr(self, "tool_failure_details"):
            self.tool_failure_details = []
        args = args or {}
        target = self._failure_target(tool_name, args)
        failure_type = self._failure_type(error)
        record = {
            "tool": tool_name,
            "target": target,
            "failure_type": failure_type,
            "summary": str(error or "")[:300],
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.tool_failure_details.append(record)
        if len(self.tool_failure_details) > 80:
            self.tool_failure_details = self.tool_failure_details[-80:]

    @staticmethod
    def _failure_target(tool_name: str, args: dict) -> str:
        if tool_name == "textbook_chapter":
            return f"book={args.get('book_id', '')}/chapter={args.get('chapter_num', '')}/action={args.get('action', '')}"
        return str(args.get("path") or args.get("file_path") or args.get("url") or args.get("query") or "")

    @staticmethod
    def _failure_type(error: Any) -> str:
        text = str(error or "").lower()
        if "dangerous full-chapter overwrite" in text:
            return "short_full_overwrite_refused"
        if "failed to parse tool arguments" in text or "invalid json" in text or "unterminated string" in text:
            return "tool_args_parse_error"
        if "not found" in text:
            return "not_found"
        if "required" in text:
            return "missing_required_arg"
        return text[:80] or "unknown_failure"

    def _failure_fold_context(self) -> str:
        if not self.tool_failure_details:
            return ""
        grouped = {}
        for item in self.tool_failure_details:
            key = (item.get("tool", ""), item.get("target", ""), item.get("failure_type", ""))
            grouped.setdefault(key, []).append(item)
        lines = []
        for (tool, target, failure_type), items in grouped.items():
            if len(items) < 2:
                continue
            advice = self._failure_fold_advice(tool, failure_type)
            lines.append(
                f"- {tool} {failure_type} repeated {len(items)} times on {target}. {advice}"
            )
        if not lines:
            return ""
        return "\n".join(["Failure Fold:", *lines[-8:]])

    @staticmethod
    def _failure_fold_advice(tool: str, failure_type: str) -> str:
        if tool == "textbook_chapter" and failure_type == "short_full_overwrite_refused":
            return "Do not retry short write_chapter overwrite; use rewrite_chapter with a complete body or validate_structure first."
        if failure_type == "tool_args_parse_error":
            return "Use smaller tool arguments and split long content into shorter valid JSON calls."
        if failure_type == "missing_required_arg":
            return "Fix required arguments before retrying."
        return "Choose a different method instead of repeating the same failing path."

    @staticmethod
    def _tool_same_args_repeat_limit() -> int:
        try:
            from config import conf
            return max(1, int(conf().get("agent_tool_same_args_repeat_limit", 2) or 2))
        except Exception:
            return 2

    @staticmethod
    def _tool_failure_repeat_limit() -> int:
        try:
            from config import conf
            return max(1, int(conf().get("agent_tool_failure_repeat_limit", 2) or 2))
        except Exception:
            return 2

    def run_stream(self, user_message: str) -> str:
        """
        Execute streaming reasoning loop
        
        Args:
            user_message: User message
            
        Returns:
            Final response text
        """
        # Log user message with model info
        
        thinking_enabled = self._is_thinking_enabled()
        thinking_label = " | 💭 thinking" if thinking_enabled else ""
        logger.info(f"🤖 {self.model.model}{thinking_label} | 👤 {user_message}")        
        
        # Add user message (Claude format - use content blocks for consistency)
        self.messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": user_message
                }
            ]
        })

        self._maybe_record_task_boundary(user_message)
        self._record_short_term_user_goal(user_message)
        self._apply_tool_routing(user_message)

        self._maybe_save_context_checkpoint(user_message)

        # Trim context ONCE before the agent loop starts, not during tool steps.
        # This ensures tool_use/tool_result chains created during the current run
        # are never stripped mid-execution (which would cause LLM loops).
        self._trim_messages()

        # Validate after trimming: trimming may leave orphaned tool_use at the
        # boundary (e.g. the last kept turn ends with an assistant tool_use whose
        # tool_result was in a discarded turn).
        self._validate_and_fix_messages()
        self._emit_context_diagnostics("before_llm_loop")

        self._emit_event("agent_start")

        final_response = ""
        turn = 0

        try:
            while turn < self.max_turns:
                turn += 1
                logger.info(f"[Agent] 第 {turn} 轮")
                self._emit_event("turn_start", {"turn": turn})

                if self.cancel_event and self.cancel_event.is_set():
                    logger.info("[Agent] Cancelled by cancel_event before LLM call")
                    final_response = "[对话已被用户暂停]"
                    break

                self._llm_call_start_time = time.time()
                assistant_msg, tool_calls = self._call_llm_stream(retry_on_empty=True)
                final_response = assistant_msg

                # No tool calls, end loop
                if not tool_calls:
                    # 检查是否返回了空响应
                    if not assistant_msg:
                        logger.warning(f"[Agent] LLM returned empty response after retry (no content and no tool calls)")
                        logger.info(f"[Agent] This usually happens when LLM thinks the task is complete after tool execution")
                        
                        # 如果之前有工具调用，强制要求 LLM 生成文本回复
                        if turn > 1:
                            logger.info(f"[Agent] Requesting explicit response from LLM...")
                            
                            # Remember position so we can remove the injected prompt later
                            prompt_insert_idx = len(self.messages)
                            
                            # 添加一条消息，明确要求回复用户
                            self.messages.append({
                                "role": "user",
                                "content": [{
                                    "type": "text",
                                    "text": "请向用户说明刚才工具执行的结果或回答用户的问题。"
                                }]
                            })
                            
                            # 再调用一次 LLM
                            assistant_msg, tool_calls = self._call_llm_stream(retry_on_empty=False)
                            final_response = assistant_msg
                            
                            # Remove the injected prompt from history so it doesn't
                            # appear as a user message in persisted conversations.
                            # _call_llm_stream may have appended an assistant message
                            # after the prompt, so we locate and remove only the prompt.
                            if (prompt_insert_idx < len(self.messages)
                                    and self.messages[prompt_insert_idx].get("role") == "user"):
                                self.messages.pop(prompt_insert_idx)
                                logger.debug("[Agent] Removed injected explicit-response prompt from message history")
                            
                            # If LLM responded with tool_calls instead of text, fall through
                            # to the tool execution path below (don't break the loop).
                            if tool_calls:
                                logger.info(
                                    f"[Agent] LLM returned tool_calls in explicit-response retry, "
                                    f"continuing to execute tools instead of breaking"
                                )
                            elif not assistant_msg:
                                # Still empty (no text and no tool_calls): use fallback
                                logger.warning(f"[Agent] Still empty after explicit request")
                                final_response = (
                                    "抱歉，我暂时无法生成回复。请尝试换一种方式描述你的需求，或稍后再试。"
                                )
                                logger.info(f"Generated fallback response for empty LLM output")
                        else:
                            # 第一轮就空回复，直接 fallback
                            final_response = (
                                "抱歉，我暂时无法生成回复。请尝试换一种方式描述你的需求，或稍后再试。"
                            )
                            logger.info(f"Generated fallback response for empty LLM output")
                    else:
                        logger.info(f"💭 {assistant_msg[:150]}{'...' if len(assistant_msg) > 150 else ''}")
                    
                    # If the explicit-response retry produced tool_calls, skip the break
                    # and continue down to the tool execution branch in this same iteration.
                    if not tool_calls:
                        logger.debug(f"✅ 完成 (无工具调用)")
                        self._emit_event("turn_end", {
                            "turn": turn,
                            "has_tool_calls": False
                        })
                        break

                # Log tool calls with arguments (truncate long values like base64)
                tool_calls_str = []
                for tc in tool_calls:
                    args = tc.get('arguments') or {}
                    if isinstance(args, dict):
                        parts = []
                        for k, v in args.items():
                            v_str = str(v)
                            if len(v_str) > 200:
                                v_str = v_str[:200] + f"...({len(v_str)} chars)"
                            parts.append(f"{k}={v_str}")
                        args_str = ', '.join(parts)
                        if args_str:
                            tool_calls_str.append(f"{tc['name']}({args_str})")
                        else:
                            tool_calls_str.append(tc['name'])
                    else:
                        tool_calls_str.append(tc['name'])
                logger.info(f"🔧 {', '.join(tool_calls_str)}")

                # Execute tools
                tool_results = []
                tool_result_blocks = []

                try:
                    for tool_call in tool_calls:
                        if self.cancel_event and self.cancel_event.is_set():
                            logger.info("[Agent] Cancelled by cancel_event during tool execution")
                            break

                        result = self._execute_tool(tool_call)
                        tool_results.append(result)
                        
                        # Debug: Check if tool is being called repeatedly with same args
                        if turn > 2:
                            # Check last N tool calls for repeats
                            repeat_count = sum(
                                1 for name, ahash, _ in self.tool_failure_history[-10:]
                                if name == tool_call["name"] and ahash == self._hash_args(tool_call["arguments"])
                            )
                            if repeat_count >= 3:
                                logger.warning(
                                    f"⚠️  Tool '{tool_call['name']}' has been called {repeat_count} times "
                                    f"with same arguments. This may indicate a loop."
                                )
                        
                        # Check if this is a file to send
                        if result.get("status") == "success" and isinstance(result.get("result"), dict):
                            result_data = result.get("result")
                            if result_data.get("type") == "file_to_send":
                                self.files_to_send.append(result_data)
                                logger.info(f"📎 检测到待发送文件: {result_data.get('file_name', result_data.get('path'))}")
                                self._emit_event("file_to_send", result_data)
                        
                        # Check for critical error - abort entire conversation
                        if result.get("status") == "critical_error":
                            logger.error(f"💥 检测到严重错误，终止对话")
                            final_response = result.get('result', '任务执行失败')
                            return final_response
                        
                        # Log tool result in compact format
                        status_emoji = "✅" if result.get("status") == "success" else "❌"
                        result_data = result.get('result', '')
                        # Format result string with proper Chinese character support
                        if isinstance(result_data, (dict, list)):
                            result_str = json.dumps(result_data, ensure_ascii=False)
                        else:
                            result_str = str(result_data)
                        logger.info(f"  {status_emoji} {tool_call['name']} ({result.get('execution_time', 0):.2f}s): {result_str[:200]}{'...' if len(result_str) > 200 else ''}")

                        # Build tool result block (Claude format)
                        # Format content in a way that's easy for LLM to understand
                        is_error = result.get("status") == "error"

                        if is_error:
                            # For errors, provide clear error message
                            result_content = f"Error: {result.get('result', 'Unknown error')}"
                            error_hint = self._build_error_memory_context()
                            if error_hint:
                                result_content += "\n\n" + error_hint
                        elif isinstance(result.get('result'), dict):
                            # For dict results, use JSON format
                            result_content = json.dumps(result.get('result'), ensure_ascii=False)
                        elif isinstance(result.get('result'), str):
                            # For string results, use directly
                            result_content = result.get('result')
                        else:
                            # Fallback to full JSON
                            result_content = json.dumps(result, ensure_ascii=False)

                        compacted_content = compact_current_tool_result_content(
                            result_content,
                            tool_name=tool_call["name"],
                            tool_args=tool_call.get("arguments") or {},
                            status=result.get("status", ""),
                            max_chars=self._current_tool_result_context_limit(),
                            tool_budget_chars=self._tool_result_context_budgets(),
                        )
                        if compacted_content != result_content:
                            logger.info(
                                f"📎 Compacted tool result for '{tool_call['name']}': "
                                f"{len(result_content)} -> {len(compacted_content)} chars"
                            )
                            result_content = compacted_content

                        tool_result_block = {
                            "type": "tool_result",
                            "tool_use_id": tool_call["id"],
                            "content": result_content
                        }
                        
                        # Add is_error field for Claude API (helps model understand failures)
                        if is_error:
                            tool_result_block["is_error"] = True
                        
                        tool_result_blocks.append(tool_result_block)
                
                finally:
                    # CRITICAL: Always add tool_result to maintain message history integrity
                    # Even if tool execution fails, we must add error results to match tool_use
                    if tool_result_blocks:
                        # Add tool results to message history as user message (Claude format)
                        self.messages.append({
                            "role": "user",
                            "content": tool_result_blocks
                        })
                        self._compress_current_turn_tool_results_if_needed()
                        
                        # Detect potential infinite loop: same tool called multiple times with success
                        # If detected, add a hint to LLM to stop calling tools and provide response
                        if turn >= 3 and len(tool_calls) > 0:
                            tool_name = tool_calls[0]["name"]
                            args_hash = self._hash_args(tool_calls[0]["arguments"])
                            
                            # Count recent successful calls with same tool+args
                            recent_success_count = 0
                            for name, ahash, success in reversed(self.tool_failure_history[-10:]):
                                if name == tool_name and ahash == args_hash and success:
                                    recent_success_count += 1
                            
                            # If tool was called successfully 3+ times with same args, add hint to stop loop
                            if recent_success_count >= 3:
                                logger.warning(
                                    f"⚠️  Detected potential loop: '{tool_name}' called {recent_success_count} times "
                                    f"with same args. Adding hint to LLM to provide final response."
                                )
                                # Add a gentle hint message to guide LLM to respond
                                self.messages.append({
                                    "role": "user",
                                    "content": [{
                                        "type": "text",
                                        "text": "工具已成功执行并返回结果。请基于这些信息向用户做出回复，不要重复调用相同的工具。"
                                    }]
                                })
                        if self._should_close_tool_phase_after_results(tool_results):
                            self._close_tool_phase_for_answer()
                    elif tool_calls:
                        # If we have tool_calls but no tool_result_blocks (unexpected error),
                        # create error results for all tool calls to maintain message integrity
                        logger.warning("⚠️ Tool execution interrupted, adding error results to maintain message history")
                        emergency_blocks = []
                        for tool_call in tool_calls:
                            emergency_blocks.append({
                                "type": "tool_result",
                                "tool_use_id": tool_call["id"],
                                "content": "Error: Tool execution was interrupted",
                                "is_error": True
                            })
                        self.messages.append({
                            "role": "user",
                            "content": emergency_blocks
                        })

                self._emit_event("turn_end", {
                    "turn": turn,
                    "has_tool_calls": True,
                    "tool_count": len(tool_calls)
                })
                self._maybe_persist_near_max_turn_handoff(turn, final_response, tool_calls)
                if self._should_stop_after_tool_results(tool_results):
                    final_response = self._tool_budget_exhausted_final_response(tool_results)
                    self._emit_visible_assistant_message(
                        final_response,
                        stop_reason="tool_budget_exhausted",
                    )
                    self._emit_event("tool_budget_exhausted", {
                        "turn": turn,
                        "max_calls": getattr(getattr(self, "tool_budget", None), "max_calls", 0),
                        "total_calls": getattr(getattr(self, "tool_budget", None), "total_calls", 0),
                    })
                    break

                # Emergency-only mid-run trim. Normal compression happens once
                # before a run starts; compacting after every tool round can
                # blur the active task and revive old goals.
                if turn >= 3 and self.agent:
                    try:
                        max_allowed, reserve = self._effective_context_budget()
                        system_tokens = self.agent._estimate_message_tokens({"role": "system", "content": self.system_prompt}) if self.system_prompt else 0
                        msg_tokens = sum(self.agent._estimate_message_tokens(m) for m in self.messages)
                        total_estimated = system_tokens + msg_tokens
                        trim_threshold = max_allowed * self._midrun_trim_ratio()
                        if total_estimated > trim_threshold:
                            logger.info(f"📦 Mid-run context trim: ~{total_estimated} tokens approaching {max_allowed} limit")
                            self._trim_messages()
                            self._validate_and_fix_messages()
                            self._emit_context_diagnostics("midrun_trim")
                            new_total = system_tokens + sum(self.agent._estimate_message_tokens(m) for m in self.messages)
                            logger.info(f"📦 After mid-run trim: ~{new_total} tokens")
                    except Exception as e:
                        logger.debug(f"Mid-run context check skipped: {e}")

            if turn >= self.max_turns:
                logger.warning(f"[Agent] Reached max decision steps: {self.max_turns}")
                self._emit_event("max_steps_reached", {
                    "turn": turn,
                    "max_turns": self.max_turns,
                })
                self._maybe_persist_near_max_turn_handoff(turn, final_response, [], force=True)

                # Do not call the LLM again here. In practice the final "summary"
                # request can itself hang on providers that already returned a partial
                # tool call, leaving the frontend waiting after the step cap. Finish
                # deterministically so the run always closes and the user can resume.
                recent_text = self._latest_assistant_text_excerpt()
                final_response = (
                    f"已执行 {turn} 轮，达到本次运行的最大步骤上限 {self.max_turns}。\n\n"
                    "本次运行已自动停止，避免继续循环或长时间占用后台。"
                    "如果任务尚未完成，请基于已生成文件继续下达更小范围的指令。"
                )
                if recent_text:
                    final_response += f"\n\n最近进展摘录：\n{recent_text}"

        except TimeoutError as e:
            logger.warning(f"[Agent] LLM stream idle timeout: {e}")
            final_response = (
                "模型流式响应空闲超时，已自动结束本轮，避免后台一直等待尾包。"
                "如果任务尚未完成，请继续发送更小范围的指令。"
            )
            self._emit_event("error", {
                "error": str(e),
                "recoverable": True,
                "reason": "llm_stream_idle_timeout",
            })

        except Exception as e:
            logger.error(f"❌ Agent执行错误: {e}")
            self._emit_event("error", {"error": str(e)})
            raise

        finally:
            final_response = final_response.strip() if final_response else final_response
            self._compact_tool_results_after_final_response()
            self._record_short_term_final_response(final_response)
            self._emit_tool_diagnostics()
            logger.info(f"[Agent] 🏁 完成 ({turn}轮)")
            self._emit_event("agent_end", {"final_response": final_response})

        return final_response

    def _maybe_save_context_checkpoint(self, user_message: str = ""):
        """Save a Harness checkpoint before compression when context pressure is high."""
        try:
            from config import conf

            if not conf().get("agent_context_anxiety_guard_enabled", True):
                return
            threshold = float(conf().get("agent_context_anxiety_threshold", 0.70) or 0.70)
            ContextAnxietyGuard(threshold=threshold).maybe_checkpoint(self, user_message=user_message)
        except Exception as exc:
            logger.debug(f"[Harness] Context anxiety guard skipped: {exc}")

    def _get_short_term_memory(self):
        if self.short_term_memory is not None:
            return self.short_term_memory
        try:
            from config import conf
            if not conf().get("short_term_memory_enabled", True):
                return None
            from common.app_paths import system_dir
            from agent.memory import ShortTermMemoryPool

            session_id = (
                getattr(self.model, "session_id", "")
                or getattr(self.agent, "_current_session_id", "")
                or "default"
            )
            self.short_term_memory = ShortTermMemoryPool(
                system_dir(),
                session_id=session_id,
                max_events=int(conf().get("short_term_memory_max_events", 200) or 200),
                keep_events=int(conf().get("short_term_memory_keep_events", 50) or 50),
                retention_days=int(conf().get("short_term_memory_retention_days", 14) or 14),
                max_files=int(conf().get("short_term_memory_max_files", 30) or 30),
            )
            return self.short_term_memory
        except Exception as exc:
            logger.debug(f"[ShortTermMemory] unavailable: {exc}")
            return None

    def _record_short_term_user_goal(self, user_message: str) -> None:
        pool = self._get_short_term_memory()
        if not pool:
            return
        try:
            pool.record_user_goal(
                user_message,
                channel_type=getattr(self.model, "channel_type", "") or "",
            )
        except Exception as exc:
            logger.debug(f"[ShortTermMemory] user goal skipped: {exc}")

    def _maybe_record_task_boundary(self, user_message: str) -> None:
        pool = self._get_short_term_memory()
        if not pool:
            return
        try:
            boundary = pool.maybe_record_task_boundary(user_message)
            if boundary:
                logger.info(f"[TaskBoundary] {boundary.get('reason', '')}")
                self._emit_event("task_boundary", boundary)
        except Exception as exc:
            logger.debug(f"[TaskBoundary] detection skipped: {exc}")

    def _record_short_term_tool_start(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        pool = self._get_short_term_memory()
        if not pool:
            return
        try:
            pool.record_tool_start(tool_name, arguments or {})
        except Exception as exc:
            logger.debug(f"[ShortTermMemory] tool start skipped: {exc}")

    def _record_short_term_tool_end(self, tool_name: str, arguments: Dict[str, Any], status: str, result: Any) -> None:
        pool = self._get_short_term_memory()
        if not pool:
            return
        try:
            pool.record_tool_end(tool_name, arguments or {}, status or "", result)
        except Exception as exc:
            logger.debug(f"[ShortTermMemory] tool end skipped: {exc}")

    def _record_short_term_final_response(self, response: str) -> None:
        pool = self._get_short_term_memory()
        if not pool:
            return
        try:
            pool.record_final_response(response or "")
        except Exception as exc:
            logger.debug(f"[ShortTermMemory] final response skipped: {exc}")

    def _inject_short_term_memory_board(self) -> None:
        pool = self._get_short_term_memory()
        if not pool:
            return
        try:
            board = pool.compact_prompt()
            if not board:
                return
            marker = "[System: Short-term working memory]"
            for msg in self.messages:
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if marker in text:
                            block["text"] = self._strip_short_term_memory_board(text)
            for msg in reversed(self.messages):
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        original = (block.get("text") or "").strip()
                        block["text"] = f"{board}\n\n---\n\n{original}"
                        return
        except Exception as exc:
            logger.debug(f"[ShortTermMemory] inject skipped: {exc}")

    @staticmethod
    def _strip_short_term_memory_board(text: str) -> str:
        marker = "[System: Short-term working memory]"
        if marker not in text:
            return text
        parts = text.split("\n\n---\n\n", 1)
        if len(parts) == 2 and marker in parts[0]:
            return parts[1].strip()
        return text

    def _current_tool_result_context_limit(self) -> int:
        try:
            from config import conf
            value = int(conf().get("agent_current_tool_result_context_chars", 16000) or 16000)
            return max(2000, min(50000, value))
        except Exception:
            return 16000

    def _tool_result_context_budgets(self) -> dict:
        try:
            from config import conf
            budgets = conf().get("agent_tool_result_context_budgets", {}) or {}
            if not isinstance(budgets, dict):
                return {}
            cleaned = {}
            for name, value in budgets.items():
                try:
                    cleaned[str(name)] = max(400, int(value))
                except Exception:
                    continue
            return cleaned
        except Exception:
            return {}

    def _midrun_tool_result_chars_limit(self) -> int:
        try:
            from config import conf
            value = int(conf().get("agent_midrun_tool_result_chars", 60000) or 60000)
            return max(1000, min(500000, value))
        except Exception:
            return 60000

    def _historical_tool_result_context_limit(self) -> int:
        try:
            from config import conf
            value = int(conf().get("agent_historical_tool_result_context_chars", 1200) or 1200)
            return max(400, min(10000, value))
        except Exception:
            return 1200

    def _total_tool_result_chars(self) -> int:
        total = 0
        for msg in self.messages:
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    value = block.get("content", "")
                    if isinstance(value, str):
                        total += len(value)
        return total

    def _compress_current_turn_tool_results_if_needed(self) -> bool:
        limit = self._midrun_tool_result_chars_limit()
        total = self._total_tool_result_chars()
        if total <= limit:
            return False

        blocks = []
        for msg in self.messages:
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    blocks.append(block)
        if len(blocks) <= 1:
            return False

        changed = False
        # Keep the latest result intact for local continuity; compact older
        # results in the active run once aggregate tool noise exceeds budget.
        for block in blocks[:-1]:
            result_str = block.get("content", "")
            if not isinstance(result_str, str) or len(result_str) <= 300:
                continue
            tool_name, tool_args = self._find_tool_info_for_result(block.get("tool_use_id", ""))
            summary = compact_historical_tool_result_content(
                result_str,
                tool_name=tool_name,
                tool_args=tool_args,
                status="error" if block.get("is_error") else "success",
                max_chars=self._historical_tool_result_context_limit(),
            )
            if len(summary) >= len(result_str):
                summary = (
                    f"[midrun tool result compacted: {tool_name or 'unknown'}, "
                    f"original_chars={len(result_str)}]\n"
                    f"{result_str[:240]}"
                )
            if len(summary) < len(result_str):
                block["content"] = summary
                changed = True
            if self._total_tool_result_chars() <= limit:
                break

        if changed:
            logger.info(
                f"📦 Mid-run tool-result guard compacted history: "
                f"{total} -> {self._total_tool_result_chars()} chars"
            )
            self._record_context_compression("midrun_tool_results", saved_chars=total - self._total_tool_result_chars())
        return changed

    def _compact_tool_results_after_final_response(self) -> bool:
        """After answering the user, keep only durable summaries of tool output."""
        changed = False
        saved_chars = 0
        for msg in self.messages:
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                result_str = block.get("content", "")
                if not isinstance(result_str, str) or not result_str:
                    continue
                if result_str.startswith("[historical "):
                    continue
                tool_name, tool_args = self._find_tool_info_for_result(block.get("tool_use_id", ""))
                summary = compact_historical_tool_result_content(
                    result_str,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    status="error" if block.get("is_error") else "success",
                    max_chars=self._historical_tool_result_context_limit(),
                )
                if len(summary) < len(result_str) or not result_str.startswith("[historical "):
                    block["content"] = summary
                    saved_chars += max(0, len(result_str) - len(summary))
                    changed = True
        if changed:
            self._record_context_compression("historical_tool_results", saved_chars=saved_chars)
            logger.info(f"📦 Historical tool results summarized after final response; saved ~{saved_chars} chars")
        return changed

    def _record_context_compression(self, kind: str, saved_chars: int = 0) -> None:
        self.context_compression_history.append({
            "kind": kind,
            "saved_chars": int(saved_chars or 0),
            "time": time.time(),
        })
        if len(self.context_compression_history) > 20:
            self.context_compression_history = self.context_compression_history[-20:]

    def _compression_debounce_limit(self) -> int:
        try:
            from config import conf
            return max(1, int(conf().get("agent_context_compression_debounce_limit", 3) or 3))
        except Exception:
            return 3

    def _recent_compression_count(self) -> int:
        cutoff = time.time() - 3600
        return len([
            item for item in self.context_compression_history
            if float(item.get("time", 0) or 0) >= cutoff
        ])

    def _compression_debounce_active(self) -> bool:
        return self._recent_compression_count() >= self._compression_debounce_limit()

    def _apply_tool_routing(self, user_message: str) -> None:
        try:
            from config import conf
            if not conf().get("agent_tool_routing_enabled", True):
                return
            from agent.tools.router import filter_tool_mapping, route_tools

            route = route_tools(user_message, self.tools, enabled=True)
            self.tool_route = route
            self._tool_route_user_message = user_message
            self.tool_phase_state = self._initial_tool_phase_state(user_message, route)
            self.tool_phase_stop_reason = ""
            self.tools = filter_tool_mapping(self.tools, route.allowed_tools)
            logger.info(
                f"[ToolRouter] task_type={route.task_type}, "
                f"visible={route.allowed_tools}, hidden={route.omitted_tools}"
            )
        except Exception as exc:
            logger.debug(f"[ToolRouter] routing skipped: {exc}")

    @staticmethod
    def _initial_tool_phase_state(user_message: str, route) -> dict:
        text = (user_message or "").lower()
        reason = str(getattr(route, "reason", "") or "").lower()
        required = set(getattr(route, "required_tools", []) or [])
        is_chapter_review = (
            getattr(route, "task_type", "") == "textbook"
            and (
                {"textbook_chapter", "textbook_outline"} <= required
                or "chapter review" in reason
                or (any(word in text for word in ("审查", "检查", "评估", "review", "check"))
                    and any(word in text for word in ("第", "章", "chapter")))
            )
        )
        if is_chapter_review:
            return {
                "intent": "chapter_review",
                "chapter_read": False,
                "outline_read": False,
                "review_checklist_read": False,
            }
        return {}

    def _inject_tool_routing_board(self) -> None:
        route = self.tool_route
        if not route or not route.prompt:
            return
        marker = "[System: Tool routing policy]"
        try:
            for msg in self.messages:
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if marker in text:
                            block["text"] = self._strip_tool_routing_board(text)
            for msg in reversed(self.messages):
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        original = (block.get("text") or "").strip()
                        block["text"] = f"{route.prompt}\n\n---\n\n{original}"
                        return
        except Exception as exc:
            logger.debug(f"[ToolRouter] prompt injection skipped: {exc}")

    @staticmethod
    def _strip_tool_routing_board(text: str) -> str:
        marker = "[System: Tool routing policy]"
        if marker not in text:
            return text
        parts = text.split("\n\n---\n\n", 1)
        if len(parts) == 2 and marker in parts[0]:
            return parts[1].strip()
        return text

    def _call_llm_stream(self, retry_on_empty=True, retry_count=0, max_retries=3,
                         _overflow_retry: bool = False) -> Tuple[str, List[Dict]]:
        """
        Call LLM with streaming and automatic retry on errors
        
        Args:
            retry_on_empty: Whether to retry once if empty response is received
            retry_count: Current retry attempt (internal use)
            max_retries: Maximum number of retries for API errors
            _overflow_retry: Internal flag indicating this is a retry after context overflow
        
        Returns:
            (response_text, tool_calls)
        """
        # Validate and fix message history (e.g. orphaned tool_result blocks).
        # Context trimming is done once in run_stream() before the loop starts,
        # NOT here — trimming mid-execution would strip the current run's
        # tool_use/tool_result chains and cause LLM loops.
        self._validate_and_fix_messages()

        # Pre-send token check: if context exceeds model window, trim before sending
        if not _overflow_retry and self.agent:
            try:
                max_allowed, reserve = self._effective_context_budget()

                system_tokens = self.agent._estimate_message_tokens({"role": "system", "content": self.system_prompt}) if self.system_prompt else 0
                msg_tokens = sum(self.agent._estimate_message_tokens(m) for m in self.messages)
                total_estimated = system_tokens + msg_tokens

                if total_estimated > max_allowed:
                    logger.warning(f"📦 Pre-send context check: ~{total_estimated} tokens > {max_allowed} limit, trimming before send")
                    self._trim_messages()
                    self._validate_and_fix_messages()
                    new_total = system_tokens + sum(self.agent._estimate_message_tokens(m) for m in self.messages)
                    logger.info(f"📦 After trim: ~{new_total} tokens (was ~{total_estimated})")
            except Exception as e:
                logger.debug(f"Pre-send token check skipped: {e}")

        try:
            from agent.tools import ToolManager
            added, removed = ToolManager().sync_mcp_into_agent(self)
            if self.tool_route:
                from config import conf
                from agent.tools.router import filter_tool_mapping, route_tools
                route = route_tools(
                    getattr(self, "_tool_route_user_message", ""),
                    self.tools,
                    enabled=conf().get("agent_tool_routing_enabled", True),
                )
                self.tool_route = route
                self.tools = filter_tool_mapping(self.tools, route.allowed_tools)
                if added or removed:
                    logger.info(
                        f"[ToolRouter] refreshed after MCP sync: "
                        f"visible={route.allowed_tools}, hidden={route.omitted_tools}"
                    )
        except Exception as e:
            logger.debug(f"[Agent] MCP sync skipped: {e}")

        # Prepare messages
        messages = self._prepare_messages()
        turns = self._identify_complete_turns()
        logger.info(f"Sending {len(messages)} messages ({len(turns)} turns) to LLM")

        # Pull in any MCP tools that finished loading since this turn started.
        # Cheap dict reconciliation (microseconds) — lets the agent pick up
        # newly available MCP tools mid-conversation without a session restart.
        try:
            from agent.tools import ToolManager
            ToolManager().sync_mcp_into_agent(self)
            if self.tool_route:
                from agent.tools.router import filter_tool_mapping
                self.tools = filter_tool_mapping(self.tools, self.tool_route.allowed_tools)
        except Exception as e:
            logger.debug(f"[Agent] MCP sync skipped: {e}")

        # Prepare tool definitions (OpenAI/Claude format)
        tools_schema = None
        if self.tools:
            tools_schema = []
            for tool in self.tools.values():
                tools_schema.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.params  # Claude uses input_schema
                })

        # Create request
        request = LLMRequest(
            messages=messages,
            temperature=0,
            stream=True,
            tools=tools_schema,
            system=self.system_prompt  # Pass system prompt separately for Claude API
        )

        self._emit_event("message_start", {"role": "assistant"})

        _LLM_THINKING_HEARTBEAT_INTERVAL = 15
        _last_heartbeat_time = time.time()
        _last_log_heartbeat_time = time.time()
        _first_chunk_received = False
        _stream_start_time = time.time()
        _content_len_at_last_log = 0
        _tool_call_stall_timeout = self._tool_call_stall_timeout_seconds()
        _partial_tool_call_timeout = self._partial_tool_call_timeout_seconds()
        _last_meaningful_delta_time = time.time()
        _last_tool_signature = ""

        full_content = ""
        full_reasoning = ""
        tool_calls_buffer = {}  # {index: {id, name, arguments}}
        gemini_raw_parts = None  # Preserve Gemini thoughtSignature for round-trip
        stop_reason = None  # Track why the stream stopped

        try:
            stream = self.model.call_stream(request)
            stream = self._iter_stream_with_idle_timeout(stream, self._stream_idle_timeout_seconds())

            for chunk in stream:
                if self.cancel_event and self.cancel_event.is_set():
                    logger.info("[Agent] Cancelled by cancel_event during LLM stream")
                    break

                now = time.time()
                if tool_calls_buffer:
                    stable_for = now - _last_meaningful_delta_time
                    if (
                        _tool_call_stall_timeout
                        and stable_for >= _tool_call_stall_timeout
                        and self._tool_calls_parseable(tool_calls_buffer)
                    ):
                        logger.warning(
                            "[Agent] LLM tool-call stream stalled after "
                            f"{int(stable_for)}s; "
                            "closing stream with complete parseable tool call"
                        )
                        stop_reason = stop_reason or "tool_call_stall_timeout"
                        break
                    if (
                        _partial_tool_call_timeout
                        and stable_for >= _partial_tool_call_timeout
                        and not self._tool_calls_parseable(tool_calls_buffer)
                    ):
                        logger.warning(
                            "[Agent] LLM partial tool-call stream stalled after "
                            f"{int(stable_for)}s; closing stream so the next turn can recover"
                        )
                        stop_reason = stop_reason or "partial_tool_call_stall_timeout"
                        break

                if not _first_chunk_received and now - _last_heartbeat_time >= _LLM_THINKING_HEARTBEAT_INTERVAL:
                    _last_heartbeat_time = now
                    elapsed = int(now - getattr(self, '_llm_call_start_time', now))
                    self._emit_event("llm_thinking", {"elapsed_seconds": elapsed})

                if _first_chunk_received and now - _last_log_heartbeat_time >= 30:
                    _last_log_heartbeat_time = now
                    elapsed = int(now - _stream_start_time)
                    content_len = len(full_content)
                    tool_count = len(tool_calls_buffer)
                    logger.info(f"[Agent] LLM streaming... {elapsed}s elapsed, content={content_len} chars, tool_calls={tool_count}")

                if isinstance(chunk, dict) and chunk.get("choices"):
                    _first_chunk_received = True

                # Check for errors
                if isinstance(chunk, dict) and chunk.get("error"):
                    # Extract error message from nested structure
                    error_data = chunk.get("error", {})
                    if isinstance(error_data, dict):
                        error_msg = error_data.get("message", chunk.get("message", "Unknown error"))
                        error_code = error_data.get("code", "")
                        error_type = error_data.get("type", "")
                    else:
                        error_msg = chunk.get("message", str(error_data))
                        error_code = ""
                        error_type = ""
                    
                    status_code = chunk.get("status_code", "N/A")
                    
                    # Log error with all available information
                    logger.error(f"🔴 Stream API Error:")
                    logger.error(f"   Message: {error_msg}")
                    logger.error(f"   Status Code: {status_code}")
                    logger.error(f"   Error Code: {error_code}")
                    logger.error(f"   Error Type: {error_type}")
                    logger.error(f"   Full chunk: {chunk}")
                    
                    # Check if this is a context overflow error (keyword-based, works for all models)
                    # Don't rely on specific status codes as different providers use different codes
                    error_msg_lower = error_msg.lower()
                    is_overflow = any(keyword in error_msg_lower for keyword in [
                        'context length exceeded', 'maximum context length', 'prompt is too long',
                        'context overflow', 'context window', 'too large', 'exceeds model context',
                        'request_too_large', 'request exceeds the maximum size', 'tokens exceed'
                    ])
                    
                    if is_overflow:
                        # Mark as context overflow for special handling
                        raise Exception(f"[CONTEXT_OVERFLOW] {error_msg} (Status: {status_code})")
                    else:
                        # Raise exception with full error message for retry logic
                        raise Exception(f"{error_msg} (Status: {status_code}, Code: {error_code}, Type: {error_type})")

                # Parse chunk
                if isinstance(chunk, dict) and chunk.get("choices"):
                    choice = chunk["choices"][0]
                    delta = choice.get("delta", {})
                    
                    # Capture finish_reason if present
                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        stop_reason = finish_reason

                    reasoning_delta = delta.get("reasoning_content") or ""
                    if reasoning_delta:
                        _last_meaningful_delta_time = now
                        full_reasoning += reasoning_delta
                        if self._is_thinking_enabled():
                            self._emit_event("reasoning_update", {"delta": reasoning_delta})

                    # Handle text content
                    content_delta = delta.get("content") or ""
                    if content_delta:
                        _last_meaningful_delta_time = now
                        # Filter out <think> tags from content
                        filtered_delta = self._filter_think_tags(content_delta)
                        full_content += filtered_delta
                        if filtered_delta:  # Only emit if there's content after filtering
                            self._emit_event("message_update", {"delta": filtered_delta})

                    # Handle tool calls
                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc_delta in delta["tool_calls"]:
                            index = tc_delta.get("index", 0)

                            if index not in tool_calls_buffer:
                                tool_calls_buffer[index] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": ""
                                }

                            if tc_delta.get("id"):
                                tool_calls_buffer[index]["id"] = tc_delta["id"]

                            if "function" in tc_delta:
                                func = tc_delta["function"]
                                if func.get("name"):
                                    tool_calls_buffer[index]["name"] = func["name"]
                                if func.get("arguments"):
                                    tool_calls_buffer[index]["arguments"] += func["arguments"]

                        tool_signature = json.dumps(tool_calls_buffer, sort_keys=True, ensure_ascii=False)
                        if tool_signature != _last_tool_signature:
                            _last_tool_signature = tool_signature
                            _last_meaningful_delta_time = now

                    # Preserve _gemini_raw_parts for Gemini thoughtSignature round-trip
                    # (direct Gemini: list of parts; LinkAI proxy: base64 string of JSON parts)
                    if "_gemini_raw_parts" in delta:
                        gemini_raw_parts = delta["_gemini_raw_parts"]
                    elif isinstance(choice, dict) and choice.get("_gemini_raw_parts"):
                        gemini_raw_parts = choice["_gemini_raw_parts"]

        except Exception as e:
            error_str = str(e)
            error_str_lower = error_str.lower()
            
            # Check if error is context overflow (non-retryable, needs session reset)
            # Method 1: Check for special marker (set in stream error handling above)
            is_context_overflow = '[context_overflow]' in error_str_lower
            
            # Method 2: Fallback to keyword matching for non-stream errors
            if not is_context_overflow:
                is_context_overflow = any(keyword in error_str_lower for keyword in [
                    'context length exceeded', 'maximum context length', 'prompt is too long',
                    'context overflow', 'context window', 'too large', 'exceeds model context',
                    'request_too_large', 'request exceeds the maximum size'
                ])
            
            # Check if error is message format error (incomplete tool_use/tool_result pairs)
            # This happens when previous conversation had tool failures or context trimming
            # broke tool_use/tool_result pairs.
            # Note: MiniMax returns error 2013 "tool result's tool id(...) not found" for
            # tool_call_id mismatches — the keywords below are intentionally broad to catch
            # both standard (Claude/OpenAI) and provider-specific (MiniMax) variants.
            is_message_format_error = any(keyword in error_str_lower for keyword in [
                'tool_use', 'tool_result', 'tool result', 'without', 'immediately after',
                'corresponding', 'must have', 'each',
                'tool_call_id', 'tool id', 'is not found', 'not found', 'tool_calls',
                'must be a response to a preceeding message',
                '2013',  # MiniMax error code for tool_call_id mismatch
            ]) and ('400' in error_str_lower or 'status: 400' in error_str_lower
                     or 'invalid_request' in error_str_lower
                     or 'invalidparameter' in error_str_lower)
            
            if is_context_overflow or is_message_format_error:
                error_type = "context overflow" if is_context_overflow else "message format error"
                logger.error(f"💥 {error_type} detected: {e}")

                # Flush memory before trimming to preserve context that will be lost
                if is_context_overflow and self.agent.memory_manager:
                    user_id = getattr(self.agent, '_current_user_id', None)
                    self.agent.memory_manager.flush_memory(
                        messages=self.messages, user_id=user_id,
                        reason="overflow", max_messages=0
                    )

                # Strategy: try aggressive trimming first, only clear as last resort
                if is_context_overflow and not _overflow_retry:
                    trimmed = self._aggressive_trim_for_overflow()
                    if trimmed:
                        logger.warning("🔄 Aggressively trimmed context, retrying...")
                        return self._call_llm_stream(
                            retry_on_empty=retry_on_empty,
                            retry_count=retry_count,
                            max_retries=max_retries,
                            _overflow_retry=True
                        )

                # Aggressive trim didn't help or this is a message format error
                # -> clear everything and also purge DB to prevent reload of dirty data
                logger.warning("🔄 Clearing conversation history to recover")
                self.messages.clear()
                self._clear_session_db()
                if is_context_overflow:
                    raise Exception(
                        "抱歉，对话历史过长导致上下文溢出。我已清空历史记录，请重新描述你的需求。"
                    )
                else:
                    raise Exception(
                        "抱歉，之前的对话出现了问题。我已清空历史记录，请重新发送你的消息。"
                    )
            
            # Check if error is rate limit (429)
            is_rate_limit = '429' in error_str_lower or 'rate limit' in error_str_lower
            
            # Check if error is retryable (timeout, connection, server busy, etc.)
            is_retryable = any(keyword in error_str_lower for keyword in [
                'timeout', 'timed out', 'connection', 'network', 
                'rate limit', 'overloaded', 'unavailable', 'busy', 'retry',
                '429', '500', '502', '503', '504', '512'
            ])
            
            if is_retryable and retry_count < max_retries:
                # Rate limit needs longer wait time
                if is_rate_limit:
                    wait_time = 30 + (retry_count * 15)  # 30s, 45s, 60s for rate limit
                else:
                    wait_time = (retry_count + 1) * 2  # 2s, 4s, 6s for other errors
                
                logger.warning(f"⚠️ LLM API error (attempt {retry_count + 1}/{max_retries}): {e}")
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
                return self._call_llm_stream(
                    retry_on_empty=retry_on_empty, 
                    retry_count=retry_count + 1,
                    max_retries=max_retries
                )
            else:
                if retry_count >= max_retries:
                    logger.error(f"❌ LLM API error after {max_retries} retries: {e}", exc_info=True)
                else:
                    logger.error(f"❌ LLM call error (non-retryable): {e}", exc_info=True)
                raise

        # Parse tool calls
        tool_calls = []
        for idx in sorted(tool_calls_buffer.keys()):
            tc = tool_calls_buffer[idx]

            # Ensure tool call has a valid ID (some providers return empty/None IDs)
            tool_id = tc.get("id") or ""
            if not tool_id:
                import uuid
                tool_id = f"call_{uuid.uuid4().hex[:24]}"

            try:
                # Safely get arguments, handle None case
                args_str = tc.get("arguments") or ""
                arguments = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError as e:
                # Handle None or invalid arguments safely
                args_str = tc.get('arguments') or ""
                args_preview = args_str[:200] if len(args_str) > 200 else args_str
                logger.error(f"Failed to parse tool arguments for {tc['name']}")
                logger.error(f"Arguments length: {len(args_str)} chars")
                logger.error(f"Arguments preview: {args_preview}...")
                logger.error(f"JSON decode error: {e}")

                # Return a clear error message to the LLM instead of empty dict
                # This helps the LLM understand what went wrong
                tool_calls.append({
                    "id": tool_id,
                    "name": tc["name"],
                    "arguments": {},
                    "_parse_error": f"Invalid JSON in tool arguments: {args_preview}... Error: {str(e)}. Tip: For large content, consider splitting into smaller chunks or using a different approach."
                })
                continue

            tool_calls.append({
                "id": tool_id,
                "name": tc["name"],
                "arguments": arguments
            })

        # Check for empty response and retry once if enabled
        if retry_on_empty and not full_content and not tool_calls:
            logger.warning(f"⚠️  LLM returned empty response (stop_reason: {stop_reason}), retrying once...")
            self._emit_event("message_end", {
                "content": "",
                "tool_calls": [],
                "empty_retry": True,
                "stop_reason": stop_reason
            })
            # Retry without retry flag to avoid infinite loop
            return self._call_llm_stream(
                retry_on_empty=False, 
                retry_count=retry_count,
                max_retries=max_retries
            )

        # Filter full_content one more time (in case tags were split across chunks)
        full_content = self._filter_think_tags(full_content)
        
        # Add assistant message to history (Claude format uses content blocks)
        assistant_msg = {"role": "assistant", "content": []}

        if full_reasoning:
            stored_reasoning = _truncate_reasoning_for_storage(full_reasoning)
            if len(stored_reasoning) < len(full_reasoning):
                logger.info(
                    f"[reasoning] truncated for storage: "
                    f"{len(full_reasoning)} -> {len(stored_reasoning)} chars"
                )
            assistant_msg["content"].append({
                "type": "thinking",
                "thinking": stored_reasoning
            })

        if full_content:
            assistant_msg["content"].append({
                "type": "text",
                "text": full_content
            })

        # Add tool_use blocks if present
        if tool_calls:
            for tc in tool_calls:
                assistant_msg["content"].append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": tc.get("arguments", {})
                })
        
        if gemini_raw_parts:
            assistant_msg["_gemini_raw_parts"] = gemini_raw_parts

        # Only append if content is not empty
        if assistant_msg["content"]:
            self.messages.append(assistant_msg)

        self._emit_event("message_end", {
            "content": full_content,
            "tool_calls": tool_calls,
            "stop_reason": stop_reason
        })

        return full_content, tool_calls

    def _execute_tool(self, tool_call: Dict) -> Dict[str, Any]:
        """
        Execute tool
        
        Args:
            tool_call: {"id": str, "name": str, "arguments": dict}
            
        Returns:
            Tool execution result
        """
        tool_name = tool_call["name"]
        tool_id = tool_call["id"]
        arguments = tool_call["arguments"]

        # Check if there was a JSON parse error
        if "_parse_error" in tool_call:
            parse_error = tool_call["_parse_error"]
            logger.error(f"Skipping tool execution due to parse error: {parse_error}")
            recovery_hint = self._tool_parse_recovery_hint(tool_name)
            result = {
                "status": "error",
                "result": (
                    f"Failed to parse tool arguments. {parse_error}. "
                    "Please ensure your tool call uses valid JSON format with all required parameters."
                    f"{recovery_hint}"
                ),
                "execution_time": 0
            }
            self._record_tool_result(tool_name, arguments, False)
            self._record_tool_failure_detail(tool_name, arguments, result["result"])
            self._capture_tool_error_memory(
                tool_name,
                result["result"],
                arguments,
                "parse_error",
            )
            self._record_tool_metric_event(tool_name, arguments, result)
            return result

        duplicate_read_result = self._preflight_duplicate_chapter_read_check(tool_name, arguments)
        if duplicate_read_result:
            logger.info(
                f"[ToolReadGuard] blocked {tool_name}: {duplicate_read_result.get('result', '')}"
            )
            self._record_tool_result(tool_name, arguments, False)
            self._record_tool_failure_detail(tool_name, arguments, duplicate_read_result.get("result", "blocked"))
            self._record_tool_metric_event(tool_name, arguments, duplicate_read_result)
            return duplicate_read_result

        budget_result = self._preflight_tool_budget_check(tool_name)
        if budget_result:
            logger.warning(
                f"[ToolBudget] blocked {tool_name}: {budget_result.get('result', '')}"
            )
            self._record_tool_result(tool_name, arguments, False)
            self._record_tool_failure_detail(tool_name, arguments, budget_result.get("result", "blocked"))
            self._record_tool_metric_event(tool_name, arguments, budget_result)
            return budget_result

        policy_result = self._preflight_tool_policy_check(tool_name, arguments)
        if policy_result:
            logger.warning(
                f"[ToolPolicy] blocked {tool_name}: {policy_result.get('result', '')}"
            )
            self._record_tool_result(tool_name, arguments, False)
            self._record_tool_failure_detail(tool_name, arguments, policy_result.get("result", "blocked"))
            self._capture_tool_error_memory(
                tool_name,
                policy_result.get("result", "blocked"),
                arguments,
                "policy_blocked",
            )
            self._record_tool_metric_event(tool_name, arguments, policy_result)
            return policy_result

        # Check for consecutive failures (retry protection)
        should_stop, stop_reason, is_critical = self._check_consecutive_failures(tool_name, arguments)
        if should_stop:
            logger.error(f"🛑 {stop_reason}")
            self._record_tool_result(tool_name, arguments, False)
            
            if is_critical:
                # Critical failure - abort entire conversation
                result = {
                    "status": "critical_error",
                    "result": stop_reason,
                    "execution_time": 0
                }
            else:
                # Normal failure - let LLM try different approach
                result = {
                    "status": "error",
                    "result": f"{stop_reason}\n\n当前方法行不通，请尝试完全不同的方法或向用户询问更多信息。",
                    "execution_time": 0
                }
            self._record_tool_failure_detail(tool_name, arguments, result["result"])
            self._capture_tool_error_memory(
                tool_name,
                result["result"],
                arguments,
                "retry_protection",
            )
            return result

        self._emit_event("tool_execution_start", {
            "tool_call_id": tool_id,
            "tool_name": tool_name,
            "arguments": arguments
        })
        self._record_short_term_tool_start(tool_name, arguments)

        try:
            tool = self.tools.get(tool_name)
            if not tool:
                raise ValueError(self._build_tool_not_found_message(tool_name))

            # Set tool context
            tool.model = self.model
            tool.context = self.agent

            # Execute tool
            start_time = time.time()
            result: ToolResult = tool.execute_tool(arguments)
            execution_time = time.time() - start_time

            result_dict = {
                "status": result.status,
                "result": result.result,
                "execution_time": execution_time
            }

            # Record tool result for failure tracking
            success = result.status == "success"
            self._record_tool_result(tool_name, arguments, success)
            if success:
                self._record_successful_tool_read(tool_name, arguments, result.result)
                self._record_tool_phase_observation(tool_name, arguments, result.result)
            if not success:
                self._record_tool_failure_detail(tool_name, arguments, result.result)
                self._capture_tool_error_memory(
                    tool_name,
                    result.result,
                    arguments,
                    "tool_result_error",
                    execution_time=execution_time,
                )

            # Auto-refresh skills after skill creation
            if tool_name == "bash" and result.status == "success":
                command = arguments.get("command", "")
                if "init_skill.py" in command and self.agent.skill_manager:
                    logger.info("Detected skill creation, refreshing skills...")
                    self.agent.refresh_skills()
                    logger.info(f"Skills refreshed! Now have {len(self.agent.skill_manager.skills)} skills")

            self._emit_event("tool_execution_end", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                **result_dict
            })
            self._record_short_term_tool_end(tool_name, arguments, result.status, result.result)

            self._record_work_state(tool_name, arguments, result.status, result.result)
            self._record_tool_metric_event(tool_name, arguments, result_dict)

            return result_dict

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            error_result = {
                "status": "error",
                "result": str(e),
                "execution_time": 0
            }
            self._record_tool_result(tool_name, arguments, False)
            self._record_tool_failure_detail(tool_name, arguments, str(e))
            self._capture_tool_error_memory(
                tool_name,
                str(e),
                arguments,
                "exception",
            )
            
            self._emit_event("tool_execution_end", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                **error_result
            })
            self._record_short_term_tool_end(tool_name, arguments, "error", str(e))

            self._record_work_state(tool_name, arguments, "error", str(e))
            self._record_tool_metric_event(tool_name, arguments, error_result)

            return error_result

    def _record_tool_metric_event(self, tool_name: str, arguments: dict, result: dict) -> None:
        try:
            from agent.tools.metrics import classify_tool_use, default_tool_budget, record_tool_metric

            args_hash = self._hash_args(arguments or {})
            repeat_count = 0
            for name, ahash, _success in reversed(getattr(self, "tool_failure_history", [])):
                if name == tool_name and ahash == args_hash:
                    repeat_count += 1
                else:
                    break
            route = getattr(self, "tool_route", None)
            status = str((result or {}).get("status") or "")
            output = (result or {}).get("result", "")
            result_chars = len(output) if isinstance(output, str) else len(json.dumps(output, ensure_ascii=False))
            usefulness_label = classify_tool_use(tool_name, status, repeat_count=repeat_count)
            if getattr(self, "tool_budget", None) is None:
                self.tool_budget = default_tool_budget(
                    getattr(route, "mode", ""),
                    getattr(route, "task_type", ""),
                )
            if (result or {}).get("count_budget") is False:
                budget_payload = {
                    "budget_max_calls": getattr(self.tool_budget, "max_calls", 0),
                    "budget_total_calls": getattr(self.tool_budget, "total_calls", 0),
                    "over_budget": False,
                }
            else:
                budget_payload = self.tool_budget.record(tool_name, usefulness_label)
            payload = {
                "tool_name": tool_name,
                "task_type": getattr(route, "task_type", ""),
                "route_mode": getattr(route, "mode", ""),
                "arguments_hash": args_hash,
                "status": status,
                "latency_ms": int(float((result or {}).get("execution_time", 0) or 0) * 1000),
                "result_chars": result_chars,
                "repeat_count": repeat_count,
                "usefulness_label": usefulness_label,
                **budget_payload,
            }
            if not hasattr(self, "tool_metric_events"):
                self.tool_metric_events = []
            self.tool_metric_events.append(payload)
            record_tool_metric(payload)
        except Exception as exc:
            logger.debug(f"Tool metric record skipped: {exc}")

    def _ensure_read_cache(self) -> dict:
        if not hasattr(self, "chapter_read_cache") or self.chapter_read_cache is None:
            self.chapter_read_cache = {}
        return self.chapter_read_cache

    def _record_successful_tool_read(self, tool_name: str, arguments: dict, result: Any) -> None:
        if tool_name not in {"textbook_chapter", "read", "file_read"}:
            return
        arguments = arguments or {}
        result = result if isinstance(result, dict) else {}
        if tool_name == "textbook_chapter" and str(arguments.get("action") or "") != "read":
            return
        content = result.get("content")
        if not isinstance(content, str) or not content.strip():
            return
        path = str(result.get("path") or result.get("file_path") or arguments.get("path") or "")
        chapter = str(result.get("chapter_num") or arguments.get("chapter_num") or "")
        book_id = str(result.get("book_id") or arguments.get("book_id") or self._book_id_from_path(path))
        if not chapter:
            chapter = self._chapter_num_from_path(path)
        if not chapter and tool_name in {"read", "file_read"}:
            return
        title = self._extract_markdown_title(content)
        chars = int(result.get("chars") or len(content))
        record = {
            "book_id": book_id,
            "chapter_num": chapter,
            "path": path,
            "path_key": self._normalize_read_path(path),
            "basename": os.path.basename(path.replace("/", os.sep)),
            "title": title,
            "chars": chars,
            "content_hash": result.get("content_hash") or self._hash_args({"content": content}),
            "read_complete": True,
        }
        cache = self._ensure_read_cache()
        keys = []
        if book_id and chapter:
            keys.append(f"book:{book_id}:chapter:{chapter}")
        if record["path_key"]:
            keys.append(f"path:{record['path_key']}")
        if record["basename"]:
            keys.append(f"basename:{record['basename'].lower()}")
        for key in keys:
            cache[key] = record

    def _record_tool_phase_observation(self, tool_name: str, arguments: dict, result: Any) -> None:
        state = getattr(self, "tool_phase_state", None)
        if not isinstance(state, dict) or state.get("intent") != "chapter_review":
            return
        arguments = arguments or {}
        if tool_name == "textbook_chapter" and str(arguments.get("action") or "") == "read":
            state["chapter_read"] = True
            return
        if tool_name in {"read", "file_read"}:
            path = str(arguments.get("path") or arguments.get("file_path") or "").replace("\\", "/").lower()
            if "review_checklist_chapter" in path or "review_checklist" in path:
                state["review_checklist_read"] = True
                return
            if "/chapters/" in path and "chapter_" in path:
                state["chapter_read"] = True
                return
            if "/outline/" in path or path.endswith("outline.md"):
                state["outline_read"] = True
                return
        if tool_name == "textbook_outline":
            state["outline_read"] = True

    def _preflight_duplicate_chapter_read_check(self, tool_name: str, arguments: dict) -> Dict[str, Any] | None:
        arguments = arguments or {}
        if not self._is_protected_textbook_route():
            return None
        if arguments.get("force") or arguments.get("refresh"):
            return None
        record = None
        if tool_name == "textbook_chapter" and str(arguments.get("action") or "") == "read":
            book_id = str(arguments.get("book_id") or "")
            chapter = str(arguments.get("chapter_num") or arguments.get("chapter_number") or "")
            record = self._find_chapter_read_record(book_id=book_id, chapter=chapter)
        elif tool_name in {"read", "file_read"}:
            path = str(arguments.get("path") or arguments.get("file_path") or "")
            if not self._looks_like_chapter_path(path):
                return None
            record = self._find_chapter_read_record(path=path)
        if not record:
            return None
        return {
            "status": "blocked",
            "result": (
                "This chapter has already been fully read in the current turn. "
                f"chapter={record.get('chapter_num') or '?'} title={record.get('title') or '?'} "
                f"chars={record.get('chars') or 0} path={record.get('path') or ''}. "
                "Use the cached chapter facts and continue with review or repair; do not spend tool budget rereading it. "
                "If the file changed or the user explicitly asked to reread it, call with force=true."
            ),
            "execution_time": 0,
            "count_budget": False,
        }

    def _find_chapter_read_record(self, book_id: str = "", chapter: str = "", path: str = "") -> dict:
        cache = self._ensure_read_cache()
        candidates = []
        if book_id and chapter:
            candidates.append(f"book:{book_id}:chapter:{chapter}")
        if path:
            path_key = self._normalize_read_path(path)
            if path_key:
                candidates.append(f"path:{path_key}")
            basename = os.path.basename(path.replace("/", os.sep)).lower()
            if basename:
                candidates.append(f"basename:{basename}")
        for key in candidates:
            record = cache.get(key)
            if record and record.get("read_complete"):
                return record
        return {}

    @staticmethod
    def _normalize_read_path(path: str) -> str:
        value = str(path or "").strip()
        if not value:
            return ""
        return os.path.normcase(os.path.normpath(value.replace("/", os.sep)))

    @staticmethod
    def _looks_like_chapter_path(path: str) -> bool:
        value = str(path or "").lower().replace("\\", "/")
        return "/chapters/" in value and re.search(r"chapter[_-]?\d+\.md$", value) is not None

    @staticmethod
    def _chapter_num_from_path(path: str) -> str:
        match = re.search(r"chapter[_-]?0*(\d+)\.md$", str(path or ""), re.I)
        return match.group(1) if match else ""

    @staticmethod
    def _book_id_from_path(path: str) -> str:
        match = re.search(r"[\\/](tb_[A-Za-z0-9_-]+)[\\/]", str(path or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _extract_markdown_title(content: str) -> str:
        for line in str(content or "").splitlines()[:20]:
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return ""

    def _preflight_tool_budget_check(self, tool_name: str) -> Dict[str, Any] | None:
        """Hard-stop tool execution once the route budget is exhausted."""
        try:
            from agent.tools.metrics import default_tool_budget

            route = getattr(self, "tool_route", None)
            if getattr(self, "tool_budget", None) is None:
                self.tool_budget = default_tool_budget(
                    getattr(route, "mode", ""),
                    getattr(route, "task_type", ""),
                )
            max_calls = int(getattr(self.tool_budget, "max_calls", 0) or 0)
            total_calls = int(getattr(self.tool_budget, "total_calls", 0) or 0)
            if max_calls > 0 and total_calls >= max_calls:
                self.tool_budget_exhausted = True
                return {
                    "status": "blocked",
                    "result": (
                        f"Tool budget exhausted for this turn ({total_calls}/{max_calls}). "
                        "Stop calling tools and answer from current evidence, or ask the user for a narrower next step."
                    ),
                    "execution_time": 0,
                }
        except Exception as exc:
            logger.debug(f"Tool budget preflight skipped for {tool_name}: {exc}")
        return None

    def _should_stop_after_tool_results(self, tool_results: list) -> bool:
        if getattr(self, "tool_budget_exhausted", False):
            return True
        for result in tool_results or []:
            text = str((result or {}).get("result") or "").lower()
            if (result or {}).get("status") == "blocked" and "tool budget exhausted" in text:
                self.tool_budget_exhausted = True
                return True
        return False

    def _should_close_tool_phase_after_results(self, tool_results: list) -> bool:
        state = getattr(self, "tool_phase_state", None) or {}
        if state.get("closed"):
            return False
        if state.get("intent") == "chapter_review":
            if state.get("chapter_read") and (state.get("review_checklist_read") or state.get("outline_read")):
                self.tool_phase_stop_reason = "review_evidence_ready"
                state["closed"] = True
                return True
        return False

    def _close_tool_phase_for_answer(self) -> None:
        reason = getattr(self, "tool_phase_stop_reason", "") or "evidence_ready"
        self.tools = {}
        self.messages.append({
            "role": "user",
            "content": [{
                "type": "text",
                "text": (
                    "Evidence is ready for the current task. Stop calling tools now. "
                    "Use only the chapter/outline/checklist evidence already present in this turn, "
                    "and provide the requested review or answer directly to the user. "
                    "Do not search memory, do not query knowledge, and do not reread the same chapter."
                ),
            }],
        })
        self._emit_event("tool_phase_closed", {
            "reason": reason,
            "intent": (getattr(self, "tool_phase_state", None) or {}).get("intent", ""),
        })

    def _tool_budget_exhausted_final_response(self, tool_results: list) -> str:
        budget = getattr(self, "tool_budget", None)
        total_calls = getattr(budget, "total_calls", 0)
        max_calls = getattr(budget, "max_calls", 0)
        recent_text = self._latest_assistant_text_excerpt()
        lines = [
            f"本轮工具预算已达到上限（{total_calls}/{max_calls}），我已停止继续调用工具，避免继续空转。",
            "请下一轮继续时，我会先根据已保存的上下文和 handoff 接着处理，不会重新开始整章流程。",
        ]
        if recent_text:
            lines.extend(["", "最近进展：", recent_text])
        return "\n".join(lines)

    def _emit_tool_diagnostics(self) -> None:
        events = list(getattr(self, "tool_metric_events", []) or [])
        if not events:
            return
        label_counts = {}
        tool_counts = {}
        over_budget_calls = 0
        for item in events:
            label = item.get("usefulness_label", "unknown")
            label_counts[label] = label_counts.get(label, 0) + 1
            tool = item.get("tool_name", "unknown")
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
            if item.get("over_budget"):
                over_budget_calls += 1
        payload = {
            "total_calls": len(events),
            "label_counts": label_counts,
            "tool_counts": tool_counts,
            "over_budget_calls": over_budget_calls,
            "route_mode": events[-1].get("route_mode", ""),
            "task_type": events[-1].get("task_type", ""),
        }
        self._emit_event("tool_diagnostics", payload)

    def _preflight_tool_policy_check(self, tool_name: str, arguments: dict) -> Dict[str, Any] | None:
        """Block high-waste or high-risk calls before executing a tool."""
        arguments = arguments or {}
        if tool_name == "web_fetch" and self._is_search_result_url(str(arguments.get("url") or "")):
            return {
                "status": "blocked",
                "result": (
                    "Tool policy blocked web_fetch on search result pages. "
                    "Use the search workflow to discover concrete source URLs, then fetch selected source pages."
                ),
                "execution_time": 0,
            }

        if tool_name == "bash" and self._is_protected_textbook_route():
            command = str(arguments.get("command") or "")
            if self._looks_like_chapter_write_command(command):
                return {
                    "status": "blocked",
                    "result": (
                        "Tool policy blocked bash from writing textbook chapter content in protected textbook mode. "
                        "Use textbook_chapter for normal chapter operations; in repair mode use the canonical chapter actions only."
                    ),
                    "execution_time": 0,
                }
        return None

    @staticmethod
    def _is_search_result_url(url: str) -> bool:
        if not url:
            return False
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            path = (parsed.path or "").lower()
            if "google." in host and path.startswith("/search"):
                return True
            if "bing.com" in host and path.startswith("/search"):
                return True
            if "baidu.com" in host and path.startswith("/s"):
                return True
            if "search.brave.com" in host and path.startswith("/search"):
                return True
        except Exception:
            return False
        return False

    def _is_protected_textbook_route(self) -> bool:
        route = getattr(self, "tool_route", None)
        return (
            getattr(route, "mode", "") in {"strict", "repair"}
            and getattr(route, "task_type", "") == "textbook"
        )

    def _is_strict_textbook_route(self) -> bool:
        route = getattr(self, "tool_route", None)
        return (
            getattr(route, "mode", "") == "strict"
            and getattr(route, "task_type", "") == "textbook"
        )

    @staticmethod
    def _looks_like_chapter_write_command(command: str) -> bool:
        low = (command or "").lower()
        write_markers = ("add-content", "set-content", "out-file", ">", ">>")
        chapter_markers = ("chapter_", "chapters", "textbooks", "教材", "章节")
        return any(marker in low for marker in write_markers) and any(
            marker in low for marker in chapter_markers
        )

    @staticmethod
    def _tool_parse_recovery_hint(tool_name: str) -> str:
        if tool_name in {"write", "edit", "bash", "textbook_chapter"}:
            return (
                "\n\nRecovery rule for chapter writing: your next tool call must be a smaller "
                "textbook_chapter call. Use append_section for new material, replace_section "
                "only for one clear unique section, rename_heading for title-only fixes, "
                "delete_section for duplicate sections, replace_exact for one unique snippet, "
                "or list_backups/restore_backup when the chapter is corrupted. Do not use bash "
                "or PowerShell to write Chinese Markdown."
            )
        return "\n\nRecovery rule: retry with a smaller, strictly valid JSON argument object."

    def _capture_tool_error_memory(
            self,
            tool_name: str,
            detail,
            arguments: dict,
            error_type: str,
            execution_time: float = 0.0,
    ) -> None:
        try:
            from agent.memory import record_tool_error

            record_tool_error(
                tool_name,
                detail,
                {
                    "tool": tool_name,
                    "arguments": arguments or {},
                    "error_type": error_type,
                    "execution_time": execution_time,
                    "agent_name": getattr(self.agent, "name", ""),
                    "model": getattr(self.model, "model", ""),
                    "session_id": getattr(self.model, "session_id", ""),
                    "channel_type": getattr(self.model, "channel_type", ""),
                },
            )
        except Exception as exc:
            logger.debug(f"Tool error memory capture skipped: {exc}")

    def _build_error_memory_context(self) -> str:
        try:
            from agent.memory import build_error_memory_context

            return build_error_memory_context(max_items=3, max_detail_chars=220)
        except Exception as exc:
            logger.debug(f"Error memory context skipped: {exc}")
            return ""

    def _record_work_state(self, tool_name: str, arguments: dict, status: str, result: str):
        try:
            from agent.memory.work_state import WorkStateManager
            from common.app_paths import system_dir
            mgr = WorkStateManager(system_dir())
            result_summary = ""
            if isinstance(result, str) and len(result) > 200:
                result_summary = result[:200] + "..."
            elif isinstance(result, str):
                result_summary = result
            mgr.record_tool_call(tool_name, arguments, status, result_summary)
        except Exception as e:
            logger.debug(f"Work state record skipped: {e}")

    def _build_tool_not_found_message(self, tool_name: str) -> str:
        """Build a helpful error message when a tool is not found.

        If a skill with the same name exists in skill_manager, read its
        SKILL.md and include the content so the LLM knows how to use it.
        """
        available_tools = list(self.tools.keys())
        base_msg = f"Tool '{tool_name}' not found. Available tools: {available_tools}"
        route = getattr(self, "tool_route", None)
        if (
            getattr(route, "mode", "") == "strict"
            and getattr(route, "task_type", "") == "textbook"
            and tool_name not in available_tools
        ):
            required = ", ".join(getattr(route, "required_tools", []) or ["textbook_chapter"])
            return (
                f"Tool '{tool_name}' is not visible in the current strict textbook route. "
                f"Available tools: {available_tools}. Required textbook tool(s): {required}. "
                "Do not retry hidden tools such as write, edit, bash, or shell. "
                "Return to the selected SKILL.md workflow and use the visible canonical textbook tool. "
                "For repairs, use textbook_chapter actions list_backups, restore_backup, delete_section, "
                "rename_heading, replace_exact, or replace_section as appropriate. If the visible tool "
                "still cannot complete the precise operation, stop and explain the limitation to the user."
            )
        if (
            getattr(route, "mode", "") == "repair"
            and getattr(route, "task_type", "") == "textbook"
            and tool_name not in available_tools
        ):
            required = ", ".join(getattr(route, "required_tools", []) or ["textbook_chapter"])
            return (
                f"Tool '{tool_name}' is not visible in the current textbook repair route. "
                f"Available tools: {available_tools}. Start with canonical tool(s): {required}. "
                "Use textbook_chapter list_backups/restore_backup for damaged chapters, delete_section "
                "for duplicate sections, rename_heading for title-only fixes, and replace_exact for unique snippets. "
                "Do not retry hidden tools such as edit or write, and never use bash or shell redirection to write Chinese textbook body text. "
                "If the visible tools cannot complete the operation, stop and explain the limitation to the user."
            )

        skill_manager = getattr(self.agent, 'skill_manager', None)
        if not skill_manager:
            return base_msg

        skill_entry = skill_manager.get_skill(tool_name)
        if not skill_entry:
            return base_msg

        skill = skill_entry.skill
        skill_md_path = skill.file_path
        skill_content = ""
        try:
            with open(skill_md_path, 'r', encoding='utf-8') as f:
                skill_content = f.read()
        except Exception:
            skill_content = skill.description

        logger.info(
            f"[Agent] Tool '{tool_name}' not found, but matched skill '{skill.name}'. "
            f"Guiding LLM to use the skill instead."
        )

        return (
            f"Tool '{tool_name}' is not a built-in tool, but a matching skill "
            f"'{skill.name}' is available. You should use existing tools (e.g. bash with curl) "
            f"to accomplish this task following the skill instructions below:\n\n"
            f"--- SKILL: {skill.name} (path: {skill_md_path}) ---\n"
            f"{skill_content}\n"
            f"--- END SKILL ---\n\n"
            f"Available tools: {available_tools}"
        )

    def _validate_and_fix_messages(self):
        """Delegate to the shared sanitizer (see message_sanitizer.py)."""
        sanitize_claude_messages(self.messages)

    def _effective_context_budget(self) -> tuple[int, int]:
        """
        Return (max_allowed_tokens, reserve_tokens) for the next model call.

        User configuration is treated as a requested ceiling, not as truth. The
        final budget is always clamped by the detected model window, with a
        reserve for output and tool-call growth. This prevents oversized config
        values from bypassing trimming and sending multi-million-token prompts.
        """
        context_window = self.agent._get_model_context_window()
        reserve = self.agent._get_context_reserve_tokens()
        if context_window <= reserve:
            reserve = max(1024, int(context_window * 0.2))

        configured = getattr(self.agent, "max_context_tokens", None)
        if configured:
            try:
                configured = int(configured)
            except (TypeError, ValueError):
                configured = None

        hard_cap = max(1024, context_window - reserve)
        if configured and configured > 0:
            max_allowed = min(configured, hard_cap)
        else:
            max_allowed = hard_cap

        return max(1024, max_allowed), reserve

    def _context_compress_ratio(self) -> float:
        try:
            from config import conf
            value = float(conf().get("agent_context_compress_ratio", 0.92) or 0.92)
            return min(0.98, max(0.70, value))
        except Exception:
            return 0.92

    def _midrun_trim_ratio(self) -> float:
        try:
            from config import conf
            value = float(conf().get("agent_context_midrun_trim_ratio", 0.97) or 0.97)
            return min(0.995, max(0.85, value))
        except Exception:
            return 0.97

    def _identify_complete_turns(self) -> List[Dict]:
        """
        识别完整的对话轮次
        
        一个完整轮次包括：
        1. 用户消息（text）
        2. AI 回复（可能包含 tool_use）
        3. 工具结果（tool_result，如果有）
        4. 后续 AI 回复（如果有）
        
        Returns:
            List of turns, each turn is a dict with 'messages' list
        """
        turns = []
        current_turn = {'messages': []}
        
        for msg in self.messages:
            role = msg.get('role')
            content = msg.get('content', [])
            
            if role == 'user':
                # Determine if this is a real user query (not a tool_result injection
                # or an internal hint message injected by the agent loop).
                is_user_query = False
                has_tool_result = False
                if isinstance(content, list):
                    has_text = any(
                        isinstance(block, dict) and block.get('type') == 'text'
                        for block in content
                    )
                    has_tool_result = any(
                        isinstance(block, dict) and block.get('type') == 'tool_result'
                        for block in content
                    )
                    # A message with tool_result is always internal, even if it
                    # also contains text blocks (shouldn't happen, but be safe).
                    is_user_query = has_text and not has_tool_result
                elif isinstance(content, str):
                    is_user_query = True
                
                if is_user_query:
                    if current_turn['messages']:
                        turns.append(current_turn)
                    current_turn = {'messages': [msg]}
                else:
                    current_turn['messages'].append(msg)
            else:
                # AI 回复，属于当前轮次
                current_turn['messages'].append(msg)
        
        # 添加最后一个轮次
        if current_turn['messages']:
            turns.append(current_turn)
        
        return turns
    
    def _estimate_turn_tokens(self, turn: Dict) -> int:
        """估算一个轮次的 tokens"""
        return sum(
            self.agent._estimate_message_tokens(msg) 
            for msg in turn['messages']
        )

    def _progressive_compress_tool_results(self):
        """
        Apply progressive compression to tool results based on their age.

        - Recent 2 turns: Keep full (no compression)
        - 3-5 turns ago: Replace large tool results (>1500 chars) with smart summaries
        - 6+ turns ago: Replace all tool results with summaries, compress tool_use to descriptions

        This preserves key information (file names, structure, conclusions) while
        dramatically reducing token count, instead of crude truncation or deletion.
        """
        from agent.protocol.message_utils import (
            progressive_compress_messages,
            compact_historical_tool_result_content,
        )

        if len(self.messages) < 4:
            return

        turns = self._identify_complete_turns()
        total_turns = len(turns)
        if total_turns < 3:
            return

        current_turn_num = total_turns

        compressed_count = 0
        saved_chars = 0

        for turn_idx, turn in enumerate(turns):
            turn_age = total_turns - turn_idx

            if turn_age <= 1:
                continue

            for msg in turn.get("messages", []):
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue

                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue

                    result_str = block.get("content", "")
                    if not isinstance(result_str, str):
                        continue

                    threshold = 800 if turn_age <= 4 else 200

                    if len(result_str) > threshold:
                        tool_use_id = block.get("tool_use_id", "")
                        tool_name, tool_args = self._find_tool_info_for_result(tool_use_id)

                        summary = compact_historical_tool_result_content(
                            result_str,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            status="error" if block.get("is_error") else "success",
                            max_chars=self._historical_tool_result_context_limit(),
                        )

                        if len(summary) < len(result_str):
                            saved_chars += len(result_str) - len(summary)
                            block["content"] = summary
                            compressed_count += 1

        if compressed_count > 0:
            self._record_context_compression("tool_results", saved_chars=saved_chars)
            logger.info(
                f"📦 渐进式压缩工具结果: 压缩了 {compressed_count} 个结果，"
                f"节省 ~{saved_chars} 字符"
            )

    def _find_tool_info_for_result(self, tool_use_id: str) -> tuple:
        for msg in self.messages:
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == tool_use_id:
                            return block.get("name", ""), block.get("input", {})
        return "", {}

    def _aggressive_trim_for_overflow(self) -> bool:
        """
        Aggressively trim context when a real overflow error is returned by the API.

        This method goes beyond normal _trim_messages by:
        1. Truncating all tool results (including current turn) to a small limit
        2. Keeping only the last 5 complete conversation turns
        3. Truncating overly long user messages

        Returns:
            True if messages were trimmed (worth retrying), False if nothing left to trim
        """
        if not self.messages:
            return False

        original_count = len(self.messages)

        # Step 1: Aggressively truncate ALL tool results to 5K chars
        AGGRESSIVE_LIMIT = 10000
        truncated = 0
        for msg in self.messages:
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                # Truncate tool_result blocks
                if block.get("type") == "tool_result":
                    result_str = block.get("content", "")
                    if isinstance(result_str, str) and len(result_str) > AGGRESSIVE_LIMIT:
                        block["content"] = (
                            result_str[:AGGRESSIVE_LIMIT]
                            + f"\n\n[Truncated for context recovery: "
                            f"{len(result_str)} -> {AGGRESSIVE_LIMIT} chars]"
                        )
                        truncated += 1
                # Truncate tool_use input blocks (e.g. large write content)
                if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                    input_str = json.dumps(block["input"], ensure_ascii=False)
                    if len(input_str) > AGGRESSIVE_LIMIT:
                        # Keep only a summary of the input
                        for key, val in block["input"].items():
                            if isinstance(val, str) and len(val) > 1000:
                                block["input"][key] = (
                                    val[:1000]
                                    + f"... [truncated {len(val)} chars]"
                                )
                        truncated += 1

        # Step 2: Truncate overly long user text messages (e.g. pasted content)
        USER_MSG_LIMIT = 10000
        for msg in self.messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if len(text) > USER_MSG_LIMIT:
                            block["text"] = (
                                text[:USER_MSG_LIMIT]
                                + f"\n\n[Message truncated for context recovery: "
                                f"{len(text)} -> {USER_MSG_LIMIT} chars]"
                            )
                            truncated += 1
            elif isinstance(content, str) and len(content) > USER_MSG_LIMIT:
                msg["content"] = (
                    content[:USER_MSG_LIMIT]
                    + f"\n\n[Message truncated for context recovery: "
                    f"{len(content)} -> {USER_MSG_LIMIT} chars]"
                )
                truncated += 1

        # Step 3: Keep only the last 5 complete turns
        turns = self._identify_complete_turns()
        if len(turns) > 5:
            kept_turns = turns[-5:]
            new_messages = []
            for turn in kept_turns:
                new_messages.extend(turn["messages"])
            removed = len(turns) - 5
            self.messages[:] = new_messages
            logger.info(
                f"🔧 Aggressive trim: removed {removed} old turns, "
                f"truncated {truncated} large blocks, "
                f"{original_count} -> {len(self.messages)} messages"
            )
            return True

        if truncated > 0:
            logger.info(
                f"🔧 Aggressive trim: truncated {truncated} large blocks "
                f"(no turns removed, only {len(turns)} turn(s) left)"
            )
            return True

        # Nothing left to trim
        logger.warning("🔧 Aggressive trim: nothing to trim, will clear history")
        return False

    def _build_context_summary_callback(self, discarded_turns: list, kept_turns: list):
        """
        Build a callback that injects an LLM summary into the first user
        message of *kept_turns*. Returns None if no valid injection target.

        The callback is passed to flush_from_messages so that the same LLM
        call that writes daily memory also provides the in-context summary.
        """
        if not kept_turns:
            return None

        # Find the first user text block in kept_turns as injection target
        target_block = None
        for turn in kept_turns:
            for msg in turn["messages"]:
                if msg.get("role") == "user":
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                target_block = block
                                break
                    if target_block:
                        break
            if target_block:
                break

        if not target_block:
            return None

        turn_count = len(discarded_turns)
        original_text = target_block["text"]

        def _on_summary_ready(summary: str):
            if not summary or not summary.strip():
                return
            target_block["text"] = (
                f"[System: Previous conversation summary — "
                f"{turn_count} turns were compacted]\n\n"
                f"{summary.strip()}\n\n"
                f"The recent conversation continues below.\n\n---\n\n"
                f"{original_text}"
            )
            structured_summary = self._format_compacted_context_summary(
                summary.strip(),
                turn_count=turn_count,
            )
            target_block["text"] = (
                f"{structured_summary}\n\n"
                f"The recent conversation continues below.\n\n---\n\n"
                f"{original_text}"
            )
            if not self._message_list_contains_block(target_block):
                self.messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": target_block["text"]}],
                })
            logger.info(
                f"📝 Context summary injected "
                f"({len(summary)} chars, {turn_count} turns)"
            )

        return _on_summary_ready

    def _persist_context_handoff(self, discarded_turns: list, kept_turns: list, reason: str = "trim") -> Dict[str, Any]:
        """Persist a compact handoff document for context compression recovery.

        The handoff is intentionally fielded around current_done/todo so the
        next model turn can inherit the active task without rereading noisy
        historical tool results.
        """
        try:
            from common.app_paths import system_dir
            from agent.memory.handoff import HandoffService

            session_id = str(getattr(self.model, "session_id", "") or getattr(self.agent, "session_id", "") or "default")
            messages = []
            for turn in (discarded_turns or []) + (kept_turns or []):
                messages.extend(turn.get("messages", []) or [])
            if not messages:
                return {}
            service = HandoffService(system_dir())
            path = service.update_from_messages(session_id, messages)
            content = path.read_text(encoding="utf-8")
            payload = {"path": str(path), "content": content, "reason": reason}
            logger.info(f"[ContextHandoff] wrote {path} for reason={reason}")
            return payload
        except Exception as exc:
            logger.debug(f"[ContextHandoff] persist skipped: {exc}")
            return {}

    def _near_max_turn_handoff_threshold(self) -> int:
        if self.max_turns <= 1:
            return 1
        return max(1, min(49, self.max_turns - 1))

    def _maybe_persist_near_max_turn_handoff(
        self,
        turn: int,
        final_response: str = "",
        tool_calls: list | None = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Persist a resume plan before a long tool loop reaches the hard cap."""
        if getattr(self, "_near_max_turn_handoff_saved", False):
            return {}
        if not force and turn < self._near_max_turn_handoff_threshold():
            return {}
        if not force and not tool_calls:
            return {}
        try:
            from common.app_paths import system_dir
            from agent.memory.handoff import HandoffService

            session_id = str(
                getattr(self.model, "session_id", "")
                or getattr(self.agent, "session_id", "")
                or "default"
            )
            tool_names = ", ".join(
                str(call.get("name", "")) for call in (tool_calls or []) if isinstance(call, dict)
            ) or "none"
            recent_text = final_response or self._latest_assistant_text_excerpt()
            plan_text = (
                f"最大执行轮数保护：当前已执行到第 {turn} 轮，任务仍可能未完成，已保存继续计划。\n"
                f"当前已完成：{self._clip_for_handoff(recent_text, 260) or '已完成部分工具执行或阶段性处理。'}\n"
                f"最近工具：{tool_names}\n"
                "下一步：用户继续下一轮对话时，先读取本 handoff，确认当前文件/状态，然后从最近未完成的小步骤继续；"
                "不要重新发起整条管线，不要重复已经成功的工具调用。"
            )
            messages = list(getattr(self, "messages", []) or [])
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": plan_text}],
            })
            service = HandoffService(system_dir())
            path = service.update_from_messages(session_id, messages)
            content = path.read_text(encoding="utf-8")
            payload = {
                "path": str(path),
                "content": content,
                "reason": "near-max-turn",
                "turn": turn,
                "max_turns": self.max_turns,
            }
            self._near_max_turn_handoff_saved = True
            self._emit_event("session_handoff_saved", {
                "path": str(path),
                "reason": "near-max-turn",
                "turn": turn,
                "max_turns": self.max_turns,
            })
            logger.info(f"[ContextHandoff] wrote near-max-turn handoff {path} at turn={turn}")
            return payload
        except Exception as exc:
            logger.debug(f"[ContextHandoff] near-max-turn persist skipped: {exc}")
            return {}

    @staticmethod
    def _clip_for_handoff(text: str, max_chars: int) -> str:
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        return value if len(value) <= max_chars else value[: max_chars - 3].rstrip() + "..."

    def _inject_context_handoff_summary(self, handoff: Dict[str, Any]) -> None:
        if not handoff or not handoff.get("content"):
            return
        todo = self._extract_handoff_section(handoff.get("content", ""), "Todo")
        done = self._extract_handoff_section(handoff.get("content", ""), "Current Done")
        summary = [
            "[System: Context Compression Handoff]",
            f"path: {handoff.get('path', '')}",
            "This handoff was created during context compression. Treat Todo as the next-step authority.",
            "Current Done:",
            done or "- No completed work was captured before compaction.",
            "Todo:",
            todo or "- Continue from the current user goal after verifying current state.",
        ]
        block_text = "\n".join(summary)
        marker = "[System: Context Compression Handoff]"
        for msg in self.messages:
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if marker in text:
                        block["text"] = self._strip_context_handoff_summary(text)
        for msg in reversed(self.messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    original = (block.get("text") or "").strip()
                    block["text"] = f"{block_text}\n\n---\n\n{original}"
                    return

    @staticmethod
    def _extract_handoff_section(content: str, section: str, max_lines: int = 6) -> str:
        lines = str(content or "").splitlines()
        start = -1
        for idx, line in enumerate(lines):
            if line.strip() == f"## {section}":
                start = idx + 1
                break
        if start < 0:
            return ""
        values = []
        for line in lines[start:]:
            if line.startswith("## "):
                break
            if line.strip():
                values.append(line.strip())
            if len(values) >= max_lines:
                break
        return "\n".join(values)

    @staticmethod
    def _strip_context_handoff_summary(text: str) -> str:
        marker = "[System: Context Compression Handoff]"
        if marker not in text:
            return text
        parts = text.split("\n\n---\n\n", 1)
        if len(parts) == 2 and marker in parts[0]:
            return parts[1].strip()
        return text

    @staticmethod
    def _format_compacted_context_summary(summary: str, turn_count: int = 0) -> str:
        return (
            "[Compacted Context Summary]\n"
            f"source_turns: {turn_count} compacted turn(s)\n"
            "confidence: medium\n"
            "confirmed_facts:\n"
            f"- {summary}\n"
            "decisions:\n"
            "- None recorded in the compacted summary unless explicitly listed above.\n"
            "open_tasks:\n"
            "- Verify against current state files or memory before acting on old task state.\n"
            "files_or_state_refs:\n"
            "- Use status files, chapter indexes, memory_search, or memory_get when precision matters.\n"
            "user_preferences:\n"
            "- Do not infer stable preferences from this summary alone.\n"
            "omitted_details:\n"
            "- Intermediate tool outputs and exact wording may have been omitted.\n"
            "must_verify_before_use:\n"
            "- Treat this as a navigation aid, not the sole source of truth for files, dates, status, or user preferences."
        )

    def _message_list_contains_block(self, target_block: dict) -> bool:
        for msg in self.messages:
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if block is target_block:
                        return True
        return False

    def _trim_messages(self):
        """
        智能清理消息历史，保持对话完整性

        使用渐进式压缩策略，确保：
        1. 不会在对话中间截断
        2. 工具调用链（tool_use + tool_result）保持完整
        3. 优先用摘要替代全文，而非丢弃整轮对话
        4. 渐进式压缩：近2轮保持完整 → 3-5轮工具结果摘要化 → 6+轮压缩为文本摘要
        """
        if not self.messages or not self.agent:
            return

        # Step 0: Do not compress historical tool results eagerly. Compression
        # is triggered only after the context approaches the configured ratio
        # of the usable model window.

        # Step 1: 识别完整轮次
        turns = self._identify_complete_turns()
        
        if not turns:
            return
        handoff: Dict[str, Any] = {}
        
        # Step 2: 轮次限制 - 超出时渐进压缩而非丢弃
        if len(turns) > self.max_context_turns:
            removed_count = len(turns) - self.max_context_turns
            
            discarded_turns = turns[:removed_count]
            turns = turns[-self.max_context_turns:]

            logger.info(
                f"💾 上下文轮次超限: {self.max_context_turns + removed_count} > {self.max_context_turns}，"
                f"裁剪至 {self.max_context_turns} 轮（移除 {removed_count} 轮）"
            )

            if self.agent.memory_manager:
                discarded_messages = []
                for turn in discarded_turns:
                    discarded_messages.extend(turn["messages"])
                if discarded_messages:
                    user_id = getattr(self.agent, '_current_user_id', None)
                    cb = self._build_context_summary_callback(discarded_turns, turns)
                    self.agent.memory_manager.flush_memory(
                        messages=discarded_messages, user_id=user_id,
                        reason="trim", max_messages=0,
                        context_summary_callback=cb,
                    )
            handoff = self._persist_context_handoff(discarded_turns, turns, reason="turn-limit")

        # Step 3: Token 限制 - 渐进式压缩
        max_tokens, reserve_tokens = self._effective_context_budget()

        system_tokens = self.agent._estimate_message_tokens({"role": "system", "content": self.system_prompt})
        available_tokens = max_tokens - system_tokens

        current_tokens = sum(self._estimate_turn_tokens(turn) for turn in turns)

        compress_threshold = max_tokens * self._context_compress_ratio()
        if current_tokens + system_tokens > compress_threshold:
            self._progressive_compress_tool_results()
            handoff = self._persist_context_handoff([], turns, reason="tool-result-compress")
            turns = self._identify_complete_turns()
            current_tokens = sum(self._estimate_turn_tokens(turn) for turn in turns)
        
        if current_tokens + system_tokens <= max_tokens:
            new_messages = []
            for turn in turns:
                new_messages.extend(turn['messages'])
            
            old_count = len(self.messages)
            self.messages = new_messages
            
            if old_count > len(self.messages):
                logger.info(f"   重建消息列表: {old_count} -> {len(self.messages)} 条消息")
            if handoff:
                self._inject_context_handoff_summary(handoff)
            self._inject_runtime_context_board(turns, reason="rebuild")
            return

        # Token limit exceeded — progressive compression strategy:
        # Phase 1: Compress oldest turns to text-only (keep user query + final reply)
        # Phase 2: If still over limit, discard oldest turns
        # Phase 3: Last resort — aggressive truncation

        total_turns = len(turns)
        logger.info(
            f"📦 上下文tokens超限: ~{current_tokens + system_tokens} > {max_tokens}，"
            f"开始渐进式压缩（共 {total_turns} 轮）"
        )

        # Phase 1: Progressively compress from oldest to newest
        # Start by compressing the oldest turns to text-only
        compressed_count = 0
        for idx in range(total_turns):
            if current_tokens + system_tokens <= max_tokens:
                break

            turn = turns[idx]
            turn_tokens = self._estimate_turn_tokens(turn)
            
            compressed = compress_turn_to_text_only(turn)
            compressed_tokens = self._estimate_turn_tokens(compressed)
            
            if compressed_tokens < turn_tokens:
                turns[idx] = compressed
                current_tokens -= (turn_tokens - compressed_tokens)
                compressed_count += 1

        if compressed_count > 0:
            self._record_context_compression("turn_summary", saved_chars=0)
            handoff = self._persist_context_handoff([], turns, reason="turn-summary")
            logger.info(
                f"📦 渐进式压缩: 压缩了 {compressed_count} 轮为纯文本摘要 "
                f"(~{current_tokens + system_tokens} tokens)"
            )

        # Check if compression was enough
        if current_tokens + system_tokens <= max_tokens:
            new_messages = []
            for turn in turns:
                new_messages.extend(turn['messages'])
            self.messages = new_messages
            if handoff:
                self._inject_context_handoff_summary(handoff)
            self._inject_runtime_context_board(turns, reason="token-compress")
            return

        # Phase 2: Discard oldest turns, keeping at least 3
        MIN_KEEP_TURNS = 3
        while len(turns) > MIN_KEEP_TURNS and current_tokens + system_tokens > max_tokens:
            removed_turn = turns.pop(0)
            removed_tokens = self._estimate_turn_tokens(removed_turn)
            current_tokens -= removed_tokens

        if self.agent.memory_manager:
            discarded_messages = []
            for turn in turns[:1]:
                discarded_messages.extend(turn["messages"])
            if discarded_messages:
                user_id = getattr(self.agent, '_current_user_id', None)
                self.agent.memory_manager.flush_memory(
                    messages=discarded_messages, user_id=user_id,
                    reason="trim", max_messages=0,
                )
        handoff = self._persist_context_handoff([], turns, reason="token-trim")

        new_messages = []
        for turn in turns:
            new_messages.extend(turn['messages'])
        
        old_count = len(self.messages)
        self.messages = new_messages
        if handoff:
            self._inject_context_handoff_summary(handoff)
        self._inject_runtime_context_board(turns, reason="token-trim")

        logger.info(
            f"📦 渐进式压缩完成: {old_count} -> {len(self.messages)} 条消息，"
            f"~{current_tokens + system_tokens} tokens"
        )

    def _inject_runtime_context_board(self, turns: List[Dict], reason: str = ""):
        """Inject one bounded runtime board into the latest user text."""
        board = self._build_runtime_context_board(turns, reason=reason)
        if not board:
            return

        for msg in self.messages:
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                text = block.get("text", "")
                block["text"] = self._strip_runtime_context_board(text)

        for msg in reversed(self.messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    original = (block.get("text") or "").strip()
                    block["text"] = f"{board}\n\n---\n\n{original}"
                    logger.info(
                        f"📌 Context state board injected ({len(board)} chars, reason={reason})"
                    )
                    return

    def _build_runtime_context_board(self, turns: List[Dict], reason: str = "") -> str:
        sections = []
        route_prompt = getattr(self.tool_route, "prompt", "") if self.tool_route else ""
        if route_prompt:
            sections.append(("Tool Route", self._strip_known_board(route_prompt)))

        chapter_state = self._chapter_state_context()
        if chapter_state:
            sections.append(("Chapter State Index", chapter_state))

        failure_fold = self._failure_fold_context()
        if failure_fold:
            sections.append(("Failure Fold", failure_fold))

        pool = self._get_short_term_memory()
        if pool:
            try:
                short_term = pool.compact_prompt(max_events=self._runtime_board_max_events())
                if short_term:
                    sections.append(("Short-Term State", self._strip_known_board(short_term)))
            except Exception as exc:
                logger.debug(f"[RuntimeContext] short-term board skipped: {exc}")

        task_board = build_context_state_board(turns, max_events=self._runtime_board_max_events())
        if task_board:
            sections.append(("Task Checkpoint", self._strip_known_board(task_board)))

        if not sections:
            return ""

        lines = [
            "[System: Runtime Context Board]",
            f"reason: {reason or 'normal'}",
            "This bounded board is the authoritative runtime context for this turn. Prefer it over stale conversation summaries.",
            "User-facing replies must stay in Simplified Chinese unless the user explicitly asks for English.",
        ]
        max_chars = self._runtime_board_max_chars()
        remaining = max_chars - len("\n".join(lines)) - 20
        for idx, (title, body) in enumerate(sections):
            if remaining <= 80:
                break
            remaining_sections = max(1, len(sections) - idx)
            budget = max(400, remaining // remaining_sections)
            clipped = self._clip_runtime_section(body, budget)
            lines.append(f"\n## {title}\n{clipped}")
            remaining = max_chars - len("\n".join(lines))
        return "\n".join(lines)[:max_chars]

    def _runtime_board_max_chars(self) -> int:
        try:
            from config import conf
            value = int(conf().get("agent_runtime_board_max_chars", 6000) or 6000)
            return max(2000, min(20000, value))
        except Exception:
            return 6000

    def _runtime_board_max_events(self) -> int:
        try:
            from config import conf
            value = int(conf().get("agent_runtime_board_max_events", 12) or 12)
            return max(4, min(40, value))
        except Exception:
            return 12

    @staticmethod
    def _clip_runtime_section(text: str, max_chars: int) -> str:
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        head = int(max_chars * 0.75)
        tail = max_chars - head - 80
        return (
            text[:head].rstrip()
            + f"\n... [runtime section clipped: {len(text)} -> {max_chars} chars] ...\n"
            + (text[-tail:].lstrip() if tail > 0 else "")
        )

    @staticmethod
    def _strip_known_board(text: str) -> str:
        for marker in (
            "[System: Tool routing policy]",
            "[System: Short-term working memory]",
            "[System: Current task state board]",
            "[System: Runtime Context Board]",
            "[System: Context Compression Handoff]",
        ):
            text = text.replace(marker, "").strip()
        return text

    @staticmethod
    def _strip_runtime_context_board(text: str) -> str:
        markers = (
            "[System: Runtime Context Board]",
            "[System: Tool routing policy]",
            "[System: Short-term working memory]",
            "[System: Current task state board]",
            "[System: Context Compression Handoff]",
        )
        if not any(marker in text for marker in markers):
            return text
        parts = text.split("\n\n---\n\n", 1)
        if len(parts) == 2 and any(marker in parts[0] for marker in markers):
            return parts[1].strip()
        return text

    @staticmethod
    def _strip_context_state_board(text: str) -> str:
        marker = "[System: Current task state board]"
        if marker not in text:
            return text
        parts = text.split("\n\n---\n\n", 1)
        if len(parts) == 2 and marker in parts[0]:
            return parts[1].strip()
        before, _, after = text.partition(marker)
        if "\n\n---\n\n" in after:
            return (before + after.split("\n\n---\n\n", 1)[1]).strip()
        return before.strip()

    def _chapter_state_context(self) -> str:
        """Return the compact per-chapter state for the active textbook task."""
        target = self._active_textbook_target()
        book_id = target.get("book_id")
        chapter_num = target.get("chapter_num")
        if not book_id or not chapter_num:
            return ""
        try:
            from bridge.textbook_bridge import get_bridge
            bridge = get_bridge()
            book_dir = bridge.get_book_dir(book_id)
            path = os.path.join(book_dir, "state", "chapter_index.json")
            if not os.path.exists(path):
                return (
                    f"Chapter State Index: book={book_id} chapter={chapter_num}. "
                    "No chapter_index.json exists yet; use textbook_chapter status/validate_structure before editing."
                )
            with open(path, "r", encoding="utf-8") as f:
                index = json.load(f)
            entry = (index.get("chapters") or {}).get(str(chapter_num)) or {}
            if not entry:
                return (
                    f"Chapter State Index: book={book_id} chapter={chapter_num}. "
                    "No entry for this chapter yet; use textbook_chapter status/validate_structure before editing."
                )
            compact = {
                "book_id": entry.get("book_id", book_id),
                "chapter_num": entry.get("chapter_num", chapter_num),
                "title": entry.get("title", ""),
                "status": entry.get("status", ""),
                "content_hash": entry.get("content_hash", ""),
                "chars": entry.get("chars", 0),
                "headings": (entry.get("headings") or [])[:30],
                "fatal_issues": entry.get("fatal_issues") or [],
                "warnings": entry.get("warnings") or [],
                "last_operation": entry.get("last_operation", ""),
                "last_issue": entry.get("last_issue", ""),
                "updated_at": entry.get("updated_at", ""),
            }
            return json.dumps(compact, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.debug(f"[RuntimeContext] chapter state skipped: {exc}")
            return ""

    def _active_textbook_target(self) -> Dict[str, Any]:
        """Infer the current textbook/chapter target from recent messages."""
        book_id = ""
        chapter_num = 0
        for msg in reversed(self.messages[-20:]):
            try:
                blob = json.dumps(msg, ensure_ascii=False)
            except Exception:
                blob = str(msg)
            if not book_id:
                match = re.search(r"\b((?:tb|textbook)_[A-Za-z0-9_]+)\b", blob)
                if match:
                    book_id = match.group(1)
            if not chapter_num:
                match = re.search(r'\\?"chapter_num\\?"\s*:\s*(\d+)', blob)
                if not match:
                    match = re.search(r"第\s*(\d+)\s*章", blob)
                if not match:
                    match = re.search(r"\b(?:chapter|chap|ch)\s*[:#-]?\s*(\d+)\b", blob, re.IGNORECASE)
                if not match and book_id:
                    tail = blob[blob.find(book_id) + len(book_id): blob.find(book_id) + len(book_id) + 120]
                    match = re.search(r"\b(\d{1,3})\b", tail)
                if match:
                    chapter_num = int(match.group(1))
            if book_id and chapter_num:
                break
        return {"book_id": book_id, "chapter_num": chapter_num}

    def _clear_session_db(self):
        """
        Clear the current session's persisted messages from SQLite DB.

        This prevents dirty data (broken tool_use/tool_result pairs) from being
        reloaded on the next request or after a restart.
        """
        try:
            session_id = getattr(self.agent, '_current_session_id', None)
            if not session_id:
                return
            from agent.memory import get_conversation_store
            store = get_conversation_store()
            store.clear_session(session_id)
            logger.info(f"🗑️ Cleared dirty session data from DB: {session_id}")
        except Exception as e:
            logger.warning(f"Failed to clear session DB: {e}")

    def context_diagnostics(self) -> Dict[str, Any]:
        """Return lightweight diagnostics for the current assembled context."""
        turns = self._identify_complete_turns()
        system_tokens = (
            self.agent._estimate_message_tokens({"role": "system", "content": self.system_prompt})
            if self.agent and self.system_prompt
            else 0
        )
        message_tokens = (
            sum(self.agent._estimate_message_tokens(m) for m in self.messages)
            if self.agent
            else 0
        )
        runtime_board_chars = 0
        tool_result_chars = 0
        compressed_blocks = 0
        for msg in self.messages:
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                text = str(block.get("text") or block.get("content") or "")
                if "[System: Runtime Context Board]" in text:
                    runtime_board_chars = len(text.split("\n\n---\n\n", 1)[0])
                if block.get("type") == "tool_result":
                    tool_result_chars += len(str(block.get("content", "")))
                    if "compacted" in str(block.get("content", "")).lower() or "compressed" in str(block.get("content", "")).lower():
                        compressed_blocks += 1
        max_allowed, reserve = self._effective_context_budget()
        last_compression = self.context_compression_history[-1] if self.context_compression_history else {}
        return {
            "system_prompt_chars": len(self.system_prompt or ""),
            "message_count": len(self.messages),
            "turn_count": len(turns),
            "estimated_tokens": system_tokens + message_tokens,
            "max_allowed_tokens": max_allowed,
            "reserve_tokens": reserve,
            "runtime_board_chars": runtime_board_chars,
            "tool_result_chars": tool_result_chars,
            "compressed_blocks": compressed_blocks,
            "memory_bootstrap_loaded": "SYSTEM_MEMORY_BOOTSTRAP.md" in (self.system_prompt or ""),
            "recent_compression_count": self._recent_compression_count(),
            "compression_debounce_active": self._compression_debounce_active(),
            "last_compression_kind": last_compression.get("kind", ""),
            "last_compression_saved_chars": last_compression.get("saved_chars", 0),
        }

    def _emit_context_diagnostics(self, reason: str = "") -> None:
        """Emit context diagnostics without adding anything to the LLM context."""
        try:
            payload = self.context_diagnostics()
            payload["reason"] = reason or "normal"
            self._emit_event("context_diagnostics", payload)
            logger.info(
                "[ContextDiagnostics] reason=%s messages=%s turns=%s tokens~%s/%s "
                "runtime_board_chars=%s tool_result_chars=%s compressed_blocks=%s",
                payload["reason"],
                payload["message_count"],
                payload["turn_count"],
                payload["estimated_tokens"],
                payload["max_allowed_tokens"],
                payload["runtime_board_chars"],
                payload["tool_result_chars"],
                payload["compressed_blocks"],
            )
        except Exception as exc:
            logger.debug(f"[ContextDiagnostics] skipped: {exc}")

    def _prepare_messages(self) -> List[Dict[str, Any]]:
        """
        Prepare messages to send to LLM
        
        Note: For Claude API, system prompt should be passed separately via system parameter,
        not as a message. The AgentLLMModel will handle this.
        """
        # Don't add system message here - it will be handled separately by the LLM adapter
        return self.messages
