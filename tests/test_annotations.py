"""Reviewer annotations never reach a reader.

Copy generation marks anything needing clinician sign-off with
[MEDICAL-REVIEW]. Those notes are addressed to a clinician; publishing one to a
patient would be both confusing and a governance failure.
"""

import json

import pytest

from pcip.annotations import (
    find_review_annotations,
    has_review_annotations,
    strip_review_annotations,
)


BARE = "Take your medicine. [MEDICAL-REVIEW] Call us."
ANNOTATED = (
    "<p>Walk daily.</p><p>Ask your team. "
    "[MEDICAL-REVIEW: any medication change or specific A1C target must be "
    "approved by the treating physician]</p>"
)


def test_detects_the_annotated_form_the_model_actually_emits():
    """The original check tested for the bare literal and so never fired."""
    assert has_review_annotations(ANNOTATED)
    assert has_review_annotations(BARE)
    assert not has_review_annotations("<p>Plain patient copy.</p>")
    assert not has_review_annotations("")


def test_detects_across_line_breaks():
    assert has_review_annotations("text [MEDICAL-REVIEW: reason\nspanning lines] more")


def test_strips_the_note_and_reports_it():
    clean, removed = strip_review_annotations(ANNOTATED)
    assert "MEDICAL-REVIEW" not in clean
    assert "A1C" not in clean
    assert len(removed) == 1
    assert "treating physician" in removed[0]
    assert "Walk daily." in clean          # patient content survives


def test_two_notes_do_not_merge_into_one():
    clean, removed = strip_review_annotations(
        "a [MEDICAL-REVIEW: one] b [MEDICAL-REVIEW: two] c"
    )
    assert len(removed) == 2
    assert "b" in clean and "MEDICAL-REVIEW" not in clean


def test_leaves_no_empty_paragraph_or_stranded_space():
    clean, _ = strip_review_annotations("<p>Kept.</p><p>[MEDICAL-REVIEW: note]</p>")
    assert "<p></p>" not in clean
    assert clean == "<p>Kept.</p>"
    clean2, _ = strip_review_annotations("Call the clinic [MEDICAL-REVIEW: x].")
    assert clean2 == "Call the clinic."


def test_clean_copy_is_returned_untouched():
    body = "<p>Nothing to strip.</p>"
    clean, removed = strip_review_annotations(body)
    assert clean == body and removed == []


def test_the_real_reviewed_copy_carries_a_note_that_must_not_ship():
    """Regression guard tied to the actual deliverable, not a synthetic string."""
    body = json.loads(
        open("examples/copy-diabetes-es.json", encoding="utf-8").read()
    )["body_html"]
    assert has_review_annotations(body)
    clean, removed = strip_review_annotations(body)
    assert removed and "MEDICAL-REVIEW" not in clean
    assert "PassQual" in clean
