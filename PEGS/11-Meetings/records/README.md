# Meeting Records — filing structure

The written memory of the operating cadence. Everything the Meeting Kit
produces files here (except Trust-sensitive records → `06-Trust/family-records/`).

```
records/
  DECISION-LOG-2026.md          ← live enterprise decision log (D-IDs)
  ACTION-TRACKER-enterprise.md  ← live rolling tracker (A-IDs)
  2026/
    Q3/  YYYY-MM-DD-<meeting-type>.md · quarter index at close
    Q4/  … · annual-index-2026.md at year close
  2027/
    Q1/ … Q4/ · constitutional-review.md (July)
```

**Rules:** minutes filed ≤24h (Kit SOP) · quarter index closes with the
quarterly report · the annual index is the constitutional review's
evidence base · nothing here is ever deleted — supersession goes through
`15-Archives`.

## Record Identifier Convention (Chairman-directed, effective 2026-07-20)

Every record carries a unique, human-readable ID. By Year Five,
thousands of records remain easy to reference.

| Record type | Format | Example / first issued |
|---|---|---|
| Initiative / Mission | `M-NNN` | **M-001** — Ascendencia Summit 2026 |
| Decision | `D-YYYY-NNN` | **D-2026-001** — Approval of Mission-001 |
| ELT meeting | `ELT-YYYY-NNN` | ELT-2026-001 (first weekly, Aug 3) |
| Advisory Council meeting | `SAC-YYYY-NNN` | SAC-2026-001 (at seating) |
| Summit | `SUMMIT-YYYY-NNN` | SUMMIT-2026-001 (Dec 27–Jan 2) |
| Monthly Executive Review | `MER-YYYY-NNN` | MER-2026-001 (Sep 7) |
| Quarterly retreat | `QR-YYYY-QN` | QR-2026-Q3 |
| Annual Declaration | `AD-YYYY` | AD-2027 (signed Jan 1, 2027) |
| Chairman's Letter (to the Enterprise) | `CL-YYYY` | CL-2027 |
| Lessons-learned entry | `LL-YYYY-NNN` | LL-2026-001 (PEGS-950) |
| Action item | `A-YYYY-NNN` (new) | — |

**Grandfathering:** IDs already issued in the earlier date-stamp format
(D-20260719-1…D-20260720-4; A-20260720-1…-15) are permanent and never
renumbered — the ID-immutability rule (Knowledge System §2) outranks
tidiness. The new convention applies to every record from D-2026-001
forward. Meeting IDs are assigned by the secretary function at filing;
filenames keep the `YYYY-MM-DD-<type>` date convention with the ID in
the record's control block.
