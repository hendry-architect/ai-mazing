---
id: pegs-l04-corp-sec-office
type: standard
library: L04-corporate-secretary
title: Corporate Secretary Office
version: 0.1.0
status: active
owner: founder
---

# Corporate Secretary Office

The record-keeping arm of governance: the function (a role, not necessarily
a person yet) that ensures every governance act exists on paper, on time, in
the right place. Until delegated via `03-Executive-Leadership`, the Founder
holds the function; it is designed for handoff on day one.

**Library contents**

| Artifact | Use |
|---|---|
| [TEMPLATE-resolution.md](TEMPLATE-resolution.md) | Formal acts of an entity (adopt, authorize, appoint) |
| [TEMPLATE-written-consent.md](TEMPLATE-written-consent.md) | Acting without convening — unanimous written consent |
| [TEMPLATE-meeting-notice.md](TEMPLATE-meeting-notice.md) | Formal notice for meetings that require one |
| [TEMPLATE-governance-calendar.md](TEMPLATE-governance-calendar.md) | The annual governance + compliance clock |

Minutes, decision logs, and action registers are the Meeting Kit's job
(`11-Meetings/meeting-kit/`) — the Secretary runs that SOP for governance
meetings and files records to `11-Meetings/records/`.

**Duties of the function**

1. Run the governance calendar; nothing statutory or ratified-recurring is
   ever late.
2. Produce and file resolutions, consents, notices, minutes within their
   SOP deadlines.
3. Maintain the action register (Meeting Kit tracker) for governance bodies.
4. Sync the compliance calendar with `10-Policies/risk-compliance/`
   (regulatory dates live there; the Secretary schedules them here) ⚙.

**Automation hooks:** calendar template → ICS feed (Google/Apple/Outlook);
resolutions and consents are frontmattered records → indexed automatically
into the decision archive (`14-Knowledge-Base`).
