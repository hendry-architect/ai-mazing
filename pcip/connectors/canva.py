"""Canva Connect API client.

Official REST API (https://www.canva.dev/docs/connect/) using the org's own
authenticated integration — OAuth 2.0 with PKCE, scoped tokens, and only
supported endpoints:

- designs:          list/search, get, create
- folders:          get, list items, create, move
- assets:           get, upload from URL (job-based)
- brand templates:  list/search, get, dataset, autofill (job-based)
- exports:          create export job, poll, download

Licensing posture: this client can *export designs* (the supported workflow
that applies the account's Pro entitlements) but has no method to rip a
premium element out of a design — that is by design (see pcip.licensing).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import requests

from pcip.config import PCIPConfig

TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"


class CanvaError(Exception):
    """A Canva API call failed."""

    def __init__(self, message: str, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class CanvaClient:
    """Thin, well-behaved client for the Canva Connect API."""

    def __init__(self, config: PCIPConfig, session: Optional[requests.Session] = None) -> None:
        self.cfg = config
        self.http = session or requests.Session()
        self._access_token = config.canva_access_token

    # ── Auth ─────────────────────────────────────────────────────────────

    def _refresh_access_token(self) -> None:
        if not (self.cfg.canva_refresh_token and self.cfg.canva_client_id):
            raise CanvaError(
                "Canva access token expired and no refresh credentials are "
                "configured (CANVA_REFRESH_TOKEN / CANVA_CLIENT_ID)."
            )
        resp = self.http.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.cfg.canva_refresh_token,
            },
            auth=(self.cfg.canva_client_id, self.cfg.canva_client_secret),
            timeout=self.cfg.request_timeout,
        )
        if resp.status_code != 200:
            raise CanvaError(
                f"Canva token refresh failed ({resp.status_code})",
                resp.status_code,
                resp.text[:500],
            )
        data = resp.json()
        self._access_token = data["access_token"]
        # Canva rotates refresh tokens on every refresh.
        self.cfg.canva_refresh_token = data.get(
            "refresh_token", self.cfg.canva_refresh_token
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        retried_auth: bool = False,
    ) -> Dict[str, Any]:
        if not self._access_token:
            self._refresh_access_token()
        url = f"{self.cfg.canva_api_base}{path}"
        for attempt in range(4):
            resp = self.http.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=self.cfg.request_timeout,
            )
            if resp.status_code == 401 and not retried_auth:
                self._refresh_access_token()
                return self._request(
                    method, path, params=params, json_body=json_body, retried_auth=True
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                time.sleep(min(retry_after, 30))
                continue
            if resp.status_code >= 400:
                raise CanvaError(
                    f"{method} {path} → {resp.status_code}",
                    resp.status_code,
                    resp.text[:500],
                )
            return resp.json() if resp.content else {}
        raise CanvaError(f"{method} {path}: retries exhausted", resp.status_code)

    def _paginate(
        self, path: str, params: Optional[Dict[str, Any]] = None, items_key: str = "items"
    ) -> Iterator[Dict[str, Any]]:
        params = dict(params or {})
        while True:
            page = self._request("GET", path, params=params)
            for item in page.get(items_key, []):
                yield item
            continuation = page.get("continuation")
            if not continuation:
                return
            params["continuation"] = continuation

    def _poll_job(self, path: str, key: str, interval: float = 2.0, timeout: float = 300.0) -> Dict[str, Any]:
        """Poll an async Canva job (export / autofill / upload) to completion."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self._request("GET", path)
            job = data.get(key) or data.get("job") or data
            status = job.get("status")
            if status == "success":
                return job
            if status == "failed":
                raise CanvaError(f"Canva job failed: {job.get('error', job)}")
            time.sleep(interval)
        raise CanvaError(f"Canva job at {path} timed out after {timeout:.0f}s")

    # ── Profile ──────────────────────────────────────────────────────────

    def me(self) -> Dict[str, Any]:
        return self._request("GET", "/users/me")

    # ── Designs ──────────────────────────────────────────────────────────

    def list_designs(self, query: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if query:
            params["query"] = query
        out: List[Dict[str, Any]] = []
        for item in self._paginate("/designs", params):
            out.append(item)
            if len(out) >= limit:
                break
        return out

    def get_design(self, design_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/designs/{design_id}").get("design", {})

    def create_design(
        self, title: str, design_type: Optional[Dict[str, Any]] = None, asset_id: str = ""
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"title": title}
        if design_type:
            body["design_type"] = design_type
        if asset_id:
            body["asset_id"] = asset_id
        return self._request("POST", "/designs", json_body=body).get("design", {})

    # ── Folders ──────────────────────────────────────────────────────────

    def get_folder(self, folder_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/folders/{folder_id}").get("folder", {})

    def list_folder_items(
        self, folder_id: str = "root", item_types: str = ""
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if item_types:
            params["item_types"] = item_types
        return list(self._paginate(f"/folders/{folder_id}/items", params))

    def create_folder(self, name: str, parent_folder_id: str = "root") -> Dict[str, Any]:
        return self._request(
            "POST",
            "/folders",
            json_body={"name": name, "parent_folder_id": parent_folder_id},
        ).get("folder", {})

    # ── Assets ───────────────────────────────────────────────────────────

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/assets/{asset_id}").get("asset", {})

    def upload_asset_from_url(self, name: str, url: str) -> Dict[str, Any]:
        """Upload an externally-hosted file into Canva (job-based)."""
        job = self._request(
            "POST",
            "/url-asset-uploads",
            json_body={"name": name[:50], "url": url},
        ).get("job", {})
        job_id = job.get("id")
        if job.get("status") == "success":
            return job.get("asset", {})
        done = self._poll_job(f"/url-asset-uploads/{job_id}", "job")
        return done.get("asset", {})

    # ── Brand templates ──────────────────────────────────────────────────

    def list_brand_templates(self, query: str = "") -> List[Dict[str, Any]]:
        params = {"query": query} if query else None
        return list(self._paginate("/brand-templates", params))

    def get_brand_template(self, template_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/brand-templates/{template_id}").get(
            "brand_template", {}
        )

    def get_brand_template_dataset(self, template_id: str) -> Dict[str, Any]:
        """Autofillable fields (text/image/chart placeholders) of a template."""
        return self._request("GET", f"/brand-templates/{template_id}/dataset")

    def autofill(
        self, brand_template_id: str, data: Dict[str, Any], title: str = ""
    ) -> Dict[str, Any]:
        """Create a new design by autofilling a brand template — the supported
        way to mass-produce on-brand deliverables. Returns the created design."""
        body: Dict[str, Any] = {"brand_template_id": brand_template_id, "data": data}
        if title:
            body["title"] = title
        job = self._request("POST", "/autofills", json_body=body).get("job", {})
        if job.get("status") == "success":
            return job.get("result", {}).get("design", {})
        done = self._poll_job(f"/autofills/{job['id']}", "job")
        return done.get("result", {}).get("design", {})

    # ── Export (the supported premium-content workflow) ──────────────────

    def export_design(
        self,
        design_id: str,
        fmt: str = "png",
        *,
        pages: Optional[List[int]] = None,
        quality: str = "regular",
    ) -> List[str]:
        """Export a design via the official export API and return download URLs.

        This is the only way premium content leaves Canva through PCIP: as
        part of a rendered design, with the account's entitlements applied
        server-side by Canva.
        """
        fmt_body: Dict[str, Any] = {"type": fmt}
        if fmt in ("png", "jpg") and quality:
            fmt_body["quality"] = quality
        if pages:
            fmt_body["pages"] = pages
        job = self._request(
            "POST",
            "/exports",
            json_body={"design_id": design_id, "format": fmt_body},
        ).get("job", {})
        if job.get("status") != "success":
            job = self._poll_job(f"/exports/{job['id']}", "job")
        return job.get("urls", [])

    def download_export(self, url: str, dest: Path) -> Path:
        """Download an export URL to disk (URLs are short-lived)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.http.get(url, stream=True, timeout=self.cfg.request_timeout) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
        return dest
