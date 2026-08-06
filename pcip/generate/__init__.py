"""AI generation: copy, images, and video orchestrated alongside Canva.

Importing this package registers every built-in provider (Claude copy,
Canva design, and the image/video vendor pool in media_providers)."""

from pcip.generate import media_providers  # noqa: F401 — registers vendors
from pcip.generate.capabilities import (
    CapabilityRegistry,
    MediaSpec,
    default_registry,
    spec_for,
)
from pcip.generate.orchestrator import GenerationOrchestrator
from pcip.generate.providers import ProviderRegistry, register_provider

__all__ = [
    "GenerationOrchestrator",
    "ProviderRegistry",
    "register_provider",
    "CapabilityRegistry",
    "MediaSpec",
    "default_registry",
    "spec_for",
]
