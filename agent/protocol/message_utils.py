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

import json
import re
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
    tool_ledger = _build_tool_progress_ledger(turn)

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
    elif tool_ledger:
        compressed_messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": tool_ledger}]
        })

    return {"messages": compressed_messages}


def build_context_state_board(turns: List[Dict], max_events: int = 24) -> str:
    """
    Build a compact state board for long-running agent tasks.

    Unlike a conversational summary, this is operational memory: what has
    already been attempted, which sources/files are available, which failures
    should not be repeated, and what the agent should do next.
    """
    if not turns:
        return ""

    # Keep the board local to the active work segment. Old session history is
    # still available through normal messages/memory tools, but putting too much
    # old progress into this "authority" board makes the agent revive previous
    # chapter tasks when the user has switched goals.
    turns = turns[-8:]

    latest_user = ""
    assistant_notes = []
    events = []
    failed = []
    saved = []
    read_paths = []
    write_paths = []
    checkpoint = {
        "active_goal": "",
        "active_book_id": "",
        "active_chapter": "",
        "current_phase": "understand_request",
        "completed": [],
        "failed": [],
        "available_files": [],
        "next_step_policy": "continue_next_unfinished_action",
    }

    for turn in turns:
        tool_uses = {}
        for msg in turn.get("messages", []):
            role = msg.get("role")
            content = msg.get("content", [])
            if role == "user":
                if isinstance(content, list):
                    has_tool_result = any(
                        isinstance(b, dict) and b.get("type") == "tool_result"
                        for b in content
                    )
                    if not has_tool_result:
                        text = _extract_text_from_content(content)
                        if text:
                            latest_user = text[:500]
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_result":
                            continue
                        info = tool_uses.get(block.get("tool_use_id", ""), {})
                        event = _summarize_tool_event(info.get("name", ""), info.get("input", {}), block)
                        if not event:
                            continue
                        events.append(event)
                        _update_checkpoint_from_event(checkpoint, info.get("name", ""), info.get("input", {}), event)
                        if event.startswith("FAILED"):
                            failed.append(event)
                        if event.startswith("SAVED"):
                            saved.append(event)
                        if event.startswith("READ"):
                            read_paths.append(event)
                        if event.startswith("WROTE"):
                            write_paths.append(event)
                elif isinstance(content, str) and content.strip():
                    latest_user = content.strip()[:500]
            elif role == "assistant":
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_uses[block.get("id", "")] = {
                                "name": block.get("name", ""),
                                "input": block.get("input", {}) if isinstance(block.get("input"), dict) else {},
                            }
                text = _extract_text_from_content(content)
                if text:
                    assistant_notes.append(_compact_line(text, 260))

    if not any((latest_user, events, assistant_notes)):
        return ""

    lines = [
        "[System: Current task state board]",
        "This compact state survives context compression and is the authority for task progress.",
        "Do not restart completed planning/search/reading/review steps. Continue from the next unfinished action.",
    ]
    if latest_user:
        checkpoint["active_goal"] = _compact_line(latest_user, 280)
        lines.append(f"Current user goal: {_compact_line(latest_user, 500)}")

    lines.append("Structured task checkpoint (higher priority than conversation summary):")
    lines.append("```json")
    lines.append(json.dumps(_normalize_task_checkpoint(checkpoint), ensure_ascii=False, indent=2))
    lines.append("```")

    if assistant_notes:
        lines.append("Recent decisions/progress:")
        for note in _dedupe_keep_order(assistant_notes[-6:])[-4:]:
            lines.append(f"- {note}")

    if read_paths:
        lines.append("Already read/available files:")
        for item in _dedupe_keep_order(read_paths)[-10:]:
            lines.append(f"- {item}")

    if saved:
        lines.append("Knowledge/source saves:")
        for item in _dedupe_keep_order(saved)[-8:]:
            lines.append(f"- {item}")

    if failed:
        lines.append("Failures to avoid repeating:")
        for item in _dedupe_keep_order(failed)[-10:]:
            lines.append(f"- {item}")

    other_events = [
        e for e in events
        if not (e.startswith("FAILED") or e.startswith("SAVED") or e.startswith("READ"))
    ]
    if other_events:
        lines.append("Other tool progress:")
        for item in _dedupe_keep_order(other_events)[-max_events:]:
            lines.append(f"- {item}")

    if write_paths:
        lines.append("Written outputs:")
        for item in _dedupe_keep_order(write_paths)[-8:]:
            lines.append(f"- {item}")

    lines.append("Loop guard: if an action appears under read/saved/written/progress/failures, treat it as already attempted unless the user explicitly asks to redo it.")
    lines.append("Next-step rule: if enough chapter evidence has already been gathered, write/save the chapter instead of searching or rereading skills again.")
    lines.append("Textbook state-machine rule: never regenerate outline/review/search when the state board shows chapter writing has started; continue the current chapter's next unfinished section or validate/save it.")
    lines.append("Chapter writing rule: use textbook_chapter for chapter Markdown. Do not use bash/PowerShell to append Chinese textbook text.")
    lines.append("Checkpoint rule: if the structured checkpoint marks an action as completed, do not redo it unless the user explicitly asks.")
    return "\n".join(lines)


