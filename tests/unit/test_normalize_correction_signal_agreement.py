"""The two correction signals must agree on the ALPHABET.

Breezy answers "is this product a correction?" along two different paths:

  POSITIONAL  `cli_parse.CliStructuralHeader.is_correction_bbb` -- the WMO
              BBB indicator on line 2 of the abbreviated heading, already
              shape-validated by the structural allowlist.
  FREE TEXT   `classify.has_correction_evidence` -- a deliberate superset
              scan over the whole product body, advisory, feeding the
              audit trail.

They are allowed to differ in COVERAGE: the free-text path also catches
CORRECTED/CORRECTION wording carried in a body that has no BBB token at
all, and that superset behaviour is a reviewed, deliberate decision (see
`test_free_text_superset_is_preserved`).

They are NOT allowed to differ on the ALPHABET. Both were asked the same
question -- "does `CCx` mean correction?" -- and answered with different
letter ranges: `CC[AB]` in free text, `CC[A-Z]` positionally. Two signals
for one concept disagreeing about which letters count is a contradiction
waiting to be discovered at the worst possible moment, i.e. by whoever
wires either one into `revision_seq` assignment.

Corrections run CCA, CCB, CCC, ... and **a third correction is the
instance most likely to land after settlement has already happened** --
exactly the case where the audit trail has to be right. Missing it is the
expensive direction; a false positive costs an operator a few seconds
dismissing an alert.

This suite exists so the two paths cannot be widened or narrowed
independently ever again.
"""

from __future__ import annotations

import string
from pathlib import Path

import pytest

from breezy.normalize.classify import has_correction_evidence
from breezy.normalize.cli_parse import check_structural_allowlist

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"

_WMO_HEADING = "CDUS41 KOKX 220626"

ALL_CORRECTION_BBB = [f"CC{letter}" for letter in string.ascii_uppercase]
"""CCA through CCZ -- the whole correction series, not just the first two."""

NON_CORRECTION_BBB = ["RRA", "RRB", "AAA", "AAB", "PAA", "PZZ"]
"""Retransmissions, amendments and message segments. None is a correction."""


def _with_bbb(bbb: str | None) -> str:
    """The real NYC final fixture, re-headed with (or without) a BBB token.

    The fixture body carries no CORRECTED/CORRECTION wording and no
    `CC[A-Z]`-shaped token of its own (verified against all eight captured
    fixtures), so the BBB indicator is the ONLY correction evidence in the
    text. That isolation is what makes this a clean test of the alphabet
    rather than of the free-text superset.
    """
    text = (FIXTURES_DIR / "nyc_final_2026-08-21" / "product.txt").read_text()
    assert _WMO_HEADING in text
    replacement = _WMO_HEADING if bbb is None else f"{_WMO_HEADING} {bbb}"
    return text.replace(_WMO_HEADING, replacement, 1)


def _both_verdicts(bbb: str | None) -> tuple[bool, bool]:
    """(positional verdict, free-text verdict) for one BBB indicator."""
    text = _with_bbb(bbb)
    positional = check_structural_allowlist(text, cli_location="NYC").is_correction_bbb
    free_text = has_correction_evidence(text)
    return positional, free_text


@pytest.mark.parametrize("bbb", ALL_CORRECTION_BBB)
def test_both_signals_call_every_cc_letter_a_correction(bbb: str) -> None:
    """CCA..CCZ: both paths must say True.

    Before this suite, CCC through CCZ were a correction positionally and
    NOT a correction in free text -- so a third correction to an
    already-settled climate day raised the supersession signal while
    leaving no trace in the audit record meant to explain it.
    """
    positional, free_text = _both_verdicts(bbb)

    assert positional is True, f"{bbb} should be a correction positionally"
    assert free_text is True, f"{bbb} should be correction evidence in free text"


@pytest.mark.parametrize("bbb", NON_CORRECTION_BBB)
def test_neither_signal_calls_a_non_correction_indicator_a_correction(bbb: str) -> None:
    """NEGATIVE CONTROL. Widening the alphabet must not widen it to the rest
    of the BBB space: a delayed retransmission (RRx), an amendment (AAx) and
    a message segment (Pxx) are not corrections on either path.
    """
    positional, free_text = _both_verdicts(bbb)

    assert positional is False, f"{bbb} is not a correction"
    assert free_text is False, f"{bbb} is not correction evidence"


def test_absent_bbb_is_a_correction_on_neither_path() -> None:
    """NEGATIVE CONTROL: the unmodified real final, with no BBB at all."""
    assert _both_verdicts(None) == (False, False)


@pytest.mark.parametrize("bbb", ALL_CORRECTION_BBB + NON_CORRECTION_BBB)
def test_the_two_signals_agree_on_every_bbb_indicator(bbb: str) -> None:
    """THE INVARIANT. Whatever the alphabet is, both paths use the same one.

    If this fails, one of `classify._CORRECTION_RE` or
    `cli_parse._CORRECTION_BBB_RE` was changed without the other.
    """
    positional, free_text = _both_verdicts(bbb)

    assert positional == free_text, (
        f"the positional and free-text correction signals disagree about {bbb!r} "
        f"(positional={positional}, free_text={free_text}). These two answer the "
        "same question and must share one alphabet; change both or neither."
    )


def test_the_agreement_corpus_contains_both_verdicts() -> None:
    """Guard against a vacuous suite: `test_..._agree_on_every_bbb_indicator`
    would pass trivially if every case were False (or every case True). Prove
    the corpus actually exercises both outcomes.
    """
    verdicts = {_both_verdicts(bbb)[0] for bbb in ALL_CORRECTION_BBB + NON_CORRECTION_BBB}

    assert verdicts == {True, False}


@pytest.mark.parametrize(
    "text",
    [
        "XCCCX",
        "CCCA",
        "ACCC",
        "CCC072",
        "PRECCB",
    ],
)
def test_a_cc_sequence_inside_a_longer_token_is_not_correction_evidence(text: str) -> None:
    """NEGATIVE CONTROL for the widened free-text pattern. The word-boundary
    anchors stay: a bare `CCC` embedded in a longer token must not match, or
    the advisory flag becomes noise instead of signal.
    """
    assert has_correction_evidence(text) is False


def test_free_text_superset_is_preserved() -> None:
    """The agreement claim is about the ALPHABET only, not about coverage.

    A body carrying CORRECTED wording but no BBB token is correction
    evidence in free text and NOT a positional correction. That divergence
    is the reviewed superset decision and must survive -- do not "fix" it by
    forcing the two paths to agree in general.
    """
    text = _with_bbb(None).replace("CLIMATE REPORT", "CLIMATE REPORT...CORRECTED", 1)

    positional = check_structural_allowlist(text, cli_location="NYC").is_correction_bbb
    free_text = has_correction_evidence(text)

    assert positional is False
    assert free_text is True


def test_no_real_captured_product_gains_a_false_positive() -> None:
    """Widening `CC[AB]` -> `CC[A-Z]` must not start flagging genuine
    products. Every captured fixture except the synthetic CCA correction
    must remain free of correction evidence.
    """
    for directory in sorted(FIXTURES_DIR.iterdir()):
        text = (directory / "product.txt").read_text()
        expected = directory.name == "nyc_correction_synthetic_2026-08-21"

        assert has_correction_evidence(text) is expected, (
            f"{directory.name} changed correction verdict under the widened pattern"
        )
