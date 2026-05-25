from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List

from common.app_paths import ensure_system_dir
from common.log import logger


class ContextAnxietyGuard:
    """Persist a compact checkpoint when context pressure gets high."""

    def __init__(self, threshold: float = 0.70):
        self.threshold = max(0.1, min(0.95, float(threshold or 0.70)))

    @staticmethod
    def harness_dir() -> str:
        path = os.path.join(ensure_system_dir(), "harness")
        os.makedirs(path, exist_ok=True)
        return path

    def maybe_checkpoint(self, executor: Any, user_message: str = "") -> Dict[str, Any]:
        agent = getattr(executor, "agent", None)
        if not agent:
            return {"created": False, "reason": "missing_agent"}

        try:
            max_tokens, _reserve = executor._effective_context_budget()
            system_tokens = agent._estimate_message_tokens({
                "role": "system",
                "content": getattr(executor, "system_prompt", "") or "",
            })
            message_tokens = sum(agent._estimate_message_tokens(msg) for msg in getattr(executor, "messages", []))
            estimated_tokens = system_tokens + message_tokens
            ratio = estimated_tokens / max_tokens if max_tokens else 0.0
        except Exception as exc:
            logger.debug(f"[Harness] Context checkpoint skipped: {exc}")
            return {"created": False, "reason": "estimate_failed"}

        if ratio < self.threshold:
            return {
                "created": False,
                "ratio": ratio,
                "estimated_tokens": estimated_tokens,
                "max_tokens": max_tokens,
            }

        checkpoint = {
            "version": "context-checkpoint-v1",
            "created_at": datetime.now().isoformat(),
            "threshold": self.threshold,
            "ratio": round(ratio, 4),
            "estimated_tokens": estimated_tokens,
            "max_tokens": max_tokens,
            "session_id": getattr(getattr(agent, "model", None), "session_id", "") or getattr(agent, "_current_session_id", ""),
            "model": getattr(getattr(agent, "model", None), "model", ""),
            "workspace_dir": getattr(agent, "workspace_dir", ""),
            "message_count": len(getattr(executor, "messages", []) or []),
            "latest_user": self._excerpt(user_message or self._latest_text(executor.messages, "user"), 1200),
            "latest_assistant": self._excerpt(self._latest_text(executor.messages, "assistant"), 1200),
            "next_action": "Continue from durable state and this checkpoint; avoid restarting completed work.",
        }
        path = self._write_checkpoint(checkpoint)
        checkpoint["path"] = path
        logger.info(
            f"[Harness] Context checkpoint saved at ratio={checkpoint['ratio']} path={path}"
        )
        return {"created": True, **checkpoint}

    def _write_checkpoint(self, checkpoint: Dict[str, Any]) -> str:
        base = self.harness_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        json_path = os.path.join(base, f"context_checkpoint_{stamp}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)

        progress_path = os.path.join(base, "PROGRESS.md")
        with open(progress_path, "a", encoding="utf-8") as f:
            f.write(
                "\n\n"
                f"## Context Checkpoint - {checkpoint['created_at']}\n\n"
                f"- Ratio: {checkpoint['ratio']} ({checkpoint['estimated_tokens']}/{checkpoint['max_tokens']} est. tokens)\n"
                f"- Session: {checkpoint.get('session_id') or 'unknown'}\n"
                f"- Model: {checkpoint.get('model') or 'unknown'}\n"
                f"- Workspace: {checkpoint.get('workspace_dir') or 'unknown'}\n"
                f"- Latest user request: {checkpoint.get('latest_user') or '[empty]'}\n"
                f"- Latest assistant result: {checkpoint.get('latest_assistant') or '[empty]'}\n"
                f"- Checkpoint file: {json_path}\n"
            )
        index_path = os.path.join(base, "progress.json")
        history: List[Dict[str, Any]] = []
        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                history = loaded if isinstance(loaded, list) else []
            except Exception:
                history = []
        history.append({
            "created_at": checkpoint["created_at"],
            "ratio": checkpoint["ratio"],
            "estimated_tokens": checkpoint["estimated_tokens"],
            "max_tokens": checkpoint["max_tokens"],
            "path": json_path,
        })
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(history[-50:], f, ensure_ascii=False, indent=2)
        return json_path

    @staticmethod
    def _latest_text(messages: List[Dict[str, Any]], role: str) -> str:
        for msg in reversed(messages or []):
            if msg.get("role") != role:
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                text = "\n".join(parts).strip()
                if text:
                    return text
        return ""

    @staticmethod
    def _excerpt(text: str, limit: int) -> str:
        text = " ".join((text or "").split())
        return text[:limit].rstrip() + ("..." if len(text) > limit else "")
