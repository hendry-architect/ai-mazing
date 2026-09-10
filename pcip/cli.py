"""PCIP command-line interface.

    python -m pcip init                          # create the data dir + graph
    python -m pcip status                        # connector + graph health
    python -m pcip sync                          # mirror Canva library → graph
    python -m pcip search "diabetes carousel"    # full-text search the graph
    python -m pcip graph <node_id> [--depth 2]   # everything about one node
    python -m pcip pipelines                     # list available pipelines
    python -m pcip run patient_education --brief brief.json
    python -m pcip runs                          # list pipeline runs
    python -m pcip approve <run_id> [--gate medical_review] [--reviewer name]
    python -m pcip reject  <run_id> [--reason "..."]
    python -m pcip resume  <run_id>              # continue after approval
    python -m pcip attach <run_id> --design-id <id>   # fulfil a Canva handoff
    python -m pcip prepare <output_id>            # article for manual publishing
    python -m pcip publish <output_id> --channel wordpress --title "..." [--live]
"""

from __future__ import annotations

import argparse
import json
import re
import pathlib
import sys
from typing import Any, Dict

from pcip.config import PCIPConfig, load_config
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief, NodeKind
from pcip.pipelines.base import NEVER_AUTO_APPROVE


def _graph(cfg: PCIPConfig) -> KnowledgeGraph:
    cfg.ensure_dirs()
    return KnowledgeGraph(cfg.graph_db_path)


