"""Google Business Profile OAuth helper + adapter auto-refresh (no network).

A plain GBP_ACCESS_TOKEN is a Google access token — good for about an hour.
Fine for a manual test, useless for 3x/week unattended posting. These tests
cover the two halves that make unattended posting actually work: the
one-time ``pcip gbp-auth`` flow (mirrors Canva's PKCE helper, minus PKCE
itself — Google's 'Desktop app' client type doesn't need it), and the
adapter refreshing its own access token before every publish, the same
pattern already proven for Canva in test_canva_token_rotation.py.
"""

import json
import urllib.parse

import pytest

from pcip.config import PCIPConfig
from pcip.connectors.gbp_auth import (
    SCOPE,
    build_authorize_url,
    discover_accounts_and_locations,
    exchange_code,
)
from pcip.connectors.social import ChannelError, GBPAdapter


# ── authorize URL ────────────────────────────────────────────────────────


def test_authorize_url_requests_offline_access_and_forces_consent():
    """Without these two params Google silently omits the refresh token on
    a repeat consent — the exact failure exchange_code() is built to catch."""
    url = build_authorize_url("cid123", "http://127.0.0.1:8090/callback", "state456")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert urllib.parse.urlparse(url).hostname == "accounts.google.com"
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["client_id"] == ["cid123"]
    assert q["state"] == ["state456"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8090/callback"]
    assert q["scope"] == [SCOPE]


# ── token exchange ───────────────────────────────────────────────────────


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload)


def _cfg(**extra):
    return PCIPConfig(gbp_client_id="cid", gbp_client_secret="sec", **extra)


def test_exchange_code_returns_tokens_when_a_refresh_token_comes_back(monkeypatch):
    # exchange_code uses `requests` directly, not an injectable session —
    # patch the module's requests.post for this one call (auto-restored).
    import pcip.connectors.gbp_auth as gbp_auth_mod

    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append((url, data))
        return _Resp({"access_token": "at1", "refresh_token": "rt1"})

    monkeypatch.setattr(gbp_auth_mod.requests, "post", fake_post)
    tokens = exchange_code(_cfg(), "authcode", "http://127.0.0.1:8090/callback")
    assert tokens["access_token"] == "at1"
    assert tokens["refresh_token"] == "rt1"
    assert calls[0][1]["grant_type"] == "authorization_code"
    assert calls[0][1]["code"] == "authcode"


def test_exchange_code_without_a_refresh_token_fails_loudly(monkeypatch):
    """A repeat consent silently omits refresh_token — this is the one
    failure mode that must never be mistaken for success, since it means
    unattended posting dies the moment the access token expires."""
    import pcip.connectors.gbp_auth as gbp_auth_mod

    monkeypatch.setattr(
        gbp_auth_mod.requests, "post",
        lambda *a, **k: _Resp({"access_token": "at1"}),  # no refresh_token
    )
    with pytest.raises(RuntimeError) as exc:
        exchange_code(_cfg(), "authcode", "http://127.0.0.1:8090/callback")
    assert "did not return a refresh token" in str(exc.value)
    assert "myaccount.google.com/permissions" in str(exc.value)


def test_exchange_code_surfaces_a_rejected_code(monkeypatch):
    import pcip.connectors.gbp_auth as gbp_auth_mod

    monkeypatch.setattr(
        gbp_auth_mod.requests, "post",
        lambda *a, **k: _Resp({"error": "invalid_grant"}, status=400),
    )
    with pytest.raises(RuntimeError) as exc:
        exchange_code(_cfg(), "badcode", "http://127.0.0.1:8090/callback")
    assert "400" in str(exc.value)


# ── discovery (not partner-gated — works before Business Profile approval) ──


class _DiscoverySession:
    def __init__(self, accounts, locations_by_account):
        self.accounts = accounts
        self.locations_by_account = locations_by_account
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if "accounts" in url and "locations" not in url:
            return _Resp({"accounts": self.accounts})
        for account_name, locations in self.locations_by_account.items():
            if account_name in url:
                return _Resp({"locations": locations})
        return _Resp({"locations": []})


