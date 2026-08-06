"""Social channel adapters.

One small adapter per channel behind a shared interface. Adapters publish
*exported deliverables* (files already cleared by the licensing policy) plus
platform-appropriate copy. Unconfigured channels fail with a clear message
instead of silently dropping content.

Supported out of the box:
- Buffer      — one token schedules to every profile connected in Buffer
                (Instagram, Facebook, LinkedIn, X, TikTok, YouTube Shorts).
- Meta Graph  — direct Facebook Page + Instagram Business publishing.
- LinkedIn    — organization page posts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from pcip.config import PCIPConfig
from pcip.models import Channel, Publication


class ChannelNotConfigured(Exception):
    pass


class SocialAdapter(ABC):
    channels: List[Channel] = []

    def __init__(self, config: PCIPConfig, session: Optional[requests.Session] = None) -> None:
        self.cfg = config
        self.http = session or requests.Session()

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def publish(
        self,
        channel: Channel,
        text: str,
        media_urls: Optional[List[str]] = None,
        schedule_at: str = "",
    ) -> Publication: ...

    def _check(self, resp: requests.Response, what: str) -> Dict[str, Any]:
        if resp.status_code >= 400:
            raise RuntimeError(f"{what} → {resp.status_code}: {resp.text[:300]}")
        return resp.json()


class BufferAdapter(SocialAdapter):
    """Scheduler-of-least-resistance: one token, every connected profile."""

    channels = [
        Channel.INSTAGRAM, Channel.FACEBOOK, Channel.LINKEDIN,
        Channel.X, Channel.TIKTOK, Channel.YOUTUBE,
    ]
    API = "https://api.bufferapp.com/1"

    def available(self) -> bool:
        return bool(self.cfg.buffer_token)

    def _profiles(self) -> List[Dict[str, Any]]:
        return self._check(
            self.http.get(
                f"{self.API}/profiles.json",
                params={"access_token": self.cfg.buffer_token},
                timeout=self.cfg.request_timeout,
            ),
            "buffer profiles",
        )

    def publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
        profiles = [
            p for p in self._profiles()
            if p.get("service", "").lower().startswith(channel.value[:6])
        ]
        if not profiles:
            raise ChannelNotConfigured(
                f"No Buffer profile connected for {channel.value}."
            )
        body: Dict[str, Any] = {
            "access_token": self.cfg.buffer_token,
            "profile_ids[]": [p["id"] for p in profiles],
            "text": text,
        }
        if media_urls:
            body["media[photo]"] = media_urls[0]
        if schedule_at:
            body["scheduled_at"] = schedule_at
        else:
            body["now"] = True
        data = self._check(
            self.http.post(
                f"{self.API}/updates/create.json",
                data=body,
                timeout=self.cfg.request_timeout,
            ),
            "buffer create",
        )
        update = (data.get("updates") or [{}])[0]
        return Publication(
            channel=channel,
            external_id=update.get("id", ""),
            status="scheduled" if schedule_at else "published",
            metadata={"buffer": True, "profiles": len(profiles)},
        )


class MetaAdapter(SocialAdapter):
    """Direct Facebook Page / Instagram Business publishing via Graph API."""

    channels = [Channel.FACEBOOK, Channel.INSTAGRAM]
    API = "https://graph.facebook.com/v21.0"

    def available(self) -> bool:
        return bool(self.cfg.meta_page_token)

    def publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
        token = self.cfg.meta_page_token
        if channel == Channel.INSTAGRAM:
            if not (self.cfg.meta_ig_user_id and media_urls):
                raise ChannelNotConfigured(
                    "Instagram needs META_IG_USER_ID and at least one media URL."
                )
            container = self._check(
                self.http.post(
                    f"{self.API}/{self.cfg.meta_ig_user_id}/media",
                    data={"image_url": media_urls[0], "caption": text,
                          "access_token": token},
                    timeout=self.cfg.request_timeout,
                ),
                "ig media container",
            )
            pub = self._check(
                self.http.post(
                    f"{self.API}/{self.cfg.meta_ig_user_id}/media_publish",
                    data={"creation_id": container["id"], "access_token": token},
                    timeout=self.cfg.request_timeout,
                ),
                "ig publish",
            )
            return Publication(channel=channel, external_id=pub.get("id", ""))
        # Facebook Page
        endpoint, body = "/me/feed", {"message": text, "access_token": token}
        if media_urls:
            endpoint, body = "/me/photos", {
                "url": media_urls[0], "caption": text, "access_token": token
            }
        pub = self._check(
            self.http.post(
                f"{self.API}{endpoint}", data=body, timeout=self.cfg.request_timeout
            ),
            "fb publish",
        )
        return Publication(channel=channel, external_id=str(pub.get("id", "")))


class LinkedInAdapter(SocialAdapter):
    channels = [Channel.LINKEDIN]
    API = "https://api.linkedin.com/v2"

    def available(self) -> bool:
        return bool(self.cfg.linkedin_token and self.cfg.linkedin_org_urn)

    def publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
        body = {
            "author": self.cfg.linkedin_org_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "ARTICLE" if media_urls else "NONE",
                    **(
                        {"media": [{"status": "READY", "originalUrl": media_urls[0]}]}
                        if media_urls else {}
                    ),
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        data = self._check(
            self.http.post(
                f"{self.API}/ugcPosts",
                json=body,
                headers={
                    "Authorization": f"Bearer {self.cfg.linkedin_token}",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                timeout=self.cfg.request_timeout,
            ),
            "linkedin publish",
        )
        return Publication(channel=channel, external_id=data.get("id", ""))


ADAPTERS = [BufferAdapter, MetaAdapter, LinkedInAdapter]


def adapter_for(channel: Channel, config: PCIPConfig) -> SocialAdapter:
    """First configured adapter that can serve the channel wins."""
    for cls in ADAPTERS:
        inst = cls(config)
        if channel in cls.channels and inst.available():
            return inst
    raise ChannelNotConfigured(
        f"No configured adapter for {channel.value}. Set BUFFER_TOKEN (easiest, "
        "covers all channels via Buffer), or META_PAGE_TOKEN / LINKEDIN_TOKEN."
    )
