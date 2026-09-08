"""Every social adapter, executed.

PCIP shipped seven social adapters and zero tokens, so none of this code had
ever run: a wrong field name, a stale API version or a mis-parsed response
would have surfaced at the moment a physician's campaign went out, not
before. These drive each adapter's real publish() against the recording
transport and assert on what would actually go over the wire.

The assertions are deliberately about *payload shape* — the endpoint, the
field names each platform documents, the value the adapter reads back out of
the response. A test that only checked "no exception" would pass on a
request no platform accepts.
"""

import pytest

from pcip.config import PCIPConfig
from pcip.connectors.dryrun import DryRunResponse, DryRunSession, dryrun_config
from pcip.connectors.social import (
    ADAPTERS,
    CAPTION_LIMITS,
    BufferAdapter,
    CaptionTooLong,
    ChannelError,
    ChannelNotConfigured,
    LinkedInAdapter,
    MetaAdapter,
    SocialAdapter,
    ThreadsAdapter,
    TikTokAdapter,
    XAdapter,
    YouTubeAdapter,
    adapter_for,
    adapters_for,
)
from pcip.models import Channel


def configured() -> PCIPConfig:
    """Every social credential present, so the adapters run their real path."""
    return PCIPConfig(
        buffer_token="buf_tok", meta_page_token="meta_tok",
        meta_ig_user_id="17841400000000000", linkedin_token="li_tok",
        linkedin_org_urn="urn:li:organization:1234", x_user_token="x_tok",
        threads_token="th_tok", threads_user_id="9876",
        youtube_token="yt_tok", tiktok_token="tt_tok",
    )


def run(adapter_cls, channel, text="Cuide su salud hoy.", **kwargs):
    session = DryRunSession()
    adapter = adapter_cls(configured(), session)
    pub = adapter.publish(channel, text, **kwargs)
    return pub, session.calls


# ── Buffer ───────────────────────────────────────────────────────────────


def test_buffer_posts_to_the_matching_profile():
    pub, calls = run(BufferAdapter, Channel.INSTAGRAM,
                     media_urls=["https://cdn.example/hero.png"])
    profiles, create = calls
    assert profiles["url"].endswith("/profiles.json")
    assert create["url"].endswith("/updates/create.json")
    assert create["data"]["profile_ids[]"] == ["dryrun_profile_instagram"]
    assert create["data"]["media[photo]"] == "https://cdn.example/hero.png"
    assert create["data"]["now"] is True
    assert pub.status == "published"
    assert pub.external_id.startswith("dryrun_buffer_")


def test_buffer_knows_x_is_still_called_twitter():
    """Buffer never renamed the service. Prefix-matching the channel value
    meant every X post found no profile and failed."""
    _, calls = run(BufferAdapter, Channel.X)
    assert calls[1]["data"]["profile_ids[]"] == ["dryrun_profile_twitter"]


def test_buffer_schedules_instead_of_posting_now():
    _, calls = run(BufferAdapter, Channel.FACEBOOK,
                   schedule_at="2026-01-05T14:00:00Z")
    body = calls[1]["data"]
    assert body["scheduled_at"] == "2026-01-05T14:00:00Z"
    assert "now" not in body


def test_buffer_refuses_a_channel_with_no_connected_profile():
    class NoProfiles(DryRunSession):
        def _reply(self, method, url):
            if "profiles" in url:
                return DryRunResponse([])
            return super()._reply(method, url)

    adapter = BufferAdapter(configured(), NoProfiles())
    with pytest.raises(ChannelNotConfigured, match="twitter"):
        adapter.publish(Channel.X, "hola")


def test_buffer_never_puts_the_token_in_a_recorded_request():
    _, calls = run(BufferAdapter, Channel.LINKEDIN)
    for call in calls:
        assert "buf_tok" not in repr(call)


# ── Meta: Facebook and Instagram ─────────────────────────────────────────


def test_instagram_creates_a_container_then_publishes_it():
    pub, calls = run(MetaAdapter, Channel.INSTAGRAM,
                     media_urls=["https://cdn.example/hero.png"])
    container, publish = calls
    assert container["url"].endswith("/17841400000000000/media")
    assert container["data"]["image_url"] == "https://cdn.example/hero.png"
    assert container["data"]["caption"] == "Cuide su salud hoy."
    assert publish["url"].endswith("/17841400000000000/media_publish")
    assert publish["data"]["creation_id"] == "dryrun_meta_1"
    assert pub.external_id == "dryrun_meta_2"


