---
id: pegs-l12-sop-incident-response
type: sop
library: L12-enterprise-risk-compliance
title: Incident Response SOP
version: 0.1.0
status: active
owner: founder
---

# SOP — Incident Response

| Field | Value |
|---|---|
| Owner | Founder (until a compliance role is chartered) |
| Trigger | Any suspected: PHI/data breach, cyber intrusion, patient-safety event, legal threat, brand crisis, financial fraud |
| First principle | Surface early is rewarded; hiding is the only firing-level offense (PEGS-000 Art. IV §7) |

## Severity

| Level | Definition | Who leads |
|---|---|---|
| SEV-1 | Patient safety, confirmed PHI breach, active intrusion, legal service | Founder + counsel, immediately, any hour |
| SEV-2 | Suspected breach, fraud indicators, brand crisis brewing | Founder within 4h |
| SEV-3 | Contained near-miss, policy violation without exposure | Entity lead; weekly meeting §6 |

## First hour (any SEV-1/2)

1. **Stop the bleeding** — isolate systems / secure the scene / preserve
   evidence (no deletions, no "cleanup").
2. **Notify** — Founder (always), counsel (SEV-1), cyber carrier hotline
   (I-03) before touching affected systems further.
3. **Log** — start the incident log: timestamped facts only, no
   speculation (this log may be discoverable — facts, not adjectives).

## First day

Scope assessment (what data/people/systems) · containment confirmed ·
communication plan drafted with counsel (who must be told, when, by law —
HIPAA breach clock starts at discovery) · BCP scenario card activated if
operations are impaired.

## First week

Root cause (5-whys, blameless toward reporters) · regulatory notifications
per counsel and the compliance matrix · affected-party communication
(honest, dignified, both languages where applicable).

## Close-out

Incident report filed (`incidents/YYYY-MM-DD-<slug>.md`) · lessons →
ratified learnings (`14-Knowledge-Base`) · register/matrix/policy updates
PR'd · SEV-1 close-out reviewed at the next monthly review.
