"""Pure, outcome-blind transformations and invariants for the LEAK-NULL study."""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

import breezy.analysis.multisource_blend as msb

# Shared public refusal type without importing the I/O layer or a sibling core.
Refusal = msb.PreregIncompleteError
type LabelKey = tuple[str, str, dt.date]
type RowKey = tuple[str, str, dt.date, str]


class NullId(StrEnum):
    N1 = "N1_within_version"
    N2 = "N2_penalty_off"
    N3 = "N3_scrambled_sources"


def subseed(seed: int, tag: str) -> int:
    return int(hashlib.sha256(f"leak_null:{seed}:{tag}".encode()).hexdigest()[:16], 16)


@dataclass(frozen=True, slots=True)
class NullLabels:
    rows: tuple[msb.FeatureRow, ...]
    moved_fraction: float

    def __post_init__(self) -> None:
        if not self.rows or not 0.5 <= self.moved_fraction <= 1.0:
            raise Refusal("moved_fraction must be at least 0.5 over nonempty rows")


def null_label_rows(rows: Sequence[msb.FeatureRow], seed: int) -> NullLabels:
    """Replay shuffle provenance by station-day KEY, even when label values tie."""
    labels: dict[LabelKey, float] = {}
    groups: dict[str, list[LabelKey]] = {}
    for row in rows:
        key = row.version, row.station, row.climate_day
        if key not in labels:
            labels[key] = row.cli_tmax_f
            groups.setdefault(row.version, []).append(key)
        elif labels[key] != row.cli_tmax_f:
            raise Refusal("inconsistent labels for a station-day key")
    rng = random.Random(seed)
    sources: dict[LabelKey, LabelKey] = {}
    for keys in groups.values():
        permuted = keys.copy()
        rng.shuffle(permuted)
        sources.update(zip(keys, permuted, strict=True))
    moved = sum(k != source for k, source in sources.items()) / len(labels) if labels else 0.0
    if moved < 0.5:
        raise Refusal(f"moved_fraction {moved} is below 0.5")
    shuffled = tuple(msb.shuffle_labels(rows, seed=seed))
    expected = tuple(
        replace(r, cli_tmax_f=labels[sources[(r.version, r.station, r.climate_day)]]) for r in rows
    )
    if shuffled != expected:
        raise Refusal("label permutation replay mismatch with msb.shuffle_labels")
    return NullLabels(shuffled, moved)


def _source_value(row: msb.FeatureRow, source: str) -> float | None:
    if source == "lamp":
        return None if row.lamp.missing else row.lamp.rem_max_f
    return row.pfm_mu_f if source == "pfm" else row.mos_mu_f


def _replace_source(row: msb.FeatureRow, source: str, value: float | None) -> msb.FeatureRow:
    if source == "lamp":
        return replace(row, lamp=replace(row.lamp, rem_max_f=value))
    if source == "pfm":
        return replace(row, pfm_mu_f=value)
    return replace(row, mos_mu_f=value)


def scramble_sources(labels: NullLabels, seed: int) -> NullLabels:
    """Permute present values within version/horizon; keep availability with the row."""
    rows = list(labels.rows)
    for source in ("lamp", "pfm", "mos"):
        groups: dict[tuple[str, str], list[int]] = {}
        for i, row in enumerate(rows):
            if _source_value(row, source) is not None:
                groups.setdefault((row.version, row.horizon), []).append(i)
        rng = random.Random(subseed(seed, f"scramble:{source}"))
        for indices in groups.values():
            values = [_source_value(rows[i], source) for i in indices]
            rng.shuffle(values)
            for i, value in zip(indices, values, strict=True):
                rows[i] = _replace_source(rows[i], source, value)
    return NullLabels(tuple(rows), labels.moved_fraction)


def plant_leak(labels: NullLabels, *, seed: int, noise_sd_f: float) -> NullLabels:
    if not math.isfinite(noise_sd_f) or noise_sd_f < 0:
        raise Refusal("plant noise_sd_f must be finite and nonnegative")
    rng = random.Random(subseed(seed, "plant"))
    rows = tuple(
        r
        if r.lamp.missing
        else replace(
            r,
            lamp=replace(r.lamp, rem_max_f=r.cli_tmax_f + rng.gauss(0.0, noise_sd_f)),
        )
        for r in labels.rows
    )
    return NullLabels(rows, labels.moved_fraction)


