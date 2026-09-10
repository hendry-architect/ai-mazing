"""Connector Management Framework — capabilities, not credentials.

The platform never asks "is Canva connected?". It asks "can I export a PNG?
duplicate a brand template? search premium assets?" — and gets a
machine-readable answer per capability, because a connector is rarely all-on
or all-off: a scope can be missing, a plan can lack an entitlement, an API
can simply not offer an operation.

Three pieces:

- **Manifest** (``bootstrap.yaml``) — the declarative statement of which
  connectors this deployment *wants* and how each authenticates. The doctor
  provisions/diagnoses from it; connectors absent from the manifest are
  reported as ``disabled`` rather than nagging for credentials.
- **Catalog** (pcip/connectors/catalog.py) — one ConnectorDescriptor per
  connector: auth methods, env vars, docs link, and its CapabilitySpec list
  (including capabilities that are *honestly unsupported* by the vendor's
  API, so the planner never assumes them).
- **ConnectorManager** — orchestrates onboarding hints, credential checks,
  optional live health probes (auth + entitlement discovery), and the
  capability matrix the planner consumes via ``can()``.

MCP-managed connectors (the official GitHub MCP server as the repository/
automation backbone, and the Canva MCP as an in-session complement) are
first-class: they appear in the matrix as ``mcp_managed`` — available
through the MCP host, with no credentials held by PCIP.

Capability statuses:

    ready                probe passed — verified usable right now
    configured           credentials present; no live probe run/available
    mcp_managed          delegated to an MCP server (credentials live there)
    missing_credentials  desired in the manifest but env vars absent
    auth_failed          live probe rejected the credentials
    blocked              reachable, but something between PCIP and the API is
                         refusing (bot challenge, WAF, interstitial) — the
                         credentials may be fine; the path is not
    not_entitled         authenticated, but the plan/scope lacks this feature
    unsupported          the vendor's API does not offer this operation
    disabled             connector not requested in bootstrap.yaml
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pcip.config import PCIPConfig

USABLE_STATUSES = ("ready", "configured", "mcp_managed")


class ConnectorAuthError(Exception):
    """A live probe determined the credentials are invalid."""


class ConnectorBlockedError(Exception):
    """Something between PCIP and the API refused the call.

    Distinct from an auth failure: the credentials may be perfectly good, but
    a bot challenge, WAF rule or interstitial is answering instead of the API.
    Distinct from a transient network error, which leaves the connector
    ``configured`` — this one is a standing blocker and must not read as ready.
    """


class EntitlementError(Exception):
    """Authenticated, but the account's plan/scope lacks a capability."""

    def __init__(self, capabilities: List[str], detail: str = "") -> None:
        super().__init__(detail or f"not entitled: {capabilities}")
        self.capabilities = capabilities
        self.detail = detail


@dataclass
class CapabilitySpec:
    """One operation a connector can (or explicitly cannot) perform."""

    name: str                          # e.g. "export_png"
    description: str = ""
    supported: bool = True             # False = vendor API has no such operation
    entitlement: str = ""              # e.g. "canva_enterprise" (plan-gated)
    note: str = ""                     # honest context for planner/humans


@dataclass
class ConnectorDescriptor:
    """Everything the manager knows about one connector."""

    name: str
    auth_methods: Tuple[str, ...]      # ("oauth",) | ("api_key",) | ...
    capabilities: Tuple[CapabilitySpec, ...] = ()
    env_vars: Tuple[str, ...] = ()     # all required (attribute names on PCIPConfig)
    env_any: Tuple[Tuple[str, ...], ...] = ()  # alternative credential groups
    docs_url: str = ""
    setup_ref: str = ""                # pointer into pcip/SETUP.md
    mcp_managed: bool = False
    # Some connectors are MCP-managed only in certain configurations. Canva is
    # the case: in "mcp" mode an agent session holds the credentials and PCIP
    # holds none, so reporting "missing_credentials" describes a deliberate
    # design as a fault. A callable keeps that decision with the connector
    # rather than special-casing names in the manager.
    mcp_managed_when: Optional[Callable[[Any], bool]] = None
    # Optional live probe: returns {capability_name: status_override}; raises
    # ConnectorAuthError / EntitlementError to signal auth or plan problems.
    probe: Optional[Callable[[PCIPConfig], Dict[str, str]]] = None

    def configured(self, cfg: PCIPConfig) -> bool:
        if self.mcp_managed:
            return True
        if self.env_vars and not all(getattr(cfg, v, "") for v in self.env_vars):
            return False
        if self.env_any:
            return any(
                all(getattr(cfg, v, "") for v in group) for group in self.env_any
            )
        return bool(self.env_vars)

    def missing_env(self, cfg: PCIPConfig) -> List[str]:
        missing = [v for v in self.env_vars if not getattr(cfg, v, "")]
        if self.env_any and not any(
            all(getattr(cfg, v, "") for v in group) for group in self.env_any
        ):
            missing.append(
                " OR ".join("+".join(group) for group in self.env_any)
            )
        return missing


