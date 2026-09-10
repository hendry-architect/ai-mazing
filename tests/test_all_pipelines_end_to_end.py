"""Every pipeline, start to finish.

Only patient_education had ever produced a deliverable. The other five were
built from the same factory and never executed once, so "it works" rested on
the shape of the code rather than on any of them having run. This drives all
six to completion offline, which turns "never run" into "checked on every
commit".
"""

import pytest

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.licensing import LicensePolicy
from pcip.models import Asset, Brief, EdgeKind, NodeKind
from pcip.pipelines.base import PipelineRunner
from pcip.pipelines.library import PIPELINES, get_pipeline
from pcip.standards import PH


def compliant_body(words=800):
    return (
        "<p>Intro.</p>"
        + "<h2>Uno</h2><p>" + ("palabra " * words) + "</p>"
        + "<h2>Dos</h2><p>texto</p><h2>Tres</h2><p>texto</p>"
        + f"<p>Búsquenos {PH.NEAR_ME_ES}. {PH.PHYSICIAN}, {PH.FL_LICENSE}.</p>"
        + f"<p>{PH.NAP_NAME} | {PH.NAP_STREET}, {PH.NAP_CITY}, {PH.NAP_STATE} "
        f"{PH.NAP_ZIP} | {PH.NAP_PHONE_DISPLAY} | {PH.SITE}</p>"
        + f"<p>{PH.BOOKING_ES}</p>"
    )


def copy_fields(tmp_path):
    body = compliant_body()
    return {
        "titles": {"es": "Título", "en": "Title"},
        "bodies": {"es": body, "en": body.replace("palabra", "word")},
        "title": "Título",
        "body_html": body,
        "excerpt": "Resumen breve.",
        "meta_title": f"Prevención en {PH.GEO_PHRASE}",
        "meta_description": "Descripción breve para búsqueda.",
        "faq": [{"q": "a", "a": "b"}, {"q": "c", "a": "d"}, {"q": "e", "a": "f"}],
        "alt_texts_by_language": {"es": "alt es", "en": "alt en"},
        "alt_texts": ["alt es"],
    }


@pytest.fixture
def hero(tmp_path):
    path = tmp_path / "Prevención de la Diabetes.png"
    path.write_bytes(b"\x89PNG fake")
    return path


def run_to_completion(name, tmp_path, hero, gates_approved_by="Dr. Pascual"):
    """Drive one pipeline through every handoff and gate."""
    cfg = PCIPConfig(data_dir=tmp_path / "data", canva_mode="mcp")
    cfg.ensure_dirs()
    graph = KnowledgeGraph(":memory:")
    runner = PipelineRunner(cfg, graph)
    brief = Brief(id=f"brief_{name}", title="Prevención de la Diabetes",
                  objective="Enseñar tres hábitos", brand="PassQual Health",
                  language="es", channels=["wordpress"])
    graph.upsert_node(brief.id, NodeKind.BRIEF, brief.title, brief.to_dict())

    pipeline = get_pipeline(name)
    run = runner.start(pipeline, brief)

    # Fulfil handoffs and approvals until the run finishes or stops advancing.
    for _ in range(12):
        if run.status in ("done", "failed"):
            break
        if run.status == "awaiting_handoff":
            needs = (run.pending_handoff or {}).get("needs", "")
            if needs == "copy":
                run.context["copy_fields"] = copy_fields(tmp_path)
                run.context["copy"] = copy_fields(tmp_path)["body_html"]
            elif needs == "imagery":
                run.context["media_paths"] = [str(hero)]
            elif needs in ("assembly", "assemble"):
                run.context["design_id"] = "DAHUecsTYgU"
                run.context["design_title"] = "Prevención de la Diabetes"
            elif needs == "export":
                run.context["export_files"] = [str(hero)]
            else:
                pytest.fail(f"{name}: unexpected handoff {needs!r}")
            run = runner.fulfil_handoff(pipeline, run, brief)
        elif run.status == "awaiting_review":
            gate = run.current_gate
            runner.approve(run.id, gate, gates_approved_by,
                           how="test harness, no human involved")
            run = runner.resume(pipeline, runner._require_run(run.id), brief)
        else:
            break
    return run, graph


@pytest.mark.parametrize("name", sorted(PIPELINES))
def test_every_pipeline_reaches_done(name, tmp_path, hero):
    run, graph = run_to_completion(name, tmp_path, hero)
    assert run.status == "done", (
        f"{name} ended {run.status}: "
        + "; ".join(f"{s.step}={s.status} {s.detail[:80]}" for s in run.steps)
    )


@pytest.mark.parametrize("name", sorted(PIPELINES))
def test_every_pipeline_produces_an_output_with_provenance(name, tmp_path, hero):
    """A finished run that recorded nothing is not a deliverable."""
    run, graph = run_to_completion(name, tmp_path, hero)
    outputs = graph.nodes_by_kind(NodeKind.OUTPUT)
    assert outputs, f"{name} produced no output node"

    asset = Asset.from_dict(outputs[0]["payload"])
    # The licence must permit publishing — an export, not an extraction.
    assert asset.metadata.get("via_export") is True
    LicensePolicy().check_publish([asset])

    produced = [dst for _, dst in graph.neighbors(run.id, EdgeKind.PRODUCED)]
    assert outputs[0]["id"] in produced, f"{name}: output not linked to its run"


def test_patient_education_cannot_finish_without_a_clinician(tmp_path, hero):
    """The one gate that must never be automatable, checked on the real
    pipeline rather than a synthetic one."""
    cfg = PCIPConfig(data_dir=tmp_path / "data", canva_mode="mcp",
                     auto_approve_gates=["medical_review", "brand_review"])
    cfg.ensure_dirs()
    graph = KnowledgeGraph(":memory:")
    runner = PipelineRunner(cfg, graph)
    brief = Brief(id="b", title="T", brand="PassQual Health", language="es")
    pipeline = get_pipeline("patient_education")
    run = runner.start(pipeline, brief)

    for _ in range(10):
        if run.status != "awaiting_handoff":
            break
        needs = (run.pending_handoff or {}).get("needs", "")
        if needs == "copy":
            run.context["copy_fields"] = copy_fields(tmp_path)
        elif needs == "imagery":
            run.context["media_paths"] = [str(hero)]
        elif needs in ("assembly", "assemble"):
            run.context["design_id"] = "D1"
        elif needs == "export":
            run.context["export_files"] = [str(hero)]
        run = runner.fulfil_handoff(pipeline, run, brief)

    assert run.status == "awaiting_review"
    assert run.current_gate == "medical_review", (
        "auto-approve must never reach the clinician gate"
    )
