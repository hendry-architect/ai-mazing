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
    # Legacy single-language fields, kept so older runs still publish.
    "title": "",
    "excerpt": "",
    "body_html": "",
    "alt_texts": [],
    "hashtags": [],
    "captions": {},
    # PassQual Health standard: bilingual parity, SEO surface, FAQ block.
    "titles": {},                 # {"es": ..., "en": ...}
    "bodies": {},                 # {"es": "<h2>…", "en": "<h2>…"}
    "meta_title": "",             # ≤60 characters, carries service + geo
    "meta_description": "",       # ≤155 characters, ES-primary
    "faq": [],                    # [{"q": ..., "a": ...}, …] — feeds FAQPage
    "alt_texts_by_language": {},  # {"es": ..., "en": ...}
    "keywords": [],
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
        from pcip.standards import PH

        prompt = (
            f"Deliverable: {deliverable}\n"
            f"Objective: {brief.objective}\n"
            f"Audience: {brief.audience}\n"
            f"Key messages: {'; '.join(brief.key_messages) or 'n/a'}\n"
            f"Tone: {brief.tone or 'on-brand, warm, expert'}\n"
            f"Channels: {', '.join(brief.channels) or 'n/a'}\n"
            f"Constraints: {'; '.join(brief.constraints) or 'none'}\n\n"
            "This is for PassQual Health and must meet its published article "
            "standard. The standard is enforced automatically after you write, "
            "so an article that misses any of it will be rejected:\n\n"
            f"- BILINGUAL PARITY. Write the full article twice: Spanish "
            f"(primary) and English. Not a summary — the same article.\n"
            f"- LENGTH. At least {PH.MIN_BODY_WORDS} words per language, with "
            f"at least {PH.MIN_H2_SECTIONS} <h2> sections. Do not use <h1>; "
            "the post title is the H1.\n"
            f"- FAQ. At least {PH.MIN_FAQ_ITEMS} question/answer pairs "
            "answering what patients actually search.\n"
            f"- SEO. A meta title of at most {PH.META_TITLE_MAX} characters "
            f"including '{PH.GEO_PHRASE}', and a meta description of at most "
            f"{PH.META_DESCRIPTION_MAX} characters, Spanish-primary. Spanish "
            f"speakers search '{PH.NEAR_ME_ES}', not city names — write for "
            "that intent.\n"
            f"- NAP, printed verbatim in both languages, exactly:\n"
            f"    {PH.NAP_NAME} | {PH.NAP_STREET}, {PH.NAP_CITY}, "
            f"{PH.NAP_STATE} {PH.NAP_ZIP} | {PH.NAP_PHONE_DISPLAY} | {PH.SITE}\n"
            f"- CREDENTIALS. Name {PH.PHYSICIAN} and Florida license "
            f"{PH.FL_LICENSE} ({PH.CREDENTIALS}).\n"
            f"- CTA. End each language with the booking line: "
            f"'{PH.BOOKING_ES}' / '{PH.BOOKING_EN}'.\n"
            "- COMPLIANCE, absolute: no pediatric content of any kind; no "
            "outcome guarantees, cures or superlatives such as 'the best'; "
            "structure and function language only. Mental-health topics must "
            "print 988 and 911. Flag anything needing clinician sign-off with "
            "[MEDICAL-REVIEW] — those notes are stripped before publication, "
            "so never put patient-facing content inside one.\n\n"
            "Write the prose first for the human reviewer. Then, at the very "
            "end, repeat the publishable parts as a single fenced JSON block:\n\n"
            "```json\n"
            "{\n"
            '  "titles": {"es": "titular en español", "en": "English headline"},\n'
            '  "bodies": {"es": "<p>…</p><h2>…</h2>…", "en": "<p>…</p><h2>…</h2>…"},\n'
            '  "meta_title": "≤60 chars, includes ' + PH.GEO_PHRASE + '",\n'
            '  "meta_description": "≤155 chars, Spanish",\n'
            '  "faq": [{"q": "pregunta", "a": "respuesta"}],\n'
            '  "alt_texts_by_language": {"es": "texto alternativo", '
            '"en": "alt text"},\n'
            '  "keywords": ["término", "near-me phrase"],\n'
            '  "hashtags": ["#Ejemplo"],\n'
            '  "captions": {"instagram": "…", "facebook": "…"}\n'
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
