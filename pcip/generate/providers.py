"""Generation provider registry.

PCIP treats every generator — Claude for copy, any image model, any video
model, and Canva's own design generation — as a pluggable provider behind a
common interface. Add a provider by subclassing GenerationProvider and
registering it; pipelines pick providers by capability, not by vendor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from pcip.config import PCIPConfig
from pcip.licensing import LicensePolicy
from pcip.models import Asset


@dataclass
class GenerationRequest:
    capability: str                    # "copy" | "image" | "video" | "design"
    prompt: str
    brand: str = "PassQual"
    language: str = "en"
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    provider: str
    capability: str
    text: str = ""                     # for copy
    assets: List[Asset] = field(default_factory=list)  # for image/video/design
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProviderNotConfigured(Exception):
    """The selected provider has no credentials / is not available."""


class GenerationProvider(ABC):
    """One generation backend (Claude, an image model, Canva AI, ...)."""

    name: str = "base"
    capabilities: List[str] = []

    def __init__(self, config: PCIPConfig) -> None:
        self.cfg = config

    @abstractmethod
    def available(self) -> bool:
        """Whether this provider is configured and usable right now."""

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Run one generation. Must attach a proper License to any assets."""


class ProviderRegistry:
    """Resolves a capability ("image") to the first available provider."""

    _classes: List[Type[GenerationProvider]] = []

    @classmethod
    def register(cls, provider_cls: Type[GenerationProvider]) -> Type[GenerationProvider]:
        if provider_cls not in cls._classes:
            cls._classes.append(provider_cls)
        return provider_cls

    def __init__(self, config: PCIPConfig) -> None:
        self.cfg = config
        self._instances = [c(config) for c in self._classes]

    def for_capability(self, capability: str) -> GenerationProvider:
        for p in self._instances:
            if capability in p.capabilities and p.available():
                return p
        configured = [
            f"{p.name}({','.join(p.capabilities)})"
            for p in self._instances
            if p.available()
        ]
        raise ProviderNotConfigured(
            f"No provider available for capability '{capability}'. "
            f"Configured providers: {configured or 'none'}. "
            "Add credentials in .env (see .env.example) or register a provider."
        )

    def by_name(self, name: str) -> GenerationProvider:
        for p in self._instances:
            if p.name == name:
                return p
        raise ProviderNotConfigured(f"No provider named '{name}' is registered.")

    def available_names(self, capability: str) -> List[str]:
        """Names of configured providers offering a capability — the pool the
        capability registry routes across."""
        return [
            p.name for p in self._instances
            if capability in p.capabilities and p.available()
        ]

    def status(self) -> Dict[str, Any]:
        return {
            p.name: {"capabilities": p.capabilities, "available": p.available()}
            for p in self._instances
        }


def register_provider(cls: Type[GenerationProvider]) -> Type[GenerationProvider]:
    return ProviderRegistry.register(cls)


# ─── Built-in providers ──────────────────────────────────────────────────────


@register_provider
class ClaudeCopyProvider(GenerationProvider):
    """Copy, captions, hashtags, scripts, and alt-text via the Claude API."""

    name = "claude"
    capabilities = ["copy"]

    def available(self) -> bool:
        # Any of: API key, auth token, `ant auth login` profile, or federation.
        return bool(self.cfg.anthropic_auth_source)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            import anthropic  # lazy: platform works without it until copy is needed
        except ImportError as exc:
            raise ProviderNotConfigured(
                "The 'anthropic' package is not installed (pip install anthropic)."
            ) from exc
        # Pass the key only when we actually have one: a zero-arg client lets
        # the SDK use a stored profile, and an explicit empty key shadows it.
        client = (
            anthropic.Anthropic(api_key=self.cfg.anthropic_api_key)
            if self.cfg.anthropic_api_key
            else anthropic.Anthropic()
        )
        system = (
            f"You are the senior brand copywriter for {request.brand}, a "
            "physician-led healthcare organization. Write in the requested "
            "language ({lang}). Medical content must be accurate, "
            "plain-language, and free of diagnostic or treatment claims that "
            "would require clinician review — flag anything that needs "
            "medical sign-off with [MEDICAL-REVIEW]."
        ).format(lang=request.language)
        # Streaming, not create(): a bilingual article at the PH standard is
        # ~1200 words plus a structured block, and the SDK refuses a
        # non-streaming request whose max_tokens implies it could run past the
        # 10-minute HTTP limit. Streaming removes the timeout concern, so the
        # ceiling can be generous — a truncated response parses as "no fields"
        # and fails the standard for the wrong reason.
        with client.messages.stream(
            model=self.cfg.anthropic_model,
            max_tokens=request.params.get("max_tokens", 64000),
            system=system,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": request.prompt}],
        ) as stream:
            msg = stream.get_final_message()

        if getattr(msg, "stop_reason", "") == "max_tokens":
            raise RuntimeError(
                "The copy generation hit its token ceiling and was cut off "
                "mid-article. Raise max_tokens, or narrow the brief."
            )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return GenerationResult(
            provider=self.name,
            capability="copy",
            text=text,
            metadata={"model": self.cfg.anthropic_model,
                      "auth": self.cfg.anthropic_auth_source},
        )


@register_provider
class CanvaDesignProvider(GenerationProvider):
    """Canva-native generation: brand-template autofill (and, where enabled
    on the account, Canva's own AI design generation via the Connect API)."""

    name = "canva"
    capabilities = ["design"]

    def available(self) -> bool:
        return bool(self.cfg.canva_access_token or self.cfg.canva_refresh_token)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        from pcip.connectors.canva import CanvaClient

        client = CanvaClient(self.cfg)
        template_id = request.params.get("brand_template_id", "")
        if not template_id:
            raise ProviderNotConfigured(
                "CanvaDesignProvider needs params.brand_template_id "
                "(use `pcip search --kind brand_template` to find one)."
            )
        design = client.autofill(
            template_id,
            data=request.params.get("data", {}),
            title=request.params.get("title", request.prompt[:80]),
        )
        asset = Asset(
            name=design.get("title", ""),
            kind="design",
            canva_id=design.get("id", ""),
            url=(design.get("urls") or {}).get("view_url", ""),
            license=LicensePolicy.canva_export_license(pro=True),
            metadata={"canva_design": design, "brand_template_id": template_id},
        )
        return GenerationResult(
            provider=self.name, capability="design", assets=[asset]
        )


# Image/video vendor implementations live in pcip/generate/media_providers.py
# (OpenAI Images, Imagen, Ideogram, Flux; Veo, Runway, Pika, Luma) and are
# selected by capability, never by name — see pcip/generate/capabilities.py.
