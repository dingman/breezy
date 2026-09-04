"""Converged peer review item 4 (`docs/plans/PAPER_REPLAY_6B_BRIEF_2026-09-04.md`,
"Converged peer review", point 4, BINDING): the archive study's entry anchor
and the live/replay pricing anchor are DIFFERENT rules, and they only happen
to agree in the degenerate case where `R(t)` was set at the decision instant
itself.

Archive study (`mb_current_rung_edge_study.py:479-490`, `find_lagged_entry`):
anchors on the DECISION instant `t` (at which `R(t)` is read, unlagged) and
looks for the first depth row with `ts_event >= t + lag`.

Live/replay (PREREG v1 §3, A1; `paper_replay.py`'s
`received_at_ns = observed_at_ns + lag_minutes`): anchors on the RECEIPT of
the observation that SET `R` -- `quote.ts_event >= received_at_ns` of that
observation -- never on the later decision instant `t` at which `R` is
merely still being read.

When `R` is HELD from an earlier row (the running max was set well before
`t` and simply never exceeded since), the two anchors diverge: the study
waits until `t + lag`, while the live rule was already satisfied back when
the R-setting observation's receipt lagged in. When `R` is set AT `t` itself
the two anchors coincide, because the R-setting observation's own instant
IS `t`.

Both fixtures below are pure (no engine, no strategy, no catalog): archive
rows are built with `DepthObservation` (imported from
`h4_preliminary_economic_read.py`, exactly as
`mb_current_rung_edge_study.py` consumes it) and fed straight to
`find_lagged_entry`; the live/replay side uses real `StationObservation`
records with `received_at_ns` synthesized the same way
`paper_replay.load_replay_observations` synthesizes it
(`observed_at_ns + lag_minutes`), and a small local helper that applies the
A1 rule directly (`quote.ts_event >= received_at_ns`) -- adapted for this
fixture only, never a reimplementation of the strategy or the replay module.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Sequence
from pathlib import Path

from breezy.domain.station_observation import StationObservation

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from h4_preliminary_economic_read import DepthObservation
from mb_current_rung_edge_study import find_lagged_entry

STATION = "KLAX"
INSTRUMENT_ID = "lax-86-87"
SOURCE_CHANNEL = "iem_asos_metar_paper_replay"
LAG_MINUTES = 30

_ORIGIN = dt.datetime(2026, 9, 4, 13, 0, tzinfo=dt.UTC)  # study-side clock
_ORIGIN_NS = 1_800_000_000_000_000_000  # replay-side clock, same wall-clock offsets
_NS_PER_MIN = 60_000_000_000
_LAG = dt.timedelta(minutes=LAG_MINUTES)
_LAG_NS = LAG_MINUTES * _NS_PER_MIN


def _at(minutes: int) -> dt.datetime:
    """Study-side instant, `minutes` after 13:00."""
    return _ORIGIN + dt.timedelta(minutes=minutes)


def _minutes_since_origin(instant: dt.datetime) -> int:
    return int((instant - _ORIGIN).total_seconds() // 60)


def _ns_at(minutes: int) -> int:
    """Replay-side instant (ns), the same wall-clock offset as `_at`."""
    return _ORIGIN_NS + minutes * _NS_PER_MIN


def _minutes_since_origin_ns(instant_ns: int) -> int:
    return (instant_ns - _ORIGIN_NS) // _NS_PER_MIN


def _depth_row(minutes: int) -> DepthObservation:
    return DepthObservation(
        instrument_id=INSTRUMENT_ID,
        ts_event=_at(minutes),
        best_ask=0.5,
        ask_ladder=((0.5, 100.0),),
        best_bid=0.4,
    )


def _observation(*, minutes: int, temp_c_tenths: int) -> StationObservation:
    observed_at_ns = _ns_at(minutes)
    return StationObservation(
        station=STATION,
        observed_at_ns=observed_at_ns,
        received_at_ns=observed_at_ns + _LAG_NS,
        temp_c_tenths=temp_c_tenths,
        precision_c_tenths=10,
        is_metar=True,
        source_channel=SOURCE_CHANNEL,
        assumed_publication_lag_ns=_LAG_NS,
    )


def _r_setting_observation(
    observations: Sequence[StationObservation], *, at_ns: int,
) -> StationObservation:
    """The earliest observation (`observed_at_ns <= at_ns`) that set the
    running-max temperature still holding at `at_ns` -- the first occurrence
    of the max value seen so far. A local, pure helper mirroring the
    running-max semantics `R(t)` is defined by; adapted for this fixture
    only, not a substitute for the production `running_max_at`.
    """
    eligible = [o for o in observations if o.observed_at_ns <= at_ns]
    running_max = max(o.temp_c_tenths for o in eligible)
    for observation in eligible:  # `observations` is time-ascending
        if observation.temp_c_tenths == running_max:
            return observation
    raise AssertionError("unreachable: `running_max` is drawn from `eligible`")


def _first_priceable_quote_ns(
    quote_ts_events_ns: Sequence[int], *, received_at_ns: int,
) -> int | None:
    """PREREG v1 §3, A1: price a quote only once `quote.ts_event >=
    received_at_ns` of the observation that set `R`. A local, pure helper
    applying that rule directly -- adapted for this fixture only, never a
    reimplementation of the strategy or `paper_replay.py`.
    """
    for ts_event_ns in quote_ts_events_ns:
        if ts_event_ns >= received_at_ns:
            return ts_event_ns
    return None


_DEPTH_MINUTES = (0, 30, 60, 90, 120, 150)
_QUOTE_TS_EVENTS_NS = tuple(_ns_at(m) for m in _DEPTH_MINUTES)


def test_study_and_replay_anchors_diverge_when_r_is_held_from_an_earlier_row() -> None:
    # R is set at 13:00 (minute 0) and held -- every later reading is lower.
    observations = (
        _observation(minutes=0, temp_c_tenths=300),
        _observation(minutes=30, temp_c_tenths=280),
        _observation(minutes=60, temp_c_tenths=290),
        _observation(minutes=90, temp_c_tenths=295),
    )
    decision_t = _at(90)  # 14:30 -- R(t) is still 30.0C, set 90 minutes earlier

    # (a) the archive study's anchor: `find_lagged_entry(rows, not_before=t+lag)`.
    depth_rows = tuple(_depth_row(m) for m in _DEPTH_MINUTES)
    study_row = find_lagged_entry(depth_rows, not_before=decision_t + _LAG)
    assert study_row is not None
    study_anchor_minutes = _minutes_since_origin(study_row.ts_event)
    assert study_anchor_minutes == 120  # t (90) + lag (30) == 15:00

    # (b) the live/replay anchor: receipt of the R-SETTING observation, not `t`.
    r_row = _r_setting_observation(observations, at_ns=_ns_at(90))
    assert r_row.observed_at_ns == _ns_at(0)  # set at 13:00, not at the decision instant
    replay_anchor_ns = _first_priceable_quote_ns(
        _QUOTE_TS_EVENTS_NS, received_at_ns=r_row.received_at_ns,
    )
    assert replay_anchor_ns is not None
    replay_anchor_minutes = _minutes_since_origin_ns(replay_anchor_ns)
    assert replay_anchor_minutes == 30  # 13:00 + lag (30) == 13:30

    assert study_anchor_minutes != replay_anchor_minutes


def test_study_and_replay_anchors_coincide_when_r_is_set_at_the_decision_instant() -> None:
    # R is set AT t (14:30, minute 90) -- no earlier row holds it.
    observations = (
        _observation(minutes=0, temp_c_tenths=280),
        _observation(minutes=30, temp_c_tenths=285),
        _observation(minutes=60, temp_c_tenths=290),
        _observation(minutes=90, temp_c_tenths=300),
    )
    decision_t = _at(90)

    depth_rows = tuple(_depth_row(m) for m in _DEPTH_MINUTES)
    study_row = find_lagged_entry(depth_rows, not_before=decision_t + _LAG)
    assert study_row is not None
    study_anchor_minutes = _minutes_since_origin(study_row.ts_event)

    r_row = _r_setting_observation(observations, at_ns=_ns_at(90))
    assert r_row.observed_at_ns == _ns_at(90)  # set at the decision instant itself
    replay_anchor_ns = _first_priceable_quote_ns(
        _QUOTE_TS_EVENTS_NS, received_at_ns=r_row.received_at_ns,
    )
    assert replay_anchor_ns is not None
    replay_anchor_minutes = _minutes_since_origin_ns(replay_anchor_ns)

    assert study_anchor_minutes == replay_anchor_minutes == 120


def test_driver_header_states_the_live_a1_rule_and_not_the_studys_not_before_rule() -> None:
    """The mechanism-test driver's `PROVENANCE_HEADER_TEMPLATE` must state
    which anchor rule the run applied, and say plainly that it is NOT the
    archive study's `find_lagged_entry`/`not_before` rule (Converged peer
    review item 4, "print which rule the run applied in the header")."""
    source = (
        _SCRIPTS_ANALYSIS_DIR / "current_rung_hold_paper_replay.py"
    ).read_text()

    assert "PREREG A1 LIVE receipt anchor" in source
    assert "NOT the archive study's" in source
    assert "find_lagged_entry" in source
