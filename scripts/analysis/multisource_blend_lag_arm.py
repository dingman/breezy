"""F13 Phase A runner: the +60 min lag arm, compared on the keys both files hold.

The shift can legitimately remove a row (a source no longer available before the anchor, an NBP
cycle that drops out). The primary and lag arms are therefore summarised on the SAME key set and
compared as a paired difference; what was lost is diagnosed, and a lost fraction above the
prereg's ``lag_arm_max_lost_fraction`` refuses the run. The pin is an object of three caps
(PIN-R5): ``overall``, ``per_horizon`` (D-1 and D0 each) and ``per_station`` (each station);
exceeding any one refuses. The twin's measured loss can only refuse a run, never loosen a cap.
A key only the lag file holds is a builder inconsistency (the twin is derived from the primary),
never silently dropped.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from breezy.analysis import multisource_blend as msb
from scripts.analysis.multisource_blend_refusal import Refusal

__all__ = [
    "LAG_CAP_KEYS",
    "Key",
    "LagCaps",
    "LagKeys",
    "check_lag_caps",
    "common_scored",
    "lag_loss_report",
    "paired_day_values",
    "parse_lag_caps",
    "split_lag_keys",
]

Key = tuple[str, dt.date, str]
_UNASSIGNED: Final[str] = "unassigned"
LAG_CAP_KEYS: Final[tuple[str, ...]] = ("overall", "per_horizon", "per_station")
_PIN: Final[str] = "lag_arm_max_lost_fraction"


def row_key(row: msb.FeatureRow | msb.ScoredRow) -> Key:
    return (row.station, row.climate_day, row.horizon)


@dataclass(frozen=True, slots=True)
class LagKeys:
    base: frozenset[Key]
    common: frozenset[Key]

    @property
    def lost(self) -> frozenset[Key]:
        return self.base - self.common

    @property
    def lost_fraction(self) -> float:
        return len(self.lost) / len(self.base)


def split_lag_keys(rows: Sequence[msb.FeatureRow], lag_rows: Sequence[msb.FeatureRow]) -> LagKeys:
    """The key sets of the two files; a lag-only key or an empty intersection is a Refusal."""
    base = frozenset(row_key(r) for r in rows)
    lag = frozenset(row_key(r) for r in lag_rows)
    if not base & lag:
        raise Refusal("the +60 min lag feature file has no station-day in common with the base")
    only_lag = lag - base
    if only_lag:
        raise Refusal(
            f"{len(only_lag)} key(s) appear only in the lag feature file (e.g. {min(only_lag)}): "
            "the twin is derived from the primary, so this is a builder inconsistency"
        )
    return LagKeys(base=base, common=base & lag)


@dataclass(frozen=True, slots=True)
class LagCaps:
    """PIN-R5: the pinned maximum lost fractions of the +60 min lag arm."""

    overall: float
    per_horizon: float
    per_station: float


def parse_lag_caps(raw: object) -> LagCaps:
    """The ``lag_arm_max_lost_fraction`` pin as three fractions in [0, 1]; else ``ValueError``."""
    if not isinstance(raw, Mapping) or set(raw) != set(LAG_CAP_KEYS):
        raise ValueError(
            f"pins.{_PIN} must be an object with exactly the keys {list(LAG_CAP_KEYS)}, was {raw!r}"
        )
    for key in LAG_CAP_KEYS:
        value = raw[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not 0.0 <= value <= 1.0
        ):
            raise ValueError(f"pins.{_PIN}.{key} must be a number in [0, 1], was {value!r}")
    return LagCaps(float(raw["overall"]), float(raw["per_horizon"]), float(raw["per_station"]))


def check_lag_caps(keys: LagKeys, caps: LagCaps) -> None:
    """Refuse when the loss exceeds the overall cap, any horizon's cap or any station's cap."""
    breaches: list[str] = []
    if keys.lost_fraction > caps.overall:
        breaches.append(f"overall {keys.lost_fraction:.4f} > {caps.overall}")
    lost = keys.lost
    ordered = sorted(keys.base)
    for label, items, cap in (
        ("horizon", [(k[2], k in lost) for k in ordered], caps.per_horizon),
        ("station", [(k[0], k in lost) for k in ordered], caps.per_station),
    ):
        for name, cell in _breakdown(items).items():
            if cell["fraction"] > cap:
                breaches.append(f"{label} {name!r} {cell['fraction']:.4f} > {cap}")
    if breaches:
        raise Refusal(
            f"the +60 min shift lost {len(lost)} of {len(keys.base)} keys, above the pinned "
            f"{_PIN} cap(s): {'; '.join(breaches)}; no verdict is emitted"
        )


def _mean(values: Sequence[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _cell(total: int, lost: int) -> dict[str, Any]:
    return {"n": total, "lost": lost, "fraction": lost / total if total else 0.0}


def _breakdown(items: Sequence[tuple[str, bool]]) -> dict[str, dict[str, Any]]:
    totals: dict[str, int] = defaultdict(int)
    lost: dict[str, int] = defaultdict(int)
    for name, is_lost in items:
        totals[name] += 1
        lost[name] += int(is_lost)
    return {name: _cell(totals[name], lost[name]) for name in sorted(totals)}


def _lost_vs_kept(
    pairs: Sequence[tuple[bool, float]],
) -> dict[str, float | None]:
    return {
        "lost": _mean([v for is_lost, v in pairs if is_lost]),
        "kept": _mean([v for is_lost, v in pairs if not is_lost]),
    }


def _cycle_changed(
    rows: Sequence[msb.FeatureRow], lag_rows: Sequence[msb.FeatureRow], keys: LagKeys
) -> int | None:
    """Kept keys whose selected NBP cycle differs between the arms; ``None`` if not recorded."""
    cycles = {row_key(r): r.nbp_cycle_ns for r in rows}
    lag_cycles = {row_key(r): r.nbp_cycle_ns for r in lag_rows}
    if all(v is None for v in cycles.values()) and all(v is None for v in lag_cycles.values()):
        return None
    return sum(1 for key in keys.common if cycles[key] != lag_cycles[key])


def lag_loss_report(
    rows: Sequence[msb.FeatureRow],
    lag_rows: Sequence[msb.FeatureRow],
    keys: LagKeys,
    primary_scored: Sequence[msb.ScoredRow],
) -> dict[str, Any]:
    """Lost fraction overall and by horizon/station/fold, lost-vs-kept difficulty, cycle changes."""
    lost = keys.lost
    scored = [s for s in primary_scored if "M0" in s.crps]
    by_fold = [
        (str(s.fold_id) if s.fold_id is not None else _UNASSIGNED, row_key(s) in lost)
        for s in scored
    ]
    return {
        "lost_fraction": keys.lost_fraction,
        "lost_by_horizon": _breakdown([(k[2], k in lost) for k in sorted(keys.base)]),
        "lost_by_station": _breakdown([(k[0], k in lost) for k in sorted(keys.base)]),
        "lost_by_fold": _breakdown(by_fold),
        "lost_vs_kept": {
            "mean_m0_crps": _lost_vs_kept([(row_key(s) in lost, s.crps["M0"]) for s in scored]),
            "mean_abs_truth_minus_q50": _lost_vs_kept(
                [(row_key(r) in lost, abs(r.cli_tmax_f - r.percentiles.q50)) for r in rows]
            ),
        },
        "nbp_cycle_changed": _cycle_changed(rows, lag_rows, keys),
    }


def common_scored(
    primary: Sequence[msb.ScoredRow], lag: Sequence[msb.ScoredRow]
) -> tuple[list[msb.ScoredRow], list[msb.ScoredRow]]:
    """Both arms' scored rows restricted to the keys BOTH scored (the paired comparison set)."""
    shared = {row_key(s) for s in primary} & {row_key(s) for s in lag}
    return (
        [s for s in primary if row_key(s) in shared],
        [s for s in lag if row_key(s) in shared],
    )


def paired_day_values(
    primary: Sequence[msb.ScoredRow],
    lag: Sequence[msb.ScoredRow],
    first: str,
    second: str,
) -> list[tuple[dt.date, float]]:
    """Per day: (primary delta) - (lag delta), over the days both arms have."""
    lag_by_day: Mapping[dt.date, float] = dict(msb.delta_by_day(lag, first, second))
    return [
        (day, value - lag_by_day[day])
        for day, value in msb.delta_by_day(primary, first, second)
        if day in lag_by_day
    ]
