# PEGS — Pascual Enterprise Governance System

PEGS is the written canon of the Pascual Enterprise: one numbered, versioned
document system that governs every entity, brand, role, and process. It is
designed so that governance scales without the Founder being the bottleneck —
documents carry the standards, custodians carry the accountability, and this
repository carries the single source of truth.

**Supreme document:** [PEGS-000 — The Pascual Enterprise Constitution](PEGS-000-enterprise-constitution.md).
Every other document references it. Nothing gets built before it. Conflicts
between documents always resolve to the more constitutional document, and
PEGS-000 wins over everything.

---

## Document architecture

Documents are numbered by series. The series tells you what kind of authority
a document carries and who its natural custodian is.

| Series | Domain | Examples |
|---|---|---|
| **000** | Constitutional | PEGS-000 Constitution, amendment log |
| **100** | Governance structure | Stewardship Council charter, entity map, holding structure |
| **200** | Roles & decision rights | Role charters, delegation matrix, escalation triggers |
| **300** | Operating systems & playbooks | Clinic operations, publishing pipeline, media production |
| **400** | Capital, finance & risk | Capital allocation policy, risk register, acquisition criteria |
| **500** | People, family & succession | Hiring canon, family employment policy, succession plans |
| **600** | Technology, AI & automation | Automation doctrine implementation, AI use policy, data governance |
| **700** | Brand & communication canon | Brand charters and firewalls, voice guides, command registries |

Numbering: `PEGS-<nnn>-<kebab-case-title>.md`, one document per file, all in
this directory. The first document of a series takes the round number
(PEGS-100); related documents follow sequentially (PEGS-101, PEGS-102…).

## Document lifecycle

Every document carries a status in its document-control block:

`DRAFT → IN REVIEW → RATIFIED → AMENDED (vX.Y.Z) → SUPERSEDED`

Ratification rules come from PEGS-000 Article VI §2 and Article VIII: nothing
is canon until explicitly ratified by the authority for its class, and
superseded text is preserved in git history — the record is never erased.

## Workflow (how a document becomes canon)

1. **Draft** from [templates/PEGS-DOC-TEMPLATE.md](templates/PEGS-DOC-TEMPLATE.md)
   on a branch. The template enforces the document-control block, the PEGS-000
   reference, and the ratification footer.
2. **Pull request** = the review record. Discussion, dissent, and revisions
   live on the PR — written, timestamped, attributable, exactly as Article V
   §3 requires.
3. **Founder (or delegated authority) approval + merge to `main` = ratification.**
   `main` is the canon; anything not on `main` is not in force.
4. **Registry updated** in the same PR (table below), status set to RATIFIED,
   version set.

This makes governance automation-native: the ratification workflow *is* the
git workflow. No parallel approval system, no document floating in inboxes.

## Registry (living index)

| ID | Title | Series | Version | Status | Custodian |
|---|---|---|---|---|---|
| PEGS-000 | The Pascual Enterprise Constitution | 000 | 1.0.0 | RATIFIED — 2026-07-19 | Founder |
| PEGS-100 | Enterprise Structure & Entity Map | 100 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-101 | Stewardship Council Charter | 100 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |

## Phase roadmap

| Phase | Deliverable | Depends on | Status |
|---|---|---|---|
| **1** | PEGS-000 Constitution | — | ✅ RATIFIED 2026-07-19 (PR #1) |
| **2** | Governance structure (100-series): entity map, Stewardship Council charter | Phase 1 ratified | 🔄 Drafted — in review |
| **3** | Roles & decision rights (200-series): delegation matrix, role charters, escalation triggers | Phase 2 | Not started |
| **4** | Operating systems (300/700-series): brand canons, clinic ops, publishing & media playbooks | Phase 3 | Not started |
| **5** | Capital, people, technology (400/500/600-series) | Phase 4 | Not started |

Phases are sequential on purpose: each series derives authority from the one
above it, so building out of order creates documents with no legitimacy chain.

## Automation opportunities (600-series backlog)

Captured now, implemented once Phase 1 is ratified:

- **Registry lint (CI):** check that every `PEGS-*.md` appears in the registry,
  has a valid document-control block, and references PEGS-000.
- **Scaffolding command:** one script that copies the template, assigns the
  next free number in a series, and pre-fills the control block.
- **Annual review trigger:** a scheduled reminder for the Article VI §7
  constitutional review, with a checklist issue auto-created.
- **Canon publishing:** auto-render `main` into a private, readable canon site
  for executives, advisors, and family — no one governs from raw markdown.

## Delegation model

Every document has exactly one **custodian** — the person accountable for its
accuracy, its review cadence, and proposing its amendments. The Founder is
custodian of the 000-series only. As the 200-series lands, custody of the
lower series moves to the accountable role holders, which is the point: the
Founder governs the Constitution; the Constitution governs everything else.
