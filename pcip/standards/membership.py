"""The PassQual Membership, as the signed agreement defines it.

Sourced from *PassQual Membership Agreement v2.0* — the executed §624.27
Direct Health Care Agreement — not from the pricing deck, which is marked
"illustrative model, confirm final rates". When the two disagree the contract
wins, because it is the document a member signs.

Everything here exists so that no run can invent it. A model asked to write
about a product it has no facts for will produce plausible ones, and a
plausible wrong price on a medical practice's website is a promise the
practice did not make.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from pcip.standards.ph import PH, Violation


class MEMBERSHIP:
    """Canonical facts. Never paraphrase a number or a term."""

    NAME = "PassQual Membership"
    TAGLINE_EN = "Health Without Limits"
    TAGLINE_ES = "Salud Sin Límites"

    #: Tier → monthly fee, exactly as the enrollment form lists them.
    TIERS: Dict[str, int] = {"Core Care": 79, "Plus Care": 119, "Elite Care": 159}

    #: Every dollar figure the agreement and its schedule actually state.
    #: Anything else in membership copy is unverified and must not ship.
    STATED_AMOUNTS = frozenset({
        79, 119, 159,              # monthly, by tier
        790, 1190, 1590,           # annual prepay, by tier
        99,                        # one-time cancellation fee
        200, 300, 400,             # single non-member visit, by tier level
    })

    TERMS = ("6-Month · billed monthly", "12-Month Annual · prepaid, ~2 months free")
    CANCELLATION_NOTICE_DAYS = 30
    CANCELLATION_FEE = 99
    FINANCING = "CareCredit"

    #: Included at every tier.
    INCLUDED_ALL_TIERS = (
        "primary and preventive visits — office, telehealth and messaging",
        "comprehensive annual physical",
        "same/next-day priority with a bilingual care team",
        "routine labs",
        "one X-ray when clinically needed",
    )

    #: Section 9, verbatim in substance. Publishing the membership without
    #: these is how a patient discovers the limit at the worst moment.
    NOT_COVERED = (
        "emergency care",
        "hospitalization",
        "specialist care",
        "prescription drug coverage",
        "third-party services",
        "specialty and chronic-disease medications (member price)",
    )

    #: Section 2. The membership is offered ONLY to self-pay patients with no
    #: active coverage — enrollment is refused when eligibility checks find
    #: any. Marketing that invites insured readers to join sends them to a
    #: front desk that must turn them away.
    ELIGIBILITY = (
        "self-pay patients with no active Medicare, Medicaid, marketplace, "
        "employer or commercial coverage for the covered services"
    )

    #: §624.27 statutory text. Reproduced exactly; the agreement marks it
    #: DO NOT ALTER, and it is the sentence that makes the arrangement lawful
    #: to sell.
    STATUTORY_NOTICE_EN = (
        "This agreement is not health insurance and the health care provider "
        "will not file any claims against the patient's health insurance "
        "policy or plan for reimbursement of any health care services covered "
        "by the agreement. This agreement does not qualify as minimum "
        "essential coverage to satisfy the individual shared responsibility "
        "provision of the Patient Protection and Affordable Care Act, "
        "26 U.S.C. s. 5000A. This agreement is not workers' compensation "
        "insurance and does not replace an employer's obligations under "
        "chapter 440."
    )
    STATUTORY_NOTICE_ES = (
        "Este acuerdo no es un seguro de salud y el proveedor de atención "
        "médica no presentará ninguna reclamación a la póliza o plan de "
        "seguro de salud del paciente por el reembolso de los servicios "
        "cubiertos por este acuerdo. Este acuerdo no califica como cobertura "
        "esencial mínima conforme a la ley ACA (26 U.S.C. s. 5000A). No es un "
        "seguro de compensación laboral y no reemplaza las obligaciones del "
        "empleador bajo el capítulo 440."
    )

    STATUTE = "§624.27, Florida Statutes"
    AGREEMENT_VERSION = "v2.0"


_MONEY = re.compile(r"\$\s?([0-9][0-9,]*)")


def stated_amounts(text: str) -> List[int]:
    """Every dollar figure in ``text``, as integers."""
    out = []
    for raw in _MONEY.findall(text or ""):
        try:
            out.append(int(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def check_membership_facts(text: str) -> List[Violation]:
    """Refuse membership copy that states a figure the agreement does not.

    The single most likely failure when a model writes about a priced product
    is a confident, invented number. This does not try to judge whether the
    copy is *persuasive* — only whether every price in it is one the practice
    actually charges.
    """
    lowered = (text or "").lower()
    if not any(t in lowered for t in PH.MEMBERSHIP_TERMS):
        return []

    violations: List[Violation] = []
    unverified = sorted(
        {a for a in stated_amounts(text) if a not in MEMBERSHIP.STATED_AMOUNTS}
    )
    if unverified:
        listed = ", ".join(f"${a}" for a in unverified)
        violations.append(Violation(
            "unverified_price", "blocker",
            f"price(s) the membership agreement does not state: {listed}",
            "the agreement states $79 / $119 / $159 monthly ($790 / $1,190 / "
            "$1,590 annual) and a $99 cancellation fee — use those or none",
        ))

    if not any(w in lowered for w in ("no cubre", "not covered", "no incluye",
                                      "does not cover", "excluye", "excludes")):
        violations.append(Violation(
            "coverage_limits", "required",
            "membership content without its limits",
            "name what is not covered — emergency care, hospitalization, "
            "specialist care and prescription drug coverage — so a member "
            "does not discover the limit at the worst moment",
        ))

    if not any(w in lowered for w in
               ("sin seguro", "self-pay", "no active coverage", "sin cobertura",
                "without coverage", "pago directo")):
        violations.append(Violation(
            "eligibility", "required",
            "membership content that does not say who is eligible",
            f"the membership is for {MEMBERSHIP.ELIGIBILITY} — copy that "
            "invites insured readers sends them to a front desk that must "
            "turn them away",
        ))
    return violations
