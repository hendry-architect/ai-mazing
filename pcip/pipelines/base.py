"""Pipeline engine.

A Pipeline is a declarative sequence of Steps. Two step types exist:

- ``Step``       — an action (generate copy, autofill a template, export)
                   executed by a handler function.
- ``ReviewGate`` — a human checkpoint. Execution pauses with the run in
                   ``awaiting_review`` until someone approves or rejects it
                   (``pcip approve <run_id>`` / ``pcip reject <run_id>``).

Runs are persisted in the knowledge graph, so approval can happen in a later
CLI invocation, a cron job, or another tool entirely. Gates listed in
``PCIP_AUTO_APPROVE_GATES`` are passed automatically — medical_review is
deliberately refused auto-approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from pcip.config import PCIPConfig
from pcip.redact import redact_urls
from pcip.models import (
    Brief,
    EdgeKind,
    NodeKind,
    PipelineRun,
    StepResult,
    now_iso,
)
from pcip.graph.store import KnowledgeGraph

# A step handler receives a mutable context dict and returns a human-readable
# detail string. The context carries: cfg, graph, brief, run, and anything
# earlier steps stored (e.g. ctx["copy"], ctx["design_id"], ctx["export_paths"]).
StepHandler = Callable[[Dict[str, Any]], str]

# Gates that may never be auto-approved, regardless of configuration.
NEVER_AUTO_APPROVE = frozenset({"medical_review"})


class HandoffRequired(Exception):
    """A step needs work done outside PCIP before it can complete.

    Raised by steps that run through the Canva MCP connector: PCIP cannot
    call those tools itself, so it pauses the run, states exactly what it
    needs, and continues once ``pcip attach`` supplies the result. This is a
    pause, not a failure — every later gate still applies.
    """

    def __init__(self, needs: str, spec: Dict[str, Any]) -> None:
        super().__init__(f"handoff required: {needs}")
        self.needs = needs
        self.spec = spec


@dataclass
class Step:
    name: str
    handler: StepHandler
    description: str = ""


@dataclass
class ReviewGate:
    name: str
    description: str = ""


@dataclass
class Pipeline:
    name: str
    description: str
    steps: List[Union[Step, ReviewGate]] = field(default_factory=list)

    def step_names(self) -> List[str]:
        return [s.name for s in self.steps]


class PipelineRunner:
    """Executes pipelines, persisting run state to the graph at every step."""

    def __init__(self, config: PCIPConfig, graph: KnowledgeGraph) -> None:
        self.cfg = config
        self.graph = graph

    # ── Persistence ──────────────────────────────────────────────────────

    def _save(self, run: PipelineRun) -> None:
        run.updated_at = now_iso()
        self.graph.upsert_node(
            run.id,
            NodeKind.PIPELINE_RUN,
            f"{run.pipeline} [{run.status}]",
            run.to_dict(),
        )

    def load_run(self, run_id: str) -> Optional[PipelineRun]:
        node = self.graph.get_node(run_id)
        if not node or node["kind"] != NodeKind.PIPELINE_RUN.value:
            return None
        return PipelineRun.from_dict(node["payload"])

    # ── Execution ────────────────────────────────────────────────────────

    def start(self, pipeline: Pipeline, brief: Brief) -> PipelineRun:
        run = PipelineRun(
            pipeline=pipeline.name,
            brief_id=brief.id,
            steps=[StepResult(step=s.name) for s in pipeline.steps],
        )
        self.graph.upsert_node(brief.id, NodeKind.BRIEF, brief.title, brief.to_dict())
        self._save(run)
        self.graph.add_edge(run.id, EdgeKind.FROM_BRIEF, brief.id)
        return self._advance(pipeline, run, brief)

    def resume(self, pipeline: Pipeline, run: PipelineRun, brief: Brief) -> PipelineRun:
        return self._advance(pipeline, run, brief)

    _RESERVED_CTX = ("cfg", "graph", "brief", "run")

    def _advance(self, pipeline: Pipeline, run: PipelineRun, brief: Brief) -> PipelineRun:
        ctx: Dict[str, Any] = {
            "cfg": self.cfg,
            "graph": self.graph,
            "brief": brief,
            "run": run,
        }
        # Restore working state persisted by earlier (pre-pause) steps.
        ctx.update(run.context)

        run.status = "running"
        for spec, sr in zip(pipeline.steps, run.steps):
            if sr.status in ("done",):
                continue
            if sr.status == "rejected":
                run.status = "rejected"
                self._save(run)
                return run

            if isinstance(spec, ReviewGate):
                if sr.status == "approved":
                    sr.status = "done"
                    sr.finished_at = now_iso()
                    self._save(run)
                    continue
                if (
                    spec.name in self.cfg.auto_approve_gates
                    and spec.name not in NEVER_AUTO_APPROVE
                ):
                    sr.status = "done"
                    sr.detail = "auto-approved (PCIP_AUTO_APPROVE_GATES)"
                    sr.finished_at = now_iso()
                    self._save(run)
                    continue
                sr.status = "awaiting_review"
                sr.detail = spec.description
                run.status = "awaiting_review"
                self._save(run)
                return run

            # Action step
            sr.status = "running"
            sr.started_at = now_iso()
            self._save(run)
            try:
                sr.detail = spec.handler(ctx) or ""
                sr.outputs = list(ctx.pop("_step_outputs", []))
                sr.status = "done"
            except HandoffRequired as handoff:
                # Not a failure: work is owed from outside PCIP. Record what
                # is needed so `pcip runs` / `pcip attach` can act on it.
                sr.status = "awaiting_handoff"
                sr.detail = f"needs {handoff.needs}"
                sr.finished_at = ""
                run.status = "awaiting_handoff"
                run.context["handoff"] = {"needs": handoff.needs,
                                          "step": sr.step, **handoff.spec}
                self._persist_context(run, ctx)
                self._save(run)
                return run
            except Exception as exc:  # persist failures; runs are resumable
                sr.status = "failed"
                sr.detail = redact_urls(f"{type(exc).__name__}: {exc}")
                run.status = "failed"
                sr.finished_at = now_iso()
                self._save(run)
                return run
            sr.finished_at = now_iso()
            for out in sr.outputs:
                self.graph.add_edge(run.id, EdgeKind.PRODUCED, out)
            self._persist_context(run, ctx)
            self._save(run)

        run.status = "done"
        self._save(run)
        return run

    def _persist_context(self, run: PipelineRun, ctx: Dict[str, Any]) -> None:
        """Copy JSON-serializable working state into the run record."""
        import json

        for key, value in ctx.items():
            if key in self._RESERVED_CTX or key.startswith("_"):
                continue
            try:
                json.dumps(value, default=str)
            except (TypeError, ValueError):
                continue
            run.context[key] = value

    # ── Review actions ───────────────────────────────────────────────────

    def approve(self, run_id: str, gate: Optional[str] = None, reviewer: str = "") -> PipelineRun:
        run = self._require_run(run_id)
        sr = self._gate_step(run, gate)
        sr.status = "approved"
        sr.detail = f"approved by {reviewer or 'reviewer'} at {now_iso()}"
        self._save(run)
        return run

    def reject(self, run_id: str, gate: Optional[str] = None, reason: str = "") -> PipelineRun:
        run = self._require_run(run_id)
        sr = self._gate_step(run, gate)
        sr.status = "rejected"
        sr.detail = f"rejected: {reason or 'no reason given'} ({now_iso()})"
        run.status = "rejected"
        self._save(run)
        return run

    def _require_run(self, run_id: str) -> PipelineRun:
        run = self.load_run(run_id)
        if not run:
            raise KeyError(f"No pipeline run '{run_id}' in the graph.")
        return run

    @staticmethod
    def _gate_step(run: PipelineRun, gate: Optional[str]) -> StepResult:
        for sr in run.steps:
            if sr.status == "awaiting_review" and (gate is None or sr.step == gate):
                return sr
        raise ValueError(
            f"Run {run.id} has no gate awaiting review"
            + (f" named '{gate}'" if gate else "")
        )
