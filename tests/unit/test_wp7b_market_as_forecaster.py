"""WP-7b -- score the MARKET as a competing forecaster.

Governing document: ``docs/specs/PREREG_WP7b_MARKET_AS_FORECASTER_2026-09-20.md``
(committed `3e67cbe`, BEFORE the first run). These tests pin the properties the
registration makes binding, and every one of them was written and watched FAIL
before the module existed:

1. an instant whose ladder is not a complete partition of the integers is
   REFUSED, never imputed and never partially scored (§2);
2. a ``p_fc`` built from an input timestamped AFTER the decision instant
   RAISES -- the look-ahead class that already produced one false +0.55 in this
   programme (`a0a9ea8`);
3. the decision instant is 09:00 LOCAL at a NAMED station on a DST date;
4. every rung on the ladder appears exactly once per station-day -- no
   selection, no duplication (§2: "with no selection");
5. the bootstrap clusters by (station, date) and the REPORTED cluster count is
   the distinct station-day count (§6: "effective n is clusters, not rows");
6. the Brier is the REUSED implementation in
   ``forecast_conditional_scoring``, not a second one (§2);
7. ``sum(ask)`` is computed over a VERIFIED complete partition only (§4).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_NS = 10**9
DAY = dt.date(2026, 9, 1)
SFO_ZONE = ZoneInfo("America/Los_Angeles")

#: The REAL 2026-09-01 SFO ladder as it appears on the venue depth tape:
#: ..63 | 64-65 | 66-67 | 68-69 | 70-71 | 72.. -- a partition of the integers.
LADDER_IDS: tuple[str, ...] = (
    "tc-temp-sfohigh-2026-09-01-lt64f.POLYMARKET_US",
    "tc-temp-sfohigh-2026-09-01-gte64lt65f.POLYMARKET_US",
    "tc-temp-sfohigh-2026-09-01-gte66lt67f.POLYMARKET_US",
    "tc-temp-sfohigh-2026-09-01-gte68lt69f.POLYMARKET_US",
    "tc-temp-sfohigh-2026-09-01-gte70lt71f.POLYMARKET_US",
    "tc-temp-sfohigh-2026-09-01-gte72f.POLYMARKET_US",
)


def _load_module(name: str) -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def wp7b() -> ModuleType:
    return _load_module("wp7b_market_as_forecaster")


@pytest.fixture(scope="module")
def scoring(wp7b: ModuleType) -> ModuleType:
    """The scoring module ``wp7b`` ITSELF imported.

    Loaded through the ordinary import system, never re-executed into a second
    module object: re-executing it would create a distinct ``brier`` function
    and make the reuse assertion below pass or fail on fixture mechanics rather
    than on what the module under test actually calls.
    """
    import importlib

    return importlib.import_module("forecast_conditional_scoring")


@pytest.fixture(scope="module")
def h4(wp7b: ModuleType) -> ModuleType:
    import importlib

    return importlib.import_module("h4_preliminary_economic_read")


def _ladder(h4: ModuleType, ids: tuple[str, ...] = LADDER_IDS):
    return h4.parse_ladder(ids)


def _decision_ns() -> int:
    return int(dt.datetime(2026, 9, 1, 9, tzinfo=SFO_ZONE).timestamp()) * _NS


def _quote(wp7b: ModuleType, *, ts_ns: int, ask: float, bid: float, size: float = 25.0):
    local = dt.datetime.fromtimestamp(ts_ns / _NS, tz=dt.UTC).astimezone(SFO_ZONE)
    return wp7b.RungInstant(
        ts_ns=ts_ns,
        local_date=local.date(),
        hour_lst=local.hour,
        ask=ask,
        ask_size=size,
        bid=bid,
        bid_size=size,
    )


def _uniform_quotes(wp7b: ModuleType, ids: tuple[str, ...] = LADDER_IDS) -> dict:
    ts = _decision_ns() + 60 * _NS
    return {
        rung_id: _quote(wp7b, ts_ns=ts, ask=0.20, bid=0.10) for rung_id in ids
    }


# ---------------------------------------------------------------------------
# 1. An incomplete ladder is REFUSED, never imputed
# ---------------------------------------------------------------------------


def test_a_ladder_missing_an_interior_rung_is_refused_not_scored(wp7b, h4):
    """A gap at 66-67 leaves 66 and 67 in NO rung: that is not a partition."""
    ids = tuple(i for i in LADDER_IDS if "gte66lt67f" not in i)
    with pytest.raises(wp7b.IncompleteLadderError):
        wp7b.assert_complete_partition(_ladder(h4, ids))


def test_a_ladder_with_no_open_tail_is_refused(wp7b, h4):
    """Interior rungs alone bound nothing below 64 or above 71."""
    ids = tuple(i for i in LADDER_IDS if "lt64f.".lower() not in i.lower())
    with pytest.raises(wp7b.IncompleteLadderError):
        wp7b.assert_complete_partition(_ladder(h4, ids))


def test_an_instant_missing_one_rungs_quote_is_refused_not_partially_scored(wp7b, h4):
    """A partial ladder AT THE INSTANT is not a partition either (§2)."""
    quotes = _uniform_quotes(wp7b)
    del quotes[LADDER_IDS[3]]
    with pytest.raises(wp7b.IncompleteLadderError):
        wp7b.build_station_day_events(
            station="SFO",
            climate_day=DAY,
            ladder=_ladder(h4),
            quotes=quotes,
            p_fc={rung_id: 1.0 / 6.0 for rung_id in LADDER_IDS},
            settled_tmax_f=70,
        )


def test_the_complete_real_ladder_is_accepted(wp7b, h4):
    assert len(wp7b.assert_complete_partition(_ladder(h4))) == 6


# ---------------------------------------------------------------------------
# 2. Look-ahead: an input timestamped AFTER the instant RAISES
# ---------------------------------------------------------------------------


def test_p_fc_from_a_cycle_issued_after_the_decision_instant_raises(wp7b, h4):
    decision_ns = _decision_ns()
    with pytest.raises(wp7b.LookAheadError):
        wp7b.build_rung_probabilities(
            ladder=_ladder(h4),
            cycle_runtime_ns=decision_ns + _NS,
            decision_ns=decision_ns,
            mu=68.0,
            sigma=3.0,
        )


def test_p_fc_from_a_cycle_issued_at_the_instant_is_admitted_and_sums_to_one(wp7b, h4):
    decision_ns = _decision_ns()
    probs = wp7b.build_rung_probabilities(
        ladder=_ladder(h4),
        cycle_runtime_ns=decision_ns,
        decision_ns=decision_ns,
        mu=68.0,
        sigma=3.0,
    )
    assert set(probs) == set(LADDER_IDS)
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)


def test_a_quote_before_the_decision_instant_is_never_the_instants_quote(wp7b):
    decision_ns = _decision_ns()
    early = _quote(wp7b, ts_ns=decision_ns - _NS, ask=0.01, bid=0.001)
    on_time = _quote(wp7b, ts_ns=decision_ns + 5 * _NS, ask=0.33, bid=0.30)
    chosen = wp7b.first_liftable_at_or_after((early, on_time), decision_ns=decision_ns)
    assert chosen is not None
    assert chosen.ts_ns == on_time.ts_ns


# ---------------------------------------------------------------------------
# 3. The decision instant is 09:00 LOCAL on a DST date
# ---------------------------------------------------------------------------


def test_decision_instant_is_0900_local_at_a_named_station_on_a_dst_date(wp7b):
    """2026-09-01 is PDT (UTC-7) at SFO: 09:00 local is 16:00Z, not 17:00Z."""
    ns = wp7b.decision_instant_ns(city="SFO", climate_day=DAY)
    utc = dt.datetime.fromtimestamp(ns / _NS, tz=dt.UTC)
    assert (utc.hour, utc.minute) == (16, 0)
    assert utc.date() == DAY
    local = utc.astimezone(SFO_ZONE)
    assert (local.hour, local.date()) == (9, DAY)


def test_decision_instant_differs_by_zone_between_two_stations(wp7b):
    assert wp7b.decision_instant_ns(city="MIA", climate_day=DAY) < wp7b.decision_instant_ns(
        city="SFO", climate_day=DAY
    )


# ---------------------------------------------------------------------------
# 4. Every rung exactly once -- no selection, no duplication
# ---------------------------------------------------------------------------


def test_every_rung_on_the_ladder_appears_exactly_once_per_station_day(wp7b, h4):
    events = wp7b.build_station_day_events(
        station="SFO",
        climate_day=DAY,
        ladder=_ladder(h4),
        quotes=_uniform_quotes(wp7b),
        p_fc={rung_id: 1.0 / 6.0 for rung_id in LADDER_IDS},
        settled_tmax_f=70,
    )
    emitted = [e.rung_id for e in events]
    assert sorted(emitted) == sorted(LADDER_IDS)
    assert len(emitted) == len(set(emitted)) == 6


def test_exactly_one_rung_settles_yes(wp7b, h4):
    events = wp7b.build_station_day_events(
        station="SFO",
        climate_day=DAY,
        ladder=_ladder(h4),
        quotes=_uniform_quotes(wp7b),
        p_fc={rung_id: 1.0 / 6.0 for rung_id in LADDER_IDS},
        settled_tmax_f=70,
    )
    winners = [e.rung_id for e in events if e.settled]
    assert winners == ["tc-temp-sfohigh-2026-09-01-gte70lt71f.POLYMARKET_US"]


# ---------------------------------------------------------------------------
# 5. The bootstrap clusters by (station, date)
# ---------------------------------------------------------------------------


def _two_station_day_events(wp7b, h4):
    events = []
    for station, day, tmax in (("SFO", DAY, 70), ("SFO", DAY + dt.timedelta(days=1), 66)):
        ids = tuple(i.replace("2026-09-01", day.isoformat()) for i in LADDER_IDS)
        events.extend(
            wp7b.build_station_day_events(
                station=station,
                climate_day=day,
                ladder=_ladder(h4, ids),
                quotes=_uniform_quotes(wp7b, ids),
                p_fc={rung_id: 1.0 / 6.0 for rung_id in ids},
                settled_tmax_f=tmax,
            )
        )
    return events


def test_the_bootstrap_clusters_by_station_day_and_reports_that_count(wp7b, h4):
    events = _two_station_day_events(wp7b, h4)
    ci = wp7b.paired_brier_ci(events, market=wp7b.MARKET_MID)
    distinct = {(e.station, e.climate_day) for e in events}
    assert ci.cluster == "station_day"
    assert ci.n_clusters == len(distinct) == 2
    assert ci.max_cluster_size == 6


def test_the_trial_cluster_key_is_the_station_day_pair(wp7b, h4, scoring):
    trials = wp7b.to_trials(_two_station_day_events(wp7b, h4), market=wp7b.MARKET_ASK)
    keys = {t.cluster_key(scoring.CLUSTER_STATION_DAY) for t in trials}
    assert keys == {("SFO", DAY), ("SFO", DAY + dt.timedelta(days=1))}


# ---------------------------------------------------------------------------
# 6. The Brier is the REUSED implementation
# ---------------------------------------------------------------------------


def test_brier_is_the_reused_forecast_conditional_scoring_implementation(wp7b, scoring):
    assert wp7b.brier is scoring.brier
    assert wp7b.Trial is scoring.Trial
    assert wp7b._clusters is scoring._clusters
    assert wp7b.bootstrap_brier_difference_ci is scoring.bootstrap_brier_difference_ci


def test_paired_brier_matches_the_reused_implementation_on_the_same_trials(
    wp7b, h4, scoring
):
    events = _two_station_day_events(wp7b, h4)
    trials = wp7b.to_trials(events, market=wp7b.MARKET_MID)
    fc, mkt, diff = wp7b.paired_brier(events, market=wp7b.MARKET_MID)
    assert fc == scoring.brier(trials, scoring.MODEL_FORECAST)
    assert mkt == scoring.brier(trials, scoring.MODEL_CLIMATOLOGY)
    assert diff == fc - mkt


# ---------------------------------------------------------------------------
# 7. Sum(ask) over a VERIFIED complete partition only
# ---------------------------------------------------------------------------


def test_sum_ask_refuses_an_incomplete_partition(wp7b, h4):
    events = wp7b.build_station_day_events(
        station="SFO",
        climate_day=DAY,
        ladder=_ladder(h4),
        quotes=_uniform_quotes(wp7b),
        p_fc={rung_id: 1.0 / 6.0 for rung_id in LADDER_IDS},
        settled_tmax_f=70,
    )
    with pytest.raises(wp7b.IncompleteLadderError):
        wp7b.sum_ask_row(events[:-1])


def test_sum_ask_records_sum_fee_and_the_thinnest_l0_depth(wp7b, h4):
    events = wp7b.build_station_day_events(
        station="SFO",
        climate_day=DAY,
        ladder=_ladder(h4),
        quotes=_uniform_quotes(wp7b),
        p_fc={rung_id: 1.0 / 6.0 for rung_id in LADDER_IDS},
        settled_tmax_f=70,
    )
    row = wp7b.sum_ask_row(events)
    assert row.n_rungs == 6
    assert row.sum_ask == pytest.approx(6 * 0.20)
    # fee = banker's-rounded theta*p*(1-p) at 0.20 -> 0.01 a rung, never a
    # flat subtraction of the 0.0695 coefficient.
    assert row.sum_fee == pytest.approx(6 * 0.01)
    assert row.min_ask_size == pytest.approx(25.0)


def test_the_hurdle_is_the_venue_fee_plus_the_half_spread(wp7b):
    from forecast_tape_screen import venue_fee

    hurdle = wp7b.hurdle(ask=0.50, bid=0.40)
    assert hurdle == pytest.approx(venue_fee(ask_probability=0.50) + 0.05)


# ---------------------------------------------------------------------------
# 8. Step-5 qualifying-rate window flags (AUD-02 completion plan §3)
#
# Definition, from WP7b_MARKET_AS_FORECASTER_2026-09-20.md:203-208: an event
# qualifies when its OWN yes_ask >= 0.70 AND its station-day's Σask over the
# complete partition <= 1.20, at the pre-declared 09:00 LST instant. Only the
# YES side needs to be priced at L0 -- ``ask_events``/``sum_ask_rows`` already
# carry exactly that (no bid required), so this reuses the existing values and
# adds no new predicate. The frozen region opens on climate day 2026-09-21.
# ---------------------------------------------------------------------------

SINCE = dt.date(2026, 9, 21)


def _sum_ask_row(wp7b, *, station: str = "SFO", climate_day: dt.date, sum_ask: float):
    return wp7b.SumAskRow(
        station=station,
        climate_day=climate_day,
        n_rungs=6,
        sum_ask=sum_ask,
        sum_fee=0.0,
        min_ask_size=25.0,
        total_ask_size=150.0,
    )


def _rung_event(
    wp7b, *, station: str = "SFO", climate_day: dt.date, ask: float, rung_id: str = "r1"
):
    return wp7b.RungEvent(
        station=station,
        climate_day=climate_day,
        rung_id=rung_id,
        ts_ns=0,
        p_fc=0.5,
        ask=ask,
        ask_size=25.0,
        bid=None,
        bid_size=0.0,
        settled=False,
    )


def test_window_filter_includes_the_since_boundary_day(wp7b):
    events = [_rung_event(wp7b, climate_day=SINCE, ask=0.80)]
    rows = [_sum_ask_row(wp7b, climate_day=SINCE, sum_ask=1.00)]
    report = wp7b.compute_qualifying_rate(
        ask_events=events, sum_ask_rows=rows, notes=[], since=SINCE
    )
    assert report.station_days_in_window == 1
    assert report.qualifying_events == 1


def test_window_filter_excludes_the_day_before_since(wp7b):
    day_before = SINCE - dt.timedelta(days=1)
    events = [_rung_event(wp7b, climate_day=day_before, ask=0.80)]
    rows = [_sum_ask_row(wp7b, climate_day=day_before, sum_ask=1.00)]
    report = wp7b.compute_qualifying_rate(
        ask_events=events, sum_ask_rows=rows, notes=[], since=SINCE
    )
    assert report.station_days_in_window == 0
    assert report.qualifying_events == 0


def test_window_filter_includes_the_until_boundary_day_inclusive(wp7b):
    until = SINCE + dt.timedelta(days=2)
    events = [_rung_event(wp7b, climate_day=until, ask=0.80)]
    rows = [_sum_ask_row(wp7b, climate_day=until, sum_ask=1.00)]
    report = wp7b.compute_qualifying_rate(
        ask_events=events, sum_ask_rows=rows, notes=[], since=SINCE, until=until
    )
    assert report.station_days_in_window == 1


def test_window_filter_excludes_the_day_after_until(wp7b):
    until = SINCE + dt.timedelta(days=2)
    after = until + dt.timedelta(days=1)
    events = [_rung_event(wp7b, climate_day=after, ask=0.80)]
    rows = [_sum_ask_row(wp7b, climate_day=after, sum_ask=1.00)]
    report = wp7b.compute_qualifying_rate(
        ask_events=events, sum_ask_rows=rows, notes=[], since=SINCE, until=until
    )
    assert report.station_days_in_window == 0


def test_predicate_admits_high_ask_with_tight_partition(wp7b):
    rows = [_sum_ask_row(wp7b, climate_day=SINCE, sum_ask=1.10)]
    events = [_rung_event(wp7b, climate_day=SINCE, ask=0.75)]
    report = wp7b.compute_qualifying_rate(
        ask_events=events, sum_ask_rows=rows, notes=[], since=SINCE
    )
    assert report.qualifying_events == 1
    assert report.qualifying_station_days == 1


def test_predicate_rejects_ask_below_threshold(wp7b):
    rows = [_sum_ask_row(wp7b, climate_day=SINCE, sum_ask=1.10)]
    events = [_rung_event(wp7b, climate_day=SINCE, ask=0.69)]
    report = wp7b.compute_qualifying_rate(
        ask_events=events, sum_ask_rows=rows, notes=[], since=SINCE
    )
    assert report.qualifying_events == 0


def test_predicate_rejects_partition_over_the_sum_ask_cap(wp7b):
    rows = [_sum_ask_row(wp7b, climate_day=SINCE, sum_ask=1.21)]
    events = [_rung_event(wp7b, climate_day=SINCE, ask=0.90)]
    report = wp7b.compute_qualifying_rate(
        ask_events=events, sum_ask_rows=rows, notes=[], since=SINCE
    )
    assert report.qualifying_events == 0


def test_bad_since_date_format_is_refused(wp7b):
    with pytest.raises(SystemExit):
        wp7b.main(["--since", "2026/09/21"])


def test_since_after_until_is_refused(wp7b):
    with pytest.raises(SystemExit):
        wp7b.main(["--since", "2026-09-25", "--until", "2026-09-20"])


def test_a_gap_intersecting_window_reports_no_data_not_a_rate_or_nan(wp7b):
    notes = [
        (
            "FORECAST ARCHIVE GAP for KSFO: 1 runtime day(s) covered by no entry "
            "(2026-09-21..2026-09-21)"
        )
    ]
    report = wp7b.compute_qualifying_rate(
        ask_events=[], sum_ask_rows=[], notes=notes, since=SINCE
    )
    assert report.gap_intersects_window is True
    assert report.station_days_in_window == 0
    rendered = wp7b.render_qualifying_rate_report(report)
    assert "NO DATA (archive gap)" in rendered
    assert "0/0" not in rendered
    assert "nan" not in rendered.lower()


def test_a_gap_outside_the_window_does_not_trigger_no_data_language(wp7b):
    notes = [
        (
            "FORECAST ARCHIVE GAP for KSFO: 1 runtime day(s) covered by no entry "
            "(2026-08-01..2026-08-01)"
        )
    ]
    rows = [_sum_ask_row(wp7b, climate_day=SINCE, sum_ask=1.00)]
    events = [_rung_event(wp7b, climate_day=SINCE, ask=0.80)]
    report = wp7b.compute_qualifying_rate(
        ask_events=events, sum_ask_rows=rows, notes=notes, since=SINCE
    )
    assert report.gap_intersects_window is False
    rendered = wp7b.render_qualifying_rate_report(report)
    assert "NO DATA" not in rendered


def test_default_behaviour_with_no_window_flags_is_byte_identical(wp7b):
    """Pins that adding --since/--until changes nothing when neither is passed."""
    collected = wp7b.Collected(
        ask_events=[],
        mid_events=[],
        sum_ask_rows=[],
        single_instant_takes=[],
        census=wp7b.Census(),
        notes=[],
    )
    assert wp7b.build_artefact(collected, since=None, until=None) == wp7b.render(collected)
