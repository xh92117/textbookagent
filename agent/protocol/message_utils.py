"""
Message sanitizer — fix broken tool_use / tool_result pairs.

Provides two public helpers that can be reused across agent_stream.py
and any bot that converts messages to OpenAI format:

1. sanitize_claude_messages(messages)
   Operates on the internal Claude-format message list (in-place).

2. drop_orphaned_tool_results_openai(messages)
   Operates on an already-converted OpenAI-format message list,
   returning a cleaned copy.
"""

from __future__ import annotations

from typing import Dict, List, Set

from common.log import logger

_SYNTH_TOOL_ERR = (
    "Error: Missing tool_result adjacent to tool_use (session repair). "
    "The conversation history was inconsistent; continue from here."
)


def _repair_tool_use_adjacency(messages: List[Dict]) -> int:
    """
    Anthropic requires: after assistant content with tool_use, the next message
    must be user content listing tool_result for every tool_use id (same user msg).

    Valid histories satisfy this at every such assistant; the loop only mutates
    when that condition fails (broken persistence, bad trims, etc.).
    """

    def _synth_block(tid: str) -> Dict:
        return {
            "type": "tool_result",
            "tool_use_id": tid,
            "content": _SYNTH_TOOL_ERR,
            "is_error": True,
        }

    repairs = 0
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") != "assistant":
            i += 1
            continue

        content = msg.get("content", [])
        if not isinstance(content, list):
            i += 1
            continue

        required = [
            b.get("id")
            for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")
        ]
        if not required:
            i += 1
            continue

        req_set = set(required)
        if i + 1 >= len(messages):
            messages.append({
                "role": "user",
                "content": [_synth_block(tid) for tid in required],
            })
            logger.warning(
                "⚠️ Appended synthetic tool_result after trailing assistant tool_use"
            )
            repairs += 1
            break

        nxt = messages[i + 1]
        if nxt.get("role") != "user":
            messages.insert(
                i + 1,
                {"role": "user", "content": [_synth_block(tid) for tid in required]},
            )
            logger.warning(
                "⚠️ Inserted synthetic tool_result user after tool_use "
                f"(next role={nxt.get('role')!r})"
            )
            repairs += 1
            i += 2
            continue

        nc = nxt.get("content", [])
        if not isinstance(nc, list):
            messages.insert(
                i + 1,
                {"role": "user", "content": [_synth_block(tid) for tid in required]},
            )
            repairs += 1
            i += 2
            continue

        present = {
            b.get("tool_use_id")
            for b in nc
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id")
        }
        if req_set <= present:
            i += 1
            continue

        missing = [tid for tid in required if tid not in present]
        nxt["content"] = [_synth_block(tid) for tid in missing] + nc
        logger.warning(
            "⚠️ Prepended synthetic tool_result for Anthropic adjacency "
            f"(missing_ids={missing})"
        )
        repairs += len(missing)
        i += 1

    return repairs


# ------------------------------------------------------------------ #
# Claude-format sanitizer (used by agent_stream)
# ------------------------------------------------------------------ #

def sanitize_claude_messages(messages: List[Dict]) -> int:
    """
    Validate and fix a Claude-format message list **in-place**.

    Fixes handled:
    - Anthropic adjacency: assistant tool_use must be immediately followed by
      user message(s) containing matching tool_result blocks
    - Leading orphaned tool_result user messages
    - Mid-list tool_result blocks whose tool_use_id has no matching
      tool_use in any preceding assistant message

    Returns: number of removals plus adjacency repair operations (inserts/prepends).
    """
    if not messages:
        return 0

    removed = 0

    # 1. Adjacency repair (Anthropic: tool_result must be in the next user message)
    adj_repairs = _repair_tool_use_adjacency(messages)

    # 2. Remove leading orphaned tool_result user messages
    while messages:
        first = messages[0]
        if first.get("role") != "user":
            break
        content = first.get("content", [])
        if isinstance(content, list) and _has_block_type(content, "tool_result") \
                and not _has_block_type(content, "text"):
            logger.warning("⚠️ Removing leading orphaned tool_result user message")
            messages.pop(0)
            removed += 1
        else:
            break

    # 3. Iteratively remove unmatched tool_use / tool_result until stable.
    #    Removing one broken message can orphan others (e.g. an assistant msg
    #    with both matched and unmatched tool_use — deleting it orphans the
    #    previously-matched tool_result).  Loop until clean.
    for _ in range(5):
        use_ids: Set[str] = set()
        result_ids: Set[str] = set()
        for msg in messages:
            for block in (msg.get("content") or []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("id"):
                    use_ids.add(block["id"])
                elif block.get("type") == "tool_result" and block.get("tool_use_id"):
                    result_ids.add(block["tool_use_id"])

        bad_use = use_ids - result_ids
        bad_result = result_ids - use_ids
        if not bad_use and not bad_result:
            break

        pass_removed = 0
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")
            content = msg.get("content", [])
            if not isinstance(content, list):
                i += 1
                continue

            if role == "assistant" and bad_use and any(
                isinstance(b, dict) and b.get("type") == "tool_use"
                and b.get("id") in bad_use for b in content
            ):
                logger.warning(f"⚠️ Removing assistant msg with unmatched tool_use")
                messages.pop(i)
                pass_removed += 1
                continue

            if role == "user" and bad_result and _has_block_type(content, "tool_result"):
                has_bad = any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    and b.get("tool_use_id") in bad_result for b in content
                )
                if has_bad:
                    if not _has_block_type(content, "text"):
                        logger.warning(f"⚠️ Removing user msg with unmatched tool_result")
                        messages.pop(i)
                        pass_removed += 1
                        continue
                    else:
                        before = len(content)
                        msg["content"] = [
                            b for b in content
                            if not (isinstance(b, dict) and b.get("type") == "tool_result"
                                    and b.get("tool_use_id") in bad_result)
                        ]
                        pass_removed += before - len(msg["content"])

            i += 1

        removed += pass_removed
        if pass_removed == 0:
            break

    # 4. Removals above can break adjacency; re-run repair only if something was removed.
    if removed:
        adj_repairs += _repair_tool_use_adjacency(messages)

    if removed:
        logger.info(f"🔧 Message validation: removed {removed} broken message(s)")
    if adj_repairs:
        logger.info(f"🔧 Message validation: adjacency repairs={adj_repairs}")
    return removed + adj_repairs


