"""Canva MCP handoff mode: PCIP pauses for work it cannot do itself, and
every governance gate still applies once the work comes back.
"""

import pytest

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief, NodeKind
from pcip.pipelines.base import HandoffRequired, Pipeline, PipelineRunner, ReviewGate, Step
from pcip.pipelines.library import assemble_in_canva, export_deliverable


def setup(mode="mcp", **cfg_kwargs):
    cfg = PCIPConfig(canva_mode=mode, **cfg_kwargs)
    g = KnowledgeGraph(":memory:")
    brief = Brief(id="brief_1", title="Diabetes at Home", language="es",
                  brand="PassQual Health")
    return cfg, g, PipelineRunner(cfg, g), brief


def assembly_pipeline(with_gate=True):
    steps = [Step("assemble", assemble_in_canva)]
    if with_gate:
        steps.append(ReviewGate("medical_review", "clinician sign-off"))
    return Pipeline("t", "test", steps)


def test_mcp_mode_pauses_instead_of_failing():
    cfg, g, runner, brief = setup()
    run = runner.start(assembly_pipeline(), brief)
    assert run.status == "awaiting_handoff"
    assert run.steps[0].status == "awaiting_handoff"
    handoff = run.pending_handoff
    assert handoff["needs"] == "assembly"
    assert handoff["language"] == "es"
    assert "create-design-from-brand-template" in handoff["how"]
    assert f"pcip attach {run.id}" in handoff["how"]


def test_attaching_a_design_records_it_and_continues():
    cfg, g, runner, brief = setup()
    pipe = assembly_pipeline(with_gate=False)
    run = runner.start(pipe, brief)

    run = runner.load_run(run.id)
    run.context["design_id"] = "DAHUd28dW6s"
    run.context["design_url"] = "https://www.canva.com/d/xyz"
    run.context["brand_template_id"] = "EAHNKdycEE8"
    for sr in run.steps:
        if sr.status == "awaiting_handoff":
            sr.status = "pending"
    runner._save(run)
    run = runner.resume(pipe, run, brief)

    assert run.status == "done"
    node = g.get_node("canva:design:DAHUd28dW6s")
    assert node is not None
    assert node["payload"]["canva_id"] == "DAHUd28dW6s"
    assert node["payload"]["brand_template_id"] == "EAHNKdycEE8"
    # provenance is wired both ways
    assert ("from_brief", "brief_1") in g.neighbors("canva:design:DAHUd28dW6s")


def test_the_medical_gate_still_applies_after_a_handoff():
    """A handoff must not become a way around governance."""
    cfg, g, runner, brief = setup()
    cfg.auto_approve_gates = ["medical_review"]     # even so
    pipe = assembly_pipeline(with_gate=True)
    run = runner.start(pipe, brief)

    run = runner.load_run(run.id)
    run.context["design_id"] = "DAH123"
    for sr in run.steps:
        if sr.status == "awaiting_handoff":
            sr.status = "pending"
    runner._save(run)
    run = runner.resume(pipe, run, brief)

    assert run.status == "awaiting_review"
    assert run.current_gate == "medical_review"


def test_export_handoff_states_the_design_and_format():
    cfg, g, runner, brief = setup()
    ctx = {"cfg": cfg, "graph": g, "brief": brief,
           "run": type("R", (), {"id": "run_x"})(),
           "design_id": "DAH999", "export_format": "pdf"}
    with pytest.raises(HandoffRequired) as exc:
        export_deliverable(ctx)
    assert exc.value.needs == "export"
    assert exc.value.spec["design_id"] == "DAH999"
    assert exc.value.spec["format"] == "pdf"