def null_settings(settings: msb.BlendSettings, null_id: NullId) -> msb.BlendSettings:
    return replace(settings, weight_sum_lambda=0.0) if null_id == NullId.N2 else settings


def _key(row: msb.FeatureRow | msb.ScoredRow) -> RowKey:
    return row.version, row.station, row.climate_day, row.horizon


def _effective_train(
    rows: Sequence[msb.FeatureRow],
    fold: msb.Fold,
    embargo_days: int,
) -> tuple[msb.FeatureRow, ...]:
    """Independent of folds._blocked_days, including its closed embargo endpoints."""
    return tuple(
        r
        for r in rows
        if r.version == fold.version
        and r.climate_day in fold.train_days
        and all(abs((r.climate_day - held).days) > embargo_days for held in fold.held_days)
    )


def fold_disjointness_defects(
    rows: Sequence[msb.FeatureRow],
    plan: msb.FoldPlan,
    embargo_days: int,
) -> tuple[str, ...]:
    if isinstance(embargo_days, bool) or not isinstance(embargo_days, int) or embargo_days < 0:
        return ("embargo_days must be a nonnegative integer",)
    defects: list[str] = []
    counts: Counter[tuple[str, dt.date]] = Counter()
    ids: Counter[int] = Counter()
    for fold in plan.folds:
        ids[fold.fold_id] += 1
        for day in fold.train_days:
            counts.setdefault((fold.version, day), 0)
        counts.update((fold.version, day) for day in fold.held_days)
        held = {
            _key(r) for r in rows if r.version == fold.version and r.climate_day in fold.held_days
        }
        # Reject corrupt declarations even though the effective filter masks their overlap.
        if set(fold.train_days) & set(fold.held_days):
            defects.append(f"fold {fold.fold_id}: declared held/train overlap")
        train = _effective_train(rows, fold, embargo_days)
        if held & {_key(r) for r in train}:
            defects.append(f"fold {fold.fold_id}: effective held/train key overlap")
        if any(
            abs((r.climate_day - h).days) <= embargo_days for r in train for h in fold.held_days
        ):
            defects.append(f"fold {fold.fold_id}: effective embargo violation")
    if any(n != 1 for n in ids.values()):
        defects.append("duplicate fold_id")
    defects.extend(
        f"{version}/{day}: held {n} times" for (version, day), n in counts.items() if n != 1
    )
    return tuple(defects)


def scored_fold_defects(scored: Sequence[msb.ScoredRow], plan: msb.FoldPlan) -> tuple[str, ...]:
    folds = {f.fold_id: f for f in plan.folds}
    defects = []
    for row in scored:
        fold = folds.get(row.fold_id) if row.fold_id is not None else None
        if fold is None or row.version != fold.version or row.climate_day not in fold.held_days:
            defects.append(f"{_key(row)}: invalid held row for fold {row.fold_id}")
    return tuple(defects)


def _finite_abs(value: float) -> float:
    return abs(value) if math.isfinite(value) else math.inf


def level0_max_abs(scored: Sequence[msb.ScoredRow]) -> float:
    if any("M3" not in r.levels for r in scored):
        return math.inf
    return max(
        (
            _finite_abs(r.crps.get("M0prime", math.inf) - r.crps.get("M3", math.inf))
            for r in scored
            if r.levels["M3"] == 0
        ),
        default=0.0,
    )


def m0prime_max_abs(a: Sequence[msb.ScoredRow], b: Sequence[msb.ScoredRow]) -> float:
    if len(a) != len(b):
        return math.inf
    if any((_key(x), x.fold_id) != (_key(y), y.fold_id) for x, y in zip(a, b, strict=True)):
        return math.inf
    return max(
        (
            _finite_abs(x.crps.get("M0prime", math.inf) - y.crps.get("M0prime", math.inf))
            for x, y in zip(a, b, strict=True)
        ),
        default=0.0,
    )


def prefix_preserved(before: Sequence[msb.FeatureRow], after: Sequence[msb.FeatureRow]) -> bool:
    return len(before) == len(after) and all(
        (_key(a), a.prefix_level) == (_key(b), b.prefix_level)
        for a, b in zip(before, after, strict=True)
    )
