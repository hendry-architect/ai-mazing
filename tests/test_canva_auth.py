"""Canva OAuth helper tests — PKCE correctness and .env writing (no network)."""

import base64
import hashlib
import urllib.parse

import json

import pytest

from pcip.connectors.canva_auth import (
    DEFAULT_SCOPES,
    build_authorize_url,
    make_pkce_pair,
    update_env_file,
)


def test_pkce_pair_is_valid_s256():
    verifier, challenge = make_pkce_pair()
    assert 43 <= len(verifier) <= 128          # RFC 7636 bounds
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert challenge == expected
    # Fresh randomness every call.
    assert make_pkce_pair()[0] != verifier


def test_authorize_url_contains_required_params():
    url = build_authorize_url("client123", "http://127.0.0.1:8080/callback",
                              "chal", "state456")
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    assert parsed.hostname == "www.canva.com"
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["client123"]
    assert q["code_challenge_method"] == ["s256"]
    assert q["state"] == ["state456"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8080/callback"]
    assert "design:content:read" in q["scope"][0]
    assert DEFAULT_SCOPES == q["scope"][0]


def test_update_env_file_replaces_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment stays\nCANVA_ACCESS_TOKEN=old\nOTHER_VAR=keepme\n"
    )
    update_env_file(env, {"CANVA_ACCESS_TOKEN": "new_at",
                          "CANVA_REFRESH_TOKEN": "new_rt"})
    content = env.read_text()
    assert "# comment stays" in content
    assert "OTHER_VAR=keepme" in content
    assert "CANVA_ACCESS_TOKEN=new_at" in content
    assert "CANVA_ACCESS_TOKEN=old" not in content
    assert "CANVA_REFRESH_TOKEN=new_rt" in content


def test_update_env_file_creates_missing_file(tmp_path):
    env = tmp_path / "fresh.env"
    update_env_file(env, {"CANVA_ACCESS_TOKEN": "at"})
    assert env.read_text() == "CANVA_ACCESS_TOKEN=at\n"


# ── hosted redirect: carrying the code back by hand ──────────────────────────


def test_a_pasted_redirect_url_yields_the_code():
    """A hosted callback sends the code to a web address, not to this machine.
    It is visible in the address bar, so pasting the URL is enough."""
    from pcip.connectors.canva_auth import parse_code

    assert parse_code(
        "https://passqual.com/canva/callback?code=ABC123&state=S1", "S1"
    ) == "ABC123"


def test_a_trailing_slash_before_the_query_is_fine():
    from pcip.connectors.canva_auth import parse_code

    assert parse_code(
        "https://passqual.com/canva/callback/?code=ABC&state=S1", "S1"
    ) == "ABC"


def test_a_bare_code_is_accepted():
    from pcip.connectors.canva_auth import parse_code

    assert parse_code("ABC123", "S1") == "ABC123"


def test_a_mismatched_state_is_refused():
    """The CSRF check still applies when the operator carries the code by hand."""
    from pcip.connectors.canva_auth import parse_code

    with pytest.raises(RuntimeError, match="does not match"):
        parse_code(
            "https://passqual.com/canva/callback?code=ABC&state=WRONG", "EXPECTED"
        )


def test_nothing_pasted_is_an_error():
    from pcip.connectors.canva_auth import parse_code

    with pytest.raises(RuntimeError):
        parse_code("   ", "S1")


def test_a_truncated_jwt_is_named_as_truncated():
    """Canva issues the code as a JWT. A cut one is rejected by the token
    endpoint with a generic error that reads like a misconfigured
    integration, sending the operator to debug the wrong thing."""
    from pcip.connectors.canva_auth import parse_code

    with pytest.raises(RuntimeError, match="truncated"):
        parse_code("https://passqual.com/canva/callback/?code=aaa.bbb", "S1")


def test_a_complete_jwt_passes():
    from pcip.connectors.canva_auth import parse_code

    assert parse_code(
        "https://passqual.com/canva/callback/?code=aaa.bbb.ccc&state=S1", "S1"
    ) == "aaa.bbb.ccc"


def test_an_opaque_code_is_not_held_to_the_jwt_shape():
    """The three-segment check applies only to something that looks like a
    JWT; a different token format must still work."""
    from pcip.connectors.canva_auth import parse_code

    assert parse_code("plainopaquecode", "S1") == "plainopaquecode"


# ── the two-step flow, which exists because a terminal cannot take the paste ─


