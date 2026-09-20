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

No network, no clock, no I/O, no ``nautilus_trader``, no strategy import. Every
input is caller-supplied.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

__all__ = [
    "DEFAULT_FEE",
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
]

#: MEASURED 2026-09-17 (L-"venue fee theta drift"): the venue's effective fee
#: drifted 0.06 -> 0.0695. Carried here as the DEFAULT only; every caller that
#: means a specific run should pass the fee that run observed. This module
#: never reads a pin, an environment variable or a config file.
DEFAULT_FEE: Final[float] = 0.0695

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


def net_edge(*, model_probability: float, ask_probability: float, fee: float) -> float:
    """Post-fee edge of buying one YES contract at ``ask_probability``.

    ``model_probability`` is the model's P(event). Paying ``ask`` plus ``fee``
    for a claim worth ``p`` leaves ``p - ask - fee``. Both probabilities are
    validated: a probability outside ``[0, 1]`` is a caller defect, never
    something to clamp silently into a plausible-looking edge.
    """
    p = _require_unit_interval("model_probability", model_probability)
    ask = _require_unit_interval("ask_probability", ask_probability)
    if isinstance(fee, bool) or not isinstance(fee, float | int):
        raise TypeError("fee must be a real number")
    if fee < 0.0:
        raise ValueError("fee must not be negative")
    return p - ask - float(fee)


def screen_tape(
    *,
    quotes: Sequence[TapeQuote],
    model_probability: Mapping[tuple[str, dt.date, int], float],
    variants: Sequence[ScreenVariant],
    fee: float = DEFAULT_FEE,
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
        edge = net_edge(model_probability=p, ask_probability=quote.ask_probability, fee=fee)
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
