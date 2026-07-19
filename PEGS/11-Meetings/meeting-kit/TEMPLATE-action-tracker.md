---
id: pegs-mk-action-tracker
type: template
library: L05-enterprise-planning
title: Rolling Action Tracker
version: 0.1.0
status: template
owner: founder
---

# Action Tracker — <scope: enterprise / company / council> — <YYYY-QN>

> One rolling tracker per meeting series, updated from each follow-up
> report. This table is the feed for task automations (n8n → Todoist /
> Reminders / Notion — see INTEGRATION-STANDARD).

| ID | Action | Owner | Due | Status | Source meeting | Closed on |
|---|---|---|---|---|---|---|
| A-… | | | | open / done / blocked / dropped | YYYY-MM-DD | |

## Aging rules

- Overdue >7 days → automatically appears in the next agenda §1.
- Blocked >14 days → escalates to the chair (Class 2 triggers escalate
  immediately per the role's charter).
- Dropped requires the chair's initials in the row — actions don't
  silently vanish.
