"""Tools for navigating the lightweight memory graph index."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from agent.memory.graph import MemoryGraphService
from agent.tools.base_tool import BaseTool, ToolResult


class MemoryGraphContextTool(BaseTool):
    """Return short graph navigation hints for memory lookup."""

    name: str = "memory_graph_context"
    description: str = (
        "Find related memory entities, authoritative sources, historical sources, "
        "and recommended files to read. Use this as a lightweight navigation index; "
        "read source files for final evidence."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Entity, topic, textbook id, or question to navigate in memory.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum graph nodes to return (default: 8).",
                "default": 8,
            },
        },
        "required": ["query"],
    }

    def __init__(self, system_root: Optional[str] = None, project_workspace: str = ""):
        super().__init__()
        self.system_root = system_root
        self.project_workspace = project_workspace

    def execute(self, args: dict) -> ToolResult:
        query = (args or {}).get("query", "")
        limit = int((args or {}).get("limit", 8) or 8)
        if not query:
            return ToolResult.fail("Error: query parameter is required")
        try:
            service = self._service()
            try:
                context = service.context(query, limit=max(1, min(limit, 12)))
            finally:
                service.close()
            return ToolResult.success(self._format_context(context))
        except Exception as exc:
            return ToolResult.fail(f"Error reading MemoryGraph: {exc}")

    def _service(self) -> MemoryGraphService:
        system_root, project_workspace = self._roots()
        return MemoryGraphService(system_root, project_workspace=project_workspace)

    def _roots(self) -> tuple[str, str]:
        if self.system_root:
            return self.system_root, self.project_workspace
        configured_workspace = ""
        config = getattr(self, "config", None)
        if isinstance(config, dict):
            configured_workspace = str(config.get("cwd") or "")
        try:
            from common.app_paths import active_workspace, system_dir

            return system_dir(), self.project_workspace or configured_workspace or active_workspace()
        except Exception:
            return "", self.project_workspace or configured_workspace

    @staticmethod
    def _format_context(context: Dict[str, Any], max_chars: int = 2400) -> str:
        lines = [
            f"MemoryGraph context for: {context.get('query', '')}",
            "Matched entities:",
        ]
        entities = context.get("matched_entities") or []
        lines.extend(f"- {entity}" for entity in entities[:8])
        if not entities:
            lines.append("- none")

        def add_nodes(title: str, key: str) -> None:
            lines.append(title)
            nodes = context.get(key) or []
            if not nodes:
                lines.append("- none")
                return
            for node in nodes[:5]:
                reason = "/".join(
                    part for part in (node.get("temporal_scope"), node.get("authority")) if part
                )
                lines.append(f"- {node.get('entity_key', '')} [{reason or 'unknown'}] {node.get('source_path', '')}")

        add_nodes("Authoritative nodes:", "authoritative_nodes")
        add_nodes("Historical nodes:", "historical_nodes")

        conflicts = context.get("conflicts") or []
        if conflicts:
            lines.append("Conflicts:")
            for item in conflicts[:3]:
                lines.append(f"- {item.get('entity_key', '')}: {item.get('type', '')}")

        lines.append("Recommended reads:")
        reads = context.get("recommended_reads") or []
        if reads:
            for item in reads[:5]:
                lines.append(
                    f"- {item.get('source_path', '')} "
                    f"({item.get('entity_key', '')}; {item.get('reason', '')})"
                )
        else:
            lines.append("- none")

        notes = context.get("graph_notes") or []
        if notes:
            lines.append("Graph notes:")
            lines.extend(f"- {note}" for note in notes[:3])

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 32].rstrip() + "\n...(truncated)"
        return text


class MemoryGraphStatusTool(BaseTool):
    """Return compact status for the memory graph index."""

    name: str = "memory_graph_status"
    description: str = "Show MemoryGraph index health, schema version, and node/source counts."
    params: dict = {
        "type": "object",
        "properties": {
            "benchmark_query": {
                "type": "string",
                "description": "Optional query used to benchmark MemoryGraph context lookup latency.",
            },
            "action": {
                "type": "string",
                "description": "Optional action: status, repair, or rebuild.",
                "default": "status",
            }
        },
        "required": [],
    }

    def __init__(self, system_root: Optional[str] = None, project_workspace: str = ""):
        super().__init__()
        self.system_root = system_root
        self.project_workspace = project_workspace

    def execute(self, args: dict) -> ToolResult:
        try:
            service = MemoryGraphContextTool(self.system_root, self.project_workspace)._service()
            try:
                action = str((args or {}).get("action", "status") or "status").lower()
                if action in {"rebuild", "repair"}:
                    service.rebuild()
                else:
                    service.sync_changed()
                status = service.status()
                status["action"] = action
                status["graph_cache"] = self._cache_stats()
                query = (args or {}).get("benchmark_query", "")
                if query:
                    status["benchmark"] = self._benchmark(service, query)
            finally:
                service.close()
            return ToolResult.success(json.dumps(status, ensure_ascii=False, sort_keys=True))
        except Exception as exc:
            return ToolResult.fail(f"Error reading MemoryGraph status: {exc}")

    @staticmethod
    def _cache_stats() -> Dict[str, Any]:
        try:
            from agent.tools.memory.memory_search import MemorySearchTool

            return MemorySearchTool.graph_plan_cache_stats()
        except Exception:
            return {"entries": 0, "hits": 0, "misses": 0, "hit_rate": 0.0, "ttl_seconds": 0}

    @staticmethod
    def _benchmark(service: MemoryGraphService, query: str) -> Dict[str, Any]:
        import time

        start = time.perf_counter()
        context = service.context(query, limit=5, sync=False)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "query": query,
            "elapsed_ms": round(elapsed_ms, 3),
            "matched_entities": len(context.get("matched_entities") or []),
            "recommended_reads": len(context.get("recommended_reads") or []),
        }
