"""Generation orchestrator.

Takes a creative Brief and coordinates copy, image, video, and Canva design
generation through the provider registry, registering every output (with its
license) in the knowledge graph so nothing generated is ever untracked.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pcip.config import PCIPConfig
from pcip.generate.capabilities import (
    CapabilityRegistry,
    MediaSpec,
    default_registry,
    spec_for,
)
from pcip.generate.providers import (
    GenerationRequest,
    GenerationResult,
    ProviderNotConfigured,
    ProviderRegistry,
)
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief, EdgeKind, NodeKind


class GenerationOrchestrator:
    def __init__(
        self,
        config: PCIPConfig,
        graph: KnowledgeGraph,
        capability_registry: Optional[CapabilityRegistry] = None,
    ) -> None:
        self.cfg = config
        self.graph = graph
        self.registry = ProviderRegistry(config)
        self.capabilities = capability_registry or default_registry()

    # ── Brief registration ───────────────────────────────────────────────

    def register_brief(self, brief: Brief) -> str:
        self.graph.upsert_node(
            brief.id, NodeKind.BRIEF, brief.title, brief.to_dict()
        )
        for topic in brief.topics:
            topic_id = f"topic:{topic.lower().strip().replace(' ', '-')}"
            self.graph.upsert_node(topic_id, NodeKind.TOPIC, topic)
            self.graph.add_edge(brief.id, EdgeKind.ABOUT, topic_id)
        brand_id = f"brand:{brief.brand.lower().replace(' ', '-')}"
        self.graph.upsert_node(brand_id, NodeKind.BRAND, brief.brand)
        self.graph.add_edge(brief.id, EdgeKind.ON_BRAND, brand_id)
        return brief.id

    # ── Generation ───────────────────────────────────────────────────────

    def generate(
        self,
        capability: str,
        prompt: str,
        brief: Optional[Brief] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        request = GenerationRequest(
            capability=capability,
            prompt=prompt,
            brand=brief.brand if brief else self.cfg.default_brand,
            language=brief.language if brief else "en",
            params=params or {},
        )
        provider = self.registry.for_capability(capability)
        result = provider.generate(request)
        self._record(result, brief)
        return result

    def generate_media(
        self,
        spec_or_content_type: "MediaSpec | str",
        prompt: str,
        brief: Optional[Brief] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """Capability-routed media generation — the media planner.

        Pass a MediaSpec (or a content-type preset name like
        ``healthcare_photo`` / ``social_quote`` / ``quick_reel``); the
        capability registry ranks configured providers and the orchestrator
        works down the list, falling back on provider failure. The winning
        provider and the ranking are recorded in the result metadata so
        every routing decision is auditable.
        """
        spec = (
            spec_for(spec_or_content_type)
            if isinstance(spec_or_content_type, str)
            else spec_or_content_type
        )
        available = self.registry.available_names(spec.modality)
        ranked = self.capabilities.rank(spec, available)
        if not ranked:
            raise ProviderNotConfigured(
                f"No configured provider satisfies {spec}. Configured "
                f"{spec.modality} providers: {available or 'none'} — add "
                "credentials in .env (see pcip/SETUP.md)."
            )
        request_params = dict(params or {})
        for key, value in (("width", spec.width), ("height", spec.height),
                           ("duration_s", spec.duration_s)):
            if value and key not in request_params:
                request_params[key] = value

        errors = []
        for provider_name, score in ranked:
            provider = self.registry.by_name(provider_name)
            request = GenerationRequest(
                capability=spec.modality,
                prompt=prompt,
                brand=brief.brand if brief else self.cfg.default_brand,
                language=brief.language if brief else "en",
                params=request_params,
            )
            try:
                result = provider.generate(request)
            except Exception as exc:
                errors.append(f"{provider_name}: {type(exc).__name__}: {exc}")
                continue
            result.metadata["routing"] = {
                "spec": spec.__dict__,
                "ranked": ranked,
                "selected": provider_name,
                "score": score,
                "fallbacks_tried": errors,
            }
            self._record(result, brief)
            return result
        raise ProviderNotConfigured(
            "All capable providers failed: " + "; ".join(errors)
        )

    def copy_for_brief(self, brief: Brief, deliverable: str) -> GenerationResult:
        """Generate deliverable-specific copy grounded in the brief."""
        prompt = (
            f"Deliverable: {deliverable}\n"
            f"Objective: {brief.objective}\n"
            f"Audience: {brief.audience}\n"
            f"Key messages: {'; '.join(brief.key_messages) or 'n/a'}\n"
            f"Tone: {brief.tone or 'on-brand, warm, expert'}\n"
            f"Channels: {', '.join(brief.channels) or 'n/a'}\n"
            f"Constraints: {'; '.join(brief.constraints) or 'none'}\n\n"
            "Produce the complete copy package for this deliverable "
            "(headlines, body, captions, CTA, hashtags where relevant, and "
            "alt-text for every visual)."
        )
        return self.generate("copy", prompt, brief)

    # ── Graph recording ──────────────────────────────────────────────────

    def _record(self, result: GenerationResult, brief: Optional[Brief]) -> None:
        for asset in result.assets:
            self.graph.upsert_node(
                asset.id,
                NodeKind.ASSET,
                asset.name,
                asset.to_dict(),
                search_text=f"{asset.name} {' '.join(asset.tags)} "
                f"{result.provider} {result.capability}",
            )
            if brief:
                self.graph.add_edge(asset.id, EdgeKind.FROM_BRIEF, brief.id)

    def status(self) -> Dict[str, Any]:
        return self.registry.status()
