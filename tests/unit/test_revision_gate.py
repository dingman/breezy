"""RED-first tests for the pure revision-latency gate (plan r3, amended r3.1).

Book time is ``ts_init``. Quote age is never missingness. The exit bid is the
first bid in ``[t_exit, t_exit + W]``, including a fill strictly inside W.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from pathlib import Path

import pytest

from breezy.strategy.weather_common.revision_gate import (
    HEARTBEAT_WINDOW_NS,
    NS,
    W_NS,
    BookRow,
    ExitBid,
    GapSpan,
    RevisionRefused,
    as_of_snapshot,
    decision_instant,
    first_bid_in_window,
    is_missing,
    mid,
    revision,
    signed_bands,
)

_ROOT = Path(__file__).resolve().parents[2]
_SOURCES = (
    _ROOT / "src/breezy/strategy/weather_common/revision_gate.py",
    _ROOT / "src/breezy/analysis/revision_latency.py",
    _ROOT / "scripts/analysis/nbp_revision_latency.py",
)
_HOUR_PREDICATE = re.compile(r"\.hour\b|hour\s*==|strftime\(\s*[\"']%H")
_DAY = dt.date(2026, 10, 20)


def test_revision_sign_and_magnitude() -> None:
    delta = revision(
        prev_p={"a": 0.20, "b": 0.50},
        cur_p={"a": 0.55, "b": 0.10},
        prev_climate_day=_DAY,
        cur_climate_day=_DAY,
        climate_day=_DAY,
        prev_available_at_ns=1_000,
        cur_available_at_ns=2_000,
    )
    assert delta == {"a": pytest.approx(0.35), "b": pytest.approx(-0.40)}


def test_revision_refuses_mismatched_climate_days() -> None:
    other = dt.date(2026, 10, 21)
    with pytest.raises(RevisionRefused):
        revision(
            prev_p={"a": 0.2},
            cur_p={"a": 0.3},
            prev_climate_day=_DAY,
            cur_climate_day=other,
            climate_day=_DAY,
            prev_available_at_ns=1,
            cur_available_at_ns=2,
        )
    with pytest.raises(RevisionRefused):
        revision(
            prev_p={"a": 0.2},
            cur_p={"a": 0.3},
            prev_climate_day=_DAY,
            cur_climate_day=_DAY,
            climate_day=other,
            prev_available_at_ns=1,
            cur_available_at_ns=2,
        )


def test_revision_refuses_prev_available_at_or_after_cur() -> None:
    with pytest.raises(RevisionRefused):
        revision(
            prev_p={"a": 0.2},
            cur_p={"a": 0.3},
            prev_climate_day=_DAY,
            cur_climate_day=_DAY,
            climate_day=_DAY,
            prev_available_at_ns=5,
            cur_available_at_ns=5,
        )


def test_signed_bands_tie_break_on_lower_rung_id_and_absent_signs() -> None:
    bands = signed_bands({"b": 0.2, "a": 0.2, "d": -0.3, "c": -0.3})
    assert bands.r_plus == "a"
    assert bands.r_minus == "c"
    assert bands.delta_plus == pytest.approx(0.2)
    assert bands.delta_minus == pytest.approx(-0.3)
    assert signed_bands({"a": -0.1}).r_plus is None
    assert signed_bands({"a": 0.1}).r_minus is None
    assert signed_bands({"a": 0.0}).r_plus is None
    assert signed_bands({"a": 0.0}).r_minus is None
    assert signed_bands({}).r_plus is None
    assert signed_bands({}).r_minus is None


def test_decision_instant_is_strictly_after_available_plus_lag() -> None:
    t_dec = decision_instant(1_000, 300)
    assert t_dec == 1_301
    assert 1_000 + 300 < t_dec


def test_as_of_picks_the_last_row_at_or_before_t_and_never_a_future_row() -> None:
    t = 10_000
    older = BookRow(t - 50, 0.40, 0.42)
    exact = BookRow(t, 0.45, 0.47)
    future = BookRow(t + 1, 0.90, 0.95)
    assert as_of_snapshot((older, future, exact), t) == exact
    assert as_of_snapshot((future, older), t) == older
    assert as_of_snapshot((future,), t) is None


def test_two_hour_old_quote_with_a_live_heartbeat_is_not_missing() -> None:
    t = 20_000 * NS
    quote = BookRow(t - 2 * 3600 * NS, 0.40, 0.44)
    heartbeat = (t - 10 * NS,)
    verdict = is_missing((), heartbeat, t)
    assert verdict.missing is False
    assert verdict.reason == "present"
    assert as_of_snapshot((quote,), t) == quote
    assert mid(quote) == pytest.approx(0.42)


def test_gap_or_dead_heartbeat_is_missing_and_gap_wins_when_both() -> None:
    t = 20_000 * NS
    live = (t - 10 * NS,)
    gap = GapSpan(started_ns=t - 5, ended_ns=t + 5, resolved=True)
    gapped = is_missing((gap,), live, t)
    assert gapped.missing is True
    assert gapped.reason == "quote_tape_gap"
    dead = is_missing((), (t - HEARTBEAT_WINDOW_NS - 1,), t)
    assert dead.missing is True
    assert dead.reason == "heartbeat"
    both = is_missing((gap,), (t - HEARTBEAT_WINDOW_NS - 1,), t)
    assert both.reason == "quote_tape_gap"
    assert is_missing((), (t - HEARTBEAT_WINDOW_NS,), t).missing is False
    assert is_missing((), (t,), t).missing is False


def test_empty_side_makes_the_mid_missing() -> None:
    assert mid(BookRow(1, float("nan"), 0.50)) is None
    assert mid(BookRow(1, 0.40, float("nan"))) is None
    assert mid(None) is None
    assert mid(BookRow(1, 0.40, 0.50)) == pytest.approx(0.45)


def test_first_bid_uses_t_exit_then_a_later_snapshot_and_zero_when_none() -> None:
    t_exit = 5_000 * NS
    as_of = BookRow(t_exit - 1_000, 0.41, 0.45)
    at_exit = first_bid_in_window((as_of,), t_exit, W_NS)
    assert at_exit == ExitBid(
        bid=0.41, ts_ns=t_exit, missing_exit=False, filled_inside_window=False
    )
    vanished = BookRow(t_exit, float("nan"), 0.55)
    inside = BookRow(t_exit + 5 * 60 * NS, 0.62, 0.64)
    later_only = BookRow(t_exit + W_NS + 1, 0.70, 0.72)
    filled = first_bid_in_window((as_of, vanished, later_only, inside), t_exit, W_NS)
    assert filled.missing_exit is False
    assert filled.filled_inside_window is True
    assert filled.bid == pytest.approx(0.62)
    assert filled.ts_ns == inside.ts_init
    missing = first_bid_in_window((vanished, later_only), t_exit, W_NS)
    assert missing.missing_exit is True
    assert missing.bid == 0.0
    assert missing.ts_ns is None
    assert math.isfinite(missing.bid)


def test_sources_have_no_hour_of_day_predicate_and_no_asdict() -> None:
    for path in _SOURCES:
        text = path.read_text(encoding="utf-8")
        assert _HOUR_PREDICATE.search(text) is None, path
        assert "asdict" not in text, path
        assert "os.environ" not in text, path


def test_missing_exit_candidates_are_skipped_not_carried_forward() -> None:
    t_exit = 5_000 * NS
    as_of = BookRow(t_exit - 1_000, 0.41, 0.45)
    inside = BookRow(t_exit + 5 * 60 * NS, 0.62, 0.64)
    gap_until = t_exit + 60 * NS  # a recorder outage covers t_exit and the next minute

    def missing_at(t: int) -> bool:
        return t <= gap_until

    got = first_bid_in_window((as_of, inside), t_exit, W_NS, missing_at=missing_at)
    assert got.bid == pytest.approx(0.62)
    assert got.ts_ns == inside.ts_init
    assert got.filled_inside_window is True
    assert got.n_skipped_missing == 1
    everything = first_bid_in_window((as_of, inside), t_exit, W_NS, missing_at=lambda _t: True)
    assert everything.missing_exit is True
    assert everything.bid == 0.0
    assert everything.n_skipped_missing == 2
