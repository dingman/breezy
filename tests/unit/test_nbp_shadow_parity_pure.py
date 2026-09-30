"""RED-first tests for SL-13p's pure batch path (`nbp_shadow_parity_pure.py`).

`docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md` §12 A-5. No network,
no Nautilus, no strategy/actor import -- see `test_nbp_shadow_parity_contract.py`
for that boundary's own pin.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence

import pytest

from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import NBP_QUANTILE_VARIABLES
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Rung,
    rung_probabilities,
)
from scripts.analysis.nbp_shadow_parity_pure import (
    MIN_PRE_FREEZE_DAYS,
    PRE_FREEZE_END,
    DecisionKey,
    DepthSnapshotRow,
    InsufficientPreFreezeDaysError,
    NbpQuantileRow,
    PostFreezeTapeRefusedError,
    UnparsableRungInstrumentIdError,
    assert_minimum_pre_freeze_days,
    assert_pre_freeze_tape_day,
    diff_decision_keys,
    nominal_permit_expiry_upper_bound,
    parse_rung_instrument_id,
    permit_covers,
    permit_window_for_day,
    run_batch_parity,
)

STATION = "KMIA"
STD_UTC_OFFSET_HOURS = -5.0
CLIMATE_DAY = dt.date(2026, 9, 2)
EVAL_DAY = dt.date(2026, 9, 1)  # climate_day's D-1, in station LST
LADDER = (Rung(rung_id="i1", lo=None, hi=None),)
LADDER_BY_KEY = {(STATION, CLIMATE_DAY): LADDER}
FEE_COEFFICIENT = 0.0695
SLIPPAGE_FLOOR_PROB = 0.0
STD_OFFSET_BY_STATION = {STATION: STD_UTC_OFFSET_HOURS}


def _ns(y: int, m: int, d: int, hh: int, mm: int = 0) -> int:
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=dt.UTC).timestamp()) * 1_000_000_000


# Inside the nominal permit window opened on 2026-09-01 (LAUNCH_UTC 16:50,
# 10 h TTL) and D+1 of 2026-09-01 LST (offset -5h) is 2026-09-02.
NOW_NS = _ns(2026, 9, 1, 18, 0)

_CYCLE_NS = _ns(2026, 9, 1, 6, 0)
_AVAILABLE_AT_NS = _ns(2026, 9, 1, 7, 0)

_PERCENTILES = {
    "TXN_Q10": 68.0,
    "TXN_Q25": 71.0,
    "TXN_Q50": 75.0,
    "TXN_Q75": 79.0,
    "TXN_Q90": 82.0,
    "TXN_MEAN": 75.0,
    "TXN_SD": 3.0,
}
assert set(_PERCENTILES) == set(NBP_QUANTILE_VARIABLES)


def _nbp_rows() -> tuple[NbpQuantileRow, ...]:
    return tuple(
        NbpQuantileRow(
            station=STATION,
            variable=variable,
            cycle_runtime_ns=_CYCLE_NS,
            value_f=value,
            available_at_ns=_AVAILABLE_AT_NS,
            climate_day=CLIMATE_DAY,
        )
        for variable, value in _PERCENTILES.items()
    )


def _depth_snapshot(*, ts_ns: int = NOW_NS, price: float = 0.10) -> DepthSnapshotRow:
    return DepthSnapshotRow(
        instrument_id=f"{STATION}-{CLIMATE_DAY.isoformat()}-i1.POLY_US",
        ts_ns=ts_ns,
        best_ask_price=price,
        best_ask_size=25.0,
    )


def _artefact() -> CalibrationArtefact:
    return CalibrationArtefact(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        emos=EmosParams(a=0.0, gamma=0.0, delta=1.0),
    )


def _bounds_provider(
    *, cdf: Callable[[float], float], ladder: Sequence[Rung], rung_id: str,
) -> RungBounds:
    p_hat = rung_probabilities(cdf, ladder)[rung_id]
    return RungBounds(p_hat=p_hat, p_lower=max(0.0, p_hat - 0.03), p_upper=min(1.0, p_hat + 0.03))


def _run(depth_snapshots: tuple[DepthSnapshotRow, ...]) -> tuple[DecisionKey, ...]:
    return run_batch_parity(
        depth_snapshots=depth_snapshots,
        nbp_rows=_nbp_rows(),
        ladder_by_key=LADDER_BY_KEY,
        artefact=_artefact(),
        ladder_cfg=LadderEvConfig(),
        bounds_provider=_bounds_provider,
        fee_coefficient=FEE_COEFFICIENT,
        slippage_floor_prob=SLIPPAGE_FLOOR_PROB,
        std_utc_offset_hours_by_station=STD_OFFSET_BY_STATION,
    )


# ---------------------------------------------------------------------------
# RED 1: identical inputs give 0 mismatches.
# ---------------------------------------------------------------------------


def test_identical_inputs_give_zero_mismatches() -> None:
    snapshots = (_depth_snapshot(),)

    first = _run(snapshots)
    second = _run(snapshots)

    report = diff_decision_keys(first, second)

    assert report.n_mismatches == 0
    assert report.n_live_only == 0
    assert report.n_batch_only == 0
    assert report.n_matched == report.n_live == report.n_batch
    # The single-rung fixture is deliberately profitable at every snapshot
    # (see the module docstring): confirm this run actually exercises a Take,
    # not just the vacuously-equal empty set.
    assert first[0].kind == "Take"


# ---------------------------------------------------------------------------
# RED 2: an injected divergence (a dropped snapshot -- a stand-in for a
# batch-path bug that silently skips a decision) is detected.
# ---------------------------------------------------------------------------


def test_an_injected_divergence_is_detected() -> None:
    early = _depth_snapshot(ts_ns=NOW_NS)
    late = _depth_snapshot(ts_ns=NOW_NS + 60_000_000_000, price=0.11)

    full = _run((early, late))
    missing_late = _run((early,))

    report = diff_decision_keys(full, missing_late)

    assert report.n_mismatches > 0
    assert report.n_live_only == 1
    assert report.live_only[0].ts_ns == late.ts_ns


# ---------------------------------------------------------------------------
# RED 3: a tape day after 2026-09-25 is refused.
# ---------------------------------------------------------------------------


def test_a_tape_day_after_the_freeze_cutoff_is_refused() -> None:
    with pytest.raises(PostFreezeTapeRefusedError):
        assert_pre_freeze_tape_day(PRE_FREEZE_END + dt.timedelta(days=1))


def test_run_batch_parity_refuses_a_post_freeze_instrument() -> None:
    post_freeze_day = PRE_FREEZE_END + dt.timedelta(days=1)
    snapshot = DepthSnapshotRow(
        instrument_id=f"{STATION}-{post_freeze_day.isoformat()}-i1.POLY_US",
        ts_ns=NOW_NS,
        best_ask_price=0.10,
        best_ask_size=25.0,
    )

    with pytest.raises(PostFreezeTapeRefusedError):
        _run((snapshot,))


def test_fewer_than_the_minimum_pre_freeze_days_is_refused() -> None:
    with pytest.raises(InsufficientPreFreezeDaysError):
        assert_minimum_pre_freeze_days([CLIMATE_DAY])


def test_the_minimum_pre_freeze_days_boundary_passes() -> None:
    days = [CLIMATE_DAY + dt.timedelta(days=i) for i in range(MIN_PRE_FREEZE_DAYS)]
    assert_minimum_pre_freeze_days(days)  # does not raise


# ---------------------------------------------------------------------------
# RED 5: the report carries no P&L, outcome, or ev-aggregate field.
# ---------------------------------------------------------------------------


def test_the_report_carries_mismatch_counts_only() -> None:
    report = diff_decision_keys([], [])

    counts = report.to_counts_dict()

    assert set(counts) == {
        "n_live",
        "n_batch",
        "n_matched",
        "n_live_only",
        "n_batch_only",
        "n_numeric_mismatches",
        "n_mismatches",
    }
    forbidden_substrings = ("ev", "pnl", "p&l", "outcome", "settle", "profit", "loss")
    for field_name in counts:
        lowered = field_name.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, f"{field_name!r} looks scored (matches {forbidden!r})"


# ---------------------------------------------------------------------------
# Supporting correctness pins.
# ---------------------------------------------------------------------------


def test_rung_instrument_id_parsing() -> None:
    station, climate_day, rung_id = parse_rung_instrument_id(
        "KMIA-2026-10-01-i1.POLY_US",
    )

    assert station == "KMIA"
    assert climate_day == dt.date(2026, 10, 1)
    assert rung_id == "i1"


def test_rung_instrument_id_parsing_rejects_an_unrecognised_shape() -> None:
    with pytest.raises(UnparsableRungInstrumentIdError):
        parse_rung_instrument_id("not-a-rung-id")


@pytest.mark.parametrize(
    "now_ns",
    [
        NOW_NS,
        _ns(2026, 9, 1, 16, 49),  # just before the window opens
        _ns(2026, 9, 1, 16, 50),  # window opens
        _ns(2026, 9, 2, 2, 49),  # just before the window closes (spans midnight)
        _ns(2026, 9, 2, 2, 50),  # window closes
        _ns(2026, 9, 2, 12, 0),  # well outside
    ],
)
def test_the_one_sided_permit_workaround_matches_permit_covers(now_ns: int) -> None:
    assert permit_covers(now_ns) == (now_ns < nominal_permit_expiry_upper_bound(now_ns))


def test_permit_window_for_day_is_ten_hours_wide() -> None:
    start_ns, end_ns = permit_window_for_day(EVAL_DAY)

    assert (end_ns - start_ns) == 10 * 3_600 * 1_000_000_000
