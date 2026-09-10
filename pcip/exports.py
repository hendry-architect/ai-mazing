"""Choosing which downloaded file belongs to a run.

The helper scripts used to take the newest PDF in ~/Downloads. That folder is
shared with the rest of someone's life, and it once selected
"MASTER APPEAL - Ambetter (COM) - FOR FILING.docx.pdf" — an unrelated
confidential document — as the media for a public patient-education article.
Nothing published it, because the brand standard rejects a PDF as a hero
image, but the only thing standing between a private document and a public
article was a check that existed for a different reason.

So: match on the deliverable's own words, prefer the file type the article
actually needs, and when nothing matches, say so instead of guessing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

# The hero must be an image; a PDF cannot be a featured image.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
DOCUMENT_SUFFIXES = (".pdf",)

_STOPWORDS = {
    "para", "your", "with", "from", "the", "and", "los", "las", "una", "del",
    "que", "por", "sus", "care", "final", "copy", "draft", "export", "design",
}


def _words(text: str) -> set:
    """Comparable words: accent-folded, lowercased, short and generic dropped."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    return {
        w for w in re.split(r"[^a-z0-9]+", folded)
        if len(w) > 3 and w not in _STOPWORDS
    }


@dataclass
class Candidate:
    path: Path
    score: int
    is_image: bool

    @property
    def matches(self) -> bool:
        """Whether this file shares any distinctive word with the deliverable.

        Zero overlap does not mean the file is wrong — it means we cannot tell,
        which is the same thing as far as attaching it automatically goes.
        """
        return self.score > 0


def find_export_candidates(
    title: str,
    directory: Path | str,
    *,
    prefer_images: bool = True,
    suffixes: Optional[Sequence[str]] = None,
) -> List[Candidate]:
    """Files in ``directory`` that plausibly belong to ``title``, best first.

    Ranked by shared words with the title, then by modification time. Image
    files sort ahead of documents when ``prefer_images`` is set, because that
    is what an article needs and a document of the same name is usually the
    printable companion rather than the hero.
    """
    folder = Path(directory).expanduser()
    if not folder.is_dir():
        return []

    allowed = tuple(s.lower() for s in (
        suffixes if suffixes is not None
        else (IMAGE_SUFFIXES + DOCUMENT_SUFFIXES)
    ))
    wanted = _words(title)

    out: List[Candidate] = []
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        is_image = path.suffix.lower() in IMAGE_SUFFIXES
        out.append(Candidate(
            path=path,
            score=len(wanted & _words(path.stem)),
            is_image=is_image,
        ))

    out.sort(
        key=lambda c: (
            c.score,
            (1 if c.is_image else 0) if prefer_images else 0,
            c.path.stat().st_mtime,
        ),
        reverse=True,
    )
    return out


def best_export(
    title: str, directory: Path | str, **kwargs
) -> Optional[Candidate]:
    """The single best candidate, or None when nothing plausibly matches.

    Returns None rather than a low-confidence guess: attaching the wrong file
    to a run is silent, and the run then carries it forward as the deliverable.
    """
    for candidate in find_export_candidates(title, directory, **kwargs):
        if candidate.matches:
            return candidate
    return None
