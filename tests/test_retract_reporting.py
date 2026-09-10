"""Retract has to say why it retracted nothing.

`pcip status` reported an output as published while `pcip retract` answered
"nothing published — nothing to retract". Two commands disagreeing about the
same fact, and neither able to show its working: retract had four silent
`continue`s and reported none of them.
"""

import pytest

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.models import (
    Asset, Channel, EdgeKind, License, LicenseType, NodeKind, Publication,
)
from pcip.publish.router import PublishRouter


def router_with(*publications, link_edges=True):
    g = KnowledgeGraph(":memory:")
    out = Asset(id="out_1", name="Article",
                license=License(type=LicenseType.CANVA_PRO, source="canva"),
                metadata={"via_export": True})
    g.upsert_node("out_1", NodeKind.OUTPUT, out.name, out.to_dict())
    for pub in publications:
        pub.output_id = "out_1"
        g.upsert_node(pub.id, NodeKind.PUBLICATION, "pub", pub.to_dict())
        if link_edges:
            g.add_edge("out_1", EdgeKind.PUBLISHED_TO, pub.id)
    return PublishRouter(PCIPConfig(), g)


def test_a_publication_with_no_edge_is_still_found():
    """The edge and the payload are written together and should agree. When
    they did not, status and retract disagreed about the same output."""
    router = router_with(
        Publication(channel=Channel.WORDPRESS, external_id="12", status="draft"),
        link_edges=False,
    )
    assert len(router.where_did_it_go("out_1")) == 1


def test_a_publication_found_both_ways_is_counted_once():
    router = router_with(
        Publication(channel=Channel.WORDPRESS, external_id="12", status="draft")
    )
    assert len(router.where_did_it_go("out_1")) == 1


def test_nothing_recorded_says_so():
    router = router_with()
    assert router.retract("out_1") == []
    assert "no publication is recorded" in router.last_retract_skips[0]


def test_a_missing_post_id_is_named_as_the_reason():
    """A record with no WordPress post id cannot be addressed, and saying
    "nothing to retract" invites the operator to conclude it is not live."""
    router = router_with(
        Publication(channel=Channel.WORDPRESS, external_id="", status="published")
    )
    assert router.retract("out_1") == []
    assert "no WordPress post id" in " ".join(router.last_retract_skips)


def test_a_social_publication_says_why_it_cannot_be_retracted():
    router = router_with(
        Publication(channel=Channel.INSTAGRAM, external_id="99", status="published")
    )
    assert router.retract("out_1") == []
    assert "only WordPress" in " ".join(router.last_retract_skips)


def test_an_unexpected_status_is_reported_verbatim():
    router = router_with(
        Publication(channel=Channel.WORDPRESS, external_id="12", status="failed")
    )
    assert router.retract("out_1") == []
    assert "'failed'" in " ".join(router.last_retract_skips)


def test_an_already_retracted_output_is_a_finished_job_not_a_failure():
    """Reporting a completed retraction the same way as a missing one is how
    a finished job read as a broken one, three times over."""
    router = router_with(
        Publication(channel=Channel.WORDPRESS, external_id="12",
                    status="retracted",
                    metadata={"retracted_reason": "superseded"})
    )
    assert router.retract("out_1") == []
    reported = " ".join(router.last_retract_skips)
    assert "already retracted" in reported
    assert "superseded" in reported


def test_a_retracted_publication_is_not_counted_as_published():
    """It also made `publish` with no id skip the output as already done."""
    from pcip.cli import _published_output_ids, _resolve_output_id

    g = router_with(
        Publication(channel=Channel.WORDPRESS, external_id="12",
                    status="retracted")
    ).graph
    assert _published_output_ids(g) == set()
    assert _resolve_output_id(g, "latest") == "out_1"
