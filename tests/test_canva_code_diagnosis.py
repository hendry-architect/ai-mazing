"""Telling apart problems behind one Canva error, without guessing at a
format we don't actually know.

Canva answers an expired code and one issued for a different integration
with the same "invalid_grant: Invalid auth code". Those two are tellable
apart locally from the code's own JWT claims. A code from a mismatched
PKCE authorization used to be a third case this diagnosed too, by comparing
the code's ``pkce`` claim against base64url(SHA256(verifier)) — until a real
production code showed that claim is a ~112-character opaque value, not the
43-character S256 challenge that comparison assumed. The check rejected
every real code, always, regardless of whether the authorization actually
matched — see the dated comment on diagnose_code() for how that surfaced.
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


def test_a_mismatched_pkce_claim_is_not_second_guessed():
    """Regression test: this used to raise "different authorization" here,
    unconditionally, for every code — real or not — because the comparison
    assumed a claim format Canva doesn't actually use. A real, correctly
    obtained code must reach exchange_code() and Canva's own verification,
    not be rejected on a guess about an internal field."""
    code, _ = code_for()
    _, other_verifier = code_for()
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
