"""F13 Phase A blend, part 3: blocked folds, out-of-fold scoring (blend arms and champion M0).

Split out of ``breezy.analysis.multisource_blend``; re-exported by that facade.
"""

from __future__ import annotations

import datetime as dt
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from breezy.analysis.multisource_blend_features import (
    ARM_NAMES,
    HOLDOUT_START,
    FeatureRow,
    HoldoutLeakError,
    InsufficientRowsError,
    _assert_admissible,
    _finite,
    validate_percentiles,
)
from breezy.analysis.multisource_blend_fit import (
    BlendSettings,
    fit_blend,
    intended_level,
    predict_row,
    row_crps,
    student_t_cdf,
)
from breezy.analysis.nbp_calibration import (
    DEFAULT_BOOTSTRAP_DRAWS,
    DEFAULT_SPLITS,
    VersionRow,
    crps_numerical,
    fit_calibration,
)
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    apply_emos,
    build_cdf,
)


@dataclass(frozen=True, slots=True)
class Fold:
    fold_id: int
    version: str
    segment: int
    held_days: tuple[dt.date, ...]
    train_days: tuple[dt.date, ...]


@dataclass(frozen=True, slots=True)
class FoldPlan:
    folds: tuple[Fold, ...]
    excluded: tuple[tuple[str, int, str], ...]


def days_by_version(rows: Sequence[FeatureRow]) -> dict[str, tuple[dt.date, ...]]:
    grouped: dict[str, set[dt.date]] = {}
    for row in rows:
        grouped.setdefault(row.version, set()).add(row.climate_day)
    return {version: tuple(sorted(days)) for version, days in grouped.items()}


def build_folds(
    days: Mapping[str, Sequence[dt.date]],
    *,
    source_breaks: Sequence[dt.date],
    block_days: int = 28,
    min_train_days: int = 28,
    min_blocks: int = 2,
) -> FoldPlan:
    """Blocked folds within each NBM version AND each source-break segment.

    A segment enters only with at least ``min_blocks`` blocks of at least ``block_days`` held days
    and at least ``min_train_days`` train days. The remainder joins the last block. No fold's held
    or train days cross a break, so a fold never straddles a source break.
    """
    for version_days in days.values():
        for day in version_days:
            if day >= HOLDOUT_START:
                raise HoldoutLeakError(f"climate day {day} is on or after {HOLDOUT_START}")
    breaks = sorted(source_breaks)
    folds: list[Fold] = []
    excluded: list[tuple[str, int, str]] = []
    for version in sorted(days):
        segments: dict[int, list[dt.date]] = {}
        for day in sorted(set(days[version])):
            segments.setdefault(sum(1 for b in breaks if day >= b), []).append(day)
        for segment, ordered in sorted(segments.items()):
            n_blocks = len(ordered) // block_days
            if n_blocks < min_blocks:
                excluded.append(
                    (version, segment, f"{len(ordered)} days: fewer than {min_blocks} blocks")
                )
                continue
            blocks = [ordered[i * block_days : (i + 1) * block_days] for i in range(n_blocks)]
            blocks[-1] = ordered[(n_blocks - 1) * block_days :]
            if len(ordered) - max(len(b) for b in blocks) < min_train_days:
                excluded.append(
                    (
                        version,
                        segment,
                        f"{len(ordered)} days: fewer than {min_train_days} train days",
                    )
                )
                continue
            for block in blocks:
                held = set(block)
                folds.append(
                    Fold(
                        fold_id=len(folds),
                        version=version,
                        segment=segment,
                        held_days=tuple(block),
                        train_days=tuple(d for d in ordered if d not in held),
                    )
                )
    return FoldPlan(folds=tuple(folds), excluded=tuple(excluded))


# ------------------------------------------------------------------ out-of-fold scoring


@dataclass(frozen=True, slots=True)
class ArmPrediction:
    mu: float
    sigma: float
    nu: float

    def __post_init__(self) -> None:
        for name in ("mu", "sigma", "nu"):
            _finite(f"arm {name}", getattr(self, name))
        if not self.sigma > 0.0:
            raise ValueError(f"arm sigma must be positive, was {self.sigma!r}")
        if not self.nu > 0.0:
            raise ValueError(f"arm nu must be positive, was {self.nu!r}")


@dataclass(frozen=True, slots=True)
class ChampionSpec:
    """The champion's out-of-fold calibrated CDF: bulletin + fitted EMOS params."""

    method: str
    percentiles: Percentiles
    a: float
    gamma: float
    delta: float

    def __post_init__(self) -> None:
        validate_percentiles(self.percentiles)
        for name in ("a", "gamma", "delta"):
            _finite(f"champion {name}", getattr(self, name))


@dataclass(frozen=True, slots=True)
class ScoredRow:
    station: str
    climate_day: dt.date
    horizon: str
    version: str
    fold_id: int | None
    observed_f: float
    crps: Mapping[str, float]
    arm_predictions: Mapping[str, ArmPrediction]
    champion: ChampionSpec | None
    #: effective ladder level each blend arm scored this row at (S3 diagnostics)
    levels: Mapping[str, int] = field(default_factory=dict)
    #: arms whose row scored below its intended level (a missing or non-converged cell; P2)
    fell_back: tuple[str, ...] = ()


