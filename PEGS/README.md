# PEGS — Pascual Enterprise Governance System

PEGS is the written canon of the Pascual Enterprise: one versioned document
system that governs every entity, brand, role, and process. It is designed so
governance scales without the Founder as bottleneck — documents carry the
standards, custodians carry the accountability, and this repository carries
the single source of truth.

**Supreme document:** [PEGS-000 — The Pascual Enterprise Constitution](01-Constitution/PEGS-000-enterprise-constitution.md)
— RATIFIED v1.0.0 (2026-07-19). Everything references it. Nothing gets built
before it. Conflicts always resolve upward to it (Art. VIII §1).

---

## Repository architecture

Fifteen numbered folders, each with a README defining its purpose, rules, and
custodian. The number is the shelf; authority comes from ratification, not
position.

| Folder | Layer | Holds |
|---|---|---|
| [01-Constitution](01-Constitution/) | Supreme | PEGS-000, amendment log, annual review records |
| [02-Governance](02-Governance/) | Structural | Entity map (PEGS-100), Stewardship Council (PEGS-101), governance acts |
| [03-Executive-Leadership](03-Executive-Leadership/) | Roles | Delegation matrix, role charters, escalation canon |
| [04-Advisory-Council](04-Advisory-Council/) | Counsel | Advisory board charter and onboarding — advice, never authority |
| [05-Foundation](05-Foundation/) | Giving | Philanthropic charter, giving pillars, grant criteria |
| [06-Trust](06-Trust/) | Legacy | Family/succession instruments, sealed roster, incapacity process |
| [07-Holdings](07-Holdings/) | Capital | Holding structure, ownership map, capital allocation, risk register |
| [08-Companies](08-Companies/) | Operating | One subfolder per company: charter + brand canon |
| [09-SOP](09-SOP/) | Procedure | Standard operating procedures, owner-ratified |
| [10-Policies](10-Policies/) | Rules | Cross-enterprise policies (compliance, AI use, brand, family employment) |
| [11-Meetings](11-Meetings/) | Rhythm | Meeting cadence canon, agendas, minutes, decision records |
| [12-Templates](12-Templates/) | Friction-reduction | Doc, decision-memo, and SOP templates |
| [13-Automation](13-Automation/) | Leverage | Automation register, build specs, backlog |
| [14-Knowledge-Base](14-Knowledge-Base/) | Memory | Glossary, ratified learnings, onboarding paths |
| [15-Archives](15-Archives/) | Record | Superseded documents — nothing is ever deleted |

**Layering logic:** 01–02 say what the Enterprise *is*; 03–08 say *who* acts
and *where*; 09–11 say *how*; 12–15 make the whole system cheap to run and
impossible to forget.

## Document IDs

- **Governance documents** keep permanent IDs: PEGS-000 (constitutional),
  PEGS-1xx (structural — the "100-series charters" PEGS-000 references). IDs
  never change, even if a document moves shelves.
- **Working documents** are named by convention instead: `SOP-<company>-<topic>`,
  decision memos and minutes by date. Not everything needs a constitutional ID.

## Document lifecycle

`DRAFT → IN REVIEW → RATIFIED → AMENDED (vX.Y.Z) → SUPERSEDED (→ 15-Archives)`

Nothing is canon until explicitly ratified by the authority for its class
(PEGS-000 Art. VI §2); superseded text is preserved forever (Art. VIII §3).

## Workflow (how a document becomes canon)

1. **Draft** from a [12-Templates](12-Templates/) template, on a branch.
2. **Pull request** = the written review record — discussion, dissent, and
   revisions, timestamped and attributable (Art. V §3).
3. **Ratifying authority approves + merge to `main` = ratification.** For
   governance documents that is the Founder; for SOPs, the accountable owner
   (PEGS-000 Art. VI §3 — subsidiarity). `main` is the canon; anything not on
   `main` is not in force.
4. **Registry updated** in the same PR.

The ratification workflow *is* the git workflow — no parallel approval system.

## Registry (living index of governance documents)

| ID | Title | Location | Version | Status | Custodian |
|---|---|---|---|---|---|
| PEGS-000 | The Pascual Enterprise Constitution | 01-Constitution | 1.0.0 | RATIFIED — 2026-07-19 | Founder |
| PEGS-100 | Enterprise Structure & Entity Map | 02-Governance | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-101 | Stewardship Council Charter | 02-Governance | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |

## Phase roadmap

| Phase | Deliverable | Folders | Status |
|---|---|---|---|
| **1** | Enterprise Constitution | 01 | ✅ RATIFIED 2026-07-19 (PR #1) |
| **2** | Governance structure + repository architecture | 02, full 01–15 tree, 12 | 🔄 In review |
| **3** | Executive leadership: delegation matrix, role charters | 03 | Blocked on Phase 2 |
| **4** | Operations: company charters, SOPs, policies, meeting rhythm | 08, 09, 10, 11 | Blocked on Phase 3 |
| **5** | Structure & legacy: advisory council, foundation, trust, holdings | 04, 05, 06, 07 | Blocked on Phase 4 |
| **6** | Scale systems: automation build-out, knowledge base | 13, 14 | Backlog live; build after Phase 2 |

Phases are sequential on purpose: each layer derives authority from the one
above it, so building out of order creates documents with no legitimacy chain.

## Delegation model

Every folder and every document has exactly one **custodian** — accountable
for accuracy, review cadence, and proposing amendments. Today the Founder is
custodian of nearly everything; each ratified phase moves custody downward,
which is the point: the Founder governs the Constitution; the Constitution
governs everything else.
