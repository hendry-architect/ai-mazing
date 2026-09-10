"""Membership copy may only state figures the signed agreement states.

Sourced from PassQual Membership Agreement v2.0 (§624.27 Direct Health Care
Agreement). The most likely failure when a model writes about a priced
product is a confident, invented number, and a wrong price on a medical
practice's website is a promise the practice never made.
"""

import pytest

from pcip.standards import MEMBERSHIP, check_membership_facts
from pcip.standards.membership import stated_amounts


def rules(text):
    return {v.rule: v.severity for v in check_membership_facts(text)}


COMPLETE = (
    "La Membresía de PassQual es para pacientes sin seguro. Desde $79/mes. "
    "No cubre emergencias, hospital ni especialistas."
)


def test_a_price_the_agreement_states_is_fine():
    assert "unverified_price" not in rules(COMPLETE)


def test_an_invented_price_is_a_blocker():
    assert rules(COMPLETE.replace("$79", "$49"))["unverified_price"] == "blocker"


@pytest.mark.parametrize("amount", sorted(MEMBERSHIP.STATED_AMOUNTS))
def test_every_amount_the_agreement_states_is_allowed(amount):
    text = COMPLETE.replace("$79", f"${amount}")
    assert "unverified_price" not in rules(text)


def test_annual_prices_survive_thousands_separators():
    assert stated_amounts("$1,190/yr and $1,590/yr") == [1190, 1590]
    assert "unverified_price" not in rules(
        COMPLETE.replace("$79/mes", "$1,190 al año")
    )


def test_membership_copy_must_name_what_is_not_covered():
    text = "La Membresía de PassQual es para pacientes sin seguro. $79/mes."
    assert rules(text)["coverage_limits"] == "required"


def test_membership_copy_must_say_who_is_eligible():
    """Section 2 refuses enrollment when eligibility checks find coverage, so
    copy that invites insured readers sends them to a front desk that must
    turn them away."""
    text = ("La Membresía de PassQual cuesta $79/mes y no cubre emergencias "
            "ni hospital.")
    assert rules(text)["eligibility"] == "required"


def test_complete_copy_passes_every_rule():
    assert rules(COMPLETE) == {}


def test_content_that_never_mentions_the_membership_is_untouched():
    """An unrelated article quoting a lab price is not membership copy."""
    assert rules("Una prueba de A1C cuesta unos $25 sin seguro.") == {}


def test_the_tier_table_matches_the_enrollment_form():
    assert MEMBERSHIP.TIERS == {"Core Care": 79, "Plus Care": 119,
                                "Elite Care": 159}
    for fee in MEMBERSHIP.TIERS.values():
        assert fee in MEMBERSHIP.STATED_AMOUNTS


def test_the_statutory_notice_is_carried_verbatim():
    """The agreement marks this DO NOT ALTER — it is the sentence that makes
    the arrangement lawful to sell."""
    assert MEMBERSHIP.STATUTORY_NOTICE_EN.startswith(
        "This agreement is not health insurance"
    )
    assert "26 U.S.C. s. 5000A" in MEMBERSHIP.STATUTORY_NOTICE_EN
    assert "chapter 440" in MEMBERSHIP.STATUTORY_NOTICE_EN
    assert MEMBERSHIP.STATUTORY_NOTICE_ES.startswith(
        "Este acuerdo no es un seguro de salud"
    )
    assert "26 U.S.C. s. 5000A" in MEMBERSHIP.STATUTORY_NOTICE_ES


def test_an_invented_price_blocks_a_social_caption_too():
    from pcip.standards import PH, check_social_post

    check = check_social_post({
        "caption": f"Membresía desde $39/mes. Sin seguro. No cubre "
                   f"emergencias. No es un seguro médico. {PH.BOOKING_ES}",
        "channel": "instagram", "media": ["h.png"], "language": "es",
    })
    assert any(v.rule == "unverified_price" for v in check.blockers)
