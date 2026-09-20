"""Tape-side screen MECHANICS for the forecast family (WP-6 scaffolding).

WHAT THIS IS
------------
The pure arithmetic that turns a model probability plus a venue ask into a
take/no-take decision, net of the venue fee. It exists so WP-7 has a mechanism
to run, and so that mechanism is unit-tested on fixtures BEFORE it is ever
pointed at a variant space.

WHAT THIS IS NOT -- AND MAY NOT BECOME
--------------------------------------
It is NOT the multi-variant cheap screen. That is WP-7, and WP-7 is BLOCKED on
a pre-declared variant set with prediction-market sign-off obtained BEFORE its
first run. Sweeping a variant space now -- or selecting a variant by looking at
WP-6's holdout results -- is multiplicity laundering: the reported edge would be
the maximum of N unreported searches, and no honest p-value or CI survives it.

:func:`screen_tape` therefore REFUSES any call carrying more or fewer than
exactly one variant (:class:`VariantSweepRefused`). The refusal is structural,
not a comment, so the containment cannot lapse silently. Lifting it is a WP-7
change and must arrive with the pre-declaration.

No network, no clock and no I/O. It DOES import the live take rule's fee
(``current_rung_hold.decision.fee_on_ask``) -- deliberately, see
:func:`venue_fee`: a study that restates the fee formula is a study whose
hurdle can drift from the one real money pays. That import pulls
``nautilus_trader`` transitively through the strategy's config module; the
earlier "no strategy import" promise was worth less than agreeing with the
live rule byte for byte. Every other input is caller-supplied.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

from breezy.strategy.current_rung_hold.decision import fee_on_ask

__all__ = [
    "DEFAULT_FEE_COEFFICIENT",
    "REASON_EDGE_BELOW_THRESHOLD",
    "REASON_NO_MODEL_PROBABILITY",
    "REASON_TAKE",
    "SIDE_BUY",
    "ScreenDecision",
    "ScreenVariant",
    "TapeQuote",
    "VariantSweepRefused",
    "net_edge",
    "screen_tape",
    "venue_fee",
]

#: MEASURED 2026-09-17 (L-"venue fee theta drift"): the venue's effective fee
#: COEFFICIENT drifted 0.06 -> 0.0695. This is the coefficient in
#: ``fee = coefficient * price * (1 - price)``, NOT a fee. The repo's
#: ``config.py`` pin deliberately still reads 0.06 (the drift is recorded in
#: ``docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md`` and is
#: not absorbed); a SCREEN asks what a trade would really cost today, so it
#: uses the measured wire value. Carried here as the DEFAULT only; every caller
#: that means a specific run should pass the coefficient that run observed.
#: This module never reads a pin, an environment variable or a config file.
DEFAULT_FEE_COEFFICIENT: Final[float] = 0.0695

#: The only side this module can emit. ``allow_short`` stays ``False`` repo-wide
#: (CLAUDE.md), so a screen that could emit a short would be a defect even if no
#: caller used it today. There is deliberately no ``SIDE_SELL``.
SIDE_BUY: Final[str] = "BUY"

REASON_TAKE: Final[str] = "TAKE"
REASON_EDGE_BELOW_THRESHOLD: Final[str] = "EDGE_BELOW_THRESHOLD"
REASON_NO_MODEL_PROBABILITY: Final[str] = "NO_MODEL_PROBABILITY"

#: Exactly one. See the module docstring.
_ALLOWED_VARIANT_COUNT: Final[int] = 1


class VariantSweepRefused(RuntimeError):
    """Raised when a call would evaluate anything other than exactly one variant."""


@dataclass(frozen=True, slots=True)
class ScreenVariant:
    """One screen configuration: the minimum post-fee edge required to take."""

    min_edge: float

    def __post_init__(self) -> None:
        if not isinstance(self.min_edge, float | int) or isinstance(self.min_edge, bool):
            raise TypeError("min_edge must be a real number")
        if self.min_edge < 0.0:
            raise ValueError("min_edge must not be negative")


@dataclass(frozen=True, slots=True)
class TapeQuote:
    """One offer on one rung of one station-day, as probability units (0..1)."""

    station: str
    climate_day: dt.date
    rung_lower_f: int
    ask_probability: float

    def key(self) -> tuple[str, dt.date, int]:
        return (self.station, self.climate_day, self.rung_lower_f)


@dataclass(frozen=True, slots=True)
class ScreenDecision:
    """The screen's verdict on one quote under one variant."""

    station: str
    climate_day: dt.date
    rung_lower_f: int
    side: str
    take: bool
    reason: str
    ask_probability: float
    model_probability: float | None
    edge: float | None
    min_edge: float

    def to_dict(self) -> dict[str, object]:
        """Explicit serialisation. ``dataclasses.asdict`` is banned repo-wide."""
        return {
            "station": self.station,
            "climate_day": self.climate_day.isoformat(),
            "rung_lower_f": self.rung_lower_f,
            "side": self.side,
            "take": self.take,
            "reason": self.reason,
            "ask_probability": self.ask_probability,
            "model_probability": self.model_probability,
            "edge": self.edge,
            "min_edge": self.min_edge,
        }


