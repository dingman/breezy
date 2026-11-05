"""F13 Phase B0/B1 release-timing primitives (plan r3 + r3.1 R14/R16/R26 + r3.2).

PURE: stdlib only, no I/O, no network, no catalog, no clock. Every input is a value the
caller already read; nothing here knows where a quote, a release time or a source value came
from, and nothing here accepts a model output or a realised value.

Definitions (binding text: plan "Phase B1" and R26):

* **Matched-rung panel, defined at ``t`` only.** A rung is in the panel iff BOTH sides are
  quoted at ``t``. A rung one-sided at ``t`` is excluded and counted. A rung missing (or
  one-sided) at ``t+delta`` is a DROPOUT: it stays in the panel, carried forward at its last
  quote, and is counted. The ladder is NEVER renormalised.
* **Ladder-implied expected daily max** = sum over panel rungs of ``mid_probability * value_f``.
* **Signed change** = implied mean at ``t+delta`` minus implied mean at ``t``.
* **Regressor** = source value minus the pre-release ladder-implied mean.
* **Slope CI** = day-block bootstrap: whole climate days are resampled, never single events.
* **MDE** = ``(z_alpha + z_beta) * SD / sqrt(n_eff)`` with ``z_alpha = Phi^-1(1 - alpha/m)``
  (Holm's first step over a family of size ``m`` in {1, 2}), ``alpha = 0.025``, power 0.8.
  ``n_eff`` is clustered by climate day. The SD is taken from the placebo and pre-window arms
  only (R14). The MDE is in the units of the SD; dividing by the regressor SD (B1) expresses it
  as a slope.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import NormalDist
from typing import Any, Final, Literal, Protocol

__all__ = [
    "ALPHA",
    "POWER",
    "RESOLUTION_S",
    "CadenceSummary",
    "EventObservation",
    "MatchedPanel",
    "PanelRung",
    "RungQuote",
    "SlopeCI",
    "build_matched_panel",
    "cadence_summary",
    "day_block_bootstrap_slope_ci",
    "effective_n",
    "holm_family_size",
    "holm_reject",
    "is_underpowered",
    "ladder_implied_mean",
    "mde",
    "metar_offset_placebo_instants",
    "ols_slope",
    "pooled_sd",
    "regressor",
    "resolves_resolution",
    "same_clock_placebo_days",
    "signed_change",
    "time_to_fraction_of_move",
]

ALPHA: Final[float] = 0.025
POWER: Final[float] = 0.8
#: The B2 "adjusts under 60 s" STOP needs the tape to resolve this many seconds (R13).
RESOLUTION_S: Final[int] = 60
#: Share of Depth10 gaps that must be at or below the resolution for "resolves" (p90 rule).
CADENCE_QUANTILE: Final[float] = 0.9
SD_ARM_PREFIXES: Final[tuple[str, ...]] = ("placebo", "pre_window")
_NS: Final[int] = 1_000_000_000
_HOURS_PER_DAY: Final[int] = 24
_MIN_BOOTSTRAP_DAYS: Final[int] = 2
_FAMILY_SIZES: Final[tuple[int, ...]] = (1, 2)


# --------------------------------------------------------------------- panel


@dataclass(frozen=True, slots=True)
class RungQuote:
    """One rung's best bid and best ask as probabilities in [0, 1]; ``None`` is an empty side."""

    rung_id: str
    value_f: float
    bid: float | None
    ask: float | None

    @property
    def two_sided(self) -> bool:
        return self.bid is not None and self.ask is not None

    @property
    def mid(self) -> float:
        if self.bid is None or self.ask is None:
            raise ValueError(f"rung {self.rung_id} is one-sided; it has no midpoint")
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True, slots=True)
class PanelRung:
    rung_id: str
    value_f: float
    p_t: float
    p_t_plus: float
    carried_forward: bool


