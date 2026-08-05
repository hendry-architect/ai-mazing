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

    # ── WordPress (passqual.com) ─────────────────────────────────────────
    # Self-hosted WP: site URL + application password (Users → Profile →
    # Application Passwords). WordPress.com: OAuth bearer token.
    wordpress_url: str = "https://passqual.com"
    wordpress_user: str = ""
    wordpress_app_password: str = ""
    wordpress_com_token: str = ""

    # ── Social channels (each optional; unconfigured = channel disabled) ─
    buffer_token: str = ""
    meta_page_token: str = ""          # Facebook Page / Instagram Business
    meta_ig_user_id: str = ""
    linkedin_token: str = ""
    linkedin_org_urn: str = ""

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
        """Which publishing channels are configured (no secrets exposed)."""
        return {
            "canva": bool(self.canva_access_token or self.canva_refresh_token),
            "anthropic": bool(self.anthropic_api_key),
            "wordpress": bool(
                self.wordpress_com_token
                or (self.wordpress_user and self.wordpress_app_password)
            ),
            "buffer": bool(self.buffer_token),
            "meta": bool(self.meta_page_token),
            "linkedin": bool(self.linkedin_token),
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
        wordpress_url=_env("WORDPRESS_URL", "https://passqual.com").rstrip("/"),
        wordpress_user=_env("WORDPRESS_USER"),
        wordpress_app_password=_env("WORDPRESS_APP_PASSWORD"),
        wordpress_com_token=_env("WORDPRESS_COM_TOKEN"),
        buffer_token=_env("BUFFER_TOKEN"),
        meta_page_token=_env("META_PAGE_TOKEN"),
        meta_ig_user_id=_env("META_IG_USER_ID"),
        linkedin_token=_env("LINKEDIN_TOKEN"),
        linkedin_org_urn=_env("LINKEDIN_ORG_URN"),
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
