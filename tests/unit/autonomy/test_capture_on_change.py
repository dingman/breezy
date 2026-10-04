"""AUT-1 WP1 part A: the pure on-change filter (r8's four tests; r8 section 3.3.3, D9)."""

import datetime as dt
import random
import time
from typing import Any

import pytest

from breezy.persistence.autonomy.capture_on_change import OnChangeFilter

DAY_NS = 86_400 * 10**9
D0 = int(dt.datetime(2026, 10, 3, tzinfo=dt.UTC).timestamp()) * 10**9
KEY = ("KLAX", "2026-10-03", "gte93lt94f", "YES")


def _day_ns(day: str, seconds: int = 0) -> int:
    midnight = dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC)
    return int(midnight.timestamp()) * 10**9 + seconds * 10**9


def test_on_change_admits_take_and_trysubmit_always() -> None:
    """MUTATION: treating a repeated Take as suppressible returns False on the second call."""
    flt = OnChangeFilter()
    for kind in ("Take", "TrySubmit"):
        for n in range(3):
            assert flt.admit(KEY, kind, "take", D0 + n) is True, (kind, n)


def test_on_change_suppresses_an_unchanged_refusal_and_admits_a_change() -> None:
    flt = OnChangeFilter()
    assert flt.admit(KEY, "Refuse", "below_margin", D0) is True
    assert flt.admit(KEY, "Refuse", "below_margin", D0 + 1) is False
    assert flt.admit(KEY, "Refuse", "no_forecast", D0 + 2) is True  # reason changed
    assert flt.admit(KEY, "NotExecutable", "no_forecast", D0 + 3) is True  # kind changed
    other_side = ("KLAX", "2026-10-03", "gte93lt94f", "NO")
    assert flt.admit(other_side, "Refuse", "below_margin", D0 + 4) is True  # a separate key
    assert flt.admit(KEY, "Take", "take", D0 + 5) is True
    assert flt.admit(KEY, "Refuse", "below_margin", D0 + 6) is True  # change from the Take


def test_on_change_is_pure_and_replayable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two fresh filters fed one sequence give the same outputs, with every clock disabled."""

    def _no_clock(*_a: Any, **_k: Any) -> float:
        raise AssertionError("the filter must not read a clock")

    monkeypatch.setattr(time, "time", _no_clock)
    monkeypatch.setattr(time, "monotonic", _no_clock)
    rng = random.Random(7)
    kinds = ("Refuse", "NotExecutable", "NotDPlus1", "Take", "TrySubmit", "EntryVeto")
    reasons = ("below_margin", "no_forecast", "take", "venue_silent")
    keys = [("KLAX", "2026-10-03", f"r{i}", side) for i in range(3) for side in ("YES", "NO")]
    sequence = [
        (rng.choice(keys), rng.choice(kinds), rng.choice(reasons), D0 + n * 1_000)
        for n in range(500)
    ]
    first = [OnChangeFilter().admit(*s) for s in sequence[:1]]
    run_a, run_b = OnChangeFilter(), OnChangeFilter()
    out_a = [run_a.admit(*s) for s in sequence]
    out_b = [run_b.admit(*s) for s in sequence]
    assert out_a == out_b
    assert first[0] is True
    assert any(out_a) and not all(out_a)


def test_on_change_eviction_depends_only_on_eval_ns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keys with ``climate_day < utc_date(eval_ns) - 1`` are evicted on an insert.

    MUTATION: evicting on the wall-clock date (or never) fails one of the two directions.
    """
    monkeypatch.setattr(time, "time", lambda: 0.0)
    flt = OnChangeFilter()
    old = ("KLAX", "2026-10-01", "r1", "YES")
    assert flt.admit(old, "Refuse", "below_margin", _day_ns("2026-10-01", 5)) is True
    assert len(flt) == 1
    # eval date 10-02: cutoff 10-01, so 10-01 is NOT older than the cutoff: retained.
    fresh = ("KLAX", "2026-10-02", "r1", "YES")
    assert flt.admit(fresh, "Refuse", "below_margin", _day_ns("2026-10-02", 5)) is True
    assert len(flt) == 2
    assert flt.admit(old, "Refuse", "below_margin", _day_ns("2026-10-02", 6)) is False
    # eval date 10-03: cutoff 10-02, so 10-01 is evicted by the next insert.
    newer = ("KLAX", "2026-10-03", "r1", "YES")
    assert flt.admit(newer, "Refuse", "below_margin", _day_ns("2026-10-03", 5)) is True
    assert len(flt) == 2
    assert flt.admit(old, "Refuse", "below_margin", _day_ns("2026-10-03", 6)) is True  # forgotten


def test_on_change_never_resets_at_utc_rollover() -> None:
    """One filter per boot: a refusal repeated across 00:00Z stays suppressed."""
    flt = OnChangeFilter()
    key = ("KLAX", "2026-10-03", "r1", "YES")
    assert flt.admit(key, "Refuse", "below_margin", _day_ns("2026-10-03", 86_399)) is True
    assert flt.admit(key, "Refuse", "below_margin", _day_ns("2026-10-04", 1)) is False
