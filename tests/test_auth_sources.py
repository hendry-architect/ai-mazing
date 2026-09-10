"""Anthropic credential resolution: an unset API key does not mean no
credentials. PCIP must report the source the SDK will actually use.
"""

import os

from pcip.config import PCIPConfig
from pcip.generate.providers import ClaudeCopyProvider


def clear_env(monkeypatch):
    for var in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_FEDERATION_RULE_ID",
                "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_SERVICE_ACCOUNT_ID",
                "ANTHROPIC_IDENTITY_TOKEN_FILE", "ANTHROPIC_IDENTITY_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_api_key_is_reported_as_the_source(monkeypatch):
    clear_env(monkeypatch)
    cfg = PCIPConfig(anthropic_api_key="sk-ant-x")
    assert cfg.anthropic_auth_source == "api_key"
    assert ClaudeCopyProvider(cfg).available() is True


def test_auth_token_counts_without_an_api_key(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    cfg = PCIPConfig()
    assert cfg.anthropic_auth_source == "auth_token"
    assert ClaudeCopyProvider(cfg).available() is True


def test_workload_identity_federation_is_detected(monkeypatch, tmp_path):
    clear_env(monkeypatch)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    for var in ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID",
                "ANTHROPIC_SERVICE_ACCOUNT_ID"):
        monkeypatch.setenv(var, "v")
    monkeypatch.setenv("ANTHROPIC_IDENTITY_TOKEN_FILE", "/var/run/token")
    assert PCIPConfig().anthropic_auth_source == "workload_identity_federation"


def test_federation_needs_an_identity_token_not_just_ids(monkeypatch, tmp_path):
    """Federation without an identity token is not a usable credential."""
    clear_env(monkeypatch)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    for var in ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID",
                "ANTHROPIC_SERVICE_ACCOUNT_ID"):
        monkeypatch.setenv(var, "v")
    assert PCIPConfig().anthropic_auth_source == ""


def test_cli_profile_counts_as_configured(monkeypatch, tmp_path):
    """`ant auth login` leaves no secret in .env — PCIP must still see it."""
    clear_env(monkeypatch)
    profiles = tmp_path / ".config" / "anthropic"
    profiles.mkdir(parents=True)
    (profiles / "profile.json").write_text("{}")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    cfg = PCIPConfig()
    assert cfg.anthropic_auth_source == "cli_profile"
    assert cfg.channel_status()["anthropic"] is True
    assert ClaudeCopyProvider(cfg).available() is True


def test_no_credentials_anywhere(monkeypatch, tmp_path):
    clear_env(monkeypatch)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    cfg = PCIPConfig()
    assert cfg.anthropic_auth_source == ""
    assert ClaudeCopyProvider(cfg).available() is False


def test_default_model_is_opus():
    assert PCIPConfig().anthropic_model == "claude-opus-5"
