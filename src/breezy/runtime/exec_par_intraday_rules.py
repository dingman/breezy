"""EXEC-PAR BG-6: the PURE intraday stop predicates (D-PREREG r4 s5, s9, 1a; r4.1 L1, K4).

No I/O, no clock, no logging, no Nautilus or ``breezy.adapters`` import: the node's watcher
(:mod:`breezy.runtime.exec_par_intraday`) gathers the inputs and BG-4's ``--dry-eval`` recomputes
the same rules through these functions (L1).

* **s5 Clopper-Pearson.** A one-sided lower bound at alpha = 0.01 above 0.18, at n >= 20 posted
  entries in the stage window. The bound is never computed: for a monotone binomial tail the lower
  bound L exceeds ``t`` exactly when ``P(X >= k | n, p = t) < alpha``, which is evaluated in exact
  integer arithmetic (no float, no scipy, no tolerance).
* **s5 burst.** At least ``BURST_MIN_AMBIGUOUS`` (5) AMBIGUOUS entries whose ARM times span at most
  60 minutes (inclusive), at any n. D-PREREG s5 allows exactly one adjustment before freeze: 5 -> 6
  if BG-10(c) shows a false-alarm rate above 10%; the frozen s5 states which applies.
* **s9 station-day.** Open cost above 0.25 of the budget, counting ALL open positions regardless of
  arm time or floor. The comparison against the budget happens inside the injected ledger port
  (K6): only a bool leaves it. A raise or a non-bool return is an integrity trip naming the
  predicate (D4).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from math import comb
from typing import Final, Protocol

from breezy.runtime.exec_par_stage_types import (
    STOP_S5_BURST,
    STOP_S5_CLOPPER_PEARSON,
    STOP_S9_STATION_DAY_INTRADAY,
)

__all__ = [
    "BURST_MIN_AMBIGUOUS",
    "BURST_WINDOW_NS",
    "CP_ALPHA",
    "CP_MIN_POSTED",
    "CP_THRESHOLD",
    "PREDICATE_STATION_DAY",
    "STATION_DAY_OPEN_COST_FRACTION",
    "CounterIncreaseWatch",
    "IntradayInputError",
    "IntradayInputs",
    "IntradayPredicateError",
    "OpenCostPort",
    "burst_trips",
    "clopper_pearson_exceeds",
    "cp_rule_trips",
    "intraday_stop_reasons",
    "max_in_window",
    "station_days_over_open_cost",
]

_NS: Final[int] = 1_000_000_000

CP_ALPHA: Final[Fraction] = Fraction(1, 100)
CP_THRESHOLD: Final[Fraction] = Fraction(18, 100)
CP_MIN_POSTED: Final[int] = 20

BURST_MIN_AMBIGUOUS: Final[int] = 5
BURST_WINDOW_NS: Final[int] = 60 * 60 * _NS

STATION_DAY_OPEN_COST_FRACTION: Final[Decimal] = Decimal("0.25")
PREDICATE_STATION_DAY: Final[str] = "s9_station_day_open_cost"
_FAIL_PREFIX: Final[str] = "stage_eval_fail:"


class IntradayInputError(ValueError):
    """An input the rules cannot interpret (impossible count, non-int time). Value-free."""


class IntradayPredicateError(Exception):
    """A ledger predicate raised or returned a non-bool: an integrity trip naming it (D4)."""

    def __init__(self, name: str) -> None:
        self.reason = f"{_FAIL_PREFIX}predicate:{name}"
        super().__init__(self.reason)


class OpenCostPort(Protocol):
    """The open-cost slice of ``LedgerPredicatePort`` (BG-1e; K6): aggregates in, bool out."""

    def open_cost_exceeds_budget_fraction(
        self, *, aggregate_open_cost: Decimal, fraction: Decimal
    ) -> bool: ...


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IntradayInputError("count is not a non-negative int")
    return value


def clopper_pearson_exceeds(
    ambiguous: int,
    posted: int,
    *,
    alpha: Fraction = CP_ALPHA,
    threshold: Fraction = CP_THRESHOLD,
) -> bool:
    """``True`` iff the one-sided Clopper-Pearson lower bound on ``ambiguous / posted`` at
    ``alpha`` is strictly above ``threshold`` (exact; a bound AT the threshold is not above)."""
    k, n = _count(ambiguous), _count(posted)
    if k > n:
        raise IntradayInputError("ambiguous exceeds posted")
    num, den = threshold.numerator, threshold.denominator
    tail = sum(comb(n, i) * num**i * (den - num) ** (n - i) for i in range(k, n + 1))
    # tail / den**n = P(X >= k | n, p = threshold); the bound exceeds `threshold` iff it is < alpha.
    return bool(tail * alpha.denominator < alpha.numerator * den**n)


def cp_rule_trips(ambiguous: int, posted: int) -> bool:
    """The s5 Clopper-Pearson halt: n >= 20 posted entries AND the bound above 0.18."""
    k, n = _count(ambiguous), _count(posted)
    return n >= CP_MIN_POSTED and clopper_pearson_exceeds(k, n)


def burst_trips(
    arm_times_ns: Iterable[int],
    *,
    min_count: int = BURST_MIN_AMBIGUOUS,
    window_ns: int = BURST_WINDOW_NS,
) -> bool:
    """``True`` iff ``min_count`` arm times span at most ``window_ns`` (inclusive), any order."""
    times = sorted(_arm_time(t) for t in arm_times_ns)
    if min_count < 1 or window_ns < 0:
        raise IntradayInputError("burst parameters out of range")
    return any(
        times[i] - times[i - min_count + 1] <= window_ns for i in range(min_count - 1, len(times))
    )


def max_in_window(arm_times_ns: Iterable[int], *, window_ns: int = BURST_WINDOW_NS) -> int:
    """The largest number of arm times inside any span of ``window_ns`` (inclusive), any order."""
    times = sorted(_arm_time(t) for t in arm_times_ns)
    best = 0
    start = 0
    for end, moment in enumerate(times):
        while moment - times[start] > window_ns:
            start += 1
        best = max(best, end - start + 1)
    return best


def _arm_time(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise IntradayInputError("arm time is not a positive int")
    return value


def station_days_over_open_cost(
    port: OpenCostPort, open_cost_by_station_day: Mapping[str, Decimal]
) -> tuple[str, ...]:
    """The station-days whose open cost is above 0.25 of the budget, sorted.

    ``open_cost_by_station_day`` is already aggregated over ALL open positions of each station-day
    (no arm-time or floor filter). A port raise or non-bool return raises
    :class:`IntradayPredicateError`; the message never carries a value.
    """
    over: list[str] = []
    for station_day in sorted(open_cost_by_station_day):
        try:
            result = port.open_cost_exceeds_budget_fraction(
                aggregate_open_cost=open_cost_by_station_day[station_day],
                fraction=STATION_DAY_OPEN_COST_FRACTION,
            )
        except Exception:  # noqa: BLE001 - any raise is an integrity trip (D4); no value kept
            raise IntradayPredicateError(PREDICATE_STATION_DAY) from None
        if type(result) is not bool:
            raise IntradayPredicateError(PREDICATE_STATION_DAY)
        if result:
            over.append(station_day)
    return tuple(over)


@dataclass(frozen=True, slots=True)
class IntradayInputs:
    """Everything the three rules read, already gathered and windowed by the caller.

    ``posted`` and ``ambiguous`` are the stage-window totals (arm time at or after the floor,
    excluded days skipped); ``ambiguous_arm_ns`` the arm times of those AMBIGUOUS entries;
    ``open_cost_by_station_day`` the open cost of ALL open positions per ``station@day``.
    """

    posted: int
    ambiguous: int
    ambiguous_arm_ns: tuple[int, ...]
    open_cost_by_station_day: Mapping[str, Decimal]
    #: Integrity findings from the gathering (corrupt or unusable counts). They never stop the
    #: rules from being evaluated: the conservative reading still trips.
    findings: tuple[str, ...] = ()
    #: The ``stage_reset`` instant the window was cut at (``None``: no reset yet).
    floor_ts: int | None = None


def intraday_stop_reasons(inputs: IntradayInputs, port: OpenCostPort) -> tuple[str, ...]:
    """Every intraday stop reason that holds, in the fixed order s5-CP, s5-burst, s9.

    AMBIGUOUS can exceed posted when a mark outlived its anchor; n is then taken as at least the
    AMBIGUOUS count (the conservative reading: a rate of at most 1).
    """
    reasons: list[str] = []
    ambiguous = _count(inputs.ambiguous)
    if cp_rule_trips(ambiguous, max(_count(inputs.posted), ambiguous)):
        reasons.append(STOP_S5_CLOPPER_PEARSON)
    if burst_trips(inputs.ambiguous_arm_ns):
        reasons.append(STOP_S5_BURST)
    if station_days_over_open_cost(port, inputs.open_cost_by_station_day):
        reasons.append(STOP_S9_STATION_DAY_INTRADAY)
    return tuple(reasons)


class CounterIncreaseWatch:
    """Integrity trigger on a monotone counter: any value above the last ACKNOWLEDGED one.

    ``acknowledge`` is called only after the halt write succeeded, so a failed write leaves the
    increase pending and the next tick retries (the seen-counter pattern of the s4 trips).
    """

    def __init__(self) -> None:
        self._seen = 0

    def increased(self, value: int) -> bool:
        return _count(value) > self._seen

    def acknowledge(self, value: int) -> None:
        self._seen = max(self._seen, _count(value))
