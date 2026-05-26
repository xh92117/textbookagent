"""Memory promotion candidate pool.

Durable memory should not be updated from every process log directly. This
module records auditable candidates that a later consolidation step can review
and promote into MEMORY.md, user_profile, or project truth files.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class MemoryPromotionCandidatePool:
    """Append-only-ish candidate store with content hash deduplication."""

    VERSION = "memory-promotion-candidate-v1"

    def __init__(self, memory_dir: str | Path):
        self.memory_dir = Path(memory_dir)
        self.root = self.memory_dir / "candidates"
        self.path = self.root / "promotion_candidates.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)

    def record_from_process(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        text = self._candidate_text(payload.get("user_message", ""))
        if not text:
            return None
        candidate = {
            "version": self.VERSION,
            "id": self._candidate_id(text),
            "status": "candidate",
            "target": self._target_for(text),
            "confidence": 0.86,
            "reason": "user explicitly asked to remember durable information",
            "content": text,
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "evidence_count": 1,
            "lookup_count": 0,
            "last_lookup_at": "",
            "context_tags": self._context_tags(text),
            "sources": [self._source(payload)],
        }
        return self.upsert(candidate)

    def upsert(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        candidate.setdefault("lookup_count", 0)
        candidate.setdefault("last_lookup_at", "")
        candidate.setdefault("context_tags", self._context_tags(candidate.get("content", "")))
        if self._matches_quarantine(candidate.get("content", "")):
            candidate["status"] = "blocked_quarantined"
            candidate["risk_level"] = "high"
            candidate["risk_reason"] = "matches_disabled_memory"
            candidate["blocked_at"] = candidate.get("updated_at") or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            existing = self._load_all()
            existing.append(candidate)
            self._write_all(existing)
            self._append_audit(self.root / "promotion_audit.jsonl", "", [candidate], action="block_quarantined_candidate")
            return candidate
        candidate_similarity_key = self._similarity_key(candidate.get("content", ""))
        if candidate_similarity_key:
            candidate["similarity_key"] = candidate_similarity_key
            canonical = self._canonical_preference(candidate_similarity_key)
            if canonical:
                candidate["canonical_preference"] = canonical
        risk_level, risk_reason = self._risk(candidate)
        candidate["risk_level"] = risk_level
        candidate["risk_reason"] = risk_reason
        sensitivity_type = self._sensitivity_type(candidate.get("content", ""))
        if sensitivity_type:
            candidate["status"] = "blocked_sensitive"
            candidate["sensitivity_type"] = sensitivity_type
            candidate["risk_level"] = "high"
            candidate["risk_reason"] = "sensitive_information"
            candidate["content"] = "[REDACTED sensitive memory candidate]"
            candidate["blocked_at"] = candidate.get("updated_at") or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            candidate["reason"] = "sensitive information is not eligible for durable memory promotion"
        existing = self._load_all()
        by_id = {item.get("id"): item for item in existing if item.get("id")}
        current = by_id.get(candidate["id"])
        if not current:
            current = self._similar_candidate(existing, candidate)
        if current:
            original_id = candidate["id"]
            current["updated_at"] = candidate["updated_at"]
            current["evidence_count"] = int(current.get("evidence_count", 1)) + int(candidate.get("evidence_count", 1) or 1)
            current["lookup_count"] = int(current.get("lookup_count", 0) or 0)
            current.setdefault("last_lookup_at", "")
            if candidate_similarity_key:
                current["similarity_key"] = candidate_similarity_key
                canonical = self._canonical_preference(candidate_similarity_key)
                if canonical:
                    current["canonical_preference"] = canonical
            current["risk_level"] = self._max_risk(current.get("risk_level", "low"), candidate.get("risk_level", "low"))
            if self._risk_rank(candidate.get("risk_level", "low")) >= self._risk_rank(current.get("risk_level", "low")):
                current["risk_reason"] = candidate.get("risk_reason", current.get("risk_reason", "ordinary_preference"))
            tags = current.setdefault("context_tags", [])
            for tag in candidate.get("context_tags", []):
                if tag not in tags:
                    tags.append(tag)
            if original_id != current.get("id"):
                merged_ids = current.setdefault("merged_candidate_ids", [])
                if original_id not in merged_ids:
                    merged_ids.append(original_id)
            sources = current.setdefault("sources", [])
            for source in candidate.get("sources", []):
                if source not in sources:
                    sources.append(source)
            current["sources"] = sources[-12:]
            merged = current
        else:
            existing.append(candidate)
            merged = candidate
        self._write_all(existing)
        if sensitivity_type:
            self._append_audit(self.root / "promotion_audit.jsonl", "", [merged], action="block_sensitive_candidate")
        return merged

    def decay_confidence(
        self,
        now: str | None = None,
        stale_after_days: int = 30,
        decay_factor: float = 0.75,
        min_lookup_to_protect: int = 2,
    ) -> Dict[str, Any]:
        rows = self._load_all()
        current_time = self._parse_time(now) if now else datetime.now()
        decayed = []
        for item in rows:
            if item.get("status") not in {"candidate", "ready_for_review"}:
                continue
            age_days = (current_time - self._parse_time(item.get("updated_at") or item.get("created_at", ""))).days
            lookup_count = int(item.get("lookup_count", 0) or 0)
            evidence_count = int(item.get("evidence_count", 0) or 0)
            if age_days < stale_after_days or lookup_count >= min_lookup_to_protect or evidence_count >= 2:
                continue
            confidence = float(item.get("confidence", 0) or 0)
            item["confidence"] = round(max(0.05, confidence * decay_factor), 4)
            item["decay_count"] = int(item.get("decay_count", 0) or 0) + 1
            item["last_decayed_at"] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
            item["updated_at"] = item["last_decayed_at"]
            decayed.append(item.get("id", ""))
        self._write_all(rows)
        return {"decayed_count": len(decayed), "decayed_ids": decayed}

    def record_negative_feedback(self, text: str, penalty: float = 0.5) -> Dict[str, Any]:
        rows = self._load_all()
        feedback_key = self._similarity_key(text)
        adjusted = []
        for item in rows:
            if item.get("status") not in {"candidate", "ready_for_review", "applied"}:
                continue
            item_key = item.get("similarity_key") or self._similarity_key(item.get("content", ""))
            if not feedback_key or item_key != feedback_key:
                continue
            confidence = float(item.get("confidence", 0) or 0)
            item["confidence"] = round(max(0.05, confidence * penalty), 4)
            item["negative_feedback_count"] = int(item.get("negative_feedback_count", 0) or 0) + 1
            item["last_negative_feedback_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            item["updated_at"] = item["last_negative_feedback_at"]
            adjusted.append(item.get("id", ""))
        self._write_all(rows)
        return {"adjusted_count": len(adjusted), "adjusted_ids": adjusted}

    def health_report(self) -> Dict[str, Any]:
        rows = self._load_all()
        total = len(rows)
        high_risk_count = sum(1 for item in rows if item.get("risk_level") == "high")
        expired_count = sum(1 for item in rows if item.get("status") == "expired")
        conflict_count = sum(1 for item in rows if item.get("status") == "conflict")
        duplicate_groups = {}
        for item in rows:
            key = item.get("similarity_key") or ""
            if key:
                duplicate_groups.setdefault(key, 0)
                duplicate_groups[key] += 1
        duplicate_count = sum(count - 1 for count in duplicate_groups.values() if count > 1)
        penalty = high_risk_count * 15 + conflict_count * 12 + expired_count * 5 + duplicate_count * 5
        return {
            "total": total,
            "high_risk_count": high_risk_count,
            "expired_count": expired_count,
            "conflict_count": conflict_count,
            "duplicate_count": duplicate_count,
            "health_score": max(0, 100 - penalty),
        }

    def record_lookup(self, candidate_id: str) -> Dict[str, Any]:
        rows = self._load_all()
        candidate = next((item for item in rows if item.get("id") == candidate_id), None)
        if not candidate:
            return {"ok": False, "status": "not_found", "message": "candidate not found"}

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        candidate["lookup_count"] = int(candidate.get("lookup_count", 0) or 0) + 1
        candidate["last_lookup_at"] = now
        candidate["updated_at"] = now
        self._write_all(rows)
        return {
            "ok": True,
            "status": "recorded",
            "candidate_id": candidate_id,
            "lookup_count": candidate["lookup_count"],
        }

    def cleanup(
        self,
        now: str | None = None,
        expire_after_days: int = 30,
        min_lookup_to_keep: int = 2,
        archive_after_days: int = 14,
    ) -> Dict[str, Any]:
        rows = self._load_all()
        if not rows:
            return {"expired_count": 0, "kept_by_lookup_count": 0, "archived_count": 0, "total": 0}

        current_time = self._parse_time(now) if now else datetime.now()
        expired_count = 0
        kept_by_lookup_count = 0
        archive_rows: List[Dict[str, Any]] = []
        active_rows: List[Dict[str, Any]] = []

        for item in rows:
            if item.get("status") != "candidate":
                active_rows.append(item)
                continue
            if self._should_expire_candidate(item, current_time, expire_after_days, min_lookup_to_keep):
                item["status"] = "expired"
                item["expired_at"] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                item["updated_at"] = item["expired_at"]
                expired_count += 1
            elif self._is_old_weak_consulted(item, current_time, expire_after_days, min_lookup_to_keep):
                kept_by_lookup_count += 1
            active_rows.append(item)

        remaining_rows: List[Dict[str, Any]] = []
        for item in active_rows:
            if self._should_archive(item, current_time, archive_after_days):
                archived = dict(item)
                archived["archived_at"] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                archive_rows.append(archived)
            else:
                remaining_rows.append(item)

        if archive_rows:
            self._append_archive(archive_rows)

        self._write_all(remaining_rows)
        return {
            "expired_count": expired_count,
            "kept_by_lookup_count": kept_by_lookup_count,
            "archived_count": len(archive_rows),
            "total": len(remaining_rows),
        }

    def consolidate(
        self,
        min_confidence: float = 0.85,
        min_evidence: int = 2,
    ) -> Dict[str, Any]:
        """Generate a review packet for candidates ready to promote.

        This method intentionally does not modify durable memory targets. It
        only marks candidates as ready_for_review and writes an auditable review
        document a human or later policy step can apply.
        """
        rows = self._load_all()
        conflicts = self._detect_candidate_conflicts(rows)
        conflict_items = self._mark_conflicts(rows, conflicts)
        high_risk_items = [
            item for item in rows
            if item.get("status") == "candidate" and item.get("risk_level") == "high"
        ]
        conflict_path = ""
        if conflicts:
            conflict_report = self.root / "promotion_conflicts.md"
            self._write_conflicts(conflict_report, conflicts)
            conflict_path = str(conflict_report)

        selected = [
            item for item in rows
            if item.get("status") == "candidate"
            and item.get("risk_level") != "high"
            and self._is_ready(item, min_confidence, min_evidence)
        ]
        if not selected:
            if conflict_items:
                self._write_all(rows)
            return {
                "selected_count": 0,
                "review_path": "",
                "audit_path": "",
                "conflict_count": len(conflict_items),
                "conflict_path": conflict_path,
                "high_risk_count": len(high_risk_items),
            }

        review_id = datetime.now().strftime("review-%Y%m%d-%H%M%S")
        for item in selected:
            item["status"] = "ready_for_review"
            item["review_id"] = review_id
            item["target_path"] = self._target_path(item.get("target", ""))
            item["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        self._write_all(rows)
        review_path = self.root / "promotion_review.md"
        audit_path = self.root / "promotion_audit.jsonl"
        self._write_review(review_path, review_id, selected)
        self._append_audit(audit_path, review_id, selected)
        return {
            "selected_count": len(selected),
            "review_path": str(review_path),
            "audit_path": str(audit_path),
            "conflict_count": len(conflict_items),
            "conflict_path": conflict_path,
            "high_risk_count": len(high_risk_items),
        }

    def apply_candidate(self, candidate_id: str) -> Dict[str, Any]:
        rows = self._load_all()
        candidate = next((item for item in rows if item.get("id") == candidate_id), None)
        if not candidate:
            return {"ok": False, "status": "not_found", "message": "candidate not found"}
        if candidate.get("status") != "ready_for_review":
            return {"ok": False, "status": "not_ready", "message": "candidate must be ready_for_review before apply"}

        target_path = self._resolve_target_path(candidate)
        target_conflict = self._target_conflict(candidate, target_path)
        if target_conflict:
            candidate["status"] = "conflict"
            candidate["conflict_type"] = target_conflict
            candidate["conflict_with"] = self._relative_to_memory(target_path)
            candidate["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            self._write_all(rows)
            self._append_audit(
                self.root / "promotion_audit.jsonl",
                candidate.get("review_id", ""),
                [candidate],
                action="apply_candidate_conflict",
            )
            return {
                "ok": False,
                "status": "conflict",
                "message": "candidate conflicts with target memory",
                "candidate_id": candidate_id,
                "conflict_type": target_conflict,
                "target_file": self._relative_to_memory(target_path),
            }

        snapshot_path = self._snapshot_target(target_path)
        self._append_to_target(target_path, candidate)

        candidate["status"] = "applied"
        candidate["applied_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        candidate["target_path"] = self._target_path(candidate.get("target", ""))
        candidate["snapshot_path"] = self._relative_to_memory(snapshot_path)
        candidate["updated_at"] = candidate["applied_at"]
        self._write_all(rows)
        version_id = self._append_version_record(candidate, target_path, snapshot_path, action="apply_candidate")
        self._append_audit(self.root / "promotion_audit.jsonl", candidate.get("review_id", ""), [candidate], action="apply_candidate")
        return {
            "ok": True,
            "status": "applied",
            "candidate_id": candidate_id,
            "target_file": self._relative_to_memory(target_path),
            "snapshot_file": self._relative_to_memory(snapshot_path),
            "version_id": version_id,
        }

    def apply_ready_candidates(self) -> Dict[str, Any]:
        rows = self._load_all()
        ready_ids = [
            item.get("id", "")
            for item in rows
            if item.get("status") == "ready_for_review" and item.get("id")
        ]
        applied = []
        failed = []
        for candidate_id in ready_ids:
            result = self.apply_candidate(candidate_id)
            if result.get("ok"):
                applied.append(result)
            else:
                failed.append(result)
        return {
            "ok": True,
            "status": "applied" if applied else "empty",
            "applied_count": len(applied),
            "failed_count": len(failed),
            "applied": applied,
            "failed": failed,
        }

    def apply_auto_candidates(self, min_evidence: int = 2) -> Dict[str, Any]:
        rows = self._load_all()
        ready_rows = [item for item in rows if item.get("status") == "ready_for_review"]
        ready_ids = [
            item.get("id", "")
            for item in ready_rows
            if item.get("id")
            and item.get("risk_level") == "low"
            and int(item.get("evidence_count", 0) or 0) >= min_evidence
        ]
        applied = []
        failed = []
        for candidate_id in ready_ids:
            result = self.apply_candidate(candidate_id)
            if result.get("ok"):
                applied.append(result)
            else:
                failed.append(result)
        return {
            "ok": True,
            "status": "applied" if applied else "empty",
            "applied_count": len(applied),
            "failed_count": len(failed),
            "skipped_count": max(0, len(ready_rows) - len(ready_ids)),
            "applied_ids": [item.get("candidate_id", "") for item in applied],
            "applied": applied,
            "failed": failed,
        }

    def resolve_conflict(self, keep_id: str, reject_id: str) -> Dict[str, Any]:
        rows = self._load_all()
        by_id = {item.get("id"): item for item in rows if item.get("id")}
        keep = by_id.get(keep_id)
        reject = by_id.get(reject_id)
        if not keep or not reject:
            return {"ok": False, "status": "not_found", "message": "candidate not found"}
        if keep.get("status") != "conflict" or reject.get("status") != "conflict":
            return {"ok": False, "status": "not_conflict", "message": "both candidates must be conflict status"}
        if keep.get("conflict_with") not in ("", reject_id) and reject.get("conflict_with") not in ("", keep_id):
            return {"ok": False, "status": "not_related", "message": "candidates are not in the same conflict"}

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        review_id = datetime.now().strftime("resolve-%Y%m%d-%H%M%S")
        keep["status"] = "ready_for_review"
        keep["review_id"] = review_id
        keep["target_path"] = self._target_path(keep.get("target", ""))
        keep["resolved_conflict_with"] = reject_id
        keep["updated_at"] = now
        keep.pop("conflict_with", None)

        reject["status"] = "rejected"
        reject["rejected_at"] = now
        reject["rejected_reason"] = f"conflict resolved in favor of {keep_id}"
        reject["updated_at"] = now

        self._write_all(rows)
        self._append_audit(
            self.root / "promotion_audit.jsonl",
            review_id,
            [keep, reject],
            action="resolve_conflict",
        )
        return {
            "ok": True,
            "status": "resolved",
            "kept_id": keep_id,
            "rejected_id": reject_id,
            "review_id": review_id,
        }

    def rollback_version(self, version_id: str) -> Dict[str, Any]:
        version = self._find_version(version_id)
        if not version:
            return {"ok": False, "status": "not_found", "message": "version not found"}
        target_file = version.get("target_file", "")
        snapshot_file = version.get("snapshot_file", "")
        if not target_file or not snapshot_file:
            return {"ok": False, "status": "invalid_version", "message": "version is missing rollback paths"}

        target_path = self.memory_dir / target_file
        snapshot_path = self.memory_dir / snapshot_file
        if not snapshot_path.exists():
            return {"ok": False, "status": "snapshot_missing", "message": "snapshot file not found"}

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(snapshot_path, target_path)
        rollback_id = self._append_rollback_version(version, target_path, snapshot_path)
        return {
            "ok": True,
            "status": "rolled_back",
            "version_id": version_id,
            "rollback_version_id": rollback_id,
            "target_file": target_file,
        }

    def rollback_latest_version(self) -> Dict[str, Any]:
        version = self._find_latest_applied_version()
        if not version:
            return {"ok": False, "status": "not_found", "message": "no applied memory version found"}

        result = self.rollback_version(version.get("version_id", ""))
        if result.get("ok"):
            result["rolled_back_candidate_id"] = version.get("candidate_id", "")
        return result

    def _load_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                item.setdefault("lookup_count", 0)
                item.setdefault("last_lookup_at", "")
                rows.append(item)
        return rows

    def _write_all(self, rows: List[Dict[str, Any]]) -> None:
        self.path.write_text(
            ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n") if rows else "",
            encoding="utf-8",
        )

    def _append_archive(self, rows: List[Dict[str, Any]]) -> None:
        archive_path = self.root / "promotion_archive.jsonl"
        with archive_path.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _append_version_record(self, candidate: Dict[str, Any], target_path: Path, snapshot_path: Path, action: str) -> str:
        versions_dir = self.memory_dir / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        content = candidate.get("content", "")
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        candidate_id = candidate.get("id", "")
        version_id = f"memver-{stamp}-{candidate_id}"
        record = {
            "version_id": version_id,
            "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "action": action,
            "candidate_id": candidate_id,
            "target_file": self._relative_to_memory(target_path),
            "snapshot_file": self._relative_to_memory(snapshot_path),
            "content_digest": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
            "content_preview": content[:160],
            "review_id": candidate.get("review_id", ""),
        }
        with (versions_dir / "memory_versions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return version_id

    def _append_rollback_version(self, version: Dict[str, Any], target_path: Path, snapshot_path: Path) -> str:
        versions_dir = self.memory_dir / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        rollback_id = f"memver-{stamp}-rollback"
        record = {
            "version_id": rollback_id,
            "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "action": "rollback_version",
            "rolled_back_version_id": version.get("version_id", ""),
            "candidate_id": version.get("candidate_id", ""),
            "target_file": self._relative_to_memory(target_path),
            "snapshot_file": self._relative_to_memory(snapshot_path),
        }
        with (versions_dir / "memory_versions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return rollback_id

    def _find_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        version_path = self.memory_dir / "versions" / "memory_versions.jsonl"
        if not version_path.exists():
            return None
        for line in version_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if item.get("version_id") == version_id:
                return item
        return None

    def _find_latest_applied_version(self) -> Optional[Dict[str, Any]]:
        version_path = self.memory_dir / "versions" / "memory_versions.jsonl"
        if not version_path.exists():
            return None
        for line in reversed(version_path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if item.get("action") == "apply_candidate" and item.get("version_id"):
                return item
        return None

    def _write_review(self, path: Path, review_id: str, selected: List[Dict[str, Any]]) -> None:
        lines = [
            "# Memory Promotion Review",
            "",
            f"review_id: {review_id}",
            f"created_at: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}",
            "",
            "These candidates are ready for review. They have not been written to durable memory.",
            "Apply only items that are stable, non-sensitive, and useful for future work.",
            "",
        ]
        for idx, item in enumerate(selected, 1):
            lines.extend([
                f"## {idx}. {item.get('target_path', self._target_path(item.get('target', '')))}",
                "",
                f"- Candidate id: `{item.get('id', '')}`",
                f"- Confidence: {item.get('confidence', 0)}",
                f"- Evidence count: {item.get('evidence_count', 0)}",
                f"- Reason: {item.get('reason', '')}",
                "",
                "Proposed memory:",
                "",
                f"- {item.get('content', '')}",
                "",
                "Sources:",
            ])
            for source in item.get("sources", [])[:12]:
                lines.append(
                    f"- `{source.get('path', '')}` session={source.get('session_id', '')} "
                    f"process={source.get('process_id', '')}"
                )
            lines.append("")
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _detect_candidate_conflicts(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates = [item for item in rows if item.get("status") == "candidate"]
        conflicts: List[Dict[str, Any]] = []
        for left_index, left in enumerate(candidates):
            for right in candidates[left_index + 1:]:
                conflict_type = self._conflict_type(left.get("content", ""), right.get("content", ""))
                if conflict_type:
                    conflicts.append({
                        "type": conflict_type,
                        "left_id": left.get("id", ""),
                        "right_id": right.get("id", ""),
                        "left_content": left.get("content", ""),
                        "right_content": right.get("content", ""),
                    })
        return conflicts

    def _mark_conflicts(self, rows: List[Dict[str, Any]], conflicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_id = {item.get("id"): item for item in rows if item.get("id")}
        marked: List[Dict[str, Any]] = []
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        for conflict in conflicts:
            for key in ("left_id", "right_id"):
                item = by_id.get(conflict.get(key, ""))
                if not item:
                    continue
                item["status"] = "conflict"
                item["conflict_type"] = conflict["type"]
                item["conflict_with"] = conflict["right_id"] if key == "left_id" else conflict["left_id"]
                item["updated_at"] = now
                if item not in marked:
                    marked.append(item)
        return marked

    @staticmethod
    def _write_conflicts(path: Path, conflicts: List[Dict[str, Any]]) -> None:
        lines = [
            "# Memory Promotion Conflicts",
            "",
            f"created_at: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}",
            "",
            "These candidates need resolution before promotion.",
            "",
        ]
        for idx, conflict in enumerate(conflicts, 1):
            lines.extend([
                f"## {idx}. {conflict['type']}",
                "",
                f"- Left: `{conflict.get('left_id', '')}` {conflict.get('left_content', '')}",
                f"- Right: `{conflict.get('right_id', '')}` {conflict.get('right_content', '')}",
                "",
            ])
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    @staticmethod
    def _append_audit(path: Path, review_id: str, selected: List[Dict[str, Any]], action: str = "consolidate_candidates") -> None:
        record = {
            "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "action": action,
            "review_id": review_id,
            "selected_count": len(selected),
            "candidate_ids": [item.get("id", "") for item in selected],
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _resolve_target_path(self, candidate: Dict[str, Any]) -> Path:
        target = candidate.get("target_path") or self._target_path(candidate.get("target", ""))
        if target == "RULE.md":
            return self.memory_dir / "RULE.md"
        if target == "memory/user_profile.md":
            return self.memory_dir / "user_profile.md"
        return self.memory_dir / "MEMORY.md"

    def _target_conflict(self, candidate: Dict[str, Any], target_path: Path) -> str:
        if not target_path.exists():
            return ""
        try:
            target_text = target_path.read_text(encoding="utf-8")
        except Exception:
            return ""
        return self._conflict_type(candidate.get("content", ""), target_text)

    def _snapshot_target(self, target_path: Path) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        snapshots = self.root / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        snapshot_name = f"{target_path.stem}_{stamp}{target_path.suffix or '.txt'}"
        snapshot_path = snapshots / snapshot_name
        if target_path.exists():
            shutil.copyfile(target_path, snapshot_path)
        else:
            snapshot_path.write_text("", encoding="utf-8")
        return snapshot_path

    @staticmethod
    def _append_to_target(target_path: Path, candidate: Dict[str, Any]) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        existing = target_path.read_text(encoding="utf-8") if target_path.exists() else f"# {target_path.name}\n"
        entry = (
            "\n\n"
            f"## Promoted Memory - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"- {candidate.get('content', '')}\n"
            f"  - source: candidate `{candidate.get('id', '')}`; evidence_count={candidate.get('evidence_count', 0)}\n"
        )
        target_path.write_text(existing.rstrip() + entry, encoding="utf-8")

    def _relative_to_memory(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.memory_dir.resolve())).replace("\\", "/")
        except Exception:
            return str(path)

    @staticmethod
    def _is_ready(candidate: Dict[str, Any], min_confidence: float, min_evidence: int) -> bool:
        confidence = float(candidate.get("confidence", 0) or 0)
        evidence_count = int(candidate.get("evidence_count", 0) or 0)
        return confidence >= min_confidence or evidence_count >= min_evidence

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            return datetime.fromisoformat((value or "").strip())
        except Exception:
            return datetime.min

    @staticmethod
    def _should_expire_candidate(
        item: Dict[str, Any],
        current_time: datetime,
        expire_after_days: int,
        min_lookup_to_keep: int,
    ) -> bool:
        age_days = (current_time - MemoryPromotionCandidatePool._parse_time(item.get("created_at", ""))).days
        is_old = age_days >= expire_after_days
        is_weak = (
            float(item.get("confidence", 0) or 0) < 0.85
            and int(item.get("evidence_count", 0) or 0) < 2
        )
        lookup_count = int(item.get("lookup_count", 0) or 0)
        return is_old and is_weak and lookup_count < min_lookup_to_keep

    @staticmethod
    def _is_old_weak_consulted(
        item: Dict[str, Any],
        current_time: datetime,
        expire_after_days: int,
        min_lookup_to_keep: int,
    ) -> bool:
        age_days = (current_time - MemoryPromotionCandidatePool._parse_time(item.get("created_at", ""))).days
        is_old = age_days >= expire_after_days
        is_weak = (
            float(item.get("confidence", 0) or 0) < 0.85
            and int(item.get("evidence_count", 0) or 0) < 2
        )
        lookup_count = int(item.get("lookup_count", 0) or 0)
        return is_old and is_weak and lookup_count >= min_lookup_to_keep

    @staticmethod
    def _should_archive(item: Dict[str, Any], current_time: datetime, archive_after_days: int) -> bool:
        if item.get("status") not in {"applied", "rejected", "expired"}:
            return False
        timestamp = (
            item.get("applied_at")
            or item.get("rejected_at")
            or item.get("expired_at")
            or item.get("updated_at")
            or item.get("created_at")
            or ""
        )
        age_days = (current_time - MemoryPromotionCandidatePool._parse_time(timestamp)).days
        return age_days >= archive_after_days

    @staticmethod
    def _conflict_type(left: str, right: str) -> str:
        left_norm = left.lower()
        right_norm = right.lower()
        pairs = (
            (
                "brevity_vs_detail",
                ("concise", "concisely", "brief", "short", "简洁", "简短"),
                ("detailed", "detail", "详尽", "详细"),
            ),
            (
                "formal_vs_casual",
                ("formal", "严肃", "正式"),
                ("casual", "informal", "轻松", "随意"),
            ),
            (
                "auto_vs_ask_first",
                ("automatic", "automatically", "auto", "自动"),
                ("ask first", "confirm first", "先询问", "先确认"),
            ),
        )
        for conflict_type, left_terms, right_terms in pairs:
            if MemoryPromotionCandidatePool._has_any(left_norm, left_terms) and MemoryPromotionCandidatePool._has_any(right_norm, right_terms):
                return conflict_type
            if MemoryPromotionCandidatePool._has_any(right_norm, left_terms) and MemoryPromotionCandidatePool._has_any(left_norm, right_terms):
                return conflict_type
        return ""

    @staticmethod
    def _has_any(text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    @staticmethod
    def _sensitivity_type(text: str) -> str:
        checks = (
            ("api_key", r"\b(?:api[_ -]?key|secret[_ -]?key|access[_ -]?key)\b\s*[:=]\s*\S+"),
            ("api_key", r"\bsk-[A-Za-z0-9_-]{20,}\b"),
            ("token", r"\b(?:token|bearer)\b\s*[:=]\s*\S+"),
            ("password", r"\b(?:password|passwd|pwd)\b\s*[:=]\s*\S+"),
            ("private_key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        )
        for sensitivity_type, pattern in checks:
            if re.search(pattern, text or "", flags=re.I):
                return sensitivity_type
        return ""

    @staticmethod
    def _risk(candidate: Dict[str, Any]) -> tuple[str, str]:
        text = (candidate.get("content", "") or "").lower()
        high_terms = (
            "without asking",
            "without confirmation",
            "do not ask",
            "skip confirmation",
            "bypass",
            "execute shell",
            "run commands",
            "permission",
            "credential",
            "security",
            "不要询问",
            "无需确认",
            "跳过确认",
            "绕过",
            "权限",
            "安全",
        )
        if any(term in text for term in high_terms):
            return "high", "permission_or_safety_sensitive"
        if candidate.get("target") == "workspace_rule" or any(term in text for term in ("rule", "must", "always", "规则", "必须")):
            return "medium", "durable_behavior_rule"
        return "low", "ordinary_preference"

    @staticmethod
    def _risk_rank(risk_level: str) -> int:
        return {"low": 1, "medium": 2, "high": 3}.get(risk_level or "low", 1)

    @staticmethod
    def _max_risk(left: str, right: str) -> str:
        return left if MemoryPromotionCandidatePool._risk_rank(left) >= MemoryPromotionCandidatePool._risk_rank(right) else right

    @staticmethod
    def _similar_candidate(existing: List[Dict[str, Any]], candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        similarity_key = candidate.get("similarity_key")
        if not similarity_key:
            return None
        for item in existing:
            if item.get("status") not in {"candidate", "ready_for_review"}:
                continue
            if item.get("target") != candidate.get("target"):
                continue
            if item.get("similarity_key") == similarity_key:
                return item
        return None

    def _matches_quarantine(self, content: str) -> bool:
        quarantine_path = self.memory_dir / "quarantine" / "disabled_memories.jsonl"
        if not quarantine_path.exists():
            return False
        candidate_key = self._similarity_key(content)
        candidate_norm = re.sub(r"\s+", "", (content or "").lower())
        for line in quarantine_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            disabled = f"{item.get('content', '')} {item.get('preview', '')}"
            if candidate_key and candidate_key == self._similarity_key(disabled):
                return True
            disabled_norm = re.sub(r"\s+", "", disabled.lower())
            if len(candidate_norm) >= 8 and (candidate_norm in disabled_norm or disabled_norm in candidate_norm):
                return True
        return False

    @staticmethod
    def _similarity_key(text: str) -> str:
        normalized = (text or "").lower()
        groups = (
            (
                "preference:brevity",
                ("concise", "concisely", "brief", "briefly", "short", "shorter", "简洁", "简短", "简明", "只要结论", "少说", "少废话", "直接说结论", "短一些"),
            ),
            (
                "preference:detail",
                ("detailed", "detail", "explain fully", "详尽", "详细", "展开", "严谨"),
            ),
            (
                "preference:formal",
                ("formal", "正式", "严肃"),
            ),
            (
                "preference:casual",
                ("casual", "informal", "轻松", "随意"),
            ),
        )
        for key, terms in groups:
            if MemoryPromotionCandidatePool._has_any(normalized, terms):
                return key
        return ""

    @staticmethod
    def _canonical_preference(similarity_key: str) -> str:
        return {
            "preference:brevity": "brevity",
            "preference:detail": "detail",
            "preference:formal": "formal",
            "preference:casual": "casual",
        }.get(similarity_key or "", "")

    @staticmethod
    def _context_tags(text: str) -> List[str]:
        normalized = (text or "").lower()
        tags: List[str] = []
        groups = (
            ("paper", ("论文", "引用", "文献", "paper", "citation", "academic")),
            ("code", ("代码", "测试", "bug", "报错", "code", "test", "debug")),
            ("writing", ("写作", "润色", "章节", "大纲", "writing", "chapter", "outline")),
            ("chat", ("日常", "闲聊", "聊天", "chat")),
        )
        for tag, terms in groups:
            if any(term in normalized for term in terms):
                tags.append(tag)
        return tags

    @staticmethod
    def _target_path(target: str) -> str:
        return {
            "long_term_memory": "MEMORY.md",
            "workspace_rule": "RULE.md",
            "user_profile": "memory/user_profile.md",
        }.get(target or "", "MEMORY.md")

    @staticmethod
    def _candidate_text(text: str) -> str:
        text = re.sub(r"\s+", " ", (text or "")).strip()
        if not text:
            return ""
        explicit = re.search(r"(?:请记住|记住|以后|长期|偏好|规则|写论文时|写代码时)(.+)", text)
        if not explicit:
            return ""
        if re.search(r"(继续写|不要停|现在|这次|临时|第三章|第\d+章)", text) and "记住" not in text:
            return ""
        value = explicit.group(0).strip(" ：:，,。")
        if len(value) < 8:
            return ""
        return value[:300]

    @staticmethod
    def _target_for(text: str) -> str:
        if re.search(r"(偏好|称呼|语气|回答|回复|以后)", text):
            return "long_term_memory"
        if re.search(r"(规则|必须|禁止)", text):
            return "workspace_rule"
        return "long_term_memory"

    @staticmethod
    def _candidate_id(text: str) -> str:
        normalized = re.sub(r"\s+", "", text.lower())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _source(payload: Dict[str, Any]) -> Dict[str, str]:
        process_id = str(payload.get("process_id", ""))
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", process_id).strip("_") or "process"
        return {
            "session_id": str(payload.get("session_id", "")),
            "process_id": process_id,
            "path": f"memory/processes/{safe_id}_state.md",
            "observed_at": str(payload.get("started_at") or payload.get("updated_at") or ""),
        }
