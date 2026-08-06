"""Configuration for PCIP.

All credentials come from environment variables (or a .env you export before
running — same convention as the rest of this repo). Nothing is hardcoded and
nothing secret is ever written to the graph database or logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_DATA_DIR = "pcip_data"


@dataclass
class PCIPConfig:
    # ── Storage ──────────────────────────────────────────────────────────
    data_dir: Path = field(default_factory=lambda: Path(DEFAULT_DATA_DIR))

    # ── Canva Connect API ────────────────────────────────────────────────
    # Create an integration at https://www.canva.com/developers/ and grant:
    #   design:meta:read design:content:read design:content:write
    #   folder:read asset:read brandtemplate:meta:read brandtemplate:content:read
    canva_client_id: str = ""
    canva_client_secret: str = ""
    canva_access_token: str = ""       # short-lived; refreshed automatically
    canva_refresh_token: str = ""
    canva_api_base: str = "https://api.canva.com/rest/v1"

    # ── Anthropic (copy generation) ──────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # ── Image generation providers (capability-routed; all optional) ─────
    openai_api_key: str = ""           # OpenAI Images — default image provider
    openai_image_model: str = "gpt-image-1"
    google_ai_api_key: str = ""        # Gemini API key — Imagen (and Veo video)
    ideogram_api_key: str = ""         # Ideogram — typography-heavy graphics
    bfl_api_key: str = ""              # Black Forest Labs — Flux
    flux_endpoint: str = "https://api.bfl.ml"

    # ── Video generation providers (capability-routed; all optional) ────
    runway_api_key: str = ""           # Runway — production fallback
    pika_api_key: str = ""             # Pika — fast social clips (partner-hosted API)
    pika_endpoint: str = ""
    luma_api_key: str = ""             # Luma Dream Machine — stylized motion

    # ── WordPress (passqual.com) ─────────────────────────────────────────
    # Self-hosted WP: site URL + application password (Users → Profile →
    # Application Passwords). WordPress.com: OAuth bearer token.
    wordpress_url: str = "https://passqual.com"
    wordpress_user: str = ""
    wordpress_app_password: str = ""
    wordpress_com_token: str = ""

    # ── Social channels (each optional; unconfigured = channel disabled) ─
    # Direct platform APIs are first-class (full capability + resilience);
    # Buffer is a scheduling provider, not the only publishing path.
    buffer_token: str = ""
    meta_page_token: str = ""          # Facebook Page / Instagram Business
    meta_ig_user_id: str = ""
    linkedin_token: str = ""
    linkedin_org_urn: str = ""
    x_user_token: str = ""             # X API v2 OAuth2 user-context token
    threads_token: str = ""            # Threads API (Meta)
    threads_user_id: str = ""
    youtube_token: str = ""            # YouTube Data API v3 OAuth token
    tiktok_token: str = ""             # TikTok Content Posting API token

    # ── Behavior ─────────────────────────────────────────────────────────
    default_brand: str = "PassQual"
    auto_approve_gates: List[str] = field(default_factory=list)
    request_timeout: int = 60

    @property
    def graph_db_path(self) -> Path:
        return self.data_dir / "graph.db"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def channel_status(self) -> Dict[str, bool]:
        """Which connectors are configured (no secrets exposed)."""
        return {
            "canva": bool(self.canva_access_token or self.canva_refresh_token),
            "anthropic": bool(self.anthropic_api_key),
            "openai_images": bool(self.openai_api_key),
            "google_ai": bool(self.google_ai_api_key),
            "ideogram": bool(self.ideogram_api_key),
            "flux": bool(self.bfl_api_key),
            "runway": bool(self.runway_api_key),
            "pika": bool(self.pika_api_key and self.pika_endpoint),
            "luma": bool(self.luma_api_key),
            "wordpress": bool(
                self.wordpress_com_token
                or (self.wordpress_user and self.wordpress_app_password)
            ),
            "buffer": bool(self.buffer_token),
            "meta": bool(self.meta_page_token),
            "linkedin": bool(self.linkedin_token),
            "x": bool(self.x_user_token),
            "threads": bool(self.threads_token and self.threads_user_id),
            "youtube": bool(self.youtube_token),
            "tiktok": bool(self.tiktok_token),
        }


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_config(data_dir: Optional[str] = None) -> PCIPConfig:
    """Build a PCIPConfig from PCIP_* / provider environment variables."""
    cfg = PCIPConfig(
        data_dir=Path(data_dir or _env("PCIP_DATA_DIR", DEFAULT_DATA_DIR)),
        canva_client_id=_env("CANVA_CLIENT_ID"),
        canva_client_secret=_env("CANVA_CLIENT_SECRET"),
        canva_access_token=_env("CANVA_ACCESS_TOKEN"),
        canva_refresh_token=_env("CANVA_REFRESH_TOKEN"),
        canva_api_base=_env("CANVA_API_BASE", "https://api.canva.com/rest/v1"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("PCIP_ANTHROPIC_MODEL", "claude-sonnet-5"),
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_image_model=_env("PCIP_OPENAI_IMAGE_MODEL", "gpt-image-1"),
        google_ai_api_key=_env("GOOGLE_AI_API_KEY"),
        ideogram_api_key=_env("IDEOGRAM_API_KEY"),
        bfl_api_key=_env("BFL_API_KEY"),
        flux_endpoint=_env("FLUX_ENDPOINT", "https://api.bfl.ml"),
        runway_api_key=_env("RUNWAY_API_KEY"),
        pika_api_key=_env("PIKA_API_KEY"),
        pika_endpoint=_env("PIKA_ENDPOINT"),
        luma_api_key=_env("LUMA_API_KEY"),
        wordpress_url=_env("WORDPRESS_URL", "https://passqual.com").rstrip("/"),
        wordpress_user=_env("WORDPRESS_USER"),
        wordpress_app_password=_env("WORDPRESS_APP_PASSWORD"),
        wordpress_com_token=_env("WORDPRESS_COM_TOKEN"),
        buffer_token=_env("BUFFER_TOKEN"),
        meta_page_token=_env("META_PAGE_TOKEN"),
        meta_ig_user_id=_env("META_IG_USER_ID"),
        linkedin_token=_env("LINKEDIN_TOKEN"),
        linkedin_org_urn=_env("LINKEDIN_ORG_URN"),
        x_user_token=_env("X_USER_TOKEN"),
        threads_token=_env("THREADS_TOKEN"),
        threads_user_id=_env("THREADS_USER_ID"),
        youtube_token=_env("YOUTUBE_TOKEN"),
        tiktok_token=_env("TIKTOK_TOKEN"),
        default_brand=_env("PCIP_DEFAULT_BRAND", "PassQual"),
        auto_approve_gates=[
            g.strip()
            for g in _env("PCIP_AUTO_APPROVE_GATES").split(",")
            if g.strip()
        ],
    )
    timeout = _env("PCIP_REQUEST_TIMEOUT")
    if timeout.isdigit():
        cfg.request_timeout = int(timeout)
    return cfg
