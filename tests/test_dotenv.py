"""Reading .env directly.

Every credential lives in a .env beside the repo. Requiring the operator to
`set -a; source .env` before each command turns a forgotten step into a
"missing credentials" report that looks like a real diagnosis, so the platform
reads the file itself — without letting a file silently override a value the
caller exported on purpose.
"""

import os

import pytest

from pcip.config import load_dotenv


def write(tmp_path, body):
    p = tmp_path / ".env"
    p.write_text(body, encoding="utf-8")
    return p


def test_reads_plain_assignments(tmp_path, monkeypatch):
    monkeypatch.delenv("PCIP_TEST_A", raising=False)
    load_dotenv(write(tmp_path, "PCIP_TEST_A=hello\n"))
    assert os.environ["PCIP_TEST_A"] == "hello"


def test_handles_the_shapes_a_hand_edited_file_actually_has(tmp_path, monkeypatch):
    for k in ("Q1", "Q2", "EXP", "CMT", "SPACED"):
        monkeypatch.delenv(f"PCIP_TEST_{k}", raising=False)
    load_dotenv(write(tmp_path, """
# a comment line
PCIP_TEST_Q1="double quoted"
PCIP_TEST_Q2='single quoted'
export PCIP_TEST_EXP=exported
PCIP_TEST_CMT=value # trailing note
PCIP_TEST_SPACED = padded

not a valid line
=novalue
"""))
    assert os.environ["PCIP_TEST_Q1"] == "double quoted"
    assert os.environ["PCIP_TEST_Q2"] == "single quoted"
    assert os.environ["PCIP_TEST_EXP"] == "exported"
    assert os.environ["PCIP_TEST_CMT"] == "value"
    assert os.environ["PCIP_TEST_SPACED"] == "padded"


def test_a_hash_inside_a_quoted_secret_is_kept(tmp_path, monkeypatch):
    """App passwords and API keys legitimately contain '#'."""
    monkeypatch.delenv("PCIP_TEST_PW", raising=False)
    load_dotenv(write(tmp_path, 'PCIP_TEST_PW="abc #def ghi"\n'))
    assert os.environ["PCIP_TEST_PW"] == "abc #def ghi"


def test_exported_value_wins_over_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PCIP_TEST_W", "from-shell")
    load_dotenv(write(tmp_path, "PCIP_TEST_W=from-file\n"))
    assert os.environ["PCIP_TEST_W"] == "from-shell"


def test_override_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("PCIP_TEST_O", "from-shell")
    load_dotenv(write(tmp_path, "PCIP_TEST_O=from-file\n"), override=True)
    assert os.environ["PCIP_TEST_O"] == "from-file"


def test_returns_keys_but_never_values(tmp_path):
    keys = load_dotenv(write(tmp_path, "PCIP_TEST_SECRET=super-secret\n"))
    assert "PCIP_TEST_SECRET" in keys
    assert "super-secret" not in str(keys)


def test_missing_file_is_not_an_error(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == {}


def test_load_config_picks_up_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "ANTHROPIC_API_KEY=sk-test-123\n")
    from pcip.config import load_config

    assert load_config().anthropic_api_key == "sk-test-123"
