"""WP-7 cheap screen -- the decision window is a LOCAL CALENDAR DAY, not an hour.

These tests pin six look-ahead / local-time defects that made the screen's
headline number an artefact rather than a measurement:

1. the window filter matched HOUR-OF-DAY only, so a rung's D-1 tape (a rung for
   climate day D is captured from D-1 07:00 local through D+1) entered the
   window and, because the first take is the EARLIEST candidate, supplied the
   majority of all takes;
2. the C2 pre-window reference was `prior[-1]` over the WHOLE multi-day tape,
   i.e. an instant up to ~24 h AFTER the take it was compared against -- the
   screen condition `ask(t) < ref` then reads "this rung repriced upward over
   the next day", which is an outcome leak, not a screen;
3. the model's decision instant was 09:00 **UTC** while §2.2 and the comment
   both say 09:00 local;
4. `hour_lst` was derived from the STANDARD offset year-round, so every
   September window (all four stations on DST) was labelled an hour early;
5. the NO-leg C2 screen compared `1 - bid` against `1 - pre_window_ASK`, which
   is off by the spread -- the pre-window NO ask is `1 - pre_window_BID`;
6. the reported `hour_lst` was looked up by `ts_ns` across ALL rungs, so it
   could be attributed to a rung that was never chosen.

Fixtures are explicit synthetic tapes with REAL epoch timestamps: the local
date is derived from the instant itself, so a fixture cannot silently disagree
with the day it claims to be on.
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

#: LAX in September is on PDT (UTC-7); its STANDARD offset is -8. Every
#: assertion below that distinguishes the two rides on that one hour.
LAX_ZONE = ZoneInfo("America/Los_Angeles")
DAY = dt.date(2026, 9, 15)
PRIOR_DAY = DAY - dt.timedelta(days=1)
_NS = 10**9


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
def wp7() -> ModuleType:
    return _load_module("forecast_cheap_screen_wp7")


def _ns(day: dt.date, hour: int, minute: int = 0) -> int:
    """Epoch-ns for a LAX wall-clock instant -- DST-aware, never a fixed offset."""
    moment = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=LAX_ZONE)
    return int(moment.timestamp()) * _NS


def _variant(wp7: ModuleType, variant_id: str):
    return next(v for v in wp7.ALL_VARIANTS if v.variant_id == variant_id)


def _instant(
    wp7: ModuleType,
    *,
    day: dt.date,
    hour: int,
    minute: int = 0,
    ts_ns: int | None = None,
    ask: float | None = None,
    ask_size: float = 0.0,
    bid: float | None = None,
    bid_size: float = 0.0,
):
    """One L0 snapshot at ``day hour:minute`` LAX local time.

    ``ts_ns`` is overridable ONLY so a test can build the inconsistent tape the
    look-ahead guard exists to refuse; every other fixture derives it.
    """
    return wp7.RungInstant(
        ts_ns=_ns(day, hour, minute) if ts_ns is None else ts_ns,
        local_date=day,
        hour_lst=hour,
        ask=ask,
        ask_size=ask_size,
        bid=bid,
        bid_size=bid_size,
    )


def _tape(wp7: ModuleType, rung_id: str, lower: int, upper: int, instants):
    return wp7.RungTape(rung_id=rung_id, lower_f=lower, upper_f=upper, instants=tuple(instants))


# ---------------------------------------------------------------------------
# Defect 1 -- the window is scoped to the climate day, not to an hour-of-day
# ---------------------------------------------------------------------------


def test_a_prior_day_instant_in_the_window_hour_is_excluded(wp7: ModuleType) -> None:
    """The D-1 leg of the tape carries in-window HOURS and must never be taken."""
    tape = _tape(
        wp7,
        "r70",
        70,
        71,
        [
            # D-1 10:00 local: in the A1 window BY HOUR, on the wrong day.
            _instant(wp7, day=PRIOR_DAY, hour=10, ask=0.05, ask_size=5.0),
            # D 10:30 local: the only legal candidate.
            _instant(wp7, day=DAY, hour=10, minute=30, ask=0.30, ask_size=5.0),
        ],
    )
    trial = wp7.screen_station_day(
        station="LAX",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": 0.60},
    )
    assert trial.took is True
    assert trial.ask == pytest.approx(0.30), "the D-1 0.05 ask must not be reachable"


def test_a_next_day_instant_in_the_window_hour_is_excluded(wp7: ModuleType) -> None:
    tape = _tape(
        wp7,
        "r70",
        70,
        71,
        [_instant(wp7, day=DAY + dt.timedelta(days=1), hour=10, ask=0.05, ask_size=5.0)],
    )
    trial = wp7.screen_station_day(
        station="LAX",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": 0.60},
    )
    assert trial.took is False
    assert trial.reason == wp7.REASON_NO_LIFTABLE_QUOTE


# ---------------------------------------------------------------------------
# Defect 2 -- the C2 reference may never be observable after the take
# ---------------------------------------------------------------------------


def test_a_pre_window_reference_later_than_the_take_is_refused(wp7: ModuleType) -> None:
    """The guard, not the arithmetic, is what stops the leak coming back."""
    take = _instant(wp7, day=DAY, hour=10, ask=0.30, ask_size=5.0)
    leaking_reference = _instant(
        wp7,
        day=DAY,
        hour=8,
        ts_ns=take.ts_ns + 60 * _NS,  # observable AFTER the take it screens
        ask=0.40,
        ask_size=5.0,
    )
    tape = _tape(wp7, "r70", 70, 71, [leaking_reference, take])
    with pytest.raises(wp7.PreWindowLookAheadError, match="after"):
        wp7.screen_station_day(
            station="LAX",
            climate_day=DAY,
            rungs=[tape],
            variant=_variant(wp7, "A1-B1-C2"),
            p_yes_by_rung={"r70": 0.60},
        )


def test_a_prior_day_pre_window_ask_is_not_the_reference(wp7: ModuleType) -> None:
    """D-1 08:00 is not "before the window" -- it is a different day entirely."""
    tape = _tape(
        wp7,
        "r70",
        70,
        71,
        [
            _instant(wp7, day=PRIOR_DAY, hour=8, ask=0.40, ask_size=5.0),
            _instant(wp7, day=DAY, hour=10, ask=0.30, ask_size=5.0),
        ],
    )
    trial = wp7.screen_station_day(
        station="LAX",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C2"),
        p_yes_by_rung={"r70": 0.60},
    )
    assert trial.took is False, "no same-day pre-window ask exists, so C2 cannot screen"


def test_a_same_day_pre_window_ask_is_the_reference(wp7: ModuleType) -> None:
    tape = _tape(
        wp7,
        "r70",
        70,
        71,
        [
            _instant(wp7, day=DAY, hour=8, ask=0.40, ask_size=5.0),
            _instant(wp7, day=DAY, hour=10, ask=0.30, ask_size=5.0),
        ],
    )
    trial = wp7.screen_station_day(
        station="LAX",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C2"),
        p_yes_by_rung={"r70": 0.60},
    )
    assert trial.took is True
    assert trial.ask == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# Defect 4 -- local time follows DST
# ---------------------------------------------------------------------------


def test_local_hour_follows_dst_not_the_standard_offset(wp7: ModuleType) -> None:
    """2026-09-15 16:00Z is 09:00 PDT at LAX; the -8 standard offset says 08:00."""
    ts_ns = int(dt.datetime(2026, 9, 15, 16, tzinfo=dt.UTC).timestamp()) * _NS
    local_date, hour = wp7.local_date_and_hour(ts_ns, wp7.station_time_zone("LAX"))
    assert (local_date, hour) == (dt.date(2026, 9, 15), 9)


def test_local_hour_uses_the_standard_offset_out_of_dst(wp7: ModuleType) -> None:
    ts_ns = int(dt.datetime(2026, 1, 15, 17, tzinfo=dt.UTC).timestamp()) * _NS
    local_date, hour = wp7.local_date_and_hour(ts_ns, wp7.station_time_zone("LAX"))
    assert (local_date, hour) == (dt.date(2026, 1, 15), 9)


def test_every_pool_station_has_an_explicit_iana_zone(wp7: ModuleType) -> None:
    assert set(wp7.STATION_TIME_ZONES) == set(wp7.POOL_CITIES)


# ---------------------------------------------------------------------------
# Defect 3 -- the decision instant is 09:00 LOCAL, never 09:00 UTC
# ---------------------------------------------------------------------------


def test_the_decision_instant_is_nine_local_at_the_station(wp7: ModuleType) -> None:
    decision_ns = wp7.decision_instant_ns(city="LAX", climate_day=DAY)
    assert decision_ns == int(dt.datetime(2026, 9, 15, 16, tzinfo=dt.UTC).timestamp()) * _NS
    utc_nine = int(dt.datetime(2026, 9, 15, 9, tzinfo=dt.UTC).timestamp()) * _NS
    assert decision_ns != utc_nine


# ---------------------------------------------------------------------------
# Defect 5 -- the NO leg screens against the pre-window NO ask
# ---------------------------------------------------------------------------


def test_the_no_leg_screens_against_one_minus_the_pre_window_bid(wp7: ModuleType) -> None:
    """Pre-window NO ask is `1 - 0.20 = 0.80`; the live NO ask 0.75 is cheaper.

    Under the defect the comparison was against `1 - pre_window_ASK = 0.10`,
    which 0.75 never clears, so the NO leg was screened out by the spread.
    """
    tape = _tape(
        wp7,
        "r70",
        70,
        71,
        [
            _instant(wp7, day=DAY, hour=8, ask=0.90, ask_size=5.0, bid=0.20, bid_size=5.0),
            _instant(wp7, day=DAY, hour=10, ask=0.95, ask_size=5.0, bid=0.25, bid_size=5.0),
        ],
    )
    trial = wp7.screen_station_day(
        station="LAX",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B2-C2"),
        p_yes_by_rung={"r70": 0.05},
    )
    assert trial.side == "NO"
    assert trial.ask == pytest.approx(0.75)
    assert trial.took is True


def test_the_no_leg_is_screened_out_when_it_did_not_cheapen(wp7: ModuleType) -> None:
    tape = _tape(
        wp7,
        "r70",
        70,
        71,
        [
            _instant(wp7, day=DAY, hour=8, ask=0.90, ask_size=5.0, bid=0.25, bid_size=5.0),
            _instant(wp7, day=DAY, hour=10, ask=0.95, ask_size=5.0, bid=0.20, bid_size=5.0),
        ],
    )
    trial = wp7.screen_station_day(
        station="LAX",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B2-C2"),
        p_yes_by_rung={"r70": 0.05},
    )
    assert trial.took is False


# ---------------------------------------------------------------------------
# Defect 6 -- the reported hour belongs to the CHOSEN rung
# ---------------------------------------------------------------------------


def test_the_reported_hour_belongs_to_the_chosen_rung(wp7: ModuleType) -> None:
    """Two rungs share a `ts_ns`; the diagnostic must follow the take, not the scan."""
    shared_ts = _ns(DAY, 10, 30)
    unpriced = _tape(
        wp7,
        "r72",
        72,
        73,
        [_instant(wp7, day=DAY, hour=11, ts_ns=shared_ts, ask=0.10, ask_size=5.0)],
    )
    taken = _tape(
        wp7,
        "r70",
        70,
        71,
        [_instant(wp7, day=DAY, hour=10, ts_ns=shared_ts, ask=0.30, ask_size=5.0)],
    )
    trial = wp7.screen_station_day(
        station="LAX",
        climate_day=DAY,
        rungs=[unpriced, taken],  # the unpriced rung is scanned FIRST
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": 0.60},  # r72 carries no model probability
    )
    assert trial.rung == "r70"
    assert trial.hour_lst == 10
