"""Connector catalog — one descriptor per connector, capabilities included.

This is where vendor truth lives. Capabilities the vendor's API genuinely
does not offer are declared ``supported=False`` with a note, so the planner
reads an honest matrix instead of assuming a connected system can do
everything. Plan-gated capabilities carry an ``entitlement`` tag and are
discovered live by the connector's probe (e.g. Canva brand templates on a
non-Enterprise plan probe out as ``not_entitled``, not as a hard failure).
"""

from __future__ import annotations

from typing import Dict

import requests

from pcip.config import PCIPConfig
from pcip.connectors.framework import (
    CapabilitySpec,
    ConnectorAuthError,
    ConnectorBlockedError,
    ConnectorDescriptor,
    EntitlementError,
)


# ─── Live probes (cheap, read-only) ──────────────────────────────────────────


def probe_canva(cfg: PCIPConfig) -> Dict[str, str]:
    from pcip.connectors.canva import CanvaClient, CanvaError

    client = CanvaClient(cfg)
    try:
        client.me()
    except CanvaError as exc:
        raise ConnectorAuthError(f"Canva auth failed: {exc}") from exc
    overrides: Dict[str, str] = {}
    try:
        client.list_brand_templates()
        overrides["duplicate_template"] = "ready"
    except Exception:
        raise EntitlementError(
            ["duplicate_template"],
            "brand-template/autofill APIs need Canva Enterprise",
        )
    return overrides


def probe_anthropic(cfg: PCIPConfig) -> Dict[str, str]:
    resp = requests.get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": cfg.anthropic_api_key,
                 "anthropic-version": "2023-06-01"},
        timeout=cfg.request_timeout,
    )
    if resp.status_code in (401, 403):
        raise ConnectorAuthError(f"Anthropic key rejected ({resp.status_code})")
    resp.raise_for_status()
    return {}


def probe_openai(cfg: PCIPConfig) -> Dict[str, str]:
    resp = requests.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {cfg.openai_api_key}"},
        timeout=cfg.request_timeout,
    )
    if resp.status_code in (401, 403):
        raise ConnectorAuthError(f"OpenAI key rejected ({resp.status_code})")
    resp.raise_for_status()
    return {}


def probe_google_ai(cfg: PCIPConfig) -> Dict[str, str]:
    resp = requests.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": cfg.google_ai_api_key},
        timeout=cfg.request_timeout,
    )
    if resp.status_code in (400, 401, 403):
        raise ConnectorAuthError(f"Google AI key rejected ({resp.status_code})")
    resp.raise_for_status()
    return {}


def probe_wordpress(cfg: PCIPConfig) -> Dict[str, str]:
    """Verify the WordPress path end to end, without publishing anything.

    Goes through the hardened transport so a SiteGround anti-bot challenge
    (a 2xx carrying HTML) can never be mistaken for a healthy API, and asks
    WordPress whether this account may actually create posts — a read
    succeeding does not imply a write will.
    """
    from pcip.connectors.wordpress import (
        WordPressAuthHeaderError,
        WordPressChallengeError,
        WordPressError,
        WordPressPermissionError,
        WordPressPublisher,
    )

    wp = WordPressPublisher(cfg)
    try:
        wp._get("/users/me")
    except WordPressChallengeError as exc:
        raise ConnectorBlockedError(str(exc)) from exc
    except (WordPressAuthHeaderError, WordPressPermissionError) as exc:
        raise ConnectorAuthError(str(exc)) from exc

    gaps, reasons = [], []
    if not cfg.revalidation_configured:
        gaps.append("instant_revalidate")
        reasons.append(
            "instant revalidation is off (set VERCEL_REVALIDATE_URL and "
            "WP_REVALIDATE_SECRET, and the matching secret on the site) — "
            "articles still go live within ~60s without it"
        )
    try:
        if not wp.can_write_posts():
            gaps.append("create_post")
            reasons.append(
                "this WordPress account cannot create posts — grant it Author "
                "or Editor rights, or use a different Application Password"
            )
    except WordPressError:
        # OPTIONS unsupported or refused: no verdict is better than a wrong one.
        pass

    if gaps:
        raise EntitlementError(gaps, "; ".join(reasons))
    return {}


# ─── The catalog ─────────────────────────────────────────────────────────────

