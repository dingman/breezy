"""MAKER S2 WP0 -- the robust clock-offset (Delta) estimator, S-7 artefact fix.

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r4_delta_s7_estimator.md (2, 4, 7).

Delta = max of the neighbour-clamped |offset| over a window; an isolated stale-``transactTime``
spike is clamped to its larger neighbour + 10 s, a skew present in two or more consecutive samples
is kept exactly. The S-7 bound (``assert_delta_within_bound``) is not touched by this change.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence

import pytest

from scripts.analysis import maker_stage0_clock_offset as co
from scripts.analysis.maker_stage0_fill_events import (
    S7_DELTA_BOUND_NS,
    DeltaBoundExceeded,
    assert_delta_within_bound,
)
from scripts.analysis.maker_stage0_probe_core import flat_fields

_NS = 1_000_000_000
_T0 = 1_700_000_000 * _NS  # real-scale uint64 recorder stamps (~1.7e18 ns)
_STEP = 45 * _NS
_WIDE = (_T0 - 10**6 * _NS, _T0 + 10**6 * _NS)


def _ms(seconds: float) -> int:
    return round(seconds * _NS)


def _series(
    offsets_s: Sequence[float], step_ns: int = _STEP, start: int = _T0
) -> list[tuple[int, int]]:
    return [(start + i * step_ns, _ms(o)) for i, o in enumerate(offsets_s)]


def _only(
    samples: Sequence[tuple[int, int]], window: tuple[int, int] = _WIDE
) -> co.InstanceDayDelta:
    result = co.instance_day_deltas({"i": samples}, window)
    assert set(result) == {"i"}
    return result["i"]


# --- the despike rule ---------------------------------------------------------------------


def test_isolated_spike_is_clamped_to_larger_neighbour_plus_tolerance() -> None:
    row = _only(_series([0.165, 789.8, 0.193]))

    assert row.delta_ns == _ms(0.193) + 10 * _NS == 10_193_000_000
    assert row.raw_delta_ns == _ms(789.8)
    assert row.n_despiked == 1
    assert row.n_unconfirmable == 2  # the two edge samples
    assert row.samples == 3


def test_two_consecutive_skewed_samples_are_kept_exactly() -> None:
    assert _only(_series([0.1, 300, 300, 0.1])).delta_ns == 300 * _NS


def test_sustained_skew_is_kept() -> None:
    row = _only(_series([0.1, 420, 420, 420, 420, 0.1]))

    assert row.delta_ns == 420 * _NS and row.n_despiked == 0


def test_monotone_drift_ends_at_the_last_value() -> None:
    row = _only(_series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))

    assert row.delta_ns == 10 * _NS and row.n_despiked == 0


@pytest.mark.parametrize("values", [[800.0], [800.0, 0.1]])
def test_fewer_than_three_samples_stay_raw(values: list[float]) -> None:
    row = _only(_series(values))

    assert row.delta_ns == row.raw_delta_ns == _ms(800.0)
    assert row.n_unconfirmable == len(values) and row.n_despiked == 0


def test_neighbour_gap_bound_is_inclusive_and_one_ns_more_leaves_the_sample_raw() -> None:
    gap = co.MAX_NEIGHBOUR_GAP_NS
    inside = [(_T0, _ms(0.1)), (_T0 + gap, _ms(789)), (_T0 + 2 * gap, _ms(0.1))]
    outside = [(_T0, _ms(0.1)), (_T0 + gap, _ms(789)), (_T0 + 2 * gap + 1, _ms(0.1))]
    both_out = [(_T0, _ms(0.1)), (_T0 + gap + 1, _ms(789)), (_T0 + 2 * gap + 2, _ms(0.1))]

    assert _only(inside).delta_ns == _ms(0.1) + 10 * _NS
    assert _only(outside).delta_ns == _ms(789)  # one neighbour in, one out: unconfirmable
    assert _only(both_out).delta_ns == _ms(789)


def test_spike_exactly_at_neighbour_plus_tolerance_is_not_despiked() -> None:
    at = _only(_series([1, 11, 1]))
    over = _only(_series([1, 11 + 1e-9, 1]))

    assert at.delta_ns == 11 * _NS and at.n_despiked == 0
    assert over.delta_ns == 11 * _NS and over.n_despiked == 1  # clamped to 1 + 10 s


def test_clamp_uses_the_larger_raw_neighbour() -> None:
    assert _only(_series([2, 789, 5])).delta_ns == 15 * _NS


def test_negative_spike_is_despiked_but_its_signed_extreme_stays_raw() -> None:
    row = _only(_series([0.1, -789, 0.1]))

    assert row.delta_ns == _ms(0.1) + 10 * _NS
    assert (row.min_offset_ns, row.max_offset_ns) == (_ms(-789), _ms(0.1))


def test_persistent_negative_skew_survives_an_interleaved_positive_stale_frame() -> None:
    row = _only(_series([-300, -300, 120, -300, -300]))
    louder = _only(_series([-300, -300, 789, -300, -300]))

    assert row.delta_ns == 300 * _NS
    assert louder.delta_ns == 310 * _NS  # clamp ceiling: neighbour + 10 s, bounded error


def test_sustained_negative_skew_and_sign_flip_are_kept() -> None:
    assert _only(_series([-420] * 5)).delta_ns == 420 * _NS
    assert _only(_series([300, -300, 300, -300])).delta_ns == 300 * _NS


def test_despiked_values_use_raw_neighbours_never_filtered_ones() -> None:
    row = _only(
        _series([0.1, 100, 789, 0.1])
    )  # 789 clamps to 100 + 10 (raw neighbour), not to a filtered one

    assert row.delta_ns == 110 * _NS


# --- windowing ------------------------------------------------------------------------------


def test_window_edge_spike_is_clamped_by_out_of_window_neighbours() -> None:
    samples = _series([0.1, 789.8, 0.1], start=_T0 - _STEP)
    window = (_T0, _T0 + 10 * _STEP)

    filtered_first = _only(samples, window)
    window_first = _only([s for s in samples if window[0] <= s[0] < window[1]], window)

    assert filtered_first.delta_ns == _ms(0.1) + 10 * _NS
    assert filtered_first.samples == window_first.samples == 2
    assert window_first.delta_ns == _ms(789.8)  # windowing first leaves the edge sample raw


def test_empty_window_with_out_of_window_neighbours_has_no_entry() -> None:
    samples = _series([0.1, 789.8, 0.1])

    assert co.instance_day_deltas({"i": samples}, (_T0 + 10**4 * _NS, _T0 + 2 * 10**4 * _NS)) == {}
    assert co.instance_day_deltas({"i": []}, _WIDE) == {}


def test_in_window_sample_next_to_an_out_of_window_spike_is_raw_never_raised() -> None:
    samples = _series([6404.6, 0.1, 0.1], start=_T0 - _STEP)

    row = _only(samples, (_T0, _T0 + 10 * _STEP))

    assert row.delta_ns == _ms(0.1) and row.raw_delta_ns == _ms(0.1)
    assert row.samples == 2


def test_raw_delta_is_the_old_estimator_over_the_window_only() -> None:
    samples = _series([50, 0.1, 789, 0.1, 3])
    window = (_T0 + _STEP, _T0 + 5 * _STEP)

    row = _only(samples, window)

    assert (
        row.raw_delta_ns
        == _ms(789)
        == max(abs(o) for ts, o in samples if window[0] <= ts < window[1])
    )
    assert row.delta_ns < row.raw_delta_ns


def test_instances_never_confirm_each_other() -> None:
    clean = _series([0.1, 789, 0.1])
    lonely = [(_T0, _ms(0.1)), (_T0 + _STEP, _ms(789))]  # same stamps, no second neighbour

    out = co.instance_day_deltas({"a": clean, "b": lonely}, _WIDE)

    assert out["a"].delta_ns == _ms(0.1) + 10 * _NS and out["a"].n_despiked == 1
    assert out["b"].delta_ns == _ms(789) and out["b"].n_despiked == 0
    assert co.station_day_delta(out) == _ms(789)
    assert co.station_day_delta({}) is None


# --- S-7 interaction ----------------------------------------------------------------------


def test_two_consecutive_700s_samples_are_kept_and_still_trip_s7() -> None:
    row = _only(_series([0.1, 700, 700, 0.1]))

    assert row.delta_ns == 700 * _NS
    with pytest.raises(DeltaBoundExceeded):
        assert_delta_within_bound([row.delta_ns])


def test_isolated_700s_spike_no_longer_trips_s7() -> None:
    row = _only(_series([0.1, 700, 0.1]))

    assert assert_delta_within_bound([row.delta_ns]) == row.delta_ns < S7_DELTA_BOUND_NS


def test_persistent_601s_trips_and_600s_passes() -> None:
    over, at = _only(_series([601] * 5)), _only(_series([600] * 5))

    with pytest.raises(DeltaBoundExceeded):
        assert_delta_within_bound([over.delta_ns])
    assert assert_delta_within_bound([at.delta_ns]) == 600 * _NS


# --- determinism, invariants, pins ------------------------------------------------------------


def test_result_is_independent_of_input_order_and_does_not_mutate_it() -> None:
    base = _series([0.1, 5, 0.2, 789, 0.3, 0.3, 40, 41, 0.1])
    base.append((_T0 + 3 * _STEP, _ms(-9)))  # duplicate ts_init, different offset
    shuffled = list(base)
    random.Random(7).shuffle(shuffled)
    frozen = list(shuffled)

    a = co.instance_day_deltas({"i": base}, _WIDE)["i"]
    b = co.instance_day_deltas({"i": shuffled}, _WIDE)["i"]

    assert shuffled == frozen
    assert a == b and a.samples == len(base)
    assert json.dumps(flat_fields(a), sort_keys=True) == json.dumps(flat_fields(b), sort_keys=True)
    assert (a.min_offset_ns, a.max_offset_ns) == (min(o for _, o in base), max(o for _, o in base))


def _random_series(seed: int) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    ts, out = _T0, []
    for _ in range(rng.randint(1, 40)):
        ts += rng.choice([_STEP, 2 * _STEP, co.MAX_NEIGHBOUR_GAP_NS, co.MAX_NEIGHBOUR_GAP_NS + 1])
        out.append((ts, _ms(rng.choice([0.1, -0.2, 3, 12, -300, 789, 6404]) * rng.choice([1, -1]))))
    return out


@pytest.mark.parametrize("seed", range(40))
def test_invariants_over_random_series(seed: int) -> None:
    samples = _random_series(seed)

    row = _only(samples)
    triples = co.despike_abs_offsets(samples)

    assert row.delta_ns <= row.raw_delta_ns == max(abs(o) for _, o in samples)
    assert row.n_despiked + row.n_unconfirmable <= row.samples == len(samples)
    for i, (_ts, offset, filtered, confirmable) in enumerate(triples):
        assert filtered <= abs(offset)
        if filtered < abs(offset):
            assert confirmable
            neighbours = max(abs(triples[i - 1][1]), abs(triples[i + 1][1]))
            assert filtered == neighbours + co.SPIKE_TOLERANCE_NS


def test_despike_returns_sorted_tuples_with_signed_offsets() -> None:
    out = co.despike_abs_offsets([(2, -5), (1, 3), (3, 9)])

    assert [(t, o) for t, o, _f, _c in out] == [(1, 3), (2, -5), (3, 9)]


def test_constants_are_pinned() -> None:
    assert co.SPIKE_TOLERANCE_NS == 10 * _NS
    assert co.MAX_NEIGHBOUR_GAP_NS == 5 * 60 * _NS


def test_delta_summary_reports_raw_max_and_despiked_count() -> None:
    rows = co.instance_day_deltas(
        {"a": _series([0.1, 789, 0.1]), "b": _series([0.1, 50, 50, 0.1])}, _WIDE
    )

    assert co.delta_summary(rows.values()) == {"raw_max": _ms(789), "n_despiked": 1}
    assert co.delta_summary([]) == {"raw_max": None, "n_despiked": 0}
