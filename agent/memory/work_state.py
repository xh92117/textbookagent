import json
import os
import time
import threading
import logging

logger = logging.getLogger(__name__)

_WORK_STATE_FILE = ".work_state.json"


class WorkStateManager:
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self._lock = threading.Lock()
        self._cache = {}
        state_path = os.path.join(workspace_root, _WORK_STATE_FILE)
        if os.path.exists(state_path):
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load work state: {e}")
                self._cache = {}

    def _state_path(self):
        return os.path.join(self.workspace_root, _WORK_STATE_FILE)

    def save(self, updates: dict):
        with self._lock:
            self._cache.update(updates)
            self._cache["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            try:
                os.makedirs(self.workspace_root, exist_ok=True)
                with open(self._state_path(), "w", encoding="utf-8") as f:
                    json.dump(self._cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Failed to save work state: {e}")

    def load(self) -> dict:
        with self._lock:
            return dict(self._cache)

    def record_tool_call(self, tool_name: str, args: dict, status: str, result_summary: str = ""):
        entry = {
            "tool": tool_name,
            "status": status,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if tool_name in ("read", "write", "edit") and args.get("path"):
            entry["path"] = args["path"]
        if result_summary:
            entry["result_summary"] = result_summary[:200]
        recent = self._cache.get("recent_tool_calls", [])
        recent.append(entry)
        if len(recent) > 20:
            recent = recent[-20:]
        self.save({"recent_tool_calls": recent})

    def record_pipeline_phase(self, phase: str, status: str, detail: str = ""):
        entry = {
            "phase": phase,
            "status": status,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if detail:
            entry["detail"] = detail[:300]
        phases = self._cache.get("pipeline_phases", [])
        phases.append(entry)
        if len(phases) > 30:
            phases = phases[-30:]
        self.save({"pipeline_phases": phases})

    def set_active_book(self, book_id: str, book_title: str = ""):
        self.save({"active_book_id": book_id, "active_book_title": book_title})

    def get_summary_text(self) -> str:
        state = self.load()
        if not state:
            return ""
        lines = []
        book_id = state.get("active_book_id", "")
        book_title = state.get("active_book_title", "")
        if book_id:
            lines.append(f"当前教材: {book_title or book_id} (ID: {book_id})")
        phases = state.get("pipeline_phases", [])
        if phases:
            completed = [p for p in phases if p.get("status") == "completed"]
            running = [p for p in phases if p.get("status") == "running"]
            if completed:
                names = [p["phase"] for p in completed[-10:]]
                lines.append(f"已完成阶段: {', '.join(names)}")
            if running:
                names = [p["phase"] for p in running]
                lines.append(f"进行中阶段: {', '.join(names)}")
        recent = state.get("recent_tool_calls", [])
        if recent:
            last5 = recent[-5:]
            summaries = []
            for t in last5:
                s = f"{t.get('tool', '?')}({t.get('path', '')})" if t.get("path") else t.get("tool", "?")
                summaries.append(f"{s}:{t.get('status', '?')}")
            lines.append(f"最近工具调用: {', '.join(summaries)}")
        updated = state.get("updated_at", "")
        if updated:
            lines.append(f"状态更新时间: {updated}")
        return "\n".join(lines)