@dataclass(frozen=True, slots=True)
class MatchedPanel:
    rungs: tuple[PanelRung, ...]
    dropout_rungs: tuple[str, ...]
    empty_side_excluded: tuple[str, ...]

    @property
    def dropout_count(self) -> int:
        return len(self.dropout_rungs)

    @property
    def empty_side_count(self) -> int:
        return len(self.empty_side_excluded)


def build_matched_panel(
    at_t: Mapping[str, RungQuote], at_t_plus: Mapping[str, RungQuote]
) -> MatchedPanel:
    """The panel is defined by ``at_t`` alone; ``at_t_plus`` only supplies the later level."""
    rungs: list[PanelRung] = []
    dropouts: list[str] = []
    excluded: list[str] = []
    for rung_id, quote in at_t.items():
        if not quote.two_sided:
            excluded.append(rung_id)
            continue
        later = at_t_plus.get(rung_id)
        if later is not None and later.two_sided:
            rungs.append(PanelRung(rung_id, quote.value_f, quote.mid, later.mid, False))
        else:
            dropouts.append(rung_id)
            rungs.append(PanelRung(rung_id, quote.value_f, quote.mid, quote.mid, True))
    rungs.sort(key=lambda r: (r.value_f, r.rung_id))
    return MatchedPanel(tuple(rungs), tuple(sorted(dropouts)), tuple(sorted(excluded)))


def ladder_implied_mean(panel: MatchedPanel, when: Literal["t", "t_plus"]) -> float:
    """Sum of ``probability * value_f`` over the panel. Not divided by the probability mass."""
    if not panel.rungs:
        raise ValueError("empty panel has no ladder-implied mean")
    if when == "t":
        return sum(r.p_t * r.value_f for r in panel.rungs)
    return sum(r.p_t_plus * r.value_f for r in panel.rungs)


def signed_change(panel: MatchedPanel) -> float:
    return ladder_implied_mean(panel, "t_plus") - ladder_implied_mean(panel, "t")


def regressor(source_value_f: float, pre_release_ladder_mean: float) -> float:
    return source_value_f - pre_release_ladder_mean


# ------------------------------------------------------------------ bootstrap


@dataclass(frozen=True, slots=True)
class EventObservation:
    """One event: its climate day (the cluster), the regressor and the signed change."""

    day: dt.date
    regressor: float
    change: float


@dataclass(frozen=True, slots=True)
class SlopeCI:
    slope: float
    lo: float
    hi: float
    alpha: float
    n_days: int
    n_events: int
    n_boot: int
    degenerate_resamples: int


class _ChoicesRng(Protocol):
    def choices(self, population: Any, k: int) -> Any: ...


def ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys) or len(xs) < _MIN_BOOTSTRAP_DAYS:
        raise ValueError("ols_slope needs equal-length inputs with at least 2 points")
    mean_x = math.fsum(xs) / len(xs)
    mean_y = math.fsum(ys) / len(ys)
    sxx = math.fsum((x - mean_x) ** 2 for x in xs)
    if sxx == 0.0:
        raise ValueError("regressor variance is zero; the slope is undefined")
    return math.fsum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / sxx


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def day_block_bootstrap_slope_ci(
    events: Sequence[EventObservation],
    *,
    n_boot: int,
    alpha: float,
    seed: int,
    rng: _ChoicesRng | None = None,
) -> SlopeCI:
    """Percentile CI of the OLS slope; ``alpha`` is the total two-sided tail mass.

    Whole climate days are resampled with replacement, each carrying all its events. A
    resample whose regressor has no variance is skipped and counted, never silently kept.
    """
    if n_boot < 1:
        raise ValueError("n_boot must be >= 1")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    blocks: dict[dt.date, list[EventObservation]] = defaultdict(list)
    for event in events:
        blocks[event.day].append(event)
    days = sorted(blocks)
    if len(days) < _MIN_BOOTSTRAP_DAYS:
        raise ValueError("a day-block bootstrap needs at least 2 climate days")
    source: _ChoicesRng | random.Random = rng if rng is not None else random.Random(seed)
    point = ols_slope([e.regressor for e in events], [e.change for e in events])
    slopes: list[float] = []
    degenerate = 0
    for _ in range(n_boot):
        drawn = source.choices(days, k=len(days))
        picked = [event for day in drawn for event in blocks[day]]
        try:
            slopes.append(ols_slope([e.regressor for e in picked], [e.change for e in picked]))
        except ValueError:
            degenerate += 1
    if not slopes:
        raise ValueError("every bootstrap resample was degenerate")
    slopes.sort()
    return SlopeCI(
        slope=point,
        lo=_quantile(slopes, alpha / 2.0),
        hi=_quantile(slopes, 1.0 - alpha / 2.0),
        alpha=alpha,
        n_days=len(days),
        n_events=len(events),
        n_boot=n_boot,
        degenerate_resamples=degenerate,
    )


