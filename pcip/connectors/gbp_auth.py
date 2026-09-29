"""One-command Google Business Profile OAuth helper — ``pcip gbp-auth``.

Mirrors ``pcip/connectors/canva_auth.py`` — same shape, same reasons. GBP's
own Local Posts API restricts ``localPosts.create`` to approved Business
Profile API partners (see ``GBPAccessDenied`` in ``pcip/connectors/
social.py``), but the OAuth dance and the account/location discovery calls
this module makes are NOT partner-gated — a plain Google Cloud OAuth client
can run this today, before that approval ever comes through, and use it to
find the real GBP_ACCOUNT_ID / GBP_LOCATION_ID values.

    export GBP_CLIENT_ID=...   GBP_CLIENT_SECRET=...
    python -m pcip gbp-auth              # writes GBP_ACCESS_TOKEN / GBP_REFRESH_TOKEN
    python -m pcip gbp-auth --discover   # lists accounts + locations visible
                                          # to the token just obtained, so the
                                          # real listing can be told apart
                                          # from a duplicate by eye

Unlike Canva, Google does not rotate the refresh token on every use — the
same refresh token keeps working indefinitely (until revoked), so there is
no rotation-persistence race to worry about here. ``access_type=offline``
plus ``prompt=consent`` are what make Google hand back a refresh token at
all; without them a re-authorization silently gets none, which is caught
here rather than left to fail an hour later.
"""

from __future__ import annotations

import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from pcip.config import PCIPConfig

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
LOCATIONS_URL_TMPL = (
    "https://mybusinessbusinessinformation.googleapis.com/v1/{account}/locations"
    "?readMask=name,title,storefrontAddress&pageSize=100"
)

#: The one scope this needs. Google's Business Profile suite has several
#: narrower scopes (business.manage is the broad one), but Local Posts and
#: the discovery APIs below both accept it, and requesting the same scope
#: PCIP will actually use at publish time keeps the consent screen honest.
SCOPE = "https://www.googleapis.com/auth/business.manage"

#: The listing name this practice actually uses — never the duplicate.
#: Purely advisory (used to flag a likely-wrong match in --discover output),
#: not a filter: an operator confirms the real one by eye either way.
_REAL_LISTING_HINT = "passqual health"
_DUPLICATE_LISTING_HINT = "hendry perez pascual"


def build_authorize_url(
    client_id: str, redirect_uri: str, state: str, scope: str = SCOPE
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(cfg: PCIPConfig, code: str, redirect_uri: str) -> Dict[str, Any]:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cfg.gbp_client_id,
            "client_secret": cfg.gbp_client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=cfg.request_timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Token exchange failed ({resp.status_code}): {resp.text[:300]}"
        )
    data = resp.json()
    if "refresh_token" not in data:
        raise RuntimeError(
            "Google did not return a refresh token. This happens when this "
            "account has already granted this app consent before — Google "
            "only hands back a refresh token on the FIRST consent unless "
            "asked again. Revoke this app's access at "
            "https://myaccount.google.com/permissions and run `pcip gbp-auth` "
            "again. Without a refresh token, unattended posting will stop "
            "working the moment this access token expires (about an hour)."
        )
    return data


def _require_client(cfg: PCIPConfig) -> None:
    if not (cfg.gbp_client_id and cfg.gbp_client_secret):
        raise RuntimeError(
            "Set GBP_CLIENT_ID and GBP_CLIENT_SECRET first — from a "
            "'Desktop app' OAuth client in a Google Cloud project "
            "(console.cloud.google.com → APIs & Services → Credentials)."
        )


class _CallbackHandler(BaseHTTPRequestHandler):
    result: Dict[str, str] = {}
    expected_state = ""

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler API
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        error = (query.get("error") or [""])[0]
        if error:
            type(self).result = {"error": error}
            body = f"Authorization failed: {error}. You can close this tab."
        elif state != type(self).expected_state:
            type(self).result = {"error": "state_mismatch"}
            body = "State mismatch (possible CSRF) — run pcip gbp-auth again."
        else:
            type(self).result = {"code": code}
            body = "✅ Google authorized. You can close this tab and return to the terminal."
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><h2>{body}</h2></body></html>".encode())

    def log_message(self, *args):  # silence request logging
        pass


