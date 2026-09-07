"""Publish router tests: licensing and run-state gates hold before any network."""

import pytest

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.licensing import LicensingError
from pcip.models import (
    Asset,
    Channel,
    EdgeKind,
    License,
    LicenseType,
    NodeKind,
    PipelineRun,
    Publication,
    StepResult,
)
from pcip.publish.router import PublishError, PublishRouter


def setup(license_type=LicenseType.CANVA_PRO, via_export=True, run_status="done"):
    cfg = PCIPConfig()
    g = KnowledgeGraph(":memory:")
    out = Asset(
        id="out_1",
        name="Campaign hero",
        license=License(type=license_type, source="canva"),
        metadata={"via_export": via_export} if via_export else {},
    )
    g.upsert_node("out_1", NodeKind.OUTPUT, out.name, out.to_dict())
    run = PipelineRun(id="run_1", pipeline="social_campaign", status=run_status,
                      steps=[StepResult(step="export", status="done")])
    g.upsert_node("run_1", NodeKind.PIPELINE_RUN, "run", run.to_dict())
    g.add_edge("run_1", EdgeKind.PRODUCED, "out_1")
    return cfg, g, PublishRouter(cfg, g)


def test_publish_blocks_unknown_output():
    cfg, g, router = setup()
    with pytest.raises(PublishError):
        router.publish("nope", Channel.WORDPRESS)


def test_publish_blocks_unreviewed_run():
    cfg, g, router = setup(run_status="awaiting_review")
    with pytest.raises(PublishError, match="awaiting_review"):
        router.publish("out_1", Channel.WORDPRESS)


def test_publish_blocks_non_exported_premium():
    cfg, g, router = setup(via_export=False)
    with pytest.raises(LicensingError):
        router.publish("out_1", Channel.WORDPRESS)


def test_publish_blocks_unknown_license():
    cfg, g, router = setup(license_type=LicenseType.UNKNOWN)
    with pytest.raises(LicensingError):
        router.publish("out_1", Channel.WORDPRESS)


def test_licensed_output_then_faces_the_brand_standard():
    """Licensing clears; the next gate is the PassQual Health article standard.

    It sits between licensing and transport deliberately: there is no point
    checking WordPress credentials for an article that must not be published
    in the first place.
    """
    cfg, g, router = setup()
    with pytest.raises(Exception) as exc_info:
        router.publish("out_1", Channel.WORDPRESS)
    assert "PassQual Health article standard" in str(exc_info.value)


def test_operator_supplied_text_reaches_channel_config_check():
    """Explicit --text is the operator taking responsibility for the body.

    The standard is skipped, so the next failure is simply that no WordPress
    credentials exist in the test environment.
    """
    cfg, g, router = setup()
    with pytest.raises(Exception) as exc_info:
        router.publish("out_1", Channel.WORDPRESS, text="<p>Mi propio texto.</p>")
    assert "not configured" in str(exc_info.value)


def test_publication_recorded_in_graph():
    cfg, g, router = setup()
    pub = Publication(output_id="out_1", channel=Channel.WORDPRESS,
                      url="https://passqual.com/x")
    router._record(pub)
    trail = router.where_did_it_go("out_1")
    assert len(trail) == 1
    assert trail[0]["url"] == "https://passqual.com/x"
    assert ("on_channel", "channel:wordpress") in g.neighbors(pub.id)
