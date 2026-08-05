"""Canva → knowledge graph indexer.

Mirrors the org's Canva library (designs, folders, brand templates, assets)
into the graph so everything is searchable and relatable. Sync is idempotent:
nodes are upserted by their Canva id, so re-running only refreshes metadata.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pcip.connectors.canva import CanvaClient
from pcip.graph.store import KnowledgeGraph
from pcip.models import EdgeKind, LicenseType, NodeKind


def _canva_node_id(kind: str, canva_id: str) -> str:
    return f"canva:{kind}:{canva_id}"


class CanvaIndexer:
    """Pulls the Canva library into the knowledge graph."""

    def __init__(self, client: CanvaClient, graph: KnowledgeGraph) -> None:
        self.client = client
        self.graph = graph

    # ── Individual object indexers ───────────────────────────────────────

    def index_design(self, design: Dict[str, Any], folder_node: Optional[str] = None) -> str:
        node_id = _canva_node_id("design", design["id"])
        payload = {
            "canva_id": design["id"],
            "title": design.get("title", ""),
            "urls": design.get("urls", {}),
            "thumbnail": (design.get("thumbnail") or {}).get("url", ""),
            "page_count": design.get("page_count"),
            "created_at": design.get("created_at"),
            "updated_at": design.get("updated_at"),
            "owner": design.get("owner", {}),
            # Provenance: lives in Canva; export is the only way out.
            "license": {"type": LicenseType.CANVA_PRO.value, "source": "canva"},
        }
        self.graph.upsert_node(
            node_id, NodeKind.DESIGN, design.get("title", ""), payload
        )
        if folder_node:
            self.graph.add_edge(folder_node, EdgeKind.CONTAINS, node_id)
        return node_id

    def index_folder(self, folder: Dict[str, Any], parent_node: Optional[str] = None) -> str:
        node_id = _canva_node_id("folder", folder["id"])
        self.graph.upsert_node(
            node_id,
            NodeKind.FOLDER,
            folder.get("name", ""),
            {"canva_id": folder["id"], "created_at": folder.get("created_at")},
        )
        if parent_node:
            self.graph.add_edge(parent_node, EdgeKind.CONTAINS, node_id)
        return node_id

    def index_asset(self, asset: Dict[str, Any], folder_node: Optional[str] = None) -> str:
        node_id = _canva_node_id("asset", asset["id"])
        payload = {
            "canva_id": asset["id"],
            "name": asset.get("name", ""),
            "type": asset.get("type", ""),
            "tags": asset.get("tags", []),
            "thumbnail": (asset.get("thumbnail") or {}).get("url", ""),
            "created_at": asset.get("created_at"),
            "updated_at": asset.get("updated_at"),
            # Uploaded assets are org media; premium library elements never
            # appear here as standalone assets (Canva does not expose them).
            "license": {"type": LicenseType.OWNED.value, "source": "canva-upload"},
        }
        self.graph.upsert_node(node_id, NodeKind.ASSET, asset.get("name", ""), payload)
        if folder_node:
            self.graph.add_edge(folder_node, EdgeKind.CONTAINS, node_id)
        return node_id

    def index_brand_template(self, tpl: Dict[str, Any]) -> str:
        node_id = _canva_node_id("brand_template", tpl["id"])
        self.graph.upsert_node(
            node_id,
            NodeKind.BRAND_TEMPLATE,
            tpl.get("title", ""),
            {
                "canva_id": tpl["id"],
                "title": tpl.get("title", ""),
                "view_url": tpl.get("view_url", ""),
                "create_url": tpl.get("create_url", ""),
                "thumbnail": (tpl.get("thumbnail") or {}).get("url", ""),
                "created_at": tpl.get("created_at"),
                "updated_at": tpl.get("updated_at"),
            },
        )
        return node_id

    # ── Full sync ────────────────────────────────────────────────────────

    def _walk_folder(self, folder_id: str, folder_node: Optional[str], counts: Dict[str, int]) -> None:
        for item in self.client.list_folder_items(folder_id):
            itype = item.get("type")
            if itype == "folder":
                sub = item.get("folder", item)
                sub_node = self.index_folder(sub, folder_node)
                counts["folders"] += 1
                self._walk_folder(sub["id"], sub_node, counts)
            elif itype == "design":
                self.index_design(item.get("design", item), folder_node)
                counts["designs"] += 1
            elif itype in ("image", "asset"):
                self.index_asset(item.get(itype, item), folder_node)
                counts["assets"] += 1

    def sync(self, include_folders: bool = True) -> Dict[str, int]:
        """Sync the whole library. Returns counts by object type."""
        counts = {"designs": 0, "folders": 0, "assets": 0, "brand_templates": 0}

        for design in self.client.list_designs():
            self.index_design(design)
            counts["designs"] += 1

        if include_folders:
            self._walk_folder("root", None, counts)

        try:
            for tpl in self.client.list_brand_templates():
                self.index_brand_template(tpl)
                counts["brand_templates"] += 1
        except Exception:
            # Brand templates require a Canva Enterprise/Teams plan scope;
            # absence is not an error for the rest of the sync.
            pass

        return counts
