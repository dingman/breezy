"""F13 Phase A blend, part 1: feature inputs, leakage assertions and the sealed-day guard.

Split out of ``breezy.analysis.multisource_blend`` (behaviour-neutral). Pure: no network, no clock,
no file access, no Nautilus import. See that module's docstring for the model overview.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS
from breezy.domain.climate_day import climate_day_for_instant, standard_time_zone
from breezy.strategy.ladder_ev.quantile_density import Percentiles

_NS: Final[int] = 1_000_000_000
_HOUR_NS: Final[int] = 3_600 * _NS
HOLDOUT_START: Final[dt.date] = DEFAULT_SPLITS.holdout_start
#: Plan R15 acceptance 8: every source lag is shifted by this much in the sensitivity rerun.
LAG_SHIFT_NS: Final[int] = 3_600 * _NS
STRICT_24H_LABEL: Final[str] = "diagnostic_only"
PEAK_LST_HOURS: Final[tuple[int, ...]] = tuple(range(12, 19))
HORIZONS: Final[tuple[str, ...]] = ("D0", "D-1")
LEVEL_SOURCES: Final[tuple[str, ...]] = ("lamp", "pfm", "mos")
ARM_NAMES: Final[tuple[str, ...]] = ("M0prime", "M1", "M2", "M3")
#: Floor on the sd of the sources' mu in the disagreement-sigma step (avoids log 0).
DISAGREEMENT_SD_FLOOR_F: Final[float] = 0.1


class NonFiniteInputError(ValueError):
    """A NaN or infinite input; refused, never imputed."""


class LeakageError(RuntimeError):
    """A feature whose availability is not strictly before the anchor."""


class HoldoutLeakError(RuntimeError):
    """A row on or after the sealed holdout start reached a fit, a fold or a score."""


class InsufficientRowsError(ValueError):
    """Not enough rows to fit or to predict a cell."""


class InsufficientFoldsError(ValueError):
    """Fewer folds than a spread needs."""


class PreregIncompleteError(ValueError):
    """A prereg value the computation needs is still null."""


class C1LagEvidenceError(RuntimeError):
    """C1 has not yet measured enough lag days to freeze the source lags."""


# ------------------------------------------------------------------ feature inputs


@dataclass(frozen=True, slots=True)
class ObsReading:
    ts_ns: int
    available_at_ns: int
    temp_f: float
    source: str = "obs"


@dataclass(frozen=True, slots=True)
class LampHour:
    valid_ts_ns: int
    tmp_f: float | None


@dataclass(frozen=True, slots=True)
class LampRun:
    """One LAMP run: ``lavtxt`` and ``lavtxt_ext`` hours merged by the caller."""

    issued_ns: int
    available_at_ns: int
    hours: tuple[LampHour, ...]


@dataclass(frozen=True, slots=True)
class SourceVintage:
    available_at_ns: int
    mu_f: float


def _finite(name: str, value: float | None) -> None:
    if value is not None and not math.isfinite(value):
        raise NonFiniteInputError(f"{name} is not finite ({value!r}); refused, never imputed")


@dataclass(frozen=True, slots=True)
class LampFeature:
    """F13-R35: the remaining-hours LAMP feature and its persisted coverage fields."""

    rem_max_f: float | None
    hours_covered: int
    peak_covered: bool
    missing: bool
    run_available_at_ns: int | None
    min_valid_ts_ns: int | None
    strict_24h_max_f_diagnostic: float | None

    def __post_init__(self) -> None:
        _finite("lamp.rem_max_f", self.rem_max_f)
        _finite("lamp.strict_24h_max_f_diagnostic", self.strict_24h_max_f_diagnostic)
        if self.missing and self.rem_max_f is not None:
            raise ValueError("a missing LAMP feature carries no value (nothing is imputed)")
        if not self.missing and self.rem_max_f is None:
            raise ValueError("a present LAMP feature needs rem_max_f")


MISSING_LAMP: Final[LampFeature] = LampFeature(None, 0, False, True, None, None, None)


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """One station-day at one horizon, with every input available before ``anchor_ns``."""

    station: str
    climate_day: dt.date
    version: str
    horizon: str
    anchor_ns: int
    percentiles: Percentiles
    cli_tmax_f: float
    obs_so_far_f: float | None = None
    obs_available_at_ns: int | None = None
    lamp: LampFeature = MISSING_LAMP
    pfm_mu_f: float | None = None
    pfm_available_at_ns: int | None = None
    mos_mu_f: float | None = None
    mos_available_at_ns: int | None = None

    def __post_init__(self) -> None:
        if self.horizon not in HORIZONS:
            raise ValueError(f"horizon must be one of {HORIZONS}, was {self.horizon!r}")
        p = self.percentiles
        for name in ("q10", "q25", "q50", "q75", "q90", "mean", "sd"):
            _finite(f"percentiles.{name}", getattr(p, name))
        if not p.sd > 0.0:
            raise NonFiniteInputError(f"NBP sd must be positive, was {p.sd!r}")
        _finite("cli_tmax_f", self.cli_tmax_f)
        _finite("obs_so_far_f", self.obs_so_far_f)
        _finite("pfm_mu_f", self.pfm_mu_f)
        _finite("mos_mu_f", self.mos_mu_f)

    @property
    def lamp_input_f(self) -> float | None:
        """``L = max(obs_so_far, lamp_rem_max_f)``; ``None`` when LAMP is missing (R35)."""
        if self.lamp.missing:
            return None
        return combined_lamp_input(self.obs_so_far_f, self.lamp.rem_max_f)

    @property
    def prefix_level(self) -> int:
        """Length of the present prefix of [LAMP, PFM, MOS]."""
        level = 0
        for present in (
            not self.lamp.missing,
            self.pfm_mu_f is not None,
            self.mos_mu_f is not None,
        ):
            if not present:
                break
            level += 1
        return level


def combined_lamp_input(obs_so_far_f: float | None, lamp_rem_max_f: float | None) -> float | None:
    if lamp_rem_max_f is None:
        return None
    if obs_so_far_f is None:
        return lamp_rem_max_f
    return max(obs_so_far_f, lamp_rem_max_f)


def _lst_date(ts_ns: int, offset_hours: float) -> dt.date:
    return climate_day_for_instant(dt.datetime.fromtimestamp(ts_ns // _NS, tz=dt.UTC), offset_hours)


def _lst_midnight_ns(day: dt.date, offset_hours: float) -> int:
    utc = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC) - dt.timedelta(
        hours=offset_hours
    )
    return int(utc.timestamp()) * _NS


def assert_lamp_run_before_anchor(run: LampRun, anchor_ns: int, *, extra_lag_ns: int = 0) -> None:
    if run.available_at_ns + extra_lag_ns >= anchor_ns:
        raise LeakageError(
            f"LAMP run available_at {run.available_at_ns} (+{extra_lag_ns}) is not before the "
            f"anchor {anchor_ns}"
        )


def lamp_remaining_feature(
    runs: Sequence[LampRun],
    *,
    anchor_ns: int,
    climate_day: dt.date,
    std_utc_offset_hours: float,
    extra_lag_ns: int = 0,
) -> LampFeature:
    """F13-R35 ``lamp_rem_max_f`` from the latest run available before the anchor."""
    eligible = [r for r in runs if r.available_at_ns + extra_lag_ns < anchor_ns]
    if not eligible:
        return MISSING_LAMP
    run = max(eligible, key=lambda r: (r.issued_ns, r.available_at_ns))
    assert_lamp_run_before_anchor(run, anchor_ns, extra_lag_ns=extra_lag_ns)
    zone = standard_time_zone(std_utc_offset_hours)
    used: list[tuple[int, float]] = []
    present_hours: set[int] = set()
    for hour in run.hours:
        if hour.valid_ts_ns <= anchor_ns or hour.tmp_f is None:
            continue
        if _lst_date(hour.valid_ts_ns, std_utc_offset_hours) != climate_day:
            continue
        _finite("lamp hour tmp_f", hour.tmp_f)
        used.append((hour.valid_ts_ns, hour.tmp_f))
        present_hours.add(dt.datetime.fromtimestamp(hour.valid_ts_ns // _NS, tz=zone).hour)
    midnight = _lst_midnight_ns(climate_day, std_utc_offset_hours)
    expected = {h for h in PEAK_LST_HOURS if midnight + h * _HOUR_NS > anchor_ns}
    peak_covered = expected <= present_hours
    strict = strict_24h_max_diagnostic(run, climate_day, std_utc_offset_hours)
    if not used or not peak_covered:
        return LampFeature(None, len(used), peak_covered, True, run.available_at_ns, None, strict)
    return LampFeature(
        rem_max_f=max(temp for _ts, temp in used),
        hours_covered=len(used),
        peak_covered=True,
        missing=False,
        run_available_at_ns=run.available_at_ns,
        min_valid_ts_ns=min(ts for ts, _temp in used),
        strict_24h_max_f_diagnostic=strict,
    )


def strict_24h_max_diagnostic(
    run: LampRun, climate_day: dt.date, std_utc_offset_hours: float
) -> float | None:
    """The S3 strict all-24-hours max (``STRICT_24H_LABEL``): never a blend input."""
    window = [h for h in run.hours if _lst_date(h.valid_ts_ns, std_utc_offset_hours) == climate_day]
    if len(window) != 24 or any(h.tmp_f is None for h in window):
        return None
    return max(h.tmp_f for h in window if h.tmp_f is not None)


def _eligible_obs(
    readings: Sequence[ObsReading], anchor_ns: int, climate_day: dt.date, offset: float
) -> list[ObsReading]:
    chosen: list[ObsReading] = []
    for reading in readings:
        if "lamp" in reading.source.lower():
            raise LeakageError("obs_so_far is never sourced from LAMP")
        if reading.available_at_ns >= anchor_ns or reading.ts_ns > anchor_ns:
            continue
        if _lst_date(reading.ts_ns, offset) != climate_day:
            continue
        _finite("obs temp_f", reading.temp_f)
        chosen.append(reading)
    return chosen


def obs_so_far(
    readings: Sequence[ObsReading],
    *,
    anchor_ns: int,
    climate_day: dt.date,
    std_utc_offset_hours: float,
) -> float | None:
    """Max observed temperature so far in the climate day; ``None`` when none exists (D-1)."""
    chosen = _eligible_obs(readings, anchor_ns, climate_day, std_utc_offset_hours)
    return max(r.temp_f for r in chosen) if chosen else None


def _latest_vintage(
    vintages: Sequence[SourceVintage], anchor_ns: int, extra_lag_ns: int
) -> SourceVintage | None:
    eligible = [v for v in vintages if v.available_at_ns + extra_lag_ns < anchor_ns]
    return max(eligible, key=lambda v: v.available_at_ns) if eligible else None


def assemble_feature_row(
    *,
    station: str,
    climate_day: dt.date,
    version: str,
    horizon: str,
    anchor_ns: int,
    std_utc_offset_hours: float,
    percentiles: Percentiles,
    cli_tmax_f: float,
    obs_readings: Sequence[ObsReading] = (),
    lamp_runs: Sequence[LampRun] = (),
    pfm_vintages: Sequence[SourceVintage] = (),
    mos_vintages: Sequence[SourceVintage] = (),
    extra_lag_ns: int = 0,
) -> FeatureRow:
    """Build one row from raw inputs, taking only vintages available before the anchor."""
    chosen_obs = _eligible_obs(obs_readings, anchor_ns, climate_day, std_utc_offset_hours)
    pfm = _latest_vintage(pfm_vintages, anchor_ns, extra_lag_ns)
    mos = _latest_vintage(mos_vintages, anchor_ns, extra_lag_ns)
    row = FeatureRow(
        station=station,
        climate_day=climate_day,
        version=version,
        horizon=horizon,
        anchor_ns=anchor_ns,
        percentiles=percentiles,
        cli_tmax_f=cli_tmax_f,
        obs_so_far_f=max(r.temp_f for r in chosen_obs) if chosen_obs else None,
        obs_available_at_ns=max(r.available_at_ns for r in chosen_obs) if chosen_obs else None,
        lamp=lamp_remaining_feature(
            lamp_runs,
            anchor_ns=anchor_ns,
            climate_day=climate_day,
            std_utc_offset_hours=std_utc_offset_hours,
            extra_lag_ns=extra_lag_ns,
        ),
        pfm_mu_f=None if pfm is None else pfm.mu_f,
        pfm_available_at_ns=None if pfm is None else pfm.available_at_ns,
        mos_mu_f=None if mos is None else mos.mu_f,
        mos_available_at_ns=None if mos is None else mos.available_at_ns,
    )
    assert_row_leakage_free(row)
    return row


def assert_row_leakage_free(row: FeatureRow) -> None:
    """The scored-row assertion: ``max(available_at) < anchor`` and ``min(valid_ts) > anchor``."""
    pairs = (
        ("obs", row.obs_so_far_f, row.obs_available_at_ns),
        ("pfm", row.pfm_mu_f, row.pfm_available_at_ns),
        ("mos", row.mos_mu_f, row.mos_available_at_ns),
    )
    for name, value, available in pairs:
        if value is None:
            continue
        if available is None or available >= row.anchor_ns:
            raise LeakageError(
                f"{name} available_at {available} is not before the anchor {row.anchor_ns} "
                f"({row.station} {row.climate_day} {row.horizon})"
            )
    lamp = row.lamp
    if lamp.run_available_at_ns is not None and lamp.run_available_at_ns >= row.anchor_ns:
        raise LeakageError(
            f"LAMP run available_at {lamp.run_available_at_ns} is not before the anchor"
        )
    if lamp.min_valid_ts_ns is not None and lamp.min_valid_ts_ns <= row.anchor_ns:
        raise LeakageError(f"LAMP hour valid_ts {lamp.min_valid_ts_ns} is not after the anchor")
    if not lamp.missing and (lamp.run_available_at_ns is None or lamp.min_valid_ts_ns is None):
        raise LeakageError("a present LAMP feature must carry its run availability and first hour")


def assert_pre_holdout(rows: Sequence[FeatureRow]) -> None:
    for row in rows:
        if row.climate_day >= HOLDOUT_START:
            raise HoldoutLeakError(
                f"climate day {row.climate_day} is on or after the sealed start {HOLDOUT_START}"
            )


def _assert_admissible(rows: Sequence[FeatureRow]) -> None:
    assert_pre_holdout(rows)
    for row in rows:
        assert_row_leakage_free(row)
