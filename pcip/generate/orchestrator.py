"""Generation orchestrator.

Takes a creative Brief and coordinates copy, image, video, and Canva design
generation through the provider registry, registering every output (with its
license) in the knowledge graph so nothing generated is ever untracked.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pcip.config import PCIPConfig
from pcip.generate.providers import (
    GenerationRequest,
    GenerationResult,
    ProviderRegistry,
)
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief, EdgeKind, NodeKind


class GenerationOrchestrator:
    def __init__(self, config: PCIPConfig, graph: KnowledgeGraph) -> None:
        self.cfg = config
        self.graph = graph
        self.registry = ProviderRegistry(config)

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
