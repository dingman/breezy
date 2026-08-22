"""Tests for breezy.normalize.classify.

THE CENTRAL TRAP: both the preliminary and final CLI issuances read
"...THE <SITE> CLIMATE SUMMARY FOR <DATE>...". The discriminator is the
presence/absence of the "VALID TODAY AS OF 0400 PM LOCAL TIME." line --
never issuanceTime, never REPORT-vs-SUMMARY wording.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.normalize.classify import (
    ClassificationError,
    classify_issuance,
    has_correction_evidence,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name / "product.txt").read_text()


def test_preliminary_cli_is_not_settlement_grade() -> None:
    """The two-issuance trap, pinned against the real fixture pair."""
    preliminary_text = _load("nyc_preliminary_2026-08-21")
    final_text = _load("nyc_final_2026-08-21")

    assert classify_issuance(preliminary_text) == "PRELIMINARY"
    assert classify_issuance(final_text) == "FINAL"


def test_both_issuances_use_identical_climate_summary_headline_wording() -> None:
    """Confirms the corrected discriminator: REPORT-vs-SUMMARY wording is NOT
    the signal (that old rule was empirically wrong). Both issuances use
    the same 'CLIMATE SUMMARY' headline; only the VALID TODAY line differs.
    """
    preliminary_text = _load("nyc_preliminary_2026-08-21")
    final_text = _load("nyc_final_2026-08-21")

    assert "CLIMATE SUMMARY FOR AUGUST 21 2026" in preliminary_text
    assert "CLIMATE SUMMARY FOR AUGUST 21 2026" in final_text


def test_classify_issuance_final_when_valid_today_line_absent() -> None:
    text = "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\nno marker line here\n"
    assert classify_issuance(text) == "FINAL"


def test_classify_issuance_preliminary_when_valid_today_line_present() -> None:
    text = (
        "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        "VALID TODAY AS OF 0400 PM LOCAL TIME.\n"
    )
    assert classify_issuance(text) == "PRELIMINARY"


def test_classify_issuance_rejects_empty_text() -> None:
    with pytest.raises(ClassificationError):
        classify_issuance("")

    with pytest.raises(ClassificationError):
        classify_issuance("   \n  ")


def test_correction_evidence_is_detected() -> None:
    correction_text = _load("nyc_correction_synthetic_2026-08-21")
    clean_text = _load("nyc_final_2026-08-21")

    assert has_correction_evidence(correction_text) is True
    assert has_correction_evidence(clean_text) is False


@pytest.mark.parametrize("marker", ["CCA", "CCB", "CORRECTED", "CORRECTION"])
def test_correction_evidence_detects_each_marker(marker: str) -> None:
    assert has_correction_evidence(f"...some text {marker} more text...") is True


def test_correction_evidence_false_for_empty_text() -> None:
    assert has_correction_evidence("") is False


@pytest.mark.parametrize(
    "phrase",
    [
        "CORRECTIONS TO THE CLIMATE SUMMARY FOLLOW",
        "...CORRECTIONS...",
        "THE FOLLOWING CORRECTIONS APPLY",
    ],
)
def test_correction_evidence_detects_the_plural_spelling(phrase: str) -> None:
    """`\\bCORRECTED\\b|\\bCORRECTION\\b` did not match CORRECTIONS: `\\b`
    after the singular requires a non-word character, and the trailing `S`
    is a word character, so the plural slipped through entirely.

    The whole-text superset behaviour here is deliberate and stays. While
    this flag is ADVISORY, a false positive costs an operator a few seconds
    dismissing an alert; a false negative silently degrades the audit trail
    that has to explain a settlement discrepancy after the fact. Catch
    more, not less.
    """
    assert has_correction_evidence(phrase) is True


def test_correction_evidence_still_ignores_unrelated_words() -> None:
    """Widening to `CORRECTIONS?` must not widen to arbitrary prefixes:
    CORRECTIONAL and CORRECTIVE are not correction evidence.
    """
    assert has_correction_evidence("CORRECTIONAL FACILITY") is False
    assert has_correction_evidence("CORRECTIVE ACTION") is False