# ------------------------------------------------------------------ Holm / MDE


def holm_family_size(*, nbp_vintages_present: bool) -> int:
    """B0 fixes the B1 family before the read: PFM alone, or PFM and NBP (R26)."""
    return 2 if nbp_vintages_present else 1


def holm_reject(pvalues: Sequence[float], *, alpha: float = ALPHA) -> tuple[bool, ...]:
    """Holm step-down; the result is in the INPUT order."""
    count = len(pvalues)
    order = sorted(range(count), key=lambda i: pvalues[i])
    rejected = [False] * count
    for step, index in enumerate(order):
        if pvalues[index] <= alpha / (count - step):
            rejected[index] = True
        else:
            break
    return tuple(rejected)


def effective_n(events_per_day: Sequence[int], icc: float = 1.0) -> float:
    """Design-effect n: ``n / (1 + (mean_cluster_size - 1) * icc)``.

    ``icc=1`` (the default, conservative) collapses each climate day to one observation.
    """
    if not events_per_day:
        return 0.0
    if not 0.0 <= icc <= 1.0:
        raise ValueError("icc must be in [0, 1]")
    total = sum(events_per_day)
    mean_size = total / len(events_per_day)
    return total / (1.0 + (mean_size - 1.0) * icc)


def mde(
    *,
    sd: float,
    n_eff: float,
    family_size: int,
    alpha: float = ALPHA,
    power: float = POWER,
) -> float:
    """``(z_alpha + z_beta) * sd / sqrt(n_eff)``; ``z_alpha`` uses Holm's first step."""
    if family_size not in _FAMILY_SIZES:
        raise ValueError(f"family_size must be 1 or 2, was {family_size!r}")
    if not (isinstance(n_eff, int | float) and math.isfinite(n_eff) and n_eff > 0):
        raise ValueError(f"n_eff must be a positive finite number, was {n_eff!r}")
    if not (math.isfinite(sd) and sd >= 0):
        raise ValueError("sd must be finite and non-negative")
    inverse = NormalDist().inv_cdf
    return (inverse(1.0 - alpha / family_size) + inverse(power)) * sd / math.sqrt(n_eff)


def pooled_sd(arms: Mapping[str, Sequence[float]]) -> float:
    """Sample SD over the concatenated placebo and pre-window arms ONLY (R14)."""
    values = [
        v for name, series in arms.items() if name.startswith(SD_ARM_PREFIXES) for v in series
    ]
    if not any(name.startswith(SD_ARM_PREFIXES) for name in arms):
        raise ValueError("no placebo or pre_window arm supplied; the SD is taken only from those")
    if len(values) < _MIN_BOOTSTRAP_DAYS:
        raise ValueError("the placebo and pre_window arms need at least 2 values in total")
    mean = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((v - mean) ** 2 for v in values) / (len(values) - 1))


