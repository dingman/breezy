"""S2 NO-leg ``BinaryOption`` construction (plan `NO_SIDE_EDGE_2026-09-14.md`
section 4 S2). The NO leg's ``outcome`` comes from the venue's own non-long
``marketSides`` entry, never a hardcoded ``"No"``, even though every captured
fixture happens to say "No".
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.errors import InstrumentDefinitionError
from breezy.adapters.polymarket_us.parsing import (
    FEE_COEFFICIENT_KEY,
    LEG_KEY,
    LEG_NO,
    LEG_YES,
    parse_binary_option,
    parse_binary_option_pair,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE, no_leg_instrument_id

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT = 1_787_617_213_000_000_000


def _load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def open_payload() -> dict[str, Any]:
    return _load_raw("market_open_510636_by_slug.json")


def test_the_yes_leg_gains_an_additive_leg_marker(open_payload: dict[str, Any]) -> None:
    yes = parse_binary_option(open_payload, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    assert yes.info[LEG_KEY] == LEG_YES


def test_the_pair_builds_a_no_leg_from_the_venues_own_non_long_side(
    open_payload: dict[str, Any],
) -> None:
    yes, no = parse_binary_option_pair(open_payload, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    assert no is not None
    slug = open_payload["market"]["slug"]
    assert no.id == no_leg_instrument_id(slug)
    assert no.raw_symbol.value == slug
    assert no.outcome == "No"  # the venue's own marketSides[1].description
    assert no.info[LEG_KEY] == LEG_NO
    assert no.info[FEE_COEFFICIENT_KEY] == yes.info[FEE_COEFFICIENT_KEY]


def test_no_leg_outcome_is_never_hardcoded(open_payload: dict[str, Any]) -> None:
    # Prove it is read from the payload, not a literal "No": mutate the
    # venue's own description and the NO leg's outcome follows it.
    mutated = copy.deepcopy(open_payload)
    for side in mutated["market"]["marketSides"]:
        if side.get("long") is not True:
            side["description"] = "Nope"
    _yes, no = parse_binary_option_pair(mutated, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    assert no is not None
    assert no.outcome == "Nope"


def test_a_market_with_no_second_side_has_no_no_leg(open_payload: dict[str, Any]) -> None:
    mutated = copy.deepcopy(open_payload)
    mutated["market"]["marketSides"] = [
        side for side in mutated["market"]["marketSides"] if side.get("long") is True
    ]
    yes, no = parse_binary_option_pair(mutated, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    assert yes is not None
    assert no is None


def test_more_than_one_non_long_side_is_refused(open_payload: dict[str, Any]) -> None:
    mutated = copy.deepcopy(open_payload)
    no_side = next(
        side for side in mutated["market"]["marketSides"] if side.get("long") is not True
    )
    extra = dict(no_side)
    extra["id"] = "extra-side"
    mutated["market"]["marketSides"].append(extra)
    with pytest.raises(InstrumentDefinitionError):
        parse_binary_option_pair(mutated, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
