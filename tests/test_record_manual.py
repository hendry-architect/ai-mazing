"""Recording a publication that happened outside PCIP.

`prepare` exists because the automated write path can be unavailable. When
that article then goes live by hand, the graph would otherwise never learn of
it — leaving an output that reads as unpublished while it is in fact on the
internet. That is a silently wrong distribution record, which is worse than an
obviously missing one.
"""

import pytest

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.licensing import LicensePolicy
from pcip.models import Asset, Channel, EdgeKind, NodeKind
from pcip.publish.router import PublishError, PublishRouter


URL = "https://passqual.com/es/tres-habitos-diarios-para-cuidar-su-azucar/"


def setup(approved=True):
    cfg = PCIPConfig()
    g = KnowledgeGraph(":memory:")
    asset = Asset(
        id="out_1", name="Prevención (pdf)", kind="image",
        local_path="/tmp/x.pdf",
        license=LicensePolicy.canva_export_license(pro=True),
        metadata={"via_export": True, "format": "pdf"},
    )
    g.upsert_node("out_1", NodeKind.OUTPUT, asset.name, asset.to_dict())
    # A run cannot be "done" while a gate is still pending, so an unapproved
    # run is represented the way the runner actually leaves one.
    run = {
        "id": "run_1",
        "status": "done" if approved else "awaiting_review",
        "steps": [{
            "step": "medical_review",
            "status": "done" if approved else "awaiting_review",
            "detail": "approved by Dr. Pascual" if approved else "awaiting clinician",
        }],
    }
    g.upsert_node("run_1", NodeKind.PIPELINE_RUN, "patient_education", run)
    g.add_edge("run_1", EdgeKind.PRODUCED, "out_1")
    return PublishRouter(cfg, g), g


def test_records_the_publication_in_the_graph():
    router, g = setup()
    pub = router.record_manual("out_1", "wordpress", url=URL, note="REST blocked")

    assert pub.url == URL
    assert pub.status == "published"
    assert pub.channel == Channel.WORDPRESS
    node = g.get_node(pub.id)
    assert node["kind"] == NodeKind.PUBLICATION.value


def test_it_shows_up_in_the_distribution_record():
    router, _ = setup()
    router.record_manual("out_1", "wordpress", url=URL)
    where = router.where_did_it_go("out_1")
    assert len(where) == 1
    assert where[0]["url"] == URL


def test_marked_manual_so_it_is_never_mistaken_for_an_automated_publish():
    router, _ = setup()
    pub = router.record_manual("out_1", "wordpress", url=URL, note="by hand")
    assert pub.metadata["manual"] is True
    assert pub.metadata["note"] == "by hand"


def test_needs_somewhere_it_actually_went():
    router, _ = setup()
    with pytest.raises(PublishError) as exc:
        router.record_manual("out_1", "wordpress")
    assert "--url" in str(exc.value)


def test_an_unknown_output_cannot_be_recorded():
    router, _ = setup()
    with pytest.raises(PublishError):
        router.record_manual("out_nope", "wordpress", url=URL)


def test_review_gates_still_apply():
    """Publishing by hand must not become a way around the clinician gate."""
    router, _ = setup(approved=False)
    with pytest.raises(PublishError) as exc:
        router.record_manual("out_1", "wordpress", url=URL)
    assert "reviewed" in str(exc.value)


def test_explicit_timestamp_is_kept():
    router, _ = setup()
    pub = router.record_manual(
        "out_1", "wordpress", url=URL, published_at="2026-09-07T12:00:00+00:00"
    )
    assert pub.published_at == "2026-09-07T12:00:00+00:00"
