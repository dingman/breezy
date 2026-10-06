"""ARCH-0-E25: the per-lineage alpha schedules (``halving_v1`` and ``elond_heavy_tailed_v1``).

E-25 rule 4. ``halving_v1`` is ARCH's ``alpha_total * 2**-k``. ``elond_heavy_tailed_v1`` is
``alpha_total * gamma_k * (R + 1)`` with ``gamma_t = g(t) / sum_{s<=T} g(s)``,
``g(t) = 1/(t * ln(t+1)**2)`` and ``T`` the lifetime nomination ceiling in ``pins``. ``R`` is the
lineage's effective CHALLENGER->CHAMPION PROMOTE count strictly before the nomination row's
``ts_ns`` (the fold's ``promotions``).

Pure and stdlib-only (``decimal`` plus ``pins``). Every operation runs on a module-local
``Context`` so the ambient decimal context can never change a stored ``alpha_k``. Results are
floor-quantised to ``1e-18``, so at ``R = 0`` the schedule sums to at most ``alpha_total`` exactly
and every value has a canonical ``decimal_str`` form (<= 38 digits, |adjusted| <= 18).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import (
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)
from typing import Final

from breezy.persistence.autonomy import pins

__all__ = ["SCHEDULES", "alpha_k", "gamma", "promotions_before", "require_schedule_pairing"]

HALVING_V1: Final = "halving_v1"
ELOND_HEAVY_TAILED_V1: Final = "elond_heavy_tailed_v1"
SCHEDULES: Final = frozenset({HALVING_V1, ELOND_HEAVY_TAILED_V1})
_FIXED_N: Final = "fixed_n"
_E_PROCESS: Final = "e_process"
_PAIRING: Final = {HALVING_V1: _FIXED_N, ELOND_HEAVY_TAILED_V1: _E_PROCESS}
_QUANTUM: Final = Decimal("1e-18")
_ONE: Final = Decimal(1)
_CTX: Final = Context(
    prec=34,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow],
    flags=[],
)


def _check_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    return value


def _g(t: int) -> Decimal:
    """g(t) = 1 / (t * ln(t+1)**2)."""
    log = _CTX.ln(Decimal(t + 1))
    return _CTX.divide(_ONE, _CTX.multiply(Decimal(t), _CTX.multiply(log, log)))


def gamma(t: int, horizon: int = pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME) -> Decimal:
    """gamma_t of the heavy-tailed schedule, normalised over ``1..horizon`` (34 digits)."""
    _check_int(t, "t")
    _check_int(horizon, "horizon")
    if not 1 <= horizon <= pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME:
        raise ValueError(f"horizon must be in [1, {pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME}]")
    if not 1 <= t <= horizon:
        raise ValueError(f"t must be in [1, {horizon}]")
    total = Decimal(0)
    for s in range(1, horizon + 1):
        total = _CTX.add(total, _g(s))
    return _CTX.divide(_g(t), total)


def _check_schedule(schedule: object) -> str:
    if not isinstance(schedule, str):
        raise TypeError("schedule must be a str")
    if schedule not in SCHEDULES:
        raise ValueError(f"unknown alpha schedule {schedule!r}")
    return schedule


def alpha_k(k: int, promotions: int, schedule: str, alpha_total: Decimal) -> Decimal:
    """The level for the lineage's k-th nomination, floor-quantised to 1e-18.

    ``promotions`` is R; ``halving_v1`` ignores it (it is the FWER schedule).
    """
    _check_int(k, "k")
    _check_int(promotions, "promotions")
    _check_schedule(schedule)
    if not isinstance(alpha_total, Decimal):
        raise TypeError("alpha_total must be a Decimal")
    if not alpha_total.is_finite() or not Decimal(0) < alpha_total < _ONE:
        raise ValueError("alpha_total must be a finite Decimal in (0, 1)")
    if not 1 <= k <= pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME:
        raise ValueError(f"k must be in [1, {pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME}]")
    if promotions < 0:
        raise ValueError("promotions must be >= 0")
    if schedule == HALVING_V1:
        raw = _CTX.divide(alpha_total, Decimal(2**k))
    else:
        scaled = _CTX.multiply(alpha_total, gamma(k))
        raw = _CTX.multiply(scaled, Decimal(promotions + 1))
    return raw.quantize(_QUANTUM, rounding=ROUND_FLOOR, context=_CTX)


def require_schedule_pairing(schedule: str, test_kind: str) -> None:
    """E-25 rule 4: elond_heavy_tailed_v1 only on e_process, halving_v1 only on fixed_n."""
    _check_schedule(schedule)
    if test_kind not in (_FIXED_N, _E_PROCESS):
        raise ValueError(f"unknown test_kind {test_kind!r}")
    if _PAIRING[schedule] != test_kind:
        raise ValueError(f"alpha schedule {schedule} is refused on a {test_kind} lineage")


def promotions_before(promotions: Sequence[int], ts_ns: int) -> int:
    """R: the number of effective-PROMOTE instants strictly before ``ts_ns``."""
    if _check_int(ts_ns, "ts_ns") < 0:
        raise ValueError("ts_ns must be >= 0")
    return sum(1 for instant in promotions if instant < ts_ns)
