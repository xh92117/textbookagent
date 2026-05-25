"""
Memory search tool

Allows agents to search their memory using semantic and keyword search
"""

from typing import Dict, Any, Optional
from agent.tools.base_tool import BaseTool


class MemorySearchTool(BaseTool):
    """Tool for searching agent memory"""
    
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
            }
        },
        "required": ["query"]
    }
    
    def __init__(self, memory_manager, user_id: Optional[str] = None):
        """
        Initialize memory search tool
        
        Args:
            memory_manager: MemoryManager instance
            user_id: Optional user ID for scoped search
        """
        super().__init__()
        self.memory_manager = memory_manager
        self.user_id = user_id

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
        
        if not query:
            return ToolResult.fail("Error: query parameter is required")
        
        try:
            search_coro = self.memory_manager.search(
                query=query,
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
                # Return clear message that no memories exist yet
                # This prevents infinite retry loops
                return ToolResult.success(
                    f"No memories found for '{query}'. "
                    f"This is normal if no memories have been stored yet. "
                    f"You can store new memories by writing to MEMORY.md or memory/YYYY-MM-DD.md; "
                    f"these paths are routed to the system memory directory."
                )
            
            # Format results
            output = [f"Found {len(results)} relevant memories:\n"]
            conflict_notes = self._build_conflict_notes(results)
            if conflict_notes:
                output.append("Conflict notes:")
                output.extend(f"- {note}" for note in conflict_notes)
            
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
                output.append(f"   Snippet: {result.snippet}")
            
            return ToolResult.success("\n".join(output))
            
        except Exception as e:
            return ToolResult.fail(f"Error searching memory: {str(e)}")

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
