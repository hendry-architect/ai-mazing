---
id: pegs-l10-integration-standard
type: standard
library: L10-ai-governance
title: PEGS Integration Standard
version: 0.1.0
status: active
owner: founder
---

# PEGS Integration Standard

Every PEGS artifact is designed to be machine-consumable **on the day an
integration is switched on**, without rework. This standard is why.

## Design rules (every artifact in every library)

1. **Markdown + YAML frontmatter.** Every template, SOP, checklist, and record
   opens with a frontmatter block: `id` (stable, unique, kebab-case, never
   reused), `type` (template|sop|checklist|policy|record|standard|guide),
   `library` (L01–L12), `title`, `version`, `status`, `owner`. Records add
   `date`, `meeting`, and `due` fields as applicable.
2. **One artifact per file.** Automations address files, not sections.
3. **Structured tables for anything a machine must act on** — decisions,
   action items, registers, calendars. Fixed column order, one row per item.
4. **ISO dates (`YYYY-MM-DD`)** everywhere. Owners are named consistently
   (one canonical handle per person, defined in `14-Knowledge-Base/GLOSSARY.md`).
5. **GitHub `main` is the single source of truth.** Every other platform is a
   projection of it — synced from it, never competing with it (PEGS-000
   Art. VI §1: one authoritative location).

## Platform map (how each target consumes PEGS)

| Platform | Integration pattern |
|---|---|
| **Claude Code** | Native — this repo. Skills/commands read libraries directly; PR flow = ratification flow. |
| **Claude Projects** | Upload ratified `.md` files as project knowledge after each merge (see `SOP-knowledge-sync.md`). |
| **GitHub** | Source of truth. Webhooks on merge/push are the trigger bus for all automation platforms. |
| **Notion** | n8n/Zapier/Make job maps frontmatter → database properties, body → page. One database per artifact `type`. |
| **Google Workspace** | pandoc `md → Docs` for documents; action/register tables → Sheets; calendars/due dates → Google Calendar via ICS or API. |
| **Microsoft 365** | Same pattern via pandoc + Microsoft Graph (Word, Excel, Outlook calendar). |
| **n8n / Zapier / Make** | Subscribe to GitHub webhooks → parse frontmatter + tables → create tasks, events, notifications, follow-ups. n8n preferred (self-hosted, PHI-safe boundary); all three use identical inputs. |
| **Obsidian** | Zero-work: an Obsidian vault pointed at a clone of this repo reads frontmatter and markdown natively. |
| **Apple Reminders & Calendar** | Action-item tables and calendar templates export as ICS / feed Shortcuts automations (due dates + owners are already structured). |

## The meeting rule

Every meeting in the Enterprise runs on the Meeting Kit
(`11-Meetings/meeting-kit/`) and therefore automatically produces: agenda,
board packet, minutes, decision log, action items with owners and due dates,
follow-up report, and quarterly + annual archives. No meeting artifact is
ever free-form.

## Firewall boundary

No automation transmits PHI, clinical judgments, legal commitments, or
`06-Trust` contents to any external platform without an explicit,
Founder-ratified exception naming the platform, the data, and the safeguard
(PEGS-000 Art. VI §4–§5). Default is: firewalled content stays in
firewall-approved systems.
