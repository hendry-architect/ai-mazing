"""Connector Management Framework tests — the capability matrix must be
honest, manifest-driven, and useful to the planner without any network."""

import pytest

from pcip.config import PCIPConfig
from pcip.connectors.framework import (
    CapabilitySpec,
    ConnectorAuthError,
    ConnectorDescriptor,
    ConnectorManager,
    EntitlementError,
    Manifest,
    load_manifest,
)


def make_catalog(probe=None):
    return [
        ConnectorDescriptor(
            name="canva",
            auth_methods=("oauth",),
            env_any=(("canva_access_token",),
                     ("canva_refresh_token", "canva_client_id")),
            probe=probe,
            capabilities=(
                CapabilitySpec("create_design"),
                CapabilitySpec("duplicate_template", entitlement="canva_enterprise"),
                CapabilitySpec("export_png"),
                CapabilitySpec("search_premium_assets", supported=False,
                               note="not exposed by the Connect API"),
            ),
        ),
        ConnectorDescriptor(
            name="github", auth_methods=("oauth",), mcp_managed=True,
            capabilities=(CapabilitySpec("repo_write"),),
        ),
        ConnectorDescriptor(
            name="openai", auth_methods=("api_key",),
            env_vars=("openai_api_key",),
            capabilities=(CapabilitySpec("generate_image"),),
        ),
    ]


def manifest(*names):
    return Manifest(connectors={n: {} for n in names}, path="test", exists=True)


def manager(cfg=None, probe=None, mani=None):
    return ConnectorManager(
        cfg or PCIPConfig(),
        catalog=make_catalog(probe),
        manifest=mani if mani is not None else manifest("canva", "github", "openai"),
    )


def test_missing_credentials_reported_with_fix():
    report = manager().connector_report(manager().catalog["canva"], live=False)
    assert report["status"] == "missing_credentials"
    assert "canva_access_token" in report["detail"]
    assert not report["capabilities"]["create_design"]["usable"]


def test_configured_when_credentials_present():
    cfg = PCIPConfig(canva_access_token="tok")
    m = manager(cfg)
    answer = m.can("canva.export_png")
    assert answer["usable"]
    assert answer["status"] == "configured"


def test_unsupported_capability_is_honest_even_when_connected():
    cfg = PCIPConfig(canva_access_token="tok")
    answer = manager(cfg).can("canva.search_premium_assets")
    assert not answer["usable"]
    assert answer["status"] == "unsupported"
    assert "Connect API" in answer["note"]


def test_mcp_managed_connector_is_usable_without_pcip_credentials():
    answer = manager().can("github.repo_write")
    assert answer["usable"]
    assert answer["status"] == "mcp_managed"


def test_manifest_disables_undeclared_connectors():
    m = manager(mani=manifest("canva"))          # openai not declared
    assert m.can("openai.generate_image")["status"] == "disabled"
    # No manifest file at all → report-only mode, nothing disabled.
    m = manager(mani=Manifest())
    assert m.can("openai.generate_image")["status"] == "missing_credentials"


def test_live_probe_entitlement_gap():
    def probe(cfg):
        raise EntitlementError(["duplicate_template"], "needs Enterprise")

    cfg = PCIPConfig(canva_access_token="tok")
    m = manager(cfg, probe=probe)
    report = m.connector_report(m.catalog["canva"], live=True)
    caps = report["capabilities"]
    assert caps["duplicate_template"]["status"] == "not_entitled"
    assert caps["create_design"]["status"] == "ready"   # rest of connector fine
    assert caps["export_png"]["usable"]


def test_live_probe_auth_failure_fails_all_capabilities():
    def probe(cfg):
        raise ConnectorAuthError("token revoked")

    cfg = PCIPConfig(canva_access_token="tok")
    m = manager(cfg, probe=probe)
    report = m.connector_report(m.catalog["canva"], live=True)
    assert report["status"] == "auth_failed"
    assert not report["capabilities"]["create_design"]["usable"]


def test_probe_network_flake_keeps_configured():
    def probe(cfg):
        raise OSError("connection reset")

    cfg = PCIPConfig(canva_access_token="tok")
    m = manager(cfg, probe=probe)
    report = m.connector_report(m.catalog["canva"], live=True)
    assert report["status"] == "configured"      # flake ≠ bad credentials


def test_doctor_actions_and_summary():
    m = manager()
    report = m.doctor()
    assert any("canva" in a for a in report["actions"])
    assert report["summary"]["missing_credentials"] == 2   # canva + openai
    assert report["summary"]["mcp_managed"] == 1


def test_unknown_capability_and_connector():
    m = manager()
    assert m.can("canva.levitate")["status"] == "unknown_capability"
    assert m.can("figma.export")["status"] == "unknown_connector"


def test_manifest_yaml_loading(tmp_path):
    yaml_file = tmp_path / "bootstrap.yaml"
    yaml_file.write_text(
        "connectors:\n"
        "  canva:\n    oauth: true\n"
        "  wordpress:\n    app_password: true\n"
        "  github:\n"                            # bare entry also valid
    )
    mani = load_manifest(str(yaml_file))
    assert mani.exists
    assert mani.desired("canva") and mani.desired("github")
    assert not mani.desired("tiktok")
    assert mani.auth_declared("wordpress") == "app_password"


def test_real_catalog_covers_config_and_loads():
    """The real catalog must instantiate cleanly and reference only real
    PCIPConfig attributes."""
    from pcip.connectors.catalog import CATALOG

    cfg = PCIPConfig()
    names = set()
    for desc in CATALOG:
        assert desc.name not in names, f"duplicate connector {desc.name}"
        names.add(desc.name)
        for var in desc.env_vars:
            assert hasattr(cfg, var), f"{desc.name}: unknown config attr {var}"
        for group in desc.env_any:
            for var in group:
                assert hasattr(cfg, var), f"{desc.name}: unknown config attr {var}"
    assert {"github", "canva", "anthropic", "wordpress", "openai", "google",
            "instagram", "facebook", "threads", "linkedin", "x", "youtube",
            "tiktok", "buffer"} <= names
