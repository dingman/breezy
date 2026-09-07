"""X1–X11 + Xc + universe gates (spec §5.2). Pure; no I/O."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from breezy.strategy.current_rung_hold.decision import is_legal_cell
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.weather_common.running_extreme import RunningMax

__all__ = ["ExclusionInputs", "exclusion_filter"]

RungBounds = tuple[int | None, int | None]

_ENTRY_WINDOW_START_HOUR = 12
_ENTRY_WINDOW_END_HOUR = 17
_CHEAP_OPEN_ASK = 0.05
_POST_PEAK_P_MAX = 0.05


@dataclass(frozen=True, slots=True, kw_only=True)
class ExclusionInputs:
    """Facts :func:`exclusion_filter` needs, passed in by the caller."""

    station: str
    climate_day: date
    now_climate_day: date
    hour_lst: float
    ask: float
    p_lower: float
    running_max: RunningMax | None
    ladder: Sequence[RungBounds]
    rung_lower: int | None
    rung_upper: int | None
    width_code: int
    m_code: int
    cli_print_exists: bool
    climate_day_started: bool
    at_listing: bool
    interior_prelim_final_trade: bool
    p_computed_without_mt: bool


def _peak_hour(station: str, cfg: LadderEvConfig) -> int | None:
    for name, hour in cfg.peak_hour_lst:
        if name == station:
            return hour
    return None


def _x3_match(inputs: ExclusionInputs, cfg: LadderEvConfig) -> bool:
    peak = _peak_hour(inputs.station, cfg)
    if peak is None:
        return False
    return inputs.hour_lst >= peak + cfg.diurnal_peak_lag_h and inputs.p_lower <= _POST_PEAK_P_MAX


def exclusion_filter(inputs: ExclusionInputs, cfg: LadderEvConfig) -> tuple[bool, str]:
    """First-match refuse reasons in spec §5.2 order. ``('ok')`` when eligible."""
    running_max = inputs.running_max
    # X1
    if (
        running_max is not None
        and inputs.rung_upper is not None
        and running_max.lower_f > inputs.rung_upper
    ):
        return False, "hard_no"
    # X2
    if inputs.cli_print_exists:
        return False, "print_lock"
    # Xc — before X3 unconditionally so dump_ask and post_peak_lottery partition.
    if inputs.ask <= cfg.dump_ask_max:
        return False, "dump_ask"
    # X3
    if _x3_match(inputs, cfg):
        return False, "post_peak_lottery"
    # X4
    if inputs.p_lower >= cfg.lock_p_max:
        return False, "near_certain"
    # X5
    if inputs.climate_day_started and (running_max is None or inputs.p_computed_without_mt):
        return False, "climatology"
    # X6
    if cfg.nyc_degraded_excluded and inputs.station == "NYC":
        return False, "nyc_degraded"
    # X7
    if running_max is not None and running_max.spans(inputs.ladder):
        return False, "observation_ambiguous"
    # X8 (open-lower is X11, not illegal_cell)
    if not is_legal_cell(inputs.width_code, inputs.m_code) and inputs.width_code != 2:
        return False, "illegal_cell"
    # X9
    if inputs.at_listing and running_max is None and inputs.ask <= _CHEAP_OPEN_ASK:
        return False, "cheap_open"
    # X10
    if inputs.interior_prelim_final_trade:
        return False, "interior_revision"
    # X11
    if inputs.width_code == 2:
        return False, "open_lower"
    # Universe gates
    if not (_ENTRY_WINDOW_START_HOUR <= inputs.hour_lst < _ENTRY_WINDOW_END_HOUR):
        return False, "outside_entry_window"
    if cfg.dplus1_require_running_max and inputs.climate_day > inputs.now_climate_day:
        return False, "dplus1_entry"
    # Executable-ask screen AFTER the X-rules (spec §5.2 / §13.9)
    if not (cfg.executable_ask_lower < inputs.ask < cfg.executable_ask_upper):
        return False, "not_executable"
    return True, "ok"
