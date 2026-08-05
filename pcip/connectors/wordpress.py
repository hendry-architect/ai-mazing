"""WordPress publisher for passqual.com.

Supports both self-hosted WordPress (REST API + Application Password) and
WordPress.com (OAuth bearer token). Uploads media, then creates the post as
a **draft by default** — going live is a deliberate act, not a side effect.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from pcip.config import PCIPConfig
from pcip.models import Channel, Publication


class WordPressError(Exception):
    pass


class WordPressPublisher:
    channel = Channel.WORDPRESS

    def __init__(self, config: PCIPConfig, session: Optional[requests.Session] = None) -> None:
        self.cfg = config
        self.http = session or requests.Session()
        if config.wordpress_com_token:
            # WordPress.com API v2 namespace per-site.
            site = config.wordpress_url.replace("https://", "").replace("http://", "")
            self.api_base = f"https://public-api.wordpress.com/wp/v2/sites/{site}"
            self.http.headers["Authorization"] = f"Bearer {config.wordpress_com_token}"
        elif config.wordpress_user and config.wordpress_app_password:
            self.api_base = f"{config.wordpress_url}/wp-json/wp/v2"
            self.http.auth = (config.wordpress_user, config.wordpress_app_password)
        else:
            raise WordPressError(
                "WordPress is not configured. Set WORDPRESS_COM_TOKEN, or "
                "WORDPRESS_USER + WORDPRESS_APP_PASSWORD (Users → Profile → "
                "Application Passwords), in your environment."
            )

    def _post(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        resp = self.http.post(
            f"{self.api_base}{path}", timeout=self.cfg.request_timeout, **kwargs
        )
        if resp.status_code >= 400:
            raise WordPressError(f"POST {path} → {resp.status_code}: {resp.text[:300]}")
        return resp.json()

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
    ) -> Publication:
        """Create a post; embeds uploaded media and sets the first as featured."""
        media_ids: List[int] = []
        media_html: List[str] = []
        for i, path in enumerate(media_paths or []):
            alt = (alt_texts or [])[i] if alt_texts and i < len(alt_texts) else ""
            media = self.upload_media(path, alt_text=alt)
            media_ids.append(media["id"])
            src = media.get("source_url", "")
            media_html.append(f'<figure><img src="{src}" alt="{alt}" /></figure>')

        body: Dict[str, Any] = {
            "title": title,
            "content": "\n".join(media_html) + "\n" + content_html,
            "status": status,
            "excerpt": excerpt,
        }
        if media_ids:
            body["featured_media"] = media_ids[0]
        if categories:
            body["categories"] = categories
        if tags:
            body["tags"] = tags

        post = self._post("/posts", json=body)
        return Publication(
            channel=self.channel,
            url=post.get("link", ""),
            external_id=str(post.get("id", "")),
            status="published" if status == "publish" else status,
            metadata={"wp_status": post.get("status"), "media_ids": media_ids},
        )
