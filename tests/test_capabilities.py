"""Capability registry tests — routing picks vendors by capability, not name.

These encode the chief-architect decisions: OpenAI default, Imagen for
photorealism, Ideogram for typography; Veo premium video, Runway production
fallback, Pika fast social. If a profile change breaks one of these, that is
a deliberate re-decision, not a refactor.
"""

import pytest

from pcip.generate.capabilities import (
    MediaSpec,
    NoCapableProvider,
    default_registry,
    spec_for,
)

ALL_IMAGE = ["openai-images", "imagen", "ideogram", "flux"]
ALL_VIDEO = ["veo", "runway", "pika", "luma"]


def test_default_image_provider_is_openai():
    reg = default_registry()
    assert reg.select(spec_for("infographic"), ALL_IMAGE) == "openai-images"
    assert reg.select(spec_for("blog_hero"), ALL_IMAGE) == "openai-images"


def test_photorealism_routes_to_imagen():
    reg = default_registry()
    assert reg.select(spec_for("healthcare_photo"), ALL_IMAGE) == "imagen"


def test_typography_routes_to_ideogram():
    reg = default_registry()
    assert reg.select(spec_for("social_quote"), ALL_IMAGE) == "ideogram"


def test_cinematic_video_routes_to_veo():
    reg = default_registry()
    assert reg.select(spec_for("cinematic_video"), ALL_VIDEO) == "veo"


def test_quick_reel_routes_to_fast_social_provider():
    reg = default_registry()
    assert reg.select(spec_for("quick_reel"), ALL_VIDEO) == "pika"


def test_duration_ceiling_eliminates_short_form_providers():
    reg = default_registry()
    spec = MediaSpec(modality="video", style="social", duration_s=30)
    ranked = dict(reg.rank(spec, ALL_VIDEO))
    assert "pika" not in ranked          # max 15s
    assert "luma" not in ranked          # max 20s
    assert reg.select(spec, ALL_VIDEO) in ("runway", "veo")


def test_routing_respects_configured_availability():
    """When the best vendor isn't configured, the next capable one wins —
    business logic never has to know."""
    reg = default_registry()
    assert reg.select(spec_for("social_quote"), ["openai-images"]) == "openai-images"
    assert reg.select(spec_for("cinematic_video"), ["runway"]) == "runway"


def test_no_capable_provider_raises():
    reg = default_registry()
    with pytest.raises(NoCapableProvider):
        reg.select(spec_for("quick_reel"), available=[])
    with pytest.raises(NoCapableProvider):
        # Image providers can never satisfy a video spec.
        reg.select(spec_for("cinematic_video"), ALL_IMAGE)


def test_modality_is_a_hard_constraint():
    reg = default_registry()
    for name, score in reg.rank(spec_for("healthcare_photo")):
        assert reg.profile(name).modality == "image"


def test_spec_presets_and_overrides():
    spec = spec_for("quick_reel", duration_s=10)
    assert spec.duration_s == 10
    assert spec.vertical
    with pytest.raises(KeyError):
        spec_for("interpretive_dance")
