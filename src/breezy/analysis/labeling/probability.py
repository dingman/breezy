"""The bought leg's win probability (AUT-2 r7 WP3, section 3.4.4).

``p_hat`` and ``p_hat_raw`` are P(YES rung) in both FQ side modes, so a YES buy's probability is
``p_hat`` and a NO buy's is ``1 - p_hat``. A take whose side disagrees with the fill's leg cannot be
priced: it is a :class:`LegMismatch`, never a guess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

__all__ = [
    "RECALIBRATION_NONE",
    "BoughtLegP",
    "LegMismatch",
    "artefact_p_raw",
    "bought_leg_probabilities",
]

#: The artefact's ``recalibration`` value under which the raw and the shipped probability coincide.
RECALIBRATION_NONE: Final = "none"
_LEGS: Final = ("yes", "no")


@dataclass(frozen=True)
class BoughtLegP:
    p_at_decision: float
    p_raw_at_decision: float | None


@dataclass(frozen=True)
class LegMismatch:
    """The decision's side is not the leg that filled."""

    side: str
    leg: str


def _probability(name: str, raw: str | float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a number") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must lie in [0, 1]")
    return value


def _bought(value: float, leg: str) -> float:
    return value if leg == "yes" else 1.0 - value


def bought_leg_probabilities(
    *, p_hat: str | float, p_hat_raw: str | float | None, side: str, leg: str
) -> BoughtLegP | LegMismatch:
    """The bought leg's ``(p, p_raw)``; ``LegMismatch`` when ``side`` is not the filled ``leg``.

    An unusable ``p_hat`` raises ``ValueError`` (a take carries one). An empty ``p_hat_raw`` is
    simply unknown and yields ``p_raw_at_decision=None``.
    """
    if leg not in _LEGS:
        raise ValueError(f"leg must be 'yes' or 'no', got {leg!r}")
    if side != leg:
        return LegMismatch(side=side, leg=leg)
    p = _probability("p_hat", p_hat)
    raw = None
    if p_hat_raw is not None and p_hat_raw != "":
        raw = _probability("p_hat_raw", p_hat_raw)
    return BoughtLegP(
        p_at_decision=_bought(p, leg),
        p_raw_at_decision=None if raw is None else _bought(raw, leg),
    )


def artefact_p_raw(p: float, *, recalibration: str | None) -> float | None:
    """``p`` itself as the raw probability only when the bound artefact does not recalibrate."""
    return p if recalibration == RECALIBRATION_NONE else None
