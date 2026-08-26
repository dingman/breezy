"""Unit tests for the post-hoc guard-band bucket-alignment follow-up.

These tests cover the pure logic added in
``scripts/analysis/settlement_bucket_guard_band.py``: the boundary-distance
computation, the guard-band retention predicate, the end-to-end case builder,
and retention-fraction bookkeeping. They do not touch the network or the IEM
archive cache -- all fixtures are synthetic.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


def _load_guard_band_module() -> ModuleType:
    # settlement_bucket_guard_band.py does a bare `from settlement_bucket_gate
    # import ...`, so scripts/analysis must be importable as a top-level
    # module directory before we exec the guard-band module itself.
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "settlement_bucket_guard_band.py"
    spec = importlib.util.spec_from_file_location("settlement_bucket_guard_band", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _comparison(module: ModuleType, **overrides: object):
    kwargs: dict[str, object] = {
        "city": "NYC",
        "climate_day": dt.date(2025, 8, 1),
        "cli_tmax_f": 84,
        "metar_rounded_max_f": 84,
        "metar_unrounded_max_f": 84.0,
        "cli_source": "fixture-cli",
        "metar_source": "fixture-metar",
    }
    kwargs.update(overrides)
    return module.DailyComparison(**kwargs)


# --- metar_edge_distance -----------------------------------------------


def test_metar_edge_distance_is_zero_exactly_on_a_bucket_edge() -> None:
    module = _load_guard_band_module()

    # Bucket width is 2.0F; phase 0.0 puts an edge at every even integer.
    assert module.metar_edge_distance(84.0, 0.0) == 0.0


def test_metar_edge_distance_is_maximal_at_bucket_center() -> None:
    module = _load_guard_band_module()

    # Center of the [84, 86) bucket under phase 0.0 is 85.0, one full
    # half-width away from both edges.
    assert module.metar_edge_distance(85.0, 0.0) == 1.0


def test_metar_edge_distance_is_symmetric_about_lower_and_upper_edges() -> None:
    module = _load_guard_band_module()

    near_lower_edge = module.metar_edge_distance(84.3, 0.0)
    near_upper_edge = module.metar_edge_distance(85.7, 0.0)

    assert near_lower_edge == near_upper_edge == 0.3


def test_metar_edge_distance_respects_phase_offset() -> None:
    module = _load_guard_band_module()

    # Under phase 0.5, edges sit at 84.5, 86.5, ... so 84.5 itself is on an
    # edge and 85.5 is the bucket center.
    assert module.metar_edge_distance(84.5, 0.5) == 0.0
    assert module.metar_edge_distance(85.5, 0.5) == 1.0


def test_metar_edge_distance_handles_negative_values() -> None:
    module = _load_guard_band_module()

    # -4.0 sits on an edge under phase 0.0 just as 4.0 does; the modulo
    # arithmetic must not silently flip sign and misreport the distance.
    assert module.metar_edge_distance(-4.0, 0.0) == 0.0
    assert module.metar_edge_distance(-3.0, 0.0) == 1.0


# --- retained_by_guard ---------------------------------------------------


def test_retained_by_guard_zero_band_retains_everything_including_the_edge() -> None:
    module = _load_guard_band_module()

    assert module.retained_by_guard(edge_distance_f=0.0, guard_band_f=0.0) is True
    assert module.retained_by_guard(edge_distance_f=1.0, guard_band_f=0.0) is True


def test_retained_by_guard_excludes_case_exactly_at_the_guard_distance() -> None:
    module = _load_guard_band_module()

    # The guard-band rule is a strict `>`: a case sitting exactly at the
    # guard distance must NOT be retained, or the guard would be silently
    # narrower than documented in the pre-registration.
    assert module.retained_by_guard(edge_distance_f=0.5, guard_band_f=0.5) is False


def test_retained_by_guard_retains_case_strictly_beyond_the_guard_distance() -> None:
    module = _load_guard_band_module()

    assert module.retained_by_guard(edge_distance_f=0.5001, guard_band_f=0.5) is True


def test_retained_by_guard_excludes_case_strictly_inside_the_guard_distance() -> None:
    module = _load_guard_band_module()

    assert module.retained_by_guard(edge_distance_f=0.4999, guard_band_f=0.5) is False


# --- guarded_cases (end-to-end over synthetic comparisons) ----------------


def test_guarded_cases_drops_boundary_case_only_for_positive_guard_bands() -> None:
    module = _load_guard_band_module()

    # cli/metar both land on 84, exactly on a phase-0.0 edge -> agreement,
    # but zero boundary distance. It must appear at guard 0.0 and be
    # dropped at every positive guard band, for the phase-0.0 cell only.
    on_edge = _comparison(module, cli_tmax_f=84, metar_rounded_max_f=84, metar_unrounded_max_f=84.0)

    cases = module.guarded_cases([on_edge])

    phase_zero_guard_zero = [
        case for case in cases if case.phase == 0.0 and case.guard_band_f == 0.0
    ]
    phase_zero_positive_guards = [
        case
        for case in cases
        if case.phase == 0.0 and case.guard_band_f > 0.0
    ]

    assert len(phase_zero_guard_zero) == 1
    assert phase_zero_guard_zero[0].metar_edge_distance_f == 0.0
    assert phase_zero_positive_guards == []


def test_guarded_cases_retains_a_bucket_center_case_below_its_own_distance() -> None:
    module = _load_guard_band_module()

    # 85.0 is the center of the phase-0.0 [84, 86) bucket, exactly 1.0F from
    # both edges. The guard-band rule is a strict `>`, so it must survive
    # every guard band strictly less than 1.0F but must be EXCLUDED at the
    # 1.0F guard itself (distance == guard, not distance > guard). Silently
    # treating that boundary as inclusive would understate the retention
    # cost the guard-band sweep is meant to surface.
    center = _comparison(module, cli_tmax_f=85, metar_rounded_max_f=85, metar_unrounded_max_f=85.0)

    cases = module.guarded_cases([center])

    phase_zero_cases = [case for case in cases if case.phase == 0.0]
    guard_bands_seen = {case.guard_band_f for case in phase_zero_cases}

    assert guard_bands_seen == {band for band in module.GUARD_BANDS if band < 1.0}
    assert 1.0 not in guard_bands_seen
    assert all(case.agreed for case in phase_zero_cases)


def test_guarded_cases_reports_agreement_and_miss_direction_consistently() -> None:
    module = _load_guard_band_module()

    # CLI says 85 (bucket [84,86) under phase 0.0), METAR unrounded says
    # 86.4 which rounds to 86 -> bucket [86,88): a genuine miss, METAR
    # bucket above CLI bucket, and it is far from any edge (1.6F away from
    # the nearest edge under phase 0.0 -> min(0.4, 1.6) = 0.4).
    miss = _comparison(
        module,
        cli_tmax_f=85,
        metar_rounded_max_f=86,
        metar_unrounded_max_f=86.4,
    )

    cases = module.guarded_cases([miss])
    phase_zero_guard_zero = next(
        case for case in cases if case.phase == 0.0 and case.guard_band_f == 0.0
    )

    assert phase_zero_guard_zero.agreed is False
    assert phase_zero_guard_zero.miss_direction == "METAR above CLI"
    assert phase_zero_guard_zero.metar_edge_distance_f == 0.4


# --- retention_stats -------------------------------------------------------


def test_retention_stats_reports_case_and_city_day_fractions() -> None:
    module = _load_guard_band_module()

    day_one = dt.date(2025, 8, 1)
    day_two = dt.date(2025, 8, 2)

    original = [
        module.PhaseCase(
            city="NYC",
            climate_day=day,
            phase=0.0,
            cli_tmax_f=84,
            metar_rounded_max_f=84,
            cli_bucket=module.bucket_id(84, 0.0),
            metar_bucket=module.bucket_id(84, 0.0),
            edge_distance_f=0.0,
        )
        for day in (day_one, day_two)
    ]
    retained = [
        module.GuardedBucketCase(
            city="NYC",
            climate_day=day_one,
            phase=0.0,
            guard_band_f=0.5,
            cli_tmax_f=85,
            metar_rounded_max_f=85,
            metar_unrounded_max_f=85.0,
            cli_bucket=module.bucket_id(85, 0.0),
            metar_bucket=module.bucket_id(85, 0.0),
            metar_edge_distance_f=1.0,
        )
    ]

    stats = module.retention_stats(retained=retained, original=original)

    assert stats.retained_cases == 1
    assert stats.original_cases == 2
    assert stats.retained_fraction == 0.5
    assert stats.retained_city_days == 1
    assert stats.original_city_days == 2
    assert stats.retained_city_day_fraction == 0.5
    assert stats.retained_threshold_cases == module.THRESHOLD_CASES_PER_CITY_DAY
    assert stats.original_threshold_cases == 2 * module.THRESHOLD_CASES_PER_CITY_DAY
    assert stats.retained_threshold_case_fraction == 0.5


def test_retention_stats_handles_empty_original_without_dividing_by_zero() -> None:
    module = _load_guard_band_module()

    stats = module.retention_stats(retained=[], original=[])

    assert stats.retained_fraction == 0.0
    assert stats.retained_city_day_fraction == 0.0
    assert stats.retained_threshold_case_fraction == 0.0


# --- guard_passes ------------------------------------------------------


def test_guard_passes_is_false_when_any_phase_or_city_cell_fails_verdict() -> None:
    module = _load_guard_band_module()

    passing_case = module.GuardedBucketCase(
        city="NYC",
        climate_day=dt.date(2025, 8, 1),
        phase=0.0,
        guard_band_f=0.5,
        cli_tmax_f=85,
        metar_rounded_max_f=85,
        metar_unrounded_max_f=85.0,
        cli_bucket=module.bucket_id(85, 0.0),
        metar_bucket=module.bucket_id(85, 0.0),
        metar_edge_distance_f=1.0,
    )
    # Only one phase/city cell is populated; every other (phase, city)
    # combination in the sweep is empty and therefore fails the minimum
    # sample rule, so the guard band as a whole must not pass.
    retained_by_cell = {(0.5, 0.0, "NYC"): [passing_case], (0.5, 0.0, None): [passing_case]}
    for phase in module.PHASES:
        retained_by_cell.setdefault((0.5, phase, "NYC"), [])
        retained_by_cell.setdefault((0.5, phase, None), [])

    result = module.guard_passes(
        guard_band=0.5,
        cities=["NYC"],
        retained_by_cell=retained_by_cell,
    )

    assert result is False