def test_instagram_refuses_without_an_image():
    """Instagram has no text-only post; sending one would 400 at Meta."""
    with pytest.raises(ChannelNotConfigured, match="media URL"):
        run(MetaAdapter, Channel.INSTAGRAM)


def test_facebook_text_post_goes_to_the_feed():
    pub, calls = run(MetaAdapter, Channel.FACEBOOK)
    assert calls[0]["url"].endswith("/me/feed")
    assert calls[0]["data"]["message"] == "Cuide su salud hoy."
    assert pub.external_id == "dryrun_meta_1"


def test_facebook_with_an_image_goes_to_photos():
    _, calls = run(MetaAdapter, Channel.FACEBOOK,
                   media_urls=["https://cdn.example/hero.png"])
    assert calls[0]["url"].endswith("/me/photos")
    assert calls[0]["data"]["caption"] == "Cuide su salud hoy."
    assert "message" not in calls[0]["data"]


# ── LinkedIn ─────────────────────────────────────────────────────────────


def test_linkedin_posts_as_the_organisation():
    pub, calls = run(LinkedInAdapter, Channel.LINKEDIN)
    body = calls[0]["json"]
    assert calls[0]["url"].endswith("/ugcPosts")
    assert body["author"] == "urn:li:organization:1234"
    assert body["lifecycleState"] == "PUBLISHED"
    share = body["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert share["shareCommentary"]["text"] == "Cuide su salud hoy."
    assert share["shareMediaCategory"] == "NONE"
    assert calls[0]["headers"]["X-Restli-Protocol-Version"] == "2.0.0"
    assert pub.external_id.startswith("urn:li:share:")


def test_linkedin_authorization_header_is_redacted_in_the_record():
    _, calls = run(LinkedInAdapter, Channel.LINKEDIN)
    assert "li_tok" not in repr(calls)


# ── X ────────────────────────────────────────────────────────────────────


def test_x_posts_a_tweet():
    pub, calls = run(XAdapter, Channel.X)
    assert calls[0]["url"].endswith("/2/tweets")
    assert calls[0]["json"] == {"text": "Cuide su salud hoy."}
    assert pub.external_id.startswith("dryrun_tweet_")


def test_x_refuses_an_over_long_caption_instead_of_truncating():
    """Truncation used to be silent. Half a medical message, signed by a
    physician, is worse than no message."""
    with pytest.raises(CaptionTooLong, match="280"):
        run(XAdapter, Channel.X, text="a" * 281)


# ── Threads ──────────────────────────────────────────────────────────────


def test_threads_text_post():
    pub, calls = run(ThreadsAdapter, Channel.THREADS)
    container, publish = calls
    assert container["data"]["media_type"] == "TEXT"
    assert publish["url"].endswith("/9876/threads_publish")
    assert publish["data"]["creation_id"] == "dryrun_meta_1"
    assert pub.external_id == "dryrun_meta_2"


def test_threads_image_post_declares_its_media_type():
    _, calls = run(ThreadsAdapter, Channel.THREADS,
                   media_urls=["https://cdn.example/hero.png"])
    assert calls[0]["data"]["media_type"] == "IMAGE"
    assert calls[0]["data"]["image_url"] == "https://cdn.example/hero.png"


# ── YouTube ──────────────────────────────────────────────────────────────


def test_youtube_uploads_a_local_file_in_two_steps(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftyp")
    pub, calls = run(YouTubeAdapter, Channel.YOUTUBE,
                     text="Diabetes en 60 segundos\nTres hábitos.",
                     media_urls=[str(video)])
    init, upload = calls
    assert "uploadType=resumable" in init["url"]
    assert init["json"]["snippet"]["title"] == "Diabetes en 60 segundos"
    assert init["json"]["snippet"]["description"] == "Tres hábitos."
    assert init["json"]["status"]["privacyStatus"] == "public"
    assert upload["method"] == "PUT"
    assert upload["data"] == "<file stream>"
    assert pub.url == "https://youtu.be/dryrun_video_2"


def test_youtube_schedules_as_private_until_publish_time(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00")
    pub, calls = run(YouTubeAdapter, Channel.YOUTUBE, text="T\nD",
                     media_urls=[str(video)], schedule_at="2026-02-01T09:00:00Z")
    status = calls[0]["json"]["status"]
    assert status["privacyStatus"] == "private"
    assert status["publishAt"] == "2026-02-01T09:00:00Z"
    assert pub.status == "scheduled"


def test_youtube_needs_a_local_path_not_a_url():
    with pytest.raises(ChannelNotConfigured, match="local video file"):
        run(YouTubeAdapter, Channel.YOUTUBE, text="T\nD",
            media_urls=["https://cdn.example/clip.mp4"])


def test_youtube_missing_upload_session_is_explained(tmp_path):
    """A revoked token answers 200 with no Location. That used to be a
    KeyError with nothing to act on."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00")

    class NoLocation(DryRunSession):
        def _reply(self, method, url):
            if "googleapis.com" in url and method == "POST":
                return DryRunResponse({})
            return super()._reply(method, url)

    adapter = YouTubeAdapter(configured(), NoLocation())
    with pytest.raises(ChannelError, match="scope"):
        adapter.publish(Channel.YOUTUBE, "T\nD", media_urls=[str(video)])


# ── TikTok ───────────────────────────────────────────────────────────────


def test_tiktok_pulls_the_video_from_a_url():
    pub, calls = run(TikTokAdapter, Channel.TIKTOK,
                     media_urls=["https://cdn.example/clip.mp4"])
    body = calls[0]["json"]
    assert body["source_info"]["source"] == "PULL_FROM_URL"
    assert body["source_info"]["video_url"] == "https://cdn.example/clip.mp4"
    assert body["post_info"]["privacy_level"] == "PUBLIC_TO_EVERYONE"
    assert pub.external_id.startswith("dryrun_tiktok_")


def test_tiktok_refuses_without_a_video():
    with pytest.raises(ChannelNotConfigured, match="video URL"):
        run(TikTokAdapter, Channel.TIKTOK)


# ── Shared behaviour across every adapter ────────────────────────────────


@pytest.mark.parametrize("cls", ADAPTERS)
def test_adapter_is_unavailable_without_credentials(cls):
    assert cls(PCIPConfig()).available() is False


@pytest.mark.parametrize("cls", ADAPTERS)
def test_adapter_is_available_when_fully_configured(cls):
    assert cls(configured()).available() is True


@pytest.mark.parametrize("cls", ADAPTERS)
def test_every_declared_channel_actually_publishes(cls, tmp_path):
    """The channel list is a promise. An adapter that claims a channel it
    cannot serve routes real content into a dead end."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00")
    for channel in cls.channels:
        media = [str(video)] if cls is YouTubeAdapter else [
            "https://cdn.example/hero.png"
        ]
        pub, calls = run(cls, channel, text="Salud", media_urls=media)
        assert calls, f"{cls.__name__}/{channel.value} sent nothing"
        assert pub.channel == channel
        assert pub.external_id, f"{cls.__name__}/{channel.value} recorded no id"


@pytest.mark.parametrize("cls", ADAPTERS)
def test_html_bodies_are_rejected_by_length_before_reaching_a_platform(cls):
    """Every channel with a limit enforces it in the base class, so no
    adapter can be added that forgets to."""
    for channel in cls.channels:
        limit = CAPTION_LIMITS[channel]
        with pytest.raises(CaptionTooLong):
            cls(configured(), DryRunSession()).publish(channel, "x" * (limit + 1))


@pytest.mark.parametrize("cls", ADAPTERS)
def test_non_json_response_names_the_channel_instead_of_raising_json_error(cls):
    """A gateway error page is HTML. Decoding it blind raised a bare
    JSONDecodeError that said nothing about which channel had failed."""
    class Html:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html><body>502 Bad Gateway</body></html>"

        def json(self):
            raise ValueError("Expecting value: line 1 column 1")

    with pytest.raises(ChannelError, match="text/html"):
        cls(configured())._check(Html(), f"{cls.__name__} publish")


@pytest.mark.parametrize("cls", ADAPTERS)
def test_rate_limit_is_reported_as_a_rate_limit(cls):
    class Limited:
        status_code = 429
        headers = {"Retry-After": "900"}
        text = "rate limit exceeded"

        def json(self):
            return {}

    with pytest.raises(ChannelError, match="rate limited"):
        cls(configured())._check(Limited(), "publish")


def test_publish_cannot_be_reached_without_caption_validation():
    """Validation lives on the base class precisely so a new adapter cannot
    opt out of it by overriding publish()."""
    assert "_publish" in SocialAdapter.__abstractmethods__
    for cls in ADAPTERS:
        assert cls.publish is SocialAdapter.publish, (
            f"{cls.__name__} overrides publish() and skips caption checks"
        )


# ── Routing ──────────────────────────────────────────────────────────────


def test_immediate_posts_prefer_the_direct_api():
    order = [type(a).__name__ for a in adapters_for(
        Channel.INSTAGRAM, configured(), prefer="direct")]
    assert order[0] == "MetaAdapter"
    assert "BufferAdapter" in order, "the scheduler must remain as fallback"


def test_scheduled_campaigns_prefer_the_scheduler():
    order = [type(a).__name__ for a in adapters_for(
        Channel.INSTAGRAM, configured(), prefer="scheduler")]
    assert order[0] == "BufferAdapter"


def test_unconfigured_channel_names_the_variables_to_set():
    with pytest.raises(ChannelNotConfigured, match="META_PAGE_TOKEN"):
        adapter_for(Channel.FACEBOOK, PCIPConfig())


def test_dry_run_selection_ignores_availability_but_nothing_else_does():
    """The availability bypass exists for previews only."""
    adapter = adapter_for(Channel.FACEBOOK, PCIPConfig(),
                          session=DryRunSession(), require_available=False)
    assert isinstance(adapter, MetaAdapter)
    with pytest.raises(ChannelNotConfigured):
        adapter_for(Channel.FACEBOOK, PCIPConfig())


def test_dryrun_config_marks_missing_credentials_without_inventing_them():
    cfg, missing = dryrun_config(PCIPConfig(meta_page_token="real"))
    assert "meta_page_token" not in missing
    assert cfg.meta_page_token == "real"
    assert "x_user_token" in missing
    assert cfg.x_user_token == "<X_USER_TOKEN not set>"


def test_dry_run_transport_refuses_an_endpoint_it_has_never_seen():
    """A catch-all success would let an adapter aimed at the wrong host pass
    a dry run and fail in production."""
    with pytest.raises(AssertionError, match="no canned response"):
        DryRunSession().post("https://api.example.invalid/v1/posts", json={})


# ── The three lists that must not drift apart ────────────────────────────

#: config.channel_status() key for each adapter, so the two can be compared.
_STATUS_KEY = {
    "BufferAdapter": "buffer", "MetaAdapter": "meta",
    "LinkedInAdapter": "linkedin", "XAdapter": "x",
    "ThreadsAdapter": "threads", "YouTubeAdapter": "youtube",
    "TikTokAdapter": "tiktok",
}


@pytest.mark.parametrize("cls", ADAPTERS)
def test_availability_agrees_with_the_status_the_doctor_reports(cls):
    """``pcip doctor`` reads config.channel_status(); the router reads
    available(). When those disagree the doctor says a channel is ready and
    the publish fails, or the reverse — both erode the report the operator
    is meant to trust."""
    key = _STATUS_KEY[cls.__name__]
    assert cls(PCIPConfig()).available() is PCIPConfig().channel_status()[key]
    assert cls(configured()).available() is configured().channel_status()[key]


@pytest.mark.parametrize("cls", ADAPTERS)
def test_credentials_are_real_config_fields(cls):
    """A typo here disables a channel silently: getattr(cfg, "buffer_tokn",
    "") is falsy, so the adapter simply never becomes available."""
    cfg = PCIPConfig()
    assert cls.CREDENTIALS, f"{cls.__name__} declares no credentials"
    for field in cls.CREDENTIALS:
        assert hasattr(cfg, field), f"{cls.__name__}: no config field {field!r}"


@pytest.mark.parametrize("cls", ADAPTERS)
def test_missing_credentials_names_the_environment_variables(cls):
    assert cls(PCIPConfig()).missing_credentials() == [
        f.upper() for f in cls.CREDENTIALS
    ]
    assert cls(configured()).missing_credentials() == []
