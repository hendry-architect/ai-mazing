---
id: pegs-mk-sop-lifecycle
type: sop
library: L05-enterprise-planning
title: Meeting Lifecycle SOP
version: 0.1.0
status: active
owner: founder
---

# SOP — Meeting Lifecycle (every meeting, every time)

| Field | Value |
|---|---|
| Owner | Meeting secretary (chair if none named) |
| Trigger | A recurring meeting date, or any called meeting |
| Automation status | Manual → target: automated steps marked ⚙ |

## Procedure

1. **T-7d ⚙** Create agenda from `TEMPLATE-agenda.md`; auto-pull open items
   from the action tracker into §1.
2. **T-48h ⚙** Assemble packet from `TEMPLATE-board-packet.md`; attach
   decision memos for every Class 2 item; send to attendees. No packet by
   T-48h → the decision items slip to the next meeting (discussion may
   proceed).
3. **T-0** Chair runs the agenda; secretary captures minutes in
   `TEMPLATE-minutes.md`, filling the DECISIONS and ACTION ITEMS tables live.
4. **T+24h** Minutes filed to `../records/<YYYY>/Q<N>/YYYY-MM-DD-<type>.md`
   and committed (merge = the record exists).
5. **T+48h ⚙** Follow-up report generated from the minutes tables
   (`TEMPLATE-follow-up-report.md`), sent to attendees; action tracker
   updated; tasks/reminders/calendar entries created per
   INTEGRATION-STANDARD.
6. **Quarterly ⚙** `records/<YYYY>/Q<N>/` closes with a one-page quarter
   index: meetings held, decisions made, actions closed/open.
7. **Annually ⚙** `records/<YYYY>/annual-index.md` compiles the four
   quarter indexes — this is the governance year in one document, and the
   input to the annual constitutional review (PEGS-000 Art. VI §7).

## Quality bar

Minutes readable by an absent executive without oral explanation; every
action row has owner + ISO due date; every Class 2 decision links a memo.

## Escalation

Missed follow-up (T+48h) twice in a quarter → chair reassigns the secretary
role. Any firewall-touching decision recorded without its memo → escalate to
the Founder immediately.
