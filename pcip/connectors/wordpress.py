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


class WordPressOriginError(WordPressError):
    """The request did not reach a WordPress REST API at all.

    Distinct from an auth or permission failure: the address is wrong, so no
    credential could have helped.
    """


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

    # ── A 404 that is not WordPress answering ────────────────────────────
    # WordPress's own 404 is JSON with a "rest_no_route" code. A 404 carrying
    # an empty or HTML body means the request never reached the REST API at
    # all — almost always because WORDPRESS_URL points at the reader-facing
    # site rather than the WordPress origin. On this deployment the public
    # site rewrites /wp-json/* to a blocked route, which produces exactly
    # this: 404, no body, no explanation.
    if status == 404 and "rest_no_route" not in body:
        detail = (body or "").strip()
        raise WordPressOriginError(
            f"{what}: HTTP 404 with "
            + ("an empty body" if not detail else f"a non-API body ({content_type or 'unknown type'})")
            + ". WordPress answers a missing route with JSON, so this request "
            "never reached the REST API.\n\n"
            "The usual cause is WORDPRESS_URL pointing at the public site "
            "instead of the WordPress origin. They are different hosts here: "
            "the public site rewrites /wp-json/* to a blocked route.\n\n"
            "Check it:\n"
            "  WORDPRESS_URL=https://wp.passqual.com    (the REST API — writes go here)\n"
            "  WORDPRESS_PUBLIC_SITE=https://passqual.com   (where readers land)\n\n"
            "Fix with:\n"
            "  bash scripts/pcip-set-key.sh WORDPRESS_URL"
        )

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
            # Some hosts (SiteGround among them) strip the standard
            # Authorization header before PHP sees it, so WordPress reports
            # rest_not_logged_in no matter how correct the credentials are.
            #
            # The remedies, in the order they should be tried:
            #   1. An .htaccess SetEnvIf rule on the site — configuration, not
            #      code, and trivially reversible.
            #   2. The WordPress.com / Jetpack route above
            #      (WORDPRESS_COM_TOKEN), which never traverses the host's
            #      Apache at all and so cannot be affected by this.
            #   3. Only then, this mirror header, paired with a must-use
            #      plugin that copies it back into place.
            #
            # (3) is off unless explicitly enabled. It is not free: a second
            # header carrying the credential widens where it can be logged,
            # and accepting a non-standard header as an auth source re-opens a
            # REST path the stripping was incidentally closing. It grants
            # nothing by itself — WordPress still validates what it receives —
            # but it is a change to the site's exposure and belongs to the
            # operator to choose.
            if config.wordpress_auth_mirror_header:
                import base64 as _b64

                token = _b64.b64encode(
                    f"{config.wordpress_user}:{config.wordpress_app_password}".encode()
                ).decode()
                self.http.headers["X-PCIP-Authorization"] = f"Basic {token}"
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

    def _publish_via_xmlrpc(
        self,
        title: str,
        content_html: str,
        *,
        status: str,
        excerpt: str,
        slug: str,
        language: str,
        scheduled_gmt: str,
        media_paths: Optional[List[str]],
        alt_texts: Optional[List[str]],
    ) -> Publication:
        """Publish over XML-RPC and return the same Publication shape as REST.

        Callers must not have to care which transport carried the article, so
        this records the identical metadata, derives the same reader-facing URL
        and fires the same revalidation. The only difference is ``transport``,
        recorded so the distribution record stays truthful about how it went.
        """
        from pcip.connectors.wordpress_xmlrpc import WordPressXMLRPC

        rpc = WordPressXMLRPC(self.cfg)
        if not rpc.available():
            raise WordPressAuthHeaderError(
                "WordPress REST cannot authenticate on this host (the "
                "Authorization header is stripped before PHP), and XML-RPC — "
                "which would not be affected, because it sends credentials in "
                "the request body — is not enabled or does not expose "
                "wp.newPost.\n\n"
                "Either enable XML-RPC on the site, or ask the host to pass "
                "the Authorization header through to PHP.\n"
                + AUTH_HEADER_FIX
            )

        media_ids: List[str] = []
        media_html: List[str] = []
        for i, path in enumerate(media_paths or []):
            alt = (alt_texts or [])[i] if alt_texts and i < len(alt_texts) else ""
            uploaded = rpc.upload_file(path)
            attachment_id = str(uploaded.get("id") or uploaded.get("attachment_id") or "")
            if attachment_id:
                media_ids.append(attachment_id)
                rpc.set_alt_text(attachment_id, alt)
            if i == 0:
                continue      # first becomes the featured image, as in REST
            src = html.escape(uploaded.get("url", ""), quote=True)
            media_html.append(
                f'<figure><img src="{src}" alt="{html.escape(alt, quote=True)}" /></figure>'
            )

        body_html = content_html + ("\n" + "\n".join(media_html) if media_html else "")
        post_id, link = rpc.new_post(
            title,
            body_html,
            excerpt=excerpt,
            slug=slug,
            status="future" if scheduled_gmt else status,
            date_iso=scheduled_gmt,
            thumbnail_id=media_ids[0] if media_ids else "",
        )

        wp_status = "future" if scheduled_gmt else status
        public_url = self.public_url_for(slug, language)
        meta: Dict[str, Any] = {
            "wp_status": wp_status,
            "wp_link": link,
            "media_ids": media_ids,
            "language": language,
            "transport": "xmlrpc",
            "transport_reason": (
                "REST unavailable: this host strips the Authorization header "
                "before PHP"
            ),
        }
        if wp_status == "publish":
            meta.update(self.revalidate(slug, language))

        return Publication(
            channel=self.channel,
            url=public_url,
            external_id=str(post_id),
            status="scheduled" if wp_status == "future" else "published",
            metadata=meta,
        )

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
        """Create a post, choosing a write path that works on this host.

        The fallback wraps the whole REST attempt, not just the post creation.
        Media is uploaded first, so on a host that strips the Authorization
        header the failure surfaces at the media endpoint — wrapping only the
        post call would mean any deliverable with an attachment never reached
        the fallback at all.
        """
        # Validate before any network call, so a bad timestamp never leaves a
        # half-uploaded media library behind.
        scheduled_gmt = _wp_datetime(schedule_at) if schedule_at else ""

        rest_kwargs = dict(
            status=status, media_paths=media_paths, alt_texts=alt_texts,
            categories=categories, tags=tags, excerpt=excerpt, slug=slug,
            language=language, scheduled_gmt=scheduled_gmt,
        )
        if self.cfg.wordpress_transport == "xmlrpc":
            return self._publish_via_xmlrpc(
                title, content_html, status=status, excerpt=excerpt, slug=slug,
                language=language, scheduled_gmt=scheduled_gmt,
                media_paths=media_paths, alt_texts=alt_texts,
            )
        try:
            return self._publish_via_rest(title, content_html, **rest_kwargs)
        except WordPressAuthHeaderError:
            # This host cannot authenticate REST at all. XML-RPC sends the
            # credentials in the request body and is unaffected. Fall back:
            # the caller asked for the article to be published, not for a
            # particular transport to be used.
            if self.cfg.wordpress_transport == "rest":
                raise
            return self._publish_via_xmlrpc(
                title, content_html, status=status, excerpt=excerpt, slug=slug,
                language=language, scheduled_gmt=scheduled_gmt,
                media_paths=media_paths, alt_texts=alt_texts,
            )

    def _publish_via_rest(
        self,
        title: str,
        content_html: str,
        *,
        status: str,
        media_paths: Optional[List[str]],
        alt_texts: Optional[List[str]],
        categories: Optional[List[int]],
        tags: Optional[List[int]],
        excerpt: str,
        slug: str,
        language: str,
        scheduled_gmt: str,
    ) -> Publication:
        """Create a post over the REST API, uploading media first."""

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
            "transport": "rest",
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
