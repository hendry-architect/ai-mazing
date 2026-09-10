"""Attaching a Canva export by URL.

MCP export-design hands back a signed URL, not a file. PCIP downloads it inside
the export step so a URL and a file produce the same graph record — and says
plainly what to do when the download host is unreachable, which is a real
condition on locked-down networks rather than a hypothetical.
"""

import json

import pytest

from pcip.config import PCIPConfig
from pcip.connectors.canva import ExportDownloadError, download_export_url
from pcip.graph.store import KnowledgeGraph
from pcip.models import Brief, NodeKind, PipelineRun
from pcip.pipelines.base import HandoffRequired, Pipeline, PipelineRunner, Step
from pcip.pipelines.library import export_deliverable

import requests


class FakeResponse:
    def __init__(self, status=200, chunks=(b"%PDF-1.4 fake",), exc=None):
        self.status_code = status
        self._chunks = chunks
        self._exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def iter_content(self, chunk_size=None):
        if self._exc:
            raise self._exc
        return iter(self._chunks)


class FakeSession:
    """Records every URL it is asked for, so we can assert on egress."""

    def __init__(self, response):
        self.response = response
        self.requested = []
        self.headers = {}

    def get(self, url, **kw):
        self.requested.append((url, kw))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


URL = "https://export-download.canva.com/x/DAHUecsTYgU/file.pdf?sig=secret"


def test_downloads_signed_url_to_disk(tmp_path):
    session = FakeSession(FakeResponse())
    dest = download_export_url(URL, tmp_path / "out.pdf", session=session)
    assert dest.read_bytes() == b"%PDF-1.4 fake"


def test_download_sends_no_credentials(tmp_path):
    """The URL is already signed; adding auth headers would leak them to a CDN."""
    session = FakeSession(FakeResponse())
    download_export_url(URL, tmp_path / "out.pdf", session=session)
    (_, kw), = session.requested
    assert "headers" not in kw or not kw.get("headers")
    assert "auth" not in kw
    assert session.headers == {}


def test_expired_url_says_so(tmp_path):
    session = FakeSession(FakeResponse(status=403))
    with pytest.raises(ExportDownloadError) as e:
        download_export_url(URL, tmp_path / "out.pdf", session=session)
    assert "expire" in str(e.value).lower()


def test_blocked_host_names_the_fallback(tmp_path):
    session = FakeSession(requests.ConnectionError("CONNECT tunnel failed, 403"))
    with pytest.raises(ExportDownloadError) as e:
        download_export_url(URL, tmp_path / "out.pdf", session=session)
    msg = str(e.value)
    assert "export-download.canva.com" in msg
    assert "--export-file" in msg
    assert "sig=secret" not in msg          # never echo the signed query back
    assert not (tmp_path / "out.pdf").exists()   # no truncated leftover


def test_empty_download_is_not_a_deliverable(tmp_path):
    session = FakeSession(FakeResponse(chunks=()))
    with pytest.raises(ExportDownloadError) as e:
        download_export_url(URL, tmp_path / "out.pdf", session=session)
    assert "empty" in str(e.value).lower()
    assert not (tmp_path / "out.pdf").exists()


# ── the export step ──────────────────────────────────────────────────────────


def _ctx(tmp_path, **extra):
    """The export step's context, as it looks once assembly has produced a design."""
    cfg = PCIPConfig(data_dir=tmp_path / "data", canva_mode="mcp")
    g = KnowledgeGraph(":memory:")
    brief = Brief(id="b1", title="Prevención de la diabetes", language="es")
    run = PipelineRun(id="run_test", pipeline="t", brief_id=brief.id)
    ctx = {"cfg": cfg, "graph": g, "brief": brief, "run": run,
           "design_id": "DAHUecsTYgU", "export_format": "pdf"}
    ctx.update(extra)
    return ctx, run, g


def test_handoff_offers_both_url_and_file(tmp_path):
    ctx, run, _ = _ctx(tmp_path)
    with pytest.raises(HandoffRequired) as e:
        export_deliverable(ctx)
    how = e.value.spec["how"]
    assert "--export-url" in how
    assert "--export-file" in how
    assert f"pcip attach {run.id}" in how


