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

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pcip.config import PCIPConfig
from pcip.graph.store import KnowledgeGraph
from pcip.licensing import LicensePolicy, LicensingError
from pcip.models import Asset, Channel, EdgeKind, NodeKind, Publication


class PublishError(Exception):
    pass


def slugify(title: str) -> str:
    """A WordPress-style slug: lowercase, hyphenated, ASCII-safe."""
    import unicodedata

    text = unicodedata.normalize("NFKD", title or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", text)).strip("-")[:80]


def _handoff_readme(meta: Dict[str, Any], wp_origin: str) -> str:
    media_lines = "\n".join(
        f"   - `media/{name}` — alt text: {alt!r}"
        for name, alt in zip(meta["media"], meta["alt_texts"] + [""] * len(meta["media"]))
    ) or "   (no media exported)"
    hashtags = " ".join(meta["hashtags"]) or "(none)"
    return f"""# Manual publishing handoff — {meta['title']}

PCIP produced this article but did not publish it. Every gate a real publish
enforces (review approval, licensing, provenance) already passed — this folder
exists only because the WordPress REST write path is unavailable.

## Paste it in

1. Go to {wp_origin}/wp-admin/post-new.php
2. **Title**: {meta['title']}
3. **Slug** (Post → URL): `{meta['suggested_slug']}`
4. **Body**: paste the contents of `article.html` into the editor's Code/HTML view.
5. **Excerpt**: {meta['excerpt'] or '(none generated)'}
6. **Media** — upload each file and set its alt text exactly:
{media_lines}
   Set the first image as the Featured image.
7. Publish.

The article should appear at **{meta['expected_public_url']}**
within about 60 seconds — the public site fetches from WordPress on its next
request, so nothing needs to be deployed.

## Social copy (not published either)

Hashtags: {hashtags}

Captions are in `meta.json` under `captions`, keyed by channel.

## When the REST path is fixed

Apply the Authorization-header fix on the WordPress server, then
`pcip publish {meta['output_id']} --channel wordpress --live` does all of the
above automatically and records the publication in the knowledge graph.
"""


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

    # ── What the pipeline already produced ───────────────────────────────

    def _producing_run(self, output_id: str) -> Dict[str, Any]:
        for ekind, run_id in self.graph.neighbors(output_id, EdgeKind.PRODUCED, "in"):
            node = self.graph.get_node(run_id)
            if node:
                return node["payload"]
        return {}

    def payload_for(
        self, output: Asset, *, title: str = "", text: str = ""
    ) -> Dict[str, Any]:
        """Assemble one deliverable's publishable parts.

        Shared by publishing and by ``pcip prepare`` so the offline handoff is
        byte-for-byte what would have been published. Explicit ``title``/``text``
        always win; otherwise the copy step's parsed fields are used, falling
        back to its raw prose so a run is never unpublishable.
        """
        run = self._producing_run(output.id)
        ctx = run.get("context") or {}
        fields = ctx.get("copy_fields") or {}

        language = "en"
        brief_node = self.graph.get_node(run.get("brief_id", ""))
        if brief_node:
            language = brief_node["payload"].get("language") or "en"

        paths = output.metadata.get("pages") or (
            [output.local_path] if output.local_path else []
        )
        alts = [
            str(a)
            for a in (output.metadata.get("alt_texts") or fields.get("alt_texts") or [])
        ]
        if len(alts) < len(paths):
            filler = fields.get("title") or output.name
            alts = alts + [filler] * (len(paths) - len(alts))

        return {
            "title": title or fields.get("title") or output.name,
            "body_html": text or fields.get("body_html") or ctx.get("copy") or "",
            "excerpt": fields.get("excerpt", ""),
            "media_paths": paths,
            "alt_texts": alts[: len(paths)],
            "language": language,
            "hashtags": fields.get("hashtags") or [],
            "captions": fields.get("captions") or {},
        }

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

        payload = self.payload_for(output, title=title, text=text)

        if channel == Channel.WORDPRESS:
            from pcip.connectors.wordpress import WordPressPublisher

            wp = WordPressPublisher(self.cfg)
            if not payload["body_html"].strip():
                raise PublishError(
                    f"Refusing to publish {output_id} with an empty body. The run "
                    "that produced it has no generated copy, and no --text was "
                    "given. Either pass the body explicitly:\n"
                    f"  pcip publish {output_id} --channel wordpress --text '<p>…</p>'\n"
                    "or re-run the pipeline so its copy step persists an article body."
                )
            pub = wp.publish_post(
                payload["title"],
                content_html=payload["body_html"],
                status="publish" if live else "draft",
                media_paths=payload["media_paths"],
                alt_texts=payload["alt_texts"],
                excerpt=payload["excerpt"],
                language=payload["language"],
                schedule_at=schedule_at,
            )
        else:
            from pcip.connectors.social import adapter_for

            # Decision engine: immediate → direct API; scheduled → scheduler.
            prefer = "scheduler" if schedule_at else "direct"
            adapter = adapter_for(channel, self.cfg, prefer=prefer)
            caption = (
                text
                or payload["captions"].get(channel.value)
                or payload["body_html"]
                or payload["title"]
            )
            if payload["hashtags"] and not text:
                caption = f"{caption}\n\n{' '.join(payload['hashtags'])}"
            pub = adapter.publish(
                channel,
                caption,
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

    def prepare(
        self,
        output_id: str,
        *,
        title: str = "",
        text: str = "",
        dest: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Produce the article for manual publishing — same gates, no network.

        The escape hatch for when the WordPress REST write path is blocked
        (e.g. a server stripping the Authorization header). Every provenance,
        review and licensing check a real publish runs is enforced here too, so
        nothing bypasses governance just because it is pasted by hand.
        """
        import json
        import shutil

        output = self._load_output_asset(output_id)
        self._check_run_state(output_id)
        self._check_license(output)
        payload = self.payload_for(output, title=title, text=text)

        folder = Path(dest) if dest else Path(self.cfg.data_dir) / "handoff" / output_id
        (folder / "media").mkdir(parents=True, exist_ok=True)

        slug = slugify(payload["title"])
        copied: List[str] = []
        for path in payload["media_paths"]:
            src = Path(path)
            if not src.exists():
                continue
            shutil.copy2(src, folder / "media" / src.name)
            copied.append(src.name)

        (folder / "article.html").write_text(payload["body_html"], encoding="utf-8")
        meta = {
            "title": payload["title"],
            "suggested_slug": slug,
            "excerpt": payload["excerpt"],
            "language": payload["language"],
            "alt_texts": payload["alt_texts"],
            "hashtags": payload["hashtags"],
            "captions": payload["captions"],
            "media": copied,
            "expected_public_url": self._expected_url(slug, payload["language"]),
            "output_id": output_id,
        }
        (folder / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (folder / "README.md").write_text(
            _handoff_readme(meta, self.cfg.wordpress_url), encoding="utf-8"
        )
        return {"folder": str(folder), **meta}

    def _expected_url(self, slug: str, language: str) -> str:
        base = self.cfg.wordpress_public_site.rstrip("/")
        prefix = "/es" if str(language).lower().startswith("es") else ""
        return f"{base}{prefix}/{slug}/" if slug else ""

    def route_plan(self, channel: Channel | str, scheduled: bool = False) -> Dict[str, Any]:
        """Preview the decision engine's routing for a channel (no publish)."""
        from pcip.connectors.social import adapters_for

        channel = Channel(channel) if isinstance(channel, str) else channel
        if channel == Channel.WORDPRESS:
            return {
                "channel": channel.value,
                "order": ["WordPressPublisher"],
                "mode": "direct",
                "api_origin": self.cfg.wordpress_url,
                "reader_site": self.cfg.wordpress_public_site,
                "instant_revalidation": self.cfg.revalidation_configured,
                "note": "publishing to WordPress makes the article live on the "
                        "reader site within ~60s (ISR)"
                        + ("" if self.cfg.revalidation_configured
                           else "; set VERCEL_REVALIDATE_URL + WP_REVALIDATE_SECRET "
                                "to make it immediate"),
            }
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
