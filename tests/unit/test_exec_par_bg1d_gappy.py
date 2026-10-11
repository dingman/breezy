"""EXEC-PAR BG-1d: gappy-day marks from epoch rows and heartbeat liveness (pure)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import pytest

from breezy.runtime.exec_par_reconcile import (
    HEARTBEAT_LAPSE_NS,
    GapKind,
    compute_gap_spans,
    gappy_days,
)
from breezy.runtime.exec_par_records import EpochRow

S = 1_000_000_000
H = 3_600 * S
DAY = 24 * H
D0 = 20_000 * DAY  # 2024-10-04T00:00Z


def _utc_day(ns: int) -> str:
    return datetime.fromtimestamp(ns // S, UTC).date().isoformat()


def _epoch(boot: int, stop: int | None = None) -> EpochRow:
    return EpochRow(commit_sha="abc", effective_k=1, force_reason=None, boot_ts=boot, stop_ts=stop)


def _beats(start: int, end: int, every: int = 30 * S) -> list[int]:
    return list(range(start, end + 1, every))


def test_recorded_outage_between_stop_and_next_boot_is_not_a_gap() -> None:
    e1 = _epoch(D0, D0 + 2 * H)
    e2 = _epoch(D0 + 10 * H, None)
    beats = _beats(D0, D0 + 2 * H) + _beats(D0 + 10 * H, D0 + 11 * H)
    spans = compute_gap_spans((e1, e2), beats, now_ns=D0 + 11 * H)
    assert spans == ()
    assert gappy_days(spans, day_of=_utc_day) == frozenset()


def test_heartbeat_lapse_over_60s_while_up_is_a_gap() -> None:
    e1 = _epoch(D0, None)
    beats = _beats(D0, D0 + H) + _beats(D0 + H + 61 * S, D0 + 2 * H)
    spans = compute_gap_spans((e1,), beats, now_ns=D0 + 2 * H)
    assert [(s.kind, s.start_ns, s.end_ns) for s in spans] == [
        (GapKind.HEARTBEAT_LAPSE, D0 + H, D0 + H + 61 * S)
    ]
    assert gappy_days(spans, day_of=_utc_day) == frozenset({"2024-10-04"})


def test_lapse_of_exactly_60s_is_not_a_gap() -> None:
    e1 = _epoch(D0, None)
    beats = [D0, D0 + HEARTBEAT_LAPSE_NS, D0 + 2 * HEARTBEAT_LAPSE_NS]
    assert compute_gap_spans((e1,), beats, now_ns=D0 + 2 * HEARTBEAT_LAPSE_NS) == ()


def test_stale_tail_on_the_open_epoch_is_a_lapse() -> None:
    e1 = _epoch(D0, None)
    beats = _beats(D0, D0 + H)
    spans = compute_gap_spans((e1,), beats, now_ns=D0 + H + 120 * S)
    assert [s.kind for s in spans] == [GapKind.HEARTBEAT_LAPSE]


def test_unclean_shutdown_gap_runs_from_last_heartbeat_to_next_boot() -> None:
    e1 = _epoch(D0, None)  # never got a stop_ts
    e2 = _epoch(D0 + 5 * H, None)
    beats = _beats(D0, D0 + H) + _beats(D0 + 5 * H, D0 + 6 * H)
    spans = compute_gap_spans((e1, e2), beats, now_ns=D0 + 6 * H)
    assert [(s.kind, s.start_ns, s.end_ns) for s in spans] == [
        (GapKind.UNCLEAN_SHUTDOWN, D0 + H, D0 + 5 * H)
    ]


def test_gap_spanning_midnight_marks_every_touched_day() -> None:
    e1 = _epoch(D0, None)
    e2 = _epoch(D0 + DAY + 2 * H, None)
    beats = _beats(D0, D0 + 22 * H) + _beats(D0 + DAY + 2 * H, D0 + DAY + 3 * H)
    spans = compute_gap_spans((e1, e2), beats, now_ns=D0 + DAY + 3 * H)
    assert gappy_days(spans, day_of=_utc_day) == frozenset({"2024-10-04", "2024-10-05"})


def test_unclean_epoch_without_any_heartbeat_gaps_from_its_boot() -> None:
    e1 = _epoch(D0, None)
    e2 = _epoch(D0 + H, None)
    spans = compute_gap_spans((e1, e2), _beats(D0 + H, D0 + 2 * H), now_ns=D0 + 2 * H)
    assert [(s.kind, s.start_ns, s.end_ns) for s in spans] == [
        (GapKind.UNCLEAN_SHUTDOWN, D0, D0 + H)
    ]


def test_clean_stop_preceded_by_a_lapse_is_a_gap() -> None:
    e1 = _epoch(D0, D0 + H)
    beats = _beats(D0, D0 + H - 200 * S)
    spans = compute_gap_spans((e1,), beats, now_ns=D0 + 2 * H)
    assert [s.kind for s in spans] == [GapKind.HEARTBEAT_LAPSE]


def test_unsorted_inputs_give_identical_output_and_inputs_are_not_mutated() -> None:
    e1 = _epoch(D0, None)
    e2 = _epoch(D0 + 5 * H, None)
    beats = _beats(D0, D0 + H) + _beats(D0 + 5 * H, D0 + 6 * H)
    forward = compute_gap_spans((e1, e2), beats, now_ns=D0 + 6 * H)
    shuffled = list(reversed(beats))
    backward = compute_gap_spans((e2, e1), shuffled, now_ns=D0 + 6 * H)
    assert forward == backward
    assert shuffled == list(reversed(beats))


def test_no_epochs_means_no_gaps() -> None:
    assert compute_gap_spans((), [D0], now_ns=D0 + H) == ()


def test_day_of_must_be_injected() -> None:
    spans = compute_gap_spans((_epoch(D0, None),), [D0], now_ns=D0 + H)
    with pytest.raises(TypeError):
        untyped = cast("Callable[..., object]", gappy_days)
        untyped(spans)
