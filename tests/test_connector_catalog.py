

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