def _print(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ─── Commands ────────────────────────────────────────────────────────────────


def cmd_init(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    cfg.ensure_dirs()
    with _graph(cfg) as g:
        _print({"initialized": True, **g.stats()})
    return 0


def cmd_status(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Where everything stands, in one command.

    "check" is the question actually being asked, and answering it used to
    take three: doctor for credentials, runs for what is in flight, outputs
    for what is finished. Whatever is unfinished is the part worth seeing
    first, so it goes at the top.
    """
    from pcip.generate.providers import ProviderRegistry

    with _graph(cfg) as g:
        runs = [
            {
                "run_id": r["id"],
                "pipeline": r["payload"].get("pipeline"),
                "status": r["payload"].get("status"),
                **({"stopped_at": stopped}
                   if (stopped := _stopped_at(r["payload"])) else {}),
            }
            for r in g.nodes_by_kind(NodeKind.PIPELINE_RUN, limit=20)
            if r["payload"].get("status") not in ("done", "rejected")
        ]
        published = _published_output_ids(g)
        outputs = [
            {"output_id": o["id"], "name": o["name"][:70],
             "published": o["id"] in published}
            for o in g.nodes_by_kind(NodeKind.OUTPUT, limit=5)
        ]
        _print(
            {
                "unfinished_runs": runs or "none",
                "recent_outputs": outputs or "none",
                "connectors": cfg.channel_status(),
                "providers": ProviderRegistry(cfg).status(),
                "graph": g.stats(),
            }
        )
    return 0


def cmd_sync(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    from pcip.connectors.canva import CanvaClient
    from pcip.graph.indexer import CanvaIndexer

    with _graph(cfg) as g:
        counts = CanvaIndexer(CanvaClient(cfg), g).sync(
            include_folders=not args.no_folders
        )
        _print({"synced": counts, "graph": g.stats()})
    return 0


def cmd_search(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    with _graph(cfg) as g:
        results = g.search(
            args.query, kinds=[args.kind] if args.kind else None, limit=args.limit
        )
        _print(
            [
                {"id": r["id"], "kind": r["kind"], "name": r["name"]}
                for r in results
            ]
        )
    return 0


def cmd_graph(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    with _graph(cfg) as g:
        _print(g.subgraph(args.node_id, depth=args.depth))
    return 0


def cmd_canva_auth(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """One-command Canva OAuth (PKCE) — writes tokens into .env."""
    from pcip.connectors.canva_auth import (
        finish_manual_flow,
        run_flow,
        start_manual_flow,
    )

    write_env = None if args.no_write else args.env_file
    if args.start:
        if not args.redirect_uri:
            print("error: --start needs --redirect-uri (the URL registered on "
                  "your Canva integration)", file=sys.stderr)
            return 1
        start_manual_flow(cfg, args.redirect_uri,
                          open_browser=not args.no_browser)
        return 0
    if args.finish:
        finish_manual_flow(cfg, code=args.code, code_file=args.code_file,
                           write_env=write_env)
        return 0

    run_flow(
        cfg,
        port=args.port,
        write_env=write_env,
        open_browser=not args.no_browser,
        redirect_uri=args.redirect_uri,
        manual=args.manual,
    )
    return 0


def cmd_doctor(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Diagnose connectors against the bootstrap.yaml manifest."""
    from pcip.connectors.framework import ConnectorManager, load_manifest

    manager = ConnectorManager(cfg, manifest=load_manifest(args.manifest))
    report = manager.doctor(live=args.live)
    if args.table:
        _doctor_table(report)
    else:
        _print(report)
    return 0 if not report["actions"] else 1


#: Statuses that mean the connector can be used right now.
_USABLE = {"ready", "mcp_managed"}


def _doctor_table(report: dict) -> None:
    """The same report, readable.

    The JSON carries every capability and note, which is right for a machine
    and unreadable on a terminal — the answer to "did that work?" was buried
    hundreds of lines down. This prints the line that answers it.
    """
    connectors = report["connectors"]
    wanted = {k: v for k, v in connectors.items() if v.get("desired")}
    others = {k: v for k, v in connectors.items() if not v.get("desired")}

    def rows(group: dict) -> None:
        for name, c in sorted(group.items()):
            mark = "OK  " if c["status"] in _USABLE else "--  "
            detail = (c.get("detail") or "").split(";")[0][:58]
            print(f"  {mark}{name:<12} {c['status']:<20} {detail}")

    print("REQUESTED IN bootstrap.yaml")
    rows(wanted)
    if others:
        print("\nAVAILABLE, NOT REQUESTED")
        rows(others)

    usable = sum(1 for c in wanted.values() if c["status"] in _USABLE)
    print(f"\n{usable} of {len(wanted)} requested connectors usable.")
    if report["actions"]:
        print("\nTO FIX:")
        for action in report["actions"]:
            print(f"  - {action}")


def cmd_can(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Planner-style capability query: pcip can canva.export_png"""
    from pcip.connectors.framework import ConnectorManager

    answer = ConnectorManager(cfg).can(args.capability, live=args.live)
    _print(answer)
    return 0 if answer.get("usable") else 1


def cmd_media_plan(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Preview which provider the capability registry would pick."""
    from pcip.generate.capabilities import default_registry, spec_for
    from pcip.generate.providers import ProviderRegistry

    spec = spec_for(args.content_type)
    registry = ProviderRegistry(cfg)
    available = registry.available_names(spec.modality)
    ranked = default_registry().rank(spec, available)
    all_ranked = default_registry().rank(spec)
    _print({
        "content_type": args.content_type,
        "spec": spec.__dict__,
        "configured_providers": available,
        "routing": [{"provider": n, "score": round(s, 3)} for n, s in ranked],
        "would_route_if_all_configured": [
            {"provider": n, "score": round(s, 3)} for n, s in all_ranked
        ],
    })
    return 0


def cmd_route(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Preview the publish decision engine's routing for a channel."""
    from pcip.publish.router import PublishRouter

    with _graph(cfg) as g:
        _print(PublishRouter(cfg, g).route_plan(args.channel, scheduled=args.scheduled))
    return 0


def cmd_pipelines(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    from pcip.pipelines.library import PIPELINES

    _print(
        {
            name: {"description": p.description, "steps": p.step_names()}
            for name, p in PIPELINES.items()
        }
    )
    return 0


def _run_summary(run: Any) -> dict:
    summary = {
        "run_id": run.id,
        "pipeline": run.pipeline,
        "status": run.status,
        "awaiting_gate": run.current_gate,
        "steps": [{"step": s.step, "status": s.status, "detail": s.detail}
                  for s in run.steps],
    }
    handoff = run.pending_handoff
    if handoff:
        summary["awaiting_handoff"] = handoff
    return summary


def _resolve_run_id(graph: Any, run_id: str) -> str:
    """Turn 'latest' into a real run id.

    Every instruction that contained a placeholder for this has cost a round —
    someone pastes <RUN_ID> literally, because that is what the instruction
    said. Preferring a run that is actually waiting on a handoff makes the
    common case need no id at all.
    """
    if run_id and run_id != "latest":
        return run_id
    runs = graph.nodes_by_kind(NodeKind.PIPELINE_RUN, limit=50)
    if not runs:
        raise SystemExit("error: no pipeline runs exist yet — start one with `pcip run`")
    waiting = [r for r in runs
               if (r["payload"].get("status") or "") in ("awaiting_handoff",
                                                         "awaiting_review")]
    chosen = (waiting or runs)[0]
    return chosen["id"]


def _published_output_ids(graph: Any) -> set:
    return {
        (p["payload"].get("output_id") or "")
        for p in graph.nodes_by_kind(NodeKind.PUBLICATION, limit=200)
    }


def _resolve_output_id(graph: Any, output_id: str) -> str:
    """Turn 'latest' into a real output id.

    Same reasoning as _resolve_run_id, and the same evidence: an instruction
    reading `pcip publish <output_id>` gets pasted verbatim, and the shell
    reads the angle brackets as a redirect. The id is knowable, so PCIP
    should know it. An output nobody has published yet is preferred, since
    that is what someone reaching for "the latest one" means.
    """
    if output_id and output_id != "latest":
        return output_id
    outputs = graph.nodes_by_kind(NodeKind.OUTPUT, limit=50)
    if not outputs:
        raise SystemExit(
            "error: no outputs exist yet — run a pipeline through to export"
        )
    published = _published_output_ids(graph)
    unpublished = [o for o in outputs if o["id"] not in published]
    return (unpublished or outputs)[0]["id"]


def cmd_outputs(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """List finished deliverables, newest first, and whether each is live."""
    with _graph(cfg) as g:
        outputs = g.nodes_by_kind(NodeKind.OUTPUT, limit=args.limit)
        published = _published_output_ids(g)
        if not outputs:
            print("no outputs yet — run a pipeline through to export")
            return 0
        for o in outputs:
            mark = "published" if o["id"] in published else "unpublished"
            print(f"  {o['id']}  {mark:<12}{o['name'][:64]}")
    return 0


def cmd_attach(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Fulfil a handoff: attach the Canva design or exported files, then resume."""
    from pcip.pipelines.library import get_pipeline

    with _graph(cfg) as g:
        runner, run, brief = _load_run_and_brief(cfg, g, args.run_id)
        if not runner:
            return 1
        supplied = {
            "design_id": args.design_id,
            "design_url": args.design_url,
            "design_title": args.design_title,
            "brand_template_id": args.template_id,
        }
        for key, value in supplied.items():
            if value:
                run.context[key] = value
        if args.export_file:
            run.context["export_files"] = list(args.export_file)
        if args.export_url:
            run.context["_export_urls"] = list(args.export_url)
        if args.copy_file:
            fields = json.loads(pathlib.Path(args.copy_file).read_text(encoding="utf-8"))
            run.context["copy_fields"] = fields
            run.context["copy"] = fields.get("body_html", "") or run.context.get("copy", "")
        if not any(supplied.values()) and not (
            args.export_file or args.export_url or args.copy_file
        ):
            print("error: nothing to attach — pass --copy-file, --design-id, "
                  "--export-url and/or --export-file",
                  file=sys.stderr)
            return 1
        run = runner.fulfil_handoff(get_pipeline(run.pipeline), run, brief)
        _print(_run_summary(run))
    return 0 if run.status not in ("failed", "rejected") else 1


def _step_printer():
    """Say what a run is doing, on stderr, while it does it.

    A pipeline printed nothing until it finished, and generate_copy alone
    takes minutes — an operator watching a silent terminal reasonably
    concludes it has hung, and there is no way to tell that apart from a
    process that really is stuck. Progress goes to stderr so the JSON
    summary on stdout stays pipeable.
    """
    import time

    started: Dict[str, float] = {}
    # Overwriting the in-progress line needs a terminal. Piped to a file or
    # a pager, a carriage return prints as a control character and leaves
    # both lines, so there the step is announced only once it settles.
    live = sys.stderr.isatty()

    def report(name: str, status: str, detail: str = "") -> None:
        if status == "running":
            started[name] = time.monotonic()
            if live:
                print(f"  ... {name}", end="", flush=True, file=sys.stderr)
            return
        secs = time.monotonic() - started.pop(name, time.monotonic())
        mark = {"done": "ok", "failed": "FAILED",
                "awaiting_handoff": "PAUSED", "awaiting_review": "REVIEW"}
        line = (f"  {mark.get(status, status):<7}{name} ({secs:.0f}s)"
                + (f" - {detail.splitlines()[0][:60]}" if detail else ""))
        print((f"\r{line:<100}" if live else line), file=sys.stderr, flush=True)

    return report


def cmd_run(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    from pcip.pipelines.base import PipelineRunner
    from pcip.pipelines.library import get_pipeline

    brief = Brief.from_json_file(args.brief)
    pipeline = get_pipeline(args.pipeline)
    print(f"{pipeline.name}: {len(pipeline.steps)} steps. Copy and imagery "
          "call external APIs and take minutes.", file=sys.stderr)
    with _graph(cfg) as g:
        runner = PipelineRunner(cfg, g, on_step=None if args.quiet
                                else _step_printer())
        run = runner.start(pipeline, brief)
        _print(_run_summary(run))
    return 0 if run.status in ("done", "awaiting_review") else 1


def _stopped_at(payload: Dict[str, Any]) -> Dict[str, str]:
    """The step a run is sitting on, and what it said.

    "failed" with no reason has now sent three separate rounds hunting for
    the detail that was already in the record. The step that stopped the run
    is the first thing anyone wants.
    """
    for sr in payload.get("steps") or []:
        if sr.get("status") in ("failed", "awaiting_review", "awaiting_handoff",
                                "running", "rejected"):
            # Not just the first line: a standards failure opens with
            # "PH standard: 1 finding(s)." and puts the finding underneath,
            # so taking one line reported the count and hid the reason.
            lines = [ln.strip() for ln in (sr.get("detail") or "").splitlines()
                     if ln.strip()]
            return {"step": sr.get("step", ""),
                    "detail": " | ".join(lines)[:400]}
    return {}


def cmd_runs(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    with _graph(cfg) as g:
        runs = g.nodes_by_kind(NodeKind.PIPELINE_RUN, limit=args.limit)
        _print(
            [
                {
                    "run_id": r["id"],
                    "pipeline": r["payload"].get("pipeline"),
                    "status": r["payload"].get("status"),
                    "updated_at": r["payload"].get("updated_at"),
                    **({"stopped_at": stopped}
                       if (stopped := _stopped_at(r["payload"])) else {}),
                }
                for r in runs
            ]
        )
    return 0


def _load_run_and_brief(cfg: PCIPConfig, g: KnowledgeGraph, run_id: str):
    from pcip.pipelines.base import PipelineRunner
    from pcip.pipelines.library import get_pipeline

    runner = PipelineRunner(cfg, g)
    run = runner.load_run(run_id)
    if not run:
        print(f"error: no run '{run_id}'", file=sys.stderr)
        return None, None, None
    brief_node = g.get_node(run.brief_id)
    brief = Brief.from_dict(brief_node["payload"]) if brief_node else Brief()
    return runner, run, brief


def _pending_gate(run) -> str:
    for sr in run.steps:
        if sr.status == "awaiting_review":
            return sr.step
    return ""


def _review_summary(run) -> str:
    """What the reviewer is being asked to approve, in one screen."""
    from pcip.standards.membership import stated_amounts

    fields = (run.context or {}).get("copy_fields") or {}
    bodies = {k: v for k, v in (fields.get("bodies") or {}).items() if v}
    lines = [f"  run        {run.id}  ({run.pipeline})"]
    for lang, title in (fields.get("titles") or {}).items():
        words = len(re.sub(r"<[^>]+>", " ", bodies.get(lang, "")).split())
        lines.append(f"  {lang:<10} {title[:62]}  [{words} words]")
    if not bodies:
        lines.append("  (no generated copy on this run)")
    amounts = sorted(set(stated_amounts(" ".join(bodies.values()))))
    if amounts:
        lines.append("  prices     " + ", ".join(f"${a:,}" for a in amounts))
    if run.context.get("design_id"):
        lines.append(f"  design     {run.context['design_id']}")
    return "\n".join(lines)


def _confirm_clinician_review(run, gate: str) -> str:
    """Ask the reviewer directly, in a way a pasted script cannot answer.

    Flushing the terminal's input queue first is the whole point: the defect
    this exists for was a block of instructions pasted into a shell, where
    the approve commands ran with the prose still queued behind them. Any
    keystrokes already waiting are discarded, so the answer has to be typed
    after this prompt appears.
    """
    import sys

    if not sys.stdin.isatty():
        raise PermissionError(
            f"{gate} needs a person at a terminal. stdin is not a tty, so "
            "this approval would be coming from a script or a pipe — which "
            "is the one thing this gate exists to prevent."
        )
    try:
        import termios

        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:                      # noqa: BLE001 — best effort
        pass

    print(f"\n{gate.upper()} — you are approving:\n", file=sys.stderr)
    print(_review_summary(run), file=sys.stderr)
    print("\nRead the article before answering. Type 'approve' to confirm, "
          "anything else to abort.", file=sys.stderr)
    answer = input("> ").strip().lower()
    if answer != "approve":
        raise PermissionError(f"{gate} not approved (answer was {answer!r}).")
    return "typed at the terminal"


def cmd_approve(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    with _graph(cfg) as g:
        args.run_id = _resolve_run_id(g, args.run_id)
        runner, run, brief = _load_run_and_brief(cfg, g, args.run_id)
        if not runner:
            return 1
        gate = args.gate or _pending_gate(run)
        how = ""
        if gate in NEVER_AUTO_APPROVE:
            how = _confirm_clinician_review(run, gate)
        runner.approve(args.run_id, gate=args.gate, reviewer=args.reviewer,
                       how=how)
        from pcip.pipelines.library import get_pipeline

        run = runner.load_run(args.run_id)
        run = runner.resume(get_pipeline(run.pipeline), run, brief)
        _print(_run_summary(run))
    return 0


def cmd_reject(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    with _graph(cfg) as g:
        args.run_id = _resolve_run_id(g, args.run_id)
        runner, run, brief = _load_run_and_brief(cfg, g, args.run_id)
        if not runner:
            return 1
        run = runner.reject(args.run_id, gate=args.gate, reason=args.reason)
        _print(_run_summary(run))
    return 0


def cmd_resume(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    from pcip.pipelines.library import get_pipeline

    with _graph(cfg) as g:
        args.run_id = _resolve_run_id(g, args.run_id)
        runner, run, brief = _load_run_and_brief(cfg, g, args.run_id)
        if not runner:
            return 1
        run = runner.resume(get_pipeline(run.pipeline), run, brief)
        _print(_run_summary(run))
    return 0 if run.status in ("done", "awaiting_review") else 1


def cmd_prepare(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Produce a reviewed article for manual publishing — no network calls."""
    from pcip.publish.router import PublishRouter

    with _graph(cfg) as g:
        result = PublishRouter(cfg, g).prepare(
            _resolve_output_id(g, args.output_id),
            title=args.title, text=args.text, dest=args.dest
        )
        _print(result)
    return 0


def cmd_publish(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    from pcip.publish.router import PublishRouter

    if getattr(args, "transport", ""):
        cfg.wordpress_transport = args.transport
    with _graph(cfg) as g:
        args.output_id = _resolve_output_id(g, args.output_id)
        print(f"publishing {args.output_id}", file=sys.stderr)
        pub = PublishRouter(cfg, g).publish(
            args.output_id,
            args.channel,
            title=args.title,
            text=args.text,
            live=args.live,
            schedule_at=args.schedule_at,
            republish=getattr(args, "republish", False),
            dry_run=getattr(args, "dry_run", False),
        )
        _print(pub.to_dict())
        if pub.metadata.get("dry_run"):
            _report_dry_run(pub)
    return 0


def _report_dry_run(pub) -> None:
    """Say plainly what a rehearsal did and did not establish."""
    meta = pub.metadata
    print(f"\nDRY RUN — nothing was posted to {pub.channel.value}.")
    print(f"  adapter        {meta['adapter']} ({meta['mode']} mode"
          + (", fallback" if meta["fallback_used"] else "") + ")")
    print(f"  caption        {meta['caption_chars']} characters")
    print(f"  requests       {len(meta['requests'])} would have been sent")
    if meta["missing_credentials"]:
        print("  NOT CONFIGURED " + ", ".join(meta["missing_credentials"]))
        print("                 the request shape above is real; the "
              "credentials in it are placeholders, so a live run would stop "
              "at authentication.")
    if meta["would_fail"]:
        print(f"  WOULD FAIL     {meta['error']}")
    elif not meta["missing_credentials"]:
        print("  ready          every credential is set and the adapter "
              "completed against the recording transport.")


def cmd_record(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Write down a publication that happened outside PCIP."""
    from pcip.publish.router import PublishRouter

    with _graph(cfg) as g:
        pub = PublishRouter(cfg, g).record_manual(
            args.output_id,
            args.channel,
            url=args.url,
            external_id=args.external_id,
            note=args.note,
            published_at=args.published_at,
        )
        _print(pub.to_dict())
    return 0


def cmd_retract(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Trash every published copy of an output and mark the record retracted."""
    from pcip.publish.router import PublishRouter

    with _graph(cfg) as g:
        pubs = PublishRouter(cfg, g).retract(args.output_id, reason=args.reason)
        if not pubs:
            print(f"nothing published for {args.output_id} — nothing to retract")
            return 0
        _print([p.to_dict() for p in pubs])
    return 0


# ─── Parser ──────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pcip",
        description="PassQual Creative Intelligence Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--data-dir", default=None, help="override PCIP_DATA_DIR")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the data dir and graph database")
    sub.add_parser("status", help="connector, provider, and graph health")

    sp = sub.add_parser("sync", help="mirror the Canva library into the graph")
    sp.add_argument("--no-folders", action="store_true")

    sp = sub.add_parser("search", help="full-text search the knowledge graph")
    sp.add_argument("query")
    sp.add_argument("--kind", default="", help="filter by node kind")
    sp.add_argument("--limit", type=int, default=25)

    sp = sub.add_parser("graph", help="subgraph around a node")
    sp.add_argument("node_id")
    sp.add_argument("--depth", type=int, default=2)

    sub.add_parser("pipelines", help="list available pipelines")

    sp = sub.add_parser("canva-auth", help="run the Canva OAuth (PKCE) flow once")
    sp.add_argument("--port", type=int, default=8080,
                    help="local callback port (redirect URL must match)")
    sp.add_argument("--env-file", default=".env")
    sp.add_argument("--no-write", action="store_true",
                    help="print instead of writing tokens to the env file")
    sp.add_argument("--no-browser", action="store_true")
    sp.add_argument("--redirect-uri", default="",
                    help="hosted callback registered on the integration "
                         "(e.g. https://passqual.com/canva/callback). Canva "
                         "requires a non-localhost URL to review a PUBLIC "
                         "integration; a private one can keep localhost.")
    sp.add_argument("--manual", action="store_true",
                    help="paste the authorization code instead of catching it "
                         "locally — required with a hosted redirect, since the "
                         "code arrives in a browser, not on this machine")
    sp.add_argument("--start", action="store_true",
                    help="step 1 of the hosted-redirect flow: print the "
                         "authorization URL and remember this flow's PKCE "
                         "verifier, so the code can arrive by pipe or file "
                         "rather than through a terminal prompt")
    sp.add_argument("--finish", action="store_true",
                    help="step 2: complete the flow started by --start, "
                         "reading the redirected URL from --code/--code-file "
                         "or from stdin (e.g. pbpaste | python -m pcip "
                         "canva-auth --finish)")
    sp.add_argument("--code", default="",
                    help="the redirected URL or bare code, for --finish")
    sp.add_argument("--code-file", default="",
                    help="a file holding the redirected URL, for --finish — "
                         "keeps the code out of shell history")

    sp = sub.add_parser("outputs", help="list finished deliverables")
    sp.add_argument("--limit", type=int, default=10)

    sp = sub.add_parser("doctor", help="diagnose connectors from bootstrap.yaml")
    sp.add_argument("--live", action="store_true",
                    help="run live auth/entitlement probes")
    sp.add_argument("--table", action="store_true",
                    help="one line per connector instead of the full JSON")
    sp.add_argument("--manifest", default=None, help="path to bootstrap.yaml")

    sp = sub.add_parser("can", help="capability query, e.g. canva.export_png")
    sp.add_argument("capability")
    sp.add_argument("--live", action="store_true")

    sp = sub.add_parser("media-plan", help="preview capability-based provider routing")
    sp.add_argument("content_type",
                    help="healthcare_photo | infographic | social_quote | blog_hero"
                         " | cinematic_video | quick_reel | stylized_motion")

    sp = sub.add_parser("route", help="preview publish routing for a channel")
    sp.add_argument("channel")
    sp.add_argument("--scheduled", action="store_true",
                    help="preview the scheduled-campaign route (scheduler-first)")

    sp = sub.add_parser("run", help="run a pipeline from a brief JSON file")
    sp.add_argument("pipeline")
    sp.add_argument("--brief", required=True, help="path to brief JSON")
    sp.add_argument("--quiet", action="store_true",
                    help="suppress the per-step progress lines on stderr")

    sp = sub.add_parser("runs", help="list pipeline runs")
    sp.add_argument("--limit", type=int, default=20)

    sp = sub.add_parser("approve", help="approve a review gate and continue")
    sp.add_argument("run_id", nargs="?", default="latest",
                    help="run id, or omit for the run awaiting review")
    sp.add_argument("--gate", default=None)
    sp.add_argument("--reviewer", default="")

    sp = sub.add_parser("reject", help="reject a review gate")
    sp.add_argument("run_id", nargs="?", default="latest",
                    help="run id, or omit for the run awaiting review")
    sp.add_argument("--gate", default=None)
    sp.add_argument("--reason", default="")

    sp = sub.add_parser("resume", help="resume a paused/failed run")
    sp.add_argument("run_id", nargs="?", default="latest",
                    help="run id, or omit for the most recent run")

    sp = sub.add_parser(
        "attach",
        help="fulfil a Canva handoff (attach the design or exported files) and resume",
    )
    sp.add_argument("run_id", nargs="?", default="latest",
                    help="run id, or omit for the run awaiting a handoff")
    sp.add_argument("--design-id", default="", help="Canva design id created for this run")
    sp.add_argument("--design-url", default="", help="the design's view URL")
    sp.add_argument("--design-title", default="")
    sp.add_argument("--template-id", default="", help="brand template it was built from")
    sp.add_argument("--copy-file", default="", help="JSON file of copy fields")
    sp.add_argument("--export-file", action="append", default=[],
                    help="path to an exported file (repeatable, one per page)")
    sp.add_argument("--export-url", action="append", default=[],
                    help="signed Canva export URL to download (repeatable); use "
                         "instead of --export-file when this machine can reach "
                         "export-download.canva.com")

    sp = sub.add_parser(
        "prepare",
        help="produce a reviewed article for manual publishing (no network)",
    )
    sp.add_argument("output_id", nargs="?", default="latest",
                    help="output id, or omit for the most recent "
                         "not-yet-published one")
    sp.add_argument("--title", default="")
    sp.add_argument("--text", default="")
    sp.add_argument("--dest", default=None, help="output folder (default: <data-dir>/handoff/<output_id>)")

    sp = sub.add_parser(
        "record",
        help="record a publication made outside PCIP (keeps the graph honest)",
    )
    sp.add_argument("output_id")
    sp.add_argument("--channel", default="wordpress")
    sp.add_argument("--url", default="", help="the reader-facing URL it went live at")
    sp.add_argument("--external-id", default="", help="the channel's own id for the post")
    sp.add_argument("--note", default="", help="why it was published by hand")
    sp.add_argument("--published-at", default="", help="ISO timestamp (default: now)")

    sp = sub.add_parser(
        "retract",
        help="move published copies of an output to the WordPress trash",
    )
    sp.add_argument("output_id")
    sp.add_argument("--reason", default="", help="why it is being retracted")

    sp = sub.add_parser("publish", help="publish an output to a channel")
    sp.add_argument("output_id", nargs="?", default="latest",
                    help="output id, or omit for the most recent "
                         "not-yet-published one")
    sp.add_argument("--republish", action="store_true",
                    help="publish again even though this output is already live "
                         "(creates a second copy competing for the same terms)")
    sp.add_argument("--transport", choices=("auto", "rest", "xmlrpc"), default="",
                    help="WordPress write path (default: auto — REST, falling "
                         "back to XML-RPC when the host strips Authorization)")
    sp.add_argument("--channel", required=True)
    sp.add_argument("--title", default="")
    sp.add_argument("--text", default="")
    sp.add_argument("--live", action="store_true",
                    help="WordPress: publish live instead of draft")
    sp.add_argument("--schedule-at", default="")
    sp.add_argument("--dry-run", action="store_true",
                    help="social channels: run the real adapter against a "
                         "recording transport and print the exact request "
                         "instead of sending it (no token required)")

    return p


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "sync": cmd_sync,
    "search": cmd_search,
    "graph": cmd_graph,
    "pipelines": cmd_pipelines,
    "canva-auth": cmd_canva_auth,
    "doctor": cmd_doctor,
    "can": cmd_can,
    "media-plan": cmd_media_plan,
    "route": cmd_route,
    "run": cmd_run,
    "runs": cmd_runs,
    "approve": cmd_approve,
    "reject": cmd_reject,
    "resume": cmd_resume,
    "attach": cmd_attach,
    "prepare": cmd_prepare,
    "retract": cmd_retract,
    "record": cmd_record,
    "publish": cmd_publish,
    "outputs": cmd_outputs,
}


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(data_dir=args.data_dir)
    try:
        return COMMANDS[args.command](cfg, args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":                          # python -m pcip.cli …
    sys.exit(main())
