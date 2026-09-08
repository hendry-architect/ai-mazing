

# ── the doctor must not describe credentials it actually holds as absent ──


def test_canva_is_mcp_managed_only_while_pcip_holds_no_tokens():
    """`mcp` mode says which path assembly prefers, not whether the Connect
    path exists. Conflating them made the doctor report "credentials held by
    the MCP host, not PCIP" about tokens sitting in .env — and skip the live
    probe, so it stayed silent about credentials a sync was already using."""
    from pcip.config import PCIPConfig
    from pcip.connectors.catalog import CATALOG

    canva = next(d for d in CATALOG if d.name == "canva")

    no_tokens = PCIPConfig(canva_mode="mcp")
    assert canva.mcp_managed_when(no_tokens) is True

    with_tokens = PCIPConfig(canva_mode="mcp", canva_access_token="at")
    assert canva.mcp_managed_when(with_tokens) is False

    refresh_only = PCIPConfig(canva_mode="mcp", canva_refresh_token="rt")
    assert canva.mcp_managed_when(refresh_only) is False

    connect_mode = PCIPConfig(canva_mode="connect", canva_access_token="at")
    assert canva.mcp_managed_when(connect_mode) is False


def test_canva_configured_reads_either_token():
    from pcip.config import PCIPConfig

    assert PCIPConfig().canva_configured is False
    assert PCIPConfig(canva_access_token="at").canva_configured is True
    assert PCIPConfig(canva_refresh_token="rt").canva_configured is True


# ── the report a person reads ────────────────────────────────────────────


def _report(**connectors):
    return {"connectors": connectors, "actions": []}


def test_the_table_marks_usable_connectors(capsys):
    """`mcp_managed` is usable — the credentials are simply held elsewhere.
    Marking it as a problem would send the operator to fix nothing."""
    from pcip.cli import _doctor_table

    _doctor_table(_report(
        canva={"desired": True, "status": "ready", "detail": "live probe passed"},
        github={"desired": True, "status": "mcp_managed", "detail": "held by host"},
        openai={"desired": True, "status": "missing_credentials",
                "detail": "set: openai_api_key"},
    ))
    out = capsys.readouterr().out
    assert "OK  canva" in out
    assert "OK  github" in out
    assert "--  openai" in out
    assert "2 of 3 requested connectors usable." in out


def test_the_table_separates_what_was_asked_for(capsys):
    """A connector nobody requested is not a gap, and listing it among the
    gaps is how a clean report comes to look alarming."""
    from pcip.cli import _doctor_table

    _doctor_table(_report(
        wordpress={"desired": True, "status": "ready", "detail": ""},
        tiktok={"desired": False, "status": "disabled", "detail": "not requested"},
    ))
    out = capsys.readouterr().out
    assert out.index("REQUESTED") < out.index("wordpress")
    assert out.index("NOT REQUESTED") < out.index("tiktok")
    assert "1 of 1 requested connectors usable." in out


def test_the_table_lists_the_fixes(capsys):
    from pcip.cli import _doctor_table

    report = _report(openai={"desired": True, "status": "missing_credentials",
                             "detail": "set: openai_api_key"})
    report["actions"] = ["openai: set: openai_api_key — see SETUP.md Phase 4"]
    _doctor_table(report)
    assert "TO FIX:" in capsys.readouterr().out
