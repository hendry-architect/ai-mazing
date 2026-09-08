"""Social channel adapters — the hybrid publishing architecture.

Direct platform APIs are first-class (full native capability, no dependence
on a third-party scheduler's uptime or feature lag); Buffer is *one*
provider — the scheduling/queue specialist — not the only publishing path.
Every adapter declares a ``mode``:

    mode = "direct"     — native platform API (Meta, LinkedIn, X, Threads,
                          YouTube, TikTok)
    mode = "scheduler"  — queue/calendar orchestration (Buffer)

The publish router's decision engine picks the order: immediate posts
(healthcare alerts, physician announcements, time-sensitive campaigns)
prefer direct APIs; scheduled campaigns (podcasts, blogs, evergreen series)
prefer the scheduler — and either falls back to the other when its first
choice isn't configured. Unconfigured channels fail with a clear message
instead of silently dropping content.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from pcip.config import PCIPConfig
from pcip.models import Channel, Publication


class ChannelNotConfigured(Exception):
    pass


class ChannelError(RuntimeError):
    """A platform answered, but not with what it promised."""


class CaptionTooLong(ValueError):
    """The caption exceeds what the platform accepts.

    PCIP refuses rather than truncating. A post cut mid-sentence carries a
    physician's name and a clinic's phone number; publishing half a medical
    message is worse than publishing none, and the operator can always pass
    a channel-specific caption.
    """


#: Hard limits published by each platform, applied before anything is sent.
CAPTION_LIMITS: Dict[Channel, int] = {
    Channel.X: 280,
    Channel.THREADS: 500,
    Channel.INSTAGRAM: 2200,
    Channel.TIKTOK: 2200,
    Channel.LINKEDIN: 3000,
    Channel.YOUTUBE: 5000,          # description field
    Channel.FACEBOOK: 63206,
}


class SocialAdapter(ABC):
    channels: List[Channel] = []
    mode: str = "direct"               # "direct" | "scheduler"

    #: Config fields this adapter cannot work without. Declared rather than
    #: re-implemented per adapter so ``available()``, the doctor's capability
    #: report and the dry run's "not configured" list all read the same
    #: source — they used to be three separate hand-maintained lists.
    CREDENTIALS: tuple = ()

    def __init__(self, config: PCIPConfig, session: Optional[requests.Session] = None) -> None:
        self.cfg = config
        self.http = session or requests.Session()

    def available(self) -> bool:
        return all(getattr(self.cfg, f, "") for f in self.CREDENTIALS)

    def missing_credentials(self) -> List[str]:
        """Which of this adapter's credentials are unset, in env-var form."""
        return [f.upper() for f in self.CREDENTIALS if not getattr(self.cfg, f, "")]

    def publish(
        self,
        channel: Channel,
        text: str,
        media_urls: Optional[List[str]] = None,
        schedule_at: str = "",
    ) -> Publication:
        """Validate, then delegate to the adapter.

        Concrete here rather than on each adapter so no caller — router,
        script, or future adapter — can reach a platform without the caption
        having been checked first.
        """
        self._check_caption(channel, text)
        return self._publish(channel, text, media_urls, schedule_at)

    @abstractmethod
    def _publish(
        self,
        channel: Channel,
        text: str,
        media_urls: Optional[List[str]] = None,
        schedule_at: str = "",
    ) -> Publication: ...

    def _check_caption(self, channel: Channel, text: str) -> None:
        limit = CAPTION_LIMITS.get(channel)
        if limit is not None and len(text) > limit:
            raise CaptionTooLong(
                f"{channel.value} accepts {limit} characters; this caption is "
                f"{len(text)}. Give the channel its own caption instead of "
                f"letting it fall back to the article body:\n"
                f"  pcip publish <output> --channel {channel.value} "
                f"--text '<caption under {limit} chars>'"
            )

    def _check(self, resp: Any, what: str) -> Dict[str, Any]:
        """Turn a platform response into JSON, or into a useful error.

        ``resp.json()`` on its own is a trap shared by every social API: a
        gateway error page, a rate-limit notice or a login redirect all come
        back as HTML, and decoding one raises a bare JSONDecodeError with no
        indication of which channel failed or why.
        """
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "")
            raise ChannelError(
                f"{what} → rate limited by the platform"
                + (f"; retry after {retry}s" if retry else "")
            )
        if resp.status_code >= 400:
            raise ChannelError(f"{what} → {resp.status_code}: {resp.text[:300]}")
        ctype = resp.headers.get("content-type", "")
        try:
            return resp.json()
        except ValueError as exc:
            raise ChannelError(
                f"{what} → {resp.status_code} with a {ctype or 'non-JSON'} body, "
                f"not the JSON the API documents. First 200 characters: "
                f"{resp.text[:200]!r}"
            ) from exc


