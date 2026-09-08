"""Prohibited-claim matching, in both directions.

A plain substring scan blocked a correct membership article: "cure" fires
inside "secure messaging" — the exact phrase the membership agreement uses —
and "cura" inside "procura". A gate that refuses correct copy is worse than
no gate, because it teaches the writer to work around it.
"""

import pytest

from pcip.standards import PH, check_article
from pcip.standards.ph import claim_hits


def claims(text):
    return [c for c, _ in claim_hits(text)]


# ── copy that must pass ──────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "Incluye telesalud y secure messaging.",
    "Mensajería segura, no insecure email.",
    "Una manicure no es un servicio médico.",
    "El procedimiento es seguro y se procura atención temprana.",
    "Nada obscure en nuestros precios.",
])
def test_a_claim_inside_a_longer_word_is_not_a_claim(text):
    assert claims(text) == []


@pytest.mark.parametrize("text", [
    "There is no cure for type 2 diabetes.",
    "No hay cura para la diabetes.",
    "Nunca garantizamos un resultado.",
    "Ningún resultado está garantizado.",
    "Esto no es un milagro.",
])
def test_denying_a_claim_is_not_making_one(text):
    """"There is no cure for diabetes" is exactly the careful sentence a
    physician should write."""
    assert claims(text) == []


# ── copy that must be refused ────────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("We cure diabetes in 30 days.", "cure"),
    ("It cures your condition.", "cure"),
    ("Curamos la diabetes.", "curamos"),
    ("Resultados garantizados.", "garantizado"),
    ("Una mejoría garantizada.", "garantizada"),
    ("Somos el mejor consultorio de Miami.", "el mejor"),
    ("Tratamiento 100% efectivo.", "100% efectivo"),
    ("Terapia 100% efectiva.", "100% efectiva"),
    ("risk-free treatment", "risk-free"),
    ("Es un milagro médico.", "milagro"),
    ("Un tratamiento milagroso.", "milagroso"),
    ("The best doctor in Miami.", "best doctor"),
    ("Somos el número uno.", "número uno"),
])
def test_a_claim_actually_made_is_refused(text, expected):
    assert expected in claims(text)


def test_the_spanish_plural_is_caught():
    """Word boundaries alone lost "garantizados", which the old substring
    scan caught — a regression worth a test of its own."""
    assert "garantizado" in claims("Resultados garantizados en 30 días.")


# ── what the report tells the writer ─────────────────────────────────────


def test_the_finding_quotes_the_sentence():
    """"prohibited claim: 'cure'" with no quote leaves the writer hunting
    through 1,600 words for it."""
    _, quote = claim_hits("Bla bla. We cure diabetes fast. Bla.")[0]
    assert "We cure diabetes fast" in quote


def test_each_claim_is_reported_once_not_per_occurrence():
    hits = claim_hits("We cure this. We cure that. We cure everything.")
    assert [c for c, _ in hits] == ["cure"]


def test_the_article_check_reports_it_as_a_blocker():
    check = check_article({"bodies": {"es": "Curamos la diabetes."}},
                          stage="draft")
    blockers = [v for v in check.blockers if v.rule == "claims"]
    assert blockers and "Curamos la diabetes" in blockers[0].detail


def test_secure_messaging_no_longer_blocks_an_article():
    """The membership agreement's own wording for what every tier
    includes."""
    check = check_article(
        {"bodies": {"en": "Telehealth visits and secure messaging."}},
        stage="draft",
    )
    assert not [v for v in check.blockers if v.rule == "claims"]


@pytest.mark.parametrize("claim", PH.FORBIDDEN_CLAIMS)
def test_every_listed_claim_is_detectable_on_its_own(claim):
    """A term nobody can trigger is a rule that silently does nothing."""
    assert claim in claims(f"Nuestro servicio: {claim}.")
