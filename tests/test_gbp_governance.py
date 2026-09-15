"""Google Business Profile's own re-entry rules, made unconditional.

This practice's real GBP listing had posting disabled once already, most
likely over a drug name + price + CTA combination — see
GBP-post-compliance-audit.md. These tests hold ``check_social_post`` to the
checklist that audit produced: it must now be structurally impossible for a
GBP post to repeat the mistakes that caused the incident, not just
discouraged from it.
"""

from pcip.standards import PH, check_social_post

GOOD_GBP_BODY = (
    "Un chequeo anual ayuda a detectar la presión alta a tiempo. "
    "Nuestro equipo bilingüe en Miami Gardens ofrece citas rápidas para "
    "adultos que buscan atención preventiva cerca de mí, sin largas esperas."
)


def post(caption, **overrides):
    base = {"caption": caption, "channel": "gbp", "language": "es"}
    base.update(overrides)
    return base


def test_a_well_formed_gbp_post_passes():
    check = check_social_post(post(GOOD_GBP_BODY))
    assert check.passed, check.report()


def test_a_phone_number_in_the_body_is_a_blocker():
    caption = GOOD_GBP_BODY + f" Llame al {PH.NAP_PHONE_DISPLAY}."
    check = check_social_post(post(caption))
    assert any(v.rule == "gbp_cta_in_body" for v in check.blockers)


def test_a_site_url_in_the_body_is_a_blocker():
    caption = GOOD_GBP_BODY + f" Visite {PH.SITE}."
    check = check_social_post(post(caption))
    assert any(v.rule == "gbp_cta_in_body" for v in check.blockers)


def test_the_generic_cta_check_does_not_apply_to_gbp():
    """Every other channel requires the phone/link IN the caption; GBP
    requires the opposite. Running the generic check on GBP would demand a
    phone number that the gbp_cta_in_body rule then rejects — a gate that
    can never pass."""
    check = check_social_post(post(GOOD_GBP_BODY))
    assert not any(v.rule == "cta" for v in check.violations)


def test_too_short_is_flagged():
    check = check_social_post(post("Vengan a vernos."))
    assert any(v.rule == "gbp_length" for v in check.required)


def test_too_long_is_flagged():
    check = check_social_post(post(GOOD_GBP_BODY * 3))
    assert any(v.rule == "gbp_length" for v in check.required)


def test_offer_without_a_dated_discount_blocks():
    check = check_social_post(post(GOOD_GBP_BODY, post_type="Offer"))
    assert any(v.rule == "gbp_post_type" for v in check.blockers)


def test_offer_with_a_real_dated_discount_is_allowed():
    check = check_social_post(
        post(GOOD_GBP_BODY, post_type="Offer", has_dated_discount=True)
    )
    assert not any(v.rule == "gbp_post_type" for v in check.violations)


def test_update_is_the_default_post_type():
    check = check_social_post(post(GOOD_GBP_BODY))
    assert not any(v.rule == "gbp_post_type" for v in check.violations)


def test_more_than_one_emoji_is_advisory():
    caption = GOOD_GBP_BODY + " 😀😀"
    check = check_social_post(post(caption))
    assert any(v.rule == "gbp_emoji" for v in check.advisories)


def test_one_emoji_is_fine():
    caption = GOOD_GBP_BODY + " 😀"
    check = check_social_post(post(caption))
    assert not any(v.rule == "gbp_emoji" for v in check.violations)


def test_shouting_in_all_caps_is_advisory():
    caption = "OFERTA IMPORTANTE: " + GOOD_GBP_BODY
    check = check_social_post(post(caption))
    assert any(v.rule == "gbp_allcaps" for v in check.advisories)


def test_recognized_acronyms_are_not_flagged_as_shouting():
    caption = GOOD_GBP_BODY + " Examenes DOT y I-693 disponibles con USCIS."
    check = check_social_post(post(caption))
    assert not any(v.rule == "gbp_allcaps" for v in check.violations)


def test_a_glp1_mention_blocks_on_every_channel_not_just_gbp():
    caption = "Perdida de peso con semaglutide, promocion especial este mes."
    for channel in ("gbp", "facebook", "instagram"):
        check = check_social_post(
            {"caption": caption, "channel": channel, "language": "es"}
        )
        assert any(v.rule == "restricted_drug_term" for v in check.blockers), channel


def test_a_drug_mention_blocks_an_article_too():
    from pcip.standards import check_article

    body = (
        "<h2>Uno</h2><p>" + "palabra " * 300 + "</p>"
        "<h2>Dos</h2><p>" + "palabra " * 300 + "</p>"
        "<h2>Tres</h2><p>Ofrecemos tirzepatide para bajar de peso.</p>"
    )
    check = check_article({"bodies": {"es": body, "en": body}})
    assert any(v.rule == "restricted_drug_term" for v in check.blockers)