class _Pipe:
    """Stand-in for a piped stdin."""

    def __init__(self, text):
        self._text = text

    def isatty(self):
        return False

    def read(self):
        return self._text


def _client_cfg(tmp_path):
    from pcip.config import PCIPConfig

    return PCIPConfig(data_dir=tmp_path, canva_client_id="cid",
                      canva_client_secret="secret")


def test_start_remembers_the_verifier_and_finish_spends_it(tmp_path, monkeypatch):
    """macOS gives a tty a 1024-byte canonical input buffer and a Canva
    redirect URL is longer, so pasting one at a prompt silently does nothing.
    Splitting the flow lets the code arrive through a pipe instead."""
    from pcip.connectors import canva_auth

    cfg = _client_cfg(tmp_path)
    path = canva_auth.start_manual_flow(
        cfg, "https://passqual.com/canva/callback", open_browser=False
    )
    pending = json.loads(path.read_text())
    assert pending["verifier"] and pending["state"]
    assert pending["redirect_uri"] == "https://passqual.com/canva/callback"
    assert oct(path.stat().st_mode)[-3:] == "600"

    seen = {}

    def fake_exchange(_cfg, code, verifier, redirect_uri):
        seen.update(code=code, verifier=verifier, redirect_uri=redirect_uri)
        return {"access_token": "at", "refresh_token": "rt"}

    monkeypatch.setattr(canva_auth, "exchange_code", fake_exchange)
    url = f"https://passqual.com/canva/callback/?code=a.b.c&state={pending['state']}"
    canva_auth.finish_manual_flow(cfg, write_env=None, stdin=_Pipe(url))

    assert seen == {
        "code": "a.b.c",
        "verifier": pending["verifier"],
        "redirect_uri": "https://passqual.com/canva/callback",
    }
    assert not path.exists(), "a spent verifier must not invite a retry"


def test_finish_without_a_start_says_so(tmp_path):
    from pcip.connectors.canva_auth import finish_manual_flow

    with pytest.raises(RuntimeError, match="No authorization in progress"):
        finish_manual_flow(_client_cfg(tmp_path), stdin=_Pipe("code"))


def test_an_expired_authorization_is_refused_with_the_real_reason(
    tmp_path, monkeypatch
):
    """Left to reach the token endpoint, an expired code returns a generic
    failure that looks like bad credentials."""
    from pcip.connectors import canva_auth

    cfg = _client_cfg(tmp_path)
    path = canva_auth.start_manual_flow(
        cfg, "https://passqual.com/canva/callback", open_browser=False
    )
    stale = json.loads(path.read_text())
    stale["created_at"] -= canva_auth.PENDING_TTL_SECONDS + 60
    path.write_text(json.dumps(stale))

    with pytest.raises(RuntimeError, match="expired"):
        canva_auth.finish_manual_flow(cfg, stdin=_Pipe("a.b.c"))
    assert not path.exists()


def test_finish_reads_a_file_when_given_one(tmp_path, monkeypatch):
    from pcip.connectors import canva_auth

    cfg = _client_cfg(tmp_path)
    path = canva_auth.start_manual_flow(
        cfg, "https://passqual.com/canva/callback", open_browser=False
    )
    state = json.loads(path.read_text())["state"]
    url_file = tmp_path / "url.txt"
    url_file.write_text(f"https://passqual.com/canva/callback?code=a.b.c&state={state}")

    monkeypatch.setattr(canva_auth, "exchange_code",
                        lambda *_: {"access_token": "at", "refresh_token": "rt"})
    tokens = canva_auth.finish_manual_flow(
        cfg, code_file=str(url_file), write_env=None
    )
    assert tokens["access_token"] == "at"


def test_a_pipe_is_preferred_over_the_terminal():
    from pcip.connectors.canva_auth import read_code_from

    assert read_code_from(stdin=_Pipe("piped")) == "piped"


def test_an_explicit_code_wins_over_every_other_source(tmp_path):
    from pcip.connectors.canva_auth import read_code_from

    f = tmp_path / "u.txt"
    f.write_text("from-file")
    assert read_code_from("explicit", str(f), _Pipe("piped")) == "explicit"


def test_start_refuses_without_client_credentials(tmp_path):
    from pcip.config import PCIPConfig
    from pcip.connectors.canva_auth import start_manual_flow

    with pytest.raises(RuntimeError, match="CANVA_CLIENT_ID"):
        start_manual_flow(PCIPConfig(data_dir=tmp_path), "https://x/cb")
