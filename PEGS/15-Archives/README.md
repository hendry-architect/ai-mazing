# 15 — Archives

The memory-of-record layer: superseded documents come here when replaced —
the Enterprise never erases its record (PEGS-000 Art. VIII §3.4).

**Convention**

- On supersession, the old document moves here as
  `<original-name>-vX.Y.Z-SUPERSEDED-YYYY-MM-DD.md`, with its control block
  updated to point at its successor.
- Git history remains the authoritative record; this folder is the readable
  index of it for people who will never run `git log`.

**Rules of this folder**

- Nothing is ever deleted from Archives.
- Archived documents carry no authority — the registry in `PEGS/README.md`
  says what is in force.

**Status:** Active — empty until the first supersession, which is how it
should be.
**Custodian:** follows the custodian of the superseding document.
