"""Membership disclosures a model is unreliable at remembering are supplied
deterministically, mirroring how NAP/FAQ are already auto-composed rather
than left to a model's memory.

Found live: a scheduled patient_education run mentioned "atención directa"
as a passing call-to-action — exactly what 02-diabetes-habits.json's own
brief anticipates ("no es un seguro si se menciona la membresía") — and
ph_standard correctly failed it for missing three paragraphs of §624.27
disclosure language nobody asked the model to reproduce from memory reliably.
"""

from pcip.models import Brief
from pcip.pipelines.library import _with_membership_disclosures, ph_standard_check
from pcip.standards import PH
from pcip.standards.membership import MEMBERSHIP


def test_a_body_without_membership_terms_is_untouched():
    body = "<p>Camine 30 minutos al día para reducir su riesgo.</p>"
    assert _with_membership_disclosures(body, "es") == body


def test_a_passing_mention_gets_the_full_disclosure_appended():
    body = ("<p>Considere la Membresía de PassQual Health para seguimiento "
            "continuo.</p>")
    result = _with_membership_disclosures(body, "es")
    assert result != body
    lowered = result.lower()
    assert "no es un seguro de salud" in lowered
    assert "no cubre" in lowered
    assert "sin seguro" in lowered


def test_an_already_complete_mention_is_not_duplicated():
    body = (f"<p>{MEMBERSHIP.NAME} {MEMBERSHIP.STATUTORY_NOTICE_EN} "
            f"It does not cover {MEMBERSHIP.NOT_COVERED[0]}. Available to "
            "self-pay patients only.</p>")
    assert _with_membership_disclosures(body, "en") == body


def test_the_english_disclosure_is_in_english():
    body = "<p>Ask about our direct primary care membership.</p>"
    result = _with_membership_disclosures(body, "en").lower()
    assert "is not health insurance" in result
    assert "does not cover" in result
    assert "self-pay" in result


def test_ph_standard_check_no_longer_fails_a_passing_membership_mention():
    """Regression test for the exact failure a real scheduled run hit."""
    body_es = (
        "<p>Intro.</p>"
        + "<h2>Sección uno</h2><p>" + ("palabra " * 250) + "</p>"
        + "<h2>Sección dos</h2><p>" + ("palabra " * 250) + "</p>"
        + "<h2>Sección tres</h2><p>" + ("palabra " * 150)
        + " Considere la membresía de PassQual Health para seguimiento "
          "continuo.</p>"
        + f"<p>Búsquenos {PH.NEAR_ME_ES}. Atendido por {PH.PHYSICIAN}, "
        f"licencia {PH.FL_LICENSE}.</p>"
        + f"<p>{PH.NAP_NAME} | {PH.NAP_STREET}, {PH.NAP_CITY}, {PH.NAP_STATE} "
        f"{PH.NAP_ZIP} | {PH.NAP_PHONE_DISPLAY} | {PH.SITE}</p>"
        + f"<p>{PH.BOOKING_ES}</p>"
    )
    body_en = (
        body_es.replace("Sección", "Section").replace("palabra", "word")
        .replace(
            "Considere la membresía de PassQual Health para seguimiento continuo.",
            "Consider PassQual Health's membership for ongoing follow-up.",
        )
    )
    ctx = {
        "brief": Brief(id="b1", title="T", language="bilingual"),
        "copy_fields": {
            "bodies": {"es": body_es, "en": body_en},
            "titles": {"es": "Título", "en": "Title"},
            "meta_title": "Prevención de diabetes",
            "meta_description": "Tres hábitos diarios para cuidar su azúcar.",
            "faq": [{"q": "a", "a": "b"}, {"q": "c", "a": "d"}, {"q": "e", "a": "f"}],
            "featured_image": "/tmp/hero.png",
            "alt_texts_by_language": {"es": "x", "en": "y"},
        },
    }

    detail = ph_standard_check(ctx)      # must not raise
    assert "passed" in detail.lower()

    # The disclosure landed in what actually publishes, not just in the
    # pass/fail check's own private copy.
    assert "no es un seguro de salud" in ctx["copy_fields"]["bodies"]["es"].lower()
    assert "is not health insurance" in ctx["copy_fields"]["bodies"]["en"].lower()
