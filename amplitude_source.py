"""
amplitude_source.py — Amplitude Live Data Connector
=====================================================
Fetches event-volume data from Amplitude's Events Segmentation API
and returns a tidy pandas DataFrame ready for run_analysis().

Credential resolution order (highest → lowest priority)
--------------------------------------------------------
1. Streamlit secrets  — st.secrets["AMPLITUDE_API_KEY"]
   (set via .streamlit/secrets.toml or Streamlit Cloud → App Settings → Secrets)
2. Environment variables — os.environ["AMPLITUDE_API_KEY"]
   (export in shell, docker-compose env:, Railway/Render env panel, etc.)

NOTHING is hardcoded. If credentials are absent the function returns an
empty DataFrame with status.code == "no_credentials" and a clear message.

Public API
----------
    df, status = fetch_amplitude_events(
        metric  = 'totals',   # 'totals' | 'uniques' | 'average'
        days    = 7,          # lookback window in days (1–90)
        limit   = 50,         # max distinct events to return
    )

    df      : pd.DataFrame  columns → [event_name, date, count]
              Always empty DataFrame (never None) on any error.
    status  : AmplitudeStatus  (see dataclass below)

Status codes (status.code)
---------------------------
    "ok"              – data returned and parsed successfully
    "empty_project"   – API reachable + auth valid, but project has no events
    "no_credentials"  – neither st.secrets nor env vars carry the API key/secret
    "api_error"       – non-2xx HTTP response; message includes status + body
    "parse_error"     – HTTP 200 but response body could not be parsed

See .env.example for credential setup instructions.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Tuple

import pandas as pd
import requests

log = logging.getLogger(__name__)

# ── Amplitude REST API base URLs ───────────────────────────────────────────────
_API_US = "https://amplitude.com/api/2"
_API_EU = "https://analytics.eu.amplitude.com/api/2"


# ─────────────────────────────────────────────────────────────────────────────
# Status dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AmplitudeStatus:
    """Structured result companion returned alongside every DataFrame."""
    ok:         bool
    code:       str
    message:    str
    project_id: str  = ""
    rows:       int  = 0
    events:     list = field(default_factory=list)

    def __str__(self) -> str:
        icon = "✅" if self.ok else "⚠️"
        return f"{icon} [{self.code}] {self.message}"


# ─────────────────────────────────────────────────────────────────────────────
# Credential resolution — st.secrets first, then os.environ, never hardcoded
# ─────────────────────────────────────────────────────────────────────────────

def _get_secret(key: str, default: str = "") -> str:
    """
    Resolve a configuration value using a two-layer lookup:

    1. st.secrets[key]   — available on Streamlit Cloud and when
                           .streamlit/secrets.toml exists locally.
    2. os.environ[key]   — standard environment variable (dotenv,
                           shell export, Docker/Railway/Render env panel).

    Returns *default* (empty string by default) if neither source has the key.
    Never raises.
    """
    # ── Layer 1: Streamlit secrets ────────────────────────────────────────────
    # Importing streamlit unconditionally would error in non-Streamlit contexts
    # (CLI smoke-tests, notebooks, etc.).  We guard with a try/except.
    try:
        import streamlit as st  # noqa: PLC0415
        value = st.secrets.get(key, "")
        if value:
            return str(value).strip()
    except Exception:
        # Streamlit not available, not running in a Streamlit context,
        # or secrets file is absent/malformed — fall through silently.
        pass

    # ── Layer 2: Environment variable ─────────────────────────────────────────
    return os.environ.get(key, default).strip()


def _get_credentials() -> tuple[str, str, str, str]:
    """
    Return (api_key, secret_key, project_id, region).
    All values come exclusively from _get_secret(); nothing is hardcoded here.
    project_id defaults to "" (used only in status messages, not sent to API).
    region    defaults to "us".
    """
    api_key    = _get_secret("AMPLITUDE_API_KEY")
    secret_key = _get_secret("AMPLITUDE_SECRET_KEY")
    project_id = _get_secret("AMPLITUDE_PROJECT_ID", default="")
    region     = _get_secret("AMPLITUDE_REGION",     default="us").lower()
    return api_key, secret_key, project_id, region


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _base_url(region: str) -> str:
    return _API_EU if region == "eu" else _API_US


def _date_window(days: int) -> tuple[str, str]:
    """(start_YYYYMMDD, end_YYYYMMDD) for a rolling *days*-day window."""
    today = datetime.now(tz=timezone.utc).date()
    start = today - timedelta(days=days - 1)
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def _metric_param(metric: str) -> str:
    """Map friendly metric names → Amplitude API 'm' parameter value."""
    return {
        "totals":  "totals",
        "uniques": "uniques",
        "average": "average",
        "pct_dau": "pct_dau",
    }.get(metric.lower(), "totals")


def _empty_df() -> pd.DataFrame:
    """Correctly-typed empty DataFrame matching the public schema."""
    return pd.DataFrame(columns=["event_name", "date", "count"]).astype({
        "event_name": "object",
        "date":       "datetime64[ns]",
        "count":      "int64",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Core fetch function
# ─────────────────────────────────────────────────────────────────────────────

def fetch_amplitude_events(
    metric:  str = "totals",
    days:    int = 7,
    limit:   int = 50,
    timeout: int = 20,
) -> Tuple[pd.DataFrame, AmplitudeStatus]:
    """
    Query Amplitude's Events Segmentation API for top events by volume.

    Parameters
    ----------
    metric  : 'totals' (event count) | 'uniques' (distinct users) | 'average'.
    days    : Lookback window in full days, clamped to 1–90.
    limit   : Max distinct events to retrieve, clamped to 1–200.
    timeout : HTTP request timeout in seconds.

    Returns
    -------
    (pd.DataFrame, AmplitudeStatus)
        DataFrame always has columns [event_name, date, count] — empty on error.
        AmplitudeStatus.ok is True only when usable rows were returned.

    Notes
    -----
    * This function NEVER raises.  All error paths return an empty DataFrame
      plus an AmplitudeStatus with ok=False and a descriptive message.
    * Credentials are resolved via _get_credentials() — see module docstring.
    """

    # ── 1. Resolve credentials (no hardcodes) ─────────────────────────────────
    api_key, secret_key, project_id, region = _get_credentials()

    if not api_key or not secret_key:
        return _empty_df(), AmplitudeStatus(
            ok=False,
            code="no_credentials",
            message=(
                "Amplitude API credentials are not configured. "
                "Set AMPLITUDE_API_KEY and AMPLITUDE_SECRET_KEY via: "
                "(a) .streamlit/secrets.toml, "
                "(b) Streamlit Cloud → App Settings → Secrets, or "
                "(c) environment variables. "
                "See .env.example for the full setup guide."
            ),
            project_id=project_id or "(unknown)",
        )

    # ── 2. Build request parameters ───────────────────────────────────────────
    days  = max(1, min(90,  int(days)))
    limit = max(1, min(200, int(limit)))
    start, end = _date_window(days)

    # '$popularEvents' is Amplitude's built-in pseudo-event that returns the
    # top-N most-fired events for the project — no event name guessing needed.
    params = {
        "e":     '{"event_type":"$popularEvents"}',
        "start": start,
        "end":   end,
        "i":     1,                      # 1 = daily granularity
        "m":     _metric_param(metric),
        "limit": limit,
    }

    url = f"{_base_url(region)}/events/segmentation"
    log.debug("Amplitude GET %s  params=%s", url, params)

    # ── 3. Execute HTTP request ───────────────────────────────────────────────
    try:
        resp = requests.get(
            url,
            params=params,
            auth=(api_key, secret_key),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
    except requests.exceptions.Timeout:
        return _empty_df(), AmplitudeStatus(
            ok=False, code="api_error",
            message=f"Request timed out after {timeout}s — check network/VPN.",
            project_id=project_id,
        )
    except requests.exceptions.ConnectionError as exc:
        return _empty_df(), AmplitudeStatus(
            ok=False, code="api_error",
            message=f"Connection error: {exc}",
            project_id=project_id,
        )

    # ── 4. Interpret HTTP status ──────────────────────────────────────────────
    _HTTP_ERRORS = {
        401: ("HTTP 401 Unauthorised — API key or secret key is incorrect. "
              "Verify credentials in Amplitude → Settings → Projects → API Credentials."),
        403: ("HTTP 403 Forbidden — the API key may lack read access. "
              "Check project permissions in Amplitude."),
        429: ("HTTP 429 Too Many Requests — rate limit exceeded. "
              "Wait a moment and try again."),
    }
    if resp.status_code in _HTTP_ERRORS:
        return _empty_df(), AmplitudeStatus(
            ok=False, code="api_error",
            message=_HTTP_ERRORS[resp.status_code],
            project_id=project_id,
        )
    if not resp.ok:
        return _empty_df(), AmplitudeStatus(
            ok=False, code="api_error",
            message=f"HTTP {resp.status_code}: {resp.text[:400]}",
            project_id=project_id,
        )

    # ── 5. Parse response JSON ────────────────────────────────────────────────
    try:
        payload       = resp.json()
        data          = payload.get("data", {})
        series        = data.get("series",        [])
        series_labels = data.get("seriesLabels",  [])
        x_values      = data.get("xValues",       [])
    except Exception as exc:
        return _empty_df(), AmplitudeStatus(
            ok=False, code="parse_error",
            message=(f"Could not parse Amplitude response: {exc}. "
                     f"Raw (first 300 chars): {resp.text[:300]}"),
            project_id=project_id,
        )

    # ── 6. Empty-project detection ────────────────────────────────────────────
    if not series or not x_values:
        return _empty_df(), AmplitudeStatus(
            ok=False, code="empty_project",
            message=(
                f"Amplitude project{(' ID: ' + project_id) if project_id else ''} "
                f"returned no event data for the last {days} day(s). "
                "No events appear to have been ingested yet. "
                "Instrument your app with the Amplitude SDK, track some events, "
                "then re-run."
            ),
            project_id=project_id,
        )

    if all(v == 0 for s in series for v in s):
        return _empty_df(), AmplitudeStatus(
            ok=False, code="empty_project",
            message=(
                f"Amplitude returned only zero values for all events "
                f"over the last {days} day(s) "
                f"{('(project ' + project_id + ')') if project_id else ''}. "
                "No events have been ingested yet."
            ),
            project_id=project_id,
        )

    # ── 7. Build tidy long-format DataFrame ───────────────────────────────────
    try:
        dates_parsed = pd.to_datetime(x_values, format="%Y-%m-%d")
    except Exception:
        dates_parsed = pd.to_datetime(x_values)

    rows: list[dict] = [
        {"event_name": str(label), "date": date_val, "count": int(val)}
        for label, evt_series in zip(series_labels, series)
        for date_val, val in zip(dates_parsed, evt_series)
    ]

    if not rows:
        return _empty_df(), AmplitudeStatus(
            ok=False, code="empty_project",
            message="No data rows after parsing response.",
            project_id=project_id,
        )

    df = (
        pd.DataFrame(rows)
          .sort_values(["event_name", "date"])
          .reset_index(drop=True)
    )
    df["count"] = df["count"].fillna(0).astype("int64")

    distinct_events = df["event_name"].unique().tolist()
    total_count     = int(df["count"].sum())

    return df, AmplitudeStatus(
        ok=True,
        code="ok",
        message=(
            f"Fetched {len(df):,} rows · "
            f"{len(distinct_events)} event(s) · "
            f"{total_count:,} total {metric} · "
            f"last {days} day(s)."
        ),
        project_id=project_id,
        rows=len(df),
        events=distinct_events,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience aggregator
# ─────────────────────────────────────────────────────────────────────────────

def summarise_by_event(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse the long-format [event_name, date, count] DataFrame to one row
    per event.  Returns columns: [event_name, total_count, daily_avg, pct_of_total].
    Returns an empty DataFrame (with correct columns) if input is empty.
    """
    if df.empty:
        return pd.DataFrame(
            columns=["event_name", "total_count", "daily_avg", "pct_of_total"]
        )
    agg = (
        df.groupby("event_name")["count"]
          .agg(total_count="sum", daily_avg="mean")
          .reset_index()
          .sort_values("total_count", ascending=False)
          .reset_index(drop=True)
    )
    grand = agg["total_count"].sum()
    agg["pct_of_total"] = (agg["total_count"] / grand * 100).round(1)
    agg["daily_avg"]    = agg["daily_avg"].round(1)
    return agg
