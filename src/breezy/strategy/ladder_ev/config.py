"""``LadderEvConfig`` — LADDER_EV stage-1 StrategyConfig (spec §10).

Operator-reserved dollar caps (maximum daily budget; maximum per position)
are deliberately absent. ``allow_short`` stays False; ``mode='full'`` is
refused at construction. ``mode='forecast'`` is a third legal branch;
its corpus pin is supplied by the family manifest, never a src constant.
"""

from __future__ import annotations

import re
from typing import Final

from nautilus_trader.trading.config import StrategyConfig

from breezy.strategy.ladder_ev.density_table import (
    CORPUS_SHA256,
    ForecastCorpusPinMismatchError,
)

__all__ = [
    "AllowShortNotPermittedError",
    "ForecastCorpusPinMismatchError",
    "LadderEvConfig",
    "ModeFullNotPermittedError",
    "RawCorpusPinMismatchError",
]

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_UNPINNED_SHA256: Final[str] = "0" * 64

_PEAK_HOUR_LST_DEFAULT: tuple[tuple[str, int], ...] = (
    ("LAX", 15),
    ("MDW", 16),
    ("MIA", 15),
    ("SFO", 16),
    ("NYC", 16),
)


class AllowShortNotPermittedError(ValueError):
    """Raised when ``allow_short`` is constructed ``True``. SHORT_YES is forbidden."""


class ModeFullNotPermittedError(ValueError):
    """Raised when ``mode`` is constructed ``'full'``. ``degraded`` or ``forecast`` only."""


class RawCorpusPinMismatchError(ValueError):
    """Raised when ``raw_corpus_pin`` does not equal ``CORPUS_SHA256``."""


