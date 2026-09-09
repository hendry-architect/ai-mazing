"""A long run must say what it is doing.

A pipeline printed nothing until it finished, and generate_copy alone takes
minutes against the Claude API. An operator watching a silent terminal
reasonably concludes it has hung — and there is no way to tell that apart
from a process that really is stuck.
"""

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief
from pcip.pipelines.base import Pipeline, PipelineRunner, ReviewGate, Step


def runner_with_log(pipeline, **cfg_kwargs):
    seen = []
    cfg = PCIPConfig(**cfg_kwargs)
    graph = KnowledgeGraph(":memory:")
    runner = PipelineRunner(
        cfg, graph,
        on_step=lambda name, status, detail: seen.append((name, status)),
    )
    runner.start(pipeline, Brief(id="b", title="T", brand="PassQual Health"))
    return seen


def test_each_step_is_announced_as_it_starts_and_settles():
    pipeline = Pipeline(name="p", description="test", steps=[
        Step("first", lambda ctx: "did a thing"),
        Step("second", lambda ctx: "did another"),
    ])
    assert runner_with_log(pipeline) == [
        ("first", "running"), ("first", "done"),
        ("second", "running"), ("second", "done"),
    ]


def test_a_failure_is_announced_rather_than_only_persisted():
    def boom(ctx):
        raise RuntimeError("no credentials")

    seen = runner_with_log(Pipeline(name="p", description="test", steps=[Step("bad", boom)]))
    assert seen == [("bad", "running"), ("bad", "failed")]


def test_a_pause_for_review_is_announced():
    """The gate is where the operator's attention is actually needed."""
    pipeline = Pipeline(name="p", description="test", steps=[
        Step("work", lambda ctx: "ok"),
        ReviewGate("brand_review", "check the brand"),
    ])
    assert ("brand_review", "awaiting_review") in runner_with_log(pipeline)


def test_a_handoff_pause_is_announced():
    from pcip.pipelines.base import HandoffRequired

    def needs_help(ctx):
        raise HandoffRequired("imagery", {"prompt": "x"})

    seen = runner_with_log(Pipeline(name="p", description="test", steps=[Step("art", needs_help)]))
    assert seen == [("art", "running"), ("art", "awaiting_handoff")]


def test_a_runner_without_a_callback_stays_silent(capsys):
    """Library and test callers must not have progress printed at them."""
    cfg = PCIPConfig()
    runner = PipelineRunner(cfg, KnowledgeGraph(":memory:"))
    runner.start(
        Pipeline(name="p", description="test", steps=[Step("only", lambda ctx: "fine")]),
        Brief(id="b", title="T"),
    )
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_the_printer_writes_to_stderr_so_the_summary_stays_pipeable(capsys):
    from pcip.cli import _step_printer

    report = _step_printer()
    report("generate_copy", "running")
    report("generate_copy", "done", "wrote 812 words")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "generate_copy" in captured.err
    assert "wrote 812 words" in captured.err


def test_the_printer_reports_a_step_once_when_not_a_terminal(capsys):
    """Piped to a file, a carriage return prints as a control character and
    leaves both the in-progress and the finished line."""
    from pcip.cli import _step_printer

    report = _step_printer()
    report("assemble", "running")
    report("assemble", "done", "design DAF123")
    err = capsys.readouterr().err
    assert err.count("assemble") == 1
    assert "\r" not in err


# ── why a run stopped ────────────────────────────────────────────────────


def _payload(*steps):
    return {"steps": [{"step": n, "status": s, "detail": d}
                      for n, s, d in steps]}


def test_a_failed_run_reports_the_step_and_the_reason():
    """"failed" with no reason sent three separate rounds hunting for a
    detail that was already in the record."""
    from pcip.cli import _stopped_at

    assert _stopped_at(_payload(
        ("generate_copy", "done", "Copy generated."),
        ("ph_standard", "failed", "ValueError: PH standard: 1 finding(s).\nblah"),
    )) == {"step": "ph_standard",
           "detail": "ValueError: PH standard: 1 finding(s)."}


def test_a_waiting_gate_is_reported_too():
    from pcip.cli import _stopped_at

    assert _stopped_at(_payload(
        ("assemble", "done", ""),
        ("medical_review", "awaiting_review", "Human review: medical review"),
    ))["step"] == "medical_review"


def test_a_finished_run_has_nothing_to_report():
    from pcip.cli import _stopped_at

    assert _stopped_at(_payload(("export", "done", "ok"))) == {}


def test_only_the_first_stopping_step_is_reported():
    """Later steps stay pending behind the one that stopped; naming them all
    buries the one that matters."""
    from pcip.cli import _stopped_at

    assert _stopped_at(_payload(
        ("ph_standard", "failed", "first"),
        ("assemble", "failed", "second"),
    ))["detail"] == "first"
