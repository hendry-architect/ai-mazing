"""The pipeline library — PCIP's standard deliverables.

Each pipeline follows the same spine:

    retrieve context from the graph → generate copy → assemble in Canva
    (brand-template autofill) → review gate(s) → export via the official
    API → register output

Patient education adds a mandatory ``medical_review`` gate that can never be
auto-approved, plus a plain-language check. All Canva assembly goes through
supported workflows only (autofill + export), which is what keeps premium
content licensing intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from pcip.licensing import LicensePolicy
from pcip.models import Asset, EdgeKind, NodeKind, new_id
from pcip.pipelines.base import Pipeline, ReviewGate, Step


# ─── Shared step handlers ────────────────────────────────────────────────────


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

    orch = GenerationOrchestrator(ctx["cfg"], ctx["graph"])
    deliverable = ctx.get("deliverable", "creative deliverable")
    result = orch.copy_for_brief(ctx["brief"], deliverable)
    ctx["copy"] = result.text
    # The prose is what a human reads at the review gate; the parsed fields are
    # what the publisher places (body in the body, hashtags in the caption).
    ctx["copy_fields"] = result.metadata.get("fields", {})
    needs_medical = "[MEDICAL-REVIEW]" in result.text
    ctx["copy_flagged_medical"] = needs_medical
    return "Copy generated" + (" — flagged for medical review." if needs_medical else ".")


def assemble_in_canva(ctx: Dict[str, Any]) -> str:
    """Autofill the chosen brand template with the generated copy/assets.

    Requires ``brief.references`` to carry a ``canva:brand_template:<id>``
    node id (or ctx["brand_template_id"]). Without Canva configured this step
    fails cleanly and the run stays resumable.
    """
    from pcip.connectors.canva import CanvaClient

    cfg, graph, brief = ctx["cfg"], ctx["graph"], ctx["brief"]
    template_id = ctx.get("brand_template_id", "")
    for ref in brief.references:
        if ref.startswith("canva:brand_template:"):
            template_id = ref.split(":", 2)[2]
    if not template_id:
        raise ValueError(
            "No brand template selected. Add 'canva:brand_template:<id>' to "
            "brief.references (find ids with: pcip search --kind brand_template)."
        )

    client = CanvaClient(cfg)
    dataset = client.get_brand_template_dataset(template_id).get("dataset", {})
    data = _map_copy_to_dataset(ctx.get("copy", ""), brief.title, dataset)
    design = client.autofill(template_id, data=data, title=brief.title)

    node_id = f"canva:design:{design['id']}"
    graph.upsert_node(
        node_id,
        NodeKind.DESIGN,
        design.get("title", brief.title),
        {"canva_id": design["id"], "urls": design.get("urls", {}),
         "brand_template_id": template_id},
    )
    graph.add_edge(node_id, EdgeKind.FROM_TEMPLATE, f"canva:brand_template:{template_id}")
    graph.add_edge(node_id, EdgeKind.FROM_BRIEF, brief.id)
    ctx["design_id"] = design["id"]
    ctx["design_node"] = node_id
    ctx.setdefault("_step_outputs", []).append(node_id)
    return f"Design {design['id']} assembled from brand template {template_id}."


def _map_copy_to_dataset(copy_text: str, title: str, dataset: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort mapping of copy onto a template's autofill fields."""
    lines = [l.strip() for l in copy_text.splitlines() if l.strip()]
    data: Dict[str, Any] = {}
    i = 0
    for field_name, spec in dataset.items():
        ftype = spec.get("type") if isinstance(spec, dict) else "text"
        if ftype == "text":
            value = title if "title" in field_name.lower() else (
                lines[i] if i < len(lines) else ""
            )
            data[field_name] = {"type": "text", "text": value[:500]}
            i += 1
        # image/chart fields are left to the design's defaults unless a
        # specific asset id is supplied upstream.
    return data


def export_deliverable(ctx: Dict[str, Any]) -> str:
    """Export the assembled design via the official Canva export API."""
    from pcip.connectors.canva import CanvaClient

    cfg, graph = ctx["cfg"], ctx["graph"]
    design_id = ctx.get("design_id")
    if not design_id:
        raise ValueError("No design to export — assemble step did not run.")
    fmt = ctx.get("export_format", "png")
    client = CanvaClient(cfg)
    urls = client.export_design(design_id, fmt=fmt)

    cfg.ensure_dirs()
    output_id = new_id("out")
    paths: List[str] = []
    for n, url in enumerate(urls):
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


def plain_language_check(ctx: Dict[str, Any]) -> str:
    """Heuristic reading-level guard for patient-facing copy."""
    text = ctx.get("copy", "")
    if not text:
        return "No copy to check."
    words = text.split()
    long_words = sum(1 for w in words if len(w.strip(".,;:!?")) >= 13)
    sentences = max(text.count(".") + text.count("!") + text.count("?"), 1)
    avg_len = len(words) / sentences
    issues = []
    if avg_len > 22:
        issues.append(f"average sentence length {avg_len:.0f} words (target ≤ 22)")
    if words and long_words / len(words) > 0.06:
        issues.append("dense vocabulary (>6% long words)")
    ctx["plain_language_issues"] = issues
    return "Plain-language check: " + ("; ".join(issues) if issues else "passed.")


def _named(deliverable: str):
    def _set(ctx: Dict[str, Any]) -> str:
        ctx["deliverable"] = deliverable
        return f"Deliverable: {deliverable}"
    return _set


# ─── Pipeline definitions ────────────────────────────────────────────────────


def _standard(name: str, description: str, deliverable: str,
              extra_steps: List, gates: List[str], export_format: str = "png") -> Pipeline:
    def _set_format(ctx: Dict[str, Any]) -> str:
        ctx["export_format"] = export_format
        return f"Export format: {export_format}"

    steps: List = [
        Step("setup", _named(deliverable), "Configure deliverable context"),
        Step("format", _set_format, "Choose export format"),
        Step("gather_context", gather_context, "Search the knowledge graph for related work"),
        Step("generate_copy", generate_copy, "AI copy package (headlines, body, CTA, hashtags, alt-text)"),
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
    ),
    "patient_education": _standard(
        "patient_education",
        "Patient education material — plain-language, clinician-approved.",
        "patient education handout/carousel",
        [Step("plain_language", plain_language_check, "Reading-level guard")],
        ["medical_review", "brand_review"],   # medical_review can NEVER auto-approve
        export_format="pdf",
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
