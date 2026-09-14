"""Pure leg/rung derivation from an instrument id's SYMBOL text (plan
`docs/plans/NO_SIDE_EDGE_2026-09-14.md` R3-5(i), S5 Track D fix-first review).

Moved to the bottom `domain` layer (never `adapters`) because `settlement`
sits BELOW `adapters` in the layer contract
(`pyproject.toml` `[tool.importlinter]` -- `settlement` must not import
`adapters`), yet `settlement.trial_scorer.score_trial` and
`scripts/analysis/family_tally_v2.py` both need to know a trial's leg to
score/tally it correctly. These are the same byte-identical rules as
`breezy.adapters.polymarket_us.symbology.leg_of`/`base_slug_of`/
`sibling_instrument_id`, restated here as plain string functions with no
Nautilus dependency; that adapter module now DELEGATES to this one (see its
docstring) so there is exactly one implementation.

Pure module: no Nautilus, no I/O, no wall clock -- same discipline as
`breezy.settlement.trial_scorer` (which imports this module).
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "INSTRUMENT_SEPARATOR",
    "NO_LEG_SUFFIX",
    "base_symbol_of",
    "leg_of_symbol",
    "sibling_symbol_of",
    "symbol_of_instrument_id",
]

#: Reserved for the NO-leg composite symbol ``<slug><SEP>no``. Byte-identical
#: to `adapters.polymarket_us.symbology.INSTRUMENT_SEPARATOR`, which
#: re-exports this value rather than defining its own.
INSTRUMENT_SEPARATOR: str = "^"

#: The NO-leg composite symbol suffix, appended after `INSTRUMENT_SEPARATOR`.
NO_LEG_SUFFIX: str = "no"

_NO_SUFFIX: str = f"{INSTRUMENT_SEPARATOR}{NO_LEG_SUFFIX}"


def symbol_of_instrument_id(instrument_id: str) -> str:
    """Strip a trailing Nautilus ``.VENUE`` component, if present.

    `FilledTrial.instrument_id`/`ScoredTrial.instrument_id` are stored as
    plain `str` (the D1 settlement-purity rule forbids importing
    `nautilus_trader.model.identifiers.InstrumentId` here); in production
    that string is `str(InstrumentId)` -- ``"<symbol>.<VENUE>"`` -- but
    legacy/test fixtures use a bare symbol with no dot. A base slug can
    never itself contain ``.`` (`symbology.assert_valid_slug` refuses it),
    so splitting on the FIRST ``.`` is safe and never truncates a real
    symbol.
    """
    return instrument_id.split(".", 1)[0]


def leg_of_symbol(symbol: str) -> Literal["yes", "no"]:
    """``"no"`` for a composite NO-leg symbol (`<slug>^no`), else ``"yes"``."""
    return "no" if symbol.endswith(_NO_SUFFIX) else "yes"


def base_symbol_of(symbol: str) -> str:
    """Recover the underlying base slug from either leg's symbol."""
    return symbol.removesuffix(_NO_SUFFIX)


def sibling_symbol_of(symbol: str) -> str:
    """The other leg's (YES<->NO) symbol for the same base slug. An involution."""
    base = base_symbol_of(symbol)
    if leg_of_symbol(symbol) == "no":
        return base
    return f"{base}{_NO_SUFFIX}"
