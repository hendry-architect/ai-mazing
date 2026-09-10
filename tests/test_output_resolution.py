"""Resolving 'the latest output' so instructions need no placeholder.

`pcip publish <output_id>` gets pasted verbatim, and zsh reads the angle
brackets as a file redirect: "no such file or directory: output_id". The id
is knowable from the graph, so PCIP should know it — the same reasoning
already applied to run ids.
"""

import pytest

from pcip.cli import _resolve_output_id
from pcip.graph.store import KnowledgeGraph
from pcip.models import Asset, Channel, License, LicenseType, NodeKind, Publication


def graph_with(*outputs, published=()):
    g = KnowledgeGraph(":memory:")
    for oid in outputs:
        a = Asset(id=oid, name=f"Article {oid}",
                  license=License(type=LicenseType.CANVA_PRO, source="canva"))
        g.upsert_node(oid, NodeKind.OUTPUT, a.name, a.to_dict())
    for oid in published:
        pub = Publication(output_id=oid, channel=Channel.WORDPRESS)
        g.upsert_node(pub.id, NodeKind.PUBLICATION, "pub", pub.to_dict())
    return g


def test_an_explicit_id_is_returned_unchanged():
    g = graph_with("out_a", "out_b")
    assert _resolve_output_id(g, "out_a") == "out_a"


def test_latest_picks_the_most_recent():
    g = graph_with("out_old", "out_new")
    assert _resolve_output_id(g, "latest") == "out_new"


def test_an_omitted_id_behaves_like_latest():
    g = graph_with("out_only")
    assert _resolve_output_id(g, "") == "out_only"


def test_an_unpublished_output_is_preferred_over_a_newer_published_one():
    """"The latest one" means the one still waiting to go out, not the one
    already live — publishing that again is what the duplicate guard exists
    to refuse."""
    g = graph_with("out_waiting", "out_live", published=("out_live",))
    assert _resolve_output_id(g, "latest") == "out_waiting"


def test_it_falls_back_to_the_newest_when_everything_is_published():
    g = graph_with("out_a", "out_b", published=("out_a", "out_b"))
    assert _resolve_output_id(g, "latest") == "out_b"


def test_an_empty_graph_says_what_to_do():
    with pytest.raises(SystemExit, match="run a pipeline"):
        _resolve_output_id(KnowledgeGraph(":memory:"), "latest")


def test_ties_within_one_second_resolve_to_the_later_write():
    """Timestamps have one-second granularity and a pipeline writes several
    nodes inside one second — assembly, two approvals and an export landed
    in three seconds on a real run. Left to SQLite, "the latest" would be
    whichever row it felt like returning."""
    g = graph_with(*[f"out_{i}" for i in range(6)])
    assert _resolve_output_id(g, "latest") == "out_5"
