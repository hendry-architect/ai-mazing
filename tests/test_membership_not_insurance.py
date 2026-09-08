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


def test_the_disclaimer_clears_it():
    text = ("Nuestra membresía es un plan de salud alternativo. "
            f"La Membresía de PassQual {PH.NOT_INSURANCE_ES}.")
    assert rules(text) == {}


def test_the_english_disclaimer_clears_it_too():
    text = ("Our membership covers visits with no copay. "
            f"PassQual Membership {PH.NOT_INSURANCE_EN}.")
    assert rules(text) == {}


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
            "La Membresía de PassQual: atención directa cerca de mí en "
            f"Miami Gardens. {PH.NOT_INSURANCE_ES.capitalize()}. "
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