# ─── Manifest ────────────────────────────────────────────────────────────────


@dataclass
class Manifest:
    """Parsed bootstrap.yaml: the deployment's desired connector set."""

    connectors: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    path: str = ""
    exists: bool = False

    def desired(self, name: str) -> bool:
        # No manifest file → everything is a candidate (report-only mode).
        return name in self.connectors if self.exists else True

    def auth_declared(self, name: str) -> str:
        entry = self.connectors.get(name) or {}
        for key, value in entry.items():
            if value is True and key not in ("enabled",):
                return key
        return ""


def load_manifest(path: Optional[str] = None) -> Manifest:
    """Load bootstrap.yaml from an explicit path, $PCIP_BOOTSTRAP, ./bootstrap.yaml,
    or pcip/bootstrap.yaml — first hit wins; absence is not an error."""
    import os

    candidates = [
        p for p in (
            path,
            os.environ.get("PCIP_BOOTSTRAP", ""),
            "bootstrap.yaml",
            str(Path(__file__).resolve().parent.parent.parent / "bootstrap.yaml"),
        ) if p
    ]
    for candidate in candidates:
        p = Path(candidate)
        if p.is_file():
            import yaml

            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            connectors = data.get("connectors") or {}
            # `github: {oauth: true}` and bare `github:` are both accepted.
            normalized = {
                str(k): (v if isinstance(v, dict) else {})
                for k, v in connectors.items()
            }
            return Manifest(connectors=normalized, path=str(p), exists=True)
    return Manifest()


# ─── Manager ─────────────────────────────────────────────────────────────────