CATALOG = [
    ConnectorDescriptor(
        name="github",
        auth_methods=("oauth",),
        mcp_managed=True,
        docs_url="https://github.com/github/github-mcp-server",
        capabilities=(
            CapabilitySpec("repo_read", "read code, files, history"),
            CapabilitySpec("repo_write", "branches, commits, pushes"),
            CapabilitySpec("pr_automation", "create/review/merge PRs, CI status"),
        ),
    ),
    ConnectorDescriptor(
        name="canva",
        auth_methods=("oauth",),
        env_vars=(),
        env_any=(("canva_access_token",), ("canva_refresh_token", "canva_client_id")),
        docs_url="https://www.canva.dev/docs/connect/",
        setup_ref="pcip/SETUP.md Phase 1",
        probe=probe_canva,
        capabilities=(
            CapabilitySpec("create_design", "POST /designs"),
            CapabilitySpec(
                "duplicate_template",
                "brand-template autofill into a new design",
                entitlement="canva_enterprise",
            ),
            CapabilitySpec("export_png", "official export API (PNG/JPG)"),
            CapabilitySpec("export_pdf", "official export API (PDF)"),
            CapabilitySpec("export_pptx", "official export API (PPTX)"),
            CapabilitySpec("search_assets", "own designs/folders/uploads + PCIP graph FTS"),
            CapabilitySpec(
                "search_premium_assets",
                supported=False,
                note="the Connect API does not expose Canva's premium stock "
                     "library for search; premium elements are used in-app or "
                     "via the Canva MCP and leave only through design export "
                     "(enforced by pcip/licensing.py)",
            ),
            CapabilitySpec("upload_media", "url-asset-uploads (job-based)"),
            CapabilitySpec("write_folders", "create folders, move items"),
            CapabilitySpec(
                "edit_text",
                supported=False,
                note="no direct text-edit endpoint in the Connect API — text "
                     "enters designs via brand-template autofill (Enterprise) "
                     "or in-app/Canva-MCP editing",
            ),
        ),
    ),
    ConnectorDescriptor(
        name="anthropic",
        auth_methods=("api_key",),
        env_vars=("anthropic_api_key",),
        docs_url="https://docs.anthropic.com/",
        setup_ref="pcip/SETUP.md Phase 2",
        probe=probe_anthropic,
        capabilities=(
            CapabilitySpec("generate_copy",
                           "headlines, captions, CTA, hashtags, alt-text"),
        ),
    ),
    ConnectorDescriptor(
        name="wordpress",
        auth_methods=("app_password", "oauth"),
        env_any=(("wordpress_com_token",),
                 ("wordpress_user", "wordpress_app_password")),
        docs_url="https://developer.wordpress.org/rest-api/",
        setup_ref="pcip/SETUP.md Phase 3",
        probe=probe_wordpress,
        capabilities=(
            CapabilitySpec("create_post", "draft by default; --live is explicit",
                           note="WORDPRESS_URL must point at the WordPress origin "
                                "(e.g. wp.passqual.com), not the public site, which "
                                "blocks /wp-json/*"),
            CapabilitySpec("upload_media", "media library upload with alt-text"),
            CapabilitySpec("schedule_post", "native future-dated publishing"),
            CapabilitySpec(
                "instant_revalidate",
                "purge the public site's cache on publish",
                note="without it the article still appears within ~60s via the "
                     "site's own revalidation window",
            ),
            CapabilitySpec(
                "edit_live_page",
                supported=False,
                note="the public site's marketing/service pages are hand-authored "
                     "modules in the website repository, deliberately not "
                     "WordPress-driven — PCIP publishes articles only",
            ),
        ),
    ),
    ConnectorDescriptor(
        name="openai",
        auth_methods=("api_key",),
        env_vars=("openai_api_key",),
        docs_url="https://platform.openai.com/docs/guides/image-generation",
        setup_ref="pcip/SETUP.md Phase 4",
        probe=probe_openai,
        capabilities=(
            CapabilitySpec("generate_image", "default image provider (gpt-image-1)"),
        ),
    ),
    ConnectorDescriptor(
        name="google",
        auth_methods=("api_key", "oauth"),
        env_vars=("google_ai_api_key",),
        docs_url="https://ai.google.dev/gemini-api/docs",
        setup_ref="pcip/SETUP.md Phases 4-5",
        probe=probe_google_ai,
        capabilities=(
            CapabilitySpec("generate_image_imagen", "photorealistic imagery",
                           note="requires billing enabled on the key's project"),
            CapabilitySpec("generate_video_veo", "premium cinematic video",
                           note="requires billing enabled on the key's project"),
        ),
    ),
    ConnectorDescriptor(
        name="ideogram",
        auth_methods=("api_key",),
        env_vars=("ideogram_api_key",),
        docs_url="https://developer.ideogram.ai/",
        setup_ref="pcip/SETUP.md Phase 4",
        capabilities=(CapabilitySpec("generate_image_typography",
                                     "text-heavy graphics"),),
    ),
    ConnectorDescriptor(
        name="flux",
        auth_methods=("api_key",),
        env_vars=("bfl_api_key",),
        docs_url="https://docs.bfl.ai/",
        setup_ref="pcip/SETUP.md Phase 4",
        capabilities=(CapabilitySpec("generate_image",
                                     "self-host/open ecosystem"),),
    ),
    ConnectorDescriptor(
        name="runway",
        auth_methods=("api_key",),
        env_vars=("runway_api_key",),
        docs_url="https://docs.dev.runwayml.com/",
        setup_ref="pcip/SETUP.md Phase 5",
        capabilities=(
            CapabilitySpec("generate_video", "image-to-video (needs seed frame)"),
        ),
    ),
    ConnectorDescriptor(
        name="pika",
        auth_methods=("api_key",),
        env_vars=("pika_api_key", "pika_endpoint"),
        setup_ref="pcip/SETUP.md Phase 5",
        capabilities=(
            CapabilitySpec("generate_video", "fast social clips",
                           note="partner-hosted API only — PIKA_ENDPOINT required"),
        ),
    ),
    ConnectorDescriptor(
        name="luma",
        auth_methods=("api_key",),
        env_vars=("luma_api_key",),
        docs_url="https://docs.lumalabs.ai/",
        setup_ref="pcip/SETUP.md Phase 5",
        capabilities=(CapabilitySpec("generate_video", "stylized motion"),),
    ),
    ConnectorDescriptor(
        name="instagram",
        auth_methods=("oauth",),
        env_vars=("meta_page_token", "meta_ig_user_id"),
        docs_url="https://developers.facebook.com/docs/instagram-platform/content-publishing",
        setup_ref="pcip/SETUP.md Phase 6",
        capabilities=(
            CapabilitySpec("publish_post", "container → publish (direct API)"),
            CapabilitySpec("schedule_post", supported=False,
                           note="IG Graph API has no native scheduling — "
                                "route scheduled IG posts through Buffer"),
        ),
    ),
    ConnectorDescriptor(
        name="facebook",
        auth_methods=("oauth",),
        env_vars=("meta_page_token",),
        docs_url="https://developers.facebook.com/docs/pages-api",
        setup_ref="pcip/SETUP.md Phase 6",
        capabilities=(
            CapabilitySpec("publish_post", "page feed/photos (direct API)"),
            CapabilitySpec("schedule_post", "native scheduled_publish_time"),
        ),
    ),
    ConnectorDescriptor(
        name="threads",
        auth_methods=("oauth",),
        env_vars=("threads_token", "threads_user_id"),
        docs_url="https://developers.facebook.com/docs/threads",
        setup_ref="pcip/SETUP.md Phase 6",
        capabilities=(CapabilitySpec("publish_post", "container → publish"),),
    ),
    ConnectorDescriptor(
        name="linkedin",
        auth_methods=("oauth",),
        env_vars=("linkedin_token", "linkedin_org_urn"),
        docs_url="https://learn.microsoft.com/en-us/linkedin/marketing/",
        setup_ref="pcip/SETUP.md Phase 6",
        capabilities=(CapabilitySpec("publish_post", "organization page posts"),),
    ),
    ConnectorDescriptor(
        name="x",
        auth_methods=("oauth",),
        env_vars=("x_user_token",),
        docs_url="https://docs.x.com/x-api/introduction",
        setup_ref="pcip/SETUP.md Phase 6",
        capabilities=(CapabilitySpec("publish_post", "v2 /tweets"),),
    ),
    ConnectorDescriptor(
        name="youtube",
        auth_methods=("oauth",),
        env_vars=("youtube_token",),
        docs_url="https://developers.google.com/youtube/v3",
        setup_ref="pcip/SETUP.md Phase 6",
        capabilities=(
            CapabilitySpec("publish_video", "resumable upload"),
            CapabilitySpec("schedule_post", "native publishAt"),
        ),
    ),
    ConnectorDescriptor(
        name="tiktok",
        auth_methods=("oauth",),
        env_vars=("tiktok_token",),
        docs_url="https://developers.tiktok.com/doc/content-posting-api-get-started",
        setup_ref="pcip/SETUP.md Phase 6",
        capabilities=(
            CapabilitySpec("publish_video", "Content Posting API",
                           note="requires TikTok app review approval"),
        ),
    ),
    ConnectorDescriptor(
        name="buffer",
        auth_methods=("api_key",),
        env_vars=("buffer_token",),
        docs_url="https://buffer.com/developers/api",
        setup_ref="pcip/SETUP.md Phase 6",
        capabilities=(
            CapabilitySpec("schedule_post",
                           "queue/calendar across all connected profiles"),
            CapabilitySpec("publish_post", "immediate via queue (fallback path)"),
        ),
    ),
]
