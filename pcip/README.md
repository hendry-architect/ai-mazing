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
 ┌───────┴────────┐    │  AI image/video (pluggable) → Canva         │
 │  AI PROVIDERS  │───►│  autofill → ⛔ REVIEW GATES → export        │
 │  Claude (copy) │    └──────────────────┬──────────────────────────┘
 │  image slot    │                       ▼
 │  video slot    │    ┌─────────────────────────────────────────────┐
 └────────────────┘    │        LICENSE-CHECKED PUBLISH ROUTER       │
                       │  passqual.com (WordPress) · Instagram ·     │
                       │  Facebook · LinkedIn · X · TikTok · YouTube │
                       └─────────────────────────────────────────────┘
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
4. **Orchestrated generation.** Claude writes the copy package (headlines,
   captions, CTA, hashtags, alt-text); image/video providers are pluggable
   slots; Canva brand-template autofill assembles it all on-brand. Swap any
   vendor without touching the pipelines.
5. **Distribution memory.** Publishing to passqual.com or a social channel
   records a Publication node — "where did this asset go?" has a permanent
   answer.

## Module map

| Module | Responsibility |
|---|---|
| `pcip/models.py` | Domain models: assets, licenses, briefs, runs, publications, graph vocabulary |
| `pcip/config.py` | Env-based configuration; no secrets in code or the graph |
| `pcip/licensing.py` | Licensing policy engine (pure, fully unit-tested) |
| `pcip/connectors/canva.py` | Canva Connect API client: OAuth refresh, designs, folders, assets, brand templates, autofill, export |
| `pcip/connectors/wordpress.py` | passqual.com publisher (drafts by default) |
| `pcip/connectors/social.py` | Buffer / Meta Graph / LinkedIn adapters |
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

- **Image/video generation**: subclass `GenerationProvider` with capability
  `"image"` or `"video"`, implement `available()`/`generate()` (attach an
  `ai_license(provider)` to every asset), and decorate with
  `@register_provider`. The registry prefers any provider that reports
  available, so the built-in slots step aside automatically.
- **New channel**: add a `SocialAdapter` in `pcip/connectors/social.py` and
  list it in `ADAPTERS`.
- **New deliverable**: compose steps + gates in `pcip/pipelines/library.py`;
  the engine handles persistence, pause/resume, and approvals.

## Tests

```bash
python -m pytest tests/ -q     # 26 offline tests: graph, licensing, pipelines, publish
```
