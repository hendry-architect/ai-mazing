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

# pcip/config.py -> pcip/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent


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
    anthropic_model: str = "claude-opus-5"

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

    # ── WordPress (the API origin behind passqual.com) ───────────────────
    # passqual.com is a Next.js site on Vercel that fetches articles from
    # WordPress at request time (ISR, ~60s). So there are two hosts:
    #   wordpress_url         — where the REST API lives (writes go here)
    #   wordpress_public_site — where readers land (URLs recorded here)
    # The public site deliberately rewrites /wp-json/* to a blocked route,
    # so the API must be addressed at its own hostname.
    wordpress_url: str = "https://wp.passqual.com"
    wordpress_public_site: str = "https://passqual.com"
    wordpress_user: str = ""
    wordpress_app_password: str = ""
    wordpress_com_token: str = ""

    # Optional instant-publish path: the Next.js site exposes a revalidation
    # webhook that purges its ISR cache immediately instead of waiting out
    # the 60s window. Unset = publishes still appear, just within ~60s.
    vercel_revalidate_url: str = ""
    wp_revalidate_secret: str = ""

    # Last-resort workaround for hosts that strip the standard Authorization
    # header before PHP: mirror the credentials into a non-standard header.
    #
    # OFF by default, deliberately. Sending credentials in a second, custom
    # header widens where they can be logged or observed, and the server side
    # of it accepts a non-standard header as an authentication source — which
    # is exactly the shape a reviewer should challenge. Turn it on only after
    # the standard fix (an .htaccess SetEnvIf rule) has been tried and proven
    # insufficient, and only together with the companion must-use plugin,
    # which itself requires an explicit constant in wp-config.php.
    wordpress_auth_mirror_header: bool = False

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

    # ── Canva execution mode ─────────────────────────────────────────────
    # "mcp"     — assembly and export run through the Canva MCP connector
    #             (an agent session holds the credentials). Works with plain
    #             brand templates: no autofill dataset, no Enterprise plan.
    #             PCIP still owns the graph, licensing and every review gate;
    #             it pauses at a handoff and resumes once the design or the
    #             exported file is attached back to the run.
    # "connect" — direct Canva Connect API with brand-template autofill.
    #             Fully unattended, but requires templates that define autofill
    #             fields and the plan entitlement that exposes that API.
    canva_mode: str = "mcp"

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

    @property
    def anthropic_auth_source(self) -> str:
        """Which credential source the Anthropic SDK will actually use.

        An unset ANTHROPIC_API_KEY does not mean "no credentials" — the SDK
        resolves, in order: the API key, an auth token, a profile stored by
        `ant auth login`, then workload identity federation. PCIP reports the
        source rather than assuming a key, so `ant auth login` (no long-lived
        secret on disk) is a first-class way to run the platform.
        """
        if self.anthropic_api_key:
            return "api_key"
        if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return "auth_token"
        federation = (
            "ANTHROPIC_FEDERATION_RULE_ID",
            "ANTHROPIC_ORGANIZATION_ID",
            "ANTHROPIC_SERVICE_ACCOUNT_ID",
        )
        if all(os.environ.get(v) for v in federation) and (
            os.environ.get("ANTHROPIC_IDENTITY_TOKEN_FILE")
            or os.environ.get("ANTHROPIC_IDENTITY_TOKEN")
        ):
            return "workload_identity_federation"
        profiles = Path.home() / ".config" / "anthropic"
        if profiles.is_dir() and any(profiles.iterdir()):
            return "cli_profile"
        return ""

    @property
    def wordpress_configured(self) -> bool:
        """Single source of truth for 'can we talk to WordPress at all'.

        The publisher, ``channel_status`` and the doctor all ask this rather
        than each re-deriving the same predicate.
        """
        return bool(
            self.wordpress_com_token
            or (self.wordpress_user and self.wordpress_app_password)
        )

    @property
    def revalidation_configured(self) -> bool:
        """Whether the instant-publish webhook can be called."""
        return bool(self.vercel_revalidate_url and self.wp_revalidate_secret)

    def channel_status(self) -> Dict[str, bool]:
        """Which connectors are configured (no secrets exposed)."""
        return {
            "canva": bool(self.canva_access_token or self.canva_refresh_token),
            "anthropic": bool(self.anthropic_auth_source),
            "openai_images": bool(self.openai_api_key),
            "google_ai": bool(self.google_ai_api_key),
            "ideogram": bool(self.ideogram_api_key),
            "flux": bool(self.bfl_api_key),
            "runway": bool(self.runway_api_key),
            "pika": bool(self.pika_api_key and self.pika_endpoint),
            "luma": bool(self.luma_api_key),
            "wordpress": self.wordpress_configured,
            "wordpress_revalidate": self.revalidation_configured,
            "buffer": bool(self.buffer_token),
            "meta": bool(self.meta_page_token),
            "linkedin": bool(self.linkedin_token),
            "x": bool(self.x_user_token),
            "threads": bool(self.threads_token and self.threads_user_id),
            "youtube": bool(self.youtube_token),
            "tiktok": bool(self.tiktok_token),
        }


