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
    "We cannot promise a cure.",
])
def test_denying_a_claim_is_not_making_one(text):
    """"There is no cure for diabetes" is exactly the careful sentence a
    physician should write."""
    assert claims(text) == []


@pytest.mark.parametrize("text", [
    # Verbatim from the run this rule blocked.
    "No direct care agreement can promise cures or specific results.",
    "Ningún acuerdo de atención directa puede prometer curas ni resultados "
    "específicos.",
    "No clinic can guarantee that you will feel better.",
    "Ninguna membresía de atención directa puede prometer un milagro.",
])
def test_a_denial_governs_the_whole_sentence_not_the_last_few_words(text):
    """A fixed word-count lookback missed "No direct care agreement can
    promise cures" by one word and the Spanish by three. A clause can put
    any number of words between the denial and the thing denied."""
    assert claims(text) == []


def test_a_denial_does_not_launder_the_next_sentence():
    """"We do not cut corners. We cure diabetes." must still be refused —
    the denial belongs to the previous sentence."""
    assert "cure" in claims("We do not cut corners. We cure diabetes.")


def test_a_denial_after_the_claim_does_not_excuse_it():
    assert "cure" in claims("We cure diabetes. No, really.")


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


# ── markup, and the single implementation ────────────────────────────────


@pytest.mark.parametrize("html", [
    "<p>No outcome is guaranteed.</p>",
    "<p>The Membership does not guarantee any specific clinical outcome.</p>",
    "<p>La Membresía no garantiza ningún resultado clínico.</p>",
    "<h2>Qué incluye</h2><p>Ningún resultado está garantizado.</p>",
])
def test_a_disclaimer_wrapped_in_markup_is_still_a_disclaimer(html):
    """A body arrives as HTML. "<p>No outcome is guaranteed.</p>" tokenises
    as "<p>no", which is not the word "no", so the negation check silently
    failed and blocked the very sentence the standard asks for. It failed a
    real run at the last gate."""
    assert claims(html) == []


def test_the_quote_is_readable_text_not_tags():
    _, quote = claim_hits("<h2>Precios</h2><p>Results are guaranteed.</p>")[0]
    assert "<" not in quote
    assert "Results are guaranteed." in quote


def test_a_claim_inside_markup_is_still_caught():
    assert "guaranteed" in claims("<p>Results are <strong>guaranteed</strong>.</p>")


def test_the_social_check_shares_the_article_implementation():
    """check_social_post kept its own substring loop and received none of the
    three fixes the article check got — word boundaries, negation, and the
    quote. A caption saying "No outcome is guaranteed" was refused."""
    from pcip.standards import check_social_post

    def social(caption):
        check = check_social_post({"caption": caption, "channel": "instagram"})
        return [v for v in check.blockers if v.rule == "claims"]

    assert social("No outcome is guaranteed. 786•677•9922") == []
    assert social("Telehealth and secure messaging.") == []
    flagged = social("Results are guaranteed.")
    assert flagged and "Results are guaranteed" in flagged[0].detail
