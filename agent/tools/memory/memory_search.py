"""
Memory search tool

Allows agents to search their memory using semantic and keyword search
"""

from typing import Dict, Any, Optional
from agent.tools.base_tool import BaseTool


class MemorySearchTool(BaseTool):
    """Tool for searching agent memory"""
    _GRAPH_PLAN_CACHE = {}
    _GRAPH_PLAN_CACHE_TTL_SECONDS = 60
    _GRAPH_PLAN_CACHE_HITS = 0
    _GRAPH_PLAN_CACHE_MISSES = 0
    
    name: str = "memory_search"
    description: str = (
        "Search agent's long-term memory using semantic and keyword search. "
        "Use this to recall past conversations, preferences, and knowledge."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (can be natural language question or keywords)"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 10)",
                "default": 10
            },
            "min_score": {
                "type": "number",
                "description": "Minimum relevance score (0-1, default: 0.1)",
                "default": 0.1
            },
            "graph_mode": {
                "type": "string",
                "description": "Graph planner output mode: full or compact (default: compact)",
                "default": "compact"
            }
        },
        "required": ["query"]
    }
    
    def __init__(self, memory_manager, user_id: Optional[str] = None, system_root: Optional[str] = None):
        """
        Initialize memory search tool
        
        Args:
            memory_manager: MemoryManager instance
            user_id: Optional user ID for scoped search
        """
        super().__init__()
        self.memory_manager = memory_manager
        self.user_id = user_id
        self.system_root = system_root

        from config import conf
        if conf().get("knowledge", True):
            self.description = (
                "Search agent's long-term memory and knowledge base using semantic and keyword search. "
                "Use this to recall past conversations, preferences, and knowledge pages."
            )
    
    def execute(self, args: dict):
        """
        Execute memory search
        
        Args:
            args: Dictionary with query, max_results, min_score
            
        Returns:
            ToolResult with formatted search results
        """
        from agent.tools.base_tool import ToolResult
        import asyncio
        import threading
        
        query = args.get("query")
        max_results = args.get("max_results", 10)
        min_score = args.get("min_score", 0.1)
        graph_mode = str(args.get("graph_mode", "compact") or "compact").lower()
        
        if not query:
            return ToolResult.fail("Error: query parameter is required")
        
        try:
            graph_plan = self._build_graph_query_plan(query)
            search_query = graph_plan.get("search_query", query) if graph_plan else query
            search_coro = self.memory_manager.search(
                query=search_query,
                user_id=self.user_id,
                max_results=max_results,
                min_score=min_score,
                include_shared=True
            )
            try:
                asyncio.get_running_loop()
                running = True
            except RuntimeError:
                running = False

            if running:
                box = {"results": None, "error": None}

                def _run_search():
                    try:
                        box["results"] = asyncio.run(search_coro)
                    except Exception as exc:
                        box["error"] = exc

                thread = threading.Thread(target=_run_search, daemon=True)
                thread.start()
                thread.join()
                if box["error"] is not None:
                    raise box["error"]
                results = box["results"] or []
            else:
                results = asyncio.run(search_coro)
            
            if not results:
                graph_fallback = self._build_graph_no_result_fallback(query, graph_plan, graph_mode)
                if graph_fallback:
                    return ToolResult.success(graph_fallback)
                # Return clear message that no memories exist yet
                # This prevents infinite retry loops
                return ToolResult.success(
                    f"No memories found for '{query}'. "
                    f"This is normal if no memories have been stored yet. "
                    f"You can store new memories by writing to MEMORY.md or memory/YYYY-MM-DD.md; "
                    f"these paths are routed to the system memory directory."
                )

            if graph_plan:
                results = self._apply_graph_plan(results, graph_plan)
            results = self._select_results_for_context(query, results, max_results)
            self._record_long_term_usage(query, results)
            
            # Format results
            output = [f"Found {len(results)} relevant memories:\n"]
            conflict_notes = self._build_conflict_notes(results)
            if conflict_notes:
                output.append("Conflict notes:")
                output.extend(f"- {note}" for note in conflict_notes)
            planner_notes = self._build_graph_planner_notes(graph_plan)
            if planner_notes:
                output.append("Graph planner:")
                output.extend(planner_notes)
            graph_notes = [] if graph_mode == "compact" else self._build_graph_navigation(query, graph_plan)
            if graph_notes:
                output.append("Graph navigation:")
                output.extend(graph_notes)
            memory_notes = self._build_memory_use_notes(results)
            if memory_notes:
                output.append("Memory note:")
                output.extend(f"- {note}" for note in memory_notes)
            
            for i, result in enumerate(results, 1):
                metadata = getattr(result, "metadata", None) or {}
                layer = metadata.get("memory_layer", result.source)
                kind = metadata.get("path_kind", "")
                label = f"{layer}/{kind}".strip("/")
                temporal = metadata.get("temporal_scope", "unknown")
                authority = metadata.get("authority", "unknown")
                observed_at = metadata.get("observed_at", "")
                valid_from = metadata.get("valid_from", "")
                valid_until = metadata.get("valid_until", "") or "present"
                entity_key = metadata.get("entity_key", "")
                superseded_by = metadata.get("superseded_by", "")
                output.append(f"\n{i}. {result.path} (lines {result.start_line}-{result.end_line})")
                output.append(f"   Score: {result.score:.3f}")
                output.append(f"   Layer: {label}")
                if entity_key:
                    output.append(f"   Entity: {entity_key}")
                output.append(f"   Temporal: {temporal}")
                output.append(f"   Authority: {authority}")
                if superseded_by:
                    output.append(f"   Superseded by: {superseded_by}")
                if observed_at:
                    output.append(f"   Observed: {observed_at}")
                if valid_from or valid_until != "present":
                    output.append(f"   Valid: {valid_from or 'unknown'} -> {valid_until}")
                explanation = self._build_hit_explanation(query, result)
                output.append(f"   Hit reason: {explanation['reason']}")
                output.append(f"   Matched terms: {', '.join(explanation['matched_terms']) or 'none'}")
                output.append(f"   Confidence: {explanation['confidence']}")
                output.append(f"   Snippet: {result.snippet}")
            
            return ToolResult.success("\n".join(output))
            
        except Exception as e:
            return ToolResult.fail(f"Error searching memory: {str(e)}")

    def _build_graph_no_result_fallback(
        self,
        query: str,
        graph_plan: Optional[dict],
        graph_mode: str = "compact",
    ) -> str:
        if not graph_plan:
            return ""
        context = graph_plan.get("context") or {}
        reads = context.get("recommended_reads") or []
        if not reads:
            return ""
        compact_mode = graph_mode != "full"
        if compact_mode:
            lines = [f"No old-index result for '{query}'. MemoryGraph fallback:"]
        else:
            lines = [
                f"No old-index memories found for '{query}', but MemoryGraph found navigation hints.",
            ]
        planner_notes = self._build_graph_planner_notes(graph_plan)
        if planner_notes:
            lines.append("Graph planner:")
            if compact_mode:
                terms = graph_plan.get("hint_terms", [])
                planner_chars = graph_plan.get("planner_chars", 0)
                token_estimate = max(1, planner_chars // 4) if planner_chars else 0
                lines.append(f"- hints={len(terms)}, est_tokens={token_estimate}")
            else:
                lines.extend(planner_notes[:3])
        lines.append("Graph recommended reads:")
        read_limit = 3 if compact_mode else 5
        for item in reads[:read_limit]:
            lines.append(
                f"- {self._compact_graph_path(item.get('source_path', ''))} "
                f"({item.get('entity_key', '')}; {item.get('reason', '')})"
            )
        notes = context.get("graph_notes") or []
        if not compact_mode and notes:
            lines.append("Graph notes:")
            lines.extend(f"- {note}" for note in notes[:2])
        return "\n".join(lines)

    def _build_graph_query_plan(self, query: str) -> dict:
        if not self.system_root:
            return {}
        try:
            from agent.memory.graph import MemoryGraphService

            project_workspace = self._project_workspace()
            cache_key = self._graph_cache_key(query, project_workspace)
            cached = self._GRAPH_PLAN_CACHE.get(cache_key)
            now = __import__("time").time()
            if cached and cached.get("expires_at", 0) > now:
                plan = dict(cached.get("plan") or {})
                plan["cache_hit"] = True
                self.__class__._GRAPH_PLAN_CACHE_HITS += 1
                return plan

            self.__class__._GRAPH_PLAN_CACHE_MISSES += 1
            service = MemoryGraphService(self.system_root, project_workspace=project_workspace)
            try:
                status = service.status()
                context = service.context(
                    query,
                    limit=5,
                    sync=status.get("graph_dirty", True) or not status.get("last_sync_at"),
                )
                status = service.status()
            finally:
                service.close()
            if not context.get("matched_entities"):
                return {}

            hints = []
            for entity in context.get("matched_entities", [])[:5]:
                hints.append(entity)
            for node in (context.get("authoritative_nodes") or [])[:5]:
                hints.extend([
                    node.get("entity_key", ""),
                    node.get("source_path", ""),
                    node.get("title", ""),
                ])
            for item in (context.get("recommended_reads") or [])[:5]:
                hints.extend([item.get("source_path", ""), item.get("entity_key", "")])
            compact_hints = self._dedupe_terms(hints, max_terms=12)
            if not compact_hints:
                return {}

            search_query = f"{query}\nGraph planner hints: {' '.join(compact_hints)}"
            plan = {
                "context": context,
                "search_query": search_query,
                "hint_terms": compact_hints,
                "planner_chars": max(0, len(search_query) - len(query)),
                "cache_hit": False,
                "temporal_intent": self._graph_temporal_intent(query),
            }
            self._GRAPH_PLAN_CACHE[cache_key] = {
                "expires_at": __import__("time").time() + self._GRAPH_PLAN_CACHE_TTL_SECONDS,
                "graph_revision": status.get("graph_revision", 0),
                "plan": plan,
            }
            return plan
        except Exception:
            return {}

    @classmethod
    def clear_graph_plan_cache(cls, system_root: Optional[str] = None, project_workspace: str = "") -> None:
        if not system_root:
            cls._GRAPH_PLAN_CACHE.clear()
            cls._GRAPH_PLAN_CACHE_HITS = 0
            cls._GRAPH_PLAN_CACHE_MISSES = 0
            return
        root_key = str(system_root or "").replace("\\", "/").lower()
        workspace_key = str(project_workspace or "").replace("\\", "/").lower()
        for key in list(cls._GRAPH_PLAN_CACHE.keys()):
            if key[0] != root_key:
                continue
            if workspace_key and key[1] != workspace_key:
                continue
            cls._GRAPH_PLAN_CACHE.pop(key, None)

    @classmethod
    def graph_plan_cache_stats(cls) -> dict:
        total = cls._GRAPH_PLAN_CACHE_HITS + cls._GRAPH_PLAN_CACHE_MISSES
        return {
            "entries": len(cls._GRAPH_PLAN_CACHE),
            "hits": cls._GRAPH_PLAN_CACHE_HITS,
            "misses": cls._GRAPH_PLAN_CACHE_MISSES,
            "hit_rate": round(cls._GRAPH_PLAN_CACHE_HITS / total, 4) if total else 0.0,
            "ttl_seconds": cls._GRAPH_PLAN_CACHE_TTL_SECONDS,
        }

    def _build_graph_navigation(self, query: str, graph_plan: Optional[dict] = None) -> list:
        if not self.system_root:
            return []
        try:
            context = (graph_plan or {}).get("context")
            if not context:
                from agent.memory.graph import MemoryGraphService

                service = MemoryGraphService(
                    self.system_root,
                    project_workspace=self._project_workspace(),
                )
                try:
                    context = service.context(query, limit=5)
                finally:
                    service.close()
            if not context.get("matched_entities"):
                return []
            notes = []
            temporal_intent = (graph_plan or {}).get("temporal_intent", "")
            first_key = "historical_nodes" if temporal_intent == "history" else "authoritative_nodes"
            second_key = "authoritative_nodes" if temporal_intent == "history" else "historical_nodes"
            first_label = "historical" if temporal_intent == "history" else "authoritative"
            second_label = "authoritative" if temporal_intent == "history" else "historical"
            for node in context.get(first_key, [])[:3]:
                reason = "/".join(
                    part for part in (node.get("temporal_scope"), node.get("authority")) if part
                )
                notes.append(
                    f"- {first_label}: {node.get('entity_key', '')} "
                    f"[{reason or 'unknown'}] {self._compact_graph_path(node.get('source_path', ''))}"
                )
            for node in context.get(second_key, [])[:2]:
                reason = "/".join(
                    part for part in (node.get("temporal_scope"), node.get("authority")) if part
                )
                notes.append(
                    f"- {second_label}: {node.get('entity_key', '')} "
                    f"[{reason or 'unknown'}] {self._compact_graph_path(node.get('source_path', ''))}"
                )
            for item in context.get("recommended_reads", [])[:3]:
                notes.append(f"- read: {self._compact_graph_path(item.get('source_path', ''))} ({item.get('reason', '')})")
            return notes[:8]
        except Exception:
            return []

    @staticmethod
    def _build_graph_planner_notes(graph_plan: Optional[dict]) -> list:
        if not graph_plan:
            return []
        terms = graph_plan.get("hint_terms", [])
        planner_chars = graph_plan.get("planner_chars", 0)
        token_estimate = max(1, planner_chars // 4) if planner_chars else 0
        notes = [
            f"- old-index query expanded with {len(terms)} graph hint(s), ~{token_estimate} token estimate",
        ]
        if graph_plan.get("cache_hit"):
            notes.append("- graph planner cache hit; skipped graph context recomputation")
        if graph_plan.get("temporal_intent"):
            notes.append(f"- temporal intent: {graph_plan.get('temporal_intent')}")
        context = graph_plan.get("context") or {}
        conflicts = context.get("conflicts") or []
        if conflicts:
            notes.append("- current truth-file nodes are boosted over historical/snapshot nodes")
        return notes

    def _apply_graph_plan(self, results: list, graph_plan: Optional[dict]) -> list:
        if not results or not graph_plan:
            return results
        context = graph_plan.get("context") or {}
        authoritative_paths = {
            node.get("source_path", "")
            for node in context.get("authoritative_nodes", [])
            if node.get("temporal_scope") in {"current", "evergreen", "active"}
        }
        recommended_paths = {
            item.get("source_path", "")
            for item in context.get("recommended_reads", [])
        }
        historical_paths = {
            node.get("source_path", "")
            for node in context.get("historical_nodes", [])
        }
        temporal_intent = graph_plan.get("temporal_intent", "")

        def adjusted_score(result) -> float:
            metadata = getattr(result, "metadata", None) or {}
            score = float(getattr(result, "score", 0) or 0)
            path = str(getattr(result, "path", "") or "")
            boost = 0.0
            if temporal_intent == "history":
                if self._path_matches_any(path, historical_paths):
                    boost += 2.0
                elif self._path_matches_any(path, authoritative_paths):
                    boost -= 0.5
            elif self._path_matches_any(path, authoritative_paths):
                boost += 2.0
            elif self._path_matches_any(path, recommended_paths):
                boost += 1.0
            if temporal_intent != "history" and self._path_matches_any(path, historical_paths):
                boost -= 0.5
            if metadata.get("temporal_scope") in {"current", "evergreen", "active"}:
                boost += 0.25
            if metadata.get("authority") == "truth_file":
                boost += 0.25
            metadata["graph_planner_boost"] = round(boost, 3)
            result.metadata = metadata
            return score + boost

        return sorted(results, key=lambda item: (-adjusted_score(item), getattr(item, "path", "")))

    def _project_workspace(self) -> str:
        config = getattr(self.memory_manager, "config", None)
        if config and hasattr(config, "get_project_workspace"):
            try:
                return str(config.get_project_workspace())
            except Exception:
                return ""
        return ""

    @staticmethod
    def _graph_temporal_intent(query: str) -> str:
        text = (query or "").lower()
        history_markers = (
            "history", "historical", "previous", "old", "past", "snapshot", "version",
            "历史", "之前", "曾经", "过去", "旧版", "早期", "快照", "版本",
        )
        current_markers = (
            "current", "latest", "now", "status", "present",
            "当前", "最新", "现在", "状态", "目前",
        )
        if any(marker in text for marker in history_markers):
            return "history"
        if any(marker in text for marker in current_markers):
            return "current"
        return ""

    def _graph_cache_key(self, query: str, project_workspace: str) -> tuple:
        normalized_query = " ".join((query or "").lower().split())
        return (
            str(self.system_root or "").replace("\\", "/").lower(),
            str(project_workspace or "").replace("\\", "/").lower(),
            normalized_query,
        )

    @staticmethod
    def _dedupe_terms(terms: list, max_terms: int = 12) -> list:
        seen = set()
        result = []
        for term in terms:
            text = MemorySearchTool._compact_graph_path(term)
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
            if len(result) >= max_terms:
                break
        return result

    @staticmethod
    def _compact_graph_path(value: str) -> str:
        text = str(value or "").replace("\\", "/").strip()
        lower = text.lower()
        for marker in ("/textbooks/", "/memory/", "/knowledge/"):
            idx = lower.find(marker)
            if idx >= 0:
                return text[idx + 1:]
        return text

    @staticmethod
    def _path_matches_any(path: str, candidates: set) -> bool:
        normalized = path.replace("\\", "/").lower().strip()
        for candidate in candidates:
            c = str(candidate or "").replace("\\", "/").lower().strip()
            if c and (normalized == c or normalized.endswith(c) or c.endswith(normalized)):
                return True
        return False

    def _record_long_term_usage(self, query: str, results: list) -> None:
        if not self.system_root:
            return
        try:
            from agent.memory.service import MemoryService

            service = MemoryService(self.system_root)
            for result in results or []:
                metadata = getattr(result, "metadata", None) or {}
                if metadata.get("authority") != "long_term_memory":
                    continue
                key = metadata.get("memory_key") or self._memory_key_from_result(result)
                service.dispatch("record_usage", {"memory_key": key, "query": query})
        except Exception:
            return

    @staticmethod
    def _memory_key_from_result(result) -> str:
        text = f"{getattr(result, 'snippet', '')} {getattr(result, 'path', '')}"
        if any(term in text for term in ("简短", "简洁", "结论", "concise", "brief")):
            return "concise"
        if any(term in text for term in ("详细", "展开", "推理", "detail")):
            return "detail"
        return "long_term"

    @staticmethod
    def _build_conflict_notes(results) -> list:
        by_entity = {}
        for result in results or []:
            metadata = getattr(result, "metadata", None) or {}
            entity_key = metadata.get("entity_key") or metadata.get("book_id") or ""
            if not entity_key:
                continue
            by_entity.setdefault(entity_key, set()).add(metadata.get("temporal_scope") or "unknown")
        notes = []
        for entity_key, scopes in by_entity.items():
            if "current" in scopes and ({"historical", "expired"} & scopes):
                notes.append(
                    f"{entity_key}: current truth-file memory appears with historical/expired memories. "
                    "Prefer current unless the user explicitly asks for history."
                )
        return notes[:5]

    @staticmethod
    def _build_memory_use_notes(results) -> list:
        notes = []
        for result in results or []:
            metadata = getattr(result, "metadata", None) or {}
            override = metadata.get("temporary_override", "")
            if override == "detail_overrides_brevity":
                notes.append("A brevity preference was temporarily ignored because this turn asks for detail.")
            elif override == "brevity_overrides_detail":
                notes.append("A detail preference was temporarily ignored because this turn asks for a brief answer.")
        return notes[:3]

    @staticmethod
    def _build_hit_explanation(query: str, result) -> dict:
        import re

        metadata = getattr(result, "metadata", None) or {}
        query_terms = [
            term.lower()
            for term in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_-]{2,}", query or "")
            if len(term.strip()) >= 2
        ]
        haystack = " ".join([
            str(getattr(result, "path", "") or ""),
            str(getattr(result, "snippet", "") or ""),
            " ".join(str(t) for t in metadata.get("context_tags", []) or []),
            str(metadata.get("entity_key", "") or ""),
        ]).lower()
        matched = []
        for term in query_terms:
            if term in haystack and term not in matched:
                matched.append(term)
        confidence = "high" if getattr(result, "score", 0) >= 0.75 else "medium" if getattr(result, "score", 0) >= 0.4 else "low"
        reason_parts = []
        if metadata.get("authority"):
            reason_parts.append(f"authority={metadata.get('authority')}")
        if metadata.get("temporal_scope"):
            reason_parts.append(f"temporal={metadata.get('temporal_scope')}")
        if metadata.get("context_match"):
            reason_parts.append(f"context_match={metadata.get('context_match')}")
        if matched:
            reason_parts.append("query_terms_overlap")
        reason = "; ".join(reason_parts) or "score-ranked memory match"
        return {
            "reason": reason,
            "matched_terms": matched[:8],
            "confidence": confidence,
        }

    @staticmethod
    def _select_results_for_context(query: str, results: list, max_results: int, max_chars: int = 1800) -> list:
        """Keep authoritative memories prominent and cap noisy episodic layers."""
        if not results:
            return []

        debug_query = MemorySearchTool._is_debug_query(query)
        history_query = MemorySearchTool._is_history_query(query)
        caps = {
            "error_log": 3 if debug_query else 0,
            "process_log": 4 if history_query or debug_query else 1,
            "conversation": 4 if history_query else 1,
            "daily_summary": 4 if history_query else 2,
        }
        counts = {}
        selected = []
        used_chars = 0
        for result in results:
            metadata = getattr(result, "metadata", None) or {}
            authority = metadata.get("authority", "")
            cap = caps.get(authority)
            if cap is not None:
                seen = counts.get(authority, 0)
                if seen >= cap:
                    continue
                counts[authority] = seen + 1
            snippet_chars = len(getattr(result, "snippet", "") or "")
            if selected and used_chars + snippet_chars > max_chars:
                continue
            selected.append(result)
            used_chars += snippet_chars
            if len(selected) >= max_results:
                break

        if selected:
            return selected
        return results[:max(1, max_results)]

    @staticmethod
    def _is_debug_query(query: str) -> bool:
        text = (query or "").lower()
        markers = (
            "error", "failure", "failed", "bug", "fix", "exception", "traceback",
            "错误", "失败", "修复", "报错", "异常",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _is_history_query(query: str) -> bool:
        text = (query or "").lower()
        markers = (
            "history", "historical", "previous", "old", "past", "record",
            "历史", "之前", "曾经", "过去", "旧版", "早期", "记录",
        )
        return any(marker in text for marker in markers)