def champion_cdf(spec: ChampionSpec) -> Callable[[float], float]:
    return apply_emos(
        build_cdf(CdfMethod[spec.method], spec.percentiles),
        spec.percentiles,
        EmosParams(a=spec.a, gamma=spec.gamma, delta=spec.delta),
    )


def blend_cdf(prediction: ArmPrediction) -> Callable[[float], float]:
    return student_t_cdf(prediction.mu, prediction.sigma, prediction.nu)


def _version_row(row: FeatureRow) -> VersionRow:
    return VersionRow(
        version=row.version,
        split=DEFAULT_SPLITS.split_for_date(row.climate_day),
        station=row.station,
        climate_day=row.climate_day,
        percentiles=row.percentiles,
        cli_tmax_f=row.cli_tmax_f,
    )


def _champion_rows(
    pool: Sequence[FeatureRow], held: Sequence[FeatureRow], method: CdfMethod, draws: int
) -> list[tuple[float, ChampionSpec]]:
    """M0 scored out of fold: ``fit_calibration`` on ``pool`` (see :func:`_m0_pool`), then the
    held rows only."""
    fit = fit_calibration([_version_row(r) for r in pool], method=method, bootstrap_draws=draws)
    out: list[tuple[float, ChampionSpec]] = []
    for row in held:
        estimate = fit.hierarchical.shrunk_by_version[row.version]
        spec = ChampionSpec(method.name, row.percentiles, estimate.a, estimate.gamma, fit.delta)
        out.append(
            (
                crps_numerical(champion_cdf(spec), row.cli_tmax_f, center=row.percentiles.q50),
                spec,
            )
        )
    return out


def _check_embargo(embargo_days: int) -> None:
    if isinstance(embargo_days, bool) or not isinstance(embargo_days, int) or embargo_days < 0:
        raise ValueError(f"embargo_days must be a non-negative int, was {embargo_days!r}")


def _blocked_days(fold: Fold, embargo_days: int) -> frozenset[dt.date]:
    """The held days plus every day within ``embargo_days`` of one: never trained on."""
    return frozenset(
        held + dt.timedelta(days=k)
        for held in fold.held_days
        for k in range(-embargo_days, embargo_days + 1)
    )


def _m0_pool(rows: Sequence[FeatureRow], fold: Fold, embargo_days: int) -> list[FeatureRow]:
    """S1: the held version's ``fold.train_days`` (same source segment) plus every other version's
    rows, embargoed around the held block. Never padded with the held version's other segments."""
    blocked, train = _blocked_days(fold, embargo_days), set(fold.train_days)
    return [
        r
        for r in rows
        if r.climate_day not in blocked and (r.version != fold.version or r.climate_day in train)
    ]


def _pooled_sensitivity_pool(
    rows: Sequence[FeatureRow], fold: Fold, embargo_days: int
) -> list[FeatureRow]:
    """The pre-S1 pool, kept as a reported sensitivity: every pre-holdout row outside the held
    block (so it includes the held version's other source segments), embargoed identically."""
    blocked = _blocked_days(fold, embargo_days)
    return [r for r in rows if r.climate_day not in blocked]


def _m0_pool_defect(pool: Sequence[FeatureRow], fold: Fold) -> str | None:
    """Why ``fit_calibration`` cannot score ``fold`` from ``pool``; ``None`` when it can."""
    if not any(r.version == fold.version for r in pool):
        return "the held version has no train rows left"
    if len({r.version for r in pool}) < 2:
        return "fewer than 2 versions"
    if not any(
        DEFAULT_SPLITS.split_for_date(r.climate_day) in ("validate", "v5_fit_slice") for r in pool
    ):
        return "no validate/v5 row"
    return None


def m0_eligible_plan(rows: Sequence[FeatureRow], plan: FoldPlan, *, embargo_days: int) -> FoldPlan:
    """Drop (and count in ``excluded``) every fold whose M0 pool ``fit_calibration`` cannot use."""
    _check_embargo(embargo_days)
    kept: list[Fold] = []
    excluded = list(plan.excluded)
    for fold in plan.folds:
        defect = _m0_pool_defect(_m0_pool(rows, fold, embargo_days), fold)
        if defect is None:
            kept.append(fold)
        else:
            excluded.append(
                (fold.version, fold.segment, f"fold {fold.fold_id}: M0 pool inadmissible: {defect}")
            )
    return FoldPlan(folds=tuple(kept), excluded=tuple(excluded))


