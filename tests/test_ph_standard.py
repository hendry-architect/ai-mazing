"""The PassQual Health article standard.

Encoded from the canonical /PH and /PHSEO registry specs. These are not
stylistic preferences — each rule traces to a ratified instruction, and the
first article PCIP published violated most of them: ~120 words, no EN version,
no meta, no image, no NAP, no credentials.
"""

import pytest

from pcip.standards import PH, check_article


def good_article(**over):
    body_es = (
        "<p>Intro.</p>"
        + "<h2>Sección uno</h2><p>" + ("palabra " * 250) + "</p>"
        + "<h2>Sección dos</h2><p>" + ("palabra " * 250) + "</p>"
        + "<h2>Sección tres</h2><p>" + ("palabra " * 150) + "</p>"
        + f"<p>Búsquenos {PH.NEAR_ME_ES}. Atendido por {PH.PHYSICIAN}, "
        f"licencia {PH.FL_LICENSE}.</p>"
        + f"<p>{PH.NAP_NAME} | {PH.NAP_STREET}, {PH.NAP_CITY}, {PH.NAP_STATE} "
        f"{PH.NAP_ZIP} | {PH.NAP_PHONE_DISPLAY} | {PH.SITE}</p>"
        + f"<p>{PH.BOOKING_ES}</p>"
    )
    body_en = body_es.replace("Sección", "Section").replace("palabra", "word")
    article = {
        "bodies": {"es": body_es, "en": body_en},
        "titles": {"es": "Título", "en": "Title"},
        "meta_title": f"Prevención de diabetes en {PH.GEO_PHRASE}",
        "meta_description": "Tres hábitos diarios para cuidar su azúcar, "
                            "explicados por su equipo médico.",
        "faq": [{"q": "a", "a": "b"}, {"q": "c", "a": "d"}, {"q": "e", "a": "f"}],
        "featured_image": "/tmp/hero.png",
        "alt_texts": {"es": "Una persona caminando", "en": "A person walking"},
    }
    article.update(over)
    return article


def test_a_complete_article_passes():
    check = check_article(good_article())
    assert check.passed, check.report()
    assert not check.blockers


# ── bilingual parity ─────────────────────────────────────────────────────────


def test_spanish_only_is_half_a_deliverable():
    a = good_article()
    a["bodies"].pop("en")
    a["titles"].pop("en")
    check = check_article(a)
    assert not check.passed
    assert any(v.rule == "bilingual_parity" for v in check.required)


# ── substance ────────────────────────────────────────────────────────────────


def test_a_caption_length_article_is_rejected():
    """The first published article was ~120 words."""
    a = good_article()
    a["bodies"]["es"] = "<p>" + ("palabra " * 100) + "</p>"
    check = check_article(a)
    assert any(v.rule == "depth" for v in check.required)


def test_missing_section_structure_is_rejected():
    a = good_article()
    a["bodies"]["es"] = a["bodies"]["es"].replace("<h2>", "<p>").replace("</h2>", "</p>")
    assert any(v.rule == "structure" for v in check_article(a).required)


def test_an_in_body_h1_is_rejected():
    """The post title is the H1; a second one breaks the document outline."""
    a = good_article()
    a["bodies"]["es"] += "<h1>Otro título</h1>"
    assert any(v.rule == "one_h1" for v in check_article(a).required)


# ── SEO surface ──────────────────────────────────────────────────────────────


def test_meta_title_length_is_enforced():
    a = good_article(meta_title="x" * (PH.META_TITLE_MAX + 1))
    assert any(v.rule == "meta_title" for v in check_article(a).required)


def test_meta_description_length_is_enforced():
    a = good_article(meta_description="x" * (PH.META_DESCRIPTION_MAX + 1))
    assert any(v.rule == "meta_description" for v in check_article(a).required)


def test_geo_missing_from_title_is_advisory_not_blocking():
    a = good_article(meta_title="Prevención de la diabetes")
    check = check_article(a)
    assert any(v.rule == "geo_in_title" for v in check.advisories)
    assert check.passed          # advisories never block


def test_faq_minimum_is_enforced():
    a = good_article(faq=[{"q": "a", "a": "b"}])
    assert any(v.rule == "faq" for v in check_article(a).required)


# ── visual ───────────────────────────────────────────────────────────────────


def test_a_post_without_a_hero_image_is_rejected():
    a = good_article(featured_image="")
    assert any(v.rule == "featured_image" for v in check_article(a).required)


def test_alt_text_must_be_bilingual():
    a = good_article(alt_texts={"es": "solo español"})
    assert any(v.rule == "alt_text" for v in check_article(a).required)


# ── canon and compliance ─────────────────────────────────────────────────────


def test_missing_nap_blocks():
    a = good_article()
    a["bodies"]["es"] = a["bodies"]["es"].replace(PH.NAP_STREET, "somewhere")
    a["bodies"]["en"] = a["bodies"]["en"].replace(PH.NAP_STREET, "somewhere")
    check = check_article(a)
    assert any(v.rule == "nap" for v in check.blockers)


def test_pediatric_content_blocks():
    """'NO pediatrics, ever' appears in both registry specs."""
    a = good_article()
    a["bodies"]["es"] += "<p>También atendemos niños.</p>"
    assert any(v.rule == "no_pediatrics" for v in check_article(a).blockers)


@pytest.mark.parametrize("claim", ["el mejor", "garantizado", "best doctor", "cure "])
def test_outcome_guarantees_and_superlatives_block(claim):
    a = good_article()
    a["bodies"]["es"] += f"<p>Somos {claim} de la ciudad.</p>"
    assert any(v.rule == "claims" for v in check_article(a).blockers)


def test_mental_health_without_crisis_numbers_blocks():
    a = good_article()
    a["bodies"]["es"] += "<p>Hablemos de la depresión.</p>"
    check = check_article(a)
    assert any(v.rule == "crisis_numbers" for v in check.blockers)


def test_mental_health_with_crisis_numbers_passes():
    a = good_article()
    a["bodies"]["es"] += "<p>Depresión: llame al 988, o al 911 si hay peligro.</p>"
    assert not any(v.rule == "crisis_numbers" for v in check_article(a).blockers)


def test_credentials_are_required_for_eeat():
    a = good_article()
    for lang in ("es", "en"):
        a["bodies"][lang] = a["bodies"][lang].replace(PH.PHYSICIAN, "el equipo")
    assert any(v.rule == "eeat" for v in check_article(a).required)


def test_report_lists_findings_with_fixes():
    check = check_article({"bodies": {"es": "<p>x</p>"}, "titles": {"es": "T"}})
    text = check.report()
    assert "PH standard" in text
    assert "→" in text          # each finding carries a fix


def test_a_pdf_cannot_be_the_featured_image():
    """patient_education exported PDF, which the check accepted silently.

    A PDF is a fine handout and cannot be a hero image; a post shipped with one
    has no image at all in the feed or in search.
    """
    a = good_article(featured_image="/tmp/prevencion.pdf")
    check = check_article(a)
    assert any(v.rule == "featured_image" for v in check.required)
    assert "PDF cannot be a featured image" in check.report()


def test_an_image_hero_passes():
    for suffix in (".png", ".jpg", ".webp"):
        a = good_article(featured_image=f"/tmp/hero{suffix}")
        assert check_article(a).passed, suffix


def test_hero_is_only_advisory_before_the_export_step():
    """At draft the design has not been exported, so demanding it would fail
    every run before a reviewer could see it."""
    a = good_article(featured_image="")
    assert check_article(a, stage="draft").passed
    assert not check_article(a, stage="publish").passed
