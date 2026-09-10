"""The medical_review gate must involve a clinician.

A run once recorded "approved by Dr. Pascual" against medical_review and
brand_review in the same second the design was assembled, two and a half
minutes after the run started. Nobody had read anything: a block of
instructions had been pasted into a shell, and the approve commands inside
it ran with the remaining prose still queued as input. The article was fine;
the audit trail was a lie, which in a medical context is the worse failure.
"""

import pytest

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief
from pcip.pipelines.base import (
    NEVER_AUTO_APPROVE,
    Pipeline,
    PipelineRunner,
    ReviewGate,
    Step,
)


def paused_at(gate_name):
    cfg = PCIPConfig()
    runner = PipelineRunner(cfg, KnowledgeGraph(":memory:"))
    pipeline = Pipeline(name="p", description="t", steps=[
        Step("work", lambda ctx: "done"),
        ReviewGate(gate_name, "review it"),
    ])
    run = runner.start(pipeline, Brief(id="b", title="T"))
    assert run.status == "awaiting_review"
    return runner, run


def test_medical_review_refuses_an_approval_that_cannot_say_how():
    runner, run = paused_at("medical_review")
    with pytest.raises(PermissionError, match="how it was confirmed"):
        runner.approve(run.id, "medical_review", "Dr. Pascual")


def test_medical_review_refuses_an_unnamed_reviewer():
    runner, run = paused_at("medical_review")
    with pytest.raises(PermissionError, match="named reviewer"):
        runner.approve(run.id, "medical_review", "  ", how="typed")


def test_a_confirmed_approval_records_how_in_the_audit_trail():
    runner, run = paused_at("medical_review")
    run = runner.approve(run.id, "medical_review", "Dr. Pascual",
                         how="typed at the terminal")
    detail = next(s.detail for s in run.steps if s.step == "medical_review")
    assert "Dr. Pascual" in detail
    assert "typed at the terminal" in detail


def test_other_gates_are_unaffected():
    """brand_review is a judgement call, not a clinical one — it does not
    need the same ceremony."""
    runner, run = paused_at("brand_review")
    run = runner.approve(run.id, "brand_review", "Dr. Pascual")
    assert "approved by Dr. Pascual" in next(
        s.detail for s in run.steps if s.step == "brand_review"
    )


def test_the_gate_list_still_names_medical_review():
    assert "medical_review" in NEVER_AUTO_APPROVE


# ── the terminal boundary ────────────────────────────────────────────────


class _NotATty:
    def isatty(self):
        return False

    def read(self):
        return "approve"


class _Tty:
    def __init__(self):
        self.flushed = False

    def isatty(self):
        return True

    def fileno(self):
        return 0


def test_a_pipe_cannot_approve_a_clinician_gate(monkeypatch):
    """A script or a pipe answering this prompt is the one thing the gate
    exists to prevent."""
    from pcip import cli

    monkeypatch.setattr("sys.stdin", _NotATty())
    _, run = paused_at("medical_review")
    with pytest.raises(PermissionError, match="not a tty"):
        cli._confirm_clinician_review(run, "medical_review")


def test_anything_but_approve_aborts(monkeypatch):
    from pcip import cli

    monkeypatch.setattr("sys.stdin", _Tty())
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    _, run = paused_at("medical_review")
    with pytest.raises(PermissionError, match="not approved"):
        cli._confirm_clinician_review(run, "medical_review")


def test_typing_approve_confirms(monkeypatch):
    from pcip import cli

    monkeypatch.setattr("sys.stdin", _Tty())
    monkeypatch.setattr("builtins.input", lambda *_: "  Approve  ")
    _, run = paused_at("medical_review")
    assert cli._confirm_clinician_review(run, "medical_review") == (
        "typed at the terminal"
    )


def test_queued_keystrokes_are_discarded_before_asking(monkeypatch):
    """The whole mechanism: input already waiting when the prompt appears
    was typed — or pasted — before the reviewer could have read anything."""
    from pcip import cli

    flushed = []
    monkeypatch.setattr("sys.stdin", _Tty())
    monkeypatch.setattr("builtins.input", lambda *_: "approve")
    monkeypatch.setattr("termios.tcflush",
                        lambda stream, which: flushed.append(which))
    _, run = paused_at("medical_review")
    cli._confirm_clinician_review(run, "medical_review")
    assert flushed, "the terminal input queue was not flushed"


# ── what the reviewer is shown ───────────────────────────────────────────


def test_the_summary_names_the_prices_being_approved():
    """A membership article's prices are the thing most worth a second
    pair of eyes."""
    from pcip import cli

    _, run = paused_at("medical_review")
    run.context["copy_fields"] = {
        "titles": {"es": "Membresía", "en": "Membership"},
        "bodies": {"es": "<p>Desde $79 al mes, o $790 al año.</p>",
                   "en": "<p>From $79 a month.</p>"},
    }
    run.context["design_id"] = "DAF123"
    summary = cli._review_summary(run)
    assert "$79" in summary and "$790" in summary
    assert "Membresía" in summary and "Membership" in summary
    assert "DAF123" in summary


def test_the_summary_survives_a_run_with_no_copy():
    from pcip import cli

    _, run = paused_at("medical_review")
    assert "no generated copy" in cli._review_summary(run)
