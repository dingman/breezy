"""The FQ forward-shadow e-process core (E-25 rule 3; F7b-core). Pure, float, stdlib only.

Per settled climate day ``d`` the evidence is two statistics on a PINNED denominator ``m_cap``
(never derived from listings or from the day's data, FQ-R39):

* ``Y_d = (1/m_cap) * sum_{i <= min(N_d, m_cap)} X_i`` with
  ``X_i = min(h_i/BE_i - 1, X_max)``. BE is
  the HAIRCUT break-even (ask + one tick + fee, F7B-R21). The upside is clipped, the downside
  (``-1``) never is.
* ``Z_d = (1/m_cap) * sum_i ((ask_i - h_i)^2 - (p_i - h_i)^2)``, where ``ask_i`` is the RAW
  executable quote (no haircut, F7B-R21) and ``p_i`` the model's probability of the side bought.
  e_b's validity needs that comparator to be measurable at decision time (G-measurable); it is a
  quote the live rule saw.

Takes are ordered by ``(decision_ts_ns, station, rung_id, side)``, compared as ASCII bytes:
G-measurable keys only, never the outcome or the arrival order. A void is a venue-declared
``void=True`` take that holds its slot as an explicit 0 and counts in ``n``;
a void must be independent of h given G
(F7B-R15) -- if the venue voided losers more often than winners the zero would be biased. A take
whose outcome is unknown on a settled day is REFUSED, never scored as 0 (F7B-R23).

``e_a = prod(1 + lam_d * Y_d)`` and ``e_b = prod(1 + mu_d * Z_d)`` are betting processes with the
pinned ``agrapa_v1`` rule. ``lam_d`` and ``mu_d`` use SETTLED days strictly before ``d`` only, so
the bet is predictable. Both accumulate in log space and every threshold comparison is a log-space
``>=`` (F7B-R14). ``n_cum`` counts every take (voids and takes past the cap included, D7).

The day set is the contiguous calendar between the first eligible day and the last settled day.
A day needs a coverage marker (F7B-R24): an uncovered day is a gap and is refused; a covered day
with zero takes is ``Y = Z = 0`` (it still counts toward ``n_prev``, as in the F5 Monte-Carlo).

The design values arrive as parameters (the future policy block). Nothing here reads the docs.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

__all__ = [
    "BETTING_RULE_AGRAPA_V1",
    "DayStat",
    "DayState",
    "EProcessDesign",
    "EProcessRefused",
    "GuardThresholds",
    "TakeInput",
    "agrapa_fraction",
    "build_day_stats",
    "crossed",
    "daily_statistic",
    "first_pass_n",
    "order_takes",
    "pass_bar",
    "run_eprocess",
    "take_x",
]

BETTING_RULE_AGRAPA_V1: Final = "agrapa_v1:prior_pseudo_days=1,prior_second_moment=0.25"
M_CAP_CHOICES: Final = (2, 3)
PRIOR_PSEUDO_DAYS: Final = 1
PRIOR_SECOND_MOMENT: Final = 0.25
MAX_BET: Final = 0.5
#: Every betting factor is at least ``1 - MAX_BET``: Y lies in ``[-1, X_max]``, Z in ``[-1, 1]``.
FACTOR_FLOOR: Final = 1.0 - MAX_BET
_VAR_FLOOR: Final = 1e-6
_FLOOR_SLACK: Final = 1e-12
_POOLINGS: Final = frozenset({"pooled", "per_side"})


class EProcessRefused(ValueError):
    """An input the e-process refuses to score; ``reason`` is the named, machine-checkable cause."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise EProcessRefused("not_finite", name)
    return float(value)


@dataclass(frozen=True, slots=True)
class GuardThresholds:
    """The calibration-guard thresholds (F7B-R11). Unpinned in the F5 design: a design carries
    ``guard=None`` until F5 pins them, and the evaluator then reports ``guard_unpinned``."""

    n_guard_min: int
    spiegelhalter_abs_z_max: float
    slope_band: tuple[float, float]
    bin_edges: tuple[float, ...]
    pooling: str

    def __post_init__(self) -> None:
        if isinstance(self.n_guard_min, bool) or not isinstance(self.n_guard_min, int):
            raise EProcessRefused("guard_n_guard_min")
        if self.n_guard_min < 1 or _finite(self.spiegelhalter_abs_z_max, "abs_z") <= 0:
            raise EProcessRefused("guard_bounds")
        low, high = self.slope_band
        if not (_finite(low, "slope_low") < _finite(high, "slope_high")):
            raise EProcessRefused("guard_slope_band")
        edges = self.bin_edges
        if (
            len(edges) < 2
            or list(edges) != sorted(set(edges))
            or edges[0] != 0.0
            or edges[-1] != 1.0
        ):
            raise EProcessRefused("guard_bin_edges", "strictly ascending, from 0.0 to 1.0")
        if self.pooling not in _POOLINGS:
            raise EProcessRefused("guard_pooling", self.pooling)


