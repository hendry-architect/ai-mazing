"""The pipeline library — PCIP's standard deliverables.

Each pipeline follows the same spine:

    retrieve context from the graph → generate copy → assemble in Canva
    (brand-template autofill) → review gate(s) → export via the official
    API → register output

Patient education adds a plain-language check (its mandatory
``medical_review`` gate was removed 2026-09-10 — see the dated comment on
its pipeline definition below). All Canva assembly goes through supported
workflows only (autofill + export), which is what keeps premium content
licensing intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from pcip.annotations import has_review_annotations, strip_review_annotations
from pcip.licensing import LicensePolicy
from pcip.models import Asset, EdgeKind, NodeKind, new_id
from pcip.pipelines.base import HandoffRequired, Pipeline, ReviewGate, Step


# ─── Shared step handlers ────────────────────────────────────────────────────


from pcip.standards import PH as _PH

# The clinic's geo, stated once, from the standard rather than re-typed.
PH_GEO = _PH.GEO_PHRASE


def gather_context(ctx: Dict[str, Any]) -> str:
    """Pull related prior work from the knowledge graph into the context."""
    graph, brief = ctx["graph"], ctx["brief"]
    related: List[Dict[str, Any]] = []
    for topic in brief.topics or [brief.title]:
        related += graph.search(topic, limit=5)
    seen, unique = set(), []
    for node in related:
        if node["id"] not in seen and node["id"] != brief.id:
            seen.add(node["id"])
            unique.append({"id": node["id"], "kind": node["kind"], "name": node["name"]})
    ctx["related_work"] = unique[:15]
    return f"Found {len(unique)} related items in the knowledge graph."


def generate_copy(ctx: Dict[str, Any]) -> str:
    from pcip.generate.orchestrator import GenerationOrchestrator
    from pcip.generate.providers import ProviderNotConfigured

    cfg, brief = ctx["cfg"], ctx["brief"]

    # Copy already supplied (a handoff was fulfilled, or an operator passed it).
    if ctx.get("copy_fields") or ctx.get("copy"):
        text = ctx.get("copy", "")
        ctx.setdefault("copy_fields", {})
        ctx["copy_flagged_medical"] = has_review_annotations(text)
        return "Copy supplied via handoff."

    orch = GenerationOrchestrator(cfg, ctx["graph"])
    deliverable = ctx.get("deliverable", "creative deliverable")
    try:
        result = orch.copy_for_brief(brief, deliverable)
    except ProviderNotConfigured:
        if cfg.canva_mode != "mcp":
            raise
        # No copy provider configured, but an agent session is driving this
        # run and can write the copy itself. Ask for it rather than dying.
        raise HandoffRequired("copy", {
            "deliverable": deliverable,
            "brand": brief.brand,
            "language": brief.language,
            "objective": brief.objective,
            "audience": brief.audience,
            "key_messages": brief.key_messages,
            "tone": brief.tone,
            "constraints": brief.constraints,
            "wanted_shape": {
                "title": "headline, plain text",
                "excerpt": "1-2 sentence summary",
                "body_html": "body as simple HTML, no hashtags",
                "alt_texts": ["one per visual"],
                "hashtags": ["#example"],
                "captions": {"instagram": "..."},
            },
            "how": (
                "Write the copy package for this brief, save it as JSON in the "
                "shape above, then attach it:\n"
                f"  pcip attach {ctx['run'].id} --copy-file <path.json>\n"
                "Flag anything needing clinician sign-off with [MEDICAL-REVIEW]."
            ),
        })
    ctx["copy"] = result.text
    # The prose is what a human reads at the review gate; the parsed fields are
    # what the publisher places (body in the body, hashtags in the caption).
    ctx["copy_fields"] = result.metadata.get("fields", {})
    needs_medical = has_review_annotations(result.text)
    ctx["copy_flagged_medical"] = needs_medical
    return "Copy generated" + (" — flagged for medical review." if needs_medical else ".")


def _record_design(ctx: Dict[str, Any], design_id: str, *, title: str = "",
                   view_url: str = "", template_id: str = "") -> str:
    """Put an assembled design into the graph and wire its provenance."""
    graph, brief = ctx["graph"], ctx["brief"]
    node_id = f"canva:design:{design_id}"
    graph.upsert_node(
        node_id,
        NodeKind.DESIGN,
        title or brief.title,
        {"canva_id": design_id, "urls": {"view_url": view_url},
         "brand_template_id": template_id},
    )
    if template_id:
        graph.add_edge(node_id, EdgeKind.FROM_TEMPLATE,
                       f"canva:brand_template:{template_id}")
    graph.add_edge(node_id, EdgeKind.FROM_BRIEF, brief.id)
    ctx["design_id"] = design_id
    ctx["design_node"] = node_id
    ctx.setdefault("_step_outputs", []).append(node_id)
    return node_id


def _template_id_from(ctx: Dict[str, Any]) -> str:
    """Which brand template to build from, most specific source first.

    An explicit reference on the brief wins, then anything attached to the run,
    then the account default. The default exists because unattended runs have
    no one to ask: a scheduled pipeline that stops to request a template id is
    a pipeline that does not run.
    """
    template_id = ctx.get("brand_template_id", "")
    for ref in ctx["brief"].references:
        if ref.startswith("canva:brand_template:"):
            template_id = ref.split(":", 2)[2]
    return template_id or ctx["cfg"].canva_brand_template_id


def assemble_in_canva(ctx: Dict[str, Any]) -> str:
    """Produce the on-brand design for this brief.

    Two execution modes, same governance either way (see PCIPConfig.canva_mode):

    - ``mcp``     — PCIP cannot call the Canva MCP tools itself, so it pauses
      with a handoff describing exactly what to create. An agent session holding
      the connector creates the design from a brand template and attaches it
      back with ``pcip attach``. Works with ordinary brand templates.
    - ``connect`` — direct brand-template autofill through the Connect API.
      Needs templates that define autofill fields.
    """
    cfg, brief = ctx["cfg"], ctx["brief"]
    template_id = _template_id_from(ctx)

    # A handoff was fulfilled (or the design was supplied up front): record it.
    if ctx.get("design_id"):
        _record_design(ctx, ctx["design_id"], title=ctx.get("design_title", ""),
                       view_url=ctx.get("design_url", ""), template_id=template_id)
        return f"Design {ctx['design_id']} recorded from the Canva handoff."

    if cfg.canva_mode == "mcp":
        fields = ctx.get("copy_fields") or {}
        raise HandoffRequired("assembly", {
            "brand": brief.brand,
            "language": brief.language,
            "title": fields.get("title") or brief.title,
            "brand_template_id": template_id,
            "deliverable": ctx.get("deliverable", ""),
            "copy_fields": fields,
            "how": (
                "Create the design in Canva from a brand template (MCP: "
                "search-brand-templates → create-design-from-brand-template, "
                "then edit-design to place the copy), then attach it:\n"
                f"  pcip attach {ctx['run'].id} --design-id <id> --design-url <view_url>"
            ),
        })

    # ── connect mode: brand-template autofill ────────────────────────────
    from pcip.connectors.canva import CanvaClient

    if not template_id:
        raise ValueError(
            "No brand template selected. Add 'canva:brand_template:<id>' to "
            "brief.references (find ids with: pcip search --kind brand_template)."
        )
    client = CanvaClient(cfg)
    dataset = client.get_brand_template_dataset(template_id).get("dataset", {})
    if not dataset:
        raise ValueError(
            f"Brand template {template_id} defines no autofill fields, so the "
            "Connect API cannot fill it. Either add data fields to the template "
            "in Canva, or set PCIP_CANVA_MODE=mcp to assemble through the Canva "
            "connector instead (works with ordinary templates)."
        )
    data = _map_copy_to_dataset(ctx.get("copy_fields") or {}, brief.title, dataset,
                                 language=brief.language)
    design = client.autofill(template_id, data=data, title=brief.title)
    _record_design(ctx, design["id"], title=design.get("title", brief.title),
                   view_url=(design.get("urls") or {}).get("view_url", ""),
                   template_id=template_id)
    return f"Design {design['id']} assembled from brand template {template_id}."


def _map_copy_to_dataset(
    copy_fields: Dict[str, Any], title: str, dataset: Dict[str, Any],
    language: str = "",
) -> Dict[str, Any]:
    """Map generated copy onto a brand template's *named* autofill fields.

    The previous version split the prose copy into lines and handed them out
    in field order — it had no idea a field called "cta" wanted a phone
    number rather than the third sentence of the article. This instead reads
    the field names (every brand template defines its own, so this matches
    by keyword rather than hardcoding one template's schema) and pulls from
    the shaped fields ``copy_for_brief`` actually produces: ``titles``/
    ``bodies``/``captions`` for bilingual content, falling back to the flat
    ``title``/``excerpt`` for single-language briefs.

    PH is Spanish-primary (see PH_PRIMARY in pcip/connectors/wordpress.py),
    so a bilingual brief autofills in Spanish unless the brief itself is
    English-only — this only picks the *visual* asset's language; the
    published article still carries both.
    """
    import html as _html
    import re as _re

    titles = copy_fields.get("titles") or {}
    bodies = copy_fields.get("bodies") or {}
    captions = copy_fields.get("captions") or {}
    lang = "en" if str(language).lower().startswith("en") else "es"
    other = "en" if lang == "es" else "es"

    headline = (titles.get(lang) or titles.get(other)
                or copy_fields.get("title") or title)

    # A caption is already short-form, and PassQual's convention (seen in
    # every caption generated so far) ends it with a call-to-action after an
    # arrow — "...en Miami Gardens. Agenda tu cita → 786-677-9922" — which
    # belongs on the template's own cta field, not folded into the body.
    #
    # Captions are keyed by *platform* (instagram/facebook), not language —
    # copy_for_brief generates one caption, not a per-language pair — so this
    # picks a platform, never a language key.
    caption = (captions.get("instagram") or captions.get("facebook")
               or next(iter(captions.values()), ""))
    body, arrow, cta_tail = caption.partition("→")
    body = body.strip()
    cta = f"→{cta_tail}".strip() if arrow else ""
    if not body:
        body = copy_fields.get("excerpt", "") or copy_fields.get("meta_description", "")
    if not body:
        raw_html = bodies.get(lang) or bodies.get(other) or copy_fields.get("body_html", "")
        plain = _html.unescape(_re.sub(r"<[^>]+>", " ", raw_html))
        plain, _ = strip_review_annotations(plain)
        body = " ".join(plain.split())[:280]

    data: Dict[str, Any] = {}
    for field_name, spec in dataset.items():
        ftype = spec.get("type") if isinstance(spec, dict) else "text"
        if ftype != "text":
            continue      # image/chart fields: nothing to offer without an
                          # image provider configured; the template's default art stays.
        name = field_name.lower()
        if "cta" in name or "call_to_action" in name or "button" in name:
            value = cta or "Agenda tu cita"
        elif "headline" in name or "title" in name:
            value = headline
        else:
            value = body
        data[field_name] = {"type": "text", "text": value[:500]}
    return data


def export_deliverable(ctx: Dict[str, Any]) -> str:
    """Export the assembled design through Canva's official export workflow.

    Premium content leaves Canva only this way — as a rendered design, with
    the account's entitlements applied by Canva. That holds in both modes:
    the MCP connector's export-design tool is the same supported workflow,
    just invoked by an agent session rather than by PCIP directly.
    """
    cfg, graph = ctx["cfg"], ctx["graph"]
    design_id = ctx.get("design_id")
    if not design_id:
        raise ValueError("No design to export — assemble step did not run.")
    fmt = ctx.get("export_format", "png")
    cfg.ensure_dirs()
    output_id = new_id("out")
    paths: List[str] = []

    attached = [p for p in (ctx.get("export_files") or []) if p]
    # Underscore key: a signed export URL is a bearer credential for the
    # file, so it stays in memory and never reaches the run record.
    urls = [u for u in (ctx.get("_export_urls") or []) if u]
    if attached:
        paths = [str(p) for p in attached]
    elif urls:
        # MCP export-design returns signed URLs, not files. Fetching them here
        # keeps the download inside the step that records the licensing
        # metadata, so an attached URL and an attached file end up identical.
        from pcip.connectors.canva import download_export_url

        for n, url in enumerate(urls):
            dest = Path(cfg.exports_dir) / f"{output_id}_{n}.{fmt}"
            download_export_url(url, dest, timeout=cfg.request_timeout)
            paths.append(str(dest))
    elif cfg.canva_mode == "mcp":
        raise HandoffRequired("export", {
            "design_id": design_id,
            "format": fmt,
            "how": (
                "Export the design through Canva (MCP: export-design), then attach "
                "the result — either the signed URL, which PCIP downloads itself:\n"
                f"  pcip attach {ctx['run'].id} --export-url <url>\n"
                "or, if that host is unreachable from here, the downloaded file:\n"
                f"  pcip attach {ctx['run'].id} --export-file <path>"
            ),
        })
    else:
        from pcip.connectors.canva import CanvaClient

        client = CanvaClient(cfg)
        for n, url in enumerate(client.export_design(design_id, fmt=fmt)):
            dest = Path(cfg.exports_dir) / f"{output_id}_{n}.{fmt}"
            client.download_export(url, dest)
            paths.append(str(dest))

    # Real per-visual alt text from the copy step, aligned to the exported
    # pages; without this every image inherits the deliverable's filename.
    alt_texts = [str(a) for a in (ctx.get("copy_fields") or {}).get("alt_texts") or []]

    asset = Asset(
        id=output_id,
        name=f"{ctx['brief'].title} ({fmt})",
        kind="image" if fmt in ("png", "jpg", "pdf") else fmt,
        canva_id=design_id,
        local_path=paths[0] if paths else "",
        license=LicensePolicy.canva_export_license(pro=True),
        metadata={"via_export": True, "format": fmt, "pages": paths,
                  "alt_texts": alt_texts},
    )
    graph.upsert_node(output_id, NodeKind.OUTPUT, asset.name, asset.to_dict())
    if ctx.get("design_node"):
        graph.add_edge(output_id, EdgeKind.DERIVED_FROM, ctx["design_node"])
    ctx["output_id"] = output_id
    ctx["export_paths"] = paths
    ctx.setdefault("_step_outputs", []).append(output_id)
    return f"Exported {len(paths)} file(s) → {cfg.exports_dir} (output {output_id})."


def generate_hero_image(ctx: Dict[str, Any]) -> str:
    """Generate the deliverable's imagery, routed by capability.

    This is the step the vendor-agnostic provider layer was built for. The
    brief asks for a capability — a 1600x900 photorealistic image under a
    commercial licence — and the registry ranks whichever providers are
    configured. No vendor is named here, so adding or dropping one is a
    credential change rather than a code change.

    Skipping is the correct behaviour when nothing is configured. The Canva
    design is the deliverable's real artwork; a generated image supplements it,
    and refusing to run without an image provider would block a pipeline that
    worked for weeks without one. The advisory shows up in the step detail so
    the absence is visible rather than silent.

    Generated images carry a synthetic licence, so the licensing policy treats
    them differently from Canva exports — they were never Canva's to license.
    """
    from pcip.generate.capabilities import spec_for
    from pcip.generate.orchestrator import GenerationOrchestrator
    from pcip.generate.providers import ProviderNotConfigured

    cfg, brief = ctx["cfg"], ctx["brief"]
    preset = ctx.get("media_preset", "blog_hero")

    if ctx.get("media_paths"):
        return "Imagery supplied — generation skipped."

    orch = GenerationOrchestrator(cfg, ctx["graph"])
    fields = ctx.get("copy_fields") or {}
    # Prompt from the article itself, not the brief alone: the copy step has
    # already decided what this piece is actually about.
    subject = (
        fields.get("meta_description")
        or fields.get("excerpt")
        or brief.objective
        or brief.title
    )
    prompt = (
        f"{subject}\n\n"
        f"Editorial photograph for {brief.brand}, a physician-led clinic in "
        f"{PH_GEO}. Warm, natural light; real clinical setting; no text, no "
        "logos, no watermarks, no recognisable faces. Documentary rather than "
        "stock-photo styling."
    )

    try:
        result = orch.generate_media(spec_for(preset), prompt, brief)
    except ProviderNotConfigured as exc:
        ctx["media_generation"] = {"skipped": True, "reason": str(exc)}
        return (
            "No image provider configured — skipped. The Canva design remains "
            "the artwork. Configure one in .env to add generated imagery."
        )
    except HandoffRequired:
        # The Canva provider asks an agent session to source the image. That is
        # a pause, not a failure, and must reach the runner intact — swallowing
        # it here would report "continuing without imagery" for a run that is
        # simply waiting for someone.
        raise
    except Exception as exc:                      # a vendor outage is not fatal
        ctx["media_generation"] = {"skipped": True, "reason": f"{type(exc).__name__}: {exc}"}
        return f"Image generation failed ({type(exc).__name__}) — continuing without it."

    paths = [a.local_path for a in result.assets if a.local_path]
    ctx["generated_media"] = paths
    ctx["media_generation"] = {
        "provider": result.provider,
        "preset": preset,
        "ranking": result.metadata.get("ranking", []),
        "count": len(paths),
    }
    for asset in result.assets:
        ctx.setdefault("_step_outputs", []).append(asset.id)
    return (
        f"Generated {len(paths)} image(s) via {result.provider} "
        f"(preset {preset})."
    )


def ph_standard_check(ctx: Dict[str, Any]) -> str:
    """Hold the deliverable to the PassQual Health article standard.

    This runs before any review gate, so a clinician is never asked to approve
    something the brand standard already rejects. Blockers and missing
    requirements fail the step: the first article PCIP published was ~120
    words, Spanish-only, with no meta description, no hero image, no NAP and no
    physician credentials — every one of which this catches.
    """
    from pcip.standards import check_article

    fields = ctx.get("copy_fields") or {}
    bodies = fields.get("bodies") or {}
    titles = fields.get("titles") or {}
    if not bodies and fields.get("body_html"):
        # Older single-language copy: grade it in the brief's language so the
        # missing counterpart is reported rather than silently accepted.
        lang = (ctx["brief"].language or "es").lower()[:2]
        bodies = {lang: fields["body_html"]}
        titles = {lang: fields.get("title", "")}

    article = {
        "bodies": bodies,
        "titles": titles,
        "meta_title": fields.get("meta_title", ""),
        "meta_description": fields.get("meta_description", ""),
        "faq": fields.get("faq") or [],
        "featured_image": (ctx.get("export_paths") or [""])[0]
                          or (ctx.get("generated_media") or [""])[0]
                          or fields.get("featured_image", ""),
        "alt_texts": fields.get("alt_texts_by_language")
                     or fields.get("alt_texts") or {},
    }
    check = check_article(article, stage="draft")
    ctx["ph_standard"] = check.to_dict()

    if not check.passed:
        raise ValueError(check.report())
    if check.advisories:
        return (f"PH standard: passed with {len(check.advisories)} advisory "
                f"note(s) — {check.advisories[0].detail}")
    return "PH standard: passed."


# Share of long words that reads as "dense" for patient-facing copy. Spanish
# words are systematically longer than English ones, so one threshold across
# both languages fails bilingual material that is in fact plain.
_LONG_WORD_LIMITS = {"en": 0.06, "es": 0.11}


def plain_language_check(ctx: Dict[str, Any]) -> str:
    """Heuristic reading-level guard for patient-facing copy.

    Measures the prose, not the markup: HTML tags and entities are stripped
    first, otherwise every ``<p>`` counts as a word and inflates the result.
    """
    import html as _html
    import re as _re

    raw = ctx.get("copy", "") or (ctx.get("copy_fields") or {}).get("body_html", "")
    if not raw:
        return "No copy to check."
    text = _html.unescape(_re.sub(r"<[^>]+>", " ", raw))
    # Reviewer annotations are instructions to a human, not patient copy.
    text, _ = strip_review_annotations(text)

    words = text.split()
    if not words:
        return "No copy to check."
    language = str(getattr(ctx.get("brief"), "language", "en") or "en").lower()[:2]
    limit = _LONG_WORD_LIMITS.get(language, _LONG_WORD_LIMITS["en"])

    long_words = sum(1 for w in words if len(w.strip(".,;:!?¿¡()\"'")) >= 13)
    sentences = max(text.count(".") + text.count("!") + text.count("?"), 1)
    avg_len = len(words) / sentences
    issues = []
    if avg_len > 22:
        issues.append(f"average sentence length {avg_len:.0f} words (target ≤ 22)")
    share = long_words / len(words)
    if share > limit:
        issues.append(
            f"dense vocabulary ({share:.0%} long words, {language} target ≤ {limit:.0%})"
        )
    ctx["plain_language_issues"] = issues
    return "Plain-language check: " + ("; ".join(issues) if issues else "passed.")


def _named(deliverable: str):
    def _set(ctx: Dict[str, Any]) -> str:
        ctx["deliverable"] = deliverable
        return f"Deliverable: {deliverable}"
    return _set


# ─── Pipeline definitions ────────────────────────────────────────────────────


def _standard(name: str, description: str, deliverable: str,
              extra_steps: List, gates: List[str], export_format: str = "png",
              media_preset: str = "blog_hero") -> Pipeline:
    def _set_format(ctx: Dict[str, Any]) -> str:
        ctx["export_format"] = export_format
        ctx["media_preset"] = media_preset
        return f"Export format: {export_format} · imagery: {media_preset}"

    steps: List = [
        Step("setup", _named(deliverable), "Configure deliverable context"),
        Step("format", _set_format, "Choose export format"),
        Step("gather_context", gather_context, "Search the knowledge graph for related work"),
        Step("generate_copy", generate_copy, "AI copy package (headlines, body, CTA, hashtags, alt-text)"),
        # Imagery before the standard gate, so a generated hero counts toward
        # the check rather than showing as missing until export.
        Step("generate_media", generate_hero_image,
             "Capability-routed image generation (vendor-agnostic)"),
        # Before any human review: a clinician should never be asked to approve
        # something the brand standard already rejects.
        Step("ph_standard", ph_standard_check, "PassQual Health article standard"),
        *extra_steps,
        Step("assemble", assemble_in_canva, "Autofill the brand template (supported workflow)"),
    ]
    for gate in gates:
        steps.append(ReviewGate(gate, f"Human review: {gate.replace('_', ' ')}"))
    steps.append(Step("export", export_deliverable, "Export via official Canva export API"))
    return Pipeline(name=name, description=description, steps=steps)


PIPELINES: Dict[str, Pipeline] = {
    "presentation": _standard(
        "presentation",
        "Branded slide deck from a brief + brand template.",
        "slide presentation",
        [],
        ["brand_review"],
        export_format="pptx",
    ),
    "podcast_kit": _standard(
        "podcast_kit",
        "Episode cover art, audiogram frame, and promo copy for a podcast episode.",
        "podcast episode kit (cover, audiogram, show notes)",
        [],
        ["brand_review"],
    ),
    "blog_graphics": _standard(
        "blog_graphics",
        "Header + inline graphics for a passqual.com article.",
        "blog hero and inline graphics",
        [],
        ["brand_review"],
    ),
    "social_campaign": _standard(
        "social_campaign",
        "Multi-channel social campaign: visuals, captions, and hashtags.",
        "social media campaign (per-channel sizes, captions, hashtags)",
        [],
        ["brand_review"],
        media_preset="social_quote",
    ),
    "patient_education": _standard(
        "patient_education",
        "Patient education material — plain-language, standard-checked.",
        "patient education handout/carousel",
        [Step("plain_language", plain_language_check, "Reading-level guard")],
        # No medical_review: removed 2026-09-10 by explicit decision of
        # Dr. Hendry Pascual, founder/CEO/medical director of PassQual
        # Health, made after the alternative (auto-publish + notify + a
        # one-command retract) was presented and he chose full removal
        # instead. The clinical judgment this gate stood in for is
        # unchanged — he holds the license and the authority either way;
        # this is a change to where in the process it's exercised, not
        # whether it exists. The guard mechanism itself (NEVER_AUTO_APPROVE
        # in pcip/pipelines/base.py, and the terminal-confirmation ceremony
        # in pcip/cli.py) is untouched, in case a future gate needs it.
        ["brand_review"],
        # PNG, not PDF: the exported file becomes the article's featured image,
        # and a PDF cannot be one. The printable handout is a separate export.
        export_format="png",
        media_preset="healthcare_photo",
    ),
    "marketing_asset": _standard(
        "marketing_asset",
        "One-off marketing asset (flyer, banner, ad creative).",
        "marketing asset",
        [],
        ["brand_review"],
    ),
}


def get_pipeline(name: str) -> Pipeline:
    if name not in PIPELINES:
        raise KeyError(
            f"Unknown pipeline '{name}'. Available: {', '.join(sorted(PIPELINES))}"
        )
    return PIPELINES[name]