def test_discover_flags_the_real_listing_and_the_duplicate():
    session = _DiscoverySession(
        accounts=[{"name": "accounts/111", "accountName": "PassQual Health LLC"}],
        locations_by_account={
            "accounts/111": [
                {"name": "accounts/111/locations/AAA",
                 "title": "PassQual Health - Miami Gardens",
                 "storefrontAddress": {"locality": "Miami Gardens"}},
                {"name": "accounts/111/locations/BBB",
                 "title": "Hendry Perez Pascual, MD",
                 "storefrontAddress": {"locality": "Miami Gardens"}},
            ],
        },
    )
    cfg = _cfg(gbp_access_token="at1")
    found = discover_accounts_and_locations(cfg, session=session)

    real = next(f for f in found if f["location_id"] == "AAA")
    dup = next(f for f in found if f["location_id"] == "BBB")
    assert "real listing" in real["note"]
    assert "DUPLICATE" in dup["note"]
    assert real["account_id"] == "111"


def test_discover_fails_loudly_on_a_bad_token():
    class _Denied:
        def get(self, url, headers=None, timeout=None):
            return _Resp({"error": "unauthorized"}, status=401)

    with pytest.raises(RuntimeError) as exc:
        discover_accounts_and_locations(_cfg(gbp_access_token="stale"), session=_Denied())
    assert "401" in str(exc.value)


# ── adapter auto-refresh before every publish ───────────────────────────────


class _AdapterSession:
    """Answers both the token endpoint and the Local Posts endpoint."""

    def __init__(self, refresh_status=200):
        self.refresh_status = refresh_status
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(url)
        if "oauth2.googleapis.com" in url:
            if self.refresh_status != 200:
                return _Resp({"error": "invalid_grant"}, self.refresh_status)
            return _Resp({"access_token": "fresh_at"})
        return _Resp({"name": "accounts/1/locations/2/localPosts/3"})


def _adapter_cfg(**extra):
    return PCIPConfig(
        gbp_access_token="stale_at",
        gbp_account_id="1",
        gbp_location_id="2",
        **extra,
    )


def test_publish_refreshes_before_posting_when_refresh_creds_are_set(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GBP_ACCESS_TOKEN=stale_at\n")
    cfg = _adapter_cfg(
        gbp_refresh_token="rt1", gbp_client_id="cid", gbp_client_secret="sec",
        env_file=str(env),
    )
    session = _AdapterSession()
    adapter = GBPAdapter(cfg, session)
    adapter.publish(adapter.channels[0], "A" * 160)

    assert cfg.gbp_access_token == "fresh_at"
    assert "GBP_ACCESS_TOKEN=fresh_at" in env.read_text()
    # The Local Posts call must use the refreshed token, not the stale one.
    post_urls = [c for c in session.calls if "localPosts" in c]
    assert post_urls


def test_publish_skips_refresh_with_no_refresh_credentials_configured():
    """A manually-pasted access token, with no client_id/refresh_token,
    must keep working exactly as it did before this feature existed."""
    cfg = _adapter_cfg()  # no gbp_refresh_token, no gbp_client_id
    session = _AdapterSession()
    adapter = GBPAdapter(cfg, session)
    adapter.publish(adapter.channels[0], "A" * 160)

    assert cfg.gbp_access_token == "stale_at"       # never touched
    assert not any("oauth2.googleapis.com" in c for c in session.calls)


def test_a_rejected_refresh_names_the_reauth_command():
    cfg = _adapter_cfg(gbp_refresh_token="rt1", gbp_client_id="cid",
                       gbp_client_secret="sec")
    session = _AdapterSession(refresh_status=400)
    adapter = GBPAdapter(cfg, session)
    with pytest.raises(ChannelError) as exc:
        adapter.publish(adapter.channels[0], "A" * 160)
    assert "gbp-auth" in str(exc.value)


def test_an_unwritable_env_never_fails_the_publish(tmp_path):
    cfg = _adapter_cfg(
        gbp_refresh_token="rt1", gbp_client_id="cid", gbp_client_secret="sec",
        env_file=str(tmp_path / "nope" / "deeper" / ".env"),
    )
    session = _AdapterSession()
    adapter = GBPAdapter(cfg, session)
    pub = adapter.publish(adapter.channels[0], "A" * 160)
    assert pub.status == "published"
    assert cfg.gbp_access_token == "fresh_at"
