---
id: pegs-l10-sop-knowledge-sync
type: sop
library: L10-ai-governance
title: Knowledge Synchronization SOP
version: 0.1.0
status: active
owner: founder
---

# SOP — Knowledge Synchronization

One source of truth (`main`), many projections. This SOP keeps them honest.

| Field | Value |
|---|---|
| Owner | Founder (until a knowledge role is chartered) |
| Trigger | Any merge to `main` that ratifies or amends canon |

## Procedure

1. **On ratification merge ⚙** — export the ratified `.md` files.
2. **Claude Projects** — upload/replace the changed files in the PEGS
   project's knowledge; remove superseded versions (stale knowledge in an
   AI's context is worse than none).
3. **Notion / Drive mirrors (when live) ⚙** — sync job maps frontmatter →
   properties; mirrors are read-only projections. Edits happen in the repo,
   or they didn't happen.
4. **Obsidian** — `git pull` in the vault clone; nothing else to do.
5. **Quarterly integrity check** — one spot-audit: pick 3 documents, verify
   every projection matches `main` (version field comparison ⚙). Drift
   found → fix the projection, then fix the sync job that let it drift.

## The anti-drift rules

- No projection is ever edited in place.
- Anything found only in a projection is treated as unratified input:
  bring it to the repo via PR or let it die.
- New platforms join the map only with a sync method defined here first.

## Quality bar

Zero version mismatches at quarterly check; Claude Projects never more
than one merge behind `main`.
