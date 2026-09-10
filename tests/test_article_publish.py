"""Tests for turning a finished pipeline run into a publishable article:
copy-field parsing, payload assembly, and the offline `pcip prepare` handoff.

All offline — no network, no credentials.
"""

import json

import pytest

from pcip.config import PCIPConfig
from pcip.generate.orchestrator import parse_copy_fields
from pcip.graph.store import KnowledgeGraph
from pcip.licensing import LicensingError
from pcip.models import (
    Asset,
    Brief,
    EdgeKind,
    License,
    LicenseType,
    NodeKind,
    PipelineRun,
    StepResult,
)
from pcip.publish.router import PublishError, PublishRouter, slugify

# ─── Copy-field parsing ─────────────────────────────────────────────────────

FENCED = """Here is the copy package.

Headline: Managing diabetes at home

```json
{
  "title": "Managing Type 2 Diabetes at Home",
  "excerpt": "Three habits that move your A1C.",
  "body_html": "<p>Small daily habits matter.</p>",
  "alt_texts": ["A patient checking their feet", "A glucose meter"],
  "hashtags": ["#diabetes", "#MiamiGardens"],
  "captions": {"instagram": "Small habits, big results."}
}
```
"""


def test_parses_the_fenced_block():
    fields = parse_copy_fields(FENCED)
    assert fields["title"] == "Managing Type 2 Diabetes at Home"
    assert fields["body_html"] == "<p>Small daily habits matter.</p>"
    assert fields["alt_texts"][1] == "A glucose meter"
    assert fields["hashtags"] == ["#diabetes", "#MiamiGardens"]
    assert fields["captions"]["instagram"].startswith("Small habits")


def test_hashtags_never_leak_into_the_article_body():
    """The whole point of parsing: the body is the body."""
    body = parse_copy_fields(FENCED)["body_html"]
    assert "#diabetes" not in body
    assert "alt_texts" not in body


def test_parses_an_unfenced_object():
    fields = parse_copy_fields('Some prose.\n{"title": "T", "body_html": "<p>B</p>"}')
    assert fields["title"] == "T"
    assert fields["body_html"] == "<p>B</p>"


def test_malformed_json_degrades_to_the_raw_text():
    text = "Just prose, and a broken block:\n```json\n{not valid,,}\n```"
    fields = parse_copy_fields(text)
    assert fields["body_html"] == text.strip()   # never empty, never an exception
    assert fields["alt_texts"] == []


def test_no_block_at_all_still_yields_a_body():
    fields = parse_copy_fields("A model that ignored the format entirely.")
    assert fields["body_html"] == "A model that ignored the format entirely."


def test_wrong_types_do_not_crash():
    fields = parse_copy_fields('```json\n{"alt_texts": "not a list", "captions": 5}\n```')
    assert fields["alt_texts"] == []
    assert fields["captions"] == {}


def test_empty_input_is_safe():
    assert parse_copy_fields("")["body_html"] == ""


# ─── Slugs ──────────────────────────────────────────────────────────────────


def test_slugify_handles_spanish_accents_and_punctuation():
    assert slugify("¿Qué es la diabetes? — Guía práctica") == "que-es-la-diabetes-guia-practica"


def test_slugify_is_bounded_and_trimmed():
    assert slugify("A" * 200) == "a" * 80
    assert not slugify("!!!").strip("-")


# ─── Payload assembly from a real run ───────────────────────────────────────


def build_graph(*, copy_fields=None, copy_text="", language="en", alt_texts=None,
                pages=None, run_status="done"):
    g = KnowledgeGraph(":memory:")
    brief = Brief(id="brief_1", title="Diabetes at Home", language=language)
    g.upsert_node(brief.id, NodeKind.BRIEF, brief.title, brief.to_dict())

    run = PipelineRun(id="run_1", pipeline="blog_graphics", brief_id="brief_1",
                      status=run_status, steps=[StepResult(step="export", status="done")])
    run.context = {"copy": copy_text}
    if copy_fields is not None:
        run.context["copy_fields"] = copy_fields
    g.upsert_node(run.id, NodeKind.PIPELINE_RUN, "run", run.to_dict())

    output = Asset(
        id="out_1",
        name="Diabetes at Home (png)",
        license=License(type=LicenseType.CANVA_PRO, source="canva"),
        metadata={"via_export": True, "format": "png",
                  "pages": pages if pages is not None else ["/tmp/a.png"],
                  "alt_texts": alt_texts or []},
    )
    g.upsert_node(output.id, NodeKind.OUTPUT, output.name, output.to_dict())
    g.add_edge(run.id, EdgeKind.PRODUCED, output.id)
    return g, output


def router_for(graph, **cfg_kwargs):
    return PublishRouter(PCIPConfig(**cfg_kwargs), graph)


def test_payload_uses_the_pipeline_copy_fields():
    g, out = build_graph(copy_fields={
        "title": "Real Title", "excerpt": "Real excerpt",
        "body_html": "<p>Real body</p>", "alt_texts": ["A real alt"],
        "hashtags": ["#x"], "captions": {"instagram": "IG caption"},
    })
    payload = router_for(g).payload_for(out)
    assert payload["title"] == "Real Title"
    assert payload["body_html"] == "<p>Real body</p>"
    assert payload["excerpt"] == "Real excerpt"
    assert payload["alt_texts"] == ["A real alt"]


def test_explicit_text_and_title_beat_the_generated_copy():
    g, out = build_graph(copy_fields={"title": "Generated", "body_html": "<p>Gen</p>"})
    payload = router_for(g).payload_for(out, title="Mine", text="<p>Mine</p>")
    assert payload["title"] == "Mine"
    assert payload["body_html"] == "<p>Mine</p>"


