"""When Canva keeps answering 429/5xx and retries run out, the failure has
to say what Canva actually said — not just that giving up happened.

Found live: a scheduled run failed twice in a row at "POST /autofills:
retries exhausted", identical both times, with no way to tell whether Canva
was genuinely rate-limiting (wait and retry) or rejecting the request for a
reason no amount of retrying would fix. The status and body of the last
attempt were being read and then thrown away.
"""

import time

import pytest

from pcip.config import PCIPConfig
from pcip.connectors.canva import CanvaClient, CanvaError


class _Resp:
    def __init__(self, status, body=""):
        self.status_code = status
        self._body = body

    @property
    def text(self):
        return self._body

    @property
    def headers(self):
        return {}

    def json(self):
        return {}


class _AlwaysSession:
    def __init__(self, status, body=""):
        self.status = status
        self.body = body
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        return _Resp(self.status, self.body)


def client(session):
    cfg = PCIPConfig(canva_access_token="at1")
    return CanvaClient(cfg, session=session)


def test_exhausted_retries_names_the_status_and_body(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    session = _AlwaysSession(429, body='{"code":"rate_limited"}')
    c = client(session)
    with pytest.raises(CanvaError) as exc:
        c._request("POST", "/autofills")
    assert "429" in str(exc.value)
    assert "rate_limited" in str(exc.value)
    assert exc.value.status == 429
    assert session.calls == 4


def test_a_persistent_500_is_distinguishable_from_a_429(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    session = _AlwaysSession(500, body="upstream exploded")
    c = client(session)
    with pytest.raises(CanvaError) as exc:
        c._request("POST", "/autofills")
    assert "500" in str(exc.value)
    assert "upstream exploded" in str(exc.value)
