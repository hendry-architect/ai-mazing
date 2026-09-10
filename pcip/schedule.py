"""The 3x/week rotation: which brief runs next, and on which pipeline.

Scheduling is deliberately not "run the same brief three times a week" — a
manifest pairs each brief with the pipeline it should run on. Until
2026-09-10 that choice was also a safety decision (`patient_education` was
the only pipeline carrying `medical_review`, so a clinical topic stopped for
a clinician there and nowhere else); Dr. Hendry Pascual, founder/CEO/medical
director of PassQual Health, removed that gate on that date, so every
pipeline now finishes unattended with only `brand_review` auto-approved —
see pcip/pipelines/library.py for the change itself. The pipeline choice
below still matters for content shape (patient_education carries the
plain-language reading-level check and a healthcare-photo media preset that
marketing_asset does not), just no longer for whether a human is involved.

This module is the pure part: given a manifest and a state file, which entry
comes next. `scripts/pcip-scheduled-post.sh` is the part that actually runs
it and is unattended, so this stays a file (not a database) that a person can
read and hand-edit without any tooling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


class ScheduleError(Exception):
    pass


def load_manifest(path: Path | str) -> List[Dict[str, str]]:
    path = Path(path)
    if not path.is_file():
        raise ScheduleError(
            f"no schedule manifest at {path}. Create one — see "
            "examples/schedule/manifest.json for the shape."
        )
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ScheduleError(f"{path} must be a non-empty JSON array")
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or "pipeline" not in e or "brief" not in e:
            raise ScheduleError(
                f"{path}[{i}] must have \"pipeline\" and \"brief\" keys"
            )
    return entries


def _read_state(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("next_index", 0))
    except (ValueError, json.JSONDecodeError):
        return 0


def _write_state(path: Path, index: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"next_index": index}, indent=2), encoding="utf-8")


def next_entry(
    manifest_path: Path | str, state_path: Path | str, *, advance: bool = True
) -> Dict[str, Any]:
    """The manifest entry due to run next.

    Wraps around the end of the manifest rather than stopping, so a schedule
    left running for months keeps rotating instead of erroring out. Advances
    the state file unconditionally when ``advance`` is true — including when
    the caller later reports the run failed — because an unattended job that
    stops rotating on the first bad brief needs a person to notice and fix it
    before it recovers, and by then the schedule has silently gone quiet.
    Failures belong in the run log, not in a stuck index.
    """
    manifest_path, state_path = Path(manifest_path), Path(state_path)
    entries = load_manifest(manifest_path)
    index = _read_state(state_path) % len(entries)
    entry = dict(entries[index])
    entry["index"] = index
    entry["manifest_size"] = len(entries)
    if advance:
        _write_state(state_path, (index + 1) % len(entries))
    return entry


def resolve_brief_path(entry: Dict[str, Any], manifest_path: Path | str) -> Path:
    """A brief path in the manifest is relative to the manifest's own folder,
    so the manifest and its briefs can be moved together."""
    brief = Path(entry["brief"])
    if brief.is_absolute():
        return brief
    return Path(manifest_path).resolve().parent / brief


# is_clinical(), which answered "does this pipeline carry a gate that can
# never be auto-approved", was removed 2026-09-10 along with the last such
# gate (patient_education's medical_review) — no pipeline can answer True
# to that question any more, and a function that can only ever return one
# value is worse than no function. If a future pipeline adds a gate to
# pcip.pipelines.base.NEVER_AUTO_APPROVE, reintroduce a check like the one
# this replaced rather than resurrecting dead code speculatively.