@dataclass(frozen=True, slots=True)
class EProcessDesign:
    """The pinned design: ``m_cap``, ``X_max``, bet caps, ``earliest_look_n``, betting rule."""

    m_cap: int
    x_max: float
    lambda_max: float
    mu_max: float
    earliest_look_n: int
    betting_rule_e_a: str = BETTING_RULE_AGRAPA_V1
    betting_rule_e_b: str = BETTING_RULE_AGRAPA_V1
    guard: GuardThresholds | None = None

    def __post_init__(self) -> None:
        if isinstance(self.m_cap, bool) or self.m_cap not in M_CAP_CHOICES:
            raise EProcessRefused("m_cap", f"must be one of {M_CAP_CHOICES}, got {self.m_cap!r}")
        if _finite(self.x_max, "x_max") <= 0:
            raise EProcessRefused("x_max")
        for name in ("lambda_max", "mu_max"):
            if not 0.0 < _finite(getattr(self, name), name) <= MAX_BET:
                raise EProcessRefused(name, f"must be in (0, {MAX_BET}]")
        if (
            isinstance(self.earliest_look_n, bool)
            or not isinstance(self.earliest_look_n, int)
            or self.earliest_look_n < 1
        ):
            raise EProcessRefused("earliest_look_n")
        for rule in (self.betting_rule_e_a, self.betting_rule_e_b):
            if rule != BETTING_RULE_AGRAPA_V1:
                raise EProcessRefused("betting_rule", repr(rule))
        if self.guard is not None and not isinstance(self.guard, GuardThresholds):
            raise EProcessRefused("guard")


