"""Automatic updater for workspace profile files.

This module updates AGENT.md, USER.md and RULE.md only when the user gives a
clear, durable instruction. Textbook-specific preferences stay in each
textbook's WritingSpec/preferences files and are intentionally ignored here.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional


PROFILE_FILES = {"AGENT.md", "USER.md", "RULE.md"}
SECRET_PATTERN = re.compile(
    r"(api[_ -]?key|token|secret|password|passwd|密码|密钥|令牌)\s*[:：=]",
    re.IGNORECASE,
)


@dataclass
class ProfileUpdate:
    file: str
    content: str
    reason: str
    confidence: float


class WorkspaceProfileUpdater:
    """Apply conservative, auditable updates to workspace profile files."""

    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root)
        self.version_dir = self.workspace_root / ".workspace_profile_versions"

    def update_from_events(self, events: Iterable[Dict], session_id: str = "") -> List[ProfileUpdate]:
        updates: List[ProfileUpdate] = []
        for event in events:
            if event.get("role") != "user":
                continue
            updates.extend(self.extract_updates(str(event.get("content") or "")))
        return self.apply_updates(updates, session_id=session_id)

    def extract_updates(self, text: str) -> List[ProfileUpdate]:
        text = self._normalize(text)
        if not text or SECRET_PATTERN.search(text):
            return []
        if self._looks_textbook_specific(text):
            return []

        explicit = self._extract_explicit_file_update(text)
        if explicit:
            return [explicit]

        candidates: List[ProfileUpdate] = []

        if re.search(r"(工作区规则|作为.*规则|以后.*规则|固定规则|全局规则)", text):
            candidates.append(ProfileUpdate("RULE.md", text, "user declared a durable workspace rule", 0.92))

        if re.search(r"(你的工作方式|你以后|你应该|你需要|回答时|回复时|交流风格|语气|称呼你)", text):
            candidates.append(ProfileUpdate("AGENT.md", text, "user adjusted agent operating style", 0.86))

        if re.search(r"(我的称呼是|请叫我|我叫|我的名字是|我是.+(?:老师|教师|工程师|学生|研究员)|我的职业是)", text):
            candidates.append(ProfileUpdate("USER.md", text, "user provided stable identity information", 0.9))
        elif re.search(r"(我希望|我需要|我想要|我偏好|我喜欢|更倾向于|不要|避免).{4,80}", text):
            candidates.append(ProfileUpdate("USER.md", text, "user provided a stable preference", 0.78))

        return self._dedupe_updates(candidates)

    def apply_updates(self, updates: Iterable[ProfileUpdate], session_id: str = "") -> List[ProfileUpdate]:
        applied: List[ProfileUpdate] = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        backed_up: set[str] = set()

        for update in self._dedupe_updates(list(updates)):
            if update.file not in PROFILE_FILES:
                continue
            content = self._clip(update.content)
            if not content or SECRET_PATTERN.search(content):
                continue
            path = self.workspace_root / update.file
            existing = path.read_text(encoding="utf-8") if path.exists() else f"# {update.file}\n"
            if content in existing:
                continue
            if update.file not in backed_up and path.exists():
                self._backup(path)
                backed_up.add(update.file)

            new_text = self._append_record(existing, content, update, timestamp, session_id)
            path.write_text(new_text, encoding="utf-8")
            self._append_log(update, content, timestamp, session_id)
            applied.append(ProfileUpdate(update.file, content, update.reason, update.confidence))

        return applied

    def _extract_explicit_file_update(self, text: str) -> Optional[ProfileUpdate]:
        file_match = re.search(r"\b(AGENT\.md|USER\.md|RULE\.md)\b", text, re.IGNORECASE)
        if not file_match:
            return None
        file_name = next((name for name in PROFILE_FILES if name.lower() == file_match.group(1).lower()), "")
        if file_name not in PROFILE_FILES:
            return None
        payload = self._extract_payload(text, file_match.group(0))
        if not payload:
            payload = text
        reason = f"user explicitly requested updating {file_name}"
        return ProfileUpdate(file_name, payload, reason, 0.98)

    @staticmethod
    def _extract_payload(text: str, marker: str) -> str:
        after = text.split(marker, 1)[-1]
        after = re.sub(r"^[\s:：,，。；;]+", "", after).strip()
        before = text.split(marker, 1)[0]
        quoted = re.findall(r"[“\"']([^”\"']{4,240})[”\"']", text)
        if quoted:
            return quoted[-1].strip()
        return after or before.strip()

    @staticmethod
    def _append_record(existing: str, content: str, update: ProfileUpdate, timestamp: str, session_id: str) -> str:
        existing = existing.rstrip()
        section = "## 自动更新记录"
        header = "" if section in existing else f"\n\n{section}\n"
        session = f" `{session_id}`" if session_id else ""
        record = (
            f"- {timestamp}{session} [{update.reason}; confidence={update.confidence:.2f}] "
            f"{content}"
        )
        return f"{existing}{header}\n{record}\n"

    def _backup(self, path: Path) -> None:
        self.version_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, self.version_dir / f"{path.stem}_{stamp}{path.suffix}")

    def _append_log(self, update: ProfileUpdate, content: str, timestamp: str, session_id: str) -> None:
        self.version_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.version_dir / "profile_update_log.jsonl"
        payload = {
            "time": timestamp,
            "session_id": session_id,
            "file": update.file,
            "content": content,
            "reason": update.reason,
            "confidence": update.confidence,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _looks_textbook_specific(text: str) -> bool:
        if re.search(r"(本教材|本书|当前教材|这一章|本章|第[一二三四五六七八九十0-9]+章|教材偏好|WritingSpec)", text):
            return True
        return False

    @staticmethod
    def _dedupe_updates(updates: List[ProfileUpdate]) -> List[ProfileUpdate]:
        seen = set()
        deduped: List[ProfileUpdate] = []
        for update in updates:
            key = (update.file, update.content)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(update)
        return deduped

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    @staticmethod
    def _clip(text: str, limit: int = 240) -> str:
        text = WorkspaceProfileUpdater._normalize(text)
        return text[:limit].rstrip()
