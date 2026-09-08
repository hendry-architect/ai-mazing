"""Carrying the authorization code by hand.

A hosted redirect sends the code to a web address rather than to this
machine, so the operator copies it out of the browser. Canva issues it as a
JWT long enough that a clipboard or terminal can cut it, and a truncated
code is rejected by the token endpoint with a generic error that reads like
a misconfigured integration — the wrong thing to go debug.
"""

import pytest
from pcip.connectors import canva_auth

def feed(monkeypatch, value):
    monkeypatch.setattr("builtins.input", lambda _: value)

def test_truncated_jwt_is_named(monkeypatch):
    feed(monkeypatch, "https://passqual.com/canva/callback/?code=aaa.bbb")
    with pytest.raises(RuntimeError, match="truncated"):
        canva_auth._read_pasted_code("st")

def test_complete_jwt_passes(monkeypatch):
    feed(monkeypatch, "https://passqual.com/canva/callback/?code=aaa.bbb.ccc&state=st")
    assert canva_auth._read_pasted_code("st") == "aaa.bbb.ccc"

def test_state_mismatch_still_refuses(monkeypatch):
    feed(monkeypatch, "https://x/?code=aaa.bbb.ccc&state=other")
    with pytest.raises(RuntimeError, match="state"):
        canva_auth._read_pasted_code("st")

def test_opaque_code_without_dots_is_accepted(monkeypatch):
    feed(monkeypatch, "plainopaquecode")
    assert canva_auth._read_pasted_code("st") == "plainopaquecode"