@dataclass(frozen=True, slots=True)
class TakeInput:
    """One take. ``be`` is the haircut break-even, ``raw_ask`` the raw executable quote (R21).
    ``h`` is the outcome (None until settled); ``void`` is a venue-declared void (R23)."""

    climate_day: dt.date
    decision_ts_ns: int
    station: str
    rung_id: str
    side: str
    be: float
    raw_ask: float
    p_model: float
    h: int | None = None
    void: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.climate_day, dt.date):
            raise EProcessRefused("climate_day")
        if isinstance(self.decision_ts_ns, bool) or not isinstance(self.decision_ts_ns, int):
            raise EProcessRefused("decision_ts_ns")
        for name in ("station", "rung_id", "side"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise EProcessRefused("key_empty", name)
            if not value.isascii():
                raise EProcessRefused("non_ascii_key", name)
        if not _finite(self.be, "be") > 0.0:
            raise EProcessRefused("be", "must be > 0")
        for name in ("raw_ask", "p_model"):
            if not 0.0 <= _finite(getattr(self, name), name) <= 1.0:
                raise EProcessRefused(name, "must be in [0, 1]")
        if self.h is not None and (isinstance(self.h, bool) or self.h not in (0, 1)):
            raise EProcessRefused("h", "must be 0, 1 or None")
        if not isinstance(self.void, bool):
            raise EProcessRefused("void")
        if self.void and self.h is not None:
            raise EProcessRefused("void_with_outcome")


def take_x(h: int, be: float, x_max: float) -> float:
    """``X = min(h/BE - 1, X_max)``: the upside is clipped, the downside (-1) never is."""
    return min(h / be - 1.0, x_max)


def _take_key(take: TakeInput) -> tuple[int, bytes, bytes, bytes]:
    """G-measurable ordering keys only (R15): never ``h`` or ``void``."""
    return (
        take.decision_ts_ns,
        take.station.encode("ascii"),
        take.rung_id.encode("ascii"),
        take.side.encode("ascii"),
    )


def order_takes(takes: Iterable[TakeInput]) -> tuple[TakeInput, ...]:
    """Decision order: instant, then station, rung id, side (ASCII bytes). Never the outcome."""
    return tuple(sorted(takes, key=_take_key))


@dataclass(frozen=True, slots=True)
class DayStat:
    """One settled day: ``y``/``z`` on the pinned denominator, takes seen, takes past the cap."""

    climate_day: dt.date
    y: float
    z: float
    n_takes: int
    uncounted: int


def daily_statistic(
    climate_day: dt.date, takes: Iterable[TakeInput], design: EProcessDesign
) -> DayStat:
    """``Y_d`` and ``Z_d`` at ``m_d = design.m_cap``. Empty slots and voids are 0; takes past the
    cap are excluded and disclosed in ``uncounted``."""
    ordered = order_takes(takes)
    sum_x = sum_z = 0.0
    for take in ordered[: design.m_cap]:
        if take.void:
            continue
        if take.h is None:
            raise EProcessRefused("unsettled_take_in_settled_day", str(climate_day))
        sum_x += take_x(take.h, take.be, design.x_max)
        sum_z += (take.raw_ask - take.h) ** 2 - (take.p_model - take.h) ** 2
    for take in ordered[design.m_cap :]:
        if take.h is None and not take.void:
            raise EProcessRefused("unsettled_take_in_settled_day", str(climate_day))
    return DayStat(
        climate_day=climate_day,
        y=sum_x / design.m_cap,
        z=sum_z / design.m_cap,
        n_takes=len(ordered),
        uncounted=max(0, len(ordered) - design.m_cap),
    )


def build_day_stats(
    takes: Iterable[TakeInput],
    *,
    covered_days: frozenset[dt.date],
    first_day: dt.date,
    last_settled_day: dt.date,
    design: EProcessDesign,
) -> tuple[DayStat, ...]:
    """The contiguous calendar ``first_day .. last_settled_day`` as :class:`DayStat` (R13, R24).

    A day without a coverage marker is a gap (refused). Takes after ``last_settled_day`` are not
    settled and are not processed; a take before ``first_day`` is refused; a duplicate
    ``(instant, station, rung, side)`` is refused.
    """
    by_day: dict[dt.date, list[TakeInput]] = {}
    seen: set[tuple[int, bytes, bytes, bytes]] = set()
    for take in takes:
        if take.climate_day < first_day:
            raise EProcessRefused("take_before_first_day", str(take.climate_day))
        key = _take_key(take)
        if key in seen:
            raise EProcessRefused("duplicate_take", repr(key))
        seen.add(key)
        if take.climate_day <= last_settled_day:
            by_day.setdefault(take.climate_day, []).append(take)
    out: list[DayStat] = []
    day = first_day
    while day <= last_settled_day:
        if day not in covered_days:
            raise EProcessRefused("coverage_gap", str(day))
        out.append(daily_statistic(day, by_day.get(day, ()), design))
        day += dt.timedelta(days=1)
    return tuple(out)


def agrapa_fraction(sum_x: float, sum_x2: float, n_prev: int, cap: float) -> float:
    """The predictable ``agrapa_v1`` bet from SETTLED days only: ``clip(mu/(var + mu^2), 0, cap)``
    with mu and the second moment shrunk toward ``(0, 0.25)`` by one pseudo-day."""
    n = n_prev + PRIOR_PSEUDO_DAYS
    mu = sum_x / n
    m2 = (sum_x2 + PRIOR_PSEUDO_DAYS * PRIOR_SECOND_MOMENT) / n
    var = max(m2 - mu * mu, _VAR_FLOOR)
    return min(max(mu / (var + mu * mu), 0.0), cap)


@dataclass(frozen=True, slots=True)
class DayState:
    """The e-process after one settled day. ``lambda_d``/``mu_d`` were fixed BEFORE the day."""

    climate_day: dt.date
    y: float
    z: float
    lambda_d: float
    mu_d: float
    log_e_a: float
    log_e_b: float
    n_cum: int
    uncounted_cum: int

    @property
    def e_a(self) -> float:
        return _exp(self.log_e_a)

    @property
    def e_b(self) -> float:
        return _exp(self.log_e_b)

    @property
    def log_min(self) -> float:
        """``log min(e_a, e_b)``: the joint (intersection-union) PASS statistic."""
        return min(self.log_e_a, self.log_e_b)


def _exp(log_value: float) -> float:
    try:
        return math.exp(log_value)
    except OverflowError:
        return math.inf


def _log_factor(bet: float, value: float, name: str) -> float:
    if 1.0 + bet * value < FACTOR_FLOOR - _FLOOR_SLACK:
        raise EProcessRefused("factor_below_floor", f"{name} factor {1.0 + bet * value!r}")
    return math.log1p(bet * value)


def run_eprocess(stats: Sequence[DayStat], design: EProcessDesign) -> tuple[DayState, ...]:
    """Walk the settled days. Each day's bets are computed from the prior days' sums only."""
    sy = sy2 = sz = sz2 = 0.0
    log_a = log_b = 0.0
    n_cum = uncounted = 0
    out: list[DayState] = []
    for i, day in enumerate(stats):
        lam = agrapa_fraction(sy, sy2, i, design.lambda_max)
        mu = agrapa_fraction(sz, sz2, i, design.mu_max)
        log_a += _log_factor(lam, day.y, "e_a")
        log_b += _log_factor(mu, day.z, "e_b")
        sy, sy2 = sy + day.y, sy2 + day.y * day.y
        sz, sz2 = sz + day.z, sz2 + day.z * day.z
        n_cum += day.n_takes
        uncounted += day.uncounted
        out.append(DayState(day.climate_day, day.y, day.z, lam, mu, log_a, log_b, n_cum, uncounted))
    return tuple(out)


def pass_bar(alpha: float | Decimal) -> float:
    """``-log(alpha)``, converted from the stored level once (R14)."""
    value = float(alpha)
    if not 0.0 < value < 1.0:
        raise EProcessRefused("alpha", "must be in (0, 1)")
    return -math.log(value)


def crossed(log_statistic: float, bar: float) -> bool:
    """A log-space ``>=`` (the only threshold comparison, R14)."""
    return log_statistic >= bar


def first_pass_n(
    states: Sequence[DayState],
    alpha: float | Decimal,
    *,
    earliest_look_n: int,
    which: Literal["joint", "a", "b"] = "joint",
) -> int | None:
    """The ``n_cum`` at the first look (``n_cum >= earliest_look_n``) at the bar, else None."""
    bar = pass_bar(alpha)
    for state in states:
        if state.n_cum < earliest_look_n:
            continue
        stat = {"joint": state.log_min, "a": state.log_e_a, "b": state.log_e_b}[which]
        if crossed(stat, bar):
            return state.n_cum
    return None
