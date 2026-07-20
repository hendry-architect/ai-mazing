# PEGS-150.006 — Decision Authority Matrix (Enterprise-Level)

| Field | Value |
|---|---|
| Document ID | PEGS-150.006 |
| Series | 150 — Enterprise Architecture (02-Governance) |
| Version | 1.0.0 |
| Status | RATIFIED — 2026-07-19 (PR #5 + PR #6, Founder written ratification) |
| Custodian | Founder (Chief Enterprise Architect function) |
| References | PEGS-000 Art. V; PEGS-101 §4–§5; PEGS-150.004; L02 authority matrix template |
| Review cadence | Annual + on any role/body change |

> **Extends PEGS-000 Art. V.** The Constitution defines decision *classes*;
> this matrix assigns decision *domains* to authorities, Fortune-100 style.
> Entity-level matrices (L02 template) must nest inside this one — an
> entity may tighten these rules, never loosen them.

---

## 1. Legend

**A** = Approve (final authority) · **R** = Recommend (prepares the memo)
· **C** = Consult (advice recorded) · **I** = Inform (after the fact) ·
**—** = no role. Bodies: **FDR** Founder · **CEO** entity chief executive
(role TBD Phase 4) · **ELT** Executive Leadership Team · **SAC** Strategic
Advisory Council 🔮 · **LC** Legacy Council 🔮 · **TR** Trustee 🔮.
*Dormant/future bodies hold their letters only upon activation; until
then their column collapses into FDR.*

## 2. The matrix

| # | Decision domain | Class | FDR | CEO | ELT | SAC | LC | TR |
|---|---|---|---|---|---|---|---|---|
| 1 | Constitutional amendment (PEGS-000) | 1 | **A** (Art. VIII) | I | I | C | C | — |
| 2 | Entity formation / closure / restructuring | 2 | **A** | R | C | C | I | I |
| 3 | Acquisitions (any size) | 2 | **A** | R | C | C | I | I |
| 4 | Executive hiring / termination (chiefs, key roles) | 2 | **A** | R | C | C | — | — |
| 5 | Hiring below executive level | 3 | I | **A** | R | — | — | — |
| 6 | Real estate: purchase / sale / lease > threshold | 2 | **A** | R | C | C | — | I |
| 7 | Banking: new accounts, signers, credit facilities | 2 | **A** | R | I | — | — | I |
| 8 | Loans / debt issuance | 2 | **A** | R | C | C | — | I |
| 9 | Budgets (annual, per entity) | 2 | **A** | R | C | I | — | — |
| 10 | Capital expenditure within approved budget | 3 | I | **A** | I | — | — | — |
| 11 | Capital expenditure beyond budget / > threshold | 2 | **A** | R | C | — | — | — |
| 12 | Technology: core platform selection (EHR, infra) | 2 | **A** | R | C | C | — | — |
| 13 | Technology: tools within budget & policy | 3 | I | **A** | I | — | — | — |
| 14 | AI: new AI system touching patients, money, or public content | 2 | **A** | R | C | C | — | — |
| 15 | AI: internal drafting/research use per AI policy | 3 | I | **A** | — | — | — | — |
| 16 | Marketing: campaigns within brand canon & budget | 3 | I | **A** | I | — | — | — |
| 17 | Media appearances — Founder's personal voice | 2 | **A** (never delegable) | — | I | C | — | — |
| 18 | Brand licensing / use of Founder name & likeness | 2 | **A** (never delegable) | — | I | C | I | — |
| 19 | Intellectual property: filings, transfers, licensing | 2 | **A** | R | I | C | — | I |
| 20 | Partnerships / joint ventures | 2 | **A** | R | C | C | — | — |
| 21 | Healthcare operations: clinical protocols, scope of services | Firewall | **A** (licensed authority only) | R (if licensed) | I | — | — | — |
| 22 | Compliance: filings, disclosures, regulator responses | Floor | **A** | R | I | — | — | — |
| 23 | Legal settlements | 2 | **A** (+counsel) | R | I | C | — | I |
| 24 | Foundation grants (per L08 thresholds) | 2/3 | A above threshold | Foundation lead **A** below | — | C | — | — |
| 25 | Trust actions 🔮 (distributions, amendments) | Instrument | C (while living, per instrument) | — | — | — | C | **A** |
| 26 | Succession activation | 1 | **A** (written delegation) | I | I | C | C | per instrument |

## 3. Standing rules

1. Every **A** on a Class 2 row requires the written decision memo + Five
   Gates (PEGS-000 Art. V) — the matrix never waives the memo.
2. **Never-delegable set:** rows 17–18 (Founder's voice and name) and every
   firewall row — no future CEO, council, or trustee inherits these except
   through PEGS-101 succession.
3. Thresholds ($ amounts) are set during Phase 4 instantiation in each
   entity's authority matrix; until set, ALL threshold rows escalate to FDR.
4. A body listed **C** must actually be consulted — skipping a C on a
   Class 2 decision invalidates the memo's process (dissent can't be heard
   if counsel wasn't asked).
5. On Stewardship Council activation (PEGS-101 §2), FDR's Class 1 letters
   transfer to the Council; Class 2 letters transfer per the succession
   instruments; this matrix is then amended within 90 days.

## Governance notes

This matrix is the enterprise ceiling. Entity matrices instantiate under it
(L02); conflicts resolve to this document, which resolves to PEGS-000.

## Implementation recommendations

1. Phase 4: populate thresholds and the CEO/ELT columns with real names —
   until then the matrix runs in "Founder mode" (all A's collapse to FDR).
2. Print §2 as the one-page insert in every executive onboarding packet.

## Future dependencies

Role charters (Phase 4) · SAC seating · trust instrument defining TR/LC
columns (Phase 6) · succession amendment per rule 5.

## Revision history

| Version | Date | Change | Author |
|---|---|---|---|
| 0.1.0 | 2026-07-19 | Initial draft (Phase 3.5) | Chief Enterprise Architect, at Founder direction |
