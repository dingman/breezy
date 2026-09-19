"""X1–X11 + Xc + universe gates (spec §5.2). Pure; no I/O."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

from breezy.strategy.current_rung_hold.decision import is_legal_cell
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.weather_common.running_extreme import RunningMax

__all__ = [
    "ExclusionInputs",
    "ForecastRungRelation",
    "exclusion_filter",
    "forecast_side_is_legal",
]

RungBounds = tuple[int | None, int | None]

_CHEAP_OPEN_ASK = 0.05
_POST_PEAK_P_MAX = 0.05

# Scan-time rung/forecast relation (includes the coarse class ``above``).
# Distinct from ``FORECAST_OUTCOME_ALPHABET`` (settled-outcome labels), which
# has no bare ``above`` — ``above1``/``above2``/``above3+`` are the outcomes.
ForecastRungRelation = Literal[
    "below", "contains", "above", "above1", "above2", "above3+"
]
_FORECAST_RUNG_RELATIONS: Final[frozenset[ForecastRungRelation]] = frozenset(
    {"contains", "above", "above1", "above2", "above3+"}
)


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
    side: Literal["yes", "no"] = "yes"

    def __post_init__(self) -> None:
        if self.side not in ("yes", "no"):
            raise ValueError(f"side must be 'yes' or 'no', was {self.side!r}")


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
    if not (cfg.window_start_hour_lst <= inputs.hour_lst < cfg.window_end_hour_lst):
        return False, "outside_entry_window"
    if cfg.dplus1_require_running_max and inputs.climate_day > inputs.now_climate_day:
        return False, "dplus1_entry"
    # Executable-ask screen AFTER the X-rules (spec §5.2 / §13.9)
    if not (cfg.executable_ask_lower < inputs.ask < cfg.executable_ask_upper):
        return False, "not_executable"
    return True, "ok"


def forecast_side_is_legal(
    *,
    side: Literal["yes", "no"],
    r_relation: ForecastRungRelation,
    width_code: int,
    m_code: int,
) -> bool:
    """Family call-site replacement for X8 (plan §7.4).

    YES: interior or open-upper physical shape (``width_code`` in {0, 1}) and
    ``r_relation`` in {contains, above*}. ``m_code`` may be negative on a
    forecast-implied interior — ``is_legal_cell`` is a helper, not the gate.
    NO: ``r_relation`` in {contains, above*}; ``below`` is ``rung_physically_dead``
    on both legs (L-9 / L-44).
    """
    if r_relation not in _FORECAST_RUNG_RELATIONS:
        return False
    if side == "no":
        return True
    if side != "yes":
        raise ValueError(f"side must be 'yes' or 'no', was {side!r}")
    # m_code is accepted for call-site symmetry with X8; forecast interiors
    # may carry m_code < 0, so physical shape is width, not is_legal_cell.
    _ = m_code
    return width_code in (0, 1)