def load_dotenv(path: Optional[Path] = None, *, override: bool = False) -> Dict[str, str]:
    """Read a .env file into the process environment.

    PCIP is run from a terminal by one person, and every credential lives in a
    .env next to the repo. Requiring `set -a; source .env` before every command
    is a step that is easy to forget and produces a confusing "missing
    credentials" report rather than an obvious error, so the platform reads the
    file itself.

    Existing environment variables win by default: an explicitly exported value
    is a deliberate override for one command, and a file should not silently
    undo it. Nothing here is logged — the return value is the set of keys read,
    never the values.
    """
    candidates = [path] if path else [Path.cwd() / ".env", _REPO_ROOT / ".env"]
    loaded: Dict[str, str] = {}
    for candidate in candidates:
        if not candidate or not candidate.is_file():
            continue
        for raw in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, _, value = line.partition("=")
            key = key.strip()
            if not key.isidentifier():
                continue
            value = value.strip()
            # Strip one matching pair of surrounding quotes, and anything after
            # an unquoted ` #` — both are ordinary in a hand-edited .env.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            if override or key not in os.environ:
                os.environ[key] = value
            loaded[key] = ""          # keys only; values are never retained here
        break                          # first file found wins
    return loaded


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_config(data_dir: Optional[str] = None) -> PCIPConfig:
    """Build a PCIPConfig from PCIP_* / provider environment variables.

    A .env beside the repo (or in the working directory) is read first, so the
    platform behaves the same whether or not the caller remembered to export it.
    """
    load_dotenv()
    cfg = PCIPConfig(
        data_dir=Path(data_dir or _env("PCIP_DATA_DIR", DEFAULT_DATA_DIR)),
        canva_client_id=_env("CANVA_CLIENT_ID"),
        canva_client_secret=_env("CANVA_CLIENT_SECRET"),
        canva_access_token=_env("CANVA_ACCESS_TOKEN"),
        canva_refresh_token=_env("CANVA_REFRESH_TOKEN"),
        canva_api_base=_env("CANVA_API_BASE", "https://api.canva.com/rest/v1"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("PCIP_ANTHROPIC_MODEL", "claude-opus-5"),
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
        wordpress_url=_env("WORDPRESS_URL", "https://wp.passqual.com").rstrip("/"),
        wordpress_public_site=_env(
            "WORDPRESS_PUBLIC_SITE", "https://passqual.com"
        ).rstrip("/"),
        wordpress_user=_env("WORDPRESS_USER"),
        wordpress_app_password=_env("WORDPRESS_APP_PASSWORD"),
        wordpress_com_token=_env("WORDPRESS_COM_TOKEN"),
        vercel_revalidate_url=_env("VERCEL_REVALIDATE_URL"),
        wp_revalidate_secret=_env("WP_REVALIDATE_SECRET"),
        wordpress_auth_mirror_header=_env(
            "WORDPRESS_AUTH_MIRROR_HEADER", "0"
        ).lower() in ("1", "true", "yes"),
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
        canva_mode=(_env("PCIP_CANVA_MODE", "mcp").lower() or "mcp"),
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
