"""Publishing to social channels through the router.

Two things had never been exercised together: the router's social branch and
the adapters underneath it. Running them turned up a gate nobody had tripped
— the full article standard was being applied to social captions, so no
social post could ever have been published.
"""

import pytest

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.models import (
    Asset, Brief, Channel, EdgeKind, License, LicenseType, NodeKind,
    PipelineRun, StepResult,
)
from pcip.publish.router import PublishError, PublishRouter, plain_text
from pcip.standards import PH, check_social_post

GOOD_CAPTION = (
    "Tres hábitos que ayudan a prevenir la diabetes. Consulta con un médico "
    f"cerca de mí en {PH.GEO_PHRASE}. {PH.BOOKING_ES}"
)


def setup(captions=None, body_html="<h2>Uno</h2><p>Camine 30 minutos.</p>",
          hashtags=("#SaludMiami",)):
    cfg = PCIPConfig()
    g = KnowledgeGraph(":memory:")
    out = Asset(id="out_1", name="Prevención de la Diabetes",
                license=License(type=LicenseType.CANVA_PRO, source="canva"),
                metadata={"via_export": True})
    g.upsert_node("out_1", NodeKind.OUTPUT, out.name, out.to_dict())
    brief = Brief(id="b1", title="Prevención", language="es")
    g.upsert_node("b1", NodeKind.BRIEF, brief.title, brief.to_dict())
    run = PipelineRun(
        id="run_1", pipeline="social_campaign", status="done", brief_id="b1",
        steps=[StepResult(step="export", status="done")],
        context={"copy_fields": {
            "title": "Tres hábitos", "body_html": body_html,
            "hashtags": list(hashtags),
            "captions": captions if captions is not None else {},
        }},
    )
    g.upsert_node("run_1", NodeKind.PIPELINE_RUN, "run", run.to_dict())
    g.add_edge("run_1", EdgeKind.PRODUCED, "out_1")
    return cfg, g, PublishRouter(cfg, g)


def dry(router, channel="instagram", **kw):
    kw.setdefault("media_urls", ["https://cdn.example/hero.png"])
    return router.publish("out_1", channel, dry_run=True, **kw)


# ── The gate that was shut ───────────────────────────────────────────────


def test_a_social_caption_is_not_held_to_the_article_standard():
    """The article standard demands an ES/EN pair, 600 words, three H2s, an
    FAQ block and the verbatim NAP line. Applying it to social meant every
    channel was unpublishable — the failure this test exists to keep fixed."""
    cfg, g, router = setup(captions={"instagram": GOOD_CAPTION})
    pub = dry(router)
    assert pub.status == "dry_run"
    assert pub.metadata["would_fail"] is False


def test_the_article_standard_still_guards_wordpress():
    cfg, g, router = setup()
    with pytest.raises(PublishError, match="article standard"):
        router.publish("out_1", Channel.WORDPRESS)


# ── What the social standard does enforce ────────────────────────────────


def test_a_caption_with_no_route_back_to_the_practice_is_refused():
    cfg, g, router = setup(captions={"instagram": "Cuide su salud cerca de mí."})
    with pytest.raises(PublishError, match="route back to the practice"):
        dry(router)


def test_pediatric_content_is_blocked_even_when_written_by_hand():
    """--text waives the editorial findings. It does not waive the
    exclusions PassQual Health states without exception."""
    cfg, g, router = setup()
    with pytest.raises(PublishError, match="pediatric"):
        dry(router, text=f"Cuidado pediátrico para niños. {PH.BOOKING_ES}")


def test_an_outcome_guarantee_is_blocked():
    cfg, g, router = setup()
    with pytest.raises(PublishError, match="prohibited claim"):
        dry(router, text=f"Resultados garantizado. {PH.BOOKING_ES}")


def test_mental_health_content_must_carry_both_crisis_numbers():
    cfg, g, router = setup()
    with pytest.raises(PublishError, match="988"):
        dry(router, text=f"Hablemos de la depresión. {PH.BOOKING_ES}")
    pub = dry(router, text=f"Hablemos de la depresión. Llame al 988 o 911. "
                           f"{PH.BOOKING_ES}")
    assert pub.status == "dry_run"


def test_operator_text_waives_the_editorial_findings_only():
    """No hashtags, no near-me phrasing — advisory and required findings that
    an operator writing their own caption has taken on."""
    cfg, g, router = setup()
    assert dry(router, text=f"Consulta hoy. {PH.BOOKING_ES}").status == "dry_run"