def test_attached_url_produces_a_normal_output(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, dest, timeout=60, session=None):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 fake")
        return dest

    monkeypatch.setattr("pcip.connectors.canva.download_export_url", fake_download)
    ctx, _, g = _ctx(tmp_path, _export_urls=[URL])
    msg = export_deliverable(ctx)

    assert calls == [URL]
    assert "Exported 1 file(s)" in msg
    node = g.get_node(ctx["output_id"])
    assert node["kind"] == NodeKind.OUTPUT.value
    data = node["payload"]
    # Licensing provenance must be identical to the --export-file path: this is
    # a Canva export, so it is publishable.
    assert data["metadata"]["via_export"] is True
    assert data["metadata"]["format"] == "pdf"
    assert data["local_path"].endswith(".pdf")


def test_attached_file_still_wins_over_url(tmp_path):
    f = tmp_path / "already.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    ctx, _, _ = _ctx(tmp_path, export_files=[str(f)], _export_urls=[URL])
    export_deliverable(ctx)
    assert ctx["export_paths"] == [str(f)]


# ── signed URLs are credentials ──────────────────────────────────────────────


def test_error_never_echoes_the_signature(tmp_path):
    """The real failure wraps a requests error whose text embeds the full URL."""
    embedded = requests.ConnectionError(
        f"HTTPSConnectionPool(host='export-download.canva.com', port=443): "
        f"Max retries exceeded with url: {URL} (Caused by ProxyError('Tunnel "
        f"connection failed: 403 Forbidden'))"
    )
    session = FakeSession(embedded)
    with pytest.raises(ExportDownloadError) as e:
        download_export_url(URL, tmp_path / "out.pdf", session=session)
    msg = str(e.value)
    assert "sig=secret" not in msg
    assert "<redacted>" in msg
    assert "403 Forbidden" in msg           # the diagnosis survives redaction
    assert "export-download.canva.com" in msg


def test_signed_url_is_not_written_to_the_run_record(tmp_path):
    run = PipelineRun(id="run_test", pipeline="t", brief_id="b1")
    run.context["_export_urls"] = [URL]
    run.context["design_id"] = "DAHUecsTYgU"
    d = run.to_dict()
    assert "_export_urls" not in d["context"]
    assert URL not in json.dumps(d)
    assert d["context"]["design_id"] == "DAHUecsTYgU"   # ordinary state survives


def test_step_failures_are_scrubbed_before_they_are_persisted():
    from pcip.redact import redact_urls

    detail = redact_urls(f"ExportDownloadError: failed fetching {URL} after 3 tries")
    assert "sig=secret" not in detail
    assert "export-download.canva.com" in detail
    assert "after 3 tries" in detail


def test_redaction_catches_the_relative_url_requests_actually_reports():
    """urllib3 reports the request target relative — the shape that leaked."""
    from pcip.redact import redact_urls

    real = (
        "HTTPSConnectionPool(host='export-download.canva.com', port=443): Max "
        "retries exceeded with url: /sTYgU/DAHUecsTYgU/-1/0-4863.pdf?"
        "X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=8d71c043b2e15d97 "
        "(Caused by ProxyError('Tunnel connection failed: 403 Forbidden'))"
    )
    out = redact_urls(real)
    assert "8d71c043b2e15d97" not in out
    assert "AWS4-HMAC-SHA256" not in out
    assert "/sTYgU/DAHUecsTYgU/-1/0-4863.pdf" in out    # path kept
    assert "403 Forbidden" in out                        # diagnosis kept


def test_redaction_scrubs_bare_credential_params():
    from pcip.redact import redact_urls

    out = redact_urls("failed: api_key=sk-abc123 token=xyz789 status=500")
    assert "sk-abc123" not in out and "xyz789" not in out
    assert "status=500" in out


def test_redaction_is_idempotent():
    """Details are scrubbed at the raise site and again before persisting."""
    from pcip.redact import redact_urls

    once = redact_urls("with url: /a/b.pdf?X-Amz-Signature=abc (403)")
    assert redact_urls(once) == once
    assert once.count("<redacted>") == 1
