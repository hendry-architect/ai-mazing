---
id: pegs-l12-bcp
type: template
library: L12-enterprise-risk-compliance
title: Business Continuity Plan
version: 0.1.0
status: template
owner: founder
---

# Business Continuity Plan — <Entity>

> The keep-operating plan. Written calm, executed rattled — so it must be
> executable by whoever is present, not by its author.

## 1. What must never stop (ranked)

| # | Critical function | Max tolerable downtime | Minimum viable mode |
|---|---|---|---|
| 1 | <e.g., patient care continuity + emergency referrals> | hours | <paper workflow + phone triage> |
| 2 | <payroll> | days | <manual run via bank portal> |
| 3 | <scheduling/comms> | hours | <phone + SMS fallback> |

## 2. Scenario cards (one page each, this format)

**Scenario:** <facility loss / EHR-IT outage / key-person absence /
extended power or network loss / vendor failure>
- First hour: who declares, who's called (names + numbers), safety steps
- First day: minimum viable mode steps; patient/customer communication
- First week: recovery path; return-to-normal criteria
- Owner of this card: <name>

## 3. Dependencies inventory

| Dependency | Vendor/system | Failure impact | Workaround | Data recoverable from |
|---|---|---|---|---|
| EHR | ChARM | scheduling+records | paper day-sheet kit | vendor export (tested?) |
| Phones/internet | | | cellular hotspot kit | |
| Payroll | | | | |

## 4. People & authority

Successor/deputy per role (succession plans) · Authority Matrix continuity:
who signs if A and B are both unreachable · out-of-band contact list
(stored printed AND digital, updated quarterly ⚙).

## 5. Testing

Annual tabletop (one scenario card, 90 min, honest) · findings become
actions with owners · the plan is re-signed after every test — an untested
BCP is fiction with a header.
