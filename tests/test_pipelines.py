"""Pipeline engine tests: gates pause runs, approvals resume them,
medical_review can never be auto-approved, failures are resumable."""

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief
from pcip.pipelines.base import Pipeline, PipelineRunner, ReviewGate, Step
from pcip.pipelines.library import PIPELINES, get_pipeline, plain_language_check


def make_pipeline(gate_name="brand_review", fail_step=False):
    def step_a(ctx):
        ctx["a_ran"] = True
        return "a done"

    def step_b(ctx):
        if fail_step:
            raise RuntimeError("boom")
        assert ctx.get("a_ran"), "context must persist across steps"
        return "b done"

    return Pipeline(
        name="test",
        description="test pipeline",
        steps=[
            Step("a", step_a),
            ReviewGate(gate_name, "human check"),
            Step("b", step_b),
        ],
    )


def setup():
    cfg = PCIPConfig()
    g = KnowledgeGraph(":memory:")
    return cfg, g, PipelineRunner(cfg, g), Brief(title="Test brief", topics=["testing"])


def test_gate_pauses_and_approval_resumes():
    cfg, g, runner, brief = setup()
    pipe = make_pipeline()
    run = runner.start(pipe, brief)
    assert run.status == "awaiting_review"
    assert run.current_gate == "brand_review"
    # Step b has not run yet.
    assert run.steps[2].status == "pending"

    # Approval persists via the graph and the run completes.
    runner.approve(run.id, gate="brand_review", reviewer="dr-pascual")
    reloaded = runner.load_run(run.id)
    run = runner.resume(pipe, reloaded, brief)
    assert run.status == "done"
    assert all(s.status == "done" for s in run.steps)


def test_reject_stops_run():
    cfg, g, runner, brief = setup()
    pipe = make_pipeline()
    run = runner.start(pipe, brief)
    run = runner.reject(run.id, reason="off-brand")
    assert run.status == "rejected"
    run = runner.resume(pipe, runner.load_run(run.id), brief)
    assert run.status == "rejected"
    assert run.steps[2].status == "pending"  # b never ran


def test_auto_approve_gate():
    cfg, g, runner, brief = setup()
    cfg.auto_approve_gates = ["brand_review"]
    run = runner.start(make_pipeline(), brief)
    assert run.status == "done"


def test_medical_review_never_auto_approves():
    cfg, g, runner, brief = setup()
    cfg.auto_approve_gates = ["medical_review", "brand_review"]
    run = runner.start(make_pipeline(gate_name="medical_review"), brief)
    assert run.status == "awaiting_review"
    assert run.current_gate == "medical_review"


def test_failed_step_recorded_and_resumable():
    cfg, g, runner, brief = setup()
    cfg.auto_approve_gates = ["brand_review"]
    run = runner.start(make_pipeline(fail_step=True), brief)
    assert run.status == "failed"
    assert "boom" in run.steps[2].detail
    # The run is persisted in the graph for later resume.
    assert runner.load_run(run.id).status == "failed"


def test_library_pipelines_are_well_formed():
    assert set(PIPELINES) == {
        "presentation", "podcast_kit", "blog_graphics",
        "social_campaign", "patient_education", "marketing_asset",
    }
    for name, pipe in PIPELINES.items():
        steps = pipe.step_names()
        assert "generate_copy" in steps
        assert "assemble" in steps
        assert "export" in steps
        assert "brand_review" in steps, f"{name} must have a brand review gate"
    # Patient education is the strictest pipeline.
    pe = get_pipeline("patient_education").step_names()
    assert "medical_review" in pe
    assert "plain_language" in pe
    assert pe.index("medical_review") < pe.index("export")


def test_plain_language_check_flags_dense_copy():
    dense = ("Notwithstanding pharmacokinetic contraindications, individualized "
             "antihyperglycemic pharmacotherapy necessitates comprehensive "
             "multidisciplinary reevaluation considering hepatorenal comorbidities "
             "alongside cardiovascular ramifications and immunomodulatory profiles.")
    ctx = {"copy": dense}
    plain_language_check(ctx)
    assert ctx["plain_language_issues"]

    ctx = {"copy": "Take your medicine each day. Ask us if you have questions."}
    plain_language_check(ctx)
    assert not ctx["plain_language_issues"]


# ── the copy package the standard needs ──────────────────────────────────────


def test_parse_copy_fields_keeps_the_bilingual_shape():
    """The generated block carries bodies/titles per language, not one blob."""
    from pcip.generate.orchestrator import parse_copy_fields

    fields = parse_copy_fields('''```json
{"titles": {"es": "T ES", "en": "T EN"},
 "bodies": {"es": "<p>es</p>", "en": "<p>en</p>"},
 "meta_title": "MT", "meta_description": "MD",
 "faq": [{"q": "a", "a": "b"}],
 "alt_texts_by_language": {"es": "ae", "en": "ai"}}
```''')
    assert fields["bodies"]["es"] == "<p>es</p>"
    assert fields["titles"]["en"] == "T EN"
    assert fields["meta_title"] == "MT"
    assert fields["faq"] == [{"q": "a", "a": "b"}]
    assert fields["alt_texts_by_language"]["en"] == "ai"


def test_a_truncated_block_does_not_masquerade_as_empty_copy():
    """A cut-off JSON block used to parse as 'no fields', which failed the
    standard for the wrong reason — the article existed, the ceiling was too
    low. Falling back to the raw text keeps the content visible."""
    from pcip.generate.orchestrator import parse_copy_fields

    fields = parse_copy_fields('```json\n{"bodies": {"es": "<p>empieza')
    assert not fields.get("bodies")
    assert fields["body_html"]        # the text survives somewhere


def test_structured_faq_survives_parsing():
    """faq is a list of {q, a} objects; stringifying them turned every
    question into the repr of a dict, and the FAQPage schema with it."""
    from pcip.generate.orchestrator import parse_copy_fields

    fields = parse_copy_fields(
        '```json\n{"faq": [{"q": "¿Cuánto?", "a": "Treinta minutos."}]}\n```'
    )
    assert fields["faq"][0]["q"] == "¿Cuánto?"
    assert isinstance(fields["faq"][0], dict)


def test_the_raw_block_is_not_copied_into_the_legacy_body():
    """With the bilingual shape present, body_html must stay empty — otherwise
    the whole fenced JSON gets published as the article."""
    from pcip.generate.orchestrator import parse_copy_fields

    fields = parse_copy_fields('```json\n{"bodies": {"es": "<p>real</p>"}}\n```')
    assert fields["bodies"]["es"] == "<p>real</p>"
    assert "```" not in fields["body_html"]
