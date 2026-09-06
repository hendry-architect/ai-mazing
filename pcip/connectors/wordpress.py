"""WordPress publisher — the API origin behind passqual.com.

passqual.com is a Next.js site on Vercel that fetches articles from WordPress
at **request time** under ISR (~60s). So publishing a post here is what makes
an article appear there; there is no deploy step. Two consequences shape this
module:

- **Two hostnames.** Writes go to ``cfg.wordpress_url`` (the WordPress REST
  origin, e.g. wp.passqual.com). Readers land on ``cfg.wordpress_public_site``
  (passqual.com) at a root-level slug. The public site deliberately blocks
  ``/wp-json/*``, so the API must be addressed at its own hostname, and the URL
  recorded in the knowledge graph must be the reader-facing one.
- **The origin can lie with a 2xx.** A SiteGround-hosted WordPress can answer
  with an anti-bot challenge: HTTP 202 + an ``sg-captcha`` header + an HTML
  body — a success status carrying a non-API payload. Every response therefore
  goes through :func:`classify_response`, which is pure and refuses anything
  that is not a usable JSON API response. Nothing here ever calls ``.json()``
  on an unvalidated body.

Posts are created as **drafts by default** — going live is a deliberate act,
and on this architecture "live" means live to patients within 60 seconds.
"""

from __future__ import annotations

import html
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from pcip.config import PCIPConfig
from pcip.models import Channel, Publication

# Response content types we accept as a real REST payload.
_JSON_CONTENT_TYPES = ("application/json", "application/vnd.api+json", "text/json")

# The .htaccess rule that restores the Authorization header on servers
# (SiteGround and other CGI/FastCGI setups) that strip it before PHP.
AUTH_HEADER_FIX = (
    'SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1\n'
    "  # or, inside <IfModule mod_rewrite.c>:\n"
    "  RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]"
)


