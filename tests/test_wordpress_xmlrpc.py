"""Publishing over XML-RPC when the host strips the Authorization header.

This is not a preference for XML-RPC. It is the only WordPress-core write path
that survives a proxy dropping request headers, because the credentials travel
in the request body rather than in a header. Everything here runs offline
through an injected session.
"""

import xmlrpc.client

import pytest

from pcip.config import PCIPConfig
from pcip.connectors.wordpress import (
    WordPressAuthHeaderError,
    WordPressError,
    WordPressPublisher,
)
from pcip.connectors.wordpress_xmlrpc import (
    WordPressXMLRPC,
    XMLRPCFault,
    XMLRPCUnavailable,
)


def cfg(**kw):
    base = dict(
        wordpress_url="https://wp.passqual.com",
        wordpress_public_site="https://passqual.com",
        wordpress_user="editor",
        wordpress_app_password="abcd efgh ijkl",
    )
    base.update(kw)
    return PCIPConfig(**base)


class Resp:
    def __init__(self, text="", status=200, content_type="text/xml"):
        self.text = text
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.content = text.encode()

    def json(self):
        import json
        return json.loads(self.text)


def rpc_response(value):
    return xmlrpc.client.dumps((value,), methodresponse=True, allow_none=True)


def rpc_fault(code, message):
    return xmlrpc.client.dumps(xmlrpc.client.Fault(code, message), methodresponse=True)


class FakeSession:
    """Records each call and replies from a scripted queue."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.headers = {}
        self.auth = None

    def post(self, url, **kw):
        body = kw.get("data", b"")
        method = ""
        if body:
            try:
                _, method = xmlrpc.client.loads(
                    body.decode() if isinstance(body, bytes) else body
                )
            except Exception:
                pass
        self.calls.append((url, method, kw))
        return self.replies.pop(0) if self.replies else Resp(rpc_response(""))

    def request(self, method, url, **kw):
        self.calls.append((url, method, kw))
        return self.replies.pop(0) if self.replies else Resp(rpc_response(""))


# ── the client ───────────────────────────────────────────────────────────────


def test_credentials_travel_in_the_body_not_a_header():
    """The whole point: nothing to strip."""
    session = FakeSession([Resp(rpc_response(["wp.newPost"]))])
    rpc = WordPressXMLRPC(cfg(), session=session)
    rpc.available()
    url, method, kw = session.calls[0]
    assert url == "https://wp.passqual.com/xmlrpc.php"
    assert "Authorization" not in kw.get("headers", {})
    assert session.auth is None


def test_available_requires_wp_newpost():
    yes = WordPressXMLRPC(cfg(), session=FakeSession([Resp(rpc_response(["wp.newPost"]))]))
    assert yes.available() is True
    no = WordPressXMLRPC(cfg(), session=FakeSession([Resp(rpc_response(["system.listMethods"]))]))
    assert no.available() is False


def test_disabled_xmlrpc_is_named_not_guessed():
    session = FakeSession([Resp("Method Not Allowed", status=405, content_type="text/html")])
    rpc = WordPressXMLRPC(cfg(), session=session)
    with pytest.raises(XMLRPCUnavailable) as exc:
        rpc._call("system.listMethods")
    assert "disabled" in str(exc.value).lower()


def test_bad_credentials_explain_the_common_mistake():
    session = FakeSession([Resp(rpc_fault(403, "Incorrect username or password."))])
    rpc = WordPressXMLRPC(cfg(), session=session)
    with pytest.raises(XMLRPCFault) as exc:
        rpc._call("wp.newPost")
    msg = str(exc.value)
    assert "Application Password" in msg
    assert "spaces" in msg          # the actual repeated failure


def test_an_html_body_is_not_mistaken_for_a_reply():
    """A host error page or anti-bot challenge is not an XML-RPC response."""
    session = FakeSession([Resp("<html>blocked</html>", content_type="text/html")])
    rpc = WordPressXMLRPC(cfg(), session=session)
    with pytest.raises(WordPressError) as exc:
        rpc._call("system.listMethods")
    assert "did not return an XML-RPC response" in str(exc.value)


def test_new_post_sends_slug_excerpt_and_status():
    session = FakeSession([Resp(rpc_response("4242")), Resp(rpc_response({"link": "x"}))])
    rpc = WordPressXMLRPC(cfg(), session=session)
    post_id, _ = rpc.new_post(
        "T", "<p>b</p>", excerpt="E", slug="mi-slug", status="publish"
    )
    assert post_id == "4242"
    body = session.calls[0][2]["data"].decode()
    params, method = xmlrpc.client.loads(body)
    assert method == "wp.newPost"
    struct = params[3]
    assert struct["post_name"] == "mi-slug"
    assert struct["post_excerpt"] == "E"
    assert struct["post_status"] == "publish"


# ── the fallback ─────────────────────────────────────────────────────────────


def test_rest_auth_failure_falls_back_to_xmlrpc(monkeypatch):
    """The operator asked for the article published, not for a transport."""
    rest = FakeSession([Resp('{"code":"rest_not_logged_in"}', status=401,
                             content_type="application/json")])
    wp = WordPressPublisher(cfg(), session=rest)

    calls = {}

    class FakeRPC:
        def __init__(self, config, session=None):
            calls["built"] = True

        def available(self):
            return True

        def upload_file(self, path, mime_type=""):
            return {"id": "9", "url": "https://wp/x.pdf"}

        def set_alt_text(self, *a):
            pass

        def new_post(self, title, content, **kw):
            calls["post"] = (title, content, kw)
            return "77", "https://wp.passqual.com/?p=77"

    monkeypatch.setattr(
        "pcip.connectors.wordpress_xmlrpc.WordPressXMLRPC", FakeRPC
    )
    pub = wp.publish_post("Título", "<p>cuerpo</p>", status="publish",
                          slug="mi-slug", language="es")

    assert calls["built"] is True
    assert pub.external_id == "77"
    assert pub.status == "published"
    assert pub.metadata["transport"] == "xmlrpc"
    # The reader-facing URL must be identical to the REST path's.
    assert pub.url == "https://passqual.com/es/mi-slug/"


def test_pinning_rest_disables_the_fallback():
    """An operator who pinned the transport gets the real error, not a detour."""
    rest = FakeSession([Resp('{"code":"rest_not_logged_in"}', status=401,
                             content_type="application/json")])
    wp = WordPressPublisher(cfg(wordpress_transport="rest"), session=rest)
    with pytest.raises(WordPressAuthHeaderError):
        wp.publish_post("T", "<p>b</p>")


def test_both_paths_unavailable_says_so_once(monkeypatch):
    rest = FakeSession([Resp('{"code":"rest_not_logged_in"}', status=401,
                             content_type="application/json")])
    wp = WordPressPublisher(cfg(), session=rest)

    class DeadRPC:
        def __init__(self, config, session=None):
            pass

        def available(self):
            return False

    monkeypatch.setattr("pcip.connectors.wordpress_xmlrpc.WordPressXMLRPC", DeadRPC)
    with pytest.raises(WordPressAuthHeaderError) as exc:
        wp.publish_post("T", "<p>b</p>")
    msg = str(exc.value)
    assert "XML-RPC" in msg
    assert "request body" in msg      # explains why it would have helped


def test_rest_success_records_its_transport():
    ok = FakeSession([Resp('{"id":5,"slug":"s","status":"publish","link":"l"}',
                           content_type="application/json")])
    wp = WordPressPublisher(cfg(), session=ok)
    pub = wp.publish_post("T", "<p>b</p>", status="publish", slug="s", language="en")
    assert pub.metadata["transport"] == "rest"
