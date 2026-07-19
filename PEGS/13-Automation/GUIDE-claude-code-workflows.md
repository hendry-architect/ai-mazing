---
id: pegs-l10-claude-code-workflows
type: guide
library: L10-ai-governance
title: Claude Code Workflows for PEGS
version: 0.1.0
status: active
owner: founder
---

# Claude Code Workflows

How the Enterprise uses Claude Code as its governance engine. The repo is
the canon; Claude Code is the hands.

## The core loop (every phase so far, every phase to come)

1. Founder issues the phase prompt (Founder sets the pace — always).
2. Claude drafts on the working branch, from templates, anchored to
   PEGS-000; opens a **draft PR** (never self-ratifies).
3. Founder reviews; comments become revisions.
4. Founder approves → merge = ratification → Claude flips control blocks to
   RATIFIED, updates the registry, delivers the `.md` artifacts.
5. Claude stops and waits for the next phase prompt.

## Standing session behaviors

- **PR watching:** subscribe on creation; hourly self check-ins; act on
  comments; stop at merge/close.
- **Session hygiene:** one working branch (`claude/pegs-*`); restart from
  `main` after each merge; commits carry clear why-messages.
- **Deliverables:** ratified documents delivered as `.md` (and PDF for
  formal archival copies) for upload into Claude Projects.

## Division of labor

| Layer | Tool |
|---|---|
| Canon authoring, PRs, ratification mechanics | Claude Code (this repo) |
| Knowledge at hand in strategy conversations | Claude Projects (synced canon — see SOP-knowledge-sync) |
| Brand production commands | /SOSTENGO, /PH, /PHSEO per Command Registry |
| Event-driven automation (tasks, calendars, notifications) | n8n/Zapier/Make off GitHub webhooks per INTEGRATION-STANDARD |

## Future build (Automation Catalog backlog)

Registry-lint CI · scaffolding script (new doc from template with
frontmatter pre-filled) · quarter-close automation · ICS generation from
the governance calendar. Each ships with a named human owner or it doesn't
ship (AI Usage Policy §2).
