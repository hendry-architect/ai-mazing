

# ── the Canva imagery route must not depend on how assembly runs ──────────


def test_canva_imagery_survives_the_switch_to_connect_mode():
    """Connect mode adds capability everywhere else. It must not remove the
    one imagery source the account already pays for — Canva's generation is
    out of reach of the Connect API either way, so the handoff is the route
    in both modes."""
    from pcip.config import PCIPConfig
    from pcip.generate.media_providers import CanvaImageProvider

    mcp_mode = PCIPConfig(canva_mode="mcp")
    assert CanvaImageProvider(mcp_mode).available() is True

    connect_with_tokens = PCIPConfig(canva_mode="connect", canva_access_token="at")
    assert CanvaImageProvider(connect_with_tokens).available() is True

    no_canva_at_all = PCIPConfig(canva_mode="connect")
    assert CanvaImageProvider(no_canva_at_all).available() is False


def test_a_paid_image_api_still_outranks_the_canva_handoff():
    """The handoff pauses the run, so anything unattended must win."""
    from pcip.generate.capabilities import MediaSpec, default_registry

    registry = default_registry()
    for style in ("general", "photorealistic", "social", "infographic"):
        spec = MediaSpec(modality="image", style=style)
        assert registry.select(spec, ["canva-images", "openai-images"]) == (
            "openai-images"
        ), f"canva-images must not win {style} when an API provider exists"
    # ...and it is still there as the fallback when nothing else is.
    assert registry.select(
        MediaSpec(modality="image"), ["canva-images"]
    ) == "canva-images"
