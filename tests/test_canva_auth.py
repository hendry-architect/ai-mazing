"""Canva OAuth helper tests — PKCE correctness and .env writing (no network)."""

import base64
import hashlib
import urllib.parse

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
