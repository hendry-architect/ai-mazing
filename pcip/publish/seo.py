"""SEO surface for a published article: schema, meta fields, hreflang.

Three things the PassQual Health standard requires that WordPress will not
produce on its own.

**JSON-LD** is embedded in the post body rather than injected into the document
head, because PCIP publishes through the REST API and has no access to the
theme. A script block in the content is valid — Google reads structured data
wherever it appears in the document — and it survives a theme change, which a
head injection would not.

**Meta title and description** are written to both Yoast and Rank Math key
sets. Only one plugin is installed, and the other's keys are inert rows; that
is cheaper than detecting the plugin and being wrong. Both are also mirrored
into the core excerpt, which every theme reads and no plugin owns.

**hreflang** proper belongs in the head and needs Polylang to emit it. What
this module contributes is the visible half — a cross-link between the two
language versions — which works with no plugin at all and is what a reader
actually uses.
"""

from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional

from pcip.standards import PH


# Yoast and Rank Math key names for the same two values.
SEO_META_KEYS = {
    "title": ("_yoast_wpseo_title", "rank_math_title"),
    "description": ("_yoast_wpseo_metadesc", "rank_math_description"),
    "focus_keyword": ("_yoast_wpseo_focuskw", "rank_math_focus_keyword"),
}


def seo_meta_fields(
    meta_title: str = "", meta_description: str = "", focus_keyword: str = ""
) -> Dict[str, str]:
    """Post meta for whichever SEO plugin is installed.

    Writing an unregistered meta key over REST is ignored rather than fatal, so
    sending both sets costs nothing and removes a detection step that could be
    wrong.
    """
    out: Dict[str, str] = {}
    for value, keys in (
        (meta_title, SEO_META_KEYS["title"]),
        (meta_description, SEO_META_KEYS["description"]),
        (focus_keyword, SEO_META_KEYS["focus_keyword"]),
    ):
        if value:
            for key in keys:
                out[key] = value
    return out


def _organization() -> Dict[str, Any]:
    return {
        "@type": "MedicalClinic",
        "name": PH.NAP_NAME,
        "url": PH.SITE,
        "telephone": PH.NAP_PHONE_E164,
        "address": {
            "@type": "PostalAddress",
            "streetAddress": PH.NAP_STREET,
            "addressLocality": PH.NAP_CITY,
            "addressRegion": PH.NAP_STATE,
            "postalCode": PH.NAP_ZIP,
            "addressCountry": "US",
        },
        "identifier": [
            {"@type": "PropertyValue", "name": "NPI", "value": PH.NPI_ORG},
        ],
    }


def _physician() -> Dict[str, Any]:
    return {
        "@type": "Physician",
        "name": PH.PHYSICIAN,
        "medicalSpecialty": "PrimaryCare",
        "identifier": [
            {"@type": "PropertyValue", "name": "NPI", "value": PH.NPI_INDIVIDUAL},
            {"@type": "PropertyValue", "name": "FL license",
             "value": PH.FL_LICENSE},
        ],
        "worksFor": {"@type": "MedicalClinic", "name": PH.NAP_NAME},
    }


def build_jsonld(
    *,
    title: str,
    description: str,
    url: str,
    language: str,
    faq: Optional[List[Dict[str, str]]] = None,
    image_url: str = "",
    translation_url: str = "",
) -> str:
    """A single @graph carrying MedicalWebPage, the clinic, the physician and
    any FAQ — the four types the registry names.

    One graph rather than several blocks so the nodes can reference each other,
    which is what lets a search engine attribute the page to the practice
    rather than treating them as unrelated facts.
    """
    page: Dict[str, Any] = {
        "@type": "MedicalWebPage",
        "name": title,
        "description": description,
        "inLanguage": language,
        "publisher": {"@type": "MedicalClinic", "name": PH.NAP_NAME},
        "about": {"@type": "MedicalCondition", "name": title},
        "reviewedBy": {"@type": "Physician", "name": PH.PHYSICIAN},
    }
    if url:
        page["url"] = url
        page["mainEntityOfPage"] = url
    if image_url:
        page["image"] = image_url
    if translation_url:
        page["workTranslation"] = {
            "@type": "MedicalWebPage", "url": translation_url,
        }

    graph: List[Dict[str, Any]] = [page, _organization(), _physician()]

    items = [f for f in (faq or []) if f.get("q") and f.get("a")]
    if items:
        graph.append({
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": f["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": f["a"]},
                }
                for f in items
            ],
        })

    payload = {"@context": "https://schema.org", "@graph": graph}
    return (
        '<script type="application/ld+json">'
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "</script>"
    )


def faq_html(faq: List[Dict[str, str]], language: str = "es") -> str:
    """The FAQ as readable markup.

    The schema block alone gives a search engine the answers and the reader
    nothing. Both surfaces get them.
    """
    items = [f for f in (faq or []) if f.get("q") and f.get("a")]
    if not items:
        return ""
    heading = "Preguntas frecuentes" if language.startswith("es") else "Frequently asked questions"
    parts = [f"<h2>{html.escape(heading)}</h2>"]
    for item in items:
        parts.append(
            f"<h3>{html.escape(item['q'])}</h3><p>{html.escape(item['a'])}</p>"
        )
    return "".join(parts)


def translation_link(url: str, language: str) -> str:
    """Visible cross-link to the other language version.

    ``language`` is the language of the LINKED article, so the label is written
    in the language the reader is being offered.
    """
    if not url:
        return ""
    if language.startswith("en"):
        label = "Read this article in English"
    else:
        label = "Leer este artículo en español"
    return (
        f'<p class="pcip-translation"><a href="{html.escape(url, quote=True)}" '
        f'hreflang="{html.escape(language[:2], quote=True)}">'
        f"{html.escape(label)}</a></p>"
    )


def nap_block(language: str = "es") -> str:
    """The NAP, printed verbatim. Never reformat this."""
    label = "Visítenos" if language.startswith("es") else "Visit us"
    return (
        f"<h2>{html.escape(label)}</h2>"
        f"<p><strong>{html.escape(PH.NAP_NAME)}</strong><br />"
        f"{html.escape(PH.NAP_STREET)}, {html.escape(PH.NAP_CITY)}, "
        f"{PH.NAP_STATE} {PH.NAP_ZIP}<br />"
        f'<a href="tel:{PH.NAP_PHONE_E164}">{html.escape(PH.NAP_PHONE_DISPLAY)}</a>'
        f' · <a href="{PH.SITE}">{html.escape(PH.SITE)}</a></p>'
    )
