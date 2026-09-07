"""WordPress publishing over XML-RPC.

Why this exists: on hosts that strip the `Authorization` request header before
PHP (SiteGround among them), the REST API can never authenticate — WordPress
never receives the credential, so every write returns 401 `rest_not_logged_in`,
and no amount of `.htaccess` work fixes it because the header is gone before
Apache runs.

XML-RPC does not use that header. The username and password are parameters
*inside the request body*, so a proxy that drops request headers has nothing to
drop. It is WordPress core — no plugin to install, no server file to edit, no
configuration the account cannot reach.

The trade-offs, stated plainly:

- XML-RPC is a well-known brute-force target. That is an argument for keeping
  it disabled on sites that do not need it, not against using it where it is
  already enabled. PCIP checks it is enabled rather than enabling it.
- It carries credentials in the body rather than a header. Both are inside the
  same TLS session; neither is visible on the wire.
- Application Passwords authenticate here exactly as they do over REST, so the
  credential can still be scoped and revoked independently of the account
  password.

Marshalling uses the standard library's ``xmlrpc.client`` so the wire format is
correct, but transport goes through an injectable ``requests`` session — the
same seam the REST publisher uses, which keeps this testable with no network.
"""

from __future__ import annotations

import xmlrpc.client
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from pcip.config import PCIPConfig
from pcip.connectors.wordpress import WordPressError, WordPressNotConfigured


class XMLRPCUnavailable(WordPressError):
    """XML-RPC is not enabled, or does not expose the methods we need."""


class XMLRPCFault(WordPressError):
    """The server accepted the call and refused it."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


# Faults WordPress returns for a credential problem, mapped to a message that
# says what to do rather than repeating the server's wording.
_AUTH_FAULTS = {
    403: (
        "WordPress rejected the credentials over XML-RPC. Check WORDPRESS_USER "
        "is the login name (not the display name or email) and that "
        "WORDPRESS_APP_PASSWORD is an Application Password with its spaces "
        "kept exactly as WordPress generated it."
    ),
    405: (
        "XML-RPC is disabled on this site. Enable it, or ask the host to pass "
        "the Authorization header through to PHP so the REST API can be used "
        "instead."
    ),
}


class WordPressXMLRPC:
    """Minimal WordPress XML-RPC client: enough to publish an article."""

    def __init__(
        self,
        config: PCIPConfig,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not (config.wordpress_user and config.wordpress_app_password):
            raise WordPressNotConfigured(
                "XML-RPC publishing needs WORDPRESS_USER and "
                "WORDPRESS_APP_PASSWORD. The WordPress.com token route does "
                "not apply here — it uses its own API."
            )
        self.cfg = config
        self.http = session or requests.Session()
        self.endpoint = f"{config.wordpress_url}/xmlrpc.php"
        self.user = config.wordpress_user
        self.password = config.wordpress_app_password
        self.blog_id = 0

    # ── Transport ────────────────────────────────────────────────────────

    def _call(self, method: str, *params: Any) -> Any:
        body = xmlrpc.client.dumps(tuple(params), method, allow_none=True)
        resp = self.http.post(
            self.endpoint,
            data=body.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            timeout=self.cfg.request_timeout,
        )
        if resp.status_code == 405:
            raise XMLRPCUnavailable(_AUTH_FAULTS[405])
        if resp.status_code >= 400:
            raise WordPressError(
                f"XML-RPC {method} → HTTP {resp.status_code}: {resp.text[:300]}"
            )
        text = resp.text or ""
        if "<methodResponse" not in text:
            # An HTML body here is the host's error page or an anti-bot
            # challenge, not an XML-RPC reply.
            raise WordPressError(
                f"XML-RPC {method} did not return an XML-RPC response. The "
                f"server sent {resp.headers.get('content-type', 'an unknown type')}: "
                f"{text[:200]}"
            )
        try:
            values, _ = xmlrpc.client.loads(text)
        except xmlrpc.client.Fault as fault:
            message = _AUTH_FAULTS.get(fault.faultCode, fault.faultString)
            raise XMLRPCFault(
                f"{message} (XML-RPC fault {fault.faultCode})", fault.faultCode
            ) from fault
        except Exception as exc:
            raise WordPressError(
                f"Could not parse the XML-RPC response to {method}: {exc}"
            ) from exc
        return values[0] if values else None

    # ── Capability ───────────────────────────────────────────────────────

    def available(self) -> bool:
        """Whether this site can actually be published to over XML-RPC."""
        try:
            methods = self._call("system.listMethods")
        except WordPressError:
            return False
        return isinstance(methods, list) and "wp.newPost" in methods

    # ── Publishing ───────────────────────────────────────────────────────

    def new_post(
        self,
        title: str,
        content_html: str,
        *,
        excerpt: str = "",
        slug: str = "",
        status: str = "draft",
        date_iso: str = "",
        thumbnail_id: str = "",
    ) -> Tuple[str, str]:
        """Create a post. Returns (post_id, link)."""
        content: Dict[str, Any] = {
            "post_type": "post",
            "post_status": status,
            "post_title": title,
            "post_content": content_html,
        }
        if excerpt:
            content["post_excerpt"] = excerpt
        if slug:
            content["post_name"] = slug
        if thumbnail_id:
            content["post_thumbnail"] = int(thumbnail_id)
        if date_iso:
            # WordPress expects an ISO 8601 datetime; xmlrpc marshals it as
            # <dateTime.iso8601>, which is what wp.newPost wants for scheduling.
            content["post_date_gmt"] = xmlrpc.client.DateTime(
                date_iso.replace("+00:00", "").replace("Z", "")
            )

        post_id = self._call(
            "wp.newPost", self.blog_id, self.user, self.password, content
        )
        if not post_id:
            raise WordPressError("wp.newPost returned no post id.")
        post_id = str(post_id)
        return post_id, self.post_link(post_id)

    def post_link(self, post_id: str) -> str:
        """The permalink WordPress assigned, read back from the post."""
        try:
            post = self._call(
                "wp.getPost", self.blog_id, self.user, self.password,
                int(post_id), ["link"],
            )
        except WordPressError:
            return ""
        return (post or {}).get("link", "") if isinstance(post, dict) else ""

    def upload_file(self, path: str | Path, mime_type: str = "") -> Dict[str, Any]:
        """Upload one media file. Returns WordPress's {id, url, type, file}."""
        p = Path(path)
        data = p.read_bytes()
        if not mime_type:
            import mimetypes

            mime_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        result = self._call(
            "wp.uploadFile",
            self.blog_id,
            self.user,
            self.password,
            {
                "name": p.name,
                "type": mime_type,
                "bits": xmlrpc.client.Binary(data),
                "overwrite": False,
            },
        )
        if not isinstance(result, dict) or "url" not in result:
            raise WordPressError(f"wp.uploadFile returned an unexpected reply: {result!r}")
        return result

    def set_alt_text(self, attachment_id: str, alt: str) -> None:
        """Alt text is a post meta field, not part of the upload call."""
        if not alt:
            return
        try:
            self._call(
                "wp.editPost", self.blog_id, self.user, self.password,
                int(attachment_id),
                {"custom_fields": [{"key": "_wp_attachment_image_alt", "value": alt}]},
            )
        except WordPressError:
            # Alt text failing must not fail a publish that otherwise worked;
            # the caller records it and the operator can fix it in the editor.
            pass
