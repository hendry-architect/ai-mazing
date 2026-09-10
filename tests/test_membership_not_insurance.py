"""The membership is a direct-pay arrangement, not an insurance product.

Florida's direct primary care statute turns on exactly that distinction and
requires the agreement to state it plainly, so content that blurs it is a
regulatory exposure rather than a wording preference. The standard's job is
narrow and checkable: make sure the sentence is there.
"""

import pytest

from pcip.standards import PH, check_social_post
from pcip.standards.ph import _membership_violations


def rules(text):
    return {v.rule: v.severity for v in _membership_violations(text.lower())}


def test_membership_plus_insurance_language_is_a_blocker():
    text = ("Nuestra membresía reemplaza su seguro médico y no tiene "
            "deducible.")
    assert rules(text) == {"not_insurance": "blocker"}


@pytest.mark.parametrize("phrase", PH.NOT_INSURANCE_ES)
def test_either_spanish_disclaimer_clears_it(phrase):
    """The §624.27 statutory text says "seguro de salud". Insisting on
    "seguro médico" would have rejected the exact sentence Florida
    requires."""
    assert rules(f"Nuestra membresía es un plan de salud alternativo. "
                 f"La Membresía de PassQual {phrase}.") == {}


@pytest.mark.parametrize("phrase", PH.NOT_INSURANCE_EN)
def test_either_english_disclaimer_clears_it(phrase):
    assert rules(f"Our membership covers visits with no copay. "
                 f"PassQual Membership {phrase}.") == {}


def test_the_statutory_notice_itself_satisfies_the_rule():
    from pcip.standards import MEMBERSHIP

    assert rules(f"Nuestra membresía. {MEMBERSHIP.STATUTORY_NOTICE_ES}") == {}
    assert rules(f"Our membership. {MEMBERSHIP.STATUTORY_NOTICE_EN}") == {}


def test_membership_without_insurance_language_is_required_not_blocking():
    """A piece that never mentions insurance still has to say what the
    membership is not — but that is an editorial fix, not a claim to stop."""
    assert rules("Conozca nuestra membresía de atención directa.") == {
        "not_insurance": "required"
    }


def test_content_that_never_mentions_the_membership_is_untouched():
    """An article advising uninsured patients legitimately says 'seguro'."""
    assert rules("Si no tiene seguro médico, hay opciones en la comunidad.") == {}


def test_the_rule_reaches_social_captions(tmp_path):
    """The claim that gets a practice in trouble is the same one in a caption."""
    check = check_social_post({
        "caption": "Nuestra membership es mejor que tu health insurance. "
                   f"{PH.BOOKING_ES}",
        "channel": "instagram", "media": ["hero.png"], "language": "es",
    })
    assert any(v.rule == "not_insurance" for v in check.blockers)


def test_a_compliant_membership_caption_passes():
    check = check_social_post({
        "caption": (
            "La Membresía de PassQual: atención directa para quien está sin "
            "seguro, cerca de mí en Miami Gardens. No es un seguro médico y "
            "no cubre emergencias ni hospital. Desde $79/mes. "
            f"{PH.BOOKING_ES} #SaludMiami"
        ),
        "channel": "instagram", "media": ["hero.png"], "language": "es",
    })
    assert check.passed, check.report()


@pytest.mark.parametrize("term", PH.MEMBERSHIP_TERMS)
def test_every_membership_synonym_triggers_the_rule(term):
    """A synonym that slips past the list is a piece of content the standard
    silently stops governing."""
    assert "not_insurance" in rules(f"Conozca {term} hoy.")
