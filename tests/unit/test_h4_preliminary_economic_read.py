"""Unit tests for the H4 preliminary economic read.

These cover the pure logic in
``scripts/analysis/h4_preliminary_economic_read.py``: venue rung parsing, the
headroom-1 entry condition, the minute-resolution running maximum, the
depth-aware ask VWAP, and the trigger-window coverage classification.

Nothing here simulates a trade. The VWAP is a PRICE measurement over a
captured ask ladder -- no fill, no position, no fee, no P&L. NautilusTrader
owns all of that.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_MDW_STD_OFFSET_HOURS = -6.0


def _load_module() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "h4_preliminary_economic_read.py"
    spec = importlib.util.spec_from_file_location("h4_preliminary_economic_read", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def h4() -> ModuleType:
    return _load_module()


# ---------------------------------------------------------------------------
# Rung parsing -- the ladder must partition the integers with no hole
# ---------------------------------------------------------------------------


def test_parse_rung_reads_the_three_venue_band_shapes(h4: ModuleType) -> None:
    low = h4.parse_rung("tc-temp-nychigh-2026-08-31-lt78f.POLYMARKET_US")
    interior = h4.parse_rung("tc-temp-nychigh-2026-08-31-gte78lt79f.POLYMARKET_US")
    high = h4.parse_rung("tc-temp-nychigh-2026-08-31-gte86f.POLYMARKET_US")

    assert (low.city, low.climate_day) == ("NYC", dt.date(2026, 8, 31))
    assert (low.lower_f, low.upper_f) == (None, 77)
    # `gte78lt79f` is the venue's spelling of the CLOSED interval [78, 79].
    assert (interior.lower_f, interior.upper_f) == (78, 79)
    assert (high.lower_f, high.upper_f) == (86, None)


def test_the_real_2026_08_31_nyc_ladder_partitions_the_integers_with_no_hole(
    h4: ModuleType,
) -> None:
    """This is the check that makes the closed-interval reading load-bearing.

    Under a half-open `[78, 79)` reading, 79 belongs to no rung and the ladder
    has a hole at every odd degree -- which would silently drop half of all
    climate days out of the measurement.
    """
    ladder = h4.parse_ladder(
        [
            "tc-temp-nychigh-2026-08-31-lt78f.POLYMARKET_US",
            "tc-temp-nychigh-2026-08-31-gte78lt79f.POLYMARKET_US",
            "tc-temp-nychigh-2026-08-31-gte80lt81f.POLYMARKET_US",
            "tc-temp-nychigh-2026-08-31-gte82lt83f.POLYMARKET_US",
            "tc-temp-nychigh-2026-08-31-gte84lt85f.POLYMARKET_US",
            "tc-temp-nychigh-2026-08-31-gte86f.POLYMARKET_US",
        ]
    )

    assert len(ladder) == 6
    for value_f in range(60, 100):
        matches = [rung for rung in ladder if rung.contains(value_f)]
        assert len(matches) == 1, f"{value_f}F matched {len(matches)} rungs, expected exactly 1"


def test_parse_rung_refuses_a_band_whose_bounds_are_not_adjacent(h4: ModuleType) -> None:
    """`gte<A>lt<B>` is only a 2°F closed rung when `B == A + 1`. If the venue
    ever renames its bands, that must be a loud failure, not a silent reread."""
    with pytest.raises(ValueError, match="adjacent"):
        h4.parse_rung("tc-temp-nychigh-2026-08-31-gte78lt83f.POLYMARKET_US")


def test_parse_rung_refuses_an_unrecognized_instrument_id(h4: ModuleType) -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        h4.parse_rung("tc-temp-nychigh-2026-08-31-between78and79f.POLYMARKET_US")


# ---------------------------------------------------------------------------
# The H4 entry condition: headroom == 1 exactly, never 0, never an open tail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("running_f", "expected_headroom"),
    [(78, 1), (79, 0)],
)
def test_headroom_on_an_interior_rung(
    h4: ModuleType, running_f: int, expected_headroom: int
) -> None:
    rung = h4.parse_rung("tc-temp-nychigh-2026-08-31-gte78lt79f.POLYMARKET_US")

    assert rung.headroom_f(running_f) == expected_headroom


def test_an_open_tail_rung_has_no_headroom_and_is_never_an_h4_candidate(
    h4: ModuleType,
) -> None:
    """`gte86f` has no ceiling, so `upper_f − R` is undefined. H4 buys a bounded
    rung; an open tail is a different instrument with a different hazard."""
    tail = h4.parse_rung("tc-temp-nychigh-2026-08-31-gte86f.POLYMARKET_US")
    low = h4.parse_rung("tc-temp-nychigh-2026-08-31-lt78f.POLYMARKET_US")

    # No ceiling at all on the high tail: headroom is genuinely undefined.
    assert tail.headroom_f(90) is None
    assert h4.is_h4_candidate(tail, 90) is False

    # The LOW tail is the subtle one. It HAS a ceiling (77), so the arithmetic
    # is well defined -- `lt78f` at R == 76 computes h == 1. It must still be
    # refused: it is an unbounded-below band many degrees wide, and the
    # climatology that produced H4's model_p conditions on 2F rungs only.
    assert low.upper_f == 77
    assert low.headroom_f(76) == 1
    assert h4.is_interior_rung(low) is False
    assert h4.is_h4_candidate(low, 76) is False, "low tail is not a 2F rung"
    assert h4.is_h4_candidate(low, 70) is False


def test_is_h4_candidate_requires_headroom_exactly_one(h4: ModuleType) -> None:
    rung = h4.parse_rung("tc-temp-nychigh-2026-08-31-gte78lt79f.POLYMARKET_US")

    assert h4.is_h4_candidate(rung, 78) is True
    assert h4.is_h4_candidate(rung, 79) is False, "h == 0 is the cell H3 was refuted on"
    # R outside the rung entirely.
    assert h4.is_h4_candidate(rung, 77) is False
    assert h4.is_h4_candidate(rung, 80) is False


def test_rung_containing_selects_the_single_rung_holding_the_running_max(
    h4: ModuleType,
) -> None:
    ladder = h4.parse_ladder(
        [
            "tc-temp-mdwhigh-2026-08-31-lt89f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte89lt90f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte91lt92f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte93lt94f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte95lt96f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte97f.POLYMARKET_US",
        ]
    )

    holding = h4.rung_containing(ladder, 90)
    assert holding is not None
    assert (holding.lower_f, holding.upper_f) == (89, 90)
    assert holding.headroom_f(90) == 0

    candidate = h4.h4_rung(ladder, 89)
    assert candidate is not None
    assert (candidate.lower_f, candidate.upper_f) == (89, 90)
    # R == 90 sits ON the ceiling: no h==1 rung exists for it.
    assert h4.h4_rung(ladder, 90) is None


# ---------------------------------------------------------------------------
# Minute-resolution R(t) -- no look-ahead
# ---------------------------------------------------------------------------


def _metar_row(*, station: str, valid: str, t_group: str) -> dict[str, str]:
    return {
        "station": station,
        "valid": valid,
        "metar": f"K{station} 010000Z AUTO 25009KT 10SM CLR 15/07 A3015 RMK AO2 {t_group}",
    }


def _t_group(tenths: int) -> str:
    sign = "1" if tenths < 0 else "0"
    return f"T{sign}{abs(tenths):03d}{sign}{abs(tenths):03d}"


def _series(h4: ModuleType, tenths_by_minute: dict[int, int]) -> Any:
    base = dt.datetime(2026, 8, 31, 18, 0, tzinfo=dt.UTC)
    rows = [
        _metar_row(
            station="MDW",
            valid=(base + dt.timedelta(minutes=minute)).strftime("%Y-%m-%d %H:%M"),
            t_group=_t_group(tenths),
        )
        for minute, tenths in sorted(tenths_by_minute.items())
    ]
    temperatures, drops = h4.metar_temperatures(
        city="MDW", rows=rows, std_utc_offset_hours=_MDW_STD_OFFSET_HOURS
    )
    assert not drops, drops
    return h4.running_max_series(temperatures)


def test_running_max_at_uses_only_observations_at_or_before_t(h4: ModuleType) -> None:
    series = _series(h4, {0: 300, 10: 320, 20: 310, 30: 350})
    base = dt.datetime(2026, 8, 31, 18, 0, tzinfo=dt.UTC)

    # 30.0C -> 86F, 32.0C -> 89.6 -> 90F, 35.0C -> 95F.
    assert h4.running_max_at(series, base) == 86
    assert h4.running_max_at(series, base + dt.timedelta(minutes=9)) == 86
    # Exactly at the observation instant it is already included.
    assert h4.running_max_at(series, base + dt.timedelta(minutes=10)) == 90
    assert h4.running_max_at(series, base + dt.timedelta(minutes=29)) == 90
    assert h4.running_max_at(series, base + dt.timedelta(minutes=30)) == 95
    # Never falls, even though the reading at +20 did.
    assert h4.running_max_at(series, base + dt.timedelta(minutes=25)) == 90


def test_running_max_at_is_none_before_the_first_observation(h4: ModuleType) -> None:
    series = _series(h4, {10: 300})
    base = dt.datetime(2026, 8, 31, 18, 0, tzinfo=dt.UTC)

    assert h4.running_max_at(series, base) is None
    assert h4.running_max_at(series, base + dt.timedelta(minutes=10)) == 86


def test_running_max_series_is_monotone_non_decreasing(h4: ModuleType) -> None:
    series = _series(h4, {minute: 300 - minute for minute in range(0, 40, 5)})

    values = [value for _, value in series]
    assert values == sorted(values)


def test_truncating_the_series_does_not_change_earlier_answers(h4: ModuleType) -> None:
    full = _series(h4, {0: 300, 10: 320, 20: 400})
    early = _series(h4, {0: 300, 10: 320})
    base = dt.datetime(2026, 8, 31, 18, 0, tzinfo=dt.UTC)

    for minute in range(20):
        at = base + dt.timedelta(minutes=minute)
        assert h4.running_max_at(full, at) == h4.running_max_at(early, at)


# ---------------------------------------------------------------------------
# Depth-aware ask VWAP -- level 0 alone is not a price you can get in size
# ---------------------------------------------------------------------------


def test_vwap_walks_the_ladder_rather_than_pricing_at_level_zero(h4: ModuleType) -> None:
    """The failure this exists to catch: 5 contracts at 0.50 backed by 300 at
    0.99 reads as cheap at level 0 and is not cheap in any real size."""
    fill = h4.vwap_for_notional(((0.50, 5.0), (0.99, 300.0)), notional=24.53)

    # 5 @ 0.50 = $2.50, then floor((24.53 - 2.50) / 0.99) = 22 @ 0.99 = $21.78.
    # 27 contracts for $24.28; a 28th would cost $25.27 and breach the notional.
    assert fill.best_ask == 0.50
    assert fill.contracts == 27
    assert fill.cost == pytest.approx(24.28, abs=1e-9)
    assert fill.vwap == pytest.approx(24.28 / 27)
    assert fill.vwap == pytest.approx(0.8993, abs=5e-5)
    assert fill.vwap > fill.best_ask, "level 0 flatters the price by 0.40"
    assert fill.depth_limited is False


def test_vwap_reports_depth_limited_when_the_ladder_runs_out(h4: ModuleType) -> None:
    fill = h4.vwap_for_notional(((0.20, 3.0),), notional=24.53)

    assert fill.contracts == 3
    assert fill.cost == pytest.approx(0.60)
    assert fill.vwap == pytest.approx(0.20)
    assert fill.depth_limited is True, "the ladder could not absorb the notional"


def test_vwap_of_an_empty_ladder_is_no_quote_not_a_free_fill(h4: ModuleType) -> None:
    assert h4.vwap_for_notional((), notional=24.53) is None
    assert h4.vwap_for_notional(None, notional=24.53) is None


def test_vwap_takes_whole_contracts_only(h4: ModuleType) -> None:
    """Contracts are integral at this venue; a fractional last contract would
    quote a price nobody can actually be filled at."""
    fill = h4.vwap_for_notional(((0.99, 1000.0),), notional=24.53)

    assert fill.contracts == 24
    assert fill.cost == pytest.approx(23.76)
    assert fill.contracts * 0.99 <= 24.53


def test_vwap_rejects_a_zero_or_negative_price_level(h4: ModuleType) -> None:
    """`Price(0)` is the Arrow pad for a missing side, never a free contract."""
    with pytest.raises(ValueError, match="non-positive"):
        h4.vwap_for_notional(((0.0, 10.0),), notional=24.53)


# ---------------------------------------------------------------------------
# Trigger-window coverage -- what was observed vs what was never captured
# ---------------------------------------------------------------------------


def test_coverage_reports_the_observed_and_missing_parts_of_the_trigger_window(
    h4: ModuleType,
) -> None:
    # MDW trigger 16h LST; capture 18:40-18:59 LST on the same climate day.
    coverage = h4.trigger_window_coverage(
        city="MDW",
        climate_day=dt.date(2026, 8, 31),
        std_utc_offset_hours=_MDW_STD_OFFSET_HOURS,
        trigger_hour=16,
        first_ts=dt.datetime(2026, 9, 1, 0, 40, 38, tzinfo=dt.UTC),
        last_ts=dt.datetime(2026, 9, 1, 0, 59, 53, tzinfo=dt.UTC),
    )

    assert coverage.covered is True
    assert coverage.first_lst.hour == 18
    assert coverage.last_lst.hour == 18
    assert coverage.missing_hours_before == pytest.approx(2.677, abs=1e-2)
    assert "16:00" in coverage.detail


def test_coverage_flags_a_window_that_ends_before_the_trigger_hour(
    h4: ModuleType,
) -> None:
    """LAX triggers at 18h LST but the capture stops at 16:59 LST -- the
    trigger window is not observed at all, so the station contributes NO
    evidence either way."""
    coverage = h4.trigger_window_coverage(
        city="LAX",
        climate_day=dt.date(2026, 8, 31),
        std_utc_offset_hours=-8.0,
        trigger_hour=18,
        first_ts=dt.datetime(2026, 9, 1, 0, 40, 38, tzinfo=dt.UTC),
        last_ts=dt.datetime(2026, 9, 1, 0, 59, 53, tzinfo=dt.UTC),
    )

    assert coverage.covered is False
    assert coverage.first_lst.hour == 16
    assert "never reaches" in coverage.detail


# ---------------------------------------------------------------------------
# The settled-rung question
# ---------------------------------------------------------------------------


def test_settling_rung_is_the_one_containing_the_final_cli_tmax(h4: ModuleType) -> None:
    ladder = h4.parse_ladder(
        [
            "tc-temp-mdwhigh-2026-08-31-lt89f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte89lt90f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte91lt92f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte93lt94f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte95lt96f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte97f.POLYMARKET_US",
        ]
    )

    winner = h4.rung_containing(ladder, 91)

    assert winner is not None
    assert (winner.lower_f, winner.upper_f) == (91, 92)
    assert "gte91lt92f" in winner.instrument_id


def test_an_excluded_station_has_no_trigger_hour_and_yields_no_trigger_evidence(
    h4: ModuleType,
) -> None:
    """NYC is excluded from H4's universe outright, so no trigger hour exists
    for it. A sentinel hour (-1, or 0) would silently admit every captured
    instant into the measurement and let an excluded station contribute
    evidence to a verdict it is not part of.
    """
    assert "NYC" in h4.H4_EXCLUDED_STATIONS
    assert "NYC" not in h4.H4_TRIGGER_HOURS
    assert h4.trigger_hour_for("NYC") is None
    assert h4.trigger_hour_for("MDW") == 16

    coverage = h4.trigger_window_coverage(
        city="NYC",
        climate_day=dt.date(2026, 8, 31),
        std_utc_offset_hours=-5.0,
        trigger_hour=None,
        first_ts=dt.datetime(2026, 9, 1, 0, 40, 38, tzinfo=dt.UTC),
        last_ts=dt.datetime(2026, 9, 1, 0, 59, 53, tzinfo=dt.UTC),
    )

    assert coverage.covered is False
    assert coverage.trigger_hour is None
    assert "no trigger hour" in coverage.detail


def test_mdw_seasonal_carve_out_is_checked_against_the_target_day_not_assumed(
    h4: ModuleType,
) -> None:
    """H4 excludes MDW in DJF. 2026-08-31 is JJA, so the carve-out does not
    bind here -- but that must be evaluated, not taken on faith."""
    assert h4.season_for(h4.TARGET_CLIMATE_DAY) == "JJA"
    assert "DJF" in h4.H4_SEASONAL_EXCLUSIONS["MDW"]
    assert h4.season_for(h4.TARGET_CLIMATE_DAY) not in h4.H4_SEASONAL_EXCLUSIONS["MDW"]


# ---------------------------------------------------------------------------
# The verdict is COMPUTED from the counts, and scoped to what was observed
# ---------------------------------------------------------------------------


def _read(
    h4: ModuleType,
    *,
    city: str,
    trigger_hour: int | None,
    covered: bool,
    candidates: int,
    offered: int,
) -> Any:
    return h4.StationVerdictInput(
        city=city,
        trigger_hour=trigger_hour,
        covered=covered,
        candidate_instants=candidates,
        offered_instants=offered,
        observed_hours=0.32,
        missing_hours=2.68,
    )


def test_verdict_is_refuted_when_the_condition_held_and_nothing_was_offered(
    h4: ModuleType,
) -> None:
    verdict = h4.ask_availability_verdict(
        [
            _read(h4, city="MDW", trigger_hour=16, covered=True, candidates=375, offered=0),
            _read(h4, city="MIA", trigger_hour=14, covered=True, candidates=381, offered=0),
            _read(h4, city="SFO", trigger_hour=15, covered=True, candidates=372, offered=0),
        ]
    )

    assert verdict.outcome == "REFUTED_ON_OBSERVED_WINDOW"
    assert verdict.stations_refuted == ("MDW", "MIA", "SFO")
    assert verdict.stations_no_coverage == ()
    # The refutation is scoped: it speaks for the observed tail only.
    assert "observed" in verdict.detail.lower()


def test_verdict_survives_when_an_ask_was_present(h4: ModuleType) -> None:
    verdict = h4.ask_availability_verdict(
        [
            _read(h4, city="MDW", trigger_hour=16, covered=True, candidates=375, offered=12),
            _read(h4, city="MIA", trigger_hour=14, covered=True, candidates=381, offered=0),
        ]
    )

    assert verdict.outcome == "SURVIVES"
    assert verdict.stations_offered == ("MDW",)


def test_verdict_is_not_reached_when_nothing_was_observed(h4: ModuleType) -> None:
    """LAX's window ends before its trigger. A station with no coverage must
    contribute NOTHING -- neither refutation nor survival."""
    verdict = h4.ask_availability_verdict(
        [_read(h4, city="LAX", trigger_hour=18, covered=False, candidates=0, offered=0)]
    )

    assert verdict.outcome == "NO_EVIDENCE"
    assert verdict.stations_no_coverage == ("LAX",)
    assert verdict.stations_refuted == ()


def test_verdict_ignores_stations_outside_the_h4_universe(h4: ModuleType) -> None:
    verdict = h4.ask_availability_verdict(
        [
            _read(h4, city="NYC", trigger_hour=None, covered=False, candidates=0, offered=0),
            _read(h4, city="MDW", trigger_hour=16, covered=True, candidates=375, offered=0),
        ]
    )

    assert verdict.stations_refuted == ("MDW",)
    assert "NYC" not in verdict.stations_no_coverage
    assert verdict.outcome == "REFUTED_ON_OBSERVED_WINDOW"


def test_verdict_distinguishes_condition_never_held_from_never_offered(
    h4: ModuleType,
) -> None:
    """`candidates == 0` on a COVERED window is kill-criterion 3a evidence
    about the trigger, not about the book. Collapsing it into "no ask" would
    blame the market for a signal that never fired."""
    verdict = h4.ask_availability_verdict(
        [_read(h4, city="SFO", trigger_hour=15, covered=True, candidates=0, offered=0)]
    )

    assert verdict.outcome == "CONDITION_NEVER_HELD"
    assert verdict.stations_condition_never_held == ("SFO",)
    assert verdict.stations_refuted == ()


# ---------------------------------------------------------------------------
# The winner-vs-rest asymmetry
# ---------------------------------------------------------------------------


def test_winner_asymmetry_contrasts_the_settling_rung_against_the_rest(
    h4: ModuleType,
) -> None:
    asymmetry = h4.winner_asymmetry(
        winner_snapshots=58,
        winner_with_ask=0,
        other_snapshots=334,
        other_with_ask=334,
    )

    assert asymmetry.winner_ask_share == 0.0
    assert asymmetry.other_ask_share == 1.0
    assert asymmetry.winner_is_uniquely_unoffered is True


def test_winner_asymmetry_is_not_claimed_when_the_rest_is_also_empty(
    h4: ModuleType,
) -> None:
    """If nothing on the ladder is offered, the winner being unoffered says
    nothing about adverse selection -- it says the venue went dark."""
    asymmetry = h4.winner_asymmetry(
        winner_snapshots=58, winner_with_ask=0, other_snapshots=334, other_with_ask=0
    )

    assert asymmetry.winner_is_uniquely_unoffered is False


def test_winner_asymmetry_handles_a_zero_denominator(h4: ModuleType) -> None:
    asymmetry = h4.winner_asymmetry(
        winner_snapshots=0, winner_with_ask=0, other_snapshots=0, other_with_ask=0
    )

    assert asymmetry.winner_ask_share is None
    assert asymmetry.other_ask_share is None
    assert asymmetry.winner_is_uniquely_unoffered is False


# ---------------------------------------------------------------------------
# Placing a winner-side ask relative to the trigger hour
# ---------------------------------------------------------------------------


def test_winner_ask_provenance_is_silent_when_no_winner_ask_was_seen(
    h4: ModuleType,
) -> None:
    """Nothing to place: the station never offered the settling rung."""
    assert (
        h4.winner_ask_provenance(
            city="MDW",
            winner_with_ask=0,
            winner_snapshots=58,
            trigger_covered=True,
            trigger_hour=16,
        )
        is None
    )


def test_winner_ask_provenance_marks_an_uncovered_station_as_pre_trigger(
    h4: ModuleType,
) -> None:
    """LAX offered its winner on 7 of 63 snapshots, but the capture ends
    before LAX's 18:00 trigger -- so none of those instants is H4 evidence."""
    note = h4.winner_ask_provenance(
        city="LAX",
        winner_with_ask=7,
        winner_snapshots=63,
        trigger_covered=False,
        trigger_hour=18,
    )

    assert note is not None
    assert "LAX" in note
    assert "7 of 63" in note
    assert "18:00" in note
    assert "before" in note.lower()
    assert "not H4 evidence" in note


def test_winner_ask_provenance_flags_a_station_outside_the_universe(
    h4: ModuleType,
) -> None:
    note = h4.winner_ask_provenance(
        city="NYC",
        winner_with_ask=3,
        winner_snapshots=56,
        trigger_covered=False,
        trigger_hour=None,
    )

    assert note is not None
    assert "outside" in note.lower()
    assert "not H4 evidence" in note


def test_winner_ask_provenance_does_not_claim_pre_trigger_when_covered(
    h4: ModuleType,
) -> None:
    """If the trigger hour IS inside the capture, §4.1's ladder-wide counts do
    not separate before from after -- say so rather than implying either."""
    note = h4.winner_ask_provenance(
        city="MIA",
        winner_with_ask=4,
        winner_snapshots=54,
        trigger_covered=True,
        trigger_hour=14,
    )

    assert note is not None
    assert "before" not in note.lower().replace("§", "")
    assert "§2" in note or "§3" in note
