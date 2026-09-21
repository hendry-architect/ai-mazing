"""PassQual Health article standard.

Encoded from the canonical /PH and /PHSEO command-registry specs so the
platform enforces them instead of relying on whoever is reviewing to remember
them. Anything here that reads like a preference is not: each rule traces to a
ratified instruction, and several exist because something shipped wrong once.

The validator returns violations rather than raising, so a run can present the
whole list at a review gate. Severity separates what blocks a publish from what
merely wants a human's eye:

  blocker  — must never reach a reader (compliance, pediatrics, missing NAP)
  required — the standard says every article has it (bilingual pair, meta, image)
  advisory — worth a look, does not stop the run
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


class PH:
    """Canonical facts. Never paraphrase these — they are printed verbatim."""

    BRAND = "PassQual Health"
    HANDLE = "@passqualhealth"

    # NAP must be byte-identical everywhere it appears; a near-miss splits the
    # local-search entity and is worse than omitting it.
    NAP_NAME = "PassQual Health"
    NAP_STREET = "18706 NW 67th Ave"
    NAP_CITY = "Miami Gardens"
    NAP_STATE = "FL"
    NAP_ZIP = "33015"
    NAP_PHONE_DISPLAY = "(786) 677-9922"
    NAP_PHONE_SOCIAL = "786•677•9922"
    NAP_PHONE_E164 = "+17866779922"
    SITE = "https://passqual.com"

    # E-E-A-T: physician credentials belong on every clinical page.
    PHYSICIAN = "Dr. Hendry Pascual"
    FL_LICENSE = "ME143678"
    NPI_INDIVIDUAL = "1437577032"
    NPI_ORG = "1427677319"
    CREDENTIALS = (
        "USCIS-designated civil surgeon · UCLA residency · CHCQM-PHYADV"
    )

    BOOKING_ES = "Agenda tu cita → 📞 786•677•9922"
    BOOKING_EN = "Book an appointment → 📞 786•677•9922"

    # Spanish-primary, bilingual parity via Polylang.
    PRIMARY_LANGUAGE = "es"
    LANGUAGES = ("es", "en")

    META_TITLE_MAX = 60
    META_DESCRIPTION_MAX = 155

    # An article shorter than this is a social caption wearing a headline. The
    # first PCIP article shipped at ~120 words and read as thin.
    #
    # This floor is PCIP's, not the command registry's — the /PHSEO spec asks
    # for "bilingual, patient-plain language" without naming a length. It is
    # set here so the bar is explicit and reviewable rather than living in
    # whoever is editing that day.
    MIN_BODY_WORDS = 600
    # What generation aims for. A model told to write "at least 600" counts as
    # it goes and stops near 600, which lands under the floor once markup is
    # stripped — the run then fails on a near-miss that is not a quality
    # difference. Asking for margin costs nothing and removes the whole class.
    TARGET_BODY_WORDS = 800
    MIN_H2_SECTIONS = 3
    MIN_FAQ_ITEMS = 3

    # Spanish speakers search service + "cerca de mí", not city names, which
    # have near-zero volume. Geo still belongs in the title for the entity.
    GEO_PHRASE = "Miami Gardens"
    NEAR_ME_ES = "cerca de mí"

    # Hard exclusion, stated in both specs, no exceptions.
    FORBIDDEN_TOPICS = (
        "pediatr", "niño", "niños", "infantil", "child", "children",
        "kids", "pediatric",
    )

    # Outcome guarantees and superlatives. Structure/function claims only.
    # Matched on word boundaries — as a substring, "cure" fires inside
    # "secure messaging" and "cura" inside "procura", which is how a correct
    # article about the membership came to be rejected for a claim it never
    # made.
    # Spanish adjectives agree, so the feminine forms are listed alongside
    # the masculine; a trailing plural -s is matched automatically. Word
    # boundaries alone would have let "garantizados" through, which plain
    # substring matching caught.
    FORBIDDEN_CLAIMS = (
        "best doctor", "mejor médico", "mejor doctor", "el mejor",
        "guaranteed", "garantizado", "garantizada", "garantizamos",
        "garantiza", "cure", "cura", "curamos", "100% effective",
        "100% efectivo", "100% efectiva", "risk-free", "sin riesgo",
        "milagro", "milagroso", "milagrosa", "miracle", "number one",
        "número uno",
    )

    # Denying a claim is the opposite of making one. "There is no cure for
    # diabetes" is exactly the careful sentence a physician should write, and
    # a keyword blocker that refuses it teaches the writer to be vaguer.
    CLAIM_NEGATIONS = (
        "no", "not", "cannot", "n't", "never", "neither", "nor",
        "sin", "nunca", "ninguna", "ningún", "ningun", "nada", "tampoco",
        "jamás", "jamas", "hay",
    )

    # The membership is a direct-pay arrangement, not an insurance product.
    # Florida's direct primary care statute turns on exactly this distinction
    # and requires the agreement to state it in plain terms, so marketing that
    # blurs it is a regulatory exposure, not a wording preference. Whether a
    # given piece needs review is a question for counsel; what PCIP enforces
    # is that the sentence is present.
    MEMBERSHIP_TERMS = (
        "membresía", "membresia", "membership", "direct primary care",
        "atención directa", "atencion directa", "pago directo", "direct pay",
    )
    INSURANCE_TERMS = (
        "seguro médico", "seguro medico", "health insurance", "insurance plan",
        "plan de salud", "aseguranza", "póliza", "poliza", "cobertura médica",
        "cobertura medica", "deducible", "copago", "in-network", "red de",
    )
    # Both the plain phrasing and the §624.27 statutory wording count. The
    # statute says "seguro de salud"; insisting on "seguro médico" would have
    # rejected the exact sentence Florida requires.
    NOT_INSURANCE_ES = ("no es un seguro médico", "no es un seguro de salud")
    NOT_INSURANCE_EN = ("is not health insurance", "is not insurance")

    # Google Business Profile is a different animal from FB/IG/LinkedIn: the
    # practice already lived through one real enforcement incident there
    # (posting disabled ~2026-08-01, most likely a drug name + price + CTA
    # combination). These rules are the re-entry checklist made
    # unconditional, not a style preference.
    GBP_BODY_MIN = 150
    GBP_BODY_MAX = 300
    GBP_MAX_EMOJI = 1
    #: Real, licensed shorthand the practice legitimately uses in caps.
    #: Anything else in all-caps reads as shouting, which GBP's own
    #: reviewers read as a scarcity/urgency signal.
    GBP_ALLOWED_ACRONYMS = frozenset({
        "DOT", "USCIS", "APRN", "MD", "CDL", "PH", "GBP", "FAQ", "NAD",
        "AHCA", "ACA", "NPI", "ER", "ID", "FL", "I-693", "PCIP",
    })
    #: Prescription weight-loss content is banned combined with a price or
    #: CTA everywhere, per the founder's own post-incident policy — treated
    #: as equally off-limits on every channel, not just the one that was
    #: actually disabled.
    RESTRICTED_DRUG_TERMS = (
        "semaglutide", "tirzepatide", "ozempic", "wegovy", "mounjaro",
        "zepbound", "glp-1", "glp1", "peptide", "compounded",
    )

    # Mental-health content must carry crisis numbers.
    CRISIS_TRIGGERS = (
        "suicid", "depres", "crisis de salud mental", "mental health crisis",
        "autolesion", "self-harm",
    )
    CRISIS_NUMBERS = ("988", "911")


@dataclass
class Violation:
    rule: str
    severity: str            # blocker | required | advisory
    detail: str
    fix: str = ""

    def __str__(self) -> str:
        return f"[{self.severity}] {self.rule}: {self.detail}"


@dataclass
class ArticleCheck:
    violations: List[Violation] = field(default_factory=list)

    @property
    def blockers(self) -> List[Violation]:
        return [v for v in self.violations if v.severity == "blocker"]

    @property
    def required(self) -> List[Violation]:
        return [v for v in self.violations if v.severity == "required"]

    @property
    def advisories(self) -> List[Violation]:
        return [v for v in self.violations if v.severity == "advisory"]

    @property
    def passed(self) -> bool:
        """No blockers and nothing required is missing."""
        return not self.blockers and not self.required

    def report(self) -> str:
        if not self.violations:
            return "PH standard: passed."
        lines = [f"PH standard: {len(self.violations)} finding(s)."]
        for v in self.violations:
            lines.append(f"  {v}")
            if v.fix:
                lines.append(f"      → {v.fix}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "blockers": [v.detail for v in self.blockers],
            "required": [v.detail for v in self.required],
            "advisories": [v.detail for v in self.advisories],
        }


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")

_TAG_RE = re.compile(r"<[^>]+>")
_H1_RE = re.compile(r"<h1\b", re.I)
_H2_RE = re.compile(r"<h2\b", re.I)
_IMG_RE = re.compile(r"<img\b", re.I)


#: Sentence boundaries. Negation is scoped to the sentence containing the
#: claim: a fixed word-count lookback missed "No direct care agreement can
#: promise cures" by one word, and "Ningún acuerdo de atención directa puede
#: prometer curas" by three. A clause can put any number of words between the
#: denial and the thing denied; a sentence is the unit that actually governs.
_SENTENCE_SPLIT = re.compile(r"[.!?;\n\u00a1\u00bf]+")

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)
#: A whole word in caps, letters only \u2014 used to flag shouting in GBP copy.
#: Deliberately excludes anything with digits (I-693, 988) or punctuation.
_ALLCAPS_WORD_RE = re.compile(r"\b[A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1]{3,}\b")


def _drug_term_hits(lowered: str) -> List[str]:
    return [t for t in PH.RESTRICTED_DRUG_TERMS if t in lowered]


def claim_hits(text: str) -> List[Tuple[str, str]]:
    """Prohibited claims actually *made* in ``text``, with their context.

    Two things a plain substring scan gets wrong, both of which blocked
    correct copy: it matches inside longer words ("secure", "procura"), and
    it cannot tell a claim from its denial. Each hit comes back with the
    surrounding phrase, because "prohibited claim: 'cure'" with no quote
    leaves the writer hunting through 1,600 words for it.
    """
    # Markup first. A body arrives as HTML, and "<p>No outcome is
    # guaranteed.</p>" tokenises as "<p>no", which is not the word "no" — so
    # the negation check silently failed and blocked the disclaimer. It also
    # meant the quote in the finding was a mouthful of tags.
    text = " ".join(_text_of(text or "").split())
    lowered = text.lower()
    hits: List[Tuple[str, str]] = []
    for claim in PH.FORBIDDEN_CLAIMS:
        # ``s?`` catches the Spanish plural; the gendered forms are listed.
        for match in re.finditer(rf"\b{re.escape(claim)}s?\b", lowered):
            if _negated_in_sentence(lowered, match.start()):
                continue
            start = max(0, match.start() - 45)
            quote = " ".join(text[start : match.end() + 45].split())
            hits.append((claim, quote))
            break
    return hits


def _negated_in_sentence(lowered: str, at: int) -> bool:
    """Whether a denial governs the claim found at ``at``.

    Only text earlier in the same sentence counts. "We do not cut corners.
    We cure diabetes." must still be refused — the denial belongs to the
    previous sentence and says nothing about the claim in this one.
    """
    starts = [m.end() for m in _SENTENCE_SPLIT.finditer(lowered, 0, at)]
    clause = lowered[(starts[-1] if starts else 0) : at]
    return any(
        word.strip(",:¡!¿?()\"\u201c\u201d") in PH.CLAIM_NEGATIONS
        for word in clause.split()
    )


def _text_of(html: str) -> str:
    return _TAG_RE.sub(" ", html or "")


def _words(html: str) -> int:
    return len([w for w in _text_of(html).split() if w.strip()])


def check_article(article: Dict[str, Any], stage: str = "publish") -> ArticleCheck:
    """Validate one article against the PH standard.

    ``article`` carries the shape PCIP's copy step produces: per-language
    ``body_html``/``title``, plus ``meta_title``, ``meta_description``,
    ``faq``, ``alt_texts``, ``featured_image`` and ``keywords``. Optional
    ``verified_amounts`` lists dollar figures the brief itself states, so a
    cited outside statistic is not mistaken for an invented membership price.

    ``stage`` is "draft" while the copy exists but the design has not been
    exported yet, and "publish" once everything is assembled. At the draft
    stage the hero image is reported as advisory rather than required — the
    export step has not run, so demanding it would fail every run before it
    could reach a reviewer. It is required at publish, which is the point where
    its absence would actually reach a reader.
    """
    out = ArticleCheck()
    add = out.violations.append

    bodies: Dict[str, str] = article.get("bodies") or {}
    titles: Dict[str, str] = article.get("titles") or {}

    # ── Bilingual parity ─────────────────────────────────────────────────
    for lang in PH.LANGUAGES:
        if not (bodies.get(lang) or "").strip():
            add(Violation(
                "bilingual_parity", "required",
                f"no {lang.upper()} body — the standard requires an ES/EN pair "
                "with Polylang linking them",
                f"generate the {lang.upper()} version; a Spanish-only article "
                "is half a deliverable",
            ))
        if not (titles.get(lang) or "").strip():
            add(Violation(
                "bilingual_parity", "required",
                f"no {lang.upper()} title", "",
            ))

    # ── Substance ────────────────────────────────────────────────────────
    for lang, body in bodies.items():
        if not body:
            continue
        n = _words(body)
        if n < PH.MIN_BODY_WORDS:
            add(Violation(
                "depth", "required",
                f"{lang.upper()} body is {n} words, below the {PH.MIN_BODY_WORDS} "
                "-word minimum",
                "an article this short reads as a caption and will not rank",
            ))
        if len(_H2_RE.findall(body)) < PH.MIN_H2_SECTIONS:
            add(Violation(
                "structure", "required",
                f"{lang.upper()} body has fewer than {PH.MIN_H2_SECTIONS} H2 sections",
                "a scannable outline is both an SEO and a plain-language need",
            ))
        h1s = len(_H1_RE.findall(body))
        if h1s:
            add(Violation(
                "one_h1", "required",
                f"{lang.upper()} body contains {h1s} <h1> — the post title is the H1",
                "demote in-body headings to <h2>",
            ))

    # ── SEO surface ──────────────────────────────────────────────────────
    meta_title = (article.get("meta_title") or "").strip()
    meta_desc = (article.get("meta_description") or "").strip()
    if not meta_title:
        add(Violation("meta_title", "required", "no meta title", ""))
    elif len(meta_title) > PH.META_TITLE_MAX:
        add(Violation(
            "meta_title", "required",
            f"meta title is {len(meta_title)} characters, over {PH.META_TITLE_MAX}",
            "it will be truncated in results",
        ))
    if meta_title and PH.GEO_PHRASE.lower() not in meta_title.lower():
        add(Violation(
            "geo_in_title", "advisory",
            f"meta title does not carry '{PH.GEO_PHRASE}'",
            "service + geo in the title is the registry rule",
        ))
    if not meta_desc:
        add(Violation("meta_description", "required", "no meta description", ""))
    elif len(meta_desc) > PH.META_DESCRIPTION_MAX:
        add(Violation(
            "meta_description", "required",
            f"meta description is {len(meta_desc)} characters, over "
            f"{PH.META_DESCRIPTION_MAX}", "it will be truncated",
        ))

    faq = article.get("faq") or []
    if len(faq) < PH.MIN_FAQ_ITEMS:
        add(Violation(
            "faq", "required",
            f"{len(faq)} FAQ item(s); the standard expects at least "
            f"{PH.MIN_FAQ_ITEMS}",
            "the FAQ block feeds FAQPage schema and answers real search intent",
        ))

    # ── Visual ───────────────────────────────────────────────────────────
    hero = (article.get("featured_image") or "").strip()
    if hero and not hero.lower().endswith(IMAGE_SUFFIXES):
        add(Violation(
            "featured_image", "advisory" if stage == "draft" else "required",
            f"the exported file is not an image ({hero.rsplit('.', 1)[-1]})",
            "a PDF cannot be a featured image — export a PNG of the design and "
            "keep the PDF as a downloadable handout",
        ))
    if not hero:
        add(Violation(
            "featured_image", "advisory" if stage == "draft" else "required",
            "no featured image",
            "a post without a hero image looks unfinished in the feed and in "
            "search; export a PNG of the design",
        ))
    alt = article.get("alt_texts") or {}
    if isinstance(alt, dict):
        missing = [l for l in PH.LANGUAGES if not (alt.get(l) or "").strip()]
        if missing:
            add(Violation(
                "alt_text", "required",
                "alt text missing for: " + ", ".join(m.upper() for m in missing),
                "image alt text is bilingual per the registry",
            ))
    elif not alt:
        add(Violation("alt_text", "required", "no alt text", ""))

    # ── Canon ────────────────────────────────────────────────────────────
    joined = " ".join(bodies.values())
    if PH.NAP_STREET not in joined or PH.NAP_PHONE_DISPLAY not in joined:
        add(Violation(
            "nap", "blocker",
            "the exact NAP block is not present in the article body",
            f"print it verbatim: {PH.NAP_NAME} | {PH.NAP_STREET}, "
            f"{PH.NAP_CITY}, {PH.NAP_STATE} {PH.NAP_ZIP} | "
            f"{PH.NAP_PHONE_DISPLAY} | {PH.SITE}",
        ))
    if PH.PHYSICIAN not in joined:
        add(Violation(
            "eeat", "required",
            "physician credentials are absent",
            f"E-E-A-T requires {PH.PHYSICIAN} and license {PH.FL_LICENSE} on "
            "clinical pages",
        ))

    lowered = joined.lower()
    for claim, quote in claim_hits(joined):
        add(Violation(
            "claims", "blocker",
            f"prohibited claim or superlative: '{claim}' — \u201c{quote}\u201d",
            "structure/function language only; no outcome guarantees",
        ))
    for term in PH.FORBIDDEN_TOPICS:
        if term in lowered:
            add(Violation(
                "no_pediatrics", "blocker",
                f"pediatric content detected ('{term}')",
                "PassQual Health does not serve pediatrics — remove it entirely",
            ))
            break
    if any(t in lowered for t in PH.CRISIS_TRIGGERS):
        if not all(n in joined for n in PH.CRISIS_NUMBERS):
            add(Violation(
                "crisis_numbers", "blocker",
                "mental-health content without 988 and 911",
                "both numbers are mandatory on mental-health topics",
            ))
    for violation in _membership_violations(lowered):
        add(violation)
    for violation in _membership_facts(joined, article.get("verified_amounts")):
        add(violation)
    drug_terms = _drug_term_hits(lowered)
    if drug_terms:
        add(Violation(
            "restricted_drug_term", "blocker",
            f"names a prescription weight-loss drug/class: {', '.join(drug_terms)}",
            "describe weight loss only as physician-supervised medical "
            "weight management under Dr. Barroso Perez — no drug name, "
            "dose, or price, on any channel",
        ))

    # ── Conversion ───────────────────────────────────────────────────────
    if PH.NAP_PHONE_SOCIAL not in joined and PH.NAP_PHONE_DISPLAY not in joined:
        add(Violation("cta", "required", "no booking CTA with the phone number", ""))
    if PH.NEAR_ME_ES not in lowered:
        add(Violation(
            "near_me", "advisory",
            f"no '{PH.NEAR_ME_ES}' phrasing",
            "Spanish speakers search near-me intent, not city names",
        ))

    return out


def _membership_facts(
    text: str,
    verified_amounts: Optional[Iterable[int]] = None,
) -> List[Violation]:
    """Imported late: membership.py imports PH, so the reverse cannot be
    a module-level import."""
    from pcip.standards.membership import check_membership_facts

    return check_membership_facts(text, verified_amounts)


def _membership_violations(lowered: str) -> List[Violation]:
    """The membership is not insurance, and content must not imply it is.

    Shared by the article and social checks because a caption reaches a
    prospective patient exactly as an article does, and the claim that gets a
    practice in trouble is the same one in both places.
    """
    if not any(t in lowered for t in PH.MEMBERSHIP_TERMS):
        return []

    disclaimed = any(
        phrase in lowered
        for phrase in PH.NOT_INSURANCE_ES + PH.NOT_INSURANCE_EN
    )
    if disclaimed:
        return []

    insurance_language = [t for t in PH.INSURANCE_TERMS if t in lowered]
    fix = (
        f'state it plainly: "{PH.BRAND} Membership {PH.NOT_INSURANCE_EN[0]}" / '
        f'"La Membresía de {PH.BRAND} {PH.NOT_INSURANCE_ES[0]}" — or carry '
        "the §624.27 statutory notice verbatim"
    )
    if insurance_language:
        return [Violation(
            "not_insurance", "blocker",
            "the membership is described alongside insurance language "
            f"({', '.join(insurance_language[:3])}) with no statement that it "
            "is not insurance",
            fix,
        )]
    return [Violation(
        "not_insurance", "required",
        "membership content without the not-insurance statement",
        fix,
    )]


def _gbp_violations(
    post: Dict[str, Any], caption: str, language: str
) -> List[Violation]:
    """GBP's own re-entry rules, made unconditional rather than advisory.

    Distilled from ``GBP-post-compliance-audit.md``, written after Google
    disabled posting on this exact listing (~2026-08-01). Every rule here
    traces to that incident or to GBP's documented content policy, not to
    style preference — this is the checklist a human would run by hand
    before every post, encoded so a scheduled run can't skip it.
    """
    violations: List[Violation] = []
    n = len(caption)
    if n and not (PH.GBP_BODY_MIN <= n <= PH.GBP_BODY_MAX):
        violations.append(Violation(
            "gbp_length", "required",
            f"{n} characters; GBP body copy should be "
            f"{PH.GBP_BODY_MIN}-{PH.GBP_BODY_MAX}",
            "trim or expand to the recommended range — GBP truncates long "
            "posts and a very short one reads as thin",
        ))
    if any(p in caption for p in
           (PH.NAP_PHONE_SOCIAL, PH.NAP_PHONE_DISPLAY, PH.NAP_PHONE_E164,
            PH.SITE)):
        violations.append(Violation(
            "gbp_cta_in_body", "blocker",
            "phone number or URL is in the post body",
            "GBP puts the phone/link in the Call/Book/Learn-more button, "
            "never in body text — pass cta_type/cta_url instead of writing "
            "them into the caption",
        ))
    # No "CTA button configured" check here: GBPAdapter always attaches one
    # (defaulting to CALL with the practice's real number, which needs no
    # extra data), so the only genuine content-level risk is the phone/URL
    # leaking into the body text above — a missing button is a transport
    # failure the adapter itself refuses on (ChannelNotConfigured).
    post_type = str(post.get("post_type") or "Update")
    if post_type.lower() == "offer" and not post.get("has_dated_discount"):
        violations.append(Violation(
            "gbp_post_type", "blocker",
            "post_type is Offer without a real, dated discount",
            "use Update — Offer is reserved for an actual time-boxed "
            "discount, which this practice does not run",
        ))
    emoji_count = len(_EMOJI_RE.findall(caption))
    if emoji_count > PH.GBP_MAX_EMOJI:
        violations.append(Violation(
            "gbp_emoji", "advisory",
            f"{emoji_count} emoji; GBP re-entry guidance caps it at "
            f"{PH.GBP_MAX_EMOJI}",
            "keep it to zero or one",
        ))
    shouting = [
        w for w in _ALLCAPS_WORD_RE.findall(caption)
        if w.upper() not in PH.GBP_ALLOWED_ACRONYMS
    ]
    if shouting:
        violations.append(Violation(
            "gbp_allcaps", "advisory",
            f"all-caps word(s) that are not recognized acronyms: {', '.join(shouting)}",
            "GBP reviewers read unfamiliar all-caps as urgency/scarcity language",
        ))
    return violations


def check_social_post(
    post: Dict[str, Any], *, limit: Optional[int] = None
) -> ArticleCheck:
    """The PassQual Health standard as it applies to a social caption.

    ``check_article`` cannot be reused here: it requires an ES/EN pair, 600+
    words, three H2 sections, an FAQ block and the verbatim NAP line. No
    caption can satisfy that, so running it on social posts made every social
    channel unpublishable — a gate that never permits anything is not a
    standard, it is an outage.

    What survives the move to social is the part that carries risk rather
    than the part that carries SEO: the exclusions PassQual Health states
    without exception, the crisis numbers, and the booking route back to the
    practice.
    """
    violations: List[Violation] = []
    caption = str(post.get("caption") or "")
    channel = str(post.get("channel") or "").lower()
    media = list(post.get("media") or [])
    language = str(post.get("language") or PH.PRIMARY_LANGUAGE).lower()
    lowered = caption.lower()

    if not caption.strip():
        violations.append(Violation(
            "empty_caption", "blocker", "the caption is empty",
            "pass --text, or re-run the pipeline so its copy step produces "
            "a caption for this channel",
        ))

    # ── Exclusions that hold on every surface ────────────────────────────
    for term in PH.FORBIDDEN_TOPICS:
        if term in lowered:
            violations.append(Violation(
                "no_pediatrics", "blocker",
                f"pediatric content detected ('{term}')",
                "PassQual Health does not serve pediatrics — remove it entirely",
            ))
            break
    for claim, quote in claim_hits(caption):
        violations.append(Violation(
            "claims", "blocker",
            f"prohibited claim or superlative: '{claim}' — \u201c{quote}\u201d",
            "structure/function language only; no outcome guarantees",
        ))
    if any(t in lowered for t in PH.CRISIS_TRIGGERS):
        if not all(n in caption for n in PH.CRISIS_NUMBERS):
            violations.append(Violation(
                "crisis_numbers", "blocker",
                "mental-health content without 988 and 911",
                "both numbers are mandatory on mental-health topics — a "
                "caption reaches someone in crisis the same way an article does",
            ))

    violations.extend(_membership_violations(lowered))
    violations.extend(_membership_facts(caption))
    drug_terms = _drug_term_hits(lowered)
    if drug_terms:
        violations.append(Violation(
            "restricted_drug_term", "blocker",
            f"names a prescription weight-loss drug/class: {', '.join(drug_terms)}",
            "describe weight loss only as physician-supervised medical "
            "weight management under Dr. Barroso Perez — no drug name, "
            "dose, or price, on any channel",
        ))

    # ── Reach and conversion ─────────────────────────────────────────────
    if limit is not None and len(caption) > limit:
        violations.append(Violation(
            "caption_length", "required",
            f"{len(caption)} characters; {channel or 'this channel'} accepts {limit}",
            "write a channel-specific caption rather than reusing the article",
        ))
    if channel == "gbp":
        violations.extend(_gbp_violations(post, caption, language))
    elif not any(p in caption for p in
                 (PH.NAP_PHONE_SOCIAL, PH.NAP_PHONE_DISPLAY, PH.SITE)):
        violations.append(Violation(
            "cta", "required",
            "no route back to the practice",
            f"end with {PH.BOOKING_ES if language.startswith('es') else PH.BOOKING_EN} "
            f"or a link to {PH.SITE}",
        ))
    if channel in ("instagram", "tiktok", "youtube") and not media:
        violations.append(Violation(
            "media", "required",
            f"{channel} is a media-first channel and no media was given",
            "attach the exported design or video",
        ))
    if language.startswith("es") and PH.NEAR_ME_ES not in lowered:
        violations.append(Violation(
            "near_me", "advisory", "no 'cerca de mí' phrasing",
            "Spanish speakers search near-me intent, not city names",
        ))
    if "#" not in caption:
        violations.append(Violation(
            "hashtags", "advisory", "no hashtags",
            "hashtags are how a local practice is found on social",
        ))
    return ArticleCheck(violations=violations)
