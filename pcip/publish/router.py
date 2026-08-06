"""Publish router — the only door out of the platform.

Every publish goes through three checks before any network call:

1. **Provenance** — the output must exist in the graph and trace back to a
   completed (not rejected/awaiting-review) pipeline run.
2. **Licensing**  — LicensePolicy.check_publish over the output and every
   asset it uses; Canva premium content only ships as part of an exported
   design (metadata ``via_export``).
3. **Routing**    — the hybrid decision engine:

       immediate post (no schedule)  → direct platform API first
         (breaking news, healthcare alerts, physician announcements)
       scheduled campaign            → Buffer (scheduler) first
         (podcasts, blogs, newsletters, evergreen, educational series)

   with automatic fallback to the other mode when the preferred one isn't
   configured — a scheduler outage never strands an urgent post. WordPress
   posts land as drafts unless explicitly told to go live.

Every successful publish is recorded as a Publication node (including which
route the decision engine took) with edges back to the output and channel —
the graph answers "where did this go, and how?" forever.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.licensing import LicensePolicy, LicensingError
from pcip.models import Asset, Channel, EdgeKind, NodeKind, Publication


class PublishError(Exception):
    pass


class PublishRouter:
    def __init__(self, config: PCIPConfig, graph: KnowledgeGraph) -> None:
        self.cfg = config
        self.graph = graph
        self.policy = LicensePolicy()

    # ── Checks ───────────────────────────────────────────────────────────

    def _load_output_asset(self, output_id: str) -> Asset:
        node = self.graph.get_node(output_id)
        if not node or node["kind"] != NodeKind.OUTPUT.value:
            raise PublishError(f"'{output_id}' is not a known output node.")
        return Asset.from_dict(node["payload"])

    def _check_run_state(self, output_id: str) -> None:
        for ekind, run_id in self.graph.neighbors(output_id, EdgeKind.PRODUCED, "in"):
            run = self.graph.get_node(run_id)
            if run and run["payload"].get("status") not in ("done",):
                raise PublishError(
                    f"Output {output_id} came from run {run_id} which is "
                    f"'{run['payload'].get('status')}' — only outputs of "
                    "completed (fully reviewed) runs can be published."
                )

    def _check_license(self, output: Asset) -> None:
        used: List[Asset] = [output]
        for ekind, asset_id in self.graph.neighbors(output.id, EdgeKind.USES_ASSET):
            node = self.graph.get_node(asset_id)
            if node and node["kind"] == NodeKind.ASSET.value:
                used.append(Asset.from_dict(node["payload"]))
        decision = self.policy.check_publish(used)
        if not decision.allowed:
            raise LicensingError(decision.reason)

    # ── Publishing ───────────────────────────────────────────────────────

    def publish(
        self,
        output_id: str,
        channel: Channel | str,
        *,
        title: str = "",
        text: str = "",
        live: bool = False,
        schedule_at: str = "",
        media_urls: Optional[List[str]] = None,
    ) -> Publication:
        channel = Channel(channel) if isinstance(channel, str) else channel
        output = self._load_output_asset(output_id)
        self._check_run_state(output_id)
        self._check_license(output)

        if channel == Channel.WORDPRESS:
            from pcip.connectors.wordpress import WordPressPublisher

            wp = WordPressPublisher(self.cfg)
            paths = output.metadata.get("pages") or (
                [output.local_path] if output.local_path else []
            )
            pub = wp.publish_post(
                title or output.name,
                content_html=text,
                status="publish" if live else "draft",
                media_paths=paths,
                alt_texts=[output.metadata.get("alt_text", output.name)] * len(paths),
            )
        else:
            from pcip.connectors.social import adapter_for

            # Decision engine: immediate → direct API; scheduled → scheduler.
            prefer = "scheduler" if schedule_at else "direct"
            adapter = adapter_for(channel, self.cfg, prefer=prefer)
            pub = adapter.publish(
                channel,
                text or title or output.name,
                media_urls=media_urls,
                schedule_at=schedule_at,
            )
            pub.metadata["route"] = {
                "adapter": type(adapter).__name__,
                "mode": adapter.mode,
                "preferred_mode": prefer,
                "fallback_used": adapter.mode != prefer,
            }

        pub.output_id = output_id
        self._record(pub)
        return pub

    def route_plan(self, channel: Channel | str, scheduled: bool = False) -> Dict[str, Any]:
        """Preview the decision engine's routing for a channel (no publish)."""
        from pcip.connectors.social import adapters_for

        channel = Channel(channel) if isinstance(channel, str) else channel
        if channel == Channel.WORDPRESS:
            return {"channel": channel.value, "order": ["WordPressPublisher"],
                    "mode": "direct"}
        prefer = "scheduler" if scheduled else "direct"
        order = adapters_for(channel, self.cfg, prefer=prefer)
        return {
            "channel": channel.value,
            "preferred_mode": prefer,
            "order": [f"{type(a).__name__}({a.mode})" for a in order],
        }

    def _record(self, pub: Publication) -> None:
        channel_node = f"channel:{pub.channel.value}"
        self.graph.upsert_node(channel_node, NodeKind.CHANNEL, pub.channel.value)
        self.graph.upsert_node(
            pub.id, NodeKind.PUBLICATION,
            f"{pub.channel.value}: {pub.url or pub.external_id or pub.status}",
            pub.to_dict(),
        )
        self.graph.add_edge(pub.output_id, EdgeKind.PUBLISHED_TO, pub.id)
        self.graph.add_edge(pub.id, EdgeKind.ON_CHANNEL, channel_node)

    # ── Reporting ────────────────────────────────────────────────────────

    def where_did_it_go(self, output_id: str) -> List[Dict[str, Any]]:
        """All publications of an output — the distribution record."""
        pubs = []
        for ekind, pub_id in self.graph.neighbors(output_id, EdgeKind.PUBLISHED_TO):
            node = self.graph.get_node(pub_id)
            if node:
                pubs.append(node["payload"])
        return pubs
