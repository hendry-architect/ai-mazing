"""Knowledge graph store tests (in-memory SQLite, no network)."""

from pcip.graph.store import KnowledgeGraph
from pcip.models import EdgeKind, NodeKind


def make_graph() -> KnowledgeGraph:
    g = KnowledgeGraph(":memory:")
    g.upsert_node(
        "canva:design:D1", NodeKind.DESIGN, "Diabetes Carousel",
        {"tags": ["diabetes", "instagram"], "brand": "PassQual"},
    )
    g.upsert_node("topic:diabetes", NodeKind.TOPIC, "diabetes")
    g.upsert_node("asset_1", NodeKind.ASSET, "Heart hero image", {"tags": ["cardiology"]})
    g.add_edge("canva:design:D1", EdgeKind.ABOUT, "topic:diabetes")
    g.add_edge("canva:design:D1", EdgeKind.USES_ASSET, "asset_1")
    return g


def test_upsert_and_get():
    g = make_graph()
    node = g.get_node("canva:design:D1")
    assert node is not None
    assert node["name"] == "Diabetes Carousel"
    assert node["payload"]["brand"] == "PassQual"
    # Upsert overwrites in place, no duplicates.
    g.upsert_node("canva:design:D1", NodeKind.DESIGN, "Diabetes Carousel v2", {})
    assert g.get_node("canva:design:D1")["name"] == "Diabetes Carousel v2"
    assert g.stats()["by_kind"]["design"] == 1


def test_search_finds_by_name_and_tags():
    g = make_graph()
    assert any(r["id"] == "canva:design:D1" for r in g.search("diabetes"))
    assert any(r["id"] == "asset_1" for r in g.search("cardiology"))
    # Kind filter narrows results.
    only_topics = g.search("diabetes", kinds=[NodeKind.TOPIC])
    assert {r["kind"] for r in only_topics} == {"topic"}


def test_search_survives_special_characters():
    g = make_graph()
    # FTS5 operators in user queries must not raise.
    assert g.search('diabetes AND "carousel" (x:y)*') is not None


def test_neighbors_and_subgraph():
    g = make_graph()
    out = g.neighbors("canva:design:D1")
    assert ("about", "topic:diabetes") in out
    assert ("uses_asset", "asset_1") in out
    incoming = g.neighbors("topic:diabetes", direction="in")
    assert ("about", "canva:design:D1") in incoming

    sub = g.subgraph("topic:diabetes", depth=2)
    ids = {n["id"] for n in sub["nodes"]}
    assert {"topic:diabetes", "canva:design:D1", "asset_1"} <= ids


def test_delete_node_removes_edges():
    g = make_graph()
    g.delete_node("asset_1")
    assert g.get_node("asset_1") is None
    assert ("uses_asset", "asset_1") not in g.neighbors("canva:design:D1")