def test_instagram_without_media_is_refused_before_the_adapter():
    cfg, g, router = setup(captions={"instagram": GOOD_CAPTION})
    with pytest.raises(PublishError, match="media-first"):
        router.publish("out_1", "instagram", dry_run=True, media_urls=[])


# ── Captions ─────────────────────────────────────────────────────────────


def test_the_article_body_is_flattened_before_it_becomes_a_caption():
    """Without a channel caption the body is the fallback — and the body is
    HTML. Posting the markup verbatim is worse than posting nothing."""
    cfg, g, router = setup(
        captions={},
        body_html=f"<h2>Tres h&aacute;bitos</h2><p>Camine cerca de mí.</p>"
                  f"<p>{PH.BOOKING_ES}</p>",
    )
    caption = dry(router).metadata["caption"]
    assert "<" not in caption
    assert "hábitos" in caption            # entities decoded, not dropped


def test_hashtags_are_appended_to_generated_captions_only():
    cfg, g, router = setup(captions={"instagram": GOOD_CAPTION},
                           hashtags=("#SaludMiami", "#Diabetes"))
    assert dry(router).metadata["caption"].endswith("#SaludMiami #Diabetes")
    hand = dry(router, text=f"Mi propio texto. {PH.BOOKING_ES}")
    assert "#SaludMiami" not in hand.metadata["caption"]


# ── The dry run itself ───────────────────────────────────────────────────


def test_a_dry_run_records_nothing_in_the_graph():
    """The graph is the record of what was published. A rehearsal is not a
    publication, and a rehearsal that looked like one would corrupt the
    distribution history."""
    cfg, g, router = setup(captions={"instagram": GOOD_CAPTION})
    dry(router)
    assert g.nodes_by_kind(NodeKind.PUBLICATION) == []


def test_a_dry_run_shows_the_real_request_and_names_what_is_missing():
    cfg, g, router = setup(captions={"instagram": GOOD_CAPTION})
    meta = dry(router).metadata
    assert meta["adapter"] == "MetaAdapter"
    assert [c["method"] for c in meta["requests"]] == ["POST", "POST"]
    assert meta["requests"][0]["url"].endswith("/media")
    assert meta["missing_credentials"] == ["META_PAGE_TOKEN"]


def test_a_dry_run_reports_only_the_credentials_this_channel_needs():
    """A Threads preview listing YOUTUBE_TOKEN sends the operator to fix
    something unrelated to what they just previewed."""
    cfg, g, router = setup(captions={"threads": GOOD_CAPTION})
    meta = dry(router, channel="threads").metadata
    assert set(meta["missing_credentials"]) == {"THREADS_TOKEN", "THREADS_USER_ID"}


def test_a_dry_run_never_prints_a_configured_token():
    cfg, g, router = setup(captions={"instagram": GOOD_CAPTION})
    router.cfg.meta_page_token = "EAAG-secret-token"
    router.cfg.meta_ig_user_id = "17841400000000000"
    meta = dry(router).metadata
    assert "EAAG-secret-token" not in repr(meta)
    assert meta["missing_credentials"] == []
    assert meta["requests"][0]["url"].endswith("/17841400000000000/media")


def test_dry_run_on_wordpress_points_at_the_offline_path_that_exists():
    cfg, g, router = setup()
    with pytest.raises(PublishError, match="pcip prepare"):
        router.publish("out_1", Channel.WORDPRESS, dry_run=True)


def test_scheduled_posts_prefer_the_scheduler_in_the_dry_run_too():
    cfg, g, router = setup(captions={"instagram": GOOD_CAPTION})
    router.cfg.buffer_token = "buf"
    meta = dry(router, schedule_at="2026-03-01T10:00:00Z").metadata
    assert meta["adapter"] == "BufferAdapter"
    assert meta["preferred_mode"] == "scheduler"
    assert meta["fallback_used"] is False


# ── The standard in isolation ────────────────────────────────────────────


def test_check_social_post_passes_a_compliant_caption():
    check = check_social_post(
        {"caption": GOOD_CAPTION + " #SaludMiami", "channel": "instagram",
         "media": ["hero.png"], "language": "es"},
        limit=2200,
    )
    assert check.passed, check.report()


def test_check_social_post_flags_an_over_long_caption():
    check = check_social_post(
        {"caption": "x" * 300, "channel": "x", "language": "en"}, limit=280)
    assert any(v.rule == "caption_length" for v in check.required)


def test_plain_text_drops_scripts_and_keeps_paragraph_breaks():
    out = plain_text("<p>Uno</p><script>evil()</script><p>Dos</p>")
    assert out == "Uno\n\nDos"
