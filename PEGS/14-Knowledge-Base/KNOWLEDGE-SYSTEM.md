---
id: pegs-l06-knowledge-system
type: standard
library: L06-enterprise-knowledge-base
title: Enterprise Knowledge System
version: 0.1.0
status: active
owner: founder
---

# Enterprise Knowledge System

How the Enterprise remembers. One authoritative location per fact
(PEGS-000 Art. VI §1); everything below serves that rule.

## 1. Folder structure

The 15-folder PEGS tree (`PEGS/README.md`) IS the folder structure — no
parallel trees in Drive/Notion/Obsidian. Other platforms mirror this repo
(INTEGRATION-STANDARD); they never originate structure.

## 2. File naming conventions

- `TYPE-descriptor.md` — TEMPLATE- / SOP- / CHECKLIST- / GUIDE- /
  FRAMEWORK- / PLAYBOOK- prefixes make type greppable.
- Records: `YYYY-MM-DD-<slug>.md` (sorts chronologically by name).
- Kebab-case, ASCII, no spaces, no versions in filenames (git carries
  versions; frontmatter carries the number).

## 3. Version control

- `main` = in force. Branches + PRs = proposals. Merge = ratification.
- Frontmatter `version` bumps on meaningful change (semver: major =
  substance, minor = additions, patch = wording).
- Superseded documents → `15-Archives` per its README. Nothing deleted.

## 4. Decision archive

Every decision is findable by ID:
- **D-IDs** from minutes (Meeting Kit) → filed in `11-Meetings/records/`
- **Decision memos** (Class 2) → filed with their meeting or entity
- **Resolutions/consents** → `02-Governance/corporate-secretary/`
An index (auto-built ⚙ from the D-ID tables) lives here as
`decision-index.md`: ID · date · decision · class · where the record is.

## 5. Policy library

`10-Policies/` is the policy library; this folder holds the *index with
status* (auto-generated ⚙): policy · version · ratified date · owner ·
next review. An unlisted policy is not in force.

## 6. Institutional memory

- **PEGS-950 — Lessons Learned Register:** every mission, quarter,
  summit, and major project closes with exactly four questions (what
  worked · what created friction · what should become standard · what
  should never happen again) — `PEGS-950-lessons-learned-register.md`,
  entries LL-YYYY-NNN, immutable once filed.
- **Ratified learnings:** "should-become-standard" answers graduate to
  `learnings/YYYY-MM-DD-<slug>.md` only by explicit ratification (a PR
  someone approved) — insight by drift is rumor.
- **Exit knowledge:** offboarding SOP files departing-leader lessons here.
- **Glossary:** [GLOSSARY.md](GLOSSARY.md) — every defined term and
  canonical owner handle, one place.
- **Onboarding paths:** reading orders per role (constitution first,
  always).
