# PCIP — PassQual Creative Intelligence Platform

The creative operating system for the Pascual enterprise. PCIP turns Canva
into **one component** of an enterprise creative workflow — connected,
searchable, licensed, reviewed, and published — rather than the workflow
itself.

```
                       ┌─────────────────────────────────────────────┐
                       │              CREATIVE BRIEF                 │
                       │  objective · audience · brand · channels    │
                       └──────────────────┬──────────────────────────┘
                                          ▼
 ┌────────────────┐    ┌─────────────────────────────────────────────┐
 │  CANVA CONNECT │◄──►│            KNOWLEDGE GRAPH (SQLite)         │
 │  designs       │sync│  every design, asset, brief, run, output,   │
 │  folders       │    │  and publication — full-text searchable,    │
 │  Brand Kits    │    │  typed edges (uses, derived-from, about,    │
 │  brand tmpls   │    │  on-brand, published-to)                    │
 │  assets        │    └──────────────────┬──────────────────────────┘
 └───────┬────────┘                       ▼
         │             ┌─────────────────────────────────────────────┐
         │  autofill   │           ASSEMBLY PIPELINES                │
         ├────────────►│  presentation · podcast_kit · blog_graphics │
         │  export API │  social_campaign · patient_education ·      │
         │  (licensed  │  marketing_asset                            │
         │   workflow) │                                             │
         │             │  gather context → AI copy (Claude) →        │
 ┌───────┴────────┐    │  capability-routed image/video → Canva      │
 │ CAPABILITY-    │───►│  autofill → ⛔ REVIEW GATES → export        │
 │ ROUTED AI      │    └──────────────────┬──────────────────────────┘
 │ Claude (copy)  │                       ▼
 │ img: OpenAI ·  │    ┌─────────────────────────────────────────────┐
 │  Imagen ·      │    │  LICENSE-CHECKED PUBLISH ROUTER (hybrid)    │
 │  Ideogram·Flux │    │  immediate → direct APIs (Meta · LinkedIn · │
 │ vid: Veo ·     │    │    X · Threads · YouTube · TikTok)          │
 │  Runway · Pika │    │  scheduled → Buffer queue                   │
 │  · Luma        │    │  + passqual.com (WordPress, draft-first)    │
 └────────────────┘    └─────────────────────────────────────────────┘
```

## Why this beats "ask an AI to pull premium images"

A one-shot prompt produces one deliverable with no memory, no brand
governance, no license trail, and no distribution record. PCIP produces a
**system**:

1. **Institutional memory.** Every design, licensed asset, brief, generation,
   deliverable, and publication becomes a node in a knowledge graph. "Show me
   everything we've made about diabetes for Instagram" is one query
   (`pcip search "diabetes instagram"`), and every output traces back to its
   brief, template, and assets (`pcip graph <node_id>`).
2. **Licensing by construction.** Premium Canva content only leaves Canva
   through the official export API — the supported workflow that applies your
   Pro entitlements server-side. The policy engine (`pcip/licensing.py`)
   refuses extraction, scraping, watermark-stripping, and standalone
   redistribution *in code*, and the publish router re-checks every asset's
   license before anything ships.
3. **Governed output.** Every pipeline has a `brand_review` gate; patient
   education adds a `medical_review` gate that **cannot** be auto-approved,
   plus a plain-language reading-level check. Nothing publishes from an
   unreviewed run.
4. **Capability-routed generation.** Orchestration never asks for a vendor
   by name. A pipeline states requirements — "1080×1920 vertical video,
   under 15 s, commercial license" — and the capability registry
   (`pcip/generate/capabilities.py`) selects the best configured provider:
   OpenAI Images as the image default, Imagen for photorealism, Ideogram
   for typography, Flux for self-host; Veo as the premium video default,
   Runway as the production fallback, Pika for fast social clips, Luma for
   stylized motion. When a better model ships, you update a profile table —
   business logic never changes. Preview any decision with
   `pcip media-plan <content_type>`.
5. **Hybrid publishing.** Direct platform adapters (Meta, LinkedIn, X,
   Threads, YouTube, TikTok) are first-class for full native capability and
   resilience; Buffer is the scheduling provider, not the only path. The
   decision engine routes immediate posts (healthcare alerts, physician
   announcements) direct-first and scheduled campaigns (podcasts, blogs,
   evergreen series) Buffer-first, with automatic fallback either way — a
   scheduler outage never strands an urgent post. Preview with
   `pcip route <channel> [--scheduled]`.
6. **Distribution memory.** Publishing to passqual.com or a social channel
   records a Publication node — including which route the decision engine
   took — so "where did this asset go, and how?" has a permanent answer.
7. **It knows how passqual.com really works.** The site is Next.js on Vercel
   rendering WordPress articles fetched at request time, so publishing a post
   puts it live within ~60s with no deploy. PCIP writes to the WordPress origin,
   records the *reader-facing* URL, optionally purges the site's cache for an
   instant appearance, and refuses to mistake a host's anti-bot challenge for a
   healthy API. Hand-authored marketing pages are deliberately out of scope.

## Module map

