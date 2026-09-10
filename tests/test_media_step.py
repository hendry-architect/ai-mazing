"""Capability-routed image generation, wired into the pipelines.

The vendor-agnostic provider layer and the capability registry were built and
tested months of commits ago, and no pipeline ever invoked them — eight
providers of dead code. This is the step that uses them.
"""

import pytest

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief
from pcip.pipelines.library import PIPELINES, generate_hero_image


def ctx(**over):
    base = {
        "cfg": PCIPConfig(),
        "graph": KnowledgeGraph(":memory:"),
        "brief": Brief(id="b1", title="Prevención de la diabetes",
                       objective="Enseñar tres hábitos diarios",
                       brand="PassQual Health", language="es"),
        "media_preset": "healthcare_photo",
    }
    base.update(over)
    return base


# ── wiring ───────────────────────────────────────────────────────────────────


def test_every_pipeline_generates_imagery():
    for name, pipeline in PIPELINES.items():
        steps = [getattr(s, "name", "") for s in pipeline.steps]
        assert "generate_media" in steps, name


def test_imagery_runs_before_the_standard_gate():
    """So a generated hero counts toward the check instead of reading as
    missing until export."""
    steps = [getattr(s, "name", "") for s in PIPELINES["patient_education"].steps]
    assert steps.index("generate_media") < steps.index("ph_standard")


def test_each_pipeline_asks_for_the_right_kind_of_picture():
    """A patient handout, a blog hero and a social tile are not one picture."""
    def preset(name):
        c = {}
        [s for s in PIPELINES[name].steps if getattr(s, "name", "") == "format"][0].handler(c)
        return c["media_preset"]

    assert preset("patient_education") == "healthcare_photo"
    assert preset("social_campaign") == "social_quote"


# ── behaviour ────────────────────────────────────────────────────────────────


def test_no_provider_configured_skips_rather_than_fails():
    """The Canva design is the real artwork; refusing to run without an image
    provider would block a pipeline that worked for weeks without one."""
    c = ctx()
    detail = generate_hero_image(c)
    assert "skipped" in detail.lower()
    assert c["media_generation"]["skipped"] is True
    assert "generated_media" not in c


def test_a_vendor_failure_is_not_fatal(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("provider is down")

    monkeypatch.setattr(
        "pcip.generate.orchestrator.GenerationOrchestrator.generate_media", boom
    )
    c = ctx()
    detail = generate_hero_image(c)
    assert "continuing without it" in detail
    assert c["media_generation"]["skipped"] is True


def test_supplied_imagery_is_not_regenerated():
    c = ctx(media_paths=["/tmp/already.png"])
    assert "skipped" in generate_hero_image(c).lower()


def test_a_generated_image_is_recorded_with_its_provider(monkeypatch):
    from pcip.generate.providers import GenerationResult
    from pcip.models import Asset

    def fake(self, spec, prompt, brief=None, params=None):
        assert "PassQual Health" in prompt
        assert "no text" in prompt        # a hero with baked-in text is unusable
        return GenerationResult(
            provider="openai-images", capability="image",
            assets=[Asset(id="gen_1", name="hero", kind="image",
                          local_path="/tmp/hero.png")],
            metadata={"ranking": [["openai-images", 0.9], ["imagen", 0.7]]},
        )

    monkeypatch.setattr(
        "pcip.generate.orchestrator.GenerationOrchestrator.generate_media", fake
    )
    c = ctx()
    detail = generate_hero_image(c)
    assert "openai-images" in detail
    assert c["generated_media"] == ["/tmp/hero.png"]
    # The routing decision is auditable, not just the winner.
    assert c["media_generation"]["ranking"][0][0] == "openai-images"
    assert "gen_1" in c["_step_outputs"]


def test_the_prompt_is_built_from_the_article_not_just_the_brief(monkeypatch):
    seen = {}

    def fake(self, spec, prompt, brief=None, params=None):
        seen["prompt"] = prompt
        from pcip.generate.providers import GenerationResult
        return GenerationResult(provider="p", capability="image", assets=[])

    monkeypatch.setattr(
        "pcip.generate.orchestrator.GenerationOrchestrator.generate_media", fake
    )
    generate_hero_image(ctx(copy_fields={
        "meta_description": "Tres hábitos diarios para cuidar su azúcar."
    }))
    assert "azúcar" in seen["prompt"], "the copy step already decided the subject"


# ── imagery without a second subscription ────────────────────────────────────


def test_canva_supplies_imagery_when_no_api_is_configured():
    """The account already pays for Canva. Buying a second image API to
    produce what the existing subscription produces is a cost with no
    capability behind it."""
    from pcip.generate.providers import ProviderRegistry

    names = ProviderRegistry(PCIPConfig(canva_mode="mcp")).available_names("image")
    assert "canva-images" in names


def test_canva_imagery_is_unavailable_where_no_session_can_service_it():
    """It works by pausing for an agent session. In connect mode there is
    nobody to ask, so offering it would strand an unattended run."""
    from pcip.generate.providers import ProviderRegistry

    names = ProviderRegistry(PCIPConfig(canva_mode="connect")).available_names("image")
    assert "canva-images" not in names


def test_a_configured_api_outranks_canva():
    """Canva needs a human in the loop; an API does not. When both are
    available the unattended one wins."""
    from pcip.generate.capabilities import default_registry, spec_for

    ranked = default_registry().rank(
        spec_for("healthcare_photo"), ["canva-images", "openai-images"]
    )
    assert ranked[0][0] == "openai-images"
    assert "canva-images" in [name for name, _ in ranked]   # still a fallback


def test_the_canva_provider_pauses_rather_than_failing():
    from pcip.generate.media_providers import CanvaImageProvider
    from pcip.generate.providers import GenerationRequest
    from pcip.pipelines.base import HandoffRequired

    provider = CanvaImageProvider(PCIPConfig(canva_mode="mcp"))
    with pytest.raises(HandoffRequired) as exc:
        provider.generate(GenerationRequest(capability="image", prompt="a clinic"))
    how = exc.value.spec["how"]
    assert "generate-design" in how
    assert "official export workflow" in how      # the licence path, stated


def test_a_handoff_is_not_swallowed_as_a_failed_generation(monkeypatch):
    """A pause is not an outage. Reporting "continuing without imagery" for a
    run that is simply waiting for someone would strand it silently."""
    from pcip.pipelines.base import HandoffRequired

    def pause(*a, **kw):
        raise HandoffRequired("imagery", {"how": "source it in Canva"})

    monkeypatch.setattr(
        "pcip.generate.orchestrator.GenerationOrchestrator.generate_media", pause
    )
    with pytest.raises(HandoffRequired):
        generate_hero_image(ctx())