def _update_checkpoint_from_event(checkpoint: Dict, tool_name: str, tool_args: dict, event: str) -> None:
    tool_args = tool_args or {}
    if event.startswith("FAILED"):
        checkpoint["failed"].append(_compact_line(event, 180))

    if tool_name in ("textbook_chapter", "textbook_image"):
        book_id = str(tool_args.get("book_id", "") or "")
        chapter = str(tool_args.get("chapter_num", "") or "")
        if book_id:
            checkpoint["active_book_id"] = book_id
        if chapter:
            checkpoint["active_chapter"] = chapter
        if tool_name == "textbook_chapter":
            action = str(tool_args.get("action", "") or "")
            if action:
                checkpoint["current_phase"] = "chapter_writing" if action != "status" else "chapter_status_check"
                checkpoint["completed"].append(f"textbook_chapter:{action}:ch{chapter}")
        else:
            figure = str(tool_args.get("figure_num", "") or "")
            checkpoint["current_phase"] = "image_generation"
            checkpoint["completed"].append(f"textbook_image:ch{chapter}:fig{figure}")

    if tool_name in ("read", "file_read"):
        path = str(tool_args.get("path", "") or "")
        if path:
            checkpoint["available_files"].append(path)
            checkpoint["completed"].append(f"read:{path}")

    if tool_name == "knowledge_capture":
        title = str(tool_args.get("title", "") or tool_args.get("url", "") or "")
        checkpoint["current_phase"] = "knowledge_capture"
        if event.startswith("SAVED"):
            checkpoint["completed"].append(f"knowledge_capture:{_compact_line(title, 80)}")

    if tool_name == "web_fetch":
        checkpoint["current_phase"] = "web_research"
        url = str(tool_args.get("url", "") or "")
        if url and not event.startswith("FAILED"):
            checkpoint["completed"].append(f"web_fetch:{_compact_line(url, 100)}")


def _normalize_task_checkpoint(checkpoint: Dict) -> Dict:
    out = dict(checkpoint)
    for key, limit in (("completed", 12), ("failed", 8), ("available_files", 10)):
        items = _dedupe_keep_order([str(x) for x in out.get(key, []) if x])
        out[key] = items[-limit:]

    if out.get("active_chapter"):
        out["current_target"] = f"book={out.get('active_book_id') or '?'} chapter={out['active_chapter']}"
    else:
        out["current_target"] = f"book={out.get('active_book_id') or '?'}"
    return out


def _summarize_tool_event(tool_name: str, tool_args: dict, block: Dict) -> str:
    result = str(block.get("content", "") or "")
    is_failed = bool(block.get("is_error")) or result.lstrip().lower().startswith("error:")
    first = _compact_line(result.splitlines()[0] if result.splitlines() else result, 220)

    if tool_name == "web_fetch":
        url = tool_args.get("url", "")
        title = _extract_title_from_tool_result(result) or url
        if is_failed:
            return f"FAILED web_fetch: {_compact_line(first, 180)} | {url}"
        return f"FETCHED web_fetch: {_compact_line(title, 180)} | {url}"

    if tool_name == "knowledge_capture":
        url = tool_args.get("url", "")
        title = tool_args.get("title", "") or url
        low = result.lower()
        if '"useful": true' in low or "'useful': true" in low:
            return f"SAVED knowledge: {_compact_line(title, 160)} | {url}"
        return f"FAILED knowledge_capture: {_compact_line(first, 180)} | {url}"

    if tool_name in ("read", "file_read"):
        path = tool_args.get("path", "")
        if is_failed:
            return f"FAILED read: {_compact_line(first, 180)} | {path}"
        title = _extract_title_from_tool_result(result) or _extract_json_content_title(result) or path
        return f"READ file: {_compact_line(title, 180)} | {path}"

    if tool_name in ("write", "file_write"):
        path = tool_args.get("path", "")
        return f"WROTE file: {path or _compact_line(first, 180)}"

    if tool_name == "textbook_chapter":
        action = tool_args.get("action", "")
        book_id = tool_args.get("book_id", "")
        chapter = tool_args.get("chapter_num", "")
        heading = tool_args.get("heading", "")
        if is_failed:
            return f"FAILED textbook_chapter: {action} ch{chapter} {heading} | {_compact_line(first, 140)}"
        return f"WROTE textbook_chapter: {action} book={book_id} ch={chapter} {heading}"

    if tool_name == "textbook_image":
        book_id = tool_args.get("book_id", "")
        chapter = tool_args.get("chapter_num", "")
        figure = tool_args.get("figure_num", "")
        title = tool_args.get("title", "")
        if is_failed:
            return f"FAILED textbook_image: book={book_id} ch={chapter} fig={figure} | {_compact_line(first, 140)}"
        return f"WROTE textbook_image: book={book_id} ch={chapter} fig={figure} {title}"

    if tool_name in ("bash", "shell", "command"):
        command = tool_args.get("command", "")
        if is_failed or '"exit_code": 1' in result or '"exit_code": 255' in result:
            return f"FAILED bash: {_compact_line(first, 180)} | {_compact_line(command, 180)}"
        return f"RAN bash: {_compact_line(command, 180)}"

    if tool_name:
        status = "FAILED" if is_failed else "DONE"
        return f"{status} {tool_name}: {_compact_line(first, 180)}"
    return ""


