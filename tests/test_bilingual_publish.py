"""Publishing the ES/EN pair the PH standard requires.

Three things WordPress will not do on its own: link the two language versions,
carry the SEO meta, and emit structured data. All offline through an injected
session.
"""

import json

import pytest

from pcip.config import PCIPConfig
from pcip.connectors.wordpress import WordPressPublisher
from pcip.publish import seo
from pcip.standards import PH


JSON_CT = {"content-type": "application/json"}


class Resp:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self.headers = dict(JSON_CT)
        self.text = json.dumps(payload or {})
        self._payload = payload or {}

    def json(self):
        return self._payload


class RecordingSession:
    """Answers /posts and /media, remembering every request."""

    def __init__(self):
        self.calls = []
        self.headers = {}
        self.auth = None
        self._next_id = 100

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if "/media" in url:
            return Resp({"id": 55, "source_url": "https://wp.example/hero.png"})
        if url.rstrip("/").endswith("/posts"):
            self._next_id += 1
            body = kw.get("json") or {}
            slug = body.get("slug", "s")
            return Resp({
                "id": self._next_id, "slug": slug,
                "status": body.get("status", "draft"),
                "link": f"https://wp.passqual.com/{slug}/",
            })
        # POST /posts/<id> — the patch pass
        pid = url.rstrip("/").rsplit("/", 1)[-1]
        body = kw.get("json") or {}
        return Resp({
            "id": pid, "slug": "s", "status": "publish",
            "link": f"https://wp.passqual.com/patched-{pid}/",
            "content": body.get("content", ""),
        })

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def bodies_sent(self):
        out = []
        for _, url, kw in self.calls:
            body = (kw.get("json") or {}).get("content")
            if body:
                out.append(body)
        return out


def cfg():
    return PCIPConfig(
        wordpress_url="https://wp.passqual.com",
        wordpress_public_site="https://passqual.com",
        wordpress_user="editor",
        wordpress_app_password="abcd efgh",
    )


def publish(session, **over):
    wp = WordPressPublisher(cfg(), session=session)
    args = dict(
        titles={"es": "Título ES", "en": "Title EN"},
        bodies={"es": "<p>cuerpo</p>", "en": "<p>body</p>"},
        slugs={"es": "cuidar-azucar", "en": "care-blood-sugar"},
        meta_title=f"Prevención en {PH.GEO_PHRASE}",
        meta_description="Descripción breve.",
        faq=[{"q": "¿Pregunta?", "a": "Respuesta."}],
        alt_texts={"es": "alt es", "en": "alt en"},
        status="publish",
    )
    args.update(over)
    return wp.publish_bilingual(**args)


def test_publishes_both_languages():
    pubs = publish(RecordingSession())
    assert set(pubs) == {"es", "en"}
    assert pubs["es"].status == "published"
    assert pubs["en"].status == "published"


def test_each_language_links_to_the_other():
    session = RecordingSession()
    pubs = publish(session)
    assert pubs["es"].metadata["translation_url"]
    assert pubs["en"].metadata["translation_url"]
    joined = " ".join(session.bodies_sent())
    assert "Leer este artículo en español" in joined
    assert "Read this article in English" in joined


def test_the_hero_is_uploaded_once_and_shared(tmp_path):
    hero = tmp_path / "hero.png"
    hero.write_bytes(b"\x89PNG fake")
    session = RecordingSession()
    pubs = publish(session, media_paths=[str(hero)])
    # Only creations, not the follow-up alt-text patch to /media/<id>.
    uploads = [c for c in session.calls if c[1].rstrip("/").endswith("/media")]
    assert len(uploads) == 1, "two copies of the same hero is a library mess"
    assert pubs["es"].metadata["media_ids"] == [55]
    assert pubs["en"].metadata["media_ids"] == [55]


def test_seo_meta_is_sent_for_both_plugins():
    session = RecordingSession()
    publish(session)
    metas = [(kw.get("json") or {}).get("meta") for _, _, kw in session.calls]
    sent = [m for m in metas if m]
    assert sent, "no SEO meta was sent"
    keys = set(sent[0])
    assert "_yoast_wpseo_title" in keys          # Yoast
    assert "rank_math_description" in keys       # Rank Math


def test_structured_data_names_the_real_url():
    """The schema must carry the permalink WordPress assigned, which does not
    exist until after the post is created — hence the second pass."""
    session = RecordingSession()
    publish(session)
    body = [b for b in session.bodies_sent() if "application/ld+json" in b][0]
    payload = json.loads(body.split("ld+json\">", 1)[1].split("</script>", 1)[0])
    types = [n["@type"] for n in payload["@graph"]]
    assert "MedicalWebPage" in types
    assert "MedicalClinic" in types
    assert "Physician" in types
    assert "FAQPage" in types
    page = payload["@graph"][0]
    assert page["url"].startswith("https://passqual.com/")


