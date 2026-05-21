"""
Low-cost realtime memory recording.

This module is intentionally deterministic: every dialogue turn is persisted
without calling an LLM. Periodic LLM distillation can still be handled by
MemoryFlushManager, while this recorder guarantees that a restart can recover
"what happened recently" even if no compression job has run yet.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class RealtimeMemoryRecorder:
    def __init__(
        self,
        workspace_root: str,
        max_session_events: int = 80,
        compact_keep_events: int = 30,
    ):
        self.workspace_root = Path(workspace_root)
        self.memory_dir = self.workspace_root / "memory"
        self.session_dir = self.memory_dir / "sessions"
        self.process_dir = self.memory_dir / "processes"
        self.max_session_events = max_session_events
        self.compact_keep_events = compact_keep_events
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.process_dir.mkdir(parents=True, exist_ok=True)

    def start_process(
        self,
        session_id: str,
        process_id: str,
        user_message: str,
        channel_type: str = "",
    ) -> str:
        safe_id = self._safe_session_id(process_id)
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        payload = {
            "version": "process-memory-v1",
            "session_id": session_id,
            "process_id": process_id,
            "channel_type": channel_type,
            "status": "running",
            "started_at": now,
            "updated_at": now,
            "ended_at": "",
            "user_message": self._clip(user_message or "", 1600),
            "events": [
                {"time": now, "type": "process_start", "summary": self._first_line(user_message or "")}
            ],
            "final_response": "",
            "error": "",
        }
        self._write_process(safe_id, payload)
        self._write_process_index(process_id, safe_id, payload)
        return safe_id

    def update_process(self, process_id: str, event_type: str, summary: str = "", **extra) -> None:
        safe_id = self._safe_session_id(process_id)
        payload = self._read_process(safe_id)
        if not payload or payload.get("status") != "running":
            return
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        event = {
            "time": now,
            "type": event_type,
            "summary": self._clip(summary or "", 500),
        }
        event.update({k: v for k, v in extra.items() if v is not None})
        events = payload.setdefault("events", [])
        events.append(event)
        payload["events"] = events[-80:]
        payload["updated_at"] = now
        self._write_process(safe_id, payload)
        self._write_process_index(process_id, safe_id, payload)

    def finish_process(
        self,
        process_id: str,
        final_response: str = "",
        status: str = "completed",
        error: str = "",
    ) -> None:
        safe_id = self._safe_session_id(process_id)
        payload = self._read_process(safe_id)
        if not payload:
            return
        if payload.get("status") != "running":
            return
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        payload["status"] = status
        payload["ended_at"] = now
        payload["updated_at"] = now
        payload["final_response"] = self._clip(final_response or "", 1600)
        payload["error"] = self._clip(error or "", 800)
        payload.setdefault("events", []).append({
            "time": now,
            "type": "process_end",
            "summary": self._first_line(final_response or error or status),
        })
        self._write_process(safe_id, payload)
        self._write_process_index(process_id, safe_id, payload)

        profile_events = []
        if payload.get("user_message"):
            profile_events.append({"role": "user", "content": payload["user_message"]})
        if final_response:
            profile_events.append({"role": "assistant", "content": final_response})
        if profile_events:
            self._update_user_profile(profile_events, payload.get("session_id", ""))

    def distill_user_profile(
        self,
        process_id: str,
        llm_model: Any = None,
    ) -> bool:
        if llm_model is None:
            return False
        payload = self._read_process(self._safe_session_id(process_id))
        if not payload or payload.get("status") == "running":
            return False
        if not payload.get("user_message") and not payload.get("final_response"):
            return False
        try:
            patch = self._call_llm_profile_update(llm_model, payload)
        except Exception:
            return False
        if not patch:
            return False
        self._merge_user_profile_patch(patch, payload.get("session_id", ""))
        return True

    def distill_user_profile_async(
        self,
        process_id: str,
        llm_model: Any = None,
    ) -> None:
        if llm_model is None:
            return
        threading.Thread(
            target=self.distill_user_profile,
            args=(process_id, llm_model),
            daemon=True,
        ).start()

    def _read_process(self, safe_id: str) -> Dict[str, Any]:
        path = self.process_dir / f"{safe_id}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_process(self, safe_id: str, payload: Dict[str, Any]) -> None:
        json_path = self.process_dir / f"{safe_id}.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            f"# Process Memory: {payload.get('process_id', safe_id)}",
            "",
            f"status: {payload.get('status', '')}",
            f"session_id: {payload.get('session_id', '')}",
            f"started_at: {payload.get('started_at', '')}",
            f"updated_at: {payload.get('updated_at', '')}",
            f"ended_at: {payload.get('ended_at', '')}",
            "",
            "## User Request",
            "",
            payload.get("user_message", ""),
            "",
            "## Events",
            "",
        ]
        for event in payload.get("events", [])[-30:]:
            lines.append(f"- {event.get('time', '')} [{event.get('type', '')}] {event.get('summary', '')}")
        if payload.get("final_response"):
            lines.extend(["", "## Final Response", "", payload.get("final_response", "")])
        if payload.get("error"):
            lines.extend(["", "## Error", "", payload.get("error", "")])
        (self.process_dir / f"{safe_id}_state.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _write_process_index(self, process_id: str, safe_id: str, payload: Dict[str, Any]) -> None:
        index_path = self.memory_dir / "process_index.md"
        index = self._load_process_index(index_path)
        index[process_id] = {
            "state_path": f"memory/processes/{safe_id}_state.md",
            "status": payload.get("status", ""),
            "updated_at": payload.get("updated_at", ""),
            "summary": self._first_line(payload.get("user_message", "")),
        }
        rows = ["# Process Memory Index", ""]
        for pid, item in sorted(index.items(), key=lambda kv: kv[1].get("updated_at", ""), reverse=True):
            rows.append(
                f"- `{pid}` [{item.get('status', '')}] -> `{item['state_path']}` "
                f"({item.get('updated_at', '')}): {item.get('summary', '')}"
            )
        index_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def record_messages(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        channel_type: str = "",
    ) -> None:
        events = []
        for msg in messages or []:
            role = msg.get("role", "")
            text = self._extract_text(msg.get("content", ""))
            if not role or not text:
                continue
            # Tool-result messages are internal and tend to be too noisy for
            # realtime memory; tool summaries remain in persisted conversation.
            if role == "user" and self._has_tool_result(msg.get("content", "")):
                continue
            events.append({
                "role": role,
                "content": self._clip(text, 1200),
                "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            })
        if not events:
            return
        self.record_events(session_id, events, channel_type=channel_type)

    def record_events(
        self,
        session_id: str,
        events: List[Dict[str, Any]],
        channel_type: str = "",
    ) -> None:
        safe_id = self._safe_session_id(session_id)
        path = self.session_dir / f"{safe_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for event in events:
                payload = {
                    "session_id": session_id,
                    "channel_type": channel_type,
                    **event,
                }
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._write_recent_state(session_id, safe_id)
        self._update_user_profile(events, session_id)
        self._compact_session_if_needed(safe_id)

    def _write_recent_state(self, session_id: str, safe_id: str) -> None:
        events = self._read_events(safe_id)[-20:]
        lines = [
            f"# Session Memory: {session_id}",
            "",
            f"updated_at: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}",
            "",
            "## Recent Work",
            "",
        ]
        for event in events:
            role = event.get("role", "")
            label = "User" if role == "user" else "Assistant"
            content = self._first_line(event.get("content", ""))
            if content:
                lines.append(f"- {event.get('time', '')} {label}: {content}")
        (self.session_dir / f"{safe_id}_state.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

        index_path = self.memory_dir / "session_index.md"
        index = self._load_session_index(index_path)
        index[session_id] = {
            "state_path": f"memory/sessions/{safe_id}_state.md",
            "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "last_event": self._first_line(events[-1].get("content", "")) if events else "",
        }
        rows = ["# Session Memory Index", ""]
        for sid, item in sorted(index.items(), key=lambda kv: kv[1].get("updated_at", ""), reverse=True):
            rows.append(f"- `{sid}` -> `{item['state_path']}` ({item['updated_at']}): {item.get('last_event', '')}")
        index_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def _compact_session_if_needed(self, safe_id: str) -> None:
        events = self._read_events(safe_id)
        if len(events) <= self.max_session_events:
            return
        archive = events[:-self.compact_keep_events]
        keep = events[-self.compact_keep_events:]
        summary_path = self.session_dir / f"{safe_id}_summary.md"
        existing = summary_path.read_text(encoding="utf-8") if summary_path.exists() else f"# Session Summary: {safe_id}\n\n"
        summary_lines = [existing.rstrip(), "", f"## Auto Compact {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
        for event in archive[-50:]:
            label = "User" if event.get("role") == "user" else "Assistant"
            summary_lines.append(f"- {label}: {self._first_line(event.get('content', ''))}")
        summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
        raw_path = self.session_dir / f"{safe_id}.jsonl"
        with raw_path.open("w", encoding="utf-8") as f:
            for event in keep:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _update_user_profile(self, events: List[Dict[str, Any]], session_id: str) -> None:
        profile_path = self.memory_dir / "user_profile.json"
        profile = self._load_json(profile_path, default={
            "version": "user-profile-v1",
            "preferences": [],
            "goals": [],
            "projects": [],
            "facts": [],
            "recent_focus": [],
            "updated_at": "",
        })
        for event in events:
            if event.get("role") != "user":
                continue
            text = event.get("content", "")
            self._collect_profile_signal(profile, "preferences", text, [
                r"(?:\u6211\u5e0c\u671b|\u6211\u9700\u8981|\u6211\u60f3\u8981|\u8bf7\u4f60|\u4ee5\u540e)([^\u3002\uff01\uff1f\n]{4,80})",
                r"(?:\u4e0d\u8981|\u4e0d\u9700\u8981|\u907f\u514d)([^\u3002\uff01\uff1f\n]{4,80})",
                r"(?:\u504f\u597d|\u559c\u6b22|\u66f4\u503e\u5411\u4e8e)([^\u3002\uff01\uff1f\n]{4,80})",
            ])
            self._collect_profile_signal(profile, "goals", text, [
                r"(?:\u76ee\u6807\u662f|\u76ee\u7684\u662f|\u6211\u60f3\u5b9e\u73b0)([^\u3002\uff01\uff1f\n]{4,100})",
            ])
            if "\u6559\u6750" in text or "\u667a\u80fd\u4f53" in text or "\u77e5\u8bc6\u5e93" in text:
                self._append_unique(profile, "projects", "\u6559\u6750\u667a\u80fd\u4f53\u5f00\u53d1\u4e0e\u77e5\u8bc6\u5e93\u589e\u5f3a")
            focus = self._first_line(text, 120)
            if focus:
                recent = profile.setdefault("recent_focus", [])
                recent.append({"session_id": session_id, "text": focus, "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")})
                profile["recent_focus"] = recent[-20:]
        profile["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_user_profile_md(profile)

    def _call_llm_profile_update(self, llm_model: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
        from agent.protocol.models import LLMRequest

        event_lines = []
        for event in payload.get("events", [])[-12:]:
            summary = event.get("summary", "")
            if summary:
                event_lines.append(f"- {event.get('type', '')}: {summary}")
        prompt = (
            "Extract durable user memory from this completed process. "
            "Return only a strict JSON object with keys: preferences, goals, projects, facts. "
            "Each value must be an array of short strings. Keep only stable information "
            "that helps future conversations. Omit transient task details, tool logs, errors without reusable lessons, "
            "guesses, secrets, API keys, tokens, and passwords.\n\n"
            f"User request:\n{payload.get('user_message', '')}\n\n"
            f"Process events:\n{chr(10).join(event_lines)}\n\n"
            f"Assistant final response:\n{payload.get('final_response', '')[:1200]}"
        )
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
            stream=False,
            system="You update a compact user profile. Respond with strict JSON only. Do not invent facts.",
        )
        response = llm_model.call(request)
        text = self._extract_response_text(response)
        return self._json_object_from_text(text)

    def _merge_user_profile_patch(self, patch: Dict[str, Any], session_id: str) -> None:
        profile_path = self.memory_dir / "user_profile.json"
        profile = self._load_json(profile_path, default={
            "version": "user-profile-v1",
            "preferences": [],
            "goals": [],
            "projects": [],
            "facts": [],
            "recent_focus": [],
            "updated_at": "",
        })
        for key in ("preferences", "goals", "projects", "facts"):
            values = patch.get(key) or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                value = self._clip(str(value), 160)
                if value:
                    self._append_unique(profile, key, value)
        profile["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_user_profile_md(profile)
    def _write_user_profile_md(self, profile: Dict[str, Any]) -> None:
        lines = ["# User Profile", "", f"updated_at: {profile.get('updated_at', '')}", ""]
        for key, title in (("preferences", "Preferences"), ("goals", "Goals"), ("projects", "Projects"), ("facts", "Facts")):
            lines.extend([f"## {title}", ""])
            values = profile.get(key) or []
            lines.extend(f"- {item}" for item in values[-20:])
            lines.append("")
        lines.extend(["## Recent Focus", ""])
        for item in (profile.get("recent_focus") or [])[-10:]:
            lines.append(f"- {item.get('time', '')} `{item.get('session_id', '')}`: {item.get('text', '')}")
        (self.memory_dir / "user_profile.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    @staticmethod
    def _collect_profile_signal(profile: Dict[str, Any], key: str, text: str, patterns: Iterable[str]) -> None:
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                value = re.sub(r"\s+", " ", match.group(0)).strip()
                if 4 <= len(value) <= 120:
                    RealtimeMemoryRecorder._append_unique(profile, key, value)

    @staticmethod
    def _append_unique(profile: Dict[str, Any], key: str, value: str, limit: int = 50) -> None:
        items = profile.setdefault(key, [])
        if value not in items:
            items.append(value)
        profile[key] = items[-limit:]

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            content = response.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
            choices = response.get("choices") or []
            if choices:
                return choices[0].get("message", {}).get("content", "") or ""
        if hasattr(response, "choices") and response.choices:
            message = getattr(response.choices[0], "message", None)
            return getattr(message, "content", "") or ""
        return ""

    @staticmethod
    def _json_object_from_text(text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(p for p in parts if p).strip()
        return ""

    @staticmethod
    def _has_tool_result(content: Any) -> bool:
        return isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        )

    def _read_events(self, safe_id: str) -> List[Dict[str, Any]]:
        path = self.session_dir / f"{safe_id}.jsonl"
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        return events

    @staticmethod
    def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return dict(default)

    @staticmethod
    def _load_session_index(path: Path) -> Dict[str, Dict[str, str]]:
        if not path.exists():
            return {}
        index = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"- `([^`]+)` -> `([^`]+)` \(([^)]*)\):\s*(.*)", line.strip())
            if match:
                index[match.group(1)] = {
                    "state_path": match.group(2),
                    "updated_at": match.group(3),
                    "last_event": match.group(4),
                }
        return index

    @staticmethod
    def _load_process_index(path: Path) -> Dict[str, Dict[str, str]]:
        if not path.exists():
            return {}
        index = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"- `([^`]+)` \[([^\]]*)\] -> `([^`]+)` \(([^)]*)\):\s*(.*)", line.strip())
            if match:
                index[match.group(1)] = {
                    "status": match.group(2),
                    "state_path": match.group(3),
                    "updated_at": match.group(4),
                    "summary": match.group(5),
                }
        return index

    @staticmethod
    def _safe_session_id(session_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id or "default").strip("._")
        return safe or f"session_{int(time.time())}"

    @staticmethod
    def _clip(text: str, max_chars: int) -> str:
        text = text.strip()
        return text if len(text) <= max_chars else text[:max_chars].rstrip() + "..."

    @staticmethod
    def _first_line(text: str, max_chars: int = 180) -> str:
        for line in (text or "").splitlines():
            line = line.strip()
            if line:
                return RealtimeMemoryRecorder._clip(line, max_chars)
        return ""
