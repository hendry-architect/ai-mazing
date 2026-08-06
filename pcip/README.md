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

## Module map

| Module | Responsibility |
|---|---|
| `pcip/models.py` | Domain models: assets, licenses, briefs, runs, publications, graph vocabulary |
| `pcip/config.py` | Env-based configuration; no secrets in code or the graph |
| `pcip/licensing.py` | Licensing policy engine (pure, fully unit-tested) |
| `pcip/connectors/canva.py` | Canva Connect API client: OAuth refresh, designs, folders, assets, brand templates, autofill, export |
| `pcip/connectors/wordpress.py` | passqual.com publisher (drafts by default) |
| `pcip/connectors/social.py` | Direct adapters (Meta, LinkedIn, X, Threads, YouTube, TikTok) + Buffer scheduler; mode-aware resolver |
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

# 3. Publish (WordPress lands as a draft unless --live)
python -m pcip publish out_xyz789 --channel wordpress --title "..." --text "<p>…</p>"
python -m pcip publish out_xyz789 --channel instagram --text "caption #hashtags"

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

## Setup

Step-by-step credential setup for every provider, with links:
**[pcip/SETUP.md](SETUP.md)**.

## Tests

```bash
python -m pytest tests/ -q     # offline tests: graph, licensing, pipelines,
                               # capability routing, publish decision engine
```