def run_flow(
    cfg: PCIPConfig,
    port: int = 8090,
    scope: str = SCOPE,
    write_env: Optional[str] = ".env",
    open_browser: bool = True,
    timeout: float = 300.0,
) -> Dict[str, str]:
    """Run the OAuth flow with a local loopback callback. Returns the tokens.

    A 'Desktop app' OAuth client (the type this whole flow assumes) is
    registered with Google without any redirect URI to configure — Google
    accepts any http://127.0.0.1:<port>/... loopback for that client type,
    unlike Canva, which requires the exact URL to be pre-registered.
    """
    _require_client(cfg)
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = secrets.token_urlsafe(24)
    url = build_authorize_url(cfg.gbp_client_id, redirect_uri, state, scope)

    _CallbackHandler.result = {}
    _CallbackHandler.expected_state = state
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 1.0

    print(f"Listening on {redirect_uri}")
    print("If the browser doesn't open, visit:\n\n  " + url + "\n")
    if open_browser:
        webbrowser.open(url)

    deadline = time.monotonic() + timeout
    while not _CallbackHandler.result and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise RuntimeError(f"No callback received within {timeout:.0f}s.")
    if "error" in result:
        raise RuntimeError(f"Authorization failed: {result['error']}")

    tokens = exchange_code(cfg, result["code"], redirect_uri)
    return _store_tokens(tokens, write_env)


def _store_tokens(tokens: Dict[str, str], write_env: Optional[str]) -> Dict[str, str]:
    from pcip.connectors.canva_auth import update_env_file

    payload = {
        "GBP_ACCESS_TOKEN": tokens.get("access_token", ""),
        "GBP_REFRESH_TOKEN": tokens.get("refresh_token", ""),
    }
    if write_env:
        update_env_file(Path(write_env), payload)
        print(f"Tokens written to {write_env}. Next:")
        print("  python -m pcip gbp-auth --discover     # find account/location IDs")
    else:
        print("Add these to your environment (values hidden from logs):")
        for key in payload:
            print(f"  {key}=<received>")
    return tokens


def discover_accounts_and_locations(
    cfg: PCIPConfig, session: Optional[requests.Session] = None
) -> List[Dict[str, Any]]:
    """List every account + location this token can see.

    Not partner-gated — works today, before Business Profile API approval
    for Local Posts comes through, which is exactly why this exists: an
    operator can find the real GBP_ACCOUNT_ID/GBP_LOCATION_ID and confirm
    which listing is which well before posting is actually possible.
    """
    http = session or requests.Session()
    headers = {"Authorization": f"Bearer {cfg.gbp_access_token}"}
    resp = http.get(ACCOUNTS_URL, headers=headers, timeout=cfg.request_timeout)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Listing accounts failed ({resp.status_code}): {resp.text[:300]}"
        )
    accounts = resp.json().get("accounts", [])

    found: List[Dict[str, Any]] = []
    for account in accounts:
        account_name = account.get("name", "")          # "accounts/{id}"
        locations_url = LOCATIONS_URL_TMPL.format(account=account_name)
        loc_resp = http.get(locations_url, headers=headers, timeout=cfg.request_timeout)
        if loc_resp.status_code != 200:
            found.append({
                "account_id": account_name.split("/")[-1],
                "account_name": account.get("accountName", ""),
                "locations_error": f"{loc_resp.status_code}: {loc_resp.text[:200]}",
            })
            continue
        for location in loc_resp.json().get("locations", []):
            title = location.get("title", "")
            lowered = title.lower()
            flag = ""
            if _DUPLICATE_LISTING_HINT in lowered:
                flag = "⚠ looks like the DUPLICATE listing — do not use"
            elif _REAL_LISTING_HINT in lowered:
                flag = "looks like the real listing"
            found.append({
                "account_id": account_name.split("/")[-1],
                "account_name": account.get("accountName", ""),
                "location_id": location.get("name", "").split("/")[-1],
                "title": title,
                "address": location.get("storefrontAddress", {}),
                "note": flag,
            })
    return found
