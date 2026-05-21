import json
import math
import os
import re
import hashlib
from collections import Counter, defaultdict
from typing import List, Dict

from common.log import logger


class KnowledgeRetriever:
    """Lightweight retrieval over LLM-WIKI metadata.

    This intentionally starts without a mandatory embedding dependency. It uses
    metadata recall, BM25-style scoring, and graph/entity expansion. Embedding
    fields are honored when present but are not required yet.
    """

    def __init__(self, workspace_root: str, book_id: str):
        self.workspace_root = workspace_root
        self.book_id = book_id
        self.wiki_dir = os.path.join(workspace_root, "knowledge", book_id, "_llm_wiki")
        self.index_path = os.path.join(self.wiki_dir, "index.json")
        self.cache_dir = os.path.join(self.wiki_dir, "cache")
        self.index = self._load_index()

    def _load_index(self) -> dict:
        if not os.path.isfile(self.index_path):
            return {"sources": [], "chunks": [], "pages": [], "entities": [], "relations": []}
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.warning(f"Failed to load knowledge index {self.index_path}: {exc}")
        return {"sources": [], "chunks": [], "pages": [], "entities": [], "relations": []}

    @staticmethod
    def _tokens(text: str) -> List[str]:
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_-]{2,}", text or "")
        return [t.lower() for t in tokens if t.strip()]

    @staticmethod
    def _normalized_terms(text: str) -> List[str]:
        terms = []
        seen = set()
        for token in KnowledgeRetriever._tokens(text):
            normalized = re.sub(r"[_\-\s]+", "", token.lower())
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(normalized)
        return terms

    def _chunk_text_for_scoring(self, chunk: dict) -> str:
        return " ".join([
            str(chunk.get("title", "")),
            str(chunk.get("section", "")),
            str(chunk.get("summary", "")),
            str(chunk.get("use_when", "")),
            str(chunk.get("content_type", "")),
            " ".join(str(k) for k in (chunk.get("keywords") or [])),
            " ".join(str(k) for k in (chunk.get("normalized_terms") or [])),
            " ".join(str(e) for e in (chunk.get("related_entities") or [])),
            str(chunk.get("source_quote", "")),
        ])

    def _read_chunk_excerpt(self, rel_path: str, max_chars: int = 900) -> str:
        if not rel_path or ".." in rel_path:
            return ""
        full_path = os.path.normpath(os.path.join(self.wiki_dir, rel_path))
        allowed = os.path.normpath(self.wiki_dir)
        if not full_path.startswith(allowed + os.sep) and full_path != allowed:
            return ""
        if not os.path.isfile(full_path):
            return ""
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as exc:
            logger.debug(f"Failed to read knowledge chunk excerpt {rel_path}: {exc}")
            return ""
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                text = parts[2]
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "..."
        return text

    def _bm25_scores(self, query: str) -> Dict[str, float]:
        chunks = self.index.get("chunks", [])
        query_terms = self._tokens(query)
        if not chunks or not query_terms:
            return {}
        docs = []
        df = Counter()
        for chunk in chunks:
            terms = self._tokens(self._chunk_text_for_scoring(chunk))
            counts = Counter(terms)
            docs.append((chunk.get("id", ""), terms, counts))
            for term in set(terms):
                df[term] += 1
        avg_len = sum(len(terms) for _, terms, _ in docs) / max(len(docs), 1)
        k1 = 1.4
        b = 0.72
        scores = defaultdict(float)
        total_docs = len(docs)
        for chunk_id, terms, counts in docs:
            doc_len = max(len(terms), 1)
            for term in query_terms:
                if not counts.get(term):
                    continue
                idf = math.log(1 + (total_docs - df[term] + 0.5) / (df[term] + 0.5))
                tf = counts[term]
                denom = tf + k1 * (1 - b + b * doc_len / max(avg_len, 1))
                scores[chunk_id] += idf * (tf * (k1 + 1) / denom)
        return scores

    def _metadata_scores(self, query: str) -> Dict[str, float]:
        query_terms = set(self._tokens(query))
        normalized_query_terms = set(self._normalized_terms(query))
        scores = defaultdict(float)
        if not query_terms and not normalized_query_terms:
            return scores
        for chunk in self.index.get("chunks", []):
            chunk_id = chunk.get("id", "")
            title_terms = set(self._tokens(chunk.get("title", "")))
            section_terms = set(self._tokens(chunk.get("section", "")))
            keyword_terms = set(self._tokens(" ".join(chunk.get("keywords") or [])))
            normalized_terms = set(str(t).lower() for t in (chunk.get("normalized_terms") or []))
            entity_terms = set(self._tokens(" ".join(chunk.get("related_entities") or [])))
            summary_terms = set(self._tokens(chunk.get("summary", "")))
            scores[chunk_id] += len(query_terms & title_terms) * 3.0
            scores[chunk_id] += len(query_terms & section_terms) * 2.5
            scores[chunk_id] += len(query_terms & keyword_terms) * 2.0
            scores[chunk_id] += len(normalized_query_terms & normalized_terms) * 1.8
            scores[chunk_id] += len(query_terms & entity_terms) * 1.5
            scores[chunk_id] += len(query_terms & summary_terms) * 1.0
            if chunk.get("content_type") == "evidence":
                scores[chunk_id] += 0.25
        return scores

    def _rerank_scores(self, query: str, chunks: Dict[str, dict]) -> Dict[str, float]:
        """Cheap lexical rerank to improve precision before building LLM context."""
        query_terms = set(self._tokens(query))
        normalized_query_terms = set(self._normalized_terms(query))
        if not query_terms and not normalized_query_terms:
            return {}
        scores = defaultdict(float)
        for chunk_id, chunk in chunks.items():
            title_terms = set(self._tokens(chunk.get("title", "")))
            section_terms = set(self._tokens(chunk.get("section", "")))
            keyword_terms = set(self._tokens(" ".join(chunk.get("keywords") or [])))
            entity_terms = set(self._tokens(" ".join(chunk.get("related_entities") or [])))
            chunk_norm_terms = set(str(t).lower() for t in (chunk.get("normalized_terms") or []))
            chunk_norm_terms.update(self._normalized_terms(self._chunk_text_for_scoring(chunk)))

            direct_overlap = len(query_terms & (title_terms | section_terms | keyword_terms | entity_terms))
            normalized_overlap = len(normalized_query_terms & chunk_norm_terms)
            coverage = direct_overlap / max(len(query_terms), 1)
            normalized_coverage = normalized_overlap / max(len(normalized_query_terms), 1)

            scores[chunk_id] += coverage * 2.0
            scores[chunk_id] += normalized_coverage * 1.8
            scores[chunk_id] += len(query_terms & title_terms) * 1.2
            scores[chunk_id] += len(query_terms & section_terms) * 0.8
            scores[chunk_id] += len(query_terms & keyword_terms) * 0.7
            scores[chunk_id] += len(query_terms & entity_terms) * 0.5
        return scores

    def _graph_expansion_details(self, seed_ids: List[str]) -> Dict[str, dict]:
        seed_set = set(seed_ids)
        details = defaultdict(lambda: {"score": 0.0, "reasons": []})
        if not seed_set:
            return details
        entity_to_chunks = defaultdict(set)
        chunk_titles = {}
        for chunk in self.index.get("chunks", []):
            chunk_id = chunk.get("id", "")
            if chunk_id:
                chunk_titles[chunk_id] = chunk.get("title", chunk_id)
            for ent in chunk.get("related_entities") or []:
                if chunk_id:
                    entity_to_chunks[ent].add(chunk_id)
        for chunk in self.index.get("chunks", []):
            if chunk.get("id") in seed_set:
                for ent in chunk.get("related_entities") or []:
                    for neighbor in entity_to_chunks.get(ent, set()):
                        if neighbor not in seed_set:
                            details[neighbor]["score"] += 0.75
                            reason = f"shares entity '{ent}' with {chunk_titles.get(chunk.get('id'), chunk.get('id'))}"
                            if reason not in details[neighbor]["reasons"]:
                                details[neighbor]["reasons"].append(reason)
        for rel in self.index.get("relations", []):
            rel_chunks = [str(cid) for cid in (rel.get("source_chunk_ids") or [])]
            if seed_set & set(rel_chunks):
                for cid in rel_chunks:
                    if cid not in seed_set:
                        details[cid]["score"] += 0.5
                        rel_name = rel.get("type") or rel.get("label") or "relation"
                        reason = f"linked by graph relation '{rel_name}'"
                        if reason not in details[cid]["reasons"]:
                            details[cid]["reasons"].append(reason)
        return details

    def _graph_expansion_scores(self, seed_ids: List[str]) -> Dict[str, float]:
        return {chunk_id: detail["score"] for chunk_id, detail in self._graph_expansion_details(seed_ids).items()}

    def retrieve(self, query: str, limit: int = 6, excerpt_chars: int = 900, use_cache: bool = True) -> List[dict]:
        cache_key = self._cache_key(query, limit, excerpt_chars)
        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached
        chunks = {chunk.get("id", ""): chunk for chunk in self.index.get("chunks", []) if chunk.get("id")}
        if not chunks:
            return []
        bm25 = self._bm25_scores(query)
        meta = self._metadata_scores(query)
        rerank = self._rerank_scores(query, chunks)
        combined = defaultdict(float)
        for chunk_id in chunks:
            combined[chunk_id] += bm25.get(chunk_id, 0.0)
            combined[chunk_id] += meta.get(chunk_id, 0.0)
            combined[chunk_id] += rerank.get(chunk_id, 0.0)
        seeds = [
            cid
            for cid, score in sorted(combined.items(), key=lambda item: item[1], reverse=True)
            if score > 0
        ][: max(limit, 4)]
        graph_details = self._graph_expansion_details(seeds)
        for chunk_id, detail in graph_details.items():
            combined[chunk_id] += detail.get("score", 0.0)
        ranked = sorted(combined.items(), key=lambda item: item[1], reverse=True)
        if not any(score > 0 for _, score in ranked):
            ranked = [(cid, 0.0) for cid in list(chunks.keys())[:limit]]
        evidence = []
        for chunk_id, score in ranked[:limit]:
            chunk = chunks.get(chunk_id)
            if not chunk:
                continue
            evidence.append({
                "chunk_id": chunk_id,
                "score": round(float(score), 4),
                "rerank_score": round(float(rerank.get(chunk_id, 0.0)), 4),
                "title": chunk.get("title", chunk_id),
                "section": chunk.get("section", ""),
                "summary": chunk.get("summary", ""),
                "use_when": chunk.get("use_when", ""),
                "keywords": chunk.get("keywords") or [],
                "content_type": chunk.get("content_type", ""),
                "entities": chunk.get("related_entities") or [],
                "path": chunk.get("path", ""),
                "assets": chunk.get("assets") or [],
                "graph_reason": "; ".join(graph_details.get(chunk_id, {}).get("reasons", [])[:3]),
                "embedding": chunk.get("embedding") or {"status": "pending"},
                "excerpt": self._read_chunk_excerpt(chunk.get("path", ""), max_chars=excerpt_chars) if excerpt_chars and excerpt_chars > 0 else "",
            })
        if use_cache:
            self._write_cache(cache_key, evidence)
        return evidence

    def diagnose(self, query: str, limit: int = 8) -> dict:
        """Return compact retrieval diagnostics for logs/UI, not for LLM context."""
        chunks = {chunk.get("id", ""): chunk for chunk in self.index.get("chunks", []) if chunk.get("id")}
        if not chunks:
            return {
                "query_chars": len(query or ""),
                "chunk_count": 0,
                "source_count": len(self.index.get("sources", []) or []),
                "relation_count": len(self.index.get("relations", []) or []),
                "top_chunks": [],
        }
        bm25 = self._bm25_scores(query)
        meta = self._metadata_scores(query)
        rerank = self._rerank_scores(query, chunks)
        combined = defaultdict(float)
        for chunk_id in chunks:
            combined[chunk_id] += bm25.get(chunk_id, 0.0)
            combined[chunk_id] += meta.get(chunk_id, 0.0)
            combined[chunk_id] += rerank.get(chunk_id, 0.0)
        seeds = [
            cid
            for cid, score in sorted(combined.items(), key=lambda item: item[1], reverse=True)
            if score > 0
        ][: max(limit, 4)]
        graph_details = self._graph_expansion_details(seeds)
        for chunk_id, detail in graph_details.items():
            combined[chunk_id] += detail.get("score", 0.0)
        ranked = sorted(combined.items(), key=lambda item: item[1], reverse=True)[:limit]
        return {
            "query_chars": len(query or ""),
            "query_terms": self._tokens(query)[:12],
            "chunk_count": len(chunks),
            "source_count": len(self.index.get("sources", []) or []),
            "entity_count": len(self.index.get("entities", []) or []),
            "relation_count": len(self.index.get("relations", []) or []),
            "seed_count": len([cid for cid in seeds if combined.get(cid, 0.0) > 0]),
            "graph_expanded_count": len(graph_details),
            "top_chunks": [
                {
                    "chunk_id": chunk_id,
                    "title": chunks.get(chunk_id, {}).get("title", chunk_id),
                    "score": round(float(score), 4),
                    "rerank_score": round(float(rerank.get(chunk_id, 0.0)), 4),
                    "graph_expanded": chunk_id in graph_details,
                    "graph_reason": "; ".join(graph_details.get(chunk_id, {}).get("reasons", [])[:2]),
                    "path": chunks.get(chunk_id, {}).get("path", ""),
                }
                for chunk_id, score in ranked
            ],
        }

    def format_compact_evidence_pack(self, query: str, metadata_limit: int = 8, excerpt_limit: int = 3, excerpt_chars: int = 500) -> str:
        evidence = self.retrieve(query, limit=metadata_limit, excerpt_chars=0)
        if not evidence:
            return ""
        lines = ["## Knowledge Evidence Pack", f"Query: {query}", "Mode: metadata-first; excerpts included only for top matches."]
        for idx, item in enumerate(evidence, start=1):
            lines.append(f"\n### Evidence {idx}: {item['title']}")
            if item.get("section"):
                lines.append(f"Section: {item['section']}")
            if item.get("summary"):
                lines.append(f"Summary: {item['summary']}")
            if item.get("use_when"):
                lines.append(f"Use when: {item['use_when']}")
            if item.get("keywords"):
                lines.append("Keywords: " + ", ".join(str(k) for k in item["keywords"][:8]))
            if item.get("rerank_score"):
                lines.append(f"Rerank score: {item['rerank_score']}")
            if item.get("graph_reason"):
                lines.append(f"Graph reason: {item['graph_reason']}")
            lines.append(f"Citation: knowledge/_llm_wiki/{item.get('path', '')}")
            if item.get("assets"):
                lines.append("Assets: " + ", ".join(str(a.get("path", "")) for a in item["assets"][:3] if a.get("path")))
            if idx <= excerpt_limit and item.get("path"):
                excerpt = self._read_chunk_excerpt(item.get("path", ""), max_chars=excerpt_chars)
                if excerpt:
                    lines.append("Excerpt:")
                    lines.extend("  " + line for line in excerpt.splitlines())
        return "\n".join(lines)

    def format_evidence_pack(self, query: str, limit: int = 6, excerpt_chars: int = 900) -> str:
        evidence = self.retrieve(query, limit=limit, excerpt_chars=excerpt_chars)
        if not evidence:
            return ""
        lines = ["## Knowledge Evidence Pack", f"Query: {query}"]
        for idx, item in enumerate(evidence, start=1):
            lines.append(f"\n### Evidence {idx}: {item['title']}")
            if item.get("section"):
                lines.append(f"Section: {item['section']}")
            if item.get("summary"):
                lines.append(f"Summary: {item['summary']}")
            if item.get("use_when"):
                lines.append(f"Use when: {item['use_when']}")
            if item.get("keywords"):
                lines.append("Keywords: " + ", ".join(str(k) for k in item["keywords"][:10]))
            if item.get("entities"):
                lines.append("Entities: " + ", ".join(str(e) for e in item["entities"][:10]))
            if item.get("rerank_score"):
                lines.append(f"Rerank score: {item['rerank_score']}")
            if item.get("graph_reason"):
                lines.append(f"Graph reason: {item['graph_reason']}")
            lines.append(f"Citation: knowledge/_llm_wiki/{item.get('path', '')}")
            if item.get("assets"):
                lines.append("Assets: " + ", ".join(str(a.get("path", "")) for a in item["assets"][:3] if a.get("path")))
            if item.get("excerpt"):
                lines.append("Excerpt:")
                lines.extend("  " + line for line in item["excerpt"].splitlines())
        return "\n".join(lines)

    def _cache_key(self, query: str, limit: int, excerpt_chars: int) -> str:
        index_mtime = os.path.getmtime(self.index_path) if os.path.isfile(self.index_path) else 0
        raw = json.dumps({
            "query": query,
            "limit": limit,
            "excerpt_chars": excerpt_chars,
            "index_mtime": round(index_mtime, 6),
            "version": "retriever-v4",
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"retrieval_{key}.json")

    def _read_cache(self, key: str):
        path = self._cache_path(key)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("evidence"), list):
                return data["evidence"]
        except Exception as exc:
            logger.debug(f"Failed to read retrieval cache {path}: {exc}")
            return None
        return None

    def _write_cache(self, key: str, evidence: List[dict]):
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._cache_path(key), "w", encoding="utf-8") as f:
                json.dump({"evidence": evidence}, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.debug(f"Failed to write retrieval cache {self._cache_path(key)}: {exc}")
