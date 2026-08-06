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
    python -m pcip publish <output_id> --channel wordpress --title "..." [--live]
"""

from __future__ import annotations

import argparse
import json
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
    return {
        "run_id": run.id,
        "pipeline": run.pipeline,
        "status": run.status,
        "awaiting_gate": run.current_gate,
        "steps": [{"step": s.step, "status": s.status, "detail": s.detail}
                  for s in run.steps],
    }


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
    "run": cmd_run,
    "runs": cmd_runs,
    "approve": cmd_approve,
    "reject": cmd_reject,
    "resume": cmd_resume,
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
