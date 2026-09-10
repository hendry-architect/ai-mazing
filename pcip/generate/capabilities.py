"""Capability registry and media planner.

Decision #1 of the platform architecture: orchestration never asks for a
vendor by name. A pipeline asks for *capabilities* —

    "1080×1920 vertical video, under 15 seconds, photorealistic,
     commercial license"

— and the registry selects the best provider that currently satisfies them.
When a better model ships, you update a ProviderProfile (or register a new
provider); business logic never changes.

Two layers live here:

- ``MediaSpec``          — a vendor-neutral statement of what is needed.
- ``CapabilityRegistry`` — scores every available provider's profile against
  a spec and returns the ranked candidates.

``CONTENT_PRESETS`` maps the planner's content types (healthcare_photo,
infographic, social_quote, cinematic_video, quick_reel, …) onto specs, so
pipelines can say ``spec_for("healthcare_photo")`` and stay declarative.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple


@dataclass
class MediaSpec:
    """A vendor-neutral requirement for a generated visual."""

    modality: str                      # "image" | "video"
    width: int = 0                     # 0 = no constraint
    height: int = 0
    duration_s: float = 0.0            # video only; 0 = no constraint
    style: str = ""                    # photorealistic | infographic | typography |
                                       # cinematic | stylized | social | general
    text_in_image: bool = False        # typography must render crisply
    license: str = "commercial"        # commercial | any
    quality: str = "standard"          # standard | premium

    @property
    def vertical(self) -> bool:
        return bool(self.width and self.height and self.height > self.width)


@dataclass
class ProviderProfile:
    """What one provider is good at. Scores are 0..1; update these as models
    improve — this table, not business logic, is where vendor knowledge lives."""

    name: str
    modality: str
    strengths: Dict[str, float] = field(default_factory=dict)   # style → score
    text_rendering: float = 0.0        # quality of text inside images
    max_duration_s: float = 0.0        # video: longest clip (0 = n/a)
    commercial_license: bool = True
    default_score: float = 0.5         # score for styles not listed
    roles: Tuple[str, ...] = ()        # documentation: "default", "premium", ...


class NoCapableProvider(Exception):
    """No available provider satisfies the requested capabilities."""


class CapabilityRegistry:
    """Ranks provider profiles against a MediaSpec.

    Hard constraints (modality, duration ceiling, license) eliminate;
    soft scores (style strength, text rendering, default priority) rank.
    """

    def __init__(self) -> None:
        self._profiles: Dict[str, ProviderProfile] = {}

    def register(self, profile: ProviderProfile) -> None:
        self._profiles[profile.name] = profile

    def profile(self, name: str) -> Optional[ProviderProfile]:
        return self._profiles.get(name)

    def score(self, profile: ProviderProfile, spec: MediaSpec) -> float:
        """-1 = eliminated by a hard constraint; otherwise 0..2 ranking score."""
        if profile.modality != spec.modality:
            return -1.0
        if spec.license == "commercial" and not profile.commercial_license:
            return -1.0
        if (
            spec.modality == "video"
            and spec.duration_s
            and profile.max_duration_s
            and spec.duration_s > profile.max_duration_s
        ):
            return -1.0

        score = profile.strengths.get(spec.style, profile.default_score)
        if spec.text_in_image:
            # Text quality becomes decisive when the spec demands it.
            score = 0.4 * score + 0.6 * profile.text_rendering
        if spec.quality == "premium":
            score += 0.1 * max(profile.strengths.values(), default=0.0)
        return score

    def rank(
        self, spec: MediaSpec, available: Optional[List[str]] = None
    ) -> List[Tuple[str, float]]:
        """All capable providers, best first. ``available`` restricts to
        providers that currently have credentials configured."""
        candidates = []
        for name, profile in self._profiles.items():
            if available is not None and name not in available:
                continue
            s = self.score(profile, spec)
            if s >= 0:
                candidates.append((name, s))
        return sorted(candidates, key=lambda kv: kv[1], reverse=True)

    def select(self, spec: MediaSpec, available: Optional[List[str]] = None) -> str:
        ranked = self.rank(spec, available)
        if not ranked:
            raise NoCapableProvider(
                f"No available provider satisfies {spec}. "
                f"Registered: {sorted(self._profiles)}; "
                f"configured: {sorted(available or [])}."
            )
        return ranked[0][0]


# ─── The platform's current vendor knowledge ─────────────────────────────────
# Chief-architect decisions, encoded as data:
#   images — OpenAI as default, Imagen for photorealism, Ideogram for
#            typography, Flux for the self-host/open ecosystem;
#   video  — Veo as premium default, Runway as production fallback,
#            Pika for fast social clips, Luma for stylized motion.

DEFAULT_PROFILES: List[ProviderProfile] = [
    ProviderProfile(
        # Imagery from the Canva subscription the account already pays for.
        # Ranked below every API provider on purpose: it needs an agent session
        # to service the handoff, so it cannot serve an unattended run. When
        # nothing else is configured it is the difference between imagery and
        # none, at no additional cost.
        name="canva-images", modality="image",
        roles=("brand", "no_extra_cost"),
        strengths={"photorealistic": 0.6, "general": 0.6, "social": 0.6,
                   "infographic": 0.5, "typography": 0.7, "stylized": 0.5},
        text_rendering=0.9,          # text set in Canva, not rendered by a model
        default_score=0.45,
    ),
    ProviderProfile(
        name="openai-images", modality="image", roles=("default", "editing"),
        strengths={"infographic": 0.9, "general": 0.85, "social": 0.8,
                   "photorealistic": 0.75, "stylized": 0.75},
        text_rendering=0.75, default_score=0.8,
    ),
    ProviderProfile(
        name="imagen", modality="image", roles=("photorealism",),
        strengths={"photorealistic": 0.95, "general": 0.7},
        text_rendering=0.55, default_score=0.6,
    ),
    ProviderProfile(
        name="ideogram", modality="image", roles=("typography",),
        strengths={"typography": 0.98, "social": 0.75},
        text_rendering=0.98, default_score=0.4,
    ),
    ProviderProfile(
        name="flux", modality="image", roles=("self-host",),
        strengths={"stylized": 0.85, "photorealistic": 0.8},
        text_rendering=0.5, default_score=0.35,
    ),
    ProviderProfile(
        name="veo", modality="video", roles=("premium",),
        strengths={"cinematic": 0.95, "photorealistic": 0.9, "general": 0.8},
        max_duration_s=60, default_score=0.7,
    ),
    ProviderProfile(
        name="runway", modality="video", roles=("production",),
        strengths={"cinematic": 0.8, "general": 0.8, "social": 0.75},
        max_duration_s=30, default_score=0.65,
    ),
    ProviderProfile(
        name="pika", modality="video", roles=("fast-social",),
        strengths={"social": 0.85, "stylized": 0.7},
        max_duration_s=15, default_score=0.5,
    ),
    ProviderProfile(
        name="luma", modality="video", roles=("creative-motion",),
        strengths={"stylized": 0.9, "cinematic": 0.75},
        max_duration_s=20, default_score=0.45,
    ),
]


def default_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for p in DEFAULT_PROFILES:
        reg.register(p)
    return reg


# ─── Content-type presets (the media planner's vocabulary) ───────────────────

CONTENT_PRESETS: Dict[str, MediaSpec] = {
    "healthcare_photo": MediaSpec(
        modality="image", style="photorealistic", quality="premium"
    ),
    "infographic": MediaSpec(modality="image", style="infographic"),
    "social_quote": MediaSpec(
        modality="image", style="typography", text_in_image=True,
        width=1080, height=1350,
    ),
    "blog_hero": MediaSpec(modality="image", style="general", width=1600, height=900),
    "cinematic_video": MediaSpec(
        modality="video", style="cinematic", quality="premium", duration_s=30,
    ),
    "quick_reel": MediaSpec(
        modality="video", style="social", width=1080, height=1920, duration_s=15,
    ),
    "stylized_motion": MediaSpec(modality="video", style="stylized", duration_s=10),
}


def spec_for(content_type: str, **overrides) -> MediaSpec:
    """Preset spec for a planner content type, with optional field overrides."""
    if content_type not in CONTENT_PRESETS:
        raise KeyError(
            f"Unknown content type '{content_type}'. "
            f"Available: {', '.join(sorted(CONTENT_PRESETS))}"
        )
    return replace(CONTENT_PRESETS[content_type], **overrides)
