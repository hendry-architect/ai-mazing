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


# ── duplicate keys ───────────────────────────────────────────────────────────


def test_last_assignment_wins(tmp_path, monkeypatch):
    """The bootstrap seeds every key empty; a tool appends the real value after.

    Taking the first occurrence made the empty placeholder shadow a credential
    that had just been saved successfully, and the platform reported it as not
    set. `source` takes the last assignment; so does this.
    """
    monkeypatch.delenv("PCIP_TEST_DUP", raising=False)
    load_dotenv(write(tmp_path, "PCIP_TEST_DUP=\nPCIP_TEST_DUP=real-value\n"))
    assert os.environ["PCIP_TEST_DUP"] == "real-value"


def test_last_assignment_wins_even_with_export_and_spacing(tmp_path, monkeypatch):
    monkeypatch.delenv("PCIP_TEST_DUP2", raising=False)
    load_dotenv(write(tmp_path, "PCIP_TEST_DUP2=first\nexport PCIP_TEST_DUP2 = second\n"))
    assert os.environ["PCIP_TEST_DUP2"] == "second"


def test_a_credential_with_spaces_survives_a_duplicate(tmp_path, monkeypatch):
    """WordPress Application Passwords contain spaces — the real failing case."""
    monkeypatch.delenv("PCIP_TEST_APP_PW", raising=False)
    load_dotenv(write(
        tmp_path,
        "PCIP_TEST_APP_PW=\nPCIP_TEST_APP_PW=abcd efgh ijkl mnop qrst uvwx\n",
    ))
    assert os.environ["PCIP_TEST_APP_PW"] == "abcd efgh ijkl mnop qrst uvwx"


def test_a_string_path_is_accepted(tmp_path, monkeypatch):
    """It crashed on a str, which is what a caller naturally passes."""
    monkeypatch.delenv("PCIP_TEST_STRPATH", raising=False)
    load_dotenv(str(write(tmp_path, "PCIP_TEST_STRPATH=ok\n")))
    assert os.environ["PCIP_TEST_STRPATH"] == "ok"


def test_the_real_config_sees_the_later_value(tmp_path, monkeypatch):
    for k in ("WORDPRESS_USER", "WORDPRESS_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    write(tmp_path, (
        "WORDPRESS_USER=\nWORDPRESS_APP_PASSWORD=\n"
        "WORDPRESS_USER=editor\nWORDPRESS_APP_PASSWORD=abcd efgh ijkl\n"
    ))
    from pcip.config import load_config

    cfg = load_config()
    assert cfg.wordpress_user == "editor"
    assert cfg.wordpress_app_password == "abcd efgh ijkl"
    assert cfg.wordpress_configured is True


def test_an_empty_exported_variable_does_not_shadow_the_file(tmp_path, monkeypatch):
    """`source`-ing a .env full of blank placeholders poisons the shell.

    Those empty exports then shadow every credential saved afterwards, for the
    life of that shell — so a key saved successfully keeps reading back as
    unset. An empty exported value carries no information; treat it as absent.
    """
    monkeypatch.setenv("PCIP_TEST_EMPTY_SHADOW", "")
    load_dotenv(write(tmp_path, "PCIP_TEST_EMPTY_SHADOW=real\n"))
    assert os.environ["PCIP_TEST_EMPTY_SHADOW"] == "real"


def test_a_real_exported_variable_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("PCIP_TEST_REAL_WINS", "from-shell")
    load_dotenv(write(tmp_path, "PCIP_TEST_REAL_WINS=from-file\n"))
    assert os.environ["PCIP_TEST_REAL_WINS"] == "from-shell"


def test_the_full_failure_the_operator_actually_hit(tmp_path, monkeypatch):
    """Blank placeholders exported, real values appended: must resolve."""
    monkeypatch.setenv("WORDPRESS_USER", "")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "")
    monkeypatch.chdir(tmp_path)
    write(tmp_path, (
        "WORDPRESS_USER=\nWORDPRESS_APP_PASSWORD=\n"
        "WORDPRESS_USER=editor\nWORDPRESS_APP_PASSWORD=abcd efgh ijkl\n"
    ))
    from pcip.config import load_config

    cfg = load_config()
    assert cfg.wordpress_user == "editor"
    assert cfg.wordpress_app_password == "abcd efgh ijkl"
    assert cfg.wordpress_configured is True


def test_env_shadowing_reports_a_disagreement_without_values(monkeypatch, tmp_path):
    """A non-empty export beats the file by design — but say so out loud.

    Silently reading one value while the file plainly shows another makes every
    subsequent report confusing rather than wrong, and cost several rounds of
    debugging a setting that had been saved correctly.
    """
    from pcip.config import env_shadowing

    monkeypatch.setenv("WORDPRESS_URL", "https://passqual.com")
    env = write(tmp_path, "WORDPRESS_URL=https://wp.passqual.com\n")
    report = env_shadowing(env)
    assert report == {"WORDPRESS_URL": (20, 23)}
    assert "passqual" not in str(report)          # lengths only, never values


def test_agreement_is_not_reported_as_shadowing(monkeypatch, tmp_path):
    from pcip.config import env_shadowing

    monkeypatch.setenv("WORDPRESS_URL", "https://wp.passqual.com")
    assert env_shadowing(write(tmp_path, "WORDPRESS_URL=https://wp.passqual.com\n")) == {}


def test_an_empty_export_is_not_shadowing(monkeypatch, tmp_path):
    """Empty exports are handled by load_dotenv; they are not a disagreement."""
    from pcip.config import env_shadowing

    monkeypatch.setenv("WORDPRESS_URL", "")
    assert env_shadowing(write(tmp_path, "WORDPRESS_URL=https://wp.passqual.com\n")) == {}
