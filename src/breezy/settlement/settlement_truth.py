"""Settlement-grade truth predicate, ported into `src/` (SCORER_TALLY_BCA_
BRIEF_2026-09-04.md item 6c, converged review item 2).

`is_settlement_grade` / `final_tmax_f` are ported verbatim (same three
conditions, same reasoning) from
`scripts/analysis/cli_basis_offer_gate_settlement.py:147-180`
(`is_settlement_grade` / `settlement_outcome`). The script is
script-side-only and therefore not importable from `src/` -- this module is
the single `src/`-side implementation of the predicate; the script keeps its
own copy, still pinned by its own tests
(`tests/unit/test_cli_basis_offer_gate_settlement.py`). Do not delete either
copy and do not let them diverge without updating both.

Deliberately narrower than the script's `settlement_outcome`: that function
also encodes an OPEN-TAIL `>= strike_f` comparison, which is only one of the
two bucket shapes the settlement scorer must score (closed-both-ends rungs
are the other -- see `WeatherBucketFacts.contains`,
`src/breezy/domain/weather_bucket_facts.py:64-73`). `trial_scorer.py` composes
`final_tmax_f` from this module with `WeatherBucketFacts.contains` directly,
so a second settlement predicate is never introduced here.
"""

from __future__ import annotations

from breezy.domain.nws_climate_day import NwsClimateDay

__all__ = ["final_tmax_f", "is_settlement_grade"]


def is_settlement_grade(record: NwsClimateDay | None) -> bool:
    """A FINAL, non-superseded record with a real (non-sentinel) `tmax_f`.

    All three conditions are required: a corrected-away final
    (`is_superseded`) is not the answer the venue paid on; a sentinel/missing
    `tmax_f` on an otherwise-FINAL record cannot be compared to a strike at
    all. Anything short of all three means "we cannot honestly say" -- callers
    must treat that as PENDING/refused, never a fabricated outcome.
    """
    return (
        record is not None
        and record.is_final
        and not record.is_superseded
        and record.tmax_f is not None
    )


def final_tmax_f(record: NwsClimateDay | None) -> int | None:
    """The settlement-grade `tmax_f`, or `None` if `record` is not grade.

    `None` covers every case where the answer is not yet knowable: no record
    at all, a preliminary-only record, a corrected-away record, or a FINAL
    whose `tmax_f` is itself a sentinel/missing reading. Callers must never
    treat `None` as a loss or a win.
    """
    if not is_settlement_grade(record):
        return None
    assert record is not None and record.tmax_f is not None  # narrowed above
    return record.tmax_f
