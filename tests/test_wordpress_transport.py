"""WordPress transport tests — the origin is allowed to lie, and we must not
believe it. Fully offline: `classify_response` is pure, and the publisher takes
an injectable session.
"""

import pytest

from pcip.config import PCIPConfig
from pcip.connectors.wordpress import (
    WordPressAuthHeaderError,
    WordPressChallengeError,
    WordPressError,
    WordPressNotConfigured,
    WordPressPermissionError,
    WordPressPublisher,
    classify_response,
)

JSON_CT = {"Content-Type": "application/json; charset=UTF-8"}


class Resp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, status=200, headers=None, text="", payload=None, bad_json=False):
        self.status_code = status
        self.headers = headers if headers is not None else dict(JSON_CT)
        self.text = text
        self._payload = payload if payload is not None else {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class FakeSession:
    """Programmable session: handler(method, url, kwargs) -> Resp."""

    def __init__(self, handler):
        self.handler = handler
        self.headers = {}
        self.auth = None
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def cfg(**kwargs):
    base = dict(wordpress_user="editor", wordpress_app_password="abcd efgh ijkl")
    base.update(kwargs)
    return PCIPConfig(**base)


# ─── The SiteGround anti-bot challenge: a 2xx that is not the API ────────────


def test_captcha_header_is_a_challenge_not_a_success():
    resp = Resp(status=200, headers={"sg-captcha": "1", "Content-Type": "text/html"},
                text="<html>checking your browser</html>")
    with pytest.raises(WordPressChallengeError) as exc:
        classify_response(resp, "GET /posts")
    assert "anti-bot" in str(exc.value).lower()
    assert "siteground" in str(exc.value).lower()


def test_202_is_treated_as_a_challenge():
    resp = Resp(status=202, headers={"Content-Type": "text/html"}, text="<html></html>")
    with pytest.raises(WordPressChallengeError):
        classify_response(resp)


def test_200_with_html_body_is_rejected_not_decoded():
    """The failure mode that used to surface as a raw JSONDecodeError."""
    resp = Resp(status=200, headers={"Content-Type": "text/html"},
                text="<!doctype html><title>Login</title>")
    with pytest.raises(WordPressChallengeError) as exc:
        classify_response(resp)
    assert "non-JSON" in str(exc.value)


def test_json_claimed_but_undecodable_is_a_named_error():
    resp = Resp(status=200, text="not json at all", bad_json=True)
    with pytest.raises(WordPressError) as exc:
        classify_response(resp)
    assert "could not be decoded" in str(exc.value)
    assert not isinstance(exc.value, WordPressChallengeError)


# ─── Authentication ─────────────────────────────────────────────────────────


def test_rest_not_logged_in_names_the_header_stripping_fix():
    resp = Resp(status=401, text='{"code":"rest_not_logged_in","message":"..."}')
    with pytest.raises(WordPressAuthHeaderError) as exc:
        classify_response(resp, "POST /posts")
    message = str(exc.value)
    assert "Authorization header" in message
    assert "HTTP_AUTHORIZATION" in message      # the actual .htaccess fix
    assert "pcip prepare" in message            # the interim path


def test_permission_error_is_distinct_from_auth_failure():
    resp = Resp(status=403, text='{"code":"rest_cannot_create","message":"..."}')
    with pytest.raises(WordPressPermissionError):
        classify_response(resp)


def test_plain_401_still_gives_actionable_guidance():
    resp = Resp(status=401, text='{"code":"incorrect_password"}')
    with pytest.raises(WordPressAuthHeaderError) as exc:
        classify_response(resp)
    assert "application passwords contain spaces" in str(exc.value).lower()


# ─── Ordinary outcomes ──────────────────────────────────────────────────────


def test_success_returns_payload():
    assert classify_response(Resp(payload={"id": 7})) == {"id": 7}


def test_204_is_empty_not_an_error():
    assert classify_response(Resp(status=204, headers={}, text="")) == {}


def test_server_error_reports_status_and_body():
    with pytest.raises(WordPressError) as exc:
        classify_response(Resp(status=500, text="upstream exploded"))
    assert "500" in str(exc.value)


# ─── Reader-facing URLs ─────────────────────────────────────────────────────


def test_public_url_uses_the_reader_site_not_the_api_origin():
    wp = WordPressPublisher(cfg(), session=FakeSession(lambda *a: Resp()))
    assert wp.public_url_for("diabetes-at-home") == "https://passqual.com/diabetes-at-home/"
    # The API origin must never leak into a reader-facing URL.
    assert "wp.passqual.com" not in wp.public_url_for("diabetes-at-home")


def test_public_url_spanish_gets_the_locale_prefix():
    wp = WordPressPublisher(cfg(), session=FakeSession(lambda *a: Resp()))
    assert wp.public_url_for("diabetes-en-casa", "es") == "https://passqual.com/es/diabetes-en-casa/"
    assert wp.public_url_for("x", "bilingual") == "https://passqual.com/x/"


def test_public_url_is_empty_without_a_slug():
    wp = WordPressPublisher(cfg(), session=FakeSession(lambda *a: Resp()))
    assert wp.public_url_for("") == ""
    assert wp.public_url_for("/leading-and-trailing/") == "https://passqual.com/leading-and-trailing/"


def test_custom_public_site_is_respected():
    wp = WordPressPublisher(
        cfg(wordpress_public_site="https://example.org/"),
        session=FakeSession(lambda *a: Resp()),
    )
    assert wp.public_url_for("post") == "https://example.org/post/"


# ─── Revalidation is best-effort and must never break a publish ─────────────


def test_revalidate_reports_when_not_configured():
    wp = WordPressPublisher(cfg(), session=FakeSession(lambda *a: Resp()))
    result = wp.revalidate("slug")
    assert result["revalidated"] is False
    assert "60s" in result["reason"]


def _revalidating(handler):
    """A publisher whose revalidation webhook is configured and stubbed."""
    return WordPressPublisher(
        cfg(vercel_revalidate_url="https://passqual.com/api/revalidate",
            wp_revalidate_secret="s3cret"),
        session=FakeSession(lambda m, u, k: Resp(payload={"id": 1, "slug": "s",
                                                          "status": "publish"})),
        revalidate_session=FakeSession(handler),
    )


def test_revalidate_succeeds_when_configured():
    assert _revalidating(lambda m, u, k: Resp(status=200)).revalidate("slug")[
        "revalidated"
    ] is True


def test_revalidate_503_explains_the_missing_vercel_secret():
    result = _revalidating(lambda m, u, k: Resp(status=503)).revalidate("slug")
    assert result["revalidated"] is False
    assert "Vercel" in result["reason"]


def test_revalidate_never_raises():
    def boom(*args):
        raise ConnectionError("network down")

    result = _revalidating(boom).revalidate("slug")   # must not propagate
    assert result["revalidated"] is False
    assert "ConnectionError" in result["reason"]


def test_revalidate_never_carries_the_wordpress_credentials():
    """The webhook lives on another host; the WP session must not be reused."""
    wp_session = FakeSession(lambda m, u, k: Resp(payload={"id": 1, "slug": "s",
                                                           "status": "publish"}))
    hook_session = FakeSession(lambda m, u, k: Resp(status=200))
    wp = WordPressPublisher(
        cfg(vercel_revalidate_url="https://passqual.com/api/revalidate",
            wp_revalidate_secret="s3cret"),
        session=wp_session,
        revalidate_session=hook_session,
    )
    wp.publish_post("T", "<p>b</p>", status="publish")

    assert hook_session.calls, "the webhook should have been called"
    # The WordPress application password must never reach the webhook host.
    assert hook_session.auth is None
    assert "Authorization" not in hook_session.headers
    for _method, url, _kwargs in hook_session.calls:
        assert "wp-json" not in url
    # And the WordPress session was never used to talk to the webhook.
    for _method, url, _kwargs in wp_session.calls:
        assert "api/revalidate" not in url


# ─── Write capability, without writing ──────────────────────────────────────


def test_can_write_posts_reads_allowed_methods():
    yes = FakeSession(lambda m, u, k: Resp(payload={"methods": ["GET", "POST"]}))
    no = FakeSession(lambda m, u, k: Resp(payload={"methods": ["GET"]}))
    assert WordPressPublisher(cfg(), session=yes).can_write_posts() is True
    assert WordPressPublisher(cfg(), session=no).can_write_posts() is False


def test_can_write_posts_falls_back_to_endpoints():
    session = FakeSession(
        lambda m, u, k: Resp(payload={"endpoints": [{"methods": ["GET"]},
                                                    {"methods": ["POST"]}]})
    )
    assert WordPressPublisher(cfg(), session=session).can_write_posts() is True


# ─── Publishing ─────────────────────────────────────────────────────────────


def _post_handler(**post_fields):
    def handler(method, url, kwargs):
        if url.endswith("/posts"):
            body = kwargs.get("json") or {}
            return Resp(payload={"id": 42, "slug": "an-article",
                                 "link": "https://wp.passqual.com/an-article/",
                                 "status": body.get("status", "draft"),
                                 **post_fields})
        return Resp(status=200)
    return handler


def test_publish_records_the_reader_url_and_keeps_the_wp_link():
    wp = WordPressPublisher(cfg(), session=FakeSession(_post_handler()))
    pub = wp.publish_post("Title", "<p>body</p>", status="publish")
    assert pub.url == "https://passqual.com/an-article/"
    assert pub.metadata["wp_link"] == "https://wp.passqual.com/an-article/"
    assert pub.status == "published"


def test_draft_publish_does_not_revalidate():
    wp = WordPressPublisher(cfg(), session=FakeSession(_post_handler()))
    pub = wp.publish_post("Title", "<p>body</p>", status="draft")
    assert pub.status == "draft"
    assert "revalidated" not in pub.metadata   # nothing to purge for a draft


def test_schedule_at_produces_a_future_post_not_a_silent_drop():
    captured = {}

    def handler(method, url, kwargs):
        if url.endswith("/posts"):
            captured.update(kwargs.get("json") or {})
            return Resp(payload={"id": 1, "slug": "s", "status": "future"})
        return Resp()

    wp = WordPressPublisher(cfg(), session=FakeSession(handler))
    pub = wp.publish_post("T", "<p>b</p>", status="publish",
                          schedule_at="2026-12-01T09:00:00")
    assert captured["status"] == "future"
    assert captured["date_gmt"] == "2026-12-01T09:00:00"
    assert pub.status == "scheduled"


def test_schedule_at_converts_offsets_to_utc():
    captured = {}

    def handler(method, url, kwargs):
        captured.update(kwargs.get("json") or {})
        return Resp(payload={"id": 1, "slug": "s", "status": "future"})

    wp = WordPressPublisher(cfg(), session=FakeSession(handler))
    wp.publish_post("T", "<p>b</p>", schedule_at="2026-12-01T09:00:00-05:00")
    assert captured["date_gmt"] == "2026-12-01T14:00:00"


def test_unparseable_schedule_is_rejected_before_any_network_call():
    session = FakeSession(lambda m, u, k: Resp())
    wp = WordPressPublisher(cfg(), session=session)
    with pytest.raises(WordPressError) as exc:
        wp.publish_post("T", "<p>b</p>", schedule_at="next tuesday")
    assert "ISO 8601" in str(exc.value)
    assert session.calls == []          # nothing was uploaded or created


def test_first_image_is_featured_not_duplicated_in_the_body(tmp_path):
    """The site renders the featured image itself; repeating it shows it twice."""
    files = []
    for name in ("one.png", "two.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG fake")
        files.append(str(p))

    captured = {}
    ids = iter([11, 22])

    def handler(method, url, kwargs):
        if url.endswith("/media"):
            return Resp(payload={"id": next(ids), "source_url": "https://x/i.png"})
        if url.endswith("/posts"):
            captured.update(kwargs.get("json") or {})
            return Resp(payload={"id": 1, "slug": "s", "status": "draft"})
        return Resp(payload={})

    wp = WordPressPublisher(cfg(), session=FakeSession(handler))
    wp.publish_post("T", "<p>body</p>", media_paths=files,
                    alt_texts=["first alt", "second alt"])
    assert captured["featured_media"] == 11
    assert captured["content"].count("<figure>") == 1   # only the second image
    assert "second alt" in captured["content"]
    assert "first alt" not in captured["content"]


def test_alt_text_is_escaped_in_the_body_markup(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"x")
    q = tmp_path / "b.png"
    q.write_bytes(b"x")
    captured = {}

    def handler(method, url, kwargs):
        if url.endswith("/media"):
            return Resp(payload={"id": 1, "source_url": "https://x/i.png"})
        if url.endswith("/posts"):
            captured.update(kwargs.get("json") or {})
            return Resp(payload={"id": 1, "slug": "s", "status": "draft"})
        return Resp(payload={})

    wp = WordPressPublisher(cfg(), session=FakeSession(handler))
    wp.publish_post("T", "<p>b</p>", media_paths=[str(p), str(q)],
                    alt_texts=["ok", 'a "quoted" <script> alt'])
    assert "<script>" not in captured["content"]
    assert "&quot;quoted&quot;" in captured["content"]


def test_wpcom_site_slug_uses_the_host_only():
    wp = WordPressPublisher(
        PCIPConfig(wordpress_com_token="t", wordpress_url="https://wp.passqual.com/blog"),
        session=FakeSession(lambda *a: Resp()),
    )
    assert wp.api_base.endswith("/sites/wp.passqual.com")


def test_challenge_during_publish_surfaces_as_a_challenge():
    session = FakeSession(
        lambda m, u, k: Resp(status=202, headers={"sg-captcha": "1"}, text="<html>")
    )
    wp = WordPressPublisher(cfg(), session=session)
    with pytest.raises(WordPressChallengeError):
        wp.publish_post("T", "<p>b</p>")


def test_unconfigured_wordpress_names_the_origin_requirement():
    with pytest.raises(WordPressNotConfigured) as exc:
        WordPressPublisher(PCIPConfig())
    assert "wp.passqual.com" in str(exc.value)


def test_mirror_auth_header_is_sent_for_stripped_hosts():
    """Hosts that strip Authorization still receive the credentials."""
    import base64

    wp = WordPressPublisher(cfg(), session=FakeSession(lambda *a: Resp()))
    header = wp.http.headers.get("X-PCIP-Authorization", "")
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
    assert decoded == "editor:abcd efgh ijkl"


def test_mirror_auth_header_can_be_switched_off():
    wp = WordPressPublisher(cfg(wordpress_auth_mirror_header=False),
                            session=FakeSession(lambda *a: Resp()))
    assert "X-PCIP-Authorization" not in wp.http.headers


def test_wpcom_mode_does_not_send_the_mirror_header():
    """Only the self-hosted basic-auth path needs it."""
    wp = WordPressPublisher(PCIPConfig(wordpress_com_token="t"),
                            session=FakeSession(lambda *a: Resp()))
    assert "X-PCIP-Authorization" not in wp.http.headers