class BufferAdapter(SocialAdapter):
    """Buffer — the scheduling/queue specialist: one token covers every
    profile connected in Buffer. Great at queues, calendars, and retries;
    it is a *scheduler* provider, so the decision engine prefers it for
    scheduled campaigns and prefers direct APIs for immediate posts."""

    channels = [
        Channel.INSTAGRAM, Channel.FACEBOOK, Channel.LINKEDIN,
        Channel.X, Channel.TIKTOK, Channel.YOUTUBE,
    ]
    mode = "scheduler"
    API = "https://api.bufferapp.com/1"

    #: Buffer's own service names, which are not PCIP's channel names. The
    #: mismatch is not cosmetic: Buffer still calls X "twitter", so prefix
    #: matching on the channel value meant every X post through Buffer found
    #: no profile and failed.
    SERVICES = {
        Channel.INSTAGRAM: "instagram",
        Channel.FACEBOOK: "facebook",
        Channel.LINKEDIN: "linkedin",
        Channel.X: "twitter",
        Channel.TIKTOK: "tiktok",
        Channel.YOUTUBE: "youtube",
    }

    CREDENTIALS = ("buffer_token",)

    def _profiles(self) -> List[Dict[str, Any]]:
        return self._check(
            self.http.get(
                f"{self.API}/profiles.json",
                params={"access_token": self.cfg.buffer_token},
                timeout=self.cfg.request_timeout,
            ),
            "buffer profiles",
        )

    def _publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
        service = self.SERVICES.get(channel)
        if service is None:
            raise ChannelNotConfigured(f"Buffer does not serve {channel.value}.")
        profiles = [
            p for p in self._profiles()
            if p.get("service", "").lower() == service
        ]
        if not profiles:
            raise ChannelNotConfigured(
                f"No Buffer profile connected for {channel.value} (Buffer calls "
                f"it {service!r}). Connect it at https://publish.buffer.com."
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

    CREDENTIALS = ("meta_page_token",)

    def _publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
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

    CREDENTIALS = ("linkedin_token", "linkedin_org_urn")

    def _publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
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


class XAdapter(SocialAdapter):
    """X (Twitter) — native v2 API, OAuth2 user-context token."""

    channels = [Channel.X]
    API = "https://api.x.com/2"

    CREDENTIALS = ("x_user_token",)

    def _publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
        data = self._check(
            self.http.post(
                f"{self.API}/tweets",
                json={"text": text[:280]},
                headers={"Authorization": f"Bearer {self.cfg.x_user_token}"},
                timeout=self.cfg.request_timeout,
            ),
            "x publish",
        )
        return Publication(channel=channel,
                           external_id=data.get("data", {}).get("id", ""))


class ThreadsAdapter(SocialAdapter):
    """Threads — Meta's Threads API (container → publish, like Instagram)."""

    channels = [Channel.THREADS]
    API = "https://graph.threads.net/v1.0"

    CREDENTIALS = ("threads_token", "threads_user_id")

    def _publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
        body: Dict[str, Any] = {
            "media_type": "IMAGE" if media_urls else "TEXT",
            "text": text,
            "access_token": self.cfg.threads_token,
        }
        if media_urls:
            body["image_url"] = media_urls[0]
        container = self._check(
            self.http.post(
                f"{self.API}/{self.cfg.threads_user_id}/threads",
                data=body, timeout=self.cfg.request_timeout,
            ),
            "threads container",
        )
        pub = self._check(
            self.http.post(
                f"{self.API}/{self.cfg.threads_user_id}/threads_publish",
                data={"creation_id": container["id"],
                      "access_token": self.cfg.threads_token},
                timeout=self.cfg.request_timeout,
            ),
            "threads publish",
        )
        return Publication(channel=channel, external_id=pub.get("id", ""))


class YouTubeAdapter(SocialAdapter):
    """YouTube Data API v3 — video upload (Shorts included)."""

    channels = [Channel.YOUTUBE]
    API = "https://www.googleapis.com/upload/youtube/v3"

    CREDENTIALS = ("youtube_token",)

    def _publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
        local_path = None
        if media_urls and media_urls[0].startswith("/"):
            local_path = media_urls[0]
        if not local_path:
            raise ChannelNotConfigured(
                "YouTube upload needs a local video file path in media_urls[0]."
            )
        title, _, description = text.partition("\n")
        meta = {"snippet": {"title": title[:100], "description": description},
                "status": {"privacyStatus": "private" if schedule_at else "public",
                           **({"publishAt": schedule_at} if schedule_at else {})}}
        init = self.http.post(
            f"{self.API}/videos?uploadType=resumable&part=snippet,status",
            json=meta,
            headers={"Authorization": f"Bearer {self.cfg.youtube_token}"},
            timeout=self.cfg.request_timeout,
        )
        if init.status_code >= 400:
            raise ChannelError(f"youtube init → {init.status_code}: {init.text[:300]}")
        upload_url = init.headers.get("Location", "")
        if not upload_url:
            raise ChannelError(
                "youtube init → no Location header, so there is no resumable "
                "upload session to write the video to. This is what a revoked "
                "or insufficiently scoped OAuth token looks like; re-authorise "
                "with the youtube.upload scope."
            )
        with open(local_path, "rb") as fh:
            data = self._check(
                self.http.put(upload_url, data=fh,
                              headers={"Authorization": f"Bearer {self.cfg.youtube_token}"},
                              timeout=self.cfg.request_timeout * 10),
                "youtube upload",
            )
        return Publication(
            channel=channel, external_id=data.get("id", ""),
            url=f"https://youtu.be/{data.get('id', '')}",
            status="scheduled" if schedule_at else "published",
        )


class TikTokAdapter(SocialAdapter):
    """TikTok Content Posting API — direct video post from a public URL."""

    channels = [Channel.TIKTOK]
    API = "https://open.tiktokapis.com/v2"

    CREDENTIALS = ("tiktok_token",)

    def _publish(self, channel, text, media_urls=None, schedule_at="") -> Publication:
        if not media_urls:
            raise ChannelNotConfigured("TikTok needs a public video URL in media_urls[0].")
        data = self._check(
            self.http.post(
                f"{self.API}/post/publish/video/init/",
                json={
                    "post_info": {"title": text[:150], "privacy_level": "PUBLIC_TO_EVERYONE"},
                    "source_info": {"source": "PULL_FROM_URL",
                                    "video_url": media_urls[0]},
                },
                headers={"Authorization": f"Bearer {self.cfg.tiktok_token}"},
                timeout=self.cfg.request_timeout,
            ),
            "tiktok publish",
        )
        return Publication(
            channel=channel,
            external_id=data.get("data", {}).get("publish_id", ""),
        )


# Direct adapters first — the resolver reorders by mode preference, but this
# list order breaks ties inside the same mode.
ADAPTERS = [
    MetaAdapter, LinkedInAdapter, XAdapter, ThreadsAdapter,
    YouTubeAdapter, TikTokAdapter, BufferAdapter,
]


def adapters_for(
    channel: Channel,
    config: PCIPConfig,
    prefer: str = "direct",
    *,
    session: Optional[requests.Session] = None,
    require_available: bool = True,
) -> List[SocialAdapter]:
    """All configured adapters serving a channel, preferred mode first.

    ``prefer`` is the decision engine's knob: "direct" for immediate posts,
    "scheduler" for scheduled campaigns. The non-preferred mode stays in the
    list as the fallback, so a Buffer outage never strands an urgent post
    and a missing native token never blocks a scheduled one.

    ``session`` swaps the transport — used by tests and by ``--dry-run`` to
    run the real publishing code without reaching a platform.
    ``require_available`` may only be relaxed for a dry run, where the point
    is to show what an unconfigured channel *would* send.
    """
    instances = [cls(config, session) for cls in ADAPTERS if channel in cls.channels]
    candidates = [a for a in instances if a.available() or not require_available]
    return sorted(candidates, key=lambda a: a.mode != prefer)


def adapter_for(
    channel: Channel,
    config: PCIPConfig,
    prefer: str = "direct",
    *,
    session: Optional[requests.Session] = None,
    require_available: bool = True,
) -> SocialAdapter:
    """Best configured adapter for the channel (see adapters_for)."""
    candidates = adapters_for(
        channel, config, prefer,
        session=session, require_available=require_available,
    )
    if not candidates:
        raise ChannelNotConfigured(
            f"No configured adapter for {channel.value}. Configure the native "
            "token (META_PAGE_TOKEN / LINKEDIN_TOKEN / X_USER_TOKEN / "
            "THREADS_TOKEN / YOUTUBE_TOKEN / TIKTOK_TOKEN) and/or BUFFER_TOKEN "
            "for scheduling. See pcip/SETUP.md."
        )
    return candidates[0]
