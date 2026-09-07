"""Not publishing the same article twice, and undoing it when we did.

Two live articles on one topic compete for the same search terms and leave a
reader guessing which is current. It happened here: a scheduled run and a
manual run both published, and the site listed the same headline twice.
"""

import pytest

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.licensing import LicensePolicy
from pcip.models import Asset, Channel, EdgeKind, NodeKind, Publication
from pcip.publish.router import PublishError, PublishRouter


def setup(tmp_path):
    cfg = PCIPConfig(
        wordpress_url="https://wp.passqual.com",
        wordpress_public_site="https://passqual.com",
        wordpress_user="editor", wordpress_app_password="abcd efgh",
    )
    g = KnowledgeGraph(":memory:")
    hero = tmp_path / "hero.png"
    hero.write_bytes(b"\x89PNG")
    asset = Asset(id="out_1", name="Deliverable", kind="image",
                  local_path=str(hero),
                  license=LicensePolicy.canva_export_license(pro=True),
                  metadata={"via_export": True})
    g.upsert_node("out_1", NodeKind.OUTPUT, asset.name, asset.to_dict())
    g.upsert_node("run_1", NodeKind.PIPELINE_RUN, "p", {
        "id": "run_1", "status": "done", "steps": [], "context": {}})
    g.add_edge("run_1", EdgeKind.PRODUCED, "out_1")
    return cfg, g, PublishRouter(cfg, g)


def already_published(router, url="https://passqual.com/x/", post_id="3367"):
    pub = Publication(output_id="out_1", channel=Channel.WORDPRESS,
                      url=url, external_id=post_id, status="published")
    router._record(pub)
    return pub


def test_publishing_twice_is_refused(tmp_path):
    cfg, g, router = setup(tmp_path)
    already_published(router)
    with pytest.raises(PublishError) as exc:
        router.publish("out_1", Channel.WORDPRESS, live=True)
    msg = str(exc.value)
    assert "already published" in msg
    assert "3367" in msg or "passqual.com/x" in msg
    assert "pcip retract out_1" in msg          # the fix, not just the refusal


def test_republish_is_an_explicit_choice(tmp_path):
    """The guard must be overridable, or it becomes the next thing to fight."""
    cfg, g, router = setup(tmp_path)
    already_published(router)
    with pytest.raises(PublishError) as exc:
        router.publish("out_1", Channel.WORDPRESS, live=True, republish=True)
    # It gets past the duplicate guard and fails later, on the brand standard.
    assert "already published" not in str(exc.value)


def test_a_retracted_copy_no_longer_blocks(tmp_path):
    cfg, g, router = setup(tmp_path)
    pub = already_published(router)
    record = g.get_node(pub.id)["payload"]
    record["status"] = "retracted"
    g.upsert_node(pub.id, NodeKind.PUBLICATION, "retracted", record)
    with pytest.raises(PublishError) as exc:
        router.publish("out_1", Channel.WORDPRESS, live=True)
    assert "already published" not in str(exc.value)


def test_retract_trashes_the_post_and_keeps_the_history(tmp_path, monkeypatch):
    """Trash, not delete: an irreversible retraction is worse than the
    duplicate it fixes. And the record stays — that it was live is part of the
    distribution history."""
    cfg, g, router = setup(tmp_path)
    pub = already_published(router)

    trashed = []

    class FakeWP:
        def __init__(self, config, **kw):
            pass

        def trash_post(self, post_id):
            trashed.append(post_id)
            return {"id": post_id, "status": "trash"}

    monkeypatch.setattr("pcip.connectors.wordpress.WordPressPublisher", FakeWP)
    out = router.retract("out_1", reason="duplicate")

    assert trashed == ["3367"]
    assert out[0].status == "retracted"
    record = g.get_node(pub.id)["payload"]
    assert record["status"] == "retracted"
    assert record["metadata"]["retracted_reason"] == "duplicate"
    assert record["url"] == "https://passqual.com/x/"   # history preserved


def test_retracting_something_unpublished_is_not_an_error(tmp_path):
    cfg, g, router = setup(tmp_path)
    assert router.retract("out_1") == []