class ConnectorManager:
    """Onboarding, health, capability discovery, and diagnostics."""

    def __init__(
        self,
        cfg: PCIPConfig,
        catalog: Optional[List[ConnectorDescriptor]] = None,
        manifest: Optional[Manifest] = None,
    ) -> None:
        from pcip.connectors.catalog import CATALOG

        self.cfg = cfg
        self.catalog: Dict[str, ConnectorDescriptor] = {
            d.name: d for d in (catalog if catalog is not None else CATALOG)
        }
        self.manifest = manifest if manifest is not None else load_manifest()

    # ── Capability matrix ────────────────────────────────────────────────

    def connector_report(self, desc: ConnectorDescriptor, live: bool) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "connector": desc.name,
            "auth": list(desc.auth_methods),
            "desired": self.manifest.desired(desc.name),
            "docs": desc.docs_url,
            "setup": desc.setup_ref,
            "capabilities": {},
        }

        if not self.manifest.desired(desc.name):
            base_status, detail = "disabled", "not requested in bootstrap.yaml"
        elif desc.mcp_managed or (
            desc.mcp_managed_when is not None and desc.mcp_managed_when(self.cfg)
        ):
            base_status, detail = "mcp_managed", (
                "credentials held by the MCP host, not PCIP"
            )
        elif not desc.configured(self.cfg):
            base_status = "missing_credentials"
            detail = "set: " + ", ".join(desc.missing_env(self.cfg))
        else:
            base_status, detail = "configured", "credentials present (unverified)"

        overrides: Dict[str, str] = {}
        if live and base_status == "configured" and desc.probe:
            try:
                overrides = desc.probe(self.cfg) or {}
                base_status, detail = "ready", "live probe passed"
            except EntitlementError as exc:
                overrides = {c: "not_entitled" for c in exc.capabilities}
                base_status, detail = "ready", (
                    f"authenticated; entitlement gaps: {exc.detail or exc}"
                )
            except ConnectorAuthError as exc:
                base_status, detail = "auth_failed", str(exc)
            except ConnectorBlockedError as exc:
                base_status, detail = "blocked", str(exc)
            except Exception as exc:  # network flake ≠ bad credentials
                # Keep the status: a transient blip must not flip a working
                # connector to broken. But the operator asked for verification
                # and did not get it, so this must never pass silently — the
                # doctor raises it as an action below.
                detail = f"probe error (kept 'configured'): {type(exc).__name__}: {exc}"
                report["probe_error"] = detail

        report["status"] = base_status
        report["detail"] = detail
        for cap in desc.capabilities:
            if not cap.supported:
                status = "unsupported"
            elif base_status in ("disabled", "missing_credentials", "auth_failed",
                                 "blocked"):
                status = base_status
            else:
                status = overrides.get(cap.name, base_status)
            entry: Dict[str, Any] = {"status": status, "usable": status in USABLE_STATUSES}
            if cap.description:
                entry["description"] = cap.description
            if cap.note:
                entry["note"] = cap.note
            if cap.entitlement:
                entry["entitlement"] = cap.entitlement
            report["capabilities"][cap.name] = entry
        return report

    def capability_matrix(self, live: bool = False) -> Dict[str, Any]:
        return {
            name: self.connector_report(desc, live)
            for name, desc in sorted(self.catalog.items())
        }

    def can(self, capability_id: str, live: bool = False) -> Dict[str, Any]:
        """The planner's question: ``can("canva.export_png")``."""
        connector, _, capability = capability_id.partition(".")
        desc = self.catalog.get(connector)
        if not desc:
            return {"capability": capability_id, "usable": False,
                    "status": "unknown_connector",
                    "detail": f"known: {', '.join(sorted(self.catalog))}"}
        report = self.connector_report(desc, live)
        entry = report["capabilities"].get(capability)
        if not entry:
            return {"capability": capability_id, "usable": False,
                    "status": "unknown_capability",
                    "detail": f"{connector} capabilities: "
                              f"{', '.join(report['capabilities'])}"}
        return {"capability": capability_id, **entry}

    # ── Doctor ───────────────────────────────────────────────────────────

    def doctor(self, live: bool = False) -> Dict[str, Any]:
        """Full diagnostic: manifest, per-connector capability matrix, and a
        prioritized action list for everything desired-but-not-working."""
        matrix = self.capability_matrix(live)
        actions: List[str] = []
        for name, report in matrix.items():
            if report["status"] == "missing_credentials":
                actions.append(
                    f"{name}: {report['detail']}"
                    + (f" — see {report['setup']}" if report["setup"] else "")
                    + (f" ({report['docs']})" if report["docs"] else "")
                )
            elif report["status"] == "auth_failed":
                actions.append(f"{name}: credentials rejected — rotate the "
                               f"token ({report['detail']})")
            elif report["status"] == "blocked":
                actions.append(f"{name}: reachable but blocked — {report['detail']}")
            if report.get("probe_error"):
                actions.append(
                    f"{name}: live check could not complete, so '{report['status']}' "
                    f"is UNVERIFIED — {report['probe_error']}"
                )
            for cap, entry in report["capabilities"].items():
                if entry["status"] == "not_entitled":
                    actions.append(
                        f"{name}.{cap}: plan/scope upgrade needed"
                        + (f" ({entry.get('entitlement')})" if entry.get("entitlement") else "")
                    )
        undeclared = [
            n for n in self.manifest.connectors
            if self.manifest.exists and n not in self.catalog
        ]
        summary = {
            s: sum(1 for r in matrix.values() if r["status"] == s)
            for s in ("ready", "configured", "mcp_managed",
                      "missing_credentials", "auth_failed", "blocked", "disabled")
        }
        return {
            "manifest": {
                "path": self.manifest.path or "(none — report-only mode)",
                "connectors_declared": sorted(self.manifest.connectors),
                "unknown_connectors": undeclared,
            },
            "summary": {k: v for k, v in summary.items() if v},
            "connectors": matrix,
            "actions": actions,
        }
