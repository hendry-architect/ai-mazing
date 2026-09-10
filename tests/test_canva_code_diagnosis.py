"""Telling three different problems apart behind one Canva error.

Canva answers an expired code, a spent code, and a code from a different
authorization with the same "invalid_grant: Invalid auth code". That is true
and useless — the three have three different fixes, and the code itself is a
JWT carrying enough to tell them apart before Canva is called at all.
"""

import base64
import hashlib
import json
import time

import pytest

from pcip.connectors.canva_auth import diagnose_code, jwt_claims, make_pkce_pair


def code_for(verifier=None, *, expires_in=600, client_id="OC-test", **extra):
    verifier = verifier or make_pkce_pair()[0]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    claims = {"exp": time.time() + expires_in, "iat": time.time(),
              "pkce": challenge, "client_id": client_id, **extra}
    body = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    return f"header.{body}.signature", verifier


def test_a_healthy_code_passes():
    code, verifier = code_for()
    diagnose_code(code, {"verifier": verifier}, "OC-test")


def test_an_expired_code_says_how_long_ago():
    code, verifier = code_for(expires_in=-420)
    with pytest.raises(RuntimeError, match="expired 7 minute"):
        diagnose_code(code, {"verifier": verifier}, "OC-test")


def test_a_code_from_another_authorization_is_named_as_such():
    """The clipboard holding an earlier attempt's URL is the likeliest
    cause, and the least obvious from Canva's answer."""
    code, _ = code_for()
    _, other_verifier = code_for()
    with pytest.raises(RuntimeError, match="different authorization"):
        diagnose_code(code, {"verifier": other_verifier}, "OC-test")


def test_a_code_for_a_different_integration_names_both_ids():
    code, verifier = code_for(client_id="OC-somebody-else")
    with pytest.raises(RuntimeError) as exc:
        diagnose_code(code, {"verifier": verifier}, "OC-test")
    assert "OC-somebody-else" in str(exc.value)
    assert "OC-test" in str(exc.value)


def test_an_opaque_code_is_left_for_canva_to_judge():
    """Guessing about a format we cannot read would be worse than the error
    it replaces."""
    diagnose_code("not-a-jwt", {"verifier": "v"}, "OC-test")


def test_a_malformed_payload_is_not_an_exception():
    assert jwt_claims("a.!!!not-base64!!!.c") == {}
    assert jwt_claims("") == {}
    diagnose_code("a.!!!.c", {"verifier": "v"}, "OC-test")


def test_claims_survive_missing_base64_padding():
    """urlsafe_b64encode strips '=' in a JWT; decoding without restoring it
    raises rather than returning nothing."""
    code, _ = code_for(extra_field="x")
    assert jwt_claims(code)["extra_field"] == "x"


def test_a_pending_flow_with_no_verifier_is_not_second_guessed():
    code, _ = code_for()
    diagnose_code(code, {}, "OC-test")
