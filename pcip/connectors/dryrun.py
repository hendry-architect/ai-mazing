"""Run a social publish all the way to the wire, then don't send it.

Social publishing shipped with seven adapters and zero tokens: not one line
of the code that talks to Meta, LinkedIn, X, Threads, YouTube, TikTok or
Buffer had ever executed. The tempting fix — a ``preview()`` that describes
what *would* be posted — proves only that the preview works. So this
replaces the **transport** instead: every adapter runs its real
``publish()`` unchanged, and the HTTP calls it makes are captured here
rather than sent.

That makes a dry run a genuine test of the publishing path. It also means
the canned replies have to match the real APIs' response shapes, because an
adapter that parses ``data["data"]["publish_id"]`` will fail here exactly as
it would against TikTok.

Nothing here ever opens a socket.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Tuple

from pcip.config import PCIPConfig

# Field names whose values are bearer credentials. Dry-run output is printed
# to a terminal and pasted into bug reports; a token must not ride along.
_SECRET_KEYS = {
    "access_token", "accesstoken", "token", "refresh_token", "client_secret",
    "authorization", "api_key", "apikey", "password", "secret",
}

#: Credentials replaced with a marker when they are not configured, so a dry
#: run still shows the full request shape. Every substitution is reported in
#: ``missing_credentials`` — the run never pretends the channel is ready.
_CREDENTIAL_FIELDS = (
    "buffer_token", "meta_page_token", "meta_ig_user_id", "linkedin_token",
    "linkedin_org_urn", "x_user_token", "threads_token", "threads_user_id",
    "youtube_token", "tiktok_token",
)


def redact_value(key: str, value: Any) -> Any:
    if isinstance(value, str) and key.lower().replace("-", "_") in _SECRET_KEYS:
        return "<redacted>"
    return value


def redact_mapping(data: Any) -> Any:
    """Recursively blank credential-bearing values in a request body."""
    if isinstance(data, dict):
        return {k: redact_mapping(redact_value(k, v)) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [redact_mapping(v) for v in data]
    return data


def dryrun_config(cfg: PCIPConfig) -> Tuple[PCIPConfig, List[str]]:
    """A copy of ``cfg`` with unset social credentials marked, not invented.

    Without this a dry run on an unconfigured account stops at the first
    ``available()`` check and shows nothing. With it the operator sees the
    complete request *and* an explicit list of what is missing, which is the
    honest version of both answers at once.
    """
    missing = [f for f in _CREDENTIAL_FIELDS if not getattr(cfg, f, "")]
    patched = dataclasses.replace(
        cfg, **{f: f"<{f.upper()} not set>" for f in missing}
    )
    return patched, missing


class DryRunResponse:
    """The subset of ``requests.Response`` the adapters actually touch."""

    def __init__(
        self,
        payload: Any,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return repr(self._payload)


# Buffer returns every connected profile; the adapter filters them itself, so
# offering one per service exercises the real service-name matching.
_BUFFER_PROFILES = [
    {"id": f"dryrun_profile_{s}", "service": s, "formatted_username": f"@passqual_{s}"}
    for s in ("instagram", "facebook", "linkedin", "twitter", "tiktok", "youtube")
]


class DryRunSession:
    """A ``requests.Session`` stand-in that records instead of sending.

    Responses are keyed on distinctive fragments of the real endpoints. An
    unrecognised URL raises rather than returning a generic success: a silent
    catch-all would let an adapter pointed at the wrong endpoint pass a dry
    run and fail in production, which is the failure mode this exists to
    prevent.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    # ── recording ────────────────────────────────────────────────────────
    def _record(self, method: str, url: str, kwargs: Dict[str, Any]) -> None:
        entry: Dict[str, Any] = {"method": method, "url": url}
        for key in ("params", "data", "json", "headers"):
            if kwargs.get(key) is not None:
                entry[key] = redact_mapping(kwargs[key])
        if hasattr(kwargs.get("data"), "read"):          # file upload
            entry["data"] = "<file stream>"
        self.calls.append(entry)

    @property
    def requests(self) -> List[Dict[str, Any]]:
        """Alias reading better in reports than ``calls``."""
        return self.calls

    # ── transport ────────────────────────────────────────────────────────
    def get(self, url: str, **kwargs: Any) -> DryRunResponse:
        self._record("GET", url, kwargs)
        return self._reply("GET", url)

    def post(self, url: str, **kwargs: Any) -> DryRunResponse:
        self._record("POST", url, kwargs)
        return self._reply("POST", url)

    def put(self, url: str, **kwargs: Any) -> DryRunResponse:
        self._record("PUT", url, kwargs)
        return self._reply("PUT", url)

    def _reply(self, method: str, url: str) -> DryRunResponse:
        n = len(self.calls)
        if "bufferapp.com" in url:
            if "profiles" in url:
                return DryRunResponse(_BUFFER_PROFILES)
            if "updates/create" in url:
                return DryRunResponse(
                    {"success": True, "updates": [{"id": f"dryrun_buffer_{n}"}]}
                )
        if "graph.facebook.com" in url or "graph.threads.net" in url:
            # Both container creation and publish return a bare {"id": ...}.
            return DryRunResponse({"id": f"dryrun_meta_{n}"})
        if "api.linkedin.com" in url:
            return DryRunResponse({"id": f"urn:li:share:dryrun{n}"})
        if "api.x.com" in url:
            return DryRunResponse({"data": {"id": f"dryrun_tweet_{n}"}})
        if "googleapis.com" in url:
            if method == "POST":                          # resumable init
                return DryRunResponse(
                    {},
                    headers={
                        "content-type": "application/json",
                        "Location": "https://dry-run.invalid/upload/session",
                    },
                )
            return DryRunResponse({"id": f"dryrun_video_{n}"})
        if "dry-run.invalid" in url:                      # the resumable PUT
            return DryRunResponse({"id": f"dryrun_video_{n}"})
        if "open.tiktokapis.com" in url:
            return DryRunResponse({"data": {"publish_id": f"dryrun_tiktok_{n}"}})
        raise AssertionError(
            f"dry run has no canned response for {method} {url}. Add one in "
            "pcip/connectors/dryrun.py — an unrecognised endpoint means the "
            "adapter would be calling somewhere this has never checked."
        )