def test_attached_export_files_become_a_licensed_output(tmp_path):
    cfg, g, runner, brief = setup(data_dir=tmp_path)
    f = tmp_path / "page1.pdf"
    f.write_bytes(b"%PDF fake")
    ctx = {"cfg": cfg, "graph": g, "brief": brief,
           "run": type("R", (), {"id": "run_x"})(),
           "design_id": "DAH999", "export_format": "pdf",
           "export_files": [str(f)],
           "copy_fields": {"alt_texts": ["Un paciente revisando sus pies"]}}
    export_deliverable(ctx)

    out = g.get_node(ctx["output_id"])
    assert out["kind"] == NodeKind.OUTPUT.value
    # The licensing gate depends on this: exported via the supported workflow.
    assert out["payload"]["metadata"]["via_export"] is True
    assert out["payload"]["license"]["type"] == "canva_pro"
    assert out["payload"]["metadata"]["alt_texts"] == ["Un paciente revisando sus pies"]


def test_connect_mode_without_autofill_fields_says_what_to_do():
    """The exact situation on this Canva account: templates have no dataset."""
    cfg, g, runner, brief = setup(mode="connect")
    brief.references = ["canva:brand_template:EAHNKdycEE8"]

    class FakeClient:
        def __init__(self, *a, **k): pass
        def get_brand_template_dataset(self, tid): return {"dataset": {}}

    import pcip.connectors.canva as canva_mod
    original = canva_mod.CanvaClient
    canva_mod.CanvaClient = FakeClient
    try:
        with pytest.raises(ValueError) as exc:
            assemble_in_canva({"cfg": cfg, "graph": g, "brief": brief,
                               "run": type("R", (), {"id": "r"})()})
    finally:
        canva_mod.CanvaClient = original
    assert "no autofill fields" in str(exc.value)
    assert "PCIP_CANVA_MODE=mcp" in str(exc.value)


def test_plain_language_measures_prose_not_markup():
    """HTML tags are not vocabulary; counting them fails clean copy."""
    from pcip.pipelines.library import plain_language_check

    ctx = {"copy": "<p>Camine diez minutos.</p><h2>Revise sus pies</h2>"
                   "<p>Anote sus numeros cada dia.</p>",
           "brief": Brief(language="es")}
    plain_language_check(ctx)
    assert ctx["plain_language_issues"] == []


def test_plain_language_threshold_is_language_aware():
    """Spanish words are longer; one English threshold mis-flags plain Spanish."""
    from pcip.pipelines.library import plain_language_check

    spanish = ("<p>Su equipo revisa sus complicaciones y establece "
               "recomendaciones personalizadas.</p>")
    es = {"copy": spanish, "brief": Brief(language="es")}
    en = {"copy": spanish, "brief": Brief(language="en")}
    plain_language_check(es)
    plain_language_check(en)
    assert len(es["plain_language_issues"]) <= len(en["plain_language_issues"])


def test_reviewer_annotations_are_not_counted_as_patient_copy():
    from pcip.pipelines.library import plain_language_check

    ctx = {"copy": "<p>Camine diez minutos. [MEDICAL-REVIEW: verificar "
                   "contraindicaciones farmacologicas individualizadas]</p>",
           "brief": Brief(language="es")}
    plain_language_check(ctx)
    assert ctx["plain_language_issues"] == []


# ── the account's first autofill-capable template ────────────────────────────


def test_the_account_default_template_is_used_when_a_brief_names_none():
    """Unattended runs have nobody to ask. A scheduled pipeline that stops to
    request a template id is a pipeline that does not run."""
    from pcip.pipelines.library import _template_id_from

    cfg = PCIPConfig()
    brief = Brief(id="b", title="T", references=[])
    assert _template_id_from({"cfg": cfg, "brief": brief}) == cfg.canva_brand_template_id
    assert cfg.canva_brand_template_id      # a real id, not empty


def test_a_brief_reference_still_wins():
    from pcip.pipelines.library import _template_id_from

    brief = Brief(id="b", title="T",
                  references=["canva:brand_template:EAHOtherTemplate"])
    got = _template_id_from({"cfg": PCIPConfig(), "brief": brief})
    assert got == "EAHOtherTemplate"
