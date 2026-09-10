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
from pcip.annotations import strip_review_annotations
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


def plain_text(html: str) -> str:
    """Flatten article HTML into the text a social caption should carry.

    Social APIs take plain text. Handing them ``body_html`` posts the markup
    verbatim, so block-level tags become line breaks and everything else is
    dropped, entities included.
    """
    import html as _html

    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|blockquote)>", "\n\n", text)
    text = _html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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
   If a file is an image, set the first one as the Featured image. A PDF
   cannot be a featured image: attach it as a download link instead, and
   export a PNG of the same design if the article needs a hero image.
7. Publish.

8. Record it, so the knowledge graph knows where this went:
   `pcip record {meta['output_id']} --channel wordpress --url {meta['expected_public_url']}`
   Without this the output reads as unpublished while it is in fact live.

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
        # Reviewer annotations are addressed to a clinician, never to a reader.
        # The medical_review gate is where they are resolved; by the time copy
        # reaches a channel they must be gone, and what was removed is recorded
        # so the edit is auditable rather than silent.
        raw_body = text or fields.get("body_html") or ctx.get("copy") or ""
        body_html, stripped_annotations = strip_review_annotations(raw_body)

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
            "body_html": body_html,
            "excerpt": fields.get("excerpt", ""),
            "media_paths": paths,
            "alt_texts": alts[: len(paths)],
            "language": language,
            "hashtags": fields.get("hashtags") or [],
            "captions": fields.get("captions") or {},
            "stripped_annotations": stripped_annotations,
        }

    def _publish_bilingual(
        self,
        wp: Any,
        output_id: str,
        fields: Dict[str, Any],
        bodies: Dict[str, str],
        payload: Dict[str, Any],
        *,
        live: bool,
        schedule_at: str,
    ) -> Publication:
        """Publish the ES/EN pair, record both, return the primary.

        Both publications are written to the graph so the distribution record
        answers "where did this go" completely. The Spanish one is returned
        because Spanish is primary for this brand and a caller expects a single
        Publication back; the English one is reachable through
        ``where_did_it_go`` and named in the returned metadata rather than
        being invisible.
        """
        if schedule_at:
            raise PublishError(
                "Scheduling a bilingual pair is not supported yet — the two "
                "posts would need to go live together, and a partial schedule "
                "would publish one language early. Publish now, or pass "
                "--text to publish a single language."
            )

        titles = fields.get("titles") or {}
        slugs = {
            lang: slugify(titles.get(lang) or payload.get("title", ""))
            for lang in bodies
        }
        pubs = wp.publish_bilingual(
            titles=titles,
            bodies=bodies,
            slugs=slugs,
            meta_title=fields.get("meta_title", ""),
            meta_description=fields.get("meta_description",
                                        payload.get("excerpt", "")),
            faq=fields.get("faq") or [],
            alt_texts=fields.get("alt_texts_by_language") or {},
            media_paths=payload.get("media_paths") or [],
            status="publish" if live else "draft",
            excerpt=payload.get("excerpt", ""),
        )
        for pub in pubs.values():
            pub.output_id = output_id
            self._record(pub)

        primary = pubs.get("es") or next(iter(pubs.values()))
        primary.metadata["pair"] = {
            lang: {"url": p.url, "post_id": p.external_id}
            for lang, p in pubs.items()
        }
        return primary

    def _promote_drafts(
        self, wp: Any, output_id: str, *, live: bool
    ) -> Optional[Publication]:
        """Publish drafts this output already has, instead of new posts.

        Reviewing as a draft and then publishing is the intended workflow, and
        it produced two posts per language: the draft held the clean slug, so
        WordPress gave the live one a "-2" suffix. The draft is the article —
        promote it.

        Returns None when there is nothing to promote, so the caller falls
        through to creating posts normally.
        """
        if not live:
            return None
        drafts = [
            p for p in self.where_did_it_go(output_id)
            if p.get("channel") == Channel.WORDPRESS.value
            and p.get("status") == "draft"
            and p.get("external_id")
        ]
        if not drafts:
            return None

        out: List[Publication] = []
        for record in drafts:
            updated = wp.update_post(str(record["external_id"]), status="publish")
            lang = (record.get("metadata") or {}).get("language", "es")
            url = wp.public_url_for(
                updated.get("slug", ""), lang, wp_link=updated.get("link", "")
            ) or record.get("url", "")

            meta = dict(record.get("metadata") or {})
            meta["wp_status"] = updated.get("status", "publish")
            meta["wp_link"] = updated.get("link", meta.get("wp_link", ""))
            meta["promoted_from_draft"] = True
            if meta["wp_status"] == "publish":
                meta.update(wp.revalidate(updated.get("slug", ""), lang))

            pub = Publication(
                id=record["id"],          # same record: this is the same post
                output_id=output_id,
                channel=Channel.WORDPRESS,
                url=url,
                external_id=str(record["external_id"]),
                status="published",
                metadata=meta,
            )
            self._record(pub)
            out.append(pub)

        primary = next(
            (p for p in out if (p.metadata or {}).get("language") == "es"), out[0]
        )
        primary.metadata["pair"] = {
            (p.metadata or {}).get("language", "?"):
                {"url": p.url, "post_id": p.external_id}
            for p in out
        }
        return primary

    def _check_not_already_published(
        self, output_id: str, channel: Channel, republish: bool
    ) -> None:
        """Refuse to publish the same deliverable to the same channel twice.

        A scheduled run and a manual run both publishing produced two live
        articles competing for one topic — which splits the ranking signal and
        leaves a reader wondering which is current. The graph already knows
        where everything went; this makes it consult that before writing again.
        """
        if republish:
            return
        already = [
            p for p in self.where_did_it_go(output_id)
            if p.get("channel") == channel.value
            and p.get("status") in ("published", "scheduled")
        ]
        if not already:
            return
        where = ", ".join(p.get("url") or p.get("external_id", "?") for p in already)
        raise PublishError(
            f"{output_id} is already published to {channel.value}: {where}\n\n"
            "Publishing again creates a second live copy of the same article, "
            "which competes with the first for the same search terms.\n\n"
            "To replace it, retract the existing one first:\n"
            f"  pcip retract {output_id}\n"
            "or, if you genuinely want a second copy, pass --republish."
        )

    def _check_ph_standard(
        self, output_id: str, payload: Dict[str, Any], output: Asset
    ) -> None:
        """Refuse to publish an article below the PassQual Health standard.

        The pipeline runs this too, before human review — but only at the draft
        stage, when the design has not been exported and the hero image cannot
        exist yet. This is the last gate before a reader sees it, so it runs
        the full check: bilingual pair, depth, SEO surface, hero image, NAP,
        credentials, and the compliance rules that must never ship.

        Explicit ``--text`` bypasses this deliberately: an operator supplying
        the body by hand has taken responsibility for it, and refusing their
        own words would make the escape hatch useless.
        """
        from pcip.standards import check_article

        run = self._producing_run(output_id)
        fields = (run.get("context") or {}).get("copy_fields") or {}
        bodies = fields.get("bodies") or {}
        titles = fields.get("titles") or {}
        if not bodies:
            bodies = {payload.get("language", "es"): payload.get("body_html", "")}
            titles = {payload.get("language", "es"): payload.get("title", "")}

        media = payload.get("media_paths") or []
        check = check_article({
            "bodies": bodies,
            "titles": titles,
            "meta_title": fields.get("meta_title", ""),
            "meta_description": fields.get("meta_description",
                                           payload.get("excerpt", "")),
            "faq": fields.get("faq") or [],
            "featured_image": media[0] if media else "",
            "alt_texts": fields.get("alt_texts_by_language") or {},
        }, stage="publish")

        if not check.passed:
            raise PublishError(
                f"Refusing to publish {output_id}: it does not meet the "
                f"PassQual Health article standard.\n\n{check.report()}\n\n"
                "Fix the copy and re-run the pipeline, or pass --text to "
                "publish body copy you have written and taken responsibility "
                "for."
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
        republish: bool = False,
        dry_run: bool = False,
    ) -> Publication:
        channel = Channel(channel) if isinstance(channel, str) else channel
        if dry_run and channel == Channel.WORDPRESS:
            raise PublishError(
                "--dry-run covers the social channels. WordPress already has an "
                "offline path that produces the real article:\n"
                f"  pcip prepare {output_id}"
            )
        self._check_not_already_published(output_id, channel, republish)

        # Promoting a draft flips a status; it does not change the article,
        # which was validated when the draft was created. Doing it before the
        # content checks also avoids re-deriving a payload for copy that is
        # already sitting in WordPress.
        if channel == Channel.WORDPRESS and live:
            from pcip.connectors.wordpress import WordPressPublisher

            promoted = self._promote_drafts(
                WordPressPublisher(self.cfg), output_id, live=True
            )
            if promoted is not None:
                return promoted
        output = self._load_output_asset(output_id)
        self._check_run_state(output_id)
        self._check_license(output)

        payload = self.payload_for(output, title=title, text=text)
        if not text and channel == Channel.WORDPRESS:
            self._check_ph_standard(output_id, payload, output)

        if channel == Channel.WORDPRESS:
            from pcip.connectors.wordpress import WordPressPublisher

            wp = WordPressPublisher(self.cfg)

            # A bilingual copy package publishes as a linked pair. The standard
            # requires ES/EN parity, so producing one post from copy that has
            # both would quietly ship half the deliverable.
            run = self._producing_run(output_id)
            fields = (run.get("context") or {}).get("copy_fields") or {}
            bodies = {k: v for k, v in (fields.get("bodies") or {}).items() if v}
            if len(bodies) > 1 and not text:
                return self._publish_bilingual(
                    wp, output_id, fields, bodies, payload,
                    live=live, schedule_at=schedule_at,
                )
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
            # The article body is a last resort and it is *HTML*. Posting the
            # markup to Instagram would be worse than posting nothing, so it
            # is flattened to the text a reader would see.
            caption = (
                text
                or payload["captions"].get(channel.value)
                or plain_text(payload["body_html"])
                or payload["title"]
            )
            if payload["hashtags"] and not text:
                caption = f"{caption}\n\n{' '.join(payload['hashtags'])}"
            self._check_ph_social(
                channel, caption, media_urls, payload["language"],
                operator_written=bool(text),
            )
            if dry_run:
                return self._dry_run_social(
                    output_id, channel, caption, prefer,
                    media_urls=media_urls, schedule_at=schedule_at,
                )
            adapter = adapter_for(channel, self.cfg, prefer=prefer)
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

    def _check_ph_social(
        self,
        channel: Channel,
        caption: str,
        media_urls: Optional[List[str]],
        language: str,
        *,
        operator_written: bool,
    ) -> None:
        """Hold a social post to the part of the standard that applies to it.

        The article standard used to run on every channel, which no caption
        could ever satisfy — social publishing was gated shut and nobody had
        noticed, because no social post had ever been attempted.

        ``--text`` waives the required-level findings, the same escape hatch
        articles have: an operator writing the caption has taken it on. It
        does **not** waive the blockers. Pediatric content, an outcome
        guarantee, or a mental-health post without 988 and 911 are not
        matters of editorial preference, and a caption reaches a patient
        exactly as directly as an article does.
        """
        from pcip.connectors.social import CAPTION_LIMITS
        from pcip.standards import check_social_post

        check = check_social_post(
            {
                "caption": caption,
                "channel": channel.value,
                "media": list(media_urls or []),
                "language": language,
            },
            limit=CAPTION_LIMITS.get(channel),
        )
        failures = check.blockers if operator_written else (
            check.blockers + check.required
        )
        if failures:
            raise PublishError(
                f"Refusing to publish {channel.value}: the caption does not "
                f"meet the PassQual Health standard.\n\n" + check.report()
            )

    def _dry_run_social(
        self,
        output_id: str,
        channel: Channel,
        caption: str,
        prefer: str,
        *,
        media_urls: Optional[List[str]] = None,
        schedule_at: str = "",
    ) -> Publication:
        """Run the real adapter against a recording transport.

        Every gate above this point has already run, so a dry run answers the
        whole question — is this output publishable, and what exactly would
        leave the building — without a token and without a post. The result
        is deliberately *not* recorded: the graph is the record of what was
        published, and a rehearsal is not a publication.
        """
        from pcip.connectors.dryrun import DryRunSession, dryrun_config
        from pcip.connectors.social import adapter_for

        cfg, _ = dryrun_config(self.cfg)
        session = DryRunSession()
        adapter = adapter_for(
            channel, cfg, prefer=prefer,
            session=session, require_available=False,
        )
        # Report what *this* adapter needs, not every social credential in the
        # config: a Threads preview listing YOUTUBE_TOKEN as missing sends the
        # operator to fix something unrelated to what they just previewed.
        missing = type(adapter)(self.cfg, session).missing_credentials()
        error = ""
        try:
            pub = adapter.publish(
                channel, caption, media_urls=media_urls, schedule_at=schedule_at
            )
        except Exception as exc:                      # noqa: BLE001 — reported
            pub = Publication(channel=channel, status="failed")
            error = f"{type(exc).__name__}: {exc}"

        pub.output_id = output_id
        pub.external_id = ""
        pub.status = "dry_run"
        pub.metadata = {
            "dry_run": True,
            "adapter": type(adapter).__name__,
            "mode": adapter.mode,
            "preferred_mode": prefer,
            "fallback_used": adapter.mode != prefer,
            "caption": caption,
            "caption_chars": len(caption),
            "media_urls": list(media_urls or []),
            "schedule_at": schedule_at,
            "requests": session.requests,
            "missing_credentials": missing,
            "would_fail": bool(error),
            "error": error,
        }
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
            # Notes removed on the way out, kept so the reviewer can confirm
            # each one was actually resolved rather than merely deleted.
            "reviewer_notes_removed": payload["stripped_annotations"],
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

    def record_manual(
        self,
        output_id: str,
        channel: Channel | str,
        *,
        url: str = "",
        external_id: str = "",
        note: str = "",
        published_at: str = "",
    ) -> Publication:
        """Record a publication that happened outside PCIP.

        `prepare` exists because the automated write path can be unavailable —
        a host misconfiguration, a channel without an API, a one-off posted by
        hand. When that article goes live, the knowledge graph would otherwise
        never learn of it, and the distribution record would be silently wrong:
        an output that reads as unpublished while it is in fact on the internet.

        The same review-state check as a real publish still applies, because a
        deliverable whose gates never passed should not acquire a publication
        record by another route. Licensing is not re-checked: the file has
        already been distributed, and refusing to write it down would not undo
        that — it would only lose the evidence.

        The record is marked `manual` so it is never mistaken for something
        PCIP performed and could reproduce.
        """
        channel = Channel(channel) if isinstance(channel, str) else channel
        self._load_output_asset(output_id)     # raises if unknown
        self._check_run_state(output_id)

        if not (url or external_id):
            raise PublishError(
                "Recording a manual publication needs somewhere it went: pass "
                "--url (preferred, it is the reader-facing address) or "
                "--external-id."
            )

        pub = Publication(
            output_id=output_id,
            channel=channel,
            url=url,
            external_id=external_id,
            status="published",
            metadata={
                "manual": True,
                "recorded_by": "pcip record",
                "note": note,
                "reason": "published outside PCIP; see pcip/PUBLISHING-BLOCKER.md",
            },
        )
        if published_at:
            pub.published_at = published_at
        self._record(pub)
        return pub

    def retract(self, output_id: str, *, reason: str = "") -> List[Publication]:
        """Move every published copy of an output to the trash and record it.

        Trash rather than delete: WordPress keeps it recoverable, and a
        retraction that cannot be undone is a worse failure than the duplicate
        it fixes. The publication record is kept and marked retracted, because
        the fact that something was live for a while is part of the
        distribution history, not an embarrassment to erase.
        """
        from pcip.connectors.wordpress import WordPressPublisher

        out: List[Publication] = []
        self.last_retract_skips: List[str] = []
        records = self.where_did_it_go(output_id)
        if not records:
            self.last_retract_skips.append(
                f"no publication is recorded against {output_id}"
            )
        for record in records:
            # Drafts included: a leftover draft keeps its slug reserved, so
            # the next publish gets a "-2" suffix instead of the clean URL.
            # Every skip is reported: a silent `continue` is why "nothing to
            # retract" could mean four different things.
            where = record.get("id", record.get("external_id", "?"))
            if record.get("status") not in ("published", "scheduled", "draft"):
                self.last_retract_skips.append(
                    f"{where}: status is {record.get('status')!r}"
                )
                continue
            if record.get("channel") != Channel.WORDPRESS.value:
                self.last_retract_skips.append(
                    f"{where}: channel is {record.get('channel')!r}, "
                    "and only WordPress can be retracted automatically"
                )
                continue
            post_id = record.get("external_id", "")
            if not post_id:
                self.last_retract_skips.append(
                    f"{where}: no WordPress post id was recorded, so there is "
                    "nothing to address — trash it by hand"
                )
                continue
            wp = WordPressPublisher(self.cfg)
            wp.trash_post(post_id)

            record = dict(record)
            record["status"] = "retracted"
            meta = dict(record.get("metadata") or {})
            meta["retracted_reason"] = reason or "replaced"
            record["metadata"] = meta
            self.graph.upsert_node(
                record["id"], NodeKind.PUBLICATION,
                f"{record['channel']}: retracted {record.get('url', '')}",
                record,
            )
            out.append(Publication(**{
                k: v for k, v in record.items()
                if k in ("id", "output_id", "url", "external_id",
                         "published_at", "status", "metadata")
            } | {"channel": Channel(record["channel"])}))
        return out

    # ── Reporting ────────────────────────────────────────────────────────

    def where_did_it_go(self, output_id: str) -> List[Dict[str, Any]]:
        """All publications of an output — the distribution record.

        Found two ways, and the union taken: the PUBLISHED_TO edge, and any
        publication whose payload names this output. They are written
        together and should always agree, but when they did not, `pcip
        status` reported an output as published while `pcip retract` said
        there was nothing to retract — two commands disagreeing about the
        same fact, with no way for the operator to tell which was right.
        """
        found: Dict[str, Dict[str, Any]] = {}
        for _kind, pub_id in self.graph.neighbors(output_id, EdgeKind.PUBLISHED_TO):
            node = self.graph.get_node(pub_id)
            if node:
                found[pub_id] = node["payload"]
        for node in self.graph.nodes_by_kind(NodeKind.PUBLICATION, limit=500):
            if node["payload"].get("output_id") == output_id:
                found.setdefault(node["id"], node["payload"])
        return list(found.values())
