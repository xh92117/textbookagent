import json
import os
import re
from typing import Any, Dict, List

from agent.knowledge.retriever import KnowledgeRetriever
from agent.knowledge.service import KnowledgeService
from agent.tools.base_tool import BaseTool, ToolResult


class KnowledgeQueryTool(BaseTool):
    name: str = "knowledge_query"
    description: str = (
        "Token-safe knowledge-base access tool over the existing LLM-WIKI index.json. "
        "Use metadata-first actions instead of reading whole documents. Actions: "
        "glob/list source-level inventory, search metadata without excerpts, peek "
        "top hit snippets, read_range selected chunks only, read_neighbors/read_section "
        "for local context, and pack a compact "
        "evidence pack for textbook writing."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of: glob, search, peek, read_range, read_neighbors, read_section, pack",
            },
            "book_id": {
                "type": "string",
                "description": "Optional textbook/knowledge base id, for example tb_3df776e0",
            },
            "query": {
                "type": "string",
                "description": "Search query or topic.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum returned items. Defaults to 8, max 30.",
            },
            "chunk_id": {
                "type": "string",
                "description": "Chunk id to read, for read_range.",
            },
            "path": {
                "type": "string",
                "description": "Knowledge relative path to read, for read_range.",
            },
            "offset": {
                "type": "integer",
                "description": "Character offset for read_range. Defaults to 0.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters for snippets/range. Defaults: peek 500, read_range 2500, hard max 8000.",
            },
            "include_excerpt": {
                "type": "boolean",
                "description": "Only for search/peek. Search defaults false; peek defaults true.",
            },
            "radius": {
                "type": "integer",
                "description": "For read_neighbors: number of adjacent chunks on each side. Defaults to 1, max 3.",
            },
            "section": {
                "type": "string",
                "description": "For read_section: section/title text to locate if chunk_id/path is not provided.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "")).strip().lower()
        book_id = str(args.get("book_id", "") or "").strip()
        query = str(args.get("query", "") or "").strip()
        limit = self._int(args.get("limit"), 8, 1, 30)

        if action not in {"glob", "search", "peek", "read_range", "read_neighbors", "read_section", "pack"}:
            return ToolResult.fail("action must be one of: glob, search, peek, read_range, read_neighbors, read_section, pack")

        try:
            if action == "glob":
                return ToolResult.success(self._glob(book_id=book_id, limit=limit))
            if action == "search":
                if not query:
                    return ToolResult.fail("query is required for search")
                max_chars = self._int(args.get("max_chars"), 0, 0, 8000)
                include_excerpt = bool(args.get("include_excerpt", False))
                return ToolResult.success(self._search(book_id, query, limit, max_chars if include_excerpt else 0))
            if action == "peek":
                if not query:
                    return ToolResult.fail("query is required for peek")
                max_chars = self._int(args.get("max_chars"), 500, 80, 1200)
                return ToolResult.success(self._search(book_id, query, limit, max_chars, mode="peek"))
            if action == "read_range":
                max_chars = self._int(args.get("max_chars"), 2500, 200, 8000)
                offset = self._int(args.get("offset"), 0, 0, 10_000_000)
                return ToolResult.success(self._read_range(book_id, args.get("chunk_id", ""), args.get("path", ""), offset, max_chars))
            if action == "read_neighbors":
                max_chars = self._int(args.get("max_chars"), 5000, 500, 12000)
                radius = self._int(args.get("radius"), 1, 0, 3)
                return ToolResult.success(self._read_neighbors(book_id, args.get("chunk_id", ""), args.get("path", ""), radius, max_chars))
            if action == "read_section":
                max_chars = self._int(args.get("max_chars"), 7000, 500, 16000)
                return ToolResult.success(self._read_section(book_id, args.get("chunk_id", ""), args.get("path", ""), args.get("section", ""), max_chars))
            if action == "pack":
                if not query:
                    return ToolResult.fail("query is required for pack")
                max_chars = self._int(args.get("max_chars"), 500, 120, 1200)
                return ToolResult.success(self._pack(book_id, query, limit, max_chars))
        except Exception as exc:
            return ToolResult.fail(f"knowledge_query error: {exc}")

        return ToolResult.fail("unhandled action")

    def _glob(self, book_id: str, limit: int) -> Dict[str, Any]:
        svc = KnowledgeService(self.cwd)
        base = svc._resolve_book_dir(book_id)
        retriever = KnowledgeRetriever(self.cwd, book_id) if book_id else None
        index = retriever.index if retriever else self._load_global_index(base)
        files = self._visible_files(svc, book_id, limit)
        canonical_index = f"knowledge/{book_id}/_llm_wiki/index.json" if book_id and index.get("chunks") else ""
        return {
            "mode": "glob",
            "book_id": book_id,
            "view": "source-level",
            "canonical_index": canonical_index,
            "stats": {
                "sources": len(index.get("sources", []) or []),
                "chunks": len(index.get("chunks", []) or []),
                "pages": len(index.get("pages", []) or []),
                "entities": len(index.get("entities", []) or []),
                "relations": len(index.get("relations", []) or []),
                "visible_files": len(files),
            },
            "files": files,
            "top_sources": [
                {
                    "id": s.get("id", ""),
                    "title": s.get("title") or s.get("name") or s.get("path", ""),
                    "path": s.get("path", ""),
                    "chunk_count": s.get("chunk_count", 0),
                }
                for s in (index.get("sources", []) or [])[:limit]
            ],
            "sample_pages": [
                {
                    "title": p.get("title", ""),
                    "summary": p.get("summary", ""),
                    "source_chunk_ids": (p.get("source_chunk_ids") or [])[:3],
                }
                for p in (index.get("pages", []) or [])[: min(limit, 8)]
            ],
            "rule": (
                "This is a source-level inventory built from the existing LLM-WIKI index.json. "
                "Internal chunks are retained for retrieval but hidden from glob to avoid "
                "context bloat. Use search/peek next; do not read entire documents or enumerate all chunk files."
            ),
        }

    def _search(self, book_id: str, query: str, limit: int, excerpt_chars: int, mode: str = "search") -> Dict[str, Any]:
        retriever = self._retriever(book_id)
        results = retriever.retrieve(query, limit=limit, excerpt_chars=excerpt_chars, use_cache=True)
        return {
            "mode": mode,
            "book_id": book_id,
            "query": query,
            "count": len(results),
            "results": [self._compact_hit(item, include_excerpt=excerpt_chars > 0) for item in results],
            "next": (
                "Use read_neighbors/read_section when local context is needed; use read_range "
                "only for exact quotes, formulas, tables, or source verification; use pack for chapter-writing evidence."
            ),
        }

    def _read_range(self, book_id: str, chunk_id: Any, path: Any, offset: int, max_chars: int) -> Dict[str, Any]:
        retriever = self._retriever(book_id)
        chunk = self._find_chunk(retriever, str(chunk_id or ""), str(path or ""))
        if not chunk:
            raise ValueError("chunk_id or path not found")
        rel_path = chunk.get("path", "")
        full_path = self._safe_wiki_path(retriever, rel_path)
        with open(full_path, "r", encoding="utf-8") as f:
            text = f.read()
        text = self._strip_frontmatter(text)
        total = len(text)
        offset = min(offset, total)
        content = text[offset:offset + max_chars]
        return {
            "mode": "read_range",
            "book_id": book_id,
            "chunk_id": chunk.get("id", ""),
            "title": chunk.get("title", ""),
            "section": chunk.get("section", ""),
            "path": rel_path,
            "offset": offset,
            "max_chars": max_chars,
            "total_chars": total,
            "truncated": offset + max_chars < total,
            "content": content,
            "citation": f"knowledge/{book_id}/_llm_wiki/{rel_path}" if book_id else f"knowledge/_llm_wiki/{rel_path}",
        }

    def _read_neighbors(self, book_id: str, chunk_id: Any, path: Any, radius: int, max_chars: int) -> Dict[str, Any]:
        retriever = self._retriever(book_id)
        chunks = retriever.index.get("chunks", []) or []
        chunk = self._find_chunk(retriever, str(chunk_id or ""), str(path or ""))
        if not chunk:
            raise ValueError("chunk_id or path not found")
        idx = chunks.index(chunk)
        start = max(0, idx - radius)
        end = min(len(chunks), idx + radius + 1)
        selected = chunks[start:end]
        content_parts = []
        used = 0
        for item in selected:
            text = self._read_chunk_text(retriever, item)
            remaining = max_chars - used
            if remaining <= 0:
                break
            snippet = text[:remaining]
            used += len(snippet)
            content_parts.append(f"## {item.get('title', item.get('id', ''))}\n\n{snippet}")
        return {
            "mode": "read_neighbors",
            "book_id": book_id,
            "center_chunk_id": chunk.get("id", ""),
            "radius": radius,
            "chunk_ids": [item.get("id", "") for item in selected],
            "sections": [item.get("section", "") for item in selected],
            "max_chars": max_chars,
            "truncated": used >= max_chars,
            "content": "\n\n---\n\n".join(content_parts),
        }

    def _read_section(self, book_id: str, chunk_id: Any, path: Any, section: Any, max_chars: int) -> Dict[str, Any]:
        retriever = self._retriever(book_id)
        chunks = retriever.index.get("chunks", []) or []
        anchor = self._find_chunk(retriever, str(chunk_id or ""), str(path or ""))
        section_text = str(section or "").strip().lower()
        if not anchor and section_text:
            for chunk in chunks:
                haystack = " ".join([str(chunk.get("title", "")), str(chunk.get("section", ""))]).lower()
                if section_text in haystack:
                    anchor = chunk
                    break
        if not anchor:
            raise ValueError("chunk_id/path/section not found")
        target_section = anchor.get("section") or anchor.get("title", "")
        same = [
            chunk for chunk in chunks
            if (chunk.get("section") or chunk.get("title", "")) == target_section
            or str(chunk.get("title", "")).startswith(str(target_section))
        ]
        if not same:
            same = [anchor]
        content_parts = []
        used = 0
        for item in same:
            text = self._read_chunk_text(retriever, item)
            remaining = max_chars - used
            if remaining <= 0:
                break
            snippet = text[:remaining]
            used += len(snippet)
            content_parts.append(f"## {item.get('title', item.get('id', ''))}\n\n{snippet}")
        return {
            "mode": "read_section",
            "book_id": book_id,
            "section": target_section,
            "chunk_ids": [item.get("id", "") for item in same],
            "max_chars": max_chars,
            "truncated": used >= max_chars,
            "content": "\n\n---\n\n".join(content_parts),
        }

    def _pack(self, book_id: str, query: str, limit: int, excerpt_chars: int) -> Dict[str, Any]:
        retriever = self._retriever(book_id)
        text = retriever.format_compact_evidence_pack(
            query,
            metadata_limit=limit,
            excerpt_limit=min(3, limit),
            excerpt_chars=excerpt_chars,
        )
        hits = retriever.retrieve(query, limit=limit, excerpt_chars=0, use_cache=True)
        return {
            "mode": "pack",
            "book_id": book_id,
            "query": query,
            "evidence_pack": text,
            "citations": [f"knowledge/{book_id}/_llm_wiki/{h.get('path', '')}" for h in hits if h.get("path")],
            "rule": "Use this evidence pack for drafting. Read_range only for exact quotes, formulas, tables, or source verification.",
        }

    def _retriever(self, book_id: str) -> KnowledgeRetriever:
        if not book_id:
            raise ValueError("book_id is required for indexed retrieval. Use glob to inspect available knowledge bases.")
        retriever = KnowledgeRetriever(self.cwd, book_id)
        if not retriever.index.get("chunks"):
            raise ValueError(f"no LLM-WIKI chunks found for book_id={book_id}; organize knowledge first")
        return retriever

    @staticmethod
    def _compact_hit(item: Dict[str, Any], include_excerpt: bool) -> Dict[str, Any]:
        hit = {
            "chunk_id": item.get("chunk_id", ""),
            "score": item.get("score", 0),
            "title": item.get("title", ""),
            "section": item.get("section", ""),
            "summary": item.get("summary", ""),
            "use_when": item.get("use_when", ""),
            "keywords": item.get("keywords", [])[:8],
            "entities": item.get("entities", [])[:8],
            "path": item.get("path", ""),
            "citation": f"knowledge/_llm_wiki/{item.get('path', '')}",
            "graph_reason": item.get("graph_reason", ""),
        }
        if include_excerpt:
            hit["excerpt"] = item.get("excerpt", "")
        return hit

    @staticmethod
    def _find_chunk(retriever: KnowledgeRetriever, chunk_id: str, path: str) -> Dict[str, Any]:
        path = path.replace("\\", "/").strip()
        for chunk in retriever.index.get("chunks", []) or []:
            if chunk_id and chunk.get("id") == chunk_id:
                return chunk
            if path and chunk.get("path", "").replace("\\", "/") == path:
                return chunk
        return {}

    @classmethod
    def _read_chunk_text(cls, retriever: KnowledgeRetriever, chunk: Dict[str, Any]) -> str:
        full_path = cls._safe_wiki_path(retriever, chunk.get("path", ""))
        with open(full_path, "r", encoding="utf-8") as f:
            return cls._strip_frontmatter(f.read())

    @staticmethod
    def _safe_wiki_path(retriever: KnowledgeRetriever, rel_path: str) -> str:
        if not rel_path or ".." in rel_path:
            raise ValueError("invalid chunk path")
        full_path = os.path.normpath(os.path.join(retriever.wiki_dir, rel_path))
        allowed = os.path.normpath(retriever.wiki_dir)
        if not full_path.startswith(allowed + os.sep) and full_path != allowed:
            raise ValueError("path outside wiki dir")
        if not os.path.isfile(full_path):
            raise FileNotFoundError(rel_path)
        return full_path

    @staticmethod
    def _strip_frontmatter(text: str) -> str:
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                text = parts[2]
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def _load_global_index(base: str) -> Dict[str, List]:
        path = os.path.join(base, "_llm_wiki", "index.json")
        if not os.path.isfile(path):
            path = os.path.join(base, "index.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {"sources": [], "chunks": [], "pages": [], "entities": [], "relations": []}

    @staticmethod
    def _visible_files(svc: KnowledgeService, book_id: str, limit: int) -> List[Dict[str, Any]]:
        page = svc.list_files_page(book_id=book_id, limit=min(300, max(limit * 4, limit))).get("files", [])
        visible = []
        for item in page:
            path = (item.get("path") or "").replace("\\", "/")
            if (
                path.startswith("_llm_wiki/chunks/")
                or "/_llm_wiki/chunks/" in path
                or path.startswith("_llm_wiki/cache/")
                or "/_llm_wiki/cache/" in path
                or path == "_llm_wiki/index.json"
                or path == "_llm_wiki/graph.json"
            ):
                continue
            visible.append(item)
            if len(visible) >= limit:
                break
        return visible

    @staticmethod
    def _int(value: Any, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(value)
        except Exception:
            value = default
        return min(max_value, max(min_value, value))
