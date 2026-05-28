"""
Memory service for handling memory query operations via cloud protocol.

Provides a unified interface for listing and reading memory files,
callable from the cloud client (LinkAI) or a future web console.

Memory file layout (under workspace_root):
    memory/MEMORY.md        -> type: global
    memory/2026-02-20.md    -> type: daily
"""

import os
import json
import re
import shutil
import threading
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
from common.log import logger


_GOVERNANCE_LOCKS: Dict[str, threading.RLock] = {}
_GOVERNANCE_LOCKS_LOCK = threading.Lock()
_GOVERNANCE_GLOBAL_WRITE_LOCK = threading.RLock()


def _governance_lock(path: str) -> threading.RLock:
    key = os.path.realpath(path)
    with _GOVERNANCE_LOCKS_LOCK:
        lock = _GOVERNANCE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _GOVERNANCE_LOCKS[key] = lock
        return lock


class MemoryService:
    """
    High-level service for memory file queries.
    Operates directly on the filesystem — no MemoryManager dependency.
    """

    def __init__(self, workspace_root: str):
        """
        :param workspace_root: Workspace root directory (e.g. ~/cow)
        """
        self.workspace_root = workspace_root
        self.memory_dir = os.path.join(workspace_root, "memory")

    # ------------------------------------------------------------------
    # list — paginated file metadata
    # ------------------------------------------------------------------
    def list_files(self, page: int = 1, page_size: int = 20, category: str = "memory") -> dict:
        """
        List memory or dream files with metadata (without content).

        Args:
            category: ``"memory"`` (default) — MEMORY.md + daily files;
                      ``"dream"``  — dream diary files from memory/dreams/
        """
        if category == "dream":
            files = self._list_dream_files()
        else:
            files = self._list_memory_files()

        total = len(files)
        start = (page - 1) * page_size
        end = start + page_size

        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "list": files[start:end],
        }

    def _list_memory_files(self) -> List[dict]:
        """memory/MEMORY.md + memory/*.md (newest first)."""
        files: List[dict] = []

        global_path = os.path.join(self.memory_dir, "MEMORY.md")
        if os.path.isfile(global_path):
            files.append(self._file_info(global_path, "MEMORY.md", "global"))

        if os.path.isdir(self.memory_dir):
            daily_files = []
            for name in os.listdir(self.memory_dir):
                full = os.path.join(self.memory_dir, name)
                if name == "MEMORY.md":
                    continue
                if os.path.isfile(full) and name.endswith(".md"):
                    daily_files.append((name, full))
            daily_files.sort(key=lambda x: x[0], reverse=True)
            for name, full in daily_files:
                files.append(self._file_info(full, name, "daily"))

        return files

    def _list_dream_files(self) -> List[dict]:
        """memory/dreams/*.md (newest first)."""
        files: List[dict] = []
        dreams_dir = os.path.join(self.memory_dir, "dreams")

        if os.path.isdir(dreams_dir):
            entries = []
            for name in os.listdir(dreams_dir):
                full = os.path.join(dreams_dir, name)
                if os.path.isfile(full) and name.endswith(".md"):
                    entries.append((name, full))
            entries.sort(key=lambda x: x[0], reverse=True)
            for name, full in entries:
                files.append(self._file_info(full, name, "dream"))

        return files

    # ------------------------------------------------------------------
    # content — read a single file
    # ------------------------------------------------------------------
    def get_content(self, filename: str, category: str = "memory") -> dict:
        """
        Read the full content of a memory or dream file.

        :param filename: File name, e.g. ``MEMORY.md``, ``2026-02-20.md``
        :param category: ``"memory"`` or ``"dream"``
        :return: dict with ``filename`` and ``content``
        :raises FileNotFoundError: if the file does not exist
        """
        path = self._resolve_path(filename, category)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Memory file not found: {filename}")

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        return {
            "filename": filename,
            "content": content,
        }

    # ------------------------------------------------------------------
    # dispatch — single entry point for protocol messages
    # ------------------------------------------------------------------
    def dispatch(self, action: str, payload: Optional[dict] = None) -> dict:
        """
        Dispatch a memory management action.

        :param action: ``list`` or ``content``
        :param payload: action-specific payload (supports ``category``: ``"memory"`` | ``"dream"``)
        :return: protocol-compatible response dict
        """
        payload = payload or {}
        try:
            if action == "list":
                page = payload.get("page", 1)
                page_size = payload.get("page_size", 20)
                category = payload.get("category", "memory")
                result_payload = self.list_files(page=page, page_size=page_size, category=category)
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "content":
                filename = payload.get("filename")
                if not filename:
                    return {"action": action, "code": 400, "message": "filename is required", "payload": None}
                category = payload.get("category", "memory")
                result_payload = self.get_content(filename, category=category)
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "candidates":
                page = payload.get("page", 1)
                page_size = payload.get("page_size", 20)
                status = payload.get("status", "")
                result_payload = self.list_candidates(page=page, page_size=page_size, status=status)
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "consolidate":
                result_payload = self.consolidate_candidates(
                    min_confidence=float(payload.get("min_confidence", 0.85)),
                    min_evidence=int(payload.get("min_evidence", 2)),
                )
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "cleanup_candidates":
                result_payload = self.cleanup_candidates(
                    now=payload.get("now"),
                    expire_after_days=int(payload.get("expire_after_days", 30)),
                    min_lookup_to_keep=int(payload.get("min_lookup_to_keep", 2)),
                    archive_after_days=int(payload.get("archive_after_days", 14)),
                )
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "cleanup_runtime_memory":
                result_payload = self.cleanup_runtime_memory(payload or {})
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "recent_activity":
                result_payload = self.recent_activity(
                    query=payload.get("query", ""),
                    limit=int(payload.get("limit", 5) or 5),
                )
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "health":
                result_payload = self.health_report()
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "scan_sensitive":
                result_payload = self.scan_sensitive()
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "governance_report":
                result_payload = self.governance_report()
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "governance_config":
                result_payload = self.update_governance_config(payload)
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "recover_transactions":
                result_payload = self.recover_transactions()
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "record_usage":
                result_payload = self.record_usage(
                    memory_key=payload.get("memory_key", ""),
                    query=payload.get("query", ""),
                )
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "detect_long_term_conflicts":
                result_payload = self.detect_long_term_conflicts()
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "explain":
                result_payload = self.explain_memory(payload.get("query", ""))
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "compress_long_term":
                result_payload = self.compress_long_term_memory(quality_check=bool(payload.get("quality_check", False)))
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "resolve_long_term_conflicts":
                result_payload = self.resolve_long_term_conflicts()
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "modify_memory":
                result_payload = self.modify_memory(payload.get("query", ""), payload.get("replacement", ""))
                if not result_payload.get("ok"):
                    code = 404 if result_payload.get("status") == "not_found" else 409
                    return {"action": action, "code": code, "message": result_payload.get("message", "modify failed"), "payload": result_payload}
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "audit_summary":
                result_payload = self.audit_summary()
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "apply_candidate":
                candidate_id = payload.get("id") or payload.get("candidate_id") or ""
                if not candidate_id:
                    return {"action": action, "code": 400, "message": "id is required", "payload": None}
                result_payload = self.apply_candidate(candidate_id)
                if not result_payload.get("ok"):
                    code = 404 if result_payload.get("status") == "not_found" else 409
                    return {"action": action, "code": code, "message": result_payload.get("message", "candidate not ready"), "payload": result_payload}
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "apply_ready_candidates":
                result_payload = self.apply_ready_candidates()
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "resolve_conflict":
                keep_id = payload.get("keep_id", "")
                reject_id = payload.get("reject_id", "")
                if not keep_id or not reject_id:
                    return {"action": action, "code": 400, "message": "keep_id and reject_id are required", "payload": None}
                result_payload = self.resolve_conflict(keep_id, reject_id)
                if not result_payload.get("ok"):
                    code = 404 if result_payload.get("status") == "not_found" else 409
                    return {"action": action, "code": code, "message": result_payload.get("message", "conflict not resolved"), "payload": result_payload}
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "rollback_version":
                version_id = payload.get("version_id", "")
                if not version_id:
                    return {"action": action, "code": 400, "message": "version_id is required", "payload": None}
                result_payload = self.rollback_version(version_id)
                if not result_payload.get("ok"):
                    code = 404 if result_payload.get("status") == "not_found" else 409
                    return {"action": action, "code": code, "message": result_payload.get("message", "rollback failed"), "payload": result_payload}
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "rollback_latest_version":
                result_payload = self.rollback_latest_version()
                if not result_payload.get("ok"):
                    code = 404 if result_payload.get("status") == "not_found" else 409
                    return {"action": action, "code": code, "message": result_payload.get("message", "rollback failed"), "payload": result_payload}
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "forget_memory":
                query = payload.get("query", "")
                if not query:
                    return {"action": action, "code": 400, "message": "query is required", "payload": None}
                result_payload = self.forget_memory(query)
                if not result_payload.get("ok"):
                    code = 404 if result_payload.get("status") == "not_found" else 409
                    return {"action": action, "code": code, "message": result_payload.get("message", "forget failed"), "payload": result_payload}
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}

            elif action == "natural_language":
                text = payload.get("text", "")
                routed = self.route_natural_language(text)
                if not routed:
                    return {"action": action, "code": 204, "message": "no memory action", "payload": None}
                routed_action = routed["action"]
                routed_payload = routed.get("payload", {})
                result = self.dispatch(routed_action, routed_payload)
                result["action"] = routed_action
                return result

            else:
                return {"action": action, "code": 400, "message": f"unknown action: {action}", "payload": None}

        except ValueError as e:
            return {"action": action, "code": 403, "message": "invalid filename", "payload": None}
        except FileNotFoundError as e:
            return {"action": action, "code": 404, "message": str(e), "payload": None}
        except Exception as e:
            logger.error(f"[MemoryService] dispatch error: action={action}, error={e}")
            return {"action": action, "code": 500, "message": str(e), "payload": None}

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def list_candidates(self, page: int = 1, page_size: int = 20, status: str = "") -> dict:
        rows = self._load_candidate_rows()
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        total = len(rows)
        start = (max(1, int(page)) - 1) * max(1, int(page_size))
        end = start + max(1, int(page_size))
        page_rows = rows[start:end]
        self._record_candidate_lookups(page_rows)
        for row in page_rows:
            row["lookup_count"] = int(row.get("lookup_count", 0) or 0) + 1
            row["last_lookup_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "list": page_rows,
        }

    def consolidate_candidates(self, min_confidence: float = 0.85, min_evidence: int = 2) -> dict:
        from agent.memory.promotion import MemoryPromotionCandidatePool

        result = MemoryPromotionCandidatePool(self.memory_dir).consolidate(
            min_confidence=min_confidence,
            min_evidence=min_evidence,
        )
        review_path = result.get("review_path") or ""
        audit_path = result.get("audit_path") or ""
        return {
            "selected_count": result.get("selected_count", 0),
            "review_file": self._relative_memory_path(review_path),
            "audit_file": self._relative_memory_path(audit_path),
            "conflict_count": result.get("conflict_count", 0),
            "conflict_file": self._relative_memory_path(result.get("conflict_path") or ""),
            "high_risk_count": result.get("high_risk_count", 0),
        }

    def apply_candidate(self, candidate_id: str) -> dict:
        from agent.memory.promotion import MemoryPromotionCandidatePool

        return MemoryPromotionCandidatePool(self.memory_dir).apply_candidate(candidate_id)

    def apply_ready_candidates(self) -> dict:
        from agent.memory.promotion import MemoryPromotionCandidatePool

        return MemoryPromotionCandidatePool(self.memory_dir).apply_ready_candidates()

    def resolve_conflict(self, keep_id: str, reject_id: str) -> dict:
        from agent.memory.promotion import MemoryPromotionCandidatePool

        return MemoryPromotionCandidatePool(self.memory_dir).resolve_conflict(keep_id, reject_id)

    def rollback_version(self, version_id: str) -> dict:
        from agent.memory.promotion import MemoryPromotionCandidatePool

        return MemoryPromotionCandidatePool(self.memory_dir).rollback_version(version_id)

    def rollback_latest_version(self) -> dict:
        from agent.memory.promotion import MemoryPromotionCandidatePool

        return MemoryPromotionCandidatePool(self.memory_dir).rollback_latest_version()

    def forget_memory(self, query: str) -> dict:
        memory_path = Path(self.memory_dir) / "MEMORY.md"
        if not memory_path.exists():
            return {"ok": False, "status": "not_found", "message": "MEMORY.md not found"}

        text = memory_path.read_text(encoding="utf-8")
        blocks = self._split_promoted_memory_blocks(text)
        tokens = self._forget_tokens(query)
        if not blocks or not tokens:
            return {"ok": False, "status": "not_found", "message": "no matching promoted memory found"}

        kept = []
        removed = []
        for block in blocks:
            if block["promoted"] and self._matches_forget_query(block["text"], tokens):
                removed.append(block["text"])
            else:
                kept.append(block["text"])

        if not removed:
            return {"ok": False, "status": "not_found", "message": "no matching promoted memory found"}

        snapshot_file = self._snapshot_memory_file(memory_path, "forget")
        memory_path.write_text("".join(kept).rstrip() + "\n", encoding="utf-8")
        self._append_quarantine("forgotten", removed, query)
        return {
            "ok": True,
            "status": "forgotten",
            "removed_count": len(removed),
            "removed_previews": [self._preview_removed_memory(item) for item in removed[:5]],
            "snapshot_file": self._relative_memory_path(str(snapshot_file)),
        }

    def cleanup_candidates(
        self,
        now: Optional[str] = None,
        expire_after_days: int = 30,
        min_lookup_to_keep: int = 2,
        archive_after_days: int = 14,
    ) -> dict:
        from agent.memory.promotion import MemoryPromotionCandidatePool

        return MemoryPromotionCandidatePool(self.memory_dir).cleanup(
            now=now,
            expire_after_days=expire_after_days,
            min_lookup_to_keep=min_lookup_to_keep,
            archive_after_days=archive_after_days,
        )

    def cleanup_runtime_memory(self, payload: dict) -> dict:
        from agent.memory.maintenance import MemoryMaintenance

        result = MemoryMaintenance(
            self.memory_dir,
            profile_field_limit=int(payload.get("profile_field_limit", 30) or 30),
            recent_focus_limit=int(payload.get("recent_focus_limit", 10) or 10),
            drop_process_state_files=bool(payload.get("drop_process_state_files", False)),
            run_retention=bool(payload.get("run_retention", True)),
            process_retention_days=int(payload.get("process_retention_days", 7) or 7),
            process_max_files=int(payload.get("process_max_files", 60) or 60),
            session_retention_days=int(payload.get("session_retention_days", 14) or 14),
            session_max_files=int(payload.get("session_max_files", 80) or 80),
            error_retention_days=int(payload.get("error_retention_days", 30) or 30),
            error_max_files=int(payload.get("error_max_files", 80) or 80),
        ).run()
        self._append_transaction("cleanup_runtime_memory", "completed", result)
        return result

    def recent_activity(self, query: str = "", limit: int = 5) -> dict:
        from agent.memory.recent_activity import RecentActivityMemory

        reader = RecentActivityMemory(self.workspace_root)
        activities = reader.list_recent(limit=limit)
        return {
            "query": query,
            "total": len(activities),
            "activities": activities,
            "answer": reader.answer(query, limit=limit),
        }

    def health_report(self) -> dict:
        from agent.memory.promotion import MemoryPromotionCandidatePool

        return MemoryPromotionCandidatePool(self.memory_dir).health_report()

    def record_usage(self, memory_key: str, query: str = "") -> dict:
        key = memory_key or "unknown"
        usage_path = Path(self.memory_dir) / "usage" / "long_term_usage.json"
        with _GOVERNANCE_GLOBAL_WRITE_LOCK:
            usage_path.parent.mkdir(parents=True, exist_ok=True)
            usage = self._load_json_file(usage_path)
            item = usage.setdefault(key, {"use_count": 0, "last_used_at": "", "last_query": ""})
            item["use_count"] = int(item.get("use_count", 0) or 0) + 1
            item["last_used_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            item["last_query"] = query
            self._atomic_write_text(usage_path, json.dumps(usage, ensure_ascii=False, indent=2))
        result = {"memory_key": key, **item}
        self._append_transaction("record_usage", "completed", result)
        return result

    def detect_long_term_conflicts(self) -> dict:
        blocks = self._promoted_blocks_from_memory()
        return self._detect_conflicts_in_promoted_blocks(blocks)

    def _detect_conflicts_in_promoted_blocks(self, blocks: List[dict]) -> dict:
        conflicts = []
        for left_index, left in enumerate(blocks):
            for right in blocks[left_index + 1:]:
                left_preview = left.get("preview") or self._preview_removed_memory(left.get("text", ""))
                right_preview = right.get("preview") or self._preview_removed_memory(right.get("text", ""))
                conflict_type = self._long_term_conflict_type(left_preview, right_preview)
                if conflict_type:
                    conflicts.append({"type": conflict_type, "left": left_preview, "right": right_preview})
        return {"conflict_count": len(conflicts), "conflicts": conflicts}

    def explain_memory(self, query: str) -> dict:
        blocks = self._promoted_blocks_from_memory()
        tokens = self._forget_tokens(query)
        matches = [block["preview"] for block in blocks if self._matches_forget_query(block["text"], tokens)] if tokens else []
        if matches:
            detail = f"匹配到的记忆偏好是：{matches[0]}"
        else:
            detail = "没有找到非常明确的匹配项，我会优先遵循你当前这句话的要求。"
        return {
            "explanation": f"我参考了与你当前问题相关的长期偏好，并会让当前明确指令优先。{detail}",
            "matched_count": len(matches),
        }

    def compress_long_term_memory(self, quality_check: bool = False) -> dict:
        memory_path = Path(self.memory_dir) / "MEMORY.md"
        if not memory_path.exists():
            return {"ok": False, "status": "not_found", "compressed_count": 0}
        text = memory_path.read_text(encoding="utf-8")
        blocks = self._split_promoted_memory_blocks(text)
        promoted = [block for block in blocks if block.get("promoted")]
        pre_quality = self._detect_conflicts_in_promoted_blocks(promoted) if quality_check else None
        if not promoted:
            snapshot = self._snapshot_memory_file(memory_path, "compress")
            version_id = self._append_service_version("compress_long_term", memory_path, snapshot, "Compressed long-term memory")
            result = {"ok": True, "status": "empty", "compressed_count": 0, "snapshot_file": self._relative_memory_path(str(snapshot)), "version_id": version_id}
            self._append_transaction("compress_long_term", "completed", result)
            return result
        snapshot = self._snapshot_memory_file(memory_path, "compress")
        manual = "".join(block["text"] for block in blocks if not block.get("promoted")).rstrip()
        seen = set()
        groups = {
            "Preferences": [],
            "Project Facts": [],
            "Code Habits": [],
            "Writing Rules": [],
            "Other": [],
        }
        compressed_count = 0
        for block in promoted:
            preview = self._preview_removed_memory(block["text"])
            key = re.sub(r"\s+", "", preview.lower())
            if not key or key in seen:
                continue
            seen.add(key)
            compressed_count += 1
            groups[self._memory_category(preview)].append(preview)
        lines = [manual, "", "## Consolidated Long-Term Memory", ""]
        for title, values in groups.items():
            if not values:
                continue
            lines.extend([f"### {title}", ""])
            lines.extend(f"- {value}" for value in values)
            lines.append("")
        self._atomic_write_text(memory_path, "\n".join(line for line in lines if line is not None).strip() + "\n")
        version_id = self._append_service_version("compress_long_term", memory_path, snapshot, "Compressed long-term memory")
        result = {
            "ok": True,
            "status": "compressed",
            "compressed_count": compressed_count,
            "snapshot_file": self._relative_memory_path(str(snapshot)),
            "version_id": version_id,
        }
        if quality_check:
            result["quality"] = pre_quality or {"conflict_count": 0, "conflicts": []}
        self._append_transaction("compress_long_term", "completed", result)
        return result

    def resolve_long_term_conflicts(self) -> dict:
        conflicts = self.detect_long_term_conflicts().get("conflicts", [])
        if not conflicts:
            return {"resolved_count": 0, "conflicts": []}
        usage = self._load_json_file(Path(self.memory_dir) / "usage" / "long_term_usage.json")
        memory_path = Path(self.memory_dir) / "MEMORY.md"
        text = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
        blocks = self._split_promoted_memory_blocks(text)
        removed = []
        kept = []
        remove_previews = set()
        for conflict in conflicts:
            left_key = self._memory_key_from_text(conflict.get("left", ""))
            right_key = self._memory_key_from_text(conflict.get("right", ""))
            left_count = int((usage.get(left_key) or {}).get("use_count", 0) or 0)
            right_count = int((usage.get(right_key) or {}).get("use_count", 0) or 0)
            remove_previews.add(conflict["right"] if left_count >= right_count else conflict["left"])
        for block in blocks:
            preview = self._preview_removed_memory(block.get("text", ""))
            if block.get("promoted") and preview in remove_previews:
                removed.append(block["text"])
            else:
                kept.append(block["text"])
        if removed:
            snapshot = self._snapshot_memory_file(memory_path, "resolve_conflicts")
            self._append_quarantine("conflict_resolved", removed, "")
            memory_path.write_text("".join(kept).rstrip() + "\n", encoding="utf-8")
            version_id = self._append_service_version("resolve_long_term_conflicts", memory_path, snapshot, "Resolved long-term memory conflicts")
        else:
            version_id = ""
        return {"resolved_count": len(removed), "removed_previews": [self._preview_removed_memory(item) for item in removed], "version_id": version_id}

    def modify_memory(self, query: str, replacement: str) -> dict:
        if not query or not replacement:
            result = {"ok": False, "status": "invalid", "message": "query and replacement are required"}
            self._append_transaction("modify_memory", "failed", result)
            return result
        memory_path = Path(self.memory_dir) / "MEMORY.md"
        if not memory_path.exists():
            result = {"ok": False, "status": "not_found", "message": "MEMORY.md not found"}
            self._append_transaction("modify_memory", "failed", result)
            return result
        blocks = self._split_promoted_memory_blocks(memory_path.read_text(encoding="utf-8"))
        tokens = self._forget_tokens(query)
        changed = 0
        rendered = []
        original_blocks = []
        for block in blocks:
            if block.get("promoted") and self._matches_forget_query(block.get("text", ""), tokens):
                original_blocks.append(block["text"])
                rendered.append(self._replace_promoted_preview(block["text"], replacement))
                changed += 1
            else:
                rendered.append(block["text"])
        if not changed:
            result = {"ok": False, "status": "not_found", "message": "no matching promoted memory found"}
            self._append_transaction("modify_memory", "failed", result)
            return result
        snapshot = self._snapshot_memory_file(memory_path, "modify")
        self._append_quarantine("modified", original_blocks, query)
        self._atomic_write_text(memory_path, "".join(rendered).rstrip() + "\n")
        version_id = self._append_service_version("modify_memory", memory_path, snapshot, replacement)
        result = {"ok": True, "status": "modified", "modified_count": changed, "version_id": version_id}
        self._append_transaction("modify_memory", "completed", result)
        return result

    def scan_sensitive(self) -> dict:
        paths = [Path(self.memory_dir) / "MEMORY.md", Path(self.memory_dir) / "quarantine" / "disabled_memories.jsonl"]
        redacted_count = 0
        for path in paths:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            redacted, count = self._redact_sensitive_text(text)
            if count:
                self._atomic_write_text(path, redacted)
                redacted_count += count
        result = {"redacted_count": redacted_count}
        self._append_transaction("scan_sensitive", "completed", result)
        return result

    def governance_report(self) -> dict:
        usage = self._load_json_file(Path(self.memory_dir) / "usage" / "long_term_usage.json")
        health = self.health_report()
        quarantine = self._read_jsonl(Path(self.memory_dir) / "quarantine" / "disabled_memories.jsonl")
        report_path = Path(self.memory_dir) / "governance_report.md"
        lines = [
            "# Memory Governance Report",
            "",
            f"generated_at: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}",
            f"health_score: {health.get('health_score', 100)}",
            f"usage_keys: {', '.join(sorted(usage.keys())) if usage else 'none'}",
            f"quarantine_count: {len(quarantine)}",
        ]
        self._atomic_write_text(report_path, "\n".join(lines) + "\n")
        return {"report_file": self._relative_memory_path(str(report_path)), "health": health}

    def update_governance_config(self, payload: dict) -> dict:
        config_path = Path(self.memory_dir) / "governance_config.json"
        current = self._load_json_file(config_path)
        current.update({k: v for k, v in (payload or {}).items() if v is not None})
        self._atomic_write_text(config_path, json.dumps(current, ensure_ascii=False, indent=2))
        return current

    def governance_config(self) -> dict:
        defaults = {
            "auto_compress_health_threshold": 0,
            "memory_search_budget_chars": 1800,
            "quarantine_match_strength": "normal",
        }
        defaults.update(self._load_json_file(Path(self.memory_dir) / "governance_config.json"))
        return defaults

    def recover_transactions(self) -> dict:
        rows = self._read_jsonl(Path(self.memory_dir) / "transactions" / "governance_transactions.jsonl")
        for row in reversed(rows):
            snapshot = row.get("snapshot_file") or (row.get("payload") or {}).get("snapshot_file", "")
            if not snapshot:
                continue
            snapshot_path = Path(self.memory_dir) / snapshot
            target_path = Path(self.memory_dir) / "MEMORY.md"
            if snapshot_path.exists():
                shutil.copyfile(snapshot_path, target_path)
                return {"recovered": True, "snapshot_file": snapshot}
        return {"recovered": False}

    def audit_summary(self) -> dict:
        quarantine_path = Path(self.memory_dir) / "quarantine" / "disabled_memories.jsonl"
        usage_path = Path(self.memory_dir) / "usage" / "long_term_usage.json"
        quarantine_rows = self._read_jsonl(quarantine_path)
        usage = self._load_json_file(usage_path)
        return {
            "quarantine_count": len(quarantine_rows),
            "usage_keys": sorted(usage.keys()),
            "recent_quarantine": quarantine_rows[-5:],
        }

    @staticmethod
    def route_natural_language(text: str) -> Optional[dict]:
        from agent.memory.intent import MemoryIntentRouter

        return MemoryIntentRouter.route(text)

    def _load_candidate_rows(self) -> List[dict]:
        path = os.path.join(self.memory_dir, "candidates", "promotion_candidates.jsonl")
        if not os.path.isfile(path):
            return []
        rows: List[dict] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    def _record_candidate_lookups(self, rows: List[dict]) -> None:
        if not rows:
            return
        from agent.memory.promotion import MemoryPromotionCandidatePool

        pool = MemoryPromotionCandidatePool(self.memory_dir)
        for row in rows:
            candidate_id = row.get("id")
            if candidate_id:
                pool.record_lookup(candidate_id)

    def _relative_memory_path(self, path: str) -> str:
        if not path:
            return ""
        try:
            return str(Path(path).resolve().relative_to(Path(self.memory_dir).resolve())).replace("\\", "/")
        except Exception:
            return ""

    def _promoted_blocks_from_memory(self) -> List[dict]:
        memory_path = Path(self.memory_dir) / "MEMORY.md"
        if not memory_path.exists():
            return []
        blocks = self._split_promoted_memory_blocks(memory_path.read_text(encoding="utf-8"))
        return [
            {"text": block["text"], "preview": self._preview_removed_memory(block["text"])}
            for block in blocks
            if block.get("promoted")
        ]

    @staticmethod
    def _long_term_conflict_type(left: str, right: str) -> str:
        left_norm = (left or "").lower()
        right_norm = (right or "").lower()
        pairs = (
            ("brevity_vs_detail", ("简短", "简洁", "结论", "brief", "concise"), ("详细", "展开", "推理", "detail")),
            ("formal_vs_casual", ("正式", "严谨", "formal"), ("轻松", "随意", "casual")),
        )
        for conflict_type, a_terms, b_terms in pairs:
            if any(term in left_norm for term in a_terms) and any(term in right_norm for term in b_terms):
                return conflict_type
            if any(term in right_norm for term in a_terms) and any(term in left_norm for term in b_terms):
                return conflict_type
        return ""

    def _append_quarantine(self, reason: str, blocks: List[str], query: str = "") -> None:
        path = Path(self.memory_dir) / "quarantine" / "disabled_memories.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for block in blocks:
                record = {
                    "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "reason": reason,
                    "query": query,
                    "preview": self._preview_removed_memory(block),
                    "content": block,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _append_service_version(self, action: str, target_path: Path, snapshot_path: Path, preview: str = "") -> str:
        versions_dir = Path(self.memory_dir) / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        version_id = f"memver-{stamp}-{action}"
        record = {
            "version_id": version_id,
            "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "action": "apply_candidate",
            "candidate_id": action,
            "target_file": self._relative_memory_path(str(target_path)),
            "snapshot_file": self._relative_memory_path(str(snapshot_path)),
            "content_digest": "",
            "content_preview": preview[:160],
            "service_action": action,
        }
        with (versions_dir / "memory_versions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return version_id

    def _append_transaction(self, action: str, status: str, payload: dict) -> None:
        path = Path(self.memory_dir) / "transactions" / "governance_transactions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "action": action,
            "status": status,
            "payload": payload or {},
            "snapshot_file": (payload or {}).get("snapshot_file", ""),
        }
        with _GOVERNANCE_GLOBAL_WRITE_LOCK:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _redact_sensitive_text(text: str) -> tuple[str, int]:
        count = 0
        patterns = (
            (r"\b(?:api[_ -]?key|secret[_ -]?key|access[_ -]?key)\b\s*[:=]\s*\S+", "api_key"),
            (r"\bsk-[A-Za-z0-9_-]{20,}\b", "api_key"),
            (r"\b(?:password|passwd|pwd)\b\s*[:=]\s*\S+", "password"),
            (r"\b(?:token|bearer)\b\s*[:=]\s*\S+", "token"),
        )
        redacted = text or ""
        for pattern, label in patterns:
            redacted, changed = re.subn(pattern, f"[REDACTED {label}]", redacted, flags=re.I)
            count += changed
        return redacted, count

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _GOVERNANCE_GLOBAL_WRITE_LOCK:
            tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)

    @staticmethod
    def _memory_category(preview: str) -> str:
        text = preview or ""
        if any(term in text for term in ("偏好", "回答", "回复", "语气")):
            return "Preferences"
        if any(term in text for term in ("项目事实", "项目是", "事实")):
            return "Project Facts"
        if any(term in text for term in ("代码", "测试", "bug", "报错")):
            return "Code Habits"
        if any(term in text for term in ("论文", "写作", "章节", "引用")):
            return "Writing Rules"
        return "Other"

    @staticmethod
    def _memory_key_from_text(text: str) -> str:
        normalized = text or ""
        if any(term in normalized for term in ("简短", "简洁", "结论", "concise", "brief")):
            return "concise"
        if any(term in normalized for term in ("详细", "展开", "推理", "detail")):
            return "detail"
        if any(term in normalized for term in ("论文", "引用", "paper")):
            return "paper"
        return re.sub(r"\W+", "_", normalized.lower()).strip("_")[:40] or "unknown"

    @staticmethod
    def _replace_promoted_preview(block: str, replacement: str) -> str:
        lines = []
        replaced = False
        for line in (block or "").splitlines():
            if not replaced and line.strip().startswith("- "):
                indent = line[: len(line) - len(line.lstrip())]
                lines.append(f"{indent}- {replacement.strip(' 。.') }")
                replaced = True
            else:
                lines.append(line)
        return "\n".join(lines).rstrip() + "\n\n"

    @staticmethod
    def _load_json_file(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _read_jsonl(path: Path) -> List[dict]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    @staticmethod
    def _split_promoted_memory_blocks(text: str) -> List[dict]:
        matches = list(re.finditer(r"(?m)^## Promoted Memory - .*$", text or ""))
        if not matches:
            return [{"promoted": False, "text": text or ""}] if text else []
        blocks = []
        if matches[0].start() > 0:
            blocks.append({"promoted": False, "text": text[:matches[0].start()]})
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            blocks.append({"promoted": True, "text": text[match.start():end]})
        return blocks

    @staticmethod
    def _forget_tokens(query: str) -> List[str]:
        text = re.sub(r"\s+", "", query or "").lower()
        stopwords = (
            "忘掉", "忘记", "删除", "移除", "清除", "不再记住", "这个", "那个", "这条", "那条",
            "记忆", "偏好", "规则", "习惯", "关于", "之前", "以后", "按照", "回答", "回复", "按", "来", "的",
            "forget", "delete", "remove", "clear", "memory", "preference", "rule", "about", "that",
        )
        for word in stopwords:
            text = text.replace(word, "")
        tokens = [word for word in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text) if len(word) >= 2]
        if tokens:
            expanded = []
            for token in tokens:
                expanded.append(token)
                if re.fullmatch(r"[\u4e00-\u9fff]{3,}", token):
                    expanded.extend(token[index:index + 2] for index in range(len(token) - 1))
            return expanded[:12]
        compact = text.strip()
        return [compact] if len(compact) >= 2 else []

    @staticmethod
    def _matches_forget_query(block: str, tokens: List[str]) -> bool:
        normalized = re.sub(r"\s+", "", block or "").lower()
        return any(token in normalized for token in tokens)

    def _snapshot_memory_file(self, memory_path: Path, prefix: str) -> Path:
        snapshots = Path(self.memory_dir) / "candidates" / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        snapshot = snapshots / f"{prefix}_{stamp}_{memory_path.name}"
        shutil.copyfile(memory_path, snapshot)
        return snapshot

    @staticmethod
    def _preview_removed_memory(block: str) -> str:
        for line in (block or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                return stripped[2:160]
        return re.sub(r"\s+", " ", block or "").strip()[:160]

    def _resolve_path(self, filename: str, category: str = "memory") -> str:
        """
        Safely resolve a filename to its absolute path within the allowed directory.

        - ``MEMORY.md`` → ``{workspace_root}/memory/MEMORY.md``
        - ``2026-02-20.md`` (memory) → ``{workspace_root}/memory/2026-02-20.md``
        - ``2026-02-20.md`` (dream) → ``{workspace_root}/memory/dreams/2026-02-20.md``

        Raises ValueError if the resolved path escapes the allowed directory.
        """
        if filename == "MEMORY.md":
            base_dir = self.memory_dir
        elif category == "dream":
            base_dir = os.path.join(self.memory_dir, "dreams")
        else:
            base_dir = self.memory_dir

        resolved = os.path.realpath(os.path.join(base_dir, filename))
        allowed = os.path.realpath(base_dir)

        if resolved != allowed and not resolved.startswith(allowed + os.sep):
            raise ValueError(f"Invalid filename: path traversal detected")

        return resolved

    @staticmethod
    def _file_info(path: str, filename: str, file_type: str) -> dict:
        """Build a file metadata dict."""
        stat = os.stat(path)
        updated_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "filename": filename,
            "type": file_type,
            "size": stat.st_size,
            "updated_at": updated_at,
        }
