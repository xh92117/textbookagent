"""Lightweight, rebuildable graph index over memory sources."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from common.log import logger

SCHEMA_VERSION = 1
INDEX_VERSION = "memory-graph-v1"
EXTRACTOR_VERSION = "deterministic-v1"


class MemoryGraphService:
    """A SQLite graph index for navigating memory before reading full sources."""

    def __init__(self, system_root: str, project_workspace: str = ""):
        self.system_root = Path(system_root)
        self.project_workspace = Path(project_workspace) if project_workspace else None
        self.graph_dir = self.system_root / "memory" / "graph"
        self.db_path = self.graph_dir / "memory_graph.db"
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def _init_db(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                source_path TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                mtime REAL NOT NULL DEFAULT 0,
                size INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                indexed_at TEXT NOT NULL DEFAULT '',
                deleted INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                authority TEXT NOT NULL DEFAULT '',
                temporal_scope TEXT NOT NULL DEFAULT '',
                valid_from TEXT NOT NULL DEFAULT '',
                valid_until TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL DEFAULT '',
                start_line INTEGER NOT NULL DEFAULT 1,
                end_line INTEGER NOT NULL DEFAULT 1,
                evidence TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                deleted INTEGER NOT NULL DEFAULT 0
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                edge_id TEXT PRIMARY KEY,
                from_node TEXT NOT NULL,
                to_node TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                source_path TEXT NOT NULL,
                evidence TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                deleted INTEGER NOT NULL DEFAULT 0
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS aliases (
                alias TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                source_path TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(alias, entity_key, source_path)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS dirty_sources (
                source_path TEXT NOT NULL,
                entity_key TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                dirty_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(source_path, entity_key)
            )
        """)
        for key, value in {
            "schema_version": str(SCHEMA_VERSION),
            "index_version": INDEX_VERSION,
            "extractor_version": EXTRACTOR_VERSION,
        }.items():
            self.conn.execute(
                "INSERT OR REPLACE INTO graph_meta(key, value) VALUES (?, ?)",
                (key, value),
            )
        for key, value in {
            "graph_dirty": "1",
            "graph_revision": "0",
        }.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO graph_meta(key, value) VALUES (?, ?)",
                (key, value),
            )
        self._ensure_column("nodes", "start_line", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("nodes", "end_line", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("nodes", "evidence", "TEXT NOT NULL DEFAULT ''")
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def sync_changed(self, max_files: int = 200) -> Dict[str, Any]:
        candidates = list(self._candidate_sources())[:max_files]
        seen = {src["source_path"] for src in candidates}
        indexed = 0
        skipped = 0
        deleted = 0

        for src in candidates:
            previous = self.conn.execute(
                "SELECT mtime, size, sha256, deleted FROM sources WHERE source_path = ?",
                (src["source_path"],),
            ).fetchone()
            if previous and not previous["deleted"] and previous["mtime"] == src["mtime"] \
                    and previous["size"] == src["size"] and previous["sha256"] == src["sha256"]:
                skipped += 1
                continue
            self._replace_source(src)
            indexed += 1

        rows = self.conn.execute("SELECT source_path FROM sources WHERE deleted = 0").fetchall()
        for row in rows:
            if row["source_path"] not in seen and not Path(row["source_path"]).exists():
                self._mark_source_deleted(row["source_path"])
                deleted += 1
        self._refresh_belongs_to_edges()
        self._refresh_extended_edges()

        self.conn.execute(
            "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('last_sync_at', ?)",
            (time.strftime("%Y-%m-%dT%H:%M:%S"),),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('graph_dirty', '0')"
        )
        self.conn.execute("DELETE FROM dirty_sources")
        self.conn.commit()
        return {"indexed": indexed, "skipped": skipped, "deleted": deleted}

    def rebuild(self) -> Dict[str, Any]:
        self.conn.execute("DELETE FROM aliases")
        self.conn.execute("DELETE FROM edges")
        self.conn.execute("DELETE FROM nodes")
        self.conn.execute("DELETE FROM sources")
        self.conn.commit()
        return self.sync_changed(max_files=100000)

    def status(self) -> Dict[str, Any]:
        def scalar(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0] or 0)

        meta = {
            row["key"]: row["value"]
            for row in self.conn.execute("SELECT key, value FROM graph_meta").fetchall()
        }
        return {
            "schema_version": int(meta.get("schema_version", SCHEMA_VERSION)),
            "index_version": meta.get("index_version", INDEX_VERSION),
            "extractor_version": meta.get("extractor_version", EXTRACTOR_VERSION),
            "source_count": scalar("SELECT COUNT(*) FROM sources WHERE deleted = 0"),
            "deleted_source_count": scalar("SELECT COUNT(*) FROM sources WHERE deleted = 1"),
            "node_count": scalar("SELECT COUNT(*) FROM nodes WHERE deleted = 0"),
            "edge_count": scalar("SELECT COUNT(*) FROM edges WHERE deleted = 0"),
            "edge_type_counts": self._edge_type_counts(),
            "edge_evidence_count": scalar("SELECT COUNT(*) FROM edges WHERE deleted = 0 AND evidence != ''"),
            "dirty_source_count": scalar("SELECT COUNT(DISTINCT source_path) FROM dirty_sources"),
            "dirty_entity_count": scalar("SELECT COUNT(DISTINCT entity_key) FROM dirty_sources WHERE entity_key != ''"),
            "last_sync_at": meta.get("last_sync_at", ""),
            "last_error": meta.get("last_error", ""),
            "graph_dirty": meta.get("graph_dirty", "1") != "0",
            "graph_revision": int(meta.get("graph_revision", "0") or 0),
        }

    def mark_dirty(self, reason: str = "", source_path: str = "", entity_key: str = "") -> None:
        revision = self.status().get("graph_revision", 0) + 1
        self.conn.execute(
            "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('graph_dirty', '1')"
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('graph_revision', ?)",
            (str(revision),),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('dirty_reason', ?)",
            (reason or "memory changed",),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('dirty_at', ?)",
            (time.strftime("%Y-%m-%dT%H:%M:%S"),),
        )
        if source_path or entity_key:
            self.conn.execute("""
                INSERT OR REPLACE INTO dirty_sources(source_path, entity_key, reason, dirty_at)
                VALUES (?, ?, ?, ?)
            """, (
                str(source_path or ""),
                str(entity_key or ""),
                reason or "memory changed",
                time.strftime("%Y-%m-%dT%H:%M:%S"),
            ))
        self.conn.commit()
        try:
            from agent.tools.memory.memory_search import MemorySearchTool

            MemorySearchTool.clear_graph_plan_cache(
                str(self.system_root),
                str(self.project_workspace or ""),
            )
        except Exception:
            pass

    def context(self, query: str, limit: int = 8, sync: Optional[bool] = None) -> Dict[str, Any]:
        if sync is None:
            current_status = self.status()
            sync = current_status.get("graph_dirty", True) or not current_status.get("last_sync_at")
        if sync:
            try:
                self.sync_changed()
            except Exception as exc:
                logger.debug(f"[MemoryGraph] sync before context skipped: {exc}")
        terms = self._query_terms(query)
        if not terms:
            return self._empty_context(query)

        rows = self.conn.execute("""
            SELECT n.* FROM nodes n
            WHERE n.deleted = 0
        """).fetchall()
        scored = []
        for row in rows:
            blob = " ".join([
                row["entity_key"], row["title"], row["summary"], row["source_path"],
                row["authority"], row["temporal_scope"],
            ]).lower()
            score = sum(1 for term in terms if term in blob)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["source_path"]))
        matched = [self._row_to_node(row) for _, row in scored[:limit]]

        current = [n for n in matched if n.get("temporal_scope") in {"current", "evergreen", "active"}]
        historical = [n for n in matched if n.get("temporal_scope") in {"historical", "expired"}]
        if not current and matched:
            current = matched[:1]

        conflicts = self._conflicts_for_entities([n["entity_key"] for n in matched])
        recommended = current[:5] + [n for n in historical[:3] if n not in current]
        return {
            "query": query,
            "matched_entities": sorted({n["entity_key"] for n in matched}),
            "authoritative_nodes": current[:limit],
            "historical_nodes": historical[:limit],
            "conflicts": conflicts,
            "recommended_reads": [
                {
                    "source_path": n["source_path"],
                    "entity_key": n["entity_key"],
                    "reason": f"{n.get('temporal_scope')}/{n.get('authority')}",
                }
                for n in recommended
            ],
            "graph_notes": self._graph_notes(matched, conflicts),
        }

    def _empty_context(self, query: str) -> Dict[str, Any]:
        return {
            "query": query,
            "matched_entities": [],
            "authoritative_nodes": [],
            "historical_nodes": [],
            "conflicts": [],
            "recommended_reads": [],
            "graph_notes": [],
        }

    def _candidate_sources(self) -> Iterable[Dict[str, Any]]:
        roots = [self.system_root / "memory"]
        if self.project_workspace:
            roots.append(self.project_workspace / "textbooks")
            roots.append(self.project_workspace / "knowledge")
        patterns = ("*.md", "*.json", "*.jsonl")
        for root in roots:
            if not root.exists():
                continue
            for pattern in patterns:
                for path in root.rglob(pattern):
                    if not path.is_file() or "memory_graph.db" in path.name:
                        continue
                    if self._should_skip_path(path):
                        continue
                    yield self._source_record(path)

    @staticmethod
    def _should_skip_path(path: Path) -> bool:
        text = path.as_posix().lower()
        return any(part in text for part in ("/graph/", "/versions/", "/cache/"))

    def _source_record(self, path: Path) -> Dict[str, Any]:
        stat = path.stat()
        data = path.read_bytes()
        return {
            "source_path": path.as_posix(),
            "source_type": self._source_type(path),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "sha256": hashlib.sha256(data).hexdigest(),
            "text": data.decode("utf-8", errors="ignore"),
        }

    def _source_type(self, path: Path) -> str:
        p = path.as_posix().lower()
        if "/errors/" in p:
            return "error"
        if "/processes/" in p or p.endswith("process_index.md"):
            return "process"
        if "/textbooks/" in p:
            return "textbook_state" if "/state/" in p or "/snapshots/" in p else "textbook"
        if "/knowledge/" in p:
            return "knowledge"
        if p.endswith("user_profile.md") or p.endswith("user_profile.json"):
            return "user_profile"
        if p.endswith("memory.md"):
            return "long_term_memory"
        return "memory"

    def _replace_source(self, src: Dict[str, Any]) -> None:
        source_path = src["source_path"]
        self.conn.execute("DELETE FROM aliases WHERE source_path = ?", (source_path,))
        self.conn.execute("DELETE FROM edges WHERE source_path = ?", (source_path,))
        self.conn.execute("DELETE FROM nodes WHERE source_path = ?", (source_path,))
        self.conn.execute("""
            INSERT OR REPLACE INTO sources(source_path, source_type, mtime, size, sha256, indexed_at, deleted, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """, (
            source_path, src["source_type"], src["mtime"], src["size"], src["sha256"],
            time.strftime("%Y-%m-%dT%H:%M:%S"), "{}",
        ))
        nodes = self._extract_nodes(src)
        for node in nodes:
            self._insert_node(node)
            for alias in node.get("aliases", []):
                self.conn.execute(
                    "INSERT OR REPLACE INTO aliases(alias, entity_key, source_path, deleted) VALUES (?, ?, ?, 0)",
                    (alias.lower(), node["entity_key"], source_path),
                )
        self._insert_supersedes_edges_for_source(nodes, source_path)

    def _mark_source_deleted(self, source_path: str) -> None:
        self.conn.execute("UPDATE sources SET deleted = 1 WHERE source_path = ?", (source_path,))
        self.conn.execute("UPDATE nodes SET deleted = 1 WHERE source_path = ?", (source_path,))
        self.conn.execute("UPDATE edges SET deleted = 1 WHERE source_path = ?", (source_path,))
        self.conn.execute("UPDATE aliases SET deleted = 1 WHERE source_path = ?", (source_path,))

    def _extract_nodes(self, src: Dict[str, Any]) -> List[Dict[str, Any]]:
        path = src["source_path"]
        try:
            from agent.memory.manager import MemoryManager

            metadata = MemoryManager._with_temporal_metadata(
                self._relative_display_path(path),
                "textbook" if src["source_type"].startswith("textbook") else "memory",
                MemoryManager._classify_memory(
                    self._relative_display_path(path),
                    "textbook" if src["source_type"].startswith("textbook") else "memory",
                ),
            )
        except Exception:
            metadata = {}
        entity_key = metadata.get("entity_key") or self._fallback_entity_key(path, src["source_type"])
        summary = self._summary_for_source(src)
        start_line, end_line, evidence = self._evidence_span(src)
        title = self._title_for_source(src, metadata)
        node = {
            "node_id": self._node_id(path, src["source_type"], entity_key, src["sha256"]),
            "node_type": src["source_type"],
            "entity_key": entity_key,
            "title": title,
            "summary": summary,
            "authority": metadata.get("authority", ""),
            "temporal_scope": metadata.get("temporal_scope", ""),
            "valid_from": metadata.get("valid_from", ""),
            "valid_until": metadata.get("valid_until", ""),
            "source_path": path,
            "source_hash": src["sha256"],
            "start_line": start_line,
            "end_line": end_line,
            "evidence": evidence,
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
            "aliases": self._aliases_for(path, entity_key, title, summary),
        }
        return [node]

    def _insert_node(self, node: Dict[str, Any]) -> None:
        self.conn.execute("""
            INSERT OR REPLACE INTO nodes(
                node_id, node_type, entity_key, title, summary, authority, temporal_scope,
                valid_from, valid_until, source_path, source_hash, start_line, end_line, evidence,
                metadata_json, deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            node["node_id"], node["node_type"], node["entity_key"], node["title"], node["summary"],
            node["authority"], node["temporal_scope"], node["valid_from"], node["valid_until"],
            node["source_path"], node["source_hash"], node["start_line"], node["end_line"],
            node["evidence"], node["metadata_json"],
        ))

    def _insert_supersedes_edges_for_source(self, nodes: List[Dict[str, Any]], source_path: str) -> None:
        for node in nodes:
            if node.get("temporal_scope") != "current" or node.get("authority") != "truth_file":
                continue
            historical = self.conn.execute("""
                SELECT node_id, source_path FROM nodes
                WHERE deleted = 0 AND entity_key = ? AND temporal_scope IN ('historical', 'expired')
            """, (node["entity_key"],)).fetchall()
            for old in historical:
                edge_id = self._edge_id(node["node_id"], old["node_id"], "supersedes")
                self.conn.execute("""
                    INSERT OR REPLACE INTO edges(edge_id, from_node, to_node, edge_type, confidence, source_path, evidence, metadata_json, deleted)
                    VALUES (?, ?, ?, 'supersedes', 1.0, ?, ?, '{}', 0)
                """, (edge_id, node["node_id"], old["node_id"], source_path, f"current truth file supersedes {old['source_path']}"))

    def _insert_belongs_to_edges_for_source(self, nodes: List[Dict[str, Any]], source_path: str) -> None:
        for node in nodes:
            metadata = json.loads(node.get("metadata_json") or "{}")
            book_id = metadata.get("book_id") or ""
            if not book_id or metadata.get("path_kind") == "state":
                continue
            parent = self.conn.execute("""
                SELECT node_id, source_path FROM nodes
                WHERE deleted = 0
                  AND entity_key = ?
                  AND temporal_scope IN ('current', 'evergreen', 'active')
                ORDER BY source_path
                LIMIT 1
            """, (f"textbook:{book_id}:state:status.json",)).fetchone()
            if not parent:
                continue
            edge_id = self._edge_id(node["node_id"], parent["node_id"], "belongs_to")
            evidence = f"{node['entity_key']} belongs to textbook {book_id}"
            self.conn.execute("""
                INSERT OR REPLACE INTO edges(edge_id, from_node, to_node, edge_type, confidence, source_path, evidence, metadata_json, deleted)
                VALUES (?, ?, ?, 'belongs_to', 0.95, ?, ?, ?, 0)
            """, (
                edge_id,
                node["node_id"],
                parent["node_id"],
                source_path,
                evidence,
                json.dumps({"book_id": book_id}, ensure_ascii=False),
            ))

    def _refresh_belongs_to_edges(self) -> None:
        self.conn.execute("DELETE FROM edges WHERE edge_type = 'belongs_to'")
        rows = self.conn.execute("SELECT * FROM nodes WHERE deleted = 0").fetchall()
        nodes = [self._row_to_node(row) | {"metadata_json": row["metadata_json"]} for row in rows]
        by_source: Dict[str, List[Dict[str, Any]]] = {}
        for node in nodes:
            by_source.setdefault(node["source_path"], []).append(node)
        for source_path, source_nodes in by_source.items():
            self._insert_belongs_to_edges_for_source(source_nodes, source_path)

    def _refresh_extended_edges(self) -> None:
        for edge_type in ("depends_on", "derived_from", "mentions", "conflicts_with"):
            self.conn.execute("DELETE FROM edges WHERE edge_type = ?", (edge_type,))
        rows = self.conn.execute("SELECT * FROM nodes WHERE deleted = 0").fetchall()
        nodes = [self._row_to_node(row) | {"metadata_json": row["metadata_json"]} for row in rows]
        self._insert_conflict_edges(nodes)
        self._insert_text_relation_edges(nodes)

    def _insert_conflict_edges(self, nodes: List[Dict[str, Any]]) -> None:
        by_entity: Dict[str, List[Dict[str, Any]]] = {}
        for node in nodes:
            by_entity.setdefault(node["entity_key"], []).append(node)
        for entity_key, group in by_entity.items():
            currents = [n for n in group if n.get("temporal_scope") in {"current", "evergreen", "active"}]
            historical = [n for n in group if n.get("temporal_scope") in {"historical", "expired"}]
            for current in currents[:3]:
                for old in historical[:5]:
                    self._insert_edge(
                        current,
                        old,
                        "conflicts_with",
                        current["source_path"],
                        f"{entity_key}: current node conflicts with historical node {old['source_path']}",
                        0.90,
                    )

    def _insert_text_relation_edges(self, nodes: List[Dict[str, Any]]) -> None:
        targets = self._relation_targets(nodes)
        for node in nodes:
            blob = "\n".join([node.get("summary", ""), node.get("evidence", "")])
            if self._allow_natural_relation_source(node):
                for edge_type, ref, evidence in self._natural_chapter_refs(node, blob):
                    target = self._resolve_relation_ref(ref, targets)
                    if target and target["node_id"] != node["node_id"]:
                        self._insert_edge(
                            node,
                            target,
                            edge_type,
                            node["source_path"],
                            evidence,
                            0.78,
                        )
            for edge_type, pattern in {
                "depends_on": r"(?im)^\s*depends\s+on\s*:\s*(.+)$",
                "derived_from": r"(?im)^\s*derived\s+from\s*:\s*(.+)$",
                "mentions": r"(?im)^\s*mentions\s*:\s*(.+)$",
                "depends_on": r"(?im)^\s*(?:depends\s+on|依赖)\s*[:：]\s*(.+)$",
                "derived_from": r"(?im)^\s*(?:derived\s+from|来源|基于)\s*[:：]\s*(.+)$",
                "mentions": r"(?im)^\s*(?:mentions|提到|涉及)\s*[:：]\s*(.+)$",
            }.items():
                for match in re.finditer(pattern, blob):
                    for ref in self._split_relation_refs(match.group(1)):
                        target = self._resolve_relation_ref(ref, targets)
                        if not target or target["node_id"] == node["node_id"]:
                            continue
                        self._insert_edge(
                            node,
                            target,
                            edge_type,
                            node["source_path"],
                            match.group(0).strip(),
                            0.85,
                        )

    @staticmethod
    def _allow_natural_relation_source(node: Dict[str, Any]) -> bool:
        path = str(node.get("source_path", "")).replace("\\", "/").lower()
        return "/textbooks/" in path or "/knowledge/" in path

    def _natural_chapter_refs(self, node: Dict[str, Any], text: str) -> List[tuple[str, str, str]]:
        metadata = json.loads(node.get("metadata_json") or "{}")
        current_chapter = self._safe_int(metadata.get("chapter_num"))
        refs: List[tuple[str, str, str]] = []
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            for match in re.finditer(r"第\s*([0-9一二三四五六七八九十百零〇]+)\s*章", stripped):
                chapter = self._chapter_ref_to_int(match.group(1))
                if not chapter:
                    continue
                edge_type = self._chapter_ref_edge_type(stripped, match.start())
                refs.append((edge_type, f"chapter_{chapter:02d}", stripped))
            if current_chapter:
                if re.search(r"上一章|前一章|上章|previous chapter", stripped, re.IGNORECASE):
                    refs.append(("depends_on", f"chapter_{current_chapter - 1:02d}", stripped))
                if re.search(r"下一章|后一章|下章|next chapter", stripped, re.IGNORECASE):
                    refs.append(("mentions", f"chapter_{current_chapter + 1:02d}", stripped))
        return [
            item for item in refs
            if not (current_chapter and item[1] == f"chapter_{current_chapter:02d}")
        ]

    @staticmethod
    def _chapter_ref_edge_type(line: str, start: int) -> str:
        prefix = line[:start]
        suffix = line[start:]
        if re.search(r"基于|来源|源自|承接|继承|derived|based on", prefix + suffix, re.IGNORECASE):
            return "derived_from"
        if re.search(r"建立|基础|前置|回顾|依赖|铺垫|prerequisite|depends", suffix, re.IGNORECASE):
            return "depends_on"
        if re.search(r"参考|参见|见|提示|将|会|讨论|讲解|实现|深入|see|discuss|will", prefix + suffix, re.IGNORECASE):
            return "mentions"
        return "mentions"

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def _chapter_ref_to_int(value: str) -> int:
        text = str(value or "").strip()
        if text.isdigit():
            return int(text)
        numerals = {
            "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
        }
        if text == "十":
            return 10
        if text.startswith("十"):
            return 10 + numerals.get(text[1:], 0)
        if "十" in text:
            left, right = text.split("十", 1)
            return numerals.get(left, 0) * 10 + (numerals.get(right, 0) if right else 0)
        return numerals.get(text, 0)

    def _relation_targets(self, nodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        targets = {}
        for node in nodes:
            values = {
                node.get("entity_key", ""),
                Path(node.get("source_path", "")).stem,
                Path(node.get("source_path", "")).name,
            }
            metadata = json.loads(node.get("metadata_json") or "{}")
            if metadata.get("chapter_num"):
                values.add(f"chapter_{int(metadata['chapter_num']):02d}")
                values.add(f"chapter_{metadata['chapter_num']}")
                values.add(f"第{metadata['chapter_num']}章")
            for value in values:
                key = str(value or "").replace("\\", "/").lower().strip()
                if key:
                    targets[key] = node
        return targets

    @staticmethod
    def _split_relation_refs(text: str) -> List[str]:
        return [
            item.strip()
            for item in re.split(r"[,;，；]\s*", text or "")
            if item.strip()
        ]

    @staticmethod
    def _resolve_relation_ref(ref: str, targets: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        key = (ref or "").replace("\\", "/").lower().strip()
        if key in targets:
            return targets[key]
        key_stem = Path(key).stem
        if key_stem in targets:
            return targets[key_stem]
        return None

    def _insert_edge(
        self,
        from_node: Dict[str, Any],
        to_node: Dict[str, Any],
        edge_type: str,
        source_path: str,
        evidence: str,
        confidence: float,
    ) -> None:
        edge_id = self._edge_id(from_node["node_id"], to_node["node_id"], edge_type)
        self.conn.execute("""
            INSERT OR REPLACE INTO edges(edge_id, from_node, to_node, edge_type, confidence, source_path, evidence, metadata_json, deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, '{}', 0)
        """, (
            edge_id,
            from_node["node_id"],
            to_node["node_id"],
            edge_type,
            confidence,
            source_path,
            evidence[:500],
        ))

    def _edge_type_counts(self) -> Dict[str, int]:
        rows = self.conn.execute("""
            SELECT edge_type, COUNT(*) AS count
            FROM edges
            WHERE deleted = 0
            GROUP BY edge_type
        """).fetchall()
        return {row["edge_type"]: int(row["count"]) for row in rows}

    def _conflicts_for_entities(self, entity_keys: List[str]) -> List[Dict[str, Any]]:
        conflicts = []
        for entity_key in set(entity_keys):
            rows = self.conn.execute("""
                SELECT * FROM nodes WHERE deleted = 0 AND entity_key = ?
            """, (entity_key,)).fetchall()
            has_current = any(row["temporal_scope"] == "current" and row["authority"] == "truth_file" for row in rows)
            historical = [row for row in rows if row["temporal_scope"] in {"historical", "expired"}]
            if has_current and historical:
                conflicts.append({
                    "entity_key": entity_key,
                    "type": "current_supersedes_historical",
                    "historical_sources": [row["source_path"] for row in historical[:5]],
                })
        return conflicts[:5]

    def _graph_notes(self, matched: List[Dict[str, Any]], conflicts: List[Dict[str, Any]]) -> List[str]:
        notes = []
        if matched:
            notes.append("Use recommended reads for source text; MemoryGraph is only a navigation index.")
        if conflicts:
            notes.append("Current truth-file nodes should be preferred unless the user asks for history.")
        return notes

    @staticmethod
    def _node_id(path: str, node_type: str, entity_key: str, source_hash: str) -> str:
        raw = f"{path}|{node_type}|{entity_key}|{source_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _edge_id(from_node: str, to_node: str, edge_type: str) -> str:
        return hashlib.sha256(f"{from_node}|{edge_type}|{to_node}".encode("utf-8")).hexdigest()[:32]

    def _relative_display_path(self, path: str) -> str:
        p = Path(path)
        for root in (self.system_root, self.project_workspace):
            if not root:
                continue
            try:
                return p.relative_to(root).as_posix()
            except Exception:
                continue
        return p.as_posix()

    @staticmethod
    def _fallback_entity_key(path: str, source_type: str) -> str:
        return f"{source_type}:{Path(path).name.lower()}"

    @staticmethod
    def _summary_for_source(src: Dict[str, Any], max_chars: int = 360) -> str:
        text = src.get("text", "")
        if src["source_type"].endswith("state") or src["source_path"].lower().endswith(".json"):
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    text = " ".join(f"{k}: {v}" for k, v in data.items() if isinstance(v, (str, int, float, bool)))
            except Exception:
                pass
        text = re.sub(r"\s+", " ", text).strip()
        text = MemoryGraphService._redact_secrets(text)
        return text[:max_chars].rstrip()

    @staticmethod
    def _evidence_span(src: Dict[str, Any], max_lines: int = 8) -> tuple[int, int, str]:
        lines = (src.get("text", "") or "").splitlines()
        if not lines:
            return 1, 1, ""
        first = 0
        for idx, line in enumerate(lines):
            if line.strip():
                first = idx
                break
        end = min(len(lines), first + max_lines)
        evidence = "\n".join(lines[first:end]).strip()
        evidence = MemoryGraphService._redact_secrets(evidence)
        return first + 1, max(first + 1, end), evidence[:500]

    @staticmethod
    def _title_for_source(src: Dict[str, Any], metadata: Dict[str, Any]) -> str:
        entity = metadata.get("entity_key", "")
        return entity or Path(src["source_path"]).name

    @staticmethod
    def _aliases_for(path: str, entity_key: str, title: str, summary: str) -> List[str]:
        aliases = {entity_key.lower(), Path(path).stem.lower(), title.lower()}
        aliases.update(re.findall(r"\b(?:tb|textbook)_[A-Za-z0-9_]+\b", path + " " + summary))
        for token in re.findall(r"[A-Za-z0-9_-]{3,}", summary):
            aliases.add(token.lower())
            if len(aliases) >= 40:
                break
        return [a for a in aliases if a]

    @staticmethod
    def _query_terms(query: str) -> List[str]:
        return [
            term.lower()
            for term in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_-]{2,}", query or "")
            if len(term.strip()) >= 2
        ]

    @staticmethod
    def _redact_secrets(text: str) -> str:
        patterns = [
            r"sk-[A-Za-z0-9_\-]{12,}",
            r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+",
        ]
        for pattern in patterns:
            text = re.sub(pattern, "[secret redacted]", text)
        return text

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "node_id": row["node_id"],
            "node_type": row["node_type"],
            "entity_key": row["entity_key"],
            "title": row["title"],
            "summary": row["summary"],
            "authority": row["authority"],
            "temporal_scope": row["temporal_scope"],
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "source_path": row["source_path"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "evidence": row["evidence"],
        }
