"""The 3x/week rotation: pure logic, no network, no bash.

scripts/pcip-scheduled-post.sh runs unattended from a launchd job, so the
one thing this module owns -- which brief runs next -- has to be correct
without anyone watching, and has to keep rotating even when a run fails.
"""

import json

import pytest

from pcip.schedule import (
    ScheduleError,
    is_clinical,
    load_manifest,
    next_entry,
    resolve_brief_path,
)


def manifest(tmp_path, *entries):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(list(entries)))
    return path


def test_rotation_advances_and_wraps(tmp_path):
    m = manifest(tmp_path, {"pipeline": "a", "brief": "a.json"},
                 {"pipeline": "b", "brief": "b.json"})
    state = tmp_path / "state.json"

    first = next_entry(m, state)
    second = next_entry(m, state)
    third = next_entry(m, state)

    assert [first["pipeline"], second["pipeline"], third["pipeline"]] == [
        "a", "b", "a",
    ]


def test_a_missing_state_file_starts_at_the_first_entry(tmp_path):
    m = manifest(tmp_path, {"pipeline": "solo", "brief": "s.json"})
    assert next_entry(m, tmp_path / "nope.json")["pipeline"] == "solo"


def test_peek_does_not_advance(tmp_path):
    m = manifest(tmp_path, {"pipeline": "a", "brief": "a.json"},
                 {"pipeline": "b", "brief": "b.json"})
    state = tmp_path / "state.json"
    assert next_entry(m, state, advance=False)["pipeline"] == "a"
    assert next_entry(m, state, advance=False)["pipeline"] == "a"
    assert next_entry(m, state)["pipeline"] == "a"
    assert next_entry(m, state)["pipeline"] == "b"


def test_rotation_keeps_moving_past_a_shrunk_manifest(tmp_path):
    """A manifest edited down to fewer entries must not crash the next run
    just because the saved index no longer exists."""
    m = manifest(tmp_path, {"pipeline": "only", "brief": "o.json"})
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"next_index": 40}))
    assert next_entry(m, state)["pipeline"] == "only"


def test_a_missing_manifest_says_what_to_do():
    with pytest.raises(ScheduleError, match="examples/schedule/manifest.json"):
        load_manifest("/nonexistent/manifest.json")


def test_an_empty_manifest_is_rejected(tmp_path):
    with pytest.raises(ScheduleError, match="non-empty"):
        load_manifest(manifest(tmp_path))


def test_an_entry_missing_a_key_is_rejected(tmp_path):
    with pytest.raises(ScheduleError, match=r"\[0\]"):
        load_manifest(manifest(tmp_path, {"pipeline": "a"}))


def test_brief_paths_are_relative_to_the_manifest_not_the_caller(tmp_path):
    (tmp_path / "briefs").mkdir()
    entry = {"pipeline": "a", "brief": "briefs/x.json"}
    resolved = resolve_brief_path(entry, tmp_path / "manifest.json")
    assert resolved == (tmp_path / "briefs" / "x.json").resolve()


def test_an_absolute_brief_path_is_left_alone(tmp_path):
    abs_path = tmp_path / "elsewhere.json"
    resolved = resolve_brief_path({"brief": str(abs_path)}, tmp_path / "m.json")
    assert resolved == abs_path


def test_patient_education_is_clinical():
    assert is_clinical("patient_education") is True


def test_marketing_asset_is_not_clinical():
    """The whole point of routing logistics content through this pipeline:
    its only gate, brand_review, is safe to auto-approve."""
    assert is_clinical("marketing_asset") is False


# ── the real manifest this project ships ────────────────────────────────


def test_the_shipped_manifest_loads_and_every_brief_exists():
    from pathlib import Path

    manifest_path = Path("examples/schedule/manifest.json")
    entries = load_manifest(manifest_path)
    assert len(entries) >= 3
    for entry in entries:
        assert resolve_brief_path(entry, manifest_path).is_file(), entry["brief"]


def test_the_shipped_manifest_mixes_clinical_and_non_clinical_topics():
    """All-clinical would mean nothing in the rotation can ever be
    hands-off; all-logistics would mean nothing this practice actually
    treats ever gets talked about."""
    from pathlib import Path

    entries = load_manifest(Path("examples/schedule/manifest.json"))
    clinical = [is_clinical(e["pipeline"]) for e in entries]
    assert any(clinical) and not all(clinical)


def test_every_shipped_brief_parses_as_a_brief():
    from pathlib import Path

    from pcip.models import Brief

    manifest_path = Path("examples/schedule/manifest.json")
    for entry in load_manifest(manifest_path):
        Brief.from_json_file(str(resolve_brief_path(entry, manifest_path)))
