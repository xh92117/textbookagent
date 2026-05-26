"""
Memory manager for AgentMesh

Provides high-level interface for memory operations
"""

import os
from typing import List, Optional, Dict, Any
from pathlib import Path
import hashlib
from datetime import datetime, timedelta

from agent.memory.config import MemoryConfig, get_default_memory_config
from agent.memory.storage import MemoryStorage, MemoryChunk, SearchResult
from agent.memory.chunker import TextChunker
from agent.memory.embedding import create_embedding_provider, EmbeddingProvider
from agent.memory.summarizer import MemoryFlushManager, create_memory_files_if_needed


class MemoryManager:
    """
    Memory manager with hybrid search capabilities
    
    Provides long-term memory for agents with vector and keyword search
    """
    
    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        llm_model: Optional[Any] = None
    ):
        """
        Initialize memory manager
        
        Args:
            config: Memory configuration (uses global config if not provided)
            embedding_provider: Custom embedding provider (optional)
            llm_model: LLM model for summarization (optional)
        """
        self.config = config or get_default_memory_config()
        
        # Initialize storage
        db_path = self.config.get_db_path()
        self.storage = MemoryStorage(db_path)
        
        # Initialize chunker
        self.chunker = TextChunker(
            max_tokens=self.config.chunk_max_tokens,
            overlap_tokens=self.config.chunk_overlap_tokens
        )
        
        # Initialize embedding provider (optional, prefer OpenAI, fallback to LinkAI)
        self.embedding_provider = None
        if embedding_provider:
            self.embedding_provider = embedding_provider
        else:
            # Try OpenAI first
            try:
                api_key = os.environ.get('OPENAI_API_KEY')
                api_base = os.environ.get('OPENAI_API_BASE')
                if api_key:
                    self.embedding_provider = create_embedding_provider(
                        provider="openai",
                        model=self.config.embedding_model,
                        api_key=api_key,
                        api_base=api_base
                    )
            except Exception as e:
                from common.log import logger
                logger.warning(f"[MemoryManager] OpenAI embedding failed: {e}")

            # Fallback to LinkAI
            if self.embedding_provider is None:
                try:
                    linkai_key = os.environ.get('LINKAI_API_KEY')
                    linkai_base = os.environ.get('LINKAI_API_BASE', 'https://api.link-ai.tech')
                    if linkai_key:
                        from common.utils import get_cloud_headers
                        cloud_headers = get_cloud_headers(linkai_key)
                        cloud_headers.pop("Authorization", None)
                        self.embedding_provider = create_embedding_provider(
                            provider="linkai",
                            model=self.config.embedding_model,
                            api_key=linkai_key,
                            api_base=f"{linkai_base}/v1",
                            extra_headers=cloud_headers,
                        )
                except Exception as e:
                    from common.log import logger
                    logger.warning(f"[MemoryManager] LinkAI embedding failed: {e}")

            if self.embedding_provider is None:
                from common.log import logger
                logger.info(f"[MemoryManager] Memory will work with keyword search only (no vector search)")
        
        # Initialize memory flush manager
        workspace_dir = self.config.get_workspace()
        self.flush_manager = MemoryFlushManager(
            workspace_dir=workspace_dir,
            llm_model=llm_model
        )
        
        # Ensure workspace directories exist
        self._init_workspace()
        
        self._dirty = False
    
    def _init_workspace(self):
        """Initialize workspace directories"""
        memory_dir = self.config.get_memory_dir()
        memory_dir.mkdir(parents=True, exist_ok=True)
        
        # Create default memory files
        workspace_dir = self.config.get_workspace()
        create_memory_files_if_needed(workspace_dir)
    
    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        max_results: Optional[int] = None,
        min_score: Optional[float] = None,
        include_shared: bool = True
    ) -> List[SearchResult]:
        """
        Search memory with hybrid search (vector + keyword)
        
        Args:
            query: Search query
            user_id: User ID for scoped search
            max_results: Maximum results to return
            min_score: Minimum score threshold
            include_shared: Include shared memories
            
        Returns:
            List of search results sorted by relevance
        """
        max_results = max_results or self.config.max_results
        min_score = min_score or self.config.min_score
        
        # Determine scopes
        scopes = []
        if include_shared:
            scopes.append("shared")
        if user_id:
            scopes.append("user")
        
        if not scopes:
            return []
        
        # Sync if needed
        if self.config.sync_on_search and self._dirty:
            await self.sync()
        
        # Perform vector search (if embedding provider available)
        vector_results = []
        if self.embedding_provider:
            try:
                from common.log import logger
                query_embedding = self.embedding_provider.embed(query)
                vector_results = self.storage.search_vector(
                    query_embedding=query_embedding,
                    user_id=user_id,
                    scopes=scopes,
                    limit=max_results * 2  # Get more candidates for merging
                )
                logger.info(f"[MemoryManager] Vector search found {len(vector_results)} results for query: {query}")
            except Exception as e:
                from common.log import logger
                logger.warning(f"[MemoryManager] Vector search failed: {e}")
        
        # Perform keyword search
        keyword_results = self.storage.search_keyword(
            query=query,
            user_id=user_id,
            scopes=scopes,
            limit=max_results * 2
        )
        from common.log import logger
        logger.info(f"[MemoryManager] Keyword search found {len(keyword_results)} results for query: {query}")
        
        # Merge results
        merged = self._merge_results(
            vector_results,
            keyword_results,
            self.config.vector_weight,
            self.config.keyword_weight
        )
        
        reranked = self._rerank_results(query, merged)
        reranked = self._prioritize_context_tags(query, reranked)
        reranked = self._resolve_authoritative_results(query, reranked)
        compressed = [self._compress_search_result(r) for r in reranked if r.score >= min_score]
        return compressed[:max_results]
    
    async def add_memory(
        self,
        content: str,
        user_id: Optional[str] = None,
        scope: str = "shared",
        source: str = "memory",
        path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Add new memory content
        
        Args:
            content: Memory content
            user_id: User ID for user-scoped memory
            scope: Memory scope ("shared", "user", "session")
            source: Memory source ("memory" or "session")
            path: File path (auto-generated if not provided)
            metadata: Additional metadata
        """
        if not content.strip():
            return
        
        # Generate path if not provided
        if not path:
            content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()[:8]
            if user_id and scope == "user":
                path = f"memory/users/{user_id}/memory_{content_hash}.md"
            else:
                path = f"memory/shared/memory_{content_hash}.md"
        
        # Chunk content
        chunks = self.chunker.chunk_text(content)
        
        # Generate embeddings (if provider available)
        texts = [chunk.text for chunk in chunks]
        if self.embedding_provider:
            embeddings = self.embedding_provider.embed_batch(texts)
        else:
            # No embeddings, just use None
            embeddings = [None] * len(texts)
        
        # Create memory chunks
        memory_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            chunk_id = self._generate_chunk_id(path, chunk.start_line, chunk.end_line)
            chunk_hash = MemoryStorage.compute_hash(chunk.text)
            
            memory_chunks.append(MemoryChunk(
                id=chunk_id,
                user_id=user_id,
                scope=scope,
                source=source,
                path=path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                text=chunk.text,
                embedding=embedding,
                hash=chunk_hash,
                metadata=self._with_temporal_metadata(path, source, metadata or self._classify_memory(path, source))
            ))
        
        # Save to storage
        self.storage.save_chunks_batch(memory_chunks)
        
        # Update file metadata
        file_hash = MemoryStorage.compute_hash(content)
        self.storage.update_file_metadata(
            path=path,
            source=source,
            file_hash=file_hash,
            mtime=int(os.path.getmtime(__file__)),  # Use current time
            size=len(content)
        )
    
    async def sync(self, force: bool = False):
        """
        Synchronize memory from files
        
        Args:
            force: Force full reindex
        """
        memory_dir = self.config.get_memory_dir()
        workspace_dir = self.config.get_workspace()
        self.storage.delete_windows_style_paths()
        seen_paths = set()
        
        # Scan system MEMORY.md. Project-level MEMORY.md is indexed below as a
        # workspace profile, not as the agent's durable memory store.
        memory_file = memory_dir / "MEMORY.md"
        if memory_file.exists():
            rel = await self._sync_file(memory_file, "memory", "shared", None)
            if rel:
                seen_paths.add(rel)
        
        # Scan memory directory (including daily summaries)
        if memory_dir.exists():
            for file_path in memory_dir.rglob("*.md"):
                if file_path == memory_file:
                    continue
                # Skip hidden directories (e.g. .dreams/)
                if any(part.startswith('.') for part in file_path.relative_to(workspace_dir).parts):
                    continue

                # Determine scope and user_id from path
                rel_path = file_path.relative_to(workspace_dir)
                parts = rel_path.parts
                
                # Check if it's in daily summary directory
                if "daily" in parts:
                    # Daily summary files
                    if "users" in parts or len(parts) > 3:
                        # User-scoped daily summary: memory/daily/{user_id}/2024-01-29.md
                        user_idx = parts.index("daily") + 1
                        user_id = parts[user_idx] if user_idx < len(parts) else None
                        scope = "user"
                    else:
                        # Shared daily summary: memory/daily/2024-01-29.md
                        user_id = None
                        scope = "shared"
                elif "users" in parts:
                    # User-scoped memory
                    user_idx = parts.index("users") + 1
                    user_id = parts[user_idx] if user_idx < len(parts) else None
                    scope = "user"
                else:
                    # Shared memory
                    user_id = None
                    scope = "shared"
                
                rel = await self._sync_file(file_path, "memory", scope, user_id)
                if rel:
                    seen_paths.add(rel)

        project_workspace_dir = self.config.get_project_workspace()

        # Scan workspace-root profile files. They are injected once as compact
        # startup memory and remain available later through memory_search/get.
        for root_name in ("AGENT.md", "USER.md", "RULE.md", "MEMORY.md"):
            root_file = Path(project_workspace_dir) / root_name
            if root_file.exists() and root_file.is_file():
                rel = await self._sync_file(root_file, "workspace_profile", "shared", None)
                if rel:
                    seen_paths.add(rel)

        # Scan knowledge directory (structured knowledge wiki)
        from config import conf
        if conf().get("knowledge", True):
            knowledge_dir = Path(project_workspace_dir) / "knowledge"
            if knowledge_dir.exists():
                for file_path in knowledge_dir.rglob("*.md"):
                    rel = await self._sync_file(file_path, "knowledge", "shared", None)
                    if rel:
                        seen_paths.add(rel)

        # Scan textbook truth files and generated chapters. This lets agents
        # recall textbook status/outline/summaries through memory_search
        # without loading the whole workspace into context.
        textbooks_dir = Path(project_workspace_dir) / "textbooks"
        if textbooks_dir.exists():
            for file_path in self._iter_textbook_memory_files(textbooks_dir):
                rel = await self._sync_file(file_path, "textbook", "shared", None)
                if rel:
                    seen_paths.add(rel)

        self._cleanup_stale_file_indexes(seen_paths)
        
        self._dirty = False

    def _iter_textbook_memory_files(self, textbooks_dir: Path):
        allowed_suffixes = {".md", ".json"}
        skipped_parts = {"assets", "snapshots", "__pycache__"}
        for file_path in textbooks_dir.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in allowed_suffixes:
                continue
            rel_parts = set(file_path.relative_to(textbooks_dir).parts)
            if rel_parts & skipped_parts:
                continue
            # Keep machine state, outline, chapter metadata and chapter bodies
            # searchable; binary media and snapshots stay out of the memory DB.
            yield file_path
    
    async def _sync_file(
        self,
        file_path: Path,
        source: str,
        scope: str,
        user_id: Optional[str]
    ) -> Optional[str]:
        """Sync a single file"""
        # Compute file hash
        content = file_path.read_text(encoding='utf-8')
        file_hash = MemoryStorage.compute_hash(content)
        
        # Get relative path
        workspace_dir = self.config.get_workspace()
        try:
            rel_path = file_path.relative_to(workspace_dir).as_posix()
        except ValueError:
            project_workspace_dir = self.config.get_project_workspace()
            rel_path = file_path.relative_to(project_workspace_dir).as_posix()
        
        # Check if file changed
        stored_hash = self.storage.get_file_hash(rel_path)
        if stored_hash == file_hash:
            return rel_path  # No changes
        
        # Delete old chunks
        self.storage.delete_by_path(rel_path)
        
        # Chunk and embed
        chunks = self.chunker.chunk_text(content)
        if not chunks:
            self.storage.delete_by_path(rel_path)
            return rel_path
        
        texts = [chunk.text for chunk in chunks]
        if self.embedding_provider:
            embeddings = self.embedding_provider.embed_batch(texts)
        else:
            embeddings = [None] * len(texts)
        
        # Create memory chunks
        memory_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            chunk_id = self._generate_chunk_id(rel_path, chunk.start_line, chunk.end_line)
            chunk_hash = MemoryStorage.compute_hash(chunk.text)
            
            memory_chunks.append(MemoryChunk(
                id=chunk_id,
                user_id=user_id,
                scope=scope,
                source=source,
                path=rel_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                text=chunk.text,
                embedding=embedding,
                hash=chunk_hash,
                metadata=self._with_temporal_metadata(
                    rel_path,
                    source,
                    self._classify_memory(rel_path, source),
                    observed_at=datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                )
            ))
        
        # Save
        self.storage.save_chunks_batch(memory_chunks)
        
        # Update file metadata
        stat = file_path.stat()
        self.storage.update_file_metadata(
            path=rel_path,
            source=source,
            file_hash=file_hash,
            mtime=int(stat.st_mtime),
            size=stat.st_size
        )
        return rel_path

    def _cleanup_stale_file_indexes(self, seen_paths: set):
        """Remove stale file-backed memory rows whose source file is no longer present."""
        stale = []
        for record in self.storage.list_file_records():
            path = (record.get("path") or "").replace("\\", "/")
            source = record.get("source") or ""
            if path in seen_paths:
                continue
            if self._is_managed_file_index(path, source):
                stale.append(path)
        if stale:
            self.storage.delete_paths(stale)

    @staticmethod
    def _is_managed_file_index(path: str, source: str) -> bool:
        if source in {"textbook", "knowledge", "workspace_profile"}:
            return True
        if source != "memory":
            return False
        lower = (path or "").lower()
        if lower == "memory/memory.md" or lower == "memory.md":
            return True
        if lower.startswith(("memory/processes/", "memory/sessions/", "memory/errors/", "memory/short_term/", "memory/candidates/")):
            return True
        if MemoryManager._is_dated_memory_path(lower):
            return True
        return False
    
    def flush_memory(
        self,
        messages: list,
        user_id: Optional[str] = None,
        reason: str = "threshold",
        max_messages: int = 10,
        context_summary_callback=None,
    ) -> bool:
        """
        Flush conversation summary to daily memory file.

        Args:
            messages: Conversation message list
            user_id: Optional user ID
            reason: "threshold" | "overflow" | "daily_summary"
            max_messages: Max recent messages to include (0 = all)
            context_summary_callback: Optional callback(str) invoked with the
                daily summary text for in-context injection

        Returns:
            True if flush was dispatched
        """
        success = self.flush_manager.flush_from_messages(
            messages=messages,
            user_id=user_id,
            reason=reason,
            max_messages=max_messages,
            context_summary_callback=context_summary_callback,
        )
        if success:
            self._dirty = True
        return success
    
    def get_status(self) -> Dict[str, Any]:
        """Get memory status"""
        stats = self.storage.get_stats()
        return {
            'chunks': stats['chunks'],
            'files': stats['files'],
            'workspace': str(self.config.get_workspace()),
            'dirty': self._dirty,
            'embedding_enabled': self.embedding_provider is not None,
            'embedding_provider': self.config.embedding_provider if self.embedding_provider else 'disabled',
            'embedding_model': self.config.embedding_model if self.embedding_provider else 'N/A',
            'search_mode': 'hybrid (vector + keyword)' if self.embedding_provider else 'keyword only (FTS5)'
        }
    
    def mark_dirty(self):
        """Mark memory as dirty (needs sync)"""
        self._dirty = True
        try:
            from agent.memory.graph import MemoryGraphService

            system_root = str(self.config.get_workspace())
            project_workspace = ""
            if hasattr(self.config, "get_project_workspace"):
                project_workspace = str(self.config.get_project_workspace())
            service = MemoryGraphService(system_root, project_workspace=project_workspace)
            try:
                service.mark_dirty("memory manager marked dirty")
            finally:
                service.close()
        except Exception:
            pass
    
    def close(self):
        """Close memory manager and release resources"""
        self.storage.close()
    
    # Helper methods
    
    def _generate_chunk_id(self, path: str, start_line: int, end_line: int) -> str:
        """Generate unique chunk ID"""
        content = f"{path}:{start_line}:{end_line}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    @staticmethod
    def _compute_temporal_decay(path: str, half_life_days: float = 30.0) -> float:
        """
        Compute temporal decay multiplier for dated memory files.
        
        Inspired by OpenClaw's temporal-decay: exponential decay based on file date.
        MEMORY.md and non-dated files are "evergreen" (no decay, multiplier=1.0).
        Daily files like memory/2025-03-01.md decay based on age.
        
        Formula: multiplier = exp(-ln2/half_life * age_in_days)
        """
        import re
        import math
        
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})\.md$', path)
        if not match:
            return 1.0  # evergreen: MEMORY.md, non-dated files
        
        try:
            file_date = datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
            age_days = (datetime.now() - file_date).days
            if age_days <= 0:
                return 1.0
            
            decay_lambda = math.log(2) / half_life_days
            return math.exp(-decay_lambda * age_days)
        except (ValueError, OverflowError):
            return 1.0
    
    def _merge_results(
        self,
        vector_results: List[SearchResult],
        keyword_results: List[SearchResult],
        vector_weight: float,
        keyword_weight: float
    ) -> List[SearchResult]:
        """Merge vector and keyword search results with temporal decay for dated files"""
        merged_map = {}
        
        for result in vector_results:
            key = (result.path, result.start_line, result.end_line)
            merged_map[key] = {
                'result': result,
                'vector_score': result.score,
                'keyword_score': 0.0
            }
        
        for result in keyword_results:
            key = (result.path, result.start_line, result.end_line)
            if key in merged_map:
                merged_map[key]['keyword_score'] = result.score
            else:
                merged_map[key] = {
                    'result': result,
                    'vector_score': 0.0,
                    'keyword_score': result.score
                }
        
        merged_results = []
        for entry in merged_map.values():
            combined_score = (
                vector_weight * entry['vector_score'] +
                keyword_weight * entry['keyword_score']
            )
            
            # Apply temporal decay for dated memory files
            result = entry['result']
            decay = self._compute_temporal_decay(result.path)
            combined_score *= decay
            
            merged_results.append(SearchResult(
                path=result.path,
                start_line=result.start_line,
                end_line=result.end_line,
                score=combined_score,
                snippet=result.snippet,
                source=result.source,
                user_id=result.user_id,
                metadata=result.metadata,
            ))
        
        merged_results.sort(key=lambda r: r.score, reverse=True)
        return merged_results

    @staticmethod
    def _classify_memory(path: str, source: str = "") -> Dict[str, Any]:
        normalized = (path or "").replace("\\", "/")
        lower = normalized.lower()
        layer = "project"
        book_id = ""
        path_kind = MemoryManager._path_kind(normalized)
        if source == "workspace_profile" or lower in {"agent.md", "user.md", "rule.md", "memory.md"}:
            layer = "project"
        elif "user_profile" in lower or "/users/" in lower:
            layer = "user"
        elif source == "textbook" or "/textbooks/" in lower or lower.startswith("textbooks/"):
            layer = "textbook"
            parts = normalized.split("/")
            if "textbooks" in parts:
                idx = parts.index("textbooks")
                if idx + 1 < len(parts):
                    book_id = parts[idx + 1]
        elif "errors/" in lower or source == "error":
            layer = "error"
        elif source == "knowledge" or lower.startswith("knowledge/"):
            layer = "knowledge"
        elif source == "memory":
            layer = "memory"
        authority, temporal_scope = MemoryManager._infer_temporal_defaults(
            normalized,
            source,
            layer,
            path_kind,
        )
        return {
            "memory_layer": layer,
            "book_id": book_id,
            "path_kind": path_kind,
            "chapter_num": MemoryManager._chapter_num(normalized),
            "entity_key": MemoryManager._memory_entity_key(normalized, layer, book_id, path_kind),
            "temporal_scope": temporal_scope,
            "authority": authority,
            "observed_at": "",
            "valid_from": "",
            "valid_until": "",
            "supersedes": [],
            "superseded_by": "",
        }

    @staticmethod
    def _infer_temporal_defaults(path: str, source: str, layer: str, path_kind: str) -> tuple[str, str]:
        lower = (path or "").lower()
        if layer == "textbook":
            if "/snapshots/" in lower or "/versions/" in lower:
                return "truth_file", "historical"
            return "truth_file", "current"
        if layer == "user" or path_kind == "user_profile":
            return "user_profile", "evergreen"
        if source == "workspace_profile" or path_kind == "rule" or lower in {"agent.md", "user.md", "rule.md", "memory.md"}:
            authority = "workspace_rule" if path_kind == "rule" else "workspace_profile"
            return authority, "evergreen"
        if "/short_term/" in lower:
            return "short_term", "active"
        if "/candidates/" in lower:
            return "promotion_candidate", "active"
        if "/processes/" in lower:
            return "process_log", "historical"
        if "/sessions/" in lower:
            return "conversation", "historical"
        if "/errors/" in lower or layer == "error":
            return "error_log", "historical"
        if source == "knowledge" or layer == "knowledge":
            return "knowledge", "evergreen"
        if MemoryManager._is_dated_memory_path(lower):
            return "daily_summary", "historical"
        if source == "memory":
            return "long_term_memory", "evergreen"
        return source or "memory", "historical"

    @staticmethod
    def _with_temporal_metadata(
        path: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
        observed_at: str = "",
    ) -> Dict[str, Any]:
        merged = dict(metadata or MemoryManager._classify_memory(path, source))
        authority, temporal_scope = MemoryManager._infer_temporal_defaults(
            (path or "").replace("\\", "/"),
            source,
            str(merged.get("memory_layer") or ""),
            str(merged.get("path_kind") or ""),
        )
        merged.setdefault("temporal_scope", temporal_scope)
        merged.setdefault("authority", authority)
        merged["observed_at"] = merged.get("observed_at") or observed_at or datetime.now().isoformat()
        merged["valid_from"] = merged.get("valid_from") or merged["observed_at"]
        merged.setdefault("valid_until", "")
        merged.setdefault("supersedes", [])
        merged.setdefault("superseded_by", "")
        if MemoryManager._is_expired(merged):
            merged["temporal_scope"] = "expired"
        return merged

    @staticmethod
    def _is_dated_memory_path(path: str) -> bool:
        import re
        return bool(re.search(r"(^|/)\d{4}-\d{2}-\d{2}\.md$", path or ""))

    @staticmethod
    def _is_expired(metadata: Dict[str, Any], now: Optional[datetime] = None) -> bool:
        valid_until = (metadata or {}).get("valid_until") or ""
        if not valid_until:
            return False
        try:
            until = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
            current = now or datetime.now(until.tzinfo)
            return until < current
        except Exception:
            return False

    @staticmethod
    def _path_kind(path: str) -> str:
        lower = path.lower()
        if lower.endswith("harness.md"):
            return "harness"
        if "/chapters/" in lower:
            return "chapter"
        if "/outline/" in lower:
            return "outline"
        if "/state/" in lower:
            return "state"
        if lower.endswith("user_profile.md") or lower.endswith("user_profile.json"):
            return "user_profile"
        if lower.endswith("rule.md"):
            return "rule"
        return Path(path).suffix.lower().lstrip(".") or "file"

    @staticmethod
    def _chapter_num(path: str) -> str:
        import re
        match = re.search(r"chapter_0*(\d+)(?:_meta)?\.(?:md|json)$", (path or "").lower())
        return str(int(match.group(1))) if match else ""

    @staticmethod
    def _memory_entity_key(path: str, layer: str, book_id: str, path_kind: str) -> str:
        normalized = (path or "").replace("\\", "/")
        lower = normalized.lower()
        if layer == "textbook" and book_id:
            chapter = MemoryManager._chapter_num(lower)
            if chapter:
                return f"textbook:{book_id}:chapter:{chapter}"
            if "/state/" in lower:
                return f"textbook:{book_id}:state:{Path(lower).name}"
            if "/outline/" in lower:
                return f"textbook:{book_id}:outline:{Path(lower).name}"
            if lower.endswith("harness.md"):
                return f"textbook:{book_id}:harness"
            return f"textbook:{book_id}:{path_kind}:{Path(lower).name}"
        return f"{layer}:{path_kind}:{lower}"

    def _rerank_results(self, query: str, results: List[SearchResult]) -> List[SearchResult]:
        query_lower = (query or "").lower()
        query_text = query or ""
        for result in results:
            metadata = result.metadata or {}
            boost = 1.0
            layer = metadata.get("memory_layer", "")
            kind = metadata.get("path_kind", "")
            if any(word in query_text for word in ("教材", "章节", "大纲", "导出", "WritingSpec", "harness")):
                if layer == "textbook":
                    boost += 0.35
                if kind in ("harness", "state", "outline", "chapter"):
                    boost += 0.20
            if any(word in query_text for word in ("偏好", "用户", "我希望", "以后", "不要")) and layer == "user":
                boost += 0.35
            if any(word in query_text for word in ("错误", "失败", "修复", "bug", "报错")) and layer == "error":
                boost += 0.35
            temporal_scope = metadata.get("temporal_scope", "")
            if self._is_expired(metadata):
                temporal_scope = "expired"
                metadata["temporal_scope"] = "expired"
            boost += {
                "current": 0.35,
                "active": 0.25,
                "evergreen": 0.15,
                "historical": 0.0,
                "expired": -0.50,
            }.get(temporal_scope, 0.0)
            book_id = metadata.get("book_id") or ""
            if book_id and book_id.lower() in query_lower:
                boost += 0.45
            boost *= self._authority_weight(metadata, query_text)
            boost *= self._temporary_style_override_weight(query_text, result)
            result.score = max(0.0, min(1.0, result.score * boost))
        results.sort(key=lambda item: item.score, reverse=True)
        return results

    @staticmethod
    def _prioritize_context_tags(query: str, results: List[SearchResult]) -> List[SearchResult]:
        desired = MemoryManager._context_tag_for_query(query)
        if not desired:
            return results
        for result in results:
            metadata = result.metadata or {}
            tags = metadata.get("context_tags") or []
            if desired in tags:
                result.score = min(1.0, result.score * 1.35 + 0.05)
                metadata["context_match"] = desired
                result.metadata = metadata
        results.sort(key=lambda item: item.score, reverse=True)
        return results

    @staticmethod
    def _context_tag_for_query(query: str) -> str:
        text = (query or "").lower()
        groups = (
            ("paper", ("论文", "引用", "文献", "摘要", "paper", "citation", "academic")),
            ("code", ("代码", "测试", "bug", "报错", "code", "test", "debug")),
            ("writing", ("写作", "润色", "章节", "大纲", "writing", "chapter", "outline")),
            ("chat", ("日常", "闲聊", "聊天", "chat")),
        )
        for tag, terms in groups:
            if any(term in text for term in terms):
                return tag
        return ""

    @staticmethod
    def _authority_weight(metadata: Dict[str, Any], query: str = "") -> float:
        """Prefer authoritative memory layers before noisy episodic logs."""
        metadata = metadata or {}
        authority = metadata.get("authority", "")
        temporal_scope = metadata.get("temporal_scope", "")
        layer = metadata.get("memory_layer", "")

        if temporal_scope == "expired":
            return 0.30

        weights = {
            "truth_file": 1.45,
            "workspace_rule": 1.35,
            "workspace_profile": 1.25,
            "user_profile": 1.35,
            "long_term_memory": 1.20,
            "promotion_candidate": 1.05,
            "short_term": 1.15,
            "knowledge": 1.05,
            "daily_summary": 0.85,
            "conversation": 0.80,
            "process_log": 0.75,
            "error_log": 0.55,
        }
        weight = weights.get(authority, 1.0)

        if layer == "error" or authority == "error_log":
            weight = 1.10 if MemoryManager._is_error_query(query) else weight
        if temporal_scope == "current":
            weight += 0.10
        elif temporal_scope == "active":
            weight += 0.05
        return weight

    @staticmethod
    def _temporary_style_override_weight(query: str, result: SearchResult) -> float:
        override = MemoryManager._current_response_style_override(query)
        if not override:
            return 1.0

        metadata = result.metadata or {}
        text = f"{result.snippet or ''} {metadata.get('style', '')} {metadata.get('preference', '')}".lower()
        if override == "detail" and MemoryManager._looks_like_brevity_preference(text):
            metadata["temporary_override"] = "detail_overrides_brevity"
            result.metadata = metadata
            return 0.35
        if override == "brief" and MemoryManager._looks_like_detail_preference(text):
            metadata["temporary_override"] = "brevity_overrides_detail"
            result.metadata = metadata
            return 0.35
        return 1.0

    @staticmethod
    def _current_response_style_override(query: str) -> str:
        text = (query or "").lower()
        if not text:
            return ""
        directive_markers = (
            "这次", "本次", "当前", "这轮", "本轮", "请", "回答", "解释", "说",
            "this time", "for now", "in this answer", "please", "answer", "explain",
        )
        if not any(marker in text for marker in directive_markers):
            return ""
        detail_markers = (
            "详细", "展开", "完整解释", "一步步", "分步骤", "具体说明",
            "detailed", "detail", "step by step", "explain fully",
        )
        brief_markers = (
            "简短", "简洁", "简单说", "只要结论", "不要展开", "概括",
            "brief", "concise", "short", "just the answer", "summary only",
        )
        if any(marker in text for marker in detail_markers):
            return "detail"
        if any(marker in text for marker in brief_markers):
            return "brief"
        return ""

    @staticmethod
    def _looks_like_brevity_preference(text: str) -> bool:
        markers = (
            "concise", "concisely", "brief", "short", "succinct",
            "简洁", "简短", "简明", "只要结论",
        )
        return any(marker in (text or "").lower() for marker in markers)

    @staticmethod
    def _looks_like_detail_preference(text: str) -> bool:
        markers = (
            "detailed", "detail", "full explanation", "step by step", "thorough",
            "详细", "展开", "完整解释", "一步步", "分步骤",
        )
        return any(marker in (text or "").lower() for marker in markers)

    @staticmethod
    def _is_error_query(query: str) -> bool:
        text = (query or "").lower()
        markers = (
            "error", "failure", "failed", "bug", "fix", "exception", "traceback",
            "错误", "失败", "修复", "报错", "异常",
        )
        return any(marker in text for marker in markers)

    def _resolve_authoritative_results(self, query: str, results: List[SearchResult]) -> List[SearchResult]:
        """Annotate conflicts and prefer current authority for the same memory entity."""
        by_entity: Dict[str, List[SearchResult]] = {}
        for result in results:
            metadata = result.metadata or {}
            if not metadata.get("entity_key"):
                metadata["entity_key"] = self._memory_entity_key(
                    result.path,
                    metadata.get("memory_layer", result.source),
                    metadata.get("book_id", ""),
                    metadata.get("path_kind", ""),
                )
            result.metadata = metadata
            entity_key = metadata.get("entity_key") or ""
            if entity_key:
                by_entity.setdefault(entity_key, []).append(result)

        current_state_query = self._is_current_state_query(query)
        historical_query = self._is_historical_query(query)
        for entity_key, group in by_entity.items():
            current = [
                result for result in group
                if (result.metadata or {}).get("temporal_scope") == "current"
                and (result.metadata or {}).get("authority") == "truth_file"
            ]
            if not current:
                continue
            authority = sorted(current, key=lambda item: item.score, reverse=True)[0]
            authority_path = authority.path
            for result in group:
                if result is authority:
                    continue
                metadata = result.metadata or {}
                scope = metadata.get("temporal_scope", "")
                if scope in {"historical", "expired"}:
                    metadata["superseded_by"] = authority_path
                    metadata.setdefault("conflict_note", "Superseded by current truth-file memory for the same entity.")
                    if current_state_query and not historical_query:
                        result.score = max(0.0, result.score * 0.2)
                result.metadata = metadata

        results.sort(key=lambda item: item.score, reverse=True)
        return results

    @staticmethod
    def _is_current_state_query(query: str) -> bool:
        text = (query or "").lower()
        markers = (
            "current", "status", "progress", "latest", "now",
            "当前", "现在", "最新", "状态", "进度", "完成", "是否", "目前",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _is_historical_query(query: str) -> bool:
        text = (query or "").lower()
        markers = (
            "history", "historical", "previous", "old", "past",
            "历史", "之前", "曾经", "过去", "旧版", "早期", "记录",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _compress_search_result(result: SearchResult, max_chars: int = 320) -> SearchResult:
        import re
        snippet = re.sub(r"```[\s\S]*?```", "[code block omitted]", result.snippet or "")
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip() + "..."
        return SearchResult(
            path=result.path,
            start_line=result.start_line,
            end_line=result.end_line,
            score=result.score,
            snippet=snippet,
            source=result.source,
            user_id=result.user_id,
            metadata=result.metadata,
        )
