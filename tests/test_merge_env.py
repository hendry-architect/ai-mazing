"""Merging one .env into another.

Every rule here exists because its absence cost real debugging time in this
project: an empty assignment that outranked a real value, a first-occurrence
loader that read back a key which had just been written, and a stale copy
quietly overwriting a newer credential.
"""

import re
import shutil
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pcip-merge-env.sh"


def merge(tmp_path, target_text, source_text):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / SCRIPT.name)
    (repo / ".env").write_text(target_text)
    source = tmp_path / "other.env"
    source.write_text(source_text)
    result = subprocess.run(
        ["bash", str(repo / "scripts" / SCRIPT.name), str(source)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return (repo / ".env").read_text(), result.stdout


def values(text):
    return dict(
        line.split("=", 1) for line in text.splitlines()
        if "=" in line and not line.startswith("#")
    )


def test_a_missing_key_is_copied(tmp_path):
    env, out = merge(tmp_path, "A=1\n", "B=2\n")
    assert values(env) == {"A": "1", "B": "2"}
    assert "B" in out


def test_an_existing_value_is_never_overwritten(tmp_path):
    """The local file is the newer one — a credential just rotated here must
    not be replaced by a stale copy."""
    env, out = merge(tmp_path, "A=current\n", "A=stale\n")
    assert values(env)["A"] == "current"
    assert "stale" not in env
    assert re.search(r"already set, left alone:\s+A", out)


def test_an_empty_source_value_is_not_copied(tmp_path):
    """An empty assignment outranks every other credential source and fails
    with an error that looks nothing like 'you left this blank'."""
    env, out = merge(tmp_path, "A=1\n", "B=\n")
    assert "B" not in values(env)
    assert "empty in source, skipped" in out


def test_an_empty_local_value_is_filled_in_place(tmp_path):
    """Appending a second line for a key that already has an empty one leaves
    two assignments in the file, and which wins depends on the loader."""
    env, _ = merge(tmp_path, "A=\nZ=9\n", "A=filled\n")
    assert env.splitlines() == ["A=filled", "Z=9"]
    assert env.count("A=") == 1


def test_a_value_containing_spaces_survives(tmp_path):
    """WordPress Application Passwords are four space-separated groups."""
    env, _ = merge(tmp_path, "", "WORDPRESS_APP_PASSWORD=abcd efgh ijkl mnop\n")
    assert values(env)["WORDPRESS_APP_PASSWORD"] == "abcd efgh ijkl mnop"


def test_comments_and_layout_are_preserved(tmp_path):
    env, _ = merge(tmp_path, "# PCIP\nA=1\n\n# social\n", "B=2\n")
    assert env.startswith("# PCIP\nA=1\n\n# social\n")


def test_quotes_are_stripped_from_the_source(tmp_path):
    env, _ = merge(tmp_path, "", 'A="quoted"\n')
    assert values(env)["A"] == "quoted"


def test_a_backup_is_written_before_changing_anything(tmp_path):
    merge(tmp_path, "A=1\n", "B=2\n")
    backups = list((tmp_path / "repo").glob(".env.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "A=1\n"


def test_a_missing_source_is_refused(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / SCRIPT.name)
    result = subprocess.run(
        ["bash", str(repo / "scripts" / SCRIPT.name), str(tmp_path / "nope.env")],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "no file at" in result.stdout
