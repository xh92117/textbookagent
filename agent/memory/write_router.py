"""Lightweight routing decisions for memory writes."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class MemoryWriteDecision:
    should_write: bool
    target: str = ""
    reason: str = ""
    normalized_key: str = ""


class MemoryWriteRouter:
    """Centralize high-level memory write eligibility checks."""

    @classmethod
    def route_user_profile_signal(cls, text: str, source_type: str = "user") -> MemoryWriteDecision:
        if source_type != "user":
            return MemoryWriteDecision(False, "user_profile", "non_user_source")
        if cls.is_injected_context_block(text):
            return MemoryWriteDecision(False, "user_profile", "injected_context")
        if cls.is_transient_task_request(text):
            return MemoryWriteDecision(False, "user_profile", "transient_task")
        key = cls.normalize_profile_value(text)
        if not key:
            return MemoryWriteDecision(False, "user_profile", "empty")
        return MemoryWriteDecision(True, "user_profile", "stable_user_signal", key)

    @staticmethod
    def is_injected_context_block(text: str) -> bool:
        text = str(text or "").strip()
        markers = (
            "[Current textbook id:",
            "[Current textbook:",
            "[Canonical chapter directory:",
            "[Tool rule:",
            "[State rule:",
            "[Path rule:",
        )
        return text.startswith("[Current textbook id:") and sum(marker in text for marker in markers) >= 3

    @staticmethod
    def is_transient_task_request(text: str) -> bool:
        compact = re.sub(r"\s+", "", text or "")
        if not compact:
            return False
        durable_markers = ("以后", "每次", "总是", "长期", "请记住", "记住", "偏好", "习惯", "不要再")
        if any(marker in compact for marker in durable_markers):
            return False
        transient_patterns = (
            r"^(请你)?(继续)?写第[一二三四五六七八九十\d]+章",
            r"^(请你)?开始写第[一二三四五六七八九十\d]+章",
            r"^(请你)?编写第[一二三四五六七八九十\d]+章",
            r"^(请你)?继续编写第[一二三四五六七八九十\d]+章",
            r"^(请你)?写(一下)?第[一二三四五六七八九十\d]+章",
        )
        return any(re.search(pattern, compact) for pattern in transient_patterns)

    @staticmethod
    def normalize_profile_value(value: str) -> str:
        value = re.sub(r"\s+", "", str(value or "").lower())
        return re.sub(r"[\u3002\uff01\uff1f，,.;:：；、\"'`~!?\-_\[\]()（）【】{}<>《》]", "", value)

    @staticmethod
    def normalize_for_dedupe(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip().lower()
