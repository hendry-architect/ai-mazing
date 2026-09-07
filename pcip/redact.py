"""Redaction helpers.

Error text in PCIP does not stay on a terminal: it is written into step
details, persisted in the run record, and read back by whoever debugs the run
later. Anything that carries a credential has to be scrubbed on the way in.
"""

from __future__ import annotations

import re

# Absolute URLs *and* bare paths: urllib3 reports the request target relative
# ("Max retries exceeded with url: /path?X-Amz-Signature=..."), so anchoring on
# a scheme alone silently misses the exact string we most need to scrub.
# The (?!<redacted>) guard keeps this idempotent: step details are scrubbed
# where the error is raised and again before they are persisted, and redacting
# twice must not stack markers.
_URL_RE = re.compile(r"((?:https?://|/)[^\s'\"<>?]*)\?(?!<redacted>)[^\s'\"<>]*")

# Second layer, for credentials that reach us outside a recognizable URL.
_PARAM_RE = re.compile(
    r"\b(X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|Signature|"
    r"sig|token|access_token|refresh_token|api[-_]?key|password|secret)"
    r"=[^&\s'\"<>]+",
    re.IGNORECASE,
)


def redact_urls(text: str) -> str:
    """Strip query strings from any URL — absolute or relative — in ``text``.

    Signed URLs — Canva export downloads above all — carry their authorization
    in the query string. The host and path are the diagnostically useful part;
    the signature is a bearer credential for the file.
    """
    return _PARAM_RE.sub(r"\1=<redacted>", _URL_RE.sub(r"\1?<redacted>", text))