def test_the_nap_is_printed_verbatim_in_both_languages():
    session = RecordingSession()
    publish(session)
    for body in [b for b in session.bodies_sent() if "ld+json" in b]:
        assert PH.NAP_STREET in body
        assert PH.NAP_PHONE_DISPLAY in body


def test_the_faq_appears_for_readers_not_only_for_search():
    session = RecordingSession()
    publish(session)
    body = [b for b in session.bodies_sent() if "ld+json" in b][0]
    assert "Preguntas frecuentes" in body or "Frequently asked" in body
    assert "¿Pregunta?" in body


def test_a_single_language_still_publishes():
    """Degrade rather than refuse: the standard gate is where parity is
    enforced, not the transport."""
    pubs = publish(RecordingSession(), bodies={"es": "<p>solo</p>"},
                   titles={"es": "Solo"}, slugs={"es": "solo"})
    assert set(pubs) == {"es"}
    assert not pubs["es"].metadata["translation_url"]


# ── routing ──────────────────────────────────────────────────────────────────


def test_router_publishes_a_pair_when_the_copy_has_two_languages(monkeypatch, tmp_path):
    """Producing one post from bilingual copy ships half the deliverable."""
    from pcip.graph.store import KnowledgeGraph
    from pcip.licensing import LicensePolicy
    from pcip.models import Asset, Channel, EdgeKind, NodeKind
    from pcip.publish.router import PublishRouter

    g = KnowledgeGraph(":memory:")
    hero = tmp_path / "hero.png"
    hero.write_bytes(b"\x89PNG fake")
    asset = Asset(id="out_1", name="Deliverable", kind="image",
                  local_path=str(hero),
                  license=LicensePolicy.canva_export_license(pro=True),
                  metadata={"via_export": True, "alt_texts": ["a"]})
    g.upsert_node("out_1", NodeKind.OUTPUT, asset.name, asset.to_dict())

    body = ("<h2>A</h2><p>" + ("palabra " * 700) + "</p><h2>B</h2><p>x</p>"
            "<h2>C</h2><p>y</p>"
            f"<p>{PH.NAP_NAME} | {PH.NAP_STREET}, {PH.NAP_CITY}, {PH.NAP_STATE} "
            f"{PH.NAP_ZIP} | {PH.NAP_PHONE_DISPLAY} | {PH.SITE}</p>"
            f"<p>{PH.PHYSICIAN}, {PH.FL_LICENSE}. {PH.NEAR_ME_ES}.</p>")
    g.upsert_node("run_1", NodeKind.PIPELINE_RUN, "patient_education", {
        "id": "run_1", "status": "done", "steps": [],
        "context": {"copy_fields": {
            "titles": {"es": "Título", "en": "Title"},
            "bodies": {"es": body, "en": body},
            "meta_title": f"Prevención en {PH.GEO_PHRASE}",
            "meta_description": "Descripción.",
            "faq": [{"q": "a", "a": "b"}, {"q": "c", "a": "d"}, {"q": "e", "a": "f"}],
            "alt_texts_by_language": {"es": "alt es", "en": "alt en"},
        }},
    })
    g.add_edge("run_1", EdgeKind.PRODUCED, "out_1")

    router = PublishRouter(cfg(), g)
    session = RecordingSession()
    # Capture the real __init__ before patching, or the replacement calls
    # itself forever.
    real_init = WordPressPublisher.__init__
    monkeypatch.setattr(
        "pcip.connectors.wordpress.WordPressPublisher.__init__",
        lambda self, config, **kw: real_init(self, config, session=session),
    )
    pub = router.publish("out_1", Channel.WORDPRESS, live=True)

    assert set(pub.metadata["pair"]) == {"es", "en"}
    # Both are in the distribution record, not just the one returned.
    assert len(router.where_did_it_go("out_1")) == 2


def test_scheduling_a_pair_is_refused_rather_than_half_done():
    """A partial schedule would publish one language early."""
    from pcip.graph.store import KnowledgeGraph
    from pcip.publish.router import PublishError, PublishRouter

    router = PublishRouter(cfg(), KnowledgeGraph(":memory:"))
    with pytest.raises(PublishError) as exc:
        router._publish_bilingual(
            None, "out_1", {}, {"es": "a", "en": "b"}, {},
            live=True, schedule_at="2026-10-01T09:00:00Z",
        )
    assert "one language early" in str(exc.value)
