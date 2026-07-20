---
id: pegs-l10-automation-catalog
type: standard
library: L10-ai-governance
title: Automation Catalog
version: 0.1.0
status: active
owner: founder
---

# Automation Catalog

The register required by PEGS-000 Art. VI §5: **an automation without a
named human owner does not run.** One row per automation, live or planned.

| ID | Automation | Trigger | Platform | Human owner | Inspection method | Firewall boundary | Status |
|---|---|---|---|---|---|---|---|
| AUT-001 | PR watch + ratification mechanics | PR events | Claude Code | founder | PR history | none crossed | LIVE |
| AUT-002 | Registry lint (control block + registry consistency) | push/PR | GitHub CI | founder | CI logs | n/a | BACKLOG |
| AUT-003 | Doc scaffolding (template → new doc, frontmatter pre-filled) | manual command | Claude Code script | founder | git diff | n/a | BACKLOG |
| AUT-004 | Annual constitutional review reminder + checklist | July cron | Routine/n8n | founder | fired-run log | n/a | BACKLOG |
| AUT-005 | Meeting chain: agenda pre-fill from action tracker | T-7d cron | n8n | secretary fn | weekly meeting §2 | none | BACKLOG |
| AUT-006 | Follow-up → tasks/reminders/calendar (Todoist/Apple/Google) | minutes filed | n8n | secretary fn | tracker vs. tasks spot-check | no PHI in task text | BACKLOG |
| AUT-007 | Governance calendar → ICS feeds | calendar change | n8n | secretary fn | subscribed calendars | n/a | BACKLOG |
| AUT-008 | Quarter/annual archive compilation | quarter close | Claude Code | founder | index review | none | BACKLOG |
| AUT-009 | Knowledge sync to Claude Projects/Notion | merge to main | n8n + manual | founder | quarterly integrity check | Trust/PHI excluded | BACKLOG |
| AUT-010 | Dashboard pulls (KPIs → packet §2) | weekly cron | n8n + Sheets | ops lead (future) | monthly review §1 | no PHI, aggregates only | BACKLOG |
| AUT-011 | Playbook compiler (canon → single readable book) | on merge | Claude Code | founder | compiled output review | none | BACKLOG |
| AUT-012 | Asset registry ↔ insurance ↔ risk reconciliation | quarterly | Claude Code | founder | findings list | none | BACKLOG |
| AUT-013 | PEGS-900 Chairman's Book monthly compile | last day of month | Claude Code (CGO-manual until built) | founder | Founder reads §0 | private — Founder-only sync | CGO-MANUAL |
| AUT-014 | Chairman's Dashboard + Weekly Brief refresh | Fri cron | Claude Code (CGO-manual until built) | founder | last-refreshed stamp | private | CGO-MANUAL |

## Rules

1. New automation = new row FIRST (owner, inspection, boundary), build
   second.
2. Owner reviews their automation's output on the stated inspection rhythm;
   an uninspected automation is retired.
3. Any automation touching money, PHI, clinical, legal, or the Founder's
   voice: see AI Usage Policy §2 — human action stays in the loop.
4. Retired automations move to a RETIRED section with date and reason —
   the catalog is also a history.
