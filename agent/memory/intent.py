"""Natural-language intent routing for memory maintenance actions."""

from __future__ import annotations

import re
from typing import Dict, Optional


class MemoryIntentRouter:
    """Recognize explicit memory-management requests in user text."""

    @staticmethod
    def route(text: str) -> Optional[Dict[str, dict]]:
        normalized = re.sub(r"\s+", " ", (text or "")).strip()
        if not normalized:
            return None
        lower = normalized.lower()

        try:
            from agent.memory.recent_activity import RecentActivityMemory

            if RecentActivityMemory.is_activity_query(normalized):
                return {"action": "recent_activity", "payload": {"query": normalized}}
        except Exception:
            pass

        recent_correction = MemoryIntentRouter._recent_memory_correction(normalized, lower)
        if recent_correction:
            return recent_correction

        modification = MemoryIntentRouter._modify_memory(normalized, lower)
        if modification:
            return modification

        explanation = MemoryIntentRouter._explain_memory(normalized, lower)
        if explanation:
            return explanation

        targeted_forget = MemoryIntentRouter._targeted_forget(normalized, lower)
        if targeted_forget:
            return targeted_forget

        rollback = MemoryIntentRouter._version_rollback(normalized, lower)
        if rollback:
            return rollback

        conflict_resolution = MemoryIntentRouter._conflict_resolution(normalized, lower)
        if conflict_resolution:
            return conflict_resolution

        if MemoryIntentRouter._mentions_candidate_memory(normalized, lower):
            if MemoryIntentRouter._mentions_cleanup(normalized, lower):
                return {"action": "cleanup_candidates", "payload": {}}

            candidate_id = MemoryIntentRouter._candidate_id(normalized)
            if MemoryIntentRouter._mentions_apply(normalized, lower):
                if candidate_id:
                    return {"action": "apply_candidate", "payload": {"id": candidate_id}}
                if MemoryIntentRouter._mentions_all(normalized, lower) or "待审查" in normalized:
                    return {"action": "apply_ready_candidates", "payload": {}}
            if MemoryIntentRouter._mentions_consolidate(normalized, lower):
                return {"action": "consolidate", "payload": {}}
            if MemoryIntentRouter._mentions_view(normalized, lower):
                return {"action": "candidates", "payload": {}}

        return None

    @staticmethod
    def _recent_memory_correction(text: str, lower: str) -> Optional[Dict[str, dict]]:
        chinese_correction = any(
            phrase in text
            for phrase in (
                "记错",
                "删掉刚才",
                "删除刚才",
                "撤销刚才",
                "不是这个意思",
                "不要这样记",
                "别这样记",
            )
        )
        chinese_scope = any(phrase in text for phrase in ("记忆", "刚才", "这条", "那条"))
        english_correction = any(
            phrase in lower
            for phrase in (
                "wrong memory",
                "forget that",
                "undo that memory",
                "delete that memory",
                "not what i meant",
            )
        )
        english_scope = any(word in lower for word in ("memory", "that", "last"))
        if (chinese_correction and chinese_scope) or (english_correction and english_scope):
            return {"action": "rollback_latest_version", "payload": {}}
        return None

    @staticmethod
    def _targeted_forget(text: str, lower: str) -> Optional[Dict[str, dict]]:
        forget_markers = ("忘掉", "忘记", "删除", "移除", "清除", "不再记住")
        memory_markers = ("记忆", "偏好", "规则", "习惯", "preference", "memory", "rule")
        english_forget = ("forget", "delete", "remove", "clear")
        if any(marker in text for marker in forget_markers) and any(marker in text for marker in memory_markers):
            return {"action": "forget_memory", "payload": {"query": text}}
        if any(marker in lower for marker in english_forget) and any(marker in lower for marker in memory_markers):
            return {"action": "forget_memory", "payload": {"query": text}}
        return None

    @staticmethod
    def _modify_memory(text: str, lower: str) -> Optional[Dict[str, dict]]:
        match = re.search(r"把(.{2,80}?)(?:这个)?(?:记忆|偏好|规则)?改成(.{2,120})", text)
        if match:
            return {
                "action": "modify_memory",
                "payload": {"query": match.group(1).strip(), "replacement": match.group(2).strip()},
            }
        match = re.search(r"change (?:the )?(?:memory|preference|rule) (?:about )?(.{2,80}?) to (.{2,120})", lower)
        if match:
            return {
                "action": "modify_memory",
                "payload": {"query": match.group(1).strip(), "replacement": match.group(2).strip()},
            }
        return None

    @staticmethod
    def _explain_memory(text: str, lower: str) -> Optional[Dict[str, dict]]:
        if any(marker in text for marker in ("为什么", "为啥")) and any(marker in text for marker in ("回答", "这样", "这么")):
            return {"action": "explain", "payload": {"query": text}}
        if "why" in lower and ("answer" in lower or "respond" in lower):
            return {"action": "explain", "payload": {"query": text}}
        return None

    @staticmethod
    def _conflict_resolution(text: str, lower: str) -> Optional[Dict[str, dict]]:
        keep_match = re.search(r"(?:保留|keep)\s*(?:候选|candidate)?\s*([A-Za-z0-9_-]{2,64})", text, flags=re.I)
        reject_match = re.search(r"(?:拒绝|reject)\s*(?:候选|candidate)?\s*([A-Za-z0-9_-]{2,64})", text, flags=re.I)
        if keep_match and reject_match and ("候选" in text or "candidate" in lower):
            return {
                "action": "resolve_conflict",
                "payload": {
                    "keep_id": keep_match.group(1),
                    "reject_id": reject_match.group(1),
                },
            }
        return None

    @staticmethod
    def _version_rollback(text: str, lower: str) -> Optional[Dict[str, dict]]:
        if not (("rollback" in lower or "回滚" in text) and ("version" in lower or "版本" in text)):
            return None
        match = re.search(r"(memver-[A-Za-z0-9_-]+)", text, flags=re.I)
        if not match:
            return None
        return {
            "action": "rollback_version",
            "payload": {"version_id": match.group(1)},
        }

    @staticmethod
    def _mentions_candidate_memory(text: str, lower: str) -> bool:
        mentions_candidate = (
            "候选" in text
            or "待审查" in text
            or "promotion" in lower
            or "candidate" in lower
        )
        mentions_memory = "记忆" in text or "memory" in lower or mentions_candidate
        return mentions_candidate and mentions_memory

    @staticmethod
    def _mentions_view(text: str, lower: str) -> bool:
        return any(word in text for word in ("查看", "列出", "显示", "有哪些")) or any(
            word in lower for word in ("show", "list", "view")
        )

    @staticmethod
    def _mentions_consolidate(text: str, lower: str) -> bool:
        return any(word in text for word in ("整理", "合并", "生成审查", "准备审查")) or any(
            word in lower for word in ("consolidate", "review")
        )

    @staticmethod
    def _mentions_cleanup(text: str, lower: str) -> bool:
        return any(word in text for word in ("清理", "清除", "过期", "淘汰")) or any(
            word in lower for word in ("cleanup", "clean up", "expire")
        )

    @staticmethod
    def _mentions_apply(text: str, lower: str) -> bool:
        return any(word in text for word in ("应用", "确认", "写入", "保存到长期记忆")) or any(
            word in lower for word in ("apply", "confirm")
        )

    @staticmethod
    def _mentions_all(text: str, lower: str) -> bool:
        return "所有" in text or "全部" in text or "all" in lower

    @staticmethod
    def _candidate_id(text: str) -> str:
        match = re.search(r"(?:候选|candidate)\s*([A-Za-z0-9_-]{2,64})", text, flags=re.I)
        return match.group(1) if match else ""
