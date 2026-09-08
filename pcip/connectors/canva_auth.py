"""One-command Canva OAuth (PKCE) helper — ``pcip canva-auth``.

Turns the one fiddly step of Canva setup (the OAuth 2.0 PKCE dance) into:

    export CANVA_CLIENT_ID=...   CANVA_CLIENT_SECRET=...
    python -m pcip canva-auth

What it does:
1. Generates a PKCE verifier/challenge and a CSRF ``state`` value.
2. Opens your browser at Canva's consent screen for your integration.
3. Catches the redirect on http://127.0.0.1:<port>/callback with a tiny
   local HTTP server (add exactly that URL to the integration's redirect
   URLs in the developer portal).
4. Exchanges the code for tokens and writes CANVA_ACCESS_TOKEN /
   CANVA_REFRESH_TOKEN into your .env (or prints them with --no-write).

Works with a *public integration in development mode* — no Enterprise plan
required. Canva rotates refresh tokens on every refresh; PCIP handles that
at request time, so this flow is normally run once.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

from pcip.config import PCIPConfig

AUTHORIZE_URL = "https://www.canva.com/api/oauth/authorize"
TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"

DEFAULT_SCOPES = (
    "design:meta:read design:content:read design:content:write "
    "folder:read asset:read brandtemplate:meta:read brandtemplate:content:read"
)


def make_pkce_pair() -> Tuple[str, str]:
    """RFC 7636 verifier + S256 challenge."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(
    client_id: str,
    redirect_uri: str,
    challenge: str,
    state: str,
    scopes: str = DEFAULT_SCOPES,
) -> str:
    params = {
        "code_challenge": challenge,
        "code_challenge_method": "s256",
        "scope": scopes,
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(
    cfg: PCIPConfig, code: str, verifier: str, redirect_uri: str
) -> Dict[str, str]:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        },
        auth=(cfg.canva_client_id, cfg.canva_client_secret),
        timeout=cfg.request_timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Token exchange failed ({resp.status_code}): {resp.text[:300]}"
        )
    return resp.json()


def update_env_file(env_path: Path, values: Dict[str, str]) -> None:
    """Set/replace KEY=value lines in a .env file, preserving everything else."""
    lines = (
        env_path.read_text(encoding="utf-8").splitlines()
        if env_path.exists()
        else []
    )
    remaining = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


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
            body = "State mismatch (possible CSRF) — run pcip canva-auth again."
        else:
            type(self).result = {"code": code}
            body = "✅ Canva authorized. You can close this tab and return to the terminal."
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><h2>{body}</h2></body></html>".encode())

    def log_message(self, *args):  # silence request logging
        pass


def _read_pasted_code(expected_state: str) -> str:
    """Take the authorization code from the operator.

    A hosted redirect URL sends the code to a web address, not to this
    machine, so there is no local callback to catch. The code is visible in the
    browser's address bar either way, and pasting either the whole redirected
    URL or the bare code is enough to finish the exchange.
    """
    from urllib.parse import parse_qs, urlparse

    print("\nAfter approving, your browser lands on the redirect URL.")
    print("Copy the whole address from the address bar (or just the code=... "
          "value), paste it below, then press Return.\n")
    raw = input("Redirected URL or code (paste, then press Return): ").strip()
    if not raw:
        raise RuntimeError("Nothing pasted — authorization not completed.")

    code, state = raw, ""
    if "code=" in raw:
        query = urlparse(raw).query or raw.split("?", 1)[-1]
        params = parse_qs(query)
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0]

    # Canva issues the code as a JWT, and it is long enough that a clipboard
    # or terminal can cut it. A truncated code is rejected by the token
    # endpoint with a generic error that reads like a configuration problem,
    # so it is worth naming here while the operator still has the browser open.
    if "." in code:
        parts = code.split(".")
        if len(parts) != 3 or not all(parts):
            raise RuntimeError(
                f"That code looks truncated — {len(code)} characters in "
                f"{len(parts)} segment(s), where Canva issues three. Long URLs "
                "are easy to cut when copying. Select the address bar and use "
                "Select All (Cmd-A) before copying, then run the command again "
                "— a code is single-use, so this one cannot be retried."
            )

    if state and expected_state and state != expected_state:
        # The CSRF check still applies when the operator carries the code by
        # hand; a mismatched state means this is not the flow we started.
        raise RuntimeError(
            "The pasted state does not match the request that was started. "
            "Run the command again rather than continuing with this code."
        )
    if not code:
        raise RuntimeError(f"Could not find an authorization code in: {raw[:60]}")
    return code


def run_flow(
    cfg: PCIPConfig,
    port: int = 8080,
    scopes: str = DEFAULT_SCOPES,
    write_env: Optional[str] = ".env",
    open_browser: bool = True,
    timeout: float = 300.0,
    redirect_uri: str = "",
    manual: bool = False,
) -> Dict[str, str]:
    """Run the full PKCE flow. Returns the token payload.

    By default the redirect is caught by a local server. Pass ``redirect_uri``
    (and ``manual``) when the integration is registered with a hosted callback
    — Canva requires a non-localhost URL to review a *public* integration, and
    the code then arrives in a browser rather than on this machine.
    """
    if not (cfg.canva_client_id and cfg.canva_client_secret):
        raise RuntimeError(
            "Set CANVA_CLIENT_ID and CANVA_CLIENT_SECRET first (from your "
            "integration's Configuration tab at canva.com/developers)."
        )
    local = not (redirect_uri or manual)
    redirect_uri = redirect_uri or f"http://127.0.0.1:{port}/callback"
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(24)
    url = build_authorize_url(cfg.canva_client_id, redirect_uri, challenge, state, scopes)

    if not local:
        print("Authorize in the browser:\n\n  " + url + "\n")
        if open_browser:
            webbrowser.open(url)
        code = _read_pasted_code(state)
        tokens = exchange_code(cfg, code, verifier, redirect_uri)
        return _store_tokens(tokens, write_env)

    _CallbackHandler.result = {}
    _CallbackHandler.expected_state = state
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 1.0

    print(f"Listening on {redirect_uri}")
    print("If the browser doesn't open, visit:\n\n  " + url + "\n")
    if open_browser:
        webbrowser.open(url)

    import time

    deadline = time.monotonic() + timeout
    while not _CallbackHandler.result and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise RuntimeError(f"No callback received within {timeout:.0f}s.")
    if "error" in result:
        raise RuntimeError(f"Authorization failed: {result['error']}")

    tokens = exchange_code(cfg, result["code"], verifier, redirect_uri)
    return _store_tokens(tokens, write_env)


def _store_tokens(
    tokens: Dict[str, str], write_env: Optional[str]
) -> Dict[str, str]:
    payload = {
        "CANVA_ACCESS_TOKEN": tokens.get("access_token", ""),
        "CANVA_REFRESH_TOKEN": tokens.get("refresh_token", ""),
    }
    if write_env:
        update_env_file(Path(write_env), payload)
        print(f"Tokens written to {write_env}. Next:")
        print("  pcip doctor --live")
        print("  pcip sync")
    else:
        print("Add these to your environment (values hidden from logs):")
        for key in payload:
            print(f"  {key}=<received>")
    return tokens
