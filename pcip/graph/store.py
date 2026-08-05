"""SQLite-backed knowledge graph with full-text search.

Design goals:
- Zero extra dependencies (stdlib sqlite3; FTS5 with LIKE fallback).
- Nodes are (id, kind, name, JSON payload); edges are typed (src, kind, dst).
- Everything PCIP does — sync, generation, assembly, publishing — lands here,
  so "what have we made, from what, and where did it go?" is one query.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pcip.models import EdgeKind, NodeKind, now_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    payload    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);

CREATE TABLE IF NOT EXISTS edges (
    src        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    dst        TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY (src, kind, dst)
);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, kind);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(
    id UNINDEXED, kind UNINDEXED, name, text
);
"""


class KnowledgeGraph:
    """A typed property graph over SQLite."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        try:
            self._conn.executescript(_FTS_SCHEMA)
            self._fts = True
        except sqlite3.OperationalError:
            self._fts = False
        self._conn.commit()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "KnowledgeGraph":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── Nodes ────────────────────────────────────────────────────────────

    def upsert_node(
        self,
        node_id: str,
        kind: NodeKind | str,
        name: str = "",
        payload: Optional[Dict[str, Any]] = None,
        search_text: str = "",
    ) -> str:
        """Insert or update a node. ``search_text`` feeds full-text search."""
        kind = kind.value if isinstance(kind, NodeKind) else kind
        payload_json = json.dumps(payload or {}, ensure_ascii=False, default=str)
        ts = now_iso()
        self._conn.execute(
            """INSERT INTO nodes (id, kind, name, payload, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 kind=excluded.kind, name=excluded.name,
                 payload=excluded.payload, updated_at=excluded.updated_at""",
            (node_id, kind, name, payload_json, ts, ts),
        )
        if self._fts:
            text = search_text or self._default_search_text(name, payload or {})
            self._conn.execute("DELETE FROM node_fts WHERE id = ?", (node_id,))
            self._conn.execute(
                "INSERT INTO node_fts (id, kind, name, text) VALUES (?, ?, ?, ?)",
                (node_id, kind, name, text),
            )
        self._conn.commit()
        return node_id

    @staticmethod
    def _default_search_text(name: str, payload: Dict[str, Any]) -> str:
        parts = [name]
        for key in ("tags", "topics", "objective", "audience", "key_messages",
                    "notes", "description", "brand", "title"):
            v = payload.get(key)
            if isinstance(v, (list, tuple)):
                parts.extend(str(x) for x in v)
            elif v:
                parts.append(str(v))
        return " ".join(p for p in parts if p)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return self._node_row(row) if row else None

    def delete_node(self, node_id: str) -> None:
        self._conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        self._conn.execute(
            "DELETE FROM edges WHERE src = ? OR dst = ?", (node_id, node_id)
        )
        if self._fts:
            self._conn.execute("DELETE FROM node_fts WHERE id = ?", (node_id,))
        self._conn.commit()

    def nodes_by_kind(self, kind: NodeKind | str, limit: int = 200) -> List[Dict[str, Any]]:
        kind = kind.value if isinstance(kind, NodeKind) else kind
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE kind = ? ORDER BY updated_at DESC LIMIT ?",
            (kind, limit),
        ).fetchall()
        return [self._node_row(r) for r in rows]

    @staticmethod
    def _node_row(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["payload"] = json.loads(d.get("payload") or "{}")
        return d

    # ── Edges ────────────────────────────────────────────────────────────

    def add_edge(
        self,
        src: str,
        kind: EdgeKind | str,
        dst: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        kind = kind.value if isinstance(kind, EdgeKind) else kind
        self._conn.execute(
            """INSERT OR REPLACE INTO edges (src, kind, dst, payload, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (src, kind, dst, json.dumps(payload or {}, default=str), now_iso()),
        )
        self._conn.commit()

    def neighbors(
        self,
        node_id: str,
        kind: Optional[EdgeKind | str] = None,
        direction: str = "out",
    ) -> List[Tuple[str, str]]:
        """Edges touching a node → list of (edge_kind, other_node_id)."""
        kind = kind.value if isinstance(kind, EdgeKind) else kind
        results: List[Tuple[str, str]] = []
        if direction in ("out", "both"):
            q, params = "SELECT kind, dst FROM edges WHERE src = ?", [node_id]
            if kind:
                q += " AND kind = ?"
                params.append(kind)
            results += [(r["kind"], r["dst"]) for r in self._conn.execute(q, params)]
        if direction in ("in", "both"):
            q, params = "SELECT kind, src FROM edges WHERE dst = ?", [node_id]
            if kind:
                q += " AND kind = ?"
                params.append(kind)
            results += [(r["kind"], r["src"]) for r in self._conn.execute(q, params)]
        return results

    def subgraph(self, node_id: str, depth: int = 2) -> Dict[str, Any]:
        """Breadth-first expansion around a node — 'everything about X'."""
        seen = {node_id}
        frontier = [node_id]
        edges: List[Dict[str, str]] = []
        for _ in range(depth):
            next_frontier: List[str] = []
            for nid in frontier:
                for ekind, other in self.neighbors(nid, direction="both"):
                    edges.append({"src": nid, "kind": ekind, "dst": other})
                    if other not in seen:
                        seen.add(other)
                        next_frontier.append(other)
            frontier = next_frontier
        nodes = [n for nid in seen if (n := self.get_node(nid))]
        return {"nodes": nodes, "edges": edges}

    # ── Search ───────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        kinds: Optional[Iterable[NodeKind | str]] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Full-text search across names, tags, topics, briefs, and notes."""
        kind_values = [
            k.value if isinstance(k, NodeKind) else k for k in (kinds or [])
        ]
        if self._fts:
            # Quote each term to keep FTS5 syntax errors out of user queries.
            terms = " ".join(
                '"{}"'.format(t.replace('"', "")) for t in query.split()
            )
            sql = (
                "SELECT n.* FROM node_fts f JOIN nodes n ON n.id = f.id "
                "WHERE node_fts MATCH ?"
            )
            params: List[Any] = [terms]
        else:
            sql = "SELECT n.* FROM nodes n WHERE (n.name LIKE ? OR n.payload LIKE ?)"
            like = f"%{query}%"
            params = [like, like]
        if kind_values:
            sql += " AND n.kind IN ({})".format(",".join("?" * len(kind_values)))
            params += kind_values
        sql += " LIMIT ?"
        params.append(limit)
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
        return [self._node_row(r) for r in rows]

    # ── Stats ────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        node_counts = {
            r["kind"]: r["n"]
            for r in self._conn.execute(
                "SELECT kind, COUNT(*) AS n FROM nodes GROUP BY kind"
            )
        }
        edge_count = self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return {
            "nodes": sum(node_counts.values()),
            "by_kind": node_counts,
            "edges": edge_count,
            "fts": self._fts,
            "db": self.db_path,
        }
