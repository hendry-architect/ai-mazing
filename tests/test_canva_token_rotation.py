"""Canva rotates its refresh token, so PCIP has to keep the new one.

Canva issues a fresh refresh token on every refresh and invalidates the one
just used. Keeping the new value only in memory meant the rotation was lost
when the process exited: .env still held the dead token, and the next run
got a 400. Canva access survived exactly one refresh — which, for a platform
meant to run unattended three times a week, is the same as not working. It
is how a finished article failed at the export step.
"""

import json

import pytest

from pcip.config import PCIPConfig, dotenv_path
from pcip.connectors.canva import CanvaClient, CanvaError


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


class _Session:
    """Answers the token endpoint; every refresh rotates, as Canva does."""

    def __init__(self, status=200):
        self.status = status
        self.refreshes = 0
        self.sent = []

    def post(self, url, **kwargs):
        self.refreshes += 1
        self.sent.append(kwargs.get("data", {}))
        if self.status != 200:
            return _Resp({"error": "invalid_grant"}, self.status)
        return _Resp({"access_token": f"at{self.refreshes}",
                      "refresh_token": f"rt{self.refreshes}"})


def env(tmp_path, **extra):
    path = tmp_path / ".env"
    path.write_text("CANVA_ACCESS_TOKEN=old_at\nCANVA_REFRESH_TOKEN=rt0\n")
    cfg = PCIPConfig(canva_client_id="cid", canva_client_secret="sec",
                     canva_refresh_token="rt0", env_file=str(path), **extra)
    return cfg, path


def values(path):
    return dict(
        line.split("=", 1) for line in path.read_text().splitlines() if "=" in line
    )


def test_a_rotated_refresh_token_reaches_the_env_file(tmp_path):
    cfg, path = env(tmp_path)
    session = _Session()
    CanvaClient(cfg, session)._refresh_access_token()

    assert values(path)["CANVA_REFRESH_TOKEN"] == "rt1"
    assert values(path)["CANVA_ACCESS_TOKEN"] == "at1"


def test_the_next_process_uses_the_rotated_token(tmp_path):
    """The actual failure: a second run reading .env got the dead token."""
    cfg, path = env(tmp_path)
    session = _Session()
    CanvaClient(cfg, session)._refresh_access_token()

    later = PCIPConfig(canva_client_id="cid", canva_client_secret="sec",
                       canva_refresh_token=values(path)["CANVA_REFRESH_TOKEN"],
                       env_file=str(path))
    CanvaClient(later, session)._refresh_access_token()
    assert session.sent[-1]["refresh_token"] == "rt1", (
        "the second run sent a token Canva had already invalidated"
    )


def test_the_file_keeps_its_other_keys(tmp_path):
    cfg, path = env(tmp_path)
    path.write_text("# creds\nANTHROPIC_API_KEY=sk-keep\n"
                    "CANVA_REFRESH_TOKEN=rt0\n")
    CanvaClient(cfg, _Session())._refresh_access_token()
    text = path.read_text()
    assert "ANTHROPIC_API_KEY=sk-keep" in text and "# creds" in text


def test_no_env_file_means_no_persistence(tmp_path):
    """A library or test caller must not have a .env written under it."""
    cfg = PCIPConfig(canva_client_id="cid", canva_client_secret="sec",
                     canva_refresh_token="rt0")
    CanvaClient(cfg, _Session())._refresh_access_token()
    assert cfg.canva_refresh_token == "rt1"
    assert not (tmp_path / ".env").exists()


def test_an_unwritable_env_never_fails_a_run(tmp_path):
    """Losing the rotation is the old behaviour; losing the run is worse."""
    cfg, path = env(tmp_path)
    cfg.env_file = str(tmp_path / "nope" / "deeper" / ".env")
    CanvaClient(cfg, _Session())._refresh_access_token()
    assert cfg.canva_refresh_token == "rt1"


def test_a_rejected_refresh_says_what_to_do(tmp_path):
    cfg, _ = env(tmp_path)
    with pytest.raises(CanvaError) as exc:
        CanvaClient(cfg, _Session(status=400))._refresh_access_token()
    message = str(exc.value)
    assert "rotates it on every refresh" in message
    assert "canva-auth" in message


def test_dotenv_path_finds_nothing_when_there_is_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert dotenv_path(tmp_path / "absent.env") is None