def out_of_fold_scores(
    rows: Sequence[FeatureRow],
    plan: FoldPlan,
    settings: BlendSettings,
    *,
    levels: Sequence[int],
    champion: bool = True,
    m0_bootstrap_draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    champion_method: CdfMethod = CdfMethod.NORMAL,
    embargo_days: int = 0,
    pooled_sensitivity: bool = True,
) -> list[ScoredRow]:
    """Score every held row of every fold with models fitted without that fold's held days.

    The blend arms train on the fold's own train days (same version, same source segment). The
    champion M0 is ``fit_calibration`` over :func:`_m0_pool` (the held version's train days and
    every other version's rows: its hierarchical shrinkage needs several versions), never fitted on
    the rows it scores. ``embargo_days`` removes the days around the held block from M0 AND from
    the blend training. With ``pooled_sensitivity`` the old all-rows pool is also scored as
    ``M0pooled`` (a sensitivity, never gating). A fold whose M0 pool ``fit_calibration`` cannot use
    raises :class:`InsufficientRowsError`; :func:`m0_eligible_plan` excludes and counts such folds.
    """
    _check_embargo(embargo_days)
    _assert_admissible(rows)
    scored: list[ScoredRow] = []
    for fold in plan.folds:
        held_days, train_days = set(fold.held_days), set(fold.train_days)
        blocked = _blocked_days(fold, embargo_days)
        held = [r for r in rows if r.version == fold.version and r.climate_day in held_days]
        train = [
            r
            for r in rows
            if r.version == fold.version
            and r.climate_day in train_days
            and r.climate_day not in blocked
        ]
        if not held:
            continue
        crps: list[dict[str, float]] = [{} for _ in held]
        predictions: list[dict[str, ArmPrediction]] = [{} for _ in held]
        eff_levels: list[dict[str, int]] = [{} for _ in held]
        fell_back: list[list[str]] = [[] for _ in held]
        for level in levels:
            fit = fit_blend(train, level=level, settings=settings)
            arm = ARM_NAMES[level]
            for i, row in enumerate(held):
                mu, sigma, eff = predict_row(fit, row)
                predictions[i][arm] = ArmPrediction(mu, sigma, settings.nu)
                crps[i][arm] = row_crps(fit, row)
                eff_levels[i][arm] = eff
                if eff < intended_level(fit, row):
                    fell_back[i].append(arm)
        specs: list[ChampionSpec | None] = [None] * len(held)
        if champion:
            pool = _m0_pool(rows, fold, embargo_days)
            defect = _m0_pool_defect(pool, fold)
            if defect is not None:
                raise InsufficientRowsError(f"fold {fold.fold_id}: M0 pool inadmissible: {defect}")
            for i, (value, spec) in enumerate(
                _champion_rows(pool, held, champion_method, m0_bootstrap_draws)
            ):
                crps[i]["M0"] = value
                specs[i] = spec
            if pooled_sensitivity:
                wide = _pooled_sensitivity_pool(rows, fold, embargo_days)
                for i, (value, _spec) in enumerate(
                    _champion_rows(wide, held, champion_method, m0_bootstrap_draws)
                ):
                    crps[i]["M0pooled"] = value
        for i, row in enumerate(held):
            scored.append(
                ScoredRow(
                    station=row.station,
                    climate_day=row.climate_day,
                    horizon=row.horizon,
                    version=row.version,
                    fold_id=fold.fold_id,
                    observed_f=row.cli_tmax_f,
                    crps=crps[i],
                    arm_predictions=predictions[i],
                    champion=specs[i],
                    levels=eff_levels[i],
                    fell_back=tuple(fell_back[i]),
                )
            )
    return scored


def merge_scored(first: Sequence[ScoredRow], second: Sequence[ScoredRow]) -> list[ScoredRow]:
    """Union of two scorings of the SAME rows in the SAME order (stage A then stage B)."""
    if len(first) != len(second):
        raise ValueError("scorings cover different row sets")
    merged: list[ScoredRow] = []
    for a, b in zip(first, second, strict=True):
        if (a.station, a.climate_day, a.horizon, a.fold_id) != (
            b.station,
            b.climate_day,
            b.horizon,
            b.fold_id,
        ):
            raise ValueError("scorings are not row-aligned")
        merged.append(
            replace(
                a,
                crps={**a.crps, **b.crps},
                arm_predictions={**a.arm_predictions, **b.arm_predictions},
                champion=a.champion if a.champion is not None else b.champion,
                levels={**a.levels, **b.levels},
                fell_back=(*a.fell_back, *(x for x in b.fell_back if x not in a.fell_back)),
            )
        )
    return merged


def shuffle_labels(rows: Sequence[FeatureRow], *, seed: int) -> list[FeatureRow]:
    """Negative control: permute station-day labels within each NBM version."""
    rng = random.Random(seed)
    keys_by_version: dict[str, list[tuple[str, dt.date]]] = {}
    label: dict[tuple[str, str, dt.date], float] = {}
    for row in rows:
        key = (row.station, row.climate_day)
        if (row.version, *key) not in label:
            label[(row.version, *key)] = row.cli_tmax_f
            keys_by_version.setdefault(row.version, []).append(key)
    permuted: dict[tuple[str, str, dt.date], float] = {}
    for version, keys in keys_by_version.items():
        values = [label[(version, *k)] for k in keys]
        rng.shuffle(values)
        permuted.update({(version, *k): v for k, v in zip(keys, values, strict=True)})
    return [
        replace(row, cli_tmax_f=permuted[(row.version, row.station, row.climate_day)])
        for row in rows
    ]