| Module | Responsibility |
|---|---|
| `pcip/models.py` | Domain models: assets, licenses, briefs, runs, publications, graph vocabulary |
| `pcip/config.py` | Env-based configuration; no secrets in code or the graph |
| `pcip/licensing.py` | Licensing policy engine (pure, fully unit-tested) |
| `pcip/connectors/canva.py` | Canva Connect API client: OAuth refresh, designs, folders, assets, brand templates, autofill, export |
| `pcip/connectors/wordpress.py` | Article publisher: hardened transport (refuses anti-bot challenges and non-JSON 2xx), reader-facing URL derivation, best-effort cache revalidation |
| `pcip/connectors/social.py` | Direct adapters (Meta, LinkedIn, X, Threads, YouTube, TikTok) + Buffer scheduler; mode-aware resolver |
| `pcip/connectors/framework.py` | Connector Management Framework: bootstrap.yaml manifest, capability matrix, doctor, `can()` queries |
| `pcip/connectors/catalog.py` | Per-connector descriptors: auth, env vars, capabilities (incl. honestly-unsupported ones), live probes |
| `pcip/generate/capabilities.py` | MediaSpec, provider capability profiles, capability registry (the media planner) |
| `pcip/generate/media_providers.py` | Image vendors (OpenAI, Imagen, Ideogram, Flux) and video vendors (Veo, Runway, Pika, Luma) |
| `pcip/graph/store.py` | SQLite knowledge graph + FTS5 search |
| `pcip/graph/indexer.py` | Canva library → graph sync (idempotent) |
| `pcip/generate/providers.py` | Provider registry: Claude copy, Canva design, image/video slots |
| `pcip/generate/orchestrator.py` | Brief-driven generation; records outputs + licenses in the graph |
| `pcip/pipelines/base.py` | Pipeline engine: steps, review gates, resumable persisted runs |
| `pcip/pipelines/library.py` | The six standard deliverable pipelines |
| `pcip/publish/router.py` | License- and review-checked publishing; distribution record |
| `pcip/cli.py` | `python -m pcip …` operator interface |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in the PCIP section, then:
export $(grep -v '^#' .env | xargs)

python -m pcip init       # create pcip_data/ + graph.db
python -m pcip status     # verify connectors
python -m pcip sync       # mirror your Canva library into the graph
```

### Canva credentials (official Connect API)

1. Create an integration at <https://www.canva.com/developers/> (your Canva
   Business account).
2. Grant scopes: `design:meta:read design:content:read design:content:write
   folder:read asset:read brandtemplate:meta:read brandtemplate:content:read`.
3. Complete the OAuth (PKCE) flow once; put the tokens in `.env`
   (`CANVA_CLIENT_ID`, `CANVA_CLIENT_SECRET`, `CANVA_REFRESH_TOKEN`). PCIP
   refreshes access tokens automatically (Canva rotates refresh tokens).

The Canva MCP server in Claude is a complement, not a dependency — PCIP uses
the same underlying Connect API with your own integration credentials.

## Daily workflow

```bash
# 1. Write a brief (see examples/brief.example.json)
python -m pcip run patient_education --brief brief.json
# → runs until the medical_review gate, then pauses

# 2. Review the assembled design in Canva, then:
python -m pcip approve run_abc123 --gate medical_review --reviewer "Dr. Pascual"
# → brand_review gate next; approve again and it exports via the official API

# 3. Publish. Body, excerpt, per-image alt text, captions and hashtags all come
#    from the pipeline's own copy step — --title/--text are overrides, not
#    requirements. WordPress lands as a draft unless --live.
python -m pcip publish out_xyz789 --channel wordpress --live
python -m pcip publish out_xyz789 --channel instagram

# ...or hand it off for manual pasting (same gates, no credentials needed)
python -m pcip prepare out_xyz789

# 4. Ask the graph anything
python -m pcip search "diabetes carousel"
python -m pcip graph canva:design:DAF123 --depth 2
```

## Extending

- **New image/video vendor**: subclass `ImageGenerationProvider` or
  `VideoGenerationProvider` in `pcip/generate/media_providers.py`, decorate
  with `@register_provider`, and add a `ProviderProfile` for it in
  `pcip/generate/capabilities.py`. Routing picks it up automatically — no
  pipeline or orchestrator changes.
- **Re-ranking vendors as models improve**: edit `DEFAULT_PROFILES` in
  `pcip/generate/capabilities.py` — vendor knowledge lives in that table,
  never in business logic.
- **New channel**: add a `SocialAdapter` (set `mode = "direct"` or
  `"scheduler"`) in `pcip/connectors/social.py` and list it in `ADAPTERS`.
- **New deliverable**: compose steps + gates in `pcip/pipelines/library.py`;
  the engine handles persistence, pause/resume, and approvals.

## Connector management: capabilities, not credentials

The platform never asks "is Canva connected?" — it asks "**can I** export a
PNG? duplicate a brand template? search premium assets?" and gets a
machine-readable answer per capability:

```bash
python -m pcip doctor            # diagnose everything declared in bootstrap.yaml
python -m pcip doctor --live     # + live auth/entitlement probes
python -m pcip can canva.export_png
```

- **`bootstrap.yaml`** (repo root) declares which connectors this deployment
  wants and how each authenticates — the doctor provisions/diagnoses from
  it; removing a connector disables it. Credentials stay in `.env`, never in
  the manifest.
- **Statuses per capability**: `ready` · `configured` · `mcp_managed` ·
  `missing_credentials` · `auth_failed` · `not_entitled` (plan-gated, e.g.
  Canva brand templates without Enterprise) · `unsupported` (the vendor API
  genuinely can't — e.g. `canva.search_premium_assets`) · `disabled`.
- **MCP servers expose external systems**: the official GitHub MCP server is
  the repository/automation backbone and appears as `mcp_managed` — PCIP
  holds no GitHub credentials. The Canva MCP complements the Connect API the
  same way.
- The planner consumes `ConnectorManager.can()` so pipelines degrade
  gracefully around missing entitlements instead of assuming a connected
  system can do everything.

## Setup

Step-by-step credential setup for every provider, with links:
**[pcip/SETUP.md](SETUP.md)** — and `python -m pcip doctor` tells you at any
moment what's left to do.

## Tests

```bash
python -m pytest tests/ -q     # offline tests: graph, licensing, pipelines,
                               # capability routing, publish decision engine
```