def test_falls_back_to_raw_prose_when_there_are_no_fields():
    g, out = build_graph(copy_text="Just the prose.")
    assert router_for(g).payload_for(out)["body_html"] == "Just the prose."


def test_alt_text_is_never_the_filename_style_output_name():
    g, out = build_graph(alt_texts=["A patient checking their feet"])
    assert router_for(g).payload_for(out)["alt_texts"] == ["A patient checking their feet"]


def test_alt_texts_are_padded_to_the_number_of_images():
    g, out = build_graph(alt_texts=["only one"],
                         pages=["/tmp/a.png", "/tmp/b.png", "/tmp/c.png"])
    alts = router_for(g).payload_for(out)["alt_texts"]
    assert len(alts) == 3
    assert alts[0] == "only one"
    assert all(a for a in alts)          # no empty alt attributes


def test_language_comes_from_the_brief():
    g, out = build_graph(language="es")
    assert router_for(g).payload_for(out)["language"] == "es"


# ─── The offline handoff ────────────────────────────────────────────────────


def prepared(tmp_path, **kwargs):
    g, out = build_graph(**kwargs)
    router = router_for(g, data_dir=tmp_path)
    return router, router.prepare("out_1", dest=str(tmp_path / "handoff"))


def test_prepare_writes_the_expected_layout(tmp_path):
    _, result = prepared(tmp_path, copy_fields={
        "title": "Managing Diabetes", "excerpt": "An excerpt",
        "body_html": "<p>Body</p>", "alt_texts": ["An alt"],
    })
    folder = tmp_path / "handoff"
    assert (folder / "article.html").read_text() == "<p>Body</p>"
    assert (folder / "README.md").exists()
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["title"] == "Managing Diabetes"
    assert meta["suggested_slug"] == "managing-diabetes"
    assert meta["excerpt"] == "An excerpt"
    assert meta["alt_texts"] == ["An alt"]
    assert result["folder"] == str(folder)


def test_prepare_states_where_the_article_will_appear(tmp_path):
    _, result = prepared(tmp_path, copy_fields={"title": "Managing Diabetes",
                                                "body_html": "<p>b</p>"})
    assert result["expected_public_url"] == "https://passqual.com/managing-diabetes/"


def test_prepare_uses_the_es_prefix_for_spanish_briefs(tmp_path):
    _, result = prepared(tmp_path, language="es",
                         copy_fields={"title": "Diabetes en Casa",
                                      "body_html": "<p>b</p>"})
    assert result["expected_public_url"] == "https://passqual.com/es/diabetes-en-casa/"


def test_prepare_readme_carries_the_htaccess_fix_and_alt_text(tmp_path):
    _, _ = prepared(tmp_path, copy_fields={"title": "T", "body_html": "<p>b</p>",
                                           "alt_texts": ["An alt"]})
    readme = (tmp_path / "handoff" / "README.md").read_text()
    assert "wp-admin" in readme
    assert "60 seconds" in readme
    assert "Authorization-header fix" in readme


def test_prepare_copies_media_next_to_the_article(tmp_path):
    media = tmp_path / "export.png"
    media.write_bytes(b"\x89PNG")
    g, _ = build_graph(pages=[str(media)], alt_texts=["An alt"],
                       copy_fields={"title": "T", "body_html": "<p>b</p>"})
    result = router_for(g, data_dir=tmp_path).prepare("out_1",
                                                      dest=str(tmp_path / "h"))
    assert (tmp_path / "h" / "media" / "export.png").read_bytes() == b"\x89PNG"
    assert result["media"] == ["export.png"]


def test_prepare_needs_no_wordpress_credentials(tmp_path):
    """The whole point: it works while the REST write path is blocked."""
    g, _ = build_graph(copy_fields={"title": "T", "body_html": "<p>b</p>"})
    assert PCIPConfig().wordpress_configured is False
    result = router_for(g, data_dir=tmp_path).prepare("out_1")
    assert result["title"] == "T"


def test_prepare_enforces_the_same_review_gate(tmp_path):
    g, _ = build_graph(run_status="awaiting_review",
                       copy_fields={"title": "T", "body_html": "<p>b</p>"})
    with pytest.raises(PublishError, match="awaiting_review"):
        router_for(g, data_dir=tmp_path).prepare("out_1")


def test_prepare_enforces_the_same_licensing_gate(tmp_path):
    g, _ = build_graph(copy_fields={"title": "T", "body_html": "<p>b</p>"})
    node = g.get_node("out_1")
    node["payload"]["metadata"].pop("via_export")        # premium, not exported
    g.upsert_node("out_1", NodeKind.OUTPUT, node["name"], node["payload"])
    with pytest.raises(LicensingError):
        router_for(g, data_dir=tmp_path).prepare("out_1")


def test_prepare_records_no_publication(tmp_path):
    """Nothing was published, so the distribution record must stay empty."""
    g, _ = build_graph(copy_fields={"title": "T", "body_html": "<p>b</p>"})
    router = router_for(g, data_dir=tmp_path)
    router.prepare("out_1")
    assert router.where_did_it_go("out_1") == []


# ─── Publish-side guards ────────────────────────────────────────────────────


def test_publish_refuses_an_empty_body_with_guidance():
    g, _ = build_graph(copy_text="", copy_fields={})
    router = router_for(g, wordpress_user="u", wordpress_app_password="p")
    with pytest.raises(PublishError) as exc:
        router.publish("out_1", "wordpress")
    assert "--text" in str(exc.value)


def test_route_plan_explains_the_two_hosts_and_isr():
    g, _ = build_graph()
    plan = router_for(g).route_plan("wordpress")
    assert plan["api_origin"] == "https://wp.passqual.com"
    assert plan["reader_site"] == "https://passqual.com"
    assert plan["instant_revalidation"] is False
    assert "60s" in plan["note"]