def _require_unit_interval(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, float | int):
        raise TypeError(f"{name} must be a real number, was {value!r}")
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} must lie in [0, 1], was {value!r}")
    return float(value)


def venue_fee(
    *, ask_probability: float, fee_coefficient: float = DEFAULT_FEE_COEFFICIENT
) -> float:
    """The venue's per-contract fee at ``ask_probability``, as the LIVE rule pays it.

    ``fee = coefficient * p * (1 - p)``, banker's-rounded to the cent -- which
    is 0.01 at an ask of 0.30 and 0.02 at 0.50, NOT the 0.0695 coefficient.
    The arithmetic is not restated here: it is
    :func:`breezy.strategy.current_rung_hold.decision.fee_on_ask`, the exact
    function ``evaluate_decision`` uses to build ``break_even``. A study that
    re-derives the formula is a study whose hurdle silently drifts from the one
    real money pays, and a FLAT subtraction of the coefficient inflates the
    hurdle by roughly 5x -- enough to manufacture a null that reads as a
    structural absence of edge (WP-7 registration amendment A2).
    """
    ask = _require_unit_interval("ask_probability", ask_probability)
    if isinstance(fee_coefficient, bool) or not isinstance(fee_coefficient, float | int):
        raise TypeError("fee_coefficient must be a real number")
    if fee_coefficient < 0.0:
        raise ValueError("fee_coefficient must not be negative")
    return float(fee_on_ask(Decimal(str(ask)), Decimal(str(fee_coefficient))))


def net_edge(
    *,
    model_probability: float,
    ask_probability: float,
    fee_coefficient: float = DEFAULT_FEE_COEFFICIENT,
) -> float:
    """Post-fee edge of buying one YES contract at ``ask_probability``.

    ``model_probability`` is the model's P(event). Paying ``ask`` plus the
    venue fee ON that ask for a claim worth ``p`` leaves
    ``p - ask - venue_fee(ask)``. Both probabilities are validated: a
    probability outside ``[0, 1]`` is a caller defect, never something to clamp
    silently into a plausible-looking edge.

    The parameter is the fee COEFFICIENT, not a fee. The predecessor took a
    flat ``fee`` and subtracted it whole; that was amendment A2's defect and
    the signature changed so a stale caller fails loudly rather than keeping
    the wrong arithmetic through a defaulted argument.
    """
    p = _require_unit_interval("model_probability", model_probability)
    ask = _require_unit_interval("ask_probability", ask_probability)
    return p - ask - venue_fee(ask_probability=ask, fee_coefficient=fee_coefficient)


def screen_tape(
    *,
    quotes: Sequence[TapeQuote],
    model_probability: Mapping[tuple[str, dt.date, int], float],
    variants: Sequence[ScreenVariant],
    fee_coefficient: float = DEFAULT_FEE_COEFFICIENT,
) -> tuple[ScreenDecision, ...]:
    """Screen every quote under EXACTLY ONE variant.

    Raises
    ------
    VariantSweepRefused
        If ``variants`` does not hold exactly one entry. WP-6 may build and
        test this mechanism; only WP-7, after a pre-declared variant set has
        prediction-market sign-off, may evaluate more than one.
    """
    if len(variants) != _ALLOWED_VARIANT_COUNT:
        raise VariantSweepRefused(
            f"exactly {_ALLOWED_VARIANT_COUNT} variant may be screened here, got "
            f"{len(variants)}. The multi-variant cheap screen is WP-7 and is BLOCKED "
            "on a pre-declared variant set with prediction-market sign-off obtained "
            "BEFORE its first run; sweeping here would launder multiplicity into "
            "WP-6's holdout numbers."
        )
    variant = variants[0]
    decisions: list[ScreenDecision] = []
    for quote in quotes:
        p = model_probability.get(quote.key())
        if p is None:
            decisions.append(
                ScreenDecision(
                    station=quote.station,
                    climate_day=quote.climate_day,
                    rung_lower_f=quote.rung_lower_f,
                    side=SIDE_BUY,
                    take=False,
                    reason=REASON_NO_MODEL_PROBABILITY,
                    ask_probability=quote.ask_probability,
                    model_probability=None,
                    edge=None,
                    min_edge=variant.min_edge,
                )
            )
            continue
        edge = net_edge(
            model_probability=p,
            ask_probability=quote.ask_probability,
            fee_coefficient=fee_coefficient,
        )
        take = edge > variant.min_edge
        decisions.append(
            ScreenDecision(
                station=quote.station,
                climate_day=quote.climate_day,
                rung_lower_f=quote.rung_lower_f,
                side=SIDE_BUY,
                take=take,
                reason=REASON_TAKE if take else REASON_EDGE_BELOW_THRESHOLD,
                ask_probability=quote.ask_probability,
                model_probability=p,
                edge=edge,
                min_edge=variant.min_edge,
            )
        )
    return tuple(decisions)