class LadderEvConfig(StrategyConfig, frozen=True):
    """Configuration for the (stage-2) ``LadderEvStrategy``.

    Parameters
    ----------
    scan_interval_s : int
        Scan timer interval, seconds **ASSUMED**.
    rediscover_interval_s : int
        Rediscover timer interval, seconds **ASSUMED**.
    stale_quote_seconds : int
        Quote-age bound versus clock now, seconds **ASSUMED**.
    stale_observation_minutes : int
        Observation-liveness bound, minutes.
    executable_ask_lower, executable_ask_upper : float
        Open executable-ask band, probability.
    order_quantity : int
        Contracts per order.
    min_fillable_qty : float
        Minimum fillable size, contracts.
    slippage_floor_prob : float
        Slippage floor inside ``DepthAwareTradeCost``, probability **UNMEASURED**.
    required_fee_coefficient : float
        Venue taker theta; must match live instrument info.
    dump_ask_max : float
        Xc dump-ask ceiling, probability.
    lock_p_max : float
        X4 near-certain ``P^L`` ceiling, probability.
    diurnal_peak_lag_h : int
        Post-peak lag for X3, hours **ASSUMED**.
    peak_hour_lst : tuple[tuple[str, int], ...]
        Per-station diurnal peak hour LST **ASSUMED** (spec §5.2).
    n_min_cell : int
        Minimum cell count before ``margin`` is finite (counts).
    margin_m0 : float
        Margin at ``h0``, probability **ASSUMED**.
    margin_m24 : float
        Margin at 24 h, probability (pinned B1).
    margin_h0_hours : int
        Horizon at which margin equals ``m0``, hours **ASSUMED**.
    reaction_latency_s : float
        Fill-timing latency, seconds **ASSUMED**.
    uncertainty_penalty : float
        ``λ_u`` on the ranking score, dimensionless **ASSUMED**.
    max_simultaneous_positions : int
        Open-position ceiling, count **ASSUMED**.
    max_per_city_day : int
        Hard cap on YES per city-day, count.
    kelly_enabled : bool
        Fractional-Kelly gate; False until unlock.
    kelly_fraction : float
        κ in ``κ·(P−C)/(1−C)``, dimensionless.
    kelly_unlock_n : int
        Live fills required before Kelly may be enabled.
    entry_only_halt : bool
        Settlement halt applies only to new entries.
    allow_short : bool
        Must stay ``False``.
    nyc_degraded_excluded : bool
        NYC is out of the DEGRADED ENTRY universe.
    dplus1_require_running_max : bool
        D+1 rows are audit-only in DEGRADED.
    forecast_revision_invalidate_f : float
        FULL-only invalidation threshold, °F **ASSUMED**.
    exit_edge : float
        Audit-only exit buffer, probability **ASSUMED**.
    exit_sell_enabled : bool
        False; exits are audit-only in v2.
    mode : str
        ``degraded`` or ``forecast``; ``full`` refused at construction.
    raw_corpus_pin : str
        Pin of the RAW archive corpus bytes CRH's selector was built from
        (``generate_current_rung_hold_archive_table.py:115-125``). NOT a hash
        of the 6-rung table. The on-disk 6-rung freeze is NOT RUN
        (``ON_DISK_BUILD_RAN=False``).
    se_z : float
        FULL-only z; unused in DEGRADED.
    window_start_hour_lst, window_end_hour_lst : int
        Inclusive/exclusive LST entry window (E1). Defaults 12/17.
    forecast_staleness_bound_ns : int
        Max age of a visible forecast versus ``now_ns``. ``0`` means no
        staleness cut (visibility-only). Must be >= 0.
    publication_lag_ns : int
        Ingest vintage offset (``available_at_ns = cycle + lag``). ``0``
        means no added lag. Must be >= 0.
    forecast_corpus_pin : str
        Manifest-pinned ``density_artefact_sha256``. Empty in DEGRADED;
        required 64 lowercase hex (not all-zero) in ``mode='forecast'``.
        The sha lives on the family manifest, not as a source constant.

    Not present: the two operator-reserved dollar controls.
    """

    scan_interval_s: int = 15
    rediscover_interval_s: int = 300
    stale_quote_seconds: int = 30
    stale_observation_minutes: int = 50
    executable_ask_lower: float = 0.05
    executable_ask_upper: float = 0.95
    order_quantity: int = 1
    min_fillable_qty: float = 1.0
    slippage_floor_prob: float = 0.01
    required_fee_coefficient: float = 0.06
    dump_ask_max: float = 0.03
    lock_p_max: float = 0.95
    diurnal_peak_lag_h: int = 1
    peak_hour_lst: tuple[tuple[str, int], ...] = _PEAK_HOUR_LST_DEFAULT
    n_min_cell: int = 90
    margin_m0: float = 0.02
    margin_m24: float = 0.06
    margin_h0_hours: int = 6
    reaction_latency_s: float = 1.0
    uncertainty_penalty: float = 1.0
    max_simultaneous_positions: int = 4
    max_per_city_day: int = 1
    kelly_enabled: bool = False
    kelly_fraction: float = 0.25
    kelly_unlock_n: int = 40
    entry_only_halt: bool = True
    allow_short: bool = False
    nyc_degraded_excluded: bool = True
    dplus1_require_running_max: bool = True
    forecast_revision_invalidate_f: float = 1.5
    exit_edge: float = 0.015
    exit_sell_enabled: bool = False
    mode: str = "degraded"
    raw_corpus_pin: str = CORPUS_SHA256
    se_z: float = 1.96
    window_start_hour_lst: int = 12
    window_end_hour_lst: int = 17
    forecast_staleness_bound_ns: int = 0
    publication_lag_ns: int = 0
    forecast_corpus_pin: str = ""

    def __post_init__(self) -> None:
        if self.allow_short:
            raise AllowShortNotPermittedError(
                "allow_short must stay False; SHORT_YES is forbidden"
            )
        if self.mode == "full":
            raise ModeFullNotPermittedError(
                "mode='full' is refused; legal modes are 'degraded' and 'forecast'"
            )
        if self.mode not in ("degraded", "forecast"):
            raise ValueError(
                f"mode must be 'degraded' or 'forecast', was {self.mode!r}"
            )
        if self.n_min_cell < 1:
            raise ValueError(f"n_min_cell must be >= 1, was {self.n_min_cell!r}")
        if self.margin_m24 < self.margin_m0:
            raise ValueError(
                f"margin_m24 ({self.margin_m24!r}) must be >= margin_m0 ({self.margin_m0!r})"
            )
        if self.executable_ask_lower >= self.executable_ask_upper:
            raise ValueError(
                "executable_ask_lower must be < executable_ask_upper, "
                f"was {self.executable_ask_lower!r} >= {self.executable_ask_upper!r}"
            )
        if self.window_start_hour_lst >= self.window_end_hour_lst:
            raise ValueError(
                "window_start_hour_lst must be < window_end_hour_lst, "
                f"was {self.window_start_hour_lst!r} >= {self.window_end_hour_lst!r}"
            )
        if self.forecast_staleness_bound_ns < 0:
            raise ValueError(
                "forecast_staleness_bound_ns must be >= 0, "
                f"was {self.forecast_staleness_bound_ns!r}"
            )
        if self.publication_lag_ns < 0:
            raise ValueError(
                f"publication_lag_ns must be >= 0, was {self.publication_lag_ns!r}"
            )
        if self.raw_corpus_pin != CORPUS_SHA256:
            raise RawCorpusPinMismatchError(
                "raw_corpus_pin must equal density_table.CORPUS_SHA256 "
                f"({CORPUS_SHA256!r}), was {self.raw_corpus_pin!r}"
            )
        if self.mode == "forecast":
            pin = self.forecast_corpus_pin
            if not _SHA256_RE.match(pin) or pin == _UNPINNED_SHA256:
                raise ForecastCorpusPinMismatchError(
                    "forecast_corpus_pin must equal the manifest-pinned "
                    "density_artefact_sha256 (64 lowercase hex, not all-zero); "
                    f"was {pin!r}"
                )
