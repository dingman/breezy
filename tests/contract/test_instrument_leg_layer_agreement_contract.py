"""Contract: `breezy.domain.instrument_leg` and
`breezy.adapters.polymarket_us.symbology` agree on leg/base-slug derivation
(S5 Track D fix-first review, plan `docs/plans/NO_SIDE_EDGE_2026-09-14.md`
R3-5(i)).

`settlement.trial_scorer` and `scripts/analysis/family_tally_v2.py` derive a
trial's leg/rung from `breezy.domain.instrument_leg` because `settlement`
sits BELOW `adapters` in the layer contract and must never import it. This
test is the guarantee that the two independent call sites -- the adapter's
Nautilus-typed API and the domain's plain-string API -- can never silently
diverge.
"""

from __future__ import annotations

import pytest
from nautilus_trader.model.identifiers import InstrumentId, Symbol

from breezy.adapters.polymarket_us.symbology import (
    POLYMARKET_US_VENUE,
    base_slug_of,
    leg_of,
    no_leg_instrument_id,
    slug_to_instrument_id,
)
from breezy.domain.instrument_leg import (
    base_symbol_of,
    leg_of_symbol,
    symbol_of_instrument_id,
)

_SLUGS = (
    "tc-temp-nychigh-2026-08-25-lt79f",
    "instrument-0",  # legacy bare id used throughout the existing test suite
    "kxhighmia-26sep14",
)


@pytest.mark.parametrize("slug", _SLUGS)
def test_yes_leg_agrees_between_layers(slug: str) -> None:
    yes_id = slug_to_instrument_id(slug)
    symbol = str(yes_id.symbol.value)

    assert leg_of(yes_id) == leg_of_symbol(symbol) == "yes"
    assert base_slug_of(yes_id) == base_symbol_of(symbol) == slug


@pytest.mark.parametrize("slug", _SLUGS)
def test_no_leg_agrees_between_layers(slug: str) -> None:
    no_id = no_leg_instrument_id(slug)
    symbol = str(no_id.symbol.value)

    assert leg_of(no_id) == leg_of_symbol(symbol) == "no"
    assert base_slug_of(no_id) == base_symbol_of(symbol) == slug


@pytest.mark.parametrize("slug", _SLUGS)
def test_a_dotted_venue_suffixed_instrument_id_string_agrees_after_symbol_extraction(
    slug: str,
) -> None:
    """`FilledTrial.instrument_id`/`ScoredTrial.instrument_id` are plain
    `str`, in production `str(InstrumentId)` -- ``"<symbol>.<VENUE>"``.
    `symbol_of_instrument_id` strips that suffix before the leg/rung rules
    run; confirm the dotted string and the adapter's own `InstrumentId`
    agree once that extraction happens.
    """
    yes_id = slug_to_instrument_id(slug)
    no_id = no_leg_instrument_id(slug)
    dotted_yes = str(yes_id)
    dotted_no = str(no_id)

    assert dotted_yes.endswith(f".{POLYMARKET_US_VENUE}")
    assert leg_of_symbol(symbol_of_instrument_id(dotted_yes)) == leg_of(yes_id) == "yes"
    assert leg_of_symbol(symbol_of_instrument_id(dotted_no)) == leg_of(no_id) == "no"
    assert base_symbol_of(symbol_of_instrument_id(dotted_yes)) == base_slug_of(yes_id) == slug
    assert base_symbol_of(symbol_of_instrument_id(dotted_no)) == base_slug_of(no_id) == slug


def test_instrument_id_from_str_round_trips_the_dotted_form() -> None:
    slug = _SLUGS[0]
    no_id = no_leg_instrument_id(slug)
    dotted = str(no_id)
    assert InstrumentId.from_str(dotted) == no_id
    assert InstrumentId(Symbol(symbol_of_instrument_id(dotted)), POLYMARKET_US_VENUE) == no_id
