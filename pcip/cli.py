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
import pathlib
import sys
from typing import Any

from pcip.config import PCIPConfig, load_config
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief, NodeKind


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
    from pcip.generate.providers import ProviderRegistry

    with _graph(cfg) as g:
        _print(
            {
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
    from pcip.connectors.canva_auth import run_flow

    run_flow(
        cfg,
        port=args.port,
        write_env=None if args.no_write else args.env_file,
        open_browser=not args.no_browser,
    )
    return 0


def cmd_doctor(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    """Diagnose connectors against the bootstrap.yaml manifest."""
    from pcip.connectors.framework import ConnectorManager, load_manifest

    manager = ConnectorManager(cfg, manifest=load_manifest(args.manifest))
    report = manager.doctor(live=args.live)
    _print(report)
    return 0 if not report["actions"] else 1


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
        # Let the paused step run again now that its input exists.
        for sr in run.steps:
            if sr.status == "awaiting_handoff":
                sr.status = "pending"
        run.context.pop("handoff", None)
        runner._save(run)
        run = runner.resume(get_pipeline(run.pipeline), run, brief)
        _print(_run_summary(run))
    return 0 if run.status not in ("failed", "rejected") else 1


def cmd_run(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    from pcip.pipelines.base import PipelineRunner
    from pcip.pipelines.library import get_pipeline

    brief = Brief.from_json_file(args.brief)
    with _graph(cfg) as g:
        run = PipelineRunner(cfg, g).start(get_pipeline(args.pipeline), brief)
        _print(_run_summary(run))
    return 0 if run.status in ("done", "awaiting_review") else 1


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


def cmd_approve(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    with _graph(cfg) as g:
        runner, run, brief = _load_run_and_brief(cfg, g, args.run_id)
        if not runner:
            return 1
        runner.approve(args.run_id, gate=args.gate, reviewer=args.reviewer)
        from pcip.pipelines.library import get_pipeline

        run = runner.load_run(args.run_id)
        run = runner.resume(get_pipeline(run.pipeline), run, brief)
        _print(_run_summary(run))
    return 0


def cmd_reject(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    with _graph(cfg) as g:
        runner, run, brief = _load_run_and_brief(cfg, g, args.run_id)
        if not runner:
            return 1
        run = runner.reject(args.run_id, gate=args.gate, reason=args.reason)
        _print(_run_summary(run))
    return 0


def cmd_resume(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    from pcip.pipelines.library import get_pipeline

    with _graph(cfg) as g:
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
            args.output_id, title=args.title, text=args.text, dest=args.dest
        )
        _print(result)
    return 0


def cmd_publish(cfg: PCIPConfig, args: argparse.Namespace) -> int:
    from pcip.publish.router import PublishRouter

    with _graph(cfg) as g:
        pub = PublishRouter(cfg, g).publish(
            args.output_id,
            args.channel,
            title=args.title,
            text=args.text,
            live=args.live,
            schedule_at=args.schedule_at,
        )
        _print(pub.to_dict())
    return 0


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

    sp = sub.add_parser("doctor", help="diagnose connectors from bootstrap.yaml")
    sp.add_argument("--live", action="store_true",
                    help="run live auth/entitlement probes")
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

    sp = sub.add_parser("runs", help="list pipeline runs")
    sp.add_argument("--limit", type=int, default=20)

    sp = sub.add_parser("approve", help="approve a review gate and continue")
    sp.add_argument("run_id")
    sp.add_argument("--gate", default=None)
    sp.add_argument("--reviewer", default="")

    sp = sub.add_parser("reject", help="reject a review gate")
    sp.add_argument("run_id")
    sp.add_argument("--gate", default=None)
    sp.add_argument("--reason", default="")

    sp = sub.add_parser("resume", help="resume a paused/failed run")
    sp.add_argument("run_id")

    sp = sub.add_parser(
        "attach",
        help="fulfil a Canva handoff (attach the design or exported files) and resume",
    )
    sp.add_argument("run_id")
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
    sp.add_argument("output_id")
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

    sp = sub.add_parser("publish", help="publish an output to a channel")
    sp.add_argument("output_id")
    sp.add_argument("--channel", required=True)
    sp.add_argument("--title", default="")
    sp.add_argument("--text", default="")
    sp.add_argument("--live", action="store_true",
                    help="WordPress: publish live instead of draft")
    sp.add_argument("--schedule-at", default="")

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
    "record": cmd_record,
    "publish": cmd_publish,
}


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(data_dir=args.data_dir)
    try:
        return COMMANDS[args.command](cfg, args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
