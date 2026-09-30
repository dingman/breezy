"""``ForecastQuantileLadderConfig`` -- SL-12/V1 D+1 taker StrategyConfig.

Plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`, §7 row SL-12.

Operator-reserved dollar caps (maximum daily budget; maximum per position)
are deliberately absent -- same posture as ``ladder_ev.config.LadderEvConfig``
(plan §8). ``allow_short`` stays False. There is no live refitting: the
calibration artefact is identified ONLY by a sha-pinned 64-lowercase-hex
digest, checked at construction before any file is read (the byte-level
match against that pin happens in ``calibration_artefact.py``, which is I/O
and so cannot run at config-construction time). ``kelly_stake_fraction`` is
not a field -- sizing never reads it (plan §3.3): a forecast-mode take is
always exactly 1 contract.
"""

from __future__ import annotations

import re
from typing import Final

from nautilus_trader.trading.config import StrategyConfig

__all__ = [
    "AllowShortNotPermittedError",
    "ForecastQuantileLadderConfig",
    "UnpinnedCalibrationArtefactError",
]

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_UNPINNED_SHA256: Final[str] = "0" * 64


class AllowShortNotPermittedError(ValueError):
    """Raised when ``allow_short`` is constructed ``True``. SHORT_YES is forbidden."""


class UnpinnedCalibrationArtefactError(ValueError):
    """Raised when ``calibration_artefact_sha256`` is not a pinned 64-hex sha."""


class ForecastQuantileLadderConfig(StrategyConfig, frozen=True):
    """Configuration for the (S4-infra, shadow-first) ``ForecastQuantileLadderStrategy``.

    Parameters
    ----------
    stations : tuple[str, ...]
        Stations this strategy instance evaluates. Must be non-empty.
    calibration_artefact_path : str
        Filesystem path to the sha-pinned calibration artefact (json: EMOS
        params + rung-probability haircuts). Read by
        ``calibration_artefact.load_calibration_artefact``, never here.
    calibration_artefact_sha256 : str
        The manifest-pinned artefact digest (64 lowercase hex, not
        all-zero). Checked here at construction (format + non-placeholder);
        the byte-level match against the file on disk is checked at load
        time.
    forecast_staleness_bound_ns : int
        Max age of a visible quantile vector versus ``now_ns``. ``0`` means
        no staleness cut (visibility-only, matching
        ``LadderEvConfig.forecast_staleness_bound_ns``). Must be >= 0.
    required_fee_coefficient : float
        Venue taker theta; must match live instrument info (plan §4.2:
        never a flat per-contract fee).

    Not present: ``kelly_stake_fraction`` and the two operator-reserved
    dollar controls (max daily budget, max per position).
    """

    stations: tuple[str, ...] = ()
    calibration_artefact_path: str = ""
    calibration_artefact_sha256: str = ""
    forecast_staleness_bound_ns: int = 0
    required_fee_coefficient: float = 0.0695
    allow_short: bool = False
    shadow_only: bool = True

    def __post_init__(self) -> None:
        if self.allow_short:
            raise AllowShortNotPermittedError(
                "allow_short must stay False; NO exposure only via the native "
                "NO instrument (plan §8)",
            )
        if not self.stations:
            raise ValueError("`stations` must name at least one station")
        if self.forecast_staleness_bound_ns < 0:
            raise ValueError(
                "forecast_staleness_bound_ns must be >= 0, "
                f"was {self.forecast_staleness_bound_ns!r}",
            )
        pin = self.calibration_artefact_sha256
        if not _SHA256_RE.match(pin) or pin == _UNPINNED_SHA256:
            raise UnpinnedCalibrationArtefactError(
                "calibration_artefact_sha256 must be a pinned 64-lowercase-hex "
                f"sha (not all-zero); was {pin!r}. There is no live refitting "
                "(plan §2.2, SL-12).",
            )
