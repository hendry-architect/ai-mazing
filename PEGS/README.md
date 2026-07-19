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

## The twelve libraries

Modular libraries of templates, SOPs, checklists, examples, and automation
hooks, shelved inside the canon folders. Two cross-cutting systems serve all
of them: the **Meeting Kit** (`11-Meetings/meeting-kit/` — every meeting
auto-generates agenda → packet → minutes → decisions → actions → owners →
due dates → follow-up → quarterly/annual archives) and the **Integration
Standard** (`13-Automation/INTEGRATION-STANDARD.md` — every artifact is
frontmattered and machine-consumable by Claude Code/Projects, GitHub,
Notion, Google Workspace, Microsoft 365, n8n, Zapier, Make, Obsidian, and
Apple Reminders/Calendar).

| # | Library | Location |
|---|---|---|
| L-EA | **Enterprise Architecture (PEGS-150)** — the master blueprint every artifact obeys | `02-Governance/PEGS-150-enterprise-architecture/` |
| L01 | Enterprise Constitution (charter, alignment checklist, annual review) | `01-Constitution/` |
| L02 | Executive Leadership System (role charters, authority matrix, succession, reviews, on/offboarding) | `03-Executive-Leadership/` |
| L03 | Strategic Advisory Council (charter, advisor agreement, quarterly SOP, retreat framework) | `04-Advisory-Council/` |
| L04 | Corporate Secretary Office (resolutions, consents, notices, governance calendar) | `02-Governance/corporate-secretary/` |
| L05 | Enterprise Planning System (annual→quarterly→monthly→weekly, OKR/KPI guide) | `11-Meetings/planning-system/` + `meeting-kit/` |
| L06 | Enterprise Knowledge Base (knowledge system, glossary, decision archive) | `14-Knowledge-Base/` |
| L07 | Family Office & Legacy (family constitution, succession roadmap, heir education, family meetings, wealth stewardship) | `06-Trust/` |
| L08 | Foundation Governance (nonprofit framework, grant SOP, impact report, program oversight) | `05-Foundation/` |
| L09 | Holding Company Governance (intercompany agreements, capital allocation, treasury) | `07-Holdings/` |
| L10 | AI Governance (AI usage policy, prompt library, Claude Code workflows, knowledge sync, automation catalog, integration standard) | `13-Automation/` |
| L11 | Travel & Executive Retreat System (retreats, travel playbooks, budgets/itineraries) | `11-Meetings/retreats-travel/` |
| L12 | Enterprise Risk & Compliance (compliance matrix, risk/insurance registers, BCP, incident response, cybersecurity) | `10-Policies/risk-compliance/` |

## Document IDs

- **Governance documents** keep permanent IDs: PEGS-000 (constitutional),
  PEGS-1xx (structural — the "100-series charters" PEGS-000 references). IDs
  never change, even if a document moves shelves.
- **Sub-series** use dotted numbering: `PEGS-150.NNN` = the Enterprise
  Architecture blueprints (150-series, inside the structural 100-series,
  shelved at `02-Governance/PEGS-150-enterprise-architecture/`).
- **Working documents** are named by convention instead: `SOP-<company>-<topic>`,
  decision memos and minutes by date. Not everything needs a constitutional ID.

## Governance map (precedence & cross-reference)

Conflicts resolve upward through this chain; every document references the
layer above it:

`PEGS-000 (Constitution) → PEGS-150 (Architecture) → PEGS-100/101
(Structure & Succession) → plans & policies (L05/L09/10-Policies) → role
charters & matrices (L02, nested under PEGS-150.006) → SOPs & brand canons
(09/08) → records (11-Meetings/15-Archives)`

Domain placement rule for every new artifact: PEGS-150.001 §4.

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
| PEGS-100 | Enterprise Structure & Entity Map | 02-Governance | 1.0.0 | RATIFIED — 2026-07-19 · amendment pending (entity roster, Phase 3.5) | Founder |
| PEGS-101 | Stewardship Council Charter | 02-Governance | 1.0.0 | RATIFIED — 2026-07-19 | Founder |
| PEGS-150.001 | Enterprise Architecture Overview | 02-Governance/PEGS-150 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-150.002 | Enterprise Ecosystem Blueprint | 02-Governance/PEGS-150 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-150.003 | Enterprise Organizational Blueprint | 02-Governance/PEGS-150 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-150.004 | Governance Relationship Matrix | 02-Governance/PEGS-150 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-150.005 | Enterprise Cash Flow Blueprint | 02-Governance/PEGS-150 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-150.006 | Decision Authority Matrix | 02-Governance/PEGS-150 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-150.007 | Five-Year Enterprise Blueprint | 02-Governance/PEGS-150 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-150.008 | PEGS Enterprise Playbook (TOC) | 02-Governance/PEGS-150 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |
| PEGS-150.009 | Governance Maturity Roadmap | 02-Governance/PEGS-150 | 0.1.0 | DRAFT — awaiting Founder ratification | Founder |

## Phase roadmap

| Phase | Deliverable | Folders | Status |
|---|---|---|---|
| **1** | Enterprise Constitution | 01 | ✅ RATIFIED 2026-07-19 (PR #1) |
| **2** | Governance structure + repository architecture | 02, full 01–15 tree, 12 | ✅ RATIFIED 2026-07-19 (PR #2) |
| **3** | Twelve modular libraries (L01–L12): templates, SOPs, checklists, automation hooks | all | ✅ RATIFIED 2026-07-19 (PR #3) |
| **4** | Template layer completed: 11 gap templates + master index (48 templates total) | 12 + all | ✅ RATIFIED 2026-07-19 (PR #4) |
| **3.5** | Enterprise Architecture (PEGS-150.001–.009): the master blueprint — inserted by Founder directive; all later phases must conform to it | 02-Governance/PEGS-150 | 🔄 In review — Phase 4/5 HALTED pending ratification + PEGS-100 amendment |
| **5** | Instantiation: fill libraries with real names, numbers, and ratified policies (role charters signed, matrices populated, calendars loaded) | 03, 08–11 | HALTED — awaiting Phase 3.5 ratification, Missing Info answers, PEGS-100 amendment |
| **6** | Structure & legacy instruments: council seated, foundation formed, trust executed, holdings chartered | 04, 05, 06, 07 | Awaiting Founder command |
| **7** | Automation build-out: catalog items AUT-002+ shipped live | 13 | Backlog live in AUTOMATION-CATALOG.md |

Phases are sequential on purpose: each layer derives authority from the one
above it, so building out of order creates documents with no legitimacy chain.

## Delegation model

Every folder and every document has exactly one **custodian** — accountable
for accuracy, review cadence, and proposing amendments. Today the Founder is
custodian of nearly everything; each ratified phase moves custody downward,
which is the point: the Founder governs the Constitution; the Constitution
governs everything else.
