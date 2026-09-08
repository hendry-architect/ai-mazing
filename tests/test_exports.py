"""Choosing which downloaded file belongs to a run.

The helper scripts took the newest PDF in ~/Downloads. That folder holds the
rest of someone's life, and the selection landed on a confidential patient
appeal for a public patient-education article. Nothing published it — the
brand standard rejects a PDF hero — but the only thing between a private
document and a public article was a check that existed for another reason.
"""

import time

import pytest

from pcip.exports import best_export, find_export_candidates


TITLE = "Prevención de la Diabetes — Hábitos Diarios"


def make(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_bytes(b"x")
        time.sleep(0.01)          # distinct mtimes
    return tmp_path


def test_the_confidential_document_is_not_selected(tmp_path):
    """The exact file that was wrongly attached."""
    make(tmp_path,
         "Prevención de la Diabetes — Hábitos Diarios.png",
         "MASTER APPEAL - Ambetter (COM) - FOR FILING.docx.pdf")
    best = best_export(TITLE, tmp_path)
    assert best is not None
    assert "APPEAL" not in best.path.name
    assert best.path.suffix == ".png"


def test_an_unrelated_newer_file_does_not_win(tmp_path):
    """Newest-file-wins is what caused this; recency is only a tiebreak."""
    make(tmp_path,
         "Prevención de la Diabetes — Hábitos Diarios.png",
         "bank-statement-september.pdf")     # newer
    best = best_export(TITLE, tmp_path)
    assert best.path.stem.startswith("Prevención")


def test_nothing_matching_returns_none_rather_than_a_guess(tmp_path):
    """Attaching the wrong file is silent, and the run carries it forward."""
    make(tmp_path, "tax-return.pdf", "holiday-photo.png")
    assert best_export(TITLE, tmp_path) is None


def test_accents_and_case_do_not_break_the_match(tmp_path):
    make(tmp_path, "prevencion-de-la-diabetes-habitos-diarios.png")
    assert best_export(TITLE, tmp_path) is not None


def test_an_image_outranks_a_document_of_the_same_name(tmp_path):
    """Both belong to the deliverable; the article needs the image."""
    make(tmp_path,
         "Prevención de la Diabetes — Hábitos Diarios.pdf",
         "Prevención de la Diabetes — Hábitos Diarios.png")
    best = best_export(TITLE, tmp_path)
    assert best.is_image


def test_generic_words_alone_are_not_a_match(tmp_path):
    """"final copy" shares words with everything and means nothing."""
    make(tmp_path, "final copy draft export.png")
    assert best_export("Final copy for export", tmp_path) is None


def test_a_missing_folder_is_not_an_error(tmp_path):
    assert find_export_candidates(TITLE, tmp_path / "nope") == []


def test_documents_can_be_requested_explicitly(tmp_path):
    """The printable handout is a real deliverable, just not the hero."""
    make(tmp_path, "Prevención de la Diabetes — Hábitos Diarios.pdf")
    best = best_export(TITLE, tmp_path, suffixes=(".pdf",))
    assert best is not None and best.path.suffix == ".pdf"
