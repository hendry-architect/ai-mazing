"""Licensing policy engine.

PCIP's hard rule: premium content moves only through Canva-supported
workflows. Concretely —

- Canva Pro/premium stock, elements, fonts, and music are used *inside*
  Canva designs and leave Canva only via the official export API, which is
  the supported workflow that applies the org's Pro entitlements.
- PCIP never scrapes, screenshots, watermark-strips, or otherwise extracts
  a premium asset as a standalone file. ``check_action`` refuses those
  actions and there is deliberately no code path in the platform that
  performs them.
- Every asset carries a License record; the publish router refuses to
  publish outputs whose license cannot be established.

This module is pure policy — no network calls — so it is fully unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from pcip.models import Asset, License, LicenseType


class LicensingError(Exception):
    """An action was blocked by licensing policy."""


# Actions PCIP will never perform on premium/third-party content.
PROHIBITED_ACTIONS = frozenset(
    {
        "extract_standalone",      # pull a premium asset out of Canva as its own file
        "strip_watermark",
        "scrape",
        "screenshot_capture",      # capture-to-bypass-license
        "redistribute_raw",        # hand the raw premium file to a third party
    }
)

# Actions that are always the supported path.
SUPPORTED_ACTIONS = frozenset(
    {
        "use_in_design",           # place the asset inside a Canva design
        "export_design",           # export the *design* via the Canva export API
        "autofill_template",       # brand-template autofill via the API
        "resize_design",
        "publish_export",          # publish a Canva-exported deliverable
    }
)


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str

    def __bool__(self) -> bool:  # allows `if policy.check(...)`
        return self.allowed


class LicensePolicy:
    """Evaluates whether an action on an asset is within licensing policy."""

    def check_action(self, action: str, asset: Asset) -> PolicyDecision:
        lic = asset.license
        if action in PROHIBITED_ACTIONS:
            return PolicyDecision(
                False,
                f"'{action}' is never permitted by PCIP policy "
                f"(asset {asset.id}, license {lic.type.value}). Premium and "
                "third-party content may only leave Canva through supported "
                "export workflows.",
            )
        if action in SUPPORTED_ACTIONS:
            if lic.type == LicenseType.UNKNOWN and action == "publish_export":
                return PolicyDecision(
                    False,
                    f"Asset {asset.id} has no established license. Sync it "
                    "from Canva or record a license before publishing.",
                )
            return PolicyDecision(True, f"'{action}' is a supported workflow.")
        # Unknown action: default-deny for premium/third-party, allow for owned.
        if lic.type in (LicenseType.OWNED, LicenseType.AI_GENERATED):
            return PolicyDecision(True, "Org-owned asset; action permitted.")
        return PolicyDecision(
            False,
            f"Unrecognized action '{action}' on {lic.type.value} content is "
            "denied by default. Use a supported workflow: "
            + ", ".join(sorted(SUPPORTED_ACTIONS)),
        )

    def check_publish(self, assets: Iterable[Asset]) -> PolicyDecision:
        """Gate a publish: every asset in the deliverable must clear policy.

        A deliverable exported from Canva (the design export) is publishable
        even when it *contains* premium elements — that is exactly the
        supported workflow. What must never happen is publishing a premium
        element as a standalone file, which surfaces here as an asset whose
        license is CANVA_PRO/THIRD_PARTY but which was not produced by a
        design export (metadata flag ``via_export``).
        """
        problems: List[str] = []
        for a in assets:
            lic = a.license.type
            if lic == LicenseType.UNKNOWN:
                problems.append(f"{a.id} ({a.name or 'unnamed'}): license unknown")
            elif lic in (LicenseType.CANVA_PRO, LicenseType.CANVA_FREE):
                if not a.metadata.get("via_export"):
                    problems.append(
                        f"{a.id} ({a.name or 'unnamed'}): Canva {lic.value} "
                        "content may only be published as part of a design "
                        "exported through the Canva export API"
                    )
            elif lic == LicenseType.THIRD_PARTY and not a.license.terms_url:
                problems.append(
                    f"{a.id} ({a.name or 'unnamed'}): third-party asset has "
                    "no license terms on record"
                )
        if problems:
            return PolicyDecision(False, "Publish blocked: " + "; ".join(problems))
        return PolicyDecision(True, "All assets clear licensing policy.")

    # ── Convenience constructors for correctly-licensed assets ───────────

    @staticmethod
    def canva_export_license(pro: bool = True) -> License:
        return License(
            type=LicenseType.CANVA_PRO if pro else LicenseType.CANVA_FREE,
            source="canva",
            terms_url="https://www.canva.com/policies/content-license-agreement/",
            notes="Exported via Canva Connect export API (supported workflow).",
        )

    @staticmethod
    def ai_license(provider: str, terms_url: str = "") -> License:
        return License(
            type=LicenseType.AI_GENERATED,
            source=provider,
            terms_url=terms_url,
            notes=f"Generated for the org via {provider}.",
        )

    def require(self, action: str, asset: Asset) -> None:
        """Raise LicensingError if the action is not permitted."""
        decision = self.check_action(action, asset)
        if not decision.allowed:
            raise LicensingError(decision.reason)
