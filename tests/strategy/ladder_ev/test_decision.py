"""T2 + spec §13.9: X1–X11, Xc, universe gates, and exclusion order."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.decision import ExclusionInputs, exclusion_filter
from breezy.strategy.weather_common.running_extreme import RunningMax

_LADDER: tuple[tuple[int | None, int | None], ...] = (
    (None, 69),
    (70, 71),
    (72, 73),
    (74, 75),
    (76, 77),
    (78, None),
)
_CLIMATE_DAY = date(2026, 9, 5)
_CFG = LadderEvConfig()


def _running_max(reading_f: int) -> RunningMax:
    return RunningMax(
        lower_f=reading_f,
        upper_f=reading_f,
        exact_f=reading_f,
        source_observed_at_ns=0,
        source_received_at_ns=0,
    )


def _passing(**overrides: object) -> ExclusionInputs:
    base = ExclusionInputs(
        station="MDW",
        climate_day=_CLIMATE_DAY,
        now_climate_day=_CLIMATE_DAY,
        hour_lst=14,
        ask=0.40,
        p_lower=0.55,
        running_max=_running_max(70),
        ladder=_LADDER,
        rung_lower=70,
        rung_upper=71,
        width_code=0,
        m_code=0,
        cli_print_exists=False,
        climate_day_started=True,
        at_listing=False,
        interior_prelim_final_trade=False,
        p_computed_without_mt=False,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_control_cell_passes() -> None:
    eligible, reason = exclusion_filter(_passing(), _CFG)
    assert eligible is True
    assert reason == "ok"


def test_x1_hard_no_when_running_max_exceeds_finite_rung_upper() -> None:
    eligible, reason = exclusion_filter(
        _passing(running_max=_running_max(80), rung_lower=70, rung_upper=71),
        _CFG,
    )
    assert eligible is False
    assert reason == "hard_no"


def test_x2_print_lock_when_cli_exists() -> None:
    eligible, reason = exclusion_filter(_passing(cli_print_exists=True), _CFG)
    assert eligible is False
    assert reason == "print_lock"


def test_is_legal_cell_is_the_public_crh_alias() -> None:
    from breezy.strategy.current_rung_hold import decision as crh_decision
    from breezy.strategy.current_rung_hold.decision import _is_legal_cell, is_legal_cell

    assert "is_legal_cell" in crh_decision.__all__
    assert is_legal_cell is _is_legal_cell
    assert is_legal_cell(0, 0) is True
    assert is_legal_cell(0, 1) is False


def test_xc_dump_ask_at_any_hour() -> None:
    eligible, reason = exclusion_filter(_passing(ask=0.03, hour_lst=14), _CFG)
    assert eligible is False
    assert reason == "dump_ask"


def test_xc_dump_ask_wins_on_post_peak_cheap_ask() -> None:
    # V4: Xc before X3 unconditionally. 0.02-ask post-peak records dump_ask.
    eligible, reason = exclusion_filter(
        _passing(hour_lst=17, ask=0.02, p_lower=0.04),
        _CFG,
    )
    assert eligible is False
    assert reason == "dump_ask"


def test_x3_post_peak_lottery() -> None:
    # V4: X3 is hour_lst >= peak + lag AND p_lower <= 0.05 (ask conjunct dropped).
    # MDW peak 16 + lag 1 => hour >= 17. Ask 0.10 is above dump_ask_max.
    eligible, reason = exclusion_filter(
        _passing(hour_lst=17, ask=0.10, p_lower=0.03),
        _CFG,
    )
    assert eligible is False
    assert reason == "post_peak_lottery"


def test_x3_does_not_refuse_post_peak_when_p_lower_is_not_lottery() -> None:
    _eligible, reason = exclusion_filter(
        _passing(hour_lst=17, ask=0.10, p_lower=0.30),
        _CFG,
    )
    assert reason != "post_peak_lottery"


def test_x4_near_certain() -> None:
    eligible, reason = exclusion_filter(_passing(p_lower=0.95), _CFG)
    assert eligible is False
    assert reason == "near_certain"


def test_x5_climatology_without_running_max_after_climate_day_start() -> None:
    eligible, reason = exclusion_filter(
        _passing(running_max=None, p_computed_without_mt=True, climate_day_started=True),
        _CFG,
    )
    assert eligible is False
    assert reason == "climatology"


def test_x6_nyc_degraded() -> None:
    eligible, reason = exclusion_filter(_passing(station="NYC"), _CFG)
    assert eligible is False
    assert reason == "nyc_degraded"


def test_x7_observation_ambiguous() -> None:
    spanning = RunningMax(
        lower_f=71,
        upper_f=72,
        exact_f=None,
        source_observed_at_ns=0,
        source_received_at_ns=0,
    )
    eligible, reason = exclusion_filter(_passing(running_max=spanning), _CFG)
    assert eligible is False
    assert reason == "observation_ambiguous"


def test_x8_illegal_cell() -> None:
    # interior m=1 is illegal (CRH `is_legal_cell`); open-lower is X11.
    eligible, reason = exclusion_filter(_passing(width_code=0, m_code=1), _CFG)
    assert eligible is False
    assert reason == "illegal_cell"


def test_x9_cheap_open() -> None:
    eligible, reason = exclusion_filter(
        _passing(
            ask=0.04,
            running_max=None,
            at_listing=True,
            climate_day_started=False,
            p_computed_without_mt=True,
        ),
        _CFG,
    )
    assert eligible is False
    assert reason == "cheap_open"


def test_x10_interior_revision_is_not_an_entry() -> None:
    eligible, reason = exclusion_filter(
        _passing(interior_prelim_final_trade=True),
        _CFG,
    )
    assert eligible is False
    assert reason == "interior_revision"


def test_x11_open_lower_refused_for_entry() -> None:
    eligible, reason = exclusion_filter(
        _passing(
            width_code=2,
            m_code=0,
            rung_lower=None,
            rung_upper=69,
            running_max=_running_max(65),
        ),
        _CFG,
    )
    assert eligible is False
    assert reason == "open_lower"


def test_outside_entry_window() -> None:
    eligible, reason = exclusion_filter(_passing(hour_lst=11), _CFG)
    assert eligible is False
    assert reason == "outside_entry_window"


def test_dplus1_entry() -> None:
    eligible, reason = exclusion_filter(
        _passing(now_climate_day=date(2026, 9, 4)),
        _CFG,
    )
    assert eligible is False
    assert reason == "dplus1_entry"


def test_dump_ask_is_recorded_before_the_executable_ask_screen() -> None:
    eligible, reason = exclusion_filter(_passing(ask=0.02), _CFG)
    assert eligible is False
    assert reason == "dump_ask"
    assert reason != "not_executable"


def test_cheap_open_is_recorded_before_the_executable_ask_screen() -> None:
    eligible, reason = exclusion_filter(
        _passing(
            ask=0.04,
            running_max=None,
            at_listing=True,
            climate_day_started=False,
            p_computed_without_mt=True,
        ),
        _CFG,
    )
    assert eligible is False
    assert reason == "cheap_open"
    assert reason != "not_executable"


def test_not_executable_fires_after_x_rules() -> None:
    eligible, reason = exclusion_filter(_passing(ask=0.96), _CFG)
    assert eligible is False
    assert reason == "not_executable"
