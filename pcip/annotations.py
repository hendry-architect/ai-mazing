"""Reviewer annotations in generated copy.

Copy generation is instructed to mark anything needing clinician sign-off with
``[MEDICAL-REVIEW]``. Those markers are addressed to a reviewer, not to a
patient, so they drive the review gate and must never survive into anything a
reader sees.

Both halves of that were wrong before this module existed: detection tested for
the bare literal ``[MEDICAL-REVIEW]`` while the model actually emits
``[MEDICAL-REVIEW: ...]`` with the reason inline, so the flag never fired on
real copy; and nothing stripped the markers on the way out, so a note written
to a clinician would have been published to patients.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Matches the bare marker and the annotated form, across lines, non-greedy so
# two annotations in one document do not merge into one.
ANNOTATION_RE = re.compile(r"\[MEDICAL-REVIEW\b[^\]]*\]", re.IGNORECASE | re.DOTALL)


def has_review_annotations(text: str) -> bool:
    """Whether the copy carries any clinician-review marker."""
    return bool(text) and bool(ANNOTATION_RE.search(text))


def find_review_annotations(text: str) -> List[str]:
    """Every annotation, verbatim — for the audit trail and the reviewer's view."""
    return ANNOTATION_RE.findall(text or "")


def strip_review_annotations(text: str) -> Tuple[str, List[str]]:
    """Remove reviewer annotations from reader-facing copy.

    Returns the cleaned text and the annotations removed, so a publish can
    record what was taken out instead of discarding it silently. Whitespace and
    empty paragraphs left behind by a removed annotation are tidied, since an
    annotation is often the only content of its own paragraph.
    """
    found = find_review_annotations(text)
    if not found:
        return text, []
    clean = ANNOTATION_RE.sub("", text)
    clean = re.sub(r"<p>\s*</p>", "", clean)        # paragraph left empty
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = re.sub(r"\s+([.,;:!?])", r"\1", clean)  # space stranded before punctuation
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip(), found
