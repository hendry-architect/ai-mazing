"""Licensing policy engine tests — the guardrails must hold."""

import pytest

from pcip.licensing import LicensePolicy, LicensingError
from pcip.models import Asset, License, LicenseType


def asset(lic_type: LicenseType, **meta) -> Asset:
    return Asset(name="x", license=License(type=lic_type, source="canva"), metadata=meta)


def test_prohibited_actions_always_blocked():
    policy = LicensePolicy()
    for action in ("extract_standalone", "strip_watermark", "scrape",
                   "screenshot_capture", "redistribute_raw"):
        for lic in LicenseType:
            decision = policy.check_action(action, asset(lic))
            assert not decision.allowed, f"{action} must be blocked for {lic}"


def test_supported_workflows_allowed():
    policy = LicensePolicy()
    for action in ("use_in_design", "export_design", "autofill_template"):
        assert policy.check_action(action, asset(LicenseType.CANVA_PRO)).allowed


def test_unknown_action_default_denied_for_premium():
    policy = LicensePolicy()
    assert not policy.check_action("weird_new_thing", asset(LicenseType.CANVA_PRO))
    assert policy.check_action("weird_new_thing", asset(LicenseType.OWNED)).allowed


def test_publish_blocked_without_license():
    policy = LicensePolicy()
    decision = policy.check_publish([asset(LicenseType.UNKNOWN)])
    assert not decision.allowed
    assert "unknown" in decision.reason


def test_publish_blocked_for_non_exported_premium():
    policy = LicensePolicy()
    # Premium content NOT produced by a design export → blocked.
    assert not policy.check_publish([asset(LicenseType.CANVA_PRO)])
    # Same content as part of an official design export → allowed.
    assert policy.check_publish([asset(LicenseType.CANVA_PRO, via_export=True)])


def test_publish_allows_owned_and_ai():
    policy = LicensePolicy()
    assert policy.check_publish(
        [asset(LicenseType.OWNED), asset(LicenseType.AI_GENERATED)]
    ).allowed


def test_require_raises():
    with pytest.raises(LicensingError):
        LicensePolicy().require("scrape", asset(LicenseType.CANVA_PRO))


def test_canva_export_license_marks_supported_workflow():
    lic = LicensePolicy.canva_export_license(pro=True)
    assert lic.type == LicenseType.CANVA_PRO
    assert "export" in lic.notes.lower()