# ------------------------------------------------------------------ #
# OpenAI-format sanitizer (used by minimax_bot, openai_compatible_bot)
# ------------------------------------------------------------------ #

def drop_orphaned_tool_results_openai(messages: List[Dict]) -> List[Dict]:
    """
    Return a copy of *messages* (OpenAI format) with any ``role=tool``
    messages removed if their ``tool_call_id`` does not match a
    ``tool_calls[].id`` in a preceding assistant message.
    """
    known_ids: Set[str] = set()
    cleaned: List[Dict] = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                if tc_id:
                    known_ids.add(tc_id)

        if msg.get("role") == "tool":
            ref_id = msg.get("tool_call_id", "")
            if ref_id and ref_id not in known_ids:
                logger.warning(
                    f"[MessageSanitizer] Dropping orphaned tool result "
                    f"(tool_call_id={ref_id} not in known ids)"
                )
                continue
        cleaned.append(msg)
    return cleaned


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _has_block_type(content: list, block_type: str) -> bool:
    return any(
        isinstance(b, dict) and b.get("type") == block_type
        for b in content
    )


def _extract_text_from_content(content) -> str:
    """Extract plain text from a message content field (str or list of blocks)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p).strip()
    return ""


def compress_turn_to_text_only(turn: Dict) -> Dict:
    """
    Compress a full turn (with tool_use/tool_result chains) into a lightweight
    text-only turn that keeps only the first user text and the last assistant text.

    This preserves the conversational context (what the user asked and what the
    agent concluded) while stripping out the bulky intermediate tool interactions.

    Returns a new turn dict with a ``messages`` list; the original is not mutated.
    """
    user_text = ""
    last_assistant_text = ""

    for msg in turn["messages"]:
        role = msg.get("role")
        content = msg.get("content", [])

        if role == "user":
            if isinstance(content, list) and _has_block_type(content, "tool_result"):
                continue
            if not user_text:
                user_text = _extract_text_from_content(content)

        elif role == "assistant":
            text = _extract_text_from_content(content)
            if text:
                last_assistant_text = text

    compressed_messages = []
    if user_text:
        compressed_messages.append({
            "role": "user",
            "content": [{"type": "text", "text": user_text}]
        })
    if last_assistant_text:
        compressed_messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": last_assistant_text}]
        })

    return {"messages": compressed_messages}


def summarize_tool_result_content(content: str, tool_name: str = "", tool_args: dict = None) -> str:
    """
    Generate a smart summary for a tool result, preserving key information
    while dramatically reducing token count.

    Strategy:
    - For file reads: keep filename, line count, structure (headings), drop body
    - For bash/directory listings: keep full output (usually short)
    - For search results: keep file paths and match counts
    - For other tools: keep first 500 chars + truncation notice
    """
    if not content or len(content) < 300:
        return content

    tool_args = tool_args or {}
    summary_parts = []

    if tool_name in ("read", "file_read"):
        path = tool_args.get("path", "")
        if path:
            summary_parts.append(f"[文件: {path}]")

        lines = content.split("\n")
        total_lines = len(lines)
        summary_parts.append(f"[共{total_lines}行]")

        headings = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("##") or stripped.startswith("###"):
                headings.append(stripped)
            elif stripped.startswith("- ") and len(stripped) < 80:
                if len(headings) < 30:
                    headings.append(stripped)

        if headings:
            summary_parts.append("[结构概要]:")
            for h in headings[:20]:
                summary_parts.append("  " + h)
            if len(headings) > 20:
                summary_parts.append(f"  ... 共{len(headings)}个条目")

        summary_parts.append(f"[原文{len(content)}字符已压缩]")
        return "\n".join(summary_parts)

    elif tool_name in ("bash", "shell", "command"):
        if len(content) < 1000:
            return content
        lines = content.split("\n")
        if len(lines) <= 20:
            return content
        kept = lines[:10] + [f"... (省略{len(lines) - 15}行) ..."] + lines[-5:]
        return "\n".join(kept)

    elif tool_name in ("search", "grep", "glob"):
        if len(content) < 2000:
            return content
        lines = content.split("\n")
        kept = lines[:30]
        if len(lines) > 30:
            kept.append(f"... (共{len(lines)}个结果，已省略{len(lines) - 30}个)")
        return "\n".join(kept)

    else:
        if len(content) <= 800:
            return content
        return content[:500] + f"\n... [原文{len(content)}字符已压缩]"


def progressive_compress_messages(messages: list, current_turn: int) -> list:
    """
    Apply progressive compression to message history based on age.

    Level 1 (recent 2 turns): Keep full, no compression
    Level 2 (3-5 turns ago): Replace tool results with smart summaries
    Level 3 (6+ turns ago): Compress turns to text-only summaries

    This preserves key memory while dramatically reducing token count.
    """
    if not messages or current_turn < 3:
        return messages

    result = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role", "")

        if role == "user":
            content = msg.get("content", [])
            if isinstance(content, list):
                has_tool_result = any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                )
                if has_tool_result:
                    tool_result_blocks = []
                    other_blocks = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            tool_result_blocks.append(block)
                        else:
                            other_blocks.append(block)

                    turn_age = current_turn - _estimate_turn_number(messages, i)
                    compressed_blocks = list(other_blocks)

                    for tr in tool_result_blocks:
                        tr_content = tr.get("content", "")
                        tool_use_id = tr.get("tool_use_id", "")
                        tool_name, tool_args = _find_tool_info(messages, tool_use_id)

                        if turn_age >= 6:
                            summary = summarize_tool_result_content(tr_content, tool_name, tool_args)
                            if len(summary) < len(tr_content) * 0.5:
                                compressed_blocks.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_use_id,
                                    "content": summary,
                                })
                            else:
                                compressed_blocks.append(tr)
                        elif turn_age >= 3:
                            if isinstance(tr_content, str) and len(tr_content) > 1500:
                                summary = summarize_tool_result_content(tr_content, tool_name, tool_args)
                                compressed_blocks.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_use_id,
                                    "content": summary,
                                })
                            else:
                                compressed_blocks.append(tr)
                        else:
                            compressed_blocks.append(tr)

                    result.append({"role": "user", "content": compressed_blocks})
                else:
                    result.append(msg)
            else:
                result.append(msg)

        elif role == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                turn_age = current_turn - _estimate_turn_number(messages, i)
                if turn_age >= 6:
                    text_parts = []
                    tool_use_parts = []
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block)
                            elif block.get("type") == "tool_use":
                                tool_name = block.get("name", "")
                                tool_input = block.get("input", {})
                                desc = _tool_call_description(tool_name, tool_input)
                                tool_use_parts.append({
                                    "type": "text",
                                    "text": f"[调用工具: {desc}]"
                                })
                        else:
                            text_parts.append({"type": "text", "text": str(block)})

                    result.append({"role": "assistant", "content": text_parts + tool_use_parts})
                else:
                    result.append(msg)
            else:
                result.append(msg)
        else:
            result.append(msg)

        i += 1

    return result


def _estimate_turn_number(messages: list, msg_index: int) -> int:
    turn = 0
    for j in range(msg_index + 1):
        if messages[j].get("role") == "user":
            content = messages[j].get("content", [])
            if isinstance(content, list):
                has_tool_result = any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                )
                if has_tool_result:
                    turn += 1
            elif isinstance(content, str) and content.strip():
                turn += 1
    return max(turn, 1)


def _find_tool_info(messages: list, tool_use_id: str) -> tuple:
    for msg in messages:
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == tool_use_id:
                        return block.get("name", ""), block.get("input", {})
    return "", {}


def _tool_call_description(tool_name: str, tool_input: dict) -> str:
    if tool_name in ("read", "file_read"):
        return f"读取文件 {tool_input.get('path', '')}"
    elif tool_name in ("bash", "shell"):
        cmd = tool_input.get("command", "")
        if len(cmd) > 60:
            cmd = cmd[:60] + "..."
        return f"执行命令: {cmd}"
    elif tool_name in ("write", "file_write"):
        return f"写入文件 {tool_input.get('path', '')}"
    elif tool_name == "search":
        return f"搜索: {tool_input.get('query', '')}"
    else:
        args_str = str(tool_input)
        if len(args_str) > 80:
            args_str = args_str[:80] + "..."
        return f"{tool_name}({args_str})"
