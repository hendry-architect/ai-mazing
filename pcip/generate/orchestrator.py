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


COPY_FIELDS: Dict[str, Any] = {
    "title": "",
    "excerpt": "",
    "body_html": "",
    "alt_texts": [],
    "hashtags": [],
    "captions": {},
}


def parse_copy_fields(text: str) -> Dict[str, Any]:
    """Extract the machine-readable block from a copy result.

    Defensive on purpose: a model that ignores the format, wraps the block in
    prose, or emits invalid JSON must degrade to "body is the whole text",
    never break a pipeline run mid-flight.
    """
    import json
    import re

    fields = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
              for k, v in COPY_FIELDS.items()}
    text = text or ""

    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not candidates:
        # No fence — fall back to the outermost brace-balanced span.
        start, depth = text.find("{"), 0
        if start != -1:
            for i in range(start, len(text)):
                depth += (text[i] == "{") - (text[i] == "}")
                if depth == 0:
                    candidates = [text[start : i + 1]]
                    break

    for raw in reversed(candidates):          # a trailing block is the summary
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        for key, default in COPY_FIELDS.items():
            value = parsed.get(key, default)
            if isinstance(default, list):
                fields[key] = [str(v) for v in value] if isinstance(value, list) else []
            elif isinstance(default, dict):
                fields[key] = {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}
            else:
                fields[key] = str(value or "")
        break

    if not fields["body_html"]:
        # Nothing usable parsed — the prose itself is the best body we have.
        fields["body_html"] = text.strip()
    return fields


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
        """Generate deliverable-specific copy grounded in the brief.

        Returns prose for the human reviewer *and* a machine-readable block, so
        the publisher can put the body in the body and the hashtags in the
        caption rather than dumping one blob into the article.
        """
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
            "alt-text for every visual).\n\n"
            "Then, at the very end, repeat the publishable parts as a single "
            "fenced JSON block so they can be placed automatically:\n\n"
            "```json\n"
            "{\n"
            '  "title": "the headline, plain text",\n'
            '  "excerpt": "1-2 sentence summary, plain text",\n'
            '  "body_html": "the article body as simple HTML (<p>, <h2>, <ul>) '
            'with NO hashtags and no alt-text notes",\n'
            '  "alt_texts": ["one alt text per visual, in order"],\n'
            '  "hashtags": ["#example"],\n'
            '  "captions": {"instagram": "...", "linkedin": "..."}\n'
            "}\n"
            "```"
        )
        result = self.generate("copy", prompt, brief)
        result.metadata["fields"] = parse_copy_fields(result.text)
        return result

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
