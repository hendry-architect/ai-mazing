---
id: pegs-meeting-kit
type: standard
library: L05-enterprise-planning
title: The PEGS Meeting Kit
version: 0.1.0
status: active
owner: founder
---

# Meeting Kit — the universal meeting artifact chain

Every meeting in the Enterprise — leadership, advisory council, family,
foundation, retreat — runs on this one kit. One meeting automatically
generates ten artifacts:

```
BEFORE   →  1. Agenda            (TEMPLATE-agenda.md)
            2. Board packet      (TEMPLATE-board-packet.md)
DURING   →  3. Minutes           (TEMPLATE-minutes.md)
            4. Decisions          ┐
            5. Action items       │ structured tables inside the minutes —
            6. Assigned owners    │ machine-parseable per the
            7. Due dates          ┘ Integration Standard
AFTER    →  8. Follow-up report  (TEMPLATE-follow-up-report.md, ≤48h)
            9. Quarterly archive (records/YYYY/QN/)
           10. Annual archive    (records/YYYY/annual-index.md)
```

**How the chain runs:** [SOP-meeting-lifecycle.md](SOP-meeting-lifecycle.md)
— including the archive rules and the automation hooks that let n8n/Zapier/
Make turn the action-item table into tasks, reminders, and calendar events
(see `13-Automation/INTEGRATION-STANDARD.md`).

**Standing rule:** a meeting without an agenda does not convene; a meeting
without minutes did not happen (PEGS-000 Art. VI §1). Class 2 decisions
additionally require a decision memo (`12-Templates/DECISION-MEMO-TEMPLATE.md`)
— minutes alone are not sufficient for one-way doors.

**Parameterization:** each recurring meeting type (weekly leadership,
monthly review, quarterly council, family meeting, retreat) defines only its
attendees, cadence, and standing agenda sections; everything else is
inherited from this kit unchanged.