def is_underpowered(*, mde_value: float, plausible_effect: float | None) -> bool | None:
    """UNDERPOWERED when the MDE exceeds the plausible effect; None when none was given."""
    if plausible_effect is None:
        return None
    return mde_value > plausible_effect


# ----------------------------------------------------------- 50 % of the move


def time_to_fraction_of_move(
    series: Sequence[tuple[int, float]],
    t0_ns: int,
    level0: float,
    *,
    fraction: float = 0.5,
    min_move: float = 0.0,
) -> float | None:
    """Seconds after ``t0`` until the level first covers ``fraction`` of the total move.

    ``series`` is time-ordered ``(ts_ns, level)`` ending at the window end; the total move is
    the last level minus ``level0``. None when there is no move, the move is below
    ``min_move``, or the series is empty.
    """
    after = [(ts, level) for ts, level in series if ts > t0_ns]
    if not after:
        return None
    move = after[-1][1] - level0
    if move == 0.0 or abs(move) < min_move:
        return None
    sign = 1.0 if move > 0 else -1.0
    target = fraction * abs(move)
    for ts, level in after:
        if (level - level0) * sign >= target:
            return (ts - t0_ns) / _NS
    return None


# -------------------------------------------------------------------- cadence


@dataclass(frozen=True, slots=True)
class CadenceSummary:
    n_rows: int
    median_gap_s: float | None
    p90_gap_s: float | None
    max_gap_s: float | None


def cadence_summary(ts_ns_sorted: Sequence[int]) -> CadenceSummary:
    n_rows = len(ts_ns_sorted)
    if n_rows < _MIN_BOOTSTRAP_DAYS:
        return CadenceSummary(n_rows, None, None, None)
    gaps = sorted((b - a) / _NS for a, b in pairwise(ts_ns_sorted))
    return CadenceSummary(
        n_rows,
        _quantile(gaps, 0.5),
        _quantile(gaps, CADENCE_QUANTILE),
        gaps[-1],
    )


def resolves_resolution(summary: CadenceSummary, *, resolution_s: int = RESOLUTION_S) -> bool:
    """True iff the 90th-percentile gap is at or below ``resolution_s``."""
    return summary.p90_gap_s is not None and summary.p90_gap_s <= resolution_s


# ---------------------------------------------------------------- placebo pools


def _day_start_ns(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS


def _within(sorted_ns: Sequence[int], instant_ns: int, tolerance_ns: int) -> bool:
    at = bisect_right(sorted_ns, instant_ns - tolerance_ns - 1)
    return at < len(sorted_ns) and sorted_ns[at] <= instant_ns + tolerance_ns


def same_clock_placebo_days(
    clock_s_of_day: int,
    releases_ns: Sequence[int],
    days: Sequence[dt.date],
    *,
    tolerance_s: int,
) -> tuple[dt.date, ...]:
    """Tape days on which the source released nothing within ``tolerance_s`` of the clock time."""
    ordered = sorted(releases_ns)
    tolerance_ns = tolerance_s * _NS
    return tuple(
        day
        for day in sorted(set(days))
        if not _within(ordered, _day_start_ns(day) + clock_s_of_day * _NS, tolerance_ns)
    )


def metar_offset_placebo_instants(
    *,
    minute_of_hour: int,
    releases_ns: Sequence[int],
    days: Sequence[dt.date],
    exclusion_s: int,
) -> tuple[int, ...]:
    """Every hourly instant at ``minute_of_hour`` not within ``exclusion_s`` of a release."""
    ordered = sorted(releases_ns)
    exclusion_ns = exclusion_s * _NS
    out: list[int] = []
    for day in sorted(set(days)):
        base = _day_start_ns(day)
        for hour in range(_HOURS_PER_DAY):
            instant = base + (hour * 3600 + minute_of_hour * 60) * _NS
            if not _within(ordered, instant, exclusion_ns):
                out.append(instant)
    return tuple(out)
