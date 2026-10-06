"""AUT-2 r7 WP6 / sections 3.10 and 4: memory sizing from a measured peak and the slot hold."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from breezy.analysis.labeling.constants import (
    LABEL_MEMORY_CEILING_GIB,
    LABEL_MEMORY_HIGH_CAP_GIB,
    LABEL_MEMORY_HIGH_MIN_RATIO,
    LABEL_MEMORY_TARGET_GIB,
)
from breezy.analysis.labeling.memory_gate import (
    HOLD_DIR,
    Aut6Reading,
    Hold,
    MemorySizing,
    SizingExceedsCap,
    label_slot_held,
    missing_aut6_reading,
    record_hold,
    size_from_peak,
)
from breezy.analysis.labeling.skip_journal import utc_day

_GIB = 1024**3
_NOW = 1_790_000_000_000_000_000
_PASS = Aut6Reading("pass", "v" * 64)


def test_size_from_peak_is_one_point_five_rounded_up_to_a_gib() -> None:
    sized = size_from_peak(int(2.5 * _GIB))

    assert isinstance(sized, MemorySizing)
    assert sized.memory_max_bytes == 4 * _GIB  # ceil(3.75 GiB)
    assert sized.memory_high_bytes == int(0.9 * 4 * _GIB)


def test_size_from_peak_exactly_on_a_gib_boundary_does_not_round_up_again() -> None:
    sized = size_from_peak(2 * _GIB)

    assert isinstance(sized, MemorySizing) and sized.memory_max_bytes == 3 * _GIB


def test_memory_high_is_capped_at_the_studies_cap() -> None:
    sized = size_from_peak(int(8.5 * _GIB))  # ceil(12.75) = 13 G, 0.9 x 13 = 11.7 G

    assert isinstance(sized, MemorySizing) and sized.memory_max_bytes == 13 * _GIB
    assert sized.memory_high_bytes <= LABEL_MEMORY_HIGH_CAP_GIB * _GIB
    assert sized.memory_high_bytes >= LABEL_MEMORY_HIGH_MIN_RATIO * int(8.5 * _GIB)


def test_sizing_above_the_14g_ceiling_exceeds_the_cap() -> None:
    assert isinstance(size_from_peak(int(9.5 * _GIB)), SizingExceedsCap)  # ceil(14.25) = 15 G


def test_capped_memory_high_below_one_point_three_five_peak_exceeds_the_cap() -> None:
    peak = int(8.95 * _GIB)  # ceil(13.4) = 14 G; the 12 G cap is below 1.35 x peak
    assert isinstance(size_from_peak(peak), SizingExceedsCap)


@pytest.mark.parametrize("bad", [0, -1])
def test_size_from_peak_refuses_a_non_positive_peak(bad: int) -> None:
    with pytest.raises(ValueError):
        size_from_peak(bad)


def test_constants_are_the_plan_values() -> None:
    assert (LABEL_MEMORY_CEILING_GIB, LABEL_MEMORY_HIGH_CAP_GIB) == (14, 12)
    assert LABEL_MEMORY_TARGET_GIB == 4


def test_memory_gate_inactive_at_or_below_4g() -> None:
    for unit_max in (1 * _GIB, 4 * _GIB):
        assert label_slot_held(unit_max_bytes=unit_max, aut6=missing_aut6_reading()) is None


def test_memory_gate_holds_above_4g_until_aut6_memory_budget_pass() -> None:
    held = label_slot_held(unit_max_bytes=5 * _GIB, aut6=Aut6Reading("not_pass", "n" * 64))
    free = label_slot_held(unit_max_bytes=5 * _GIB, aut6=_PASS)

    assert isinstance(held, Hold)
    assert (held.cause, held.reason) == ("memory_gate", "verdict_not_pass")
    assert held.aut6_memory_verdict_id == "n" * 64 and held.memory_max_bytes == 5 * _GIB
    assert free is None


@pytest.mark.parametrize(
    ("status", "reason"), [("missing", "verdict_missing"), ("corrupt", "verdict_corrupt")]
)
def test_memory_gate_holds_on_missing_or_corrupt_aut6_memory_budget(
    status: str, reason: str
) -> None:
    held = label_slot_held(unit_max_bytes=6 * _GIB, aut6=Aut6Reading(status))  # type: ignore[arg-type]

    assert held is not None and (held.cause, held.reason) == ("memory_gate", reason)
    assert held.aut6_memory_verdict_id is None


def test_the_default_aut6_reading_fails_closed_as_missing() -> None:
    assert missing_aut6_reading() == Aut6Reading("missing")


def test_memory_sizing_above_cap_holds_with_critical_cause() -> None:
    held = label_slot_held(
        unit_max_bytes=14 * _GIB,
        aut6=_PASS,
        measured_peak_bytes=int(9.5 * _GIB),
    )

    assert held is not None
    assert (held.cause, held.reason) == ("memory_sizing_exceeds_cap", "sizing")
    assert held.measured_peak_bytes == int(9.5 * _GIB)


def test_sizing_above_cap_holds_even_at_or_below_4g_unit_max() -> None:
    held = label_slot_held(unit_max_bytes=2 * _GIB, aut6=_PASS, measured_peak_bytes=int(9.5 * _GIB))

    assert held is not None and held.cause == "memory_sizing_exceeds_cap"


def test_record_hold_writes_the_write_once_journal_with_the_plan_fields(tmp_path: Path) -> None:
    hold = Hold("memory_gate", "verdict_missing", 5 * _GIB, None, None)

    path = record_hold(tmp_path, hold, now_ns=_NOW, slot_ns=_NOW - 5)

    assert path.parent == tmp_path.joinpath(*HOLD_DIR, utc_day(_NOW))
    assert path.name == f"{_NOW}_label-outcomes.json"
    body = json.loads(path.read_text())
    assert body == {
        "schema": "aut2_hold/v1",
        "unit": "breezy-label-outcomes",
        "slot_ns": _NOW - 5,
        "cause": "memory_gate",
        "reason": "verdict_missing",
        "memory_max_bytes": 5 * _GIB,
        "measured_peak_bytes": None,
        "aut6_memory_verdict_id": None,
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_record_hold_write_failure_raises_a_typed_error(tmp_path: Path) -> None:
    from breezy.analysis.labeling.memory_gate import HoldJournalWriteFailed

    blocker = tmp_path.joinpath("evidence")
    blocker.write_text("a file where a directory is needed")

    with pytest.raises(HoldJournalWriteFailed):
        record_hold(
            tmp_path,
            Hold("memory_gate", "verdict_missing", 5 * _GIB, None, None),
            now_ns=_NOW,
            slot_ns=_NOW,
        )