def _wp_datetime(value: str) -> str:
    """Normalise a schedule timestamp to what WordPress expects (naive UTC ISO).

    Raises before any network call rather than letting WordPress silently
    publish immediately because it could not read the date.
    """
    from datetime import datetime, timezone

    raw = (value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WordPressError(
            f"--schedule-at {raw!r} is not a timestamp. Use ISO 8601, e.g. "
            "2026-12-01T09:00:00Z or 2026-12-01T09:00:00-05:00."
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.isoformat(timespec="seconds")


class WordPressError(Exception):
    """A WordPress REST call did not return a usable result."""


class WordPressNotConfigured(WordPressError):
    """No WordPress credentials are available."""


class WordPressChallengeError(WordPressError):
    """The host answered with an anti-bot challenge instead of the REST API."""


class WordPressAuthHeaderError(WordPressError):
    """WordPress saw no credentials — the Authorization header was stripped."""


class WordPressPermissionError(WordPressError):
    """Authenticated, but this user may not perform the operation."""


def classify_response(resp: Any, what: str = "request") -> Dict[str, Any]:
    """Validate a WordPress REST response and return its decoded JSON.

    Pure and dependency-free: ``resp`` only needs ``status_code``, ``headers``,
    ``text`` and ``json()``. Raises a specific ``WordPressError`` subclass for
    every failure mode this deployment actually exhibits, so callers never see
    a bare ``JSONDecodeError`` or an opaque 401.
    """
    status = getattr(resp, "status_code", 0)
    headers = {str(k).lower(): v for k, v in dict(getattr(resp, "headers", {}) or {}).items()}
    body = getattr(resp, "text", "") or ""
    content_type = str(headers.get("content-type", "")).lower()

    # ── Anti-bot challenge: a 2xx that is not the API ────────────────────
    # Mirrors the live site's own isUsable() check, which rejects on any of
    # three independent signals rather than requiring all of them.
    if "sg-captcha" in headers or (200 <= status < 300 and status == 202):
        raise WordPressChallengeError(
            f"{what}: the WordPress host returned an anti-bot challenge "
            f"(HTTP {status}"
            + (", sg-captcha header" if "sg-captcha" in headers else "")
            + f", content-type '{content_type or 'none'}'). This is SiteGround's "
            "bot protection, not WordPress. Allowlist the calling machine's IP "
            "in SiteGround Site Tools → Security → Blocked IPs / Bot protection, "
            "or run PCIP from an allowlisted host."
        )

    if status == 204:
        return {}

    # ── Authentication and permission ────────────────────────────────────
    if status in (401, 403):
        if "rest_not_logged_in" in body:
            raise WordPressAuthHeaderError(
                f"{what}: WordPress replied 'rest_not_logged_in' (HTTP {status}) — "
                "it received no credentials even though PCIP sent them. The web "
                "server is stripping the Authorization header before PHP sees it "
                "(common on SiteGround and other CGI/FastCGI setups).\n\n"
                "Fix, in the WordPress site's .htaccess:\n\n  "
                + AUTH_HEADER_FIX
                + "\n\nUntil that is applied, use `pcip prepare` to produce the "
                "article for manual pasting."
            )
        if "rest_cannot" in body or "rest_forbidden" in body:
            raise WordPressPermissionError(
                f"{what}: authenticated, but this WordPress user is not allowed to "
                f"perform it (HTTP {status}). Grant the account Author or Editor "
                f"rights, or use a different Application Password. Body: {body[:200]}"
            )
        raise WordPressAuthHeaderError(
            f"{what}: WordPress rejected the credentials (HTTP {status}). Check "
            f"WORDPRESS_USER and WORDPRESS_APP_PASSWORD (application passwords "
            f"contain spaces and must be copied whole). Body: {body[:200]}"
        )

    if status >= 400:
        raise WordPressError(f"{what}: HTTP {status}. Body: {body[:300]}")

    # ── 2xx: insist on an actual JSON payload ────────────────────────────
    if not any(ct in content_type for ct in _JSON_CONTENT_TYPES):
        raise WordPressChallengeError(
            f"{what}: HTTP {status} with content-type '{content_type or 'none'}' — "
            "the host returned a non-JSON body where the REST API was expected. "
            "This usually means a security/CDN interstitial, a redirect to a login "
            "page, or that WORDPRESS_URL points at the public site rather than the "
            f"WordPress origin. First bytes: {body[:120]!r}"
        )
    try:
        return resp.json()
    except Exception as exc:
        raise WordPressError(
            f"{what}: HTTP {status} claimed JSON but the body could not be decoded "
            f"({type(exc).__name__}). First bytes: {body[:120]!r}"
        ) from exc


class WordPressPublisher:
    channel = Channel.WORDPRESS

    def __init__(
        self,
        config: PCIPConfig,
        session: Optional[requests.Session] = None,
        revalidate_session: Optional[requests.Session] = None,
    ) -> None:
        self.cfg = config
        self.http = session or requests.Session()
        # Deliberately separate: self.http carries WordPress credentials, and the
        # revalidation webhook lives on a different host. Reusing that session
        # would send the WordPress application password to the site's CDN.
        self._revalidate_http = revalidate_session
        if config.wordpress_com_token:
            # WordPress.com API v2 namespace per-site — host only, no path.
            from urllib.parse import urlsplit

            site = urlsplit(config.wordpress_url).netloc or config.wordpress_url
            self.api_base = f"https://public-api.wordpress.com/wp/v2/sites/{site}"
            self.http.headers["Authorization"] = f"Bearer {config.wordpress_com_token}"
        elif config.wordpress_user and config.wordpress_app_password:
            self.api_base = f"{config.wordpress_url}/wp-json/wp/v2"
            self.http.auth = (config.wordpress_user, config.wordpress_app_password)
        else:
            raise WordPressNotConfigured(
                "WordPress is not configured. Set WORDPRESS_COM_TOKEN, or "
                "WORDPRESS_USER + WORDPRESS_APP_PASSWORD (Users → Profile → "
                "Application Passwords), in your environment. Point "
                "WORDPRESS_URL at the WordPress origin (e.g. "
                "https://wp.passqual.com), not the public site."
            )

    # ── Transport ────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        resp = self.http.request(
            method, f"{self.api_base}{path}", timeout=self.cfg.request_timeout, **kwargs
        )
        return classify_response(resp, f"{method} {path}")

    def _get(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        return self._request("POST", path, **kwargs)

    def can_write_posts(self) -> bool:
        """Whether this account may create posts — without creating one.

        An OPTIONS on the posts collection reports the methods WordPress will
        accept from the *current* user, so a read-only account is detected
        before anything is published.
        """
        data = self._request("OPTIONS", "/posts")
        methods = [str(m).upper() for m in (data.get("methods") or [])]
        if methods:
            return "POST" in methods
        for endpoint in data.get("endpoints") or []:
            if "POST" in [str(m).upper() for m in (endpoint.get("methods") or [])]:
                return True
        return False

    # ── Reader-facing URLs ───────────────────────────────────────────────

    def public_url_for(self, slug: str, language: str = "en") -> str:
        """The URL a reader visits, on the public site — not the WP link.

        Locale comes from the brief (PCIP already carries it) rather than from
        the REST payload, because whether the translation plugin exposes a
        language field over REST is deployment-specific; guessing wrong would
        record a 404 as the permanent distribution record.
        """
        slug = (slug or "").strip("/")
        if not slug:
            return ""
        base = self.cfg.wordpress_public_site.rstrip("/")
        if str(language or "").lower().startswith("es"):
            return f"{base}/es/{slug}/"
        return f"{base}/{slug}/"

    def revalidate(self, slug: str = "", language: str = "en") -> Dict[str, Any]:
        """Ask the public site to purge its cache now. Never raises.

        Without this the article still appears — the site revalidates on its
        own within ~60s — so a webhook failure must never fail a publish.
        """
        if not self.cfg.revalidation_configured:
            return {
                "revalidated": False,
                "reason": "revalidation webhook not configured "
                "(VERCEL_REVALIDATE_URL + WP_REVALIDATE_SECRET); the site will "
                "pick the article up on its own within ~60s",
            }
        # Never self.http — that session is authenticated to WordPress.
        http = self._revalidate_http or requests.Session()
        try:
            resp = http.post(
                self.cfg.vercel_revalidate_url,
                json={"slug": slug, "language": language,
                      "secret": self.cfg.wp_revalidate_secret},
                headers={"x-revalidate-secret": self.cfg.wp_revalidate_secret},
                timeout=self.cfg.request_timeout,
            )
            if resp.status_code >= 400:
                return {
                    "revalidated": False,
                    "reason": f"webhook returned HTTP {resp.status_code}"
                    + (" — WP_REVALIDATE_SECRET is probably not set on Vercel"
                       if resp.status_code == 503 else "")
                    + "; the site will still refresh within ~60s",
                }
            return {"revalidated": True, "reason": "cache purged immediately"}
        except Exception as exc:
            return {
                "revalidated": False,
                "reason": f"webhook call failed ({type(exc).__name__}: {exc}); "
                "the site will still refresh within ~60s",
            }

    # ── Publishing ───────────────────────────────────────────────────────

    def upload_media(self, file_path: str, alt_text: str = "") -> Dict[str, Any]:
        p = Path(file_path)
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        with open(p, "rb") as fh:
            media = self._post(
                "/media",
                data=fh.read(),
                headers={
                    "Content-Type": mime,
                    "Content-Disposition": f'attachment; filename="{p.name}"',
                },
            )
        if alt_text and media.get("id"):
            self._post(f"/media/{media['id']}", json={"alt_text": alt_text})
        return media

    def publish_post(
        self,
        title: str,
        content_html: str,
        *,
        status: str = "draft",
        media_paths: Optional[List[str]] = None,
        alt_texts: Optional[List[str]] = None,
        categories: Optional[List[int]] = None,
        tags: Optional[List[int]] = None,
        excerpt: str = "",
        slug: str = "",
        language: str = "en",
        schedule_at: str = "",
    ) -> Publication:
        """Create a post; embeds uploaded media and sets the first as featured."""
        # Validate before any network call, so a bad timestamp never leaves a
        # half-uploaded media library behind.
        scheduled_gmt = _wp_datetime(schedule_at) if schedule_at else ""

        media_ids: List[int] = []
        media_html: List[str] = []
        for i, path in enumerate(media_paths or []):
            alt = (alt_texts or [])[i] if alt_texts and i < len(alt_texts) else ""
            media = self.upload_media(path, alt_text=alt)
            media_ids.append(media["id"])
            if i == 0:
                # The first image becomes the featured image, which the site
                # renders on its own; repeating it in the body shows it twice.
                continue
            src = html.escape(media.get("source_url", ""), quote=True)
            media_html.append(
                f'<figure><img src="{src}" alt="{html.escape(alt, quote=True)}" /></figure>'
            )

        body: Dict[str, Any] = {
            "title": title,
            "content": content_html + ("\n" + "\n".join(media_html) if media_html else ""),
            "status": status,
            "excerpt": excerpt,
        }
        if scheduled_gmt:
            # WordPress schedules a post with status 'future' plus a future
            # date; setting only the date would silently publish immediately.
            body["date_gmt"] = scheduled_gmt
            body["status"] = "future"
        if slug:
            body["slug"] = slug
        if media_ids:
            body["featured_media"] = media_ids[0]
        if categories:
            body["categories"] = categories
        if tags:
            body["tags"] = tags

        post = self._post("/posts", json=body)
        wp_status = post.get("status", body["status"])
        public_url = self.public_url_for(post.get("slug", slug), language)

        meta: Dict[str, Any] = {
            "wp_status": wp_status,
            "wp_link": post.get("link", ""),
            "media_ids": media_ids,
            "language": language,
        }
        if wp_status == "publish":
            meta.update(self.revalidate(post.get("slug", slug), language))

        return Publication(
            channel=self.channel,
            # The reader-facing URL, not the WordPress link — this is the
            # permanent distribution record.
            url=public_url or post.get("link", ""),
            external_id=str(post.get("id", "")),
            status={"publish": "published", "future": "scheduled"}.get(
                wp_status, "draft"
            ),
            metadata=meta,
        )