def _extract_json_content_title(content: str) -> str:
    try:
        data = json.loads(content)
    except Exception:
        return ""
    if isinstance(data, dict):
        text = data.get("content") or data.get("output") or ""
        if isinstance(text, str):
            for line in text.splitlines()[:8]:
                stripped = line.strip()
                if stripped.startswith("#"):
                    return stripped.lstrip("#").strip()
    return ""


def _compact_line(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _build_tool_progress_ledger(turn: Dict) -> str:
    """Preserve task progress when a tool-heavy turn is compressed.

    Web research and knowledge-capture turns can have little assistant prose but
    lots of tool results. If compression drops those results entirely, the model
    may restart from the original task. Keep a compact ledger of completed
    searches/fetches/captures instead.
    """
    tool_uses = {}
    lines = []
    for msg in turn.get("messages", []):
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        if msg.get("role") == "assistant":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_uses[block.get("id", "")] = {
                        "name": block.get("name", ""),
                        "input": block.get("input", {}) if isinstance(block.get("input"), dict) else {},
                    }
        elif msg.get("role") == "user":
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                info = tool_uses.get(block.get("tool_use_id", ""), {})
                tool_name = info.get("name", "")
                tool_args = info.get("input", {})
                result = block.get("content", "")
                if tool_name == "web_fetch":
                    url = tool_args.get("url", "")
                    status = "failed" if block.get("is_error") or str(result).lstrip().lower().startswith("error:") else "fetched"
                    title = _extract_title_from_tool_result(str(result))
                    lines.append(f"- web_fetch {status}: {title or url} | {url}")
                elif tool_name == "knowledge_capture":
                    url = tool_args.get("url", "")
                    status = "saved" if not block.get("is_error") and '"useful": true' in str(result).lower() else "skipped/failed"
                    lines.append(f"- knowledge_capture {status}: {tool_args.get('title', '') or url} | {url}")
    if not lines:
        return ""
    return (
        "[System: compressed tool progress ledger]\n"
        "The task has already made the following web-research/knowledge-capture attempts. "
        "Do not restart from the original search plan; continue from unfinished items and avoid repeating failed engines.\n"
        + "\n".join(lines[:30])
        + (f"\n... {len(lines) - 30} more tool events omitted" if len(lines) > 30 else "")
    )


def _extract_title_from_tool_result(content: str) -> str:
    for line in (content or "").splitlines()[:8]:
        if line.startswith("Title:"):
            return line.split(":", 1)[1].strip()[:120]
    return ""


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
    if not content:
        return content

    tool_args = tool_args or {}
    summary_parts = []

    if tool_name == "web_fetch":
        url = (tool_args or {}).get("url", "")
        title = _extract_title_from_tool_result(content)
        if content.lstrip().lower().startswith("error:"):
            return f"[web_fetch failed]\nURL: {url}\n{content.splitlines()[0][:300]}"
        if len(content) < 300:
            return content
        lines = [f"[web_fetch summary]", f"URL: {url}"]
        if title:
            lines.append(f"Title: {title}")
        text_lines = [line.strip() for line in content.splitlines() if line.strip()]
        useful = []
        for line in text_lines:
            low = line.lower()
            if line.startswith("Title:") or line == "Content:":
                continue
            if any(marker in low for marker in ("http://", "https://", "abstract", "introduction", "summary", "framework", "architecture", "survey", "bim", "rag", "agent")):
                useful.append(line[:240])
            if len(useful) >= 8:
                break
        if useful:
            lines.append("Key visible snippets:")
            lines.extend(f"- {item}" for item in useful)
        lines.append(f"[original web_fetch result compressed from {len(content)} chars]")
        return "\n".join(lines)

    if tool_name == "knowledge_capture":
        url = (tool_args or {}).get("url", "")
        title = (tool_args or {}).get("title", "")
        first = content.splitlines()[0][:300] if content else ""
        return f"[knowledge_capture summary]\nTitle: {title}\nURL: {url}\nResult: {first}"

    if len(content) < 300:
        return content

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


def compact_current_tool_result_content(
    content: str,
    tool_name: str = "",
    tool_args: dict = None,
    status: str = "",
    max_chars: int = 16000,
    tool_budget_chars: dict = None,
) -> str:
    """Compact a just-produced tool result before it enters model context.

    The UI can still receive the full tool output through streaming events; this
    only reduces the tool_result block stored in the LLM message history.
    """
    if not isinstance(content, str):
        content = str(content)
    if not content:
        return content
    tool_args = tool_args or {}
    tool_budget_chars = tool_budget_chars or {}
    if tool_name in tool_budget_chars:
        max_chars = int(tool_budget_chars.get(tool_name) or max_chars or 16000)
    max_chars = max(400, int(max_chars or 16000))

    if len(content) <= max_chars and tool_name not in {"read", "file_read", "web_fetch"}:
        return content

    if tool_name in ("read", "file_read"):
        path = tool_args.get("path") or tool_args.get("file_path") or ""
        lines = content.splitlines()
        headings = []
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                headings.append(f"L{idx}: {stripped[:160]}")
            if len(headings) >= 30:
                break
        head = "\n".join(lines[:40])
        tail = "\n".join(lines[-20:]) if len(lines) > 60 else ""
        parts = [
            "[current read result compacted]",
            f"tool: {tool_name}",
            f"path: {path}",
            f"status: {status}",
            f"original_chars: {len(content)}",
            f"line_count: {len(lines)}",
        ]
        if headings:
            parts.extend(["headings:", *[f"- {h}" for h in headings]])
        parts.extend(["head excerpt:", head[:6000]])
        if tail:
            parts.extend(["tail excerpt:", tail[:3000]])
        return "\n".join(parts)[:max_chars]

    if tool_name == "web_fetch":
        title = _extract_title_from_tool_result(content)
        url = tool_args.get("url", "")
        summary = summarize_tool_result_content(content, tool_name, tool_args)
        parts = [
            "[current web_fetch result compacted]",
            f"url: {url}",
            f"title: {title}",
            f"status: {status}",
            f"original_chars: {len(content)}",
            summary,
        ]
        return "\n".join(part for part in parts if part)[:max_chars]

    if tool_name == "textbook_chapter":
        return _compact_jsonish_result(
            content,
            keep_keys=(
                "status", "message", "path", "file_path", "chapter_path",
                "chapter_num", "book_id", "word_count", "chars", "content_hash",
                "action", "heading", "completed", "backup_path", "structure",
                "chapter_index", "chapter_metadata", "fatal_issues", "warnings",
                "duplicate_headings", "heading_count", "line_count", "ok",
            ),
            header="[current textbook_chapter result compacted]",
            max_chars=max_chars,
        )

    if tool_name in ("bash", "shell", "command"):
        lines = content.splitlines()
        if len(content) <= max_chars and len(lines) <= 120:
            return content
        marker = f"... [output compacted: {len(lines)} lines, {len(content)} chars] ..."
        if max_chars < 3000:
            head_budget = max(120, int(max_chars * 0.38))
            tail_budget = max(120, max_chars - head_budget - len(marker) - 4)
            head = content[:head_budget].rstrip()
            tail = content[-tail_budget:].lstrip()
            return f"{head}\n{marker}\n{tail}"[:max_chars]
        kept = lines[:80] + [marker] + lines[-40:]
        return "\n".join(kept)[:max_chars]

    if len(content) <= max_chars:
        return content
    head = content[: max_chars // 2]
    tail = content[-max_chars // 4 :]
    return (
        f"[current tool result compacted: {tool_name}, status={status}, "
        f"original_chars={len(content)}]\n"
        f"{head}\n\n... [middle omitted] ...\n\n{tail}"
    )[:max_chars]


def _compact_jsonish_result(content: str, keep_keys: tuple, header: str, max_chars: int) -> str:
    try:
        data = json.loads(content)
    except Exception:
        data = None
    if isinstance(data, dict):
        compact = {key: data.get(key) for key in keep_keys if key in data}
        for key, value in data.items():
            if key not in compact and isinstance(value, (int, float, bool)):
                compact[key] = value
        return header + "\n" + json.dumps(compact, ensure_ascii=False, indent=2)
    if len(content) <= max_chars:
        return content
    return header + "\n" + content[:max_chars - len(header) - 20]


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
