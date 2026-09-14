"""Contract: for every YES/NO ``BinaryOption`` pair, the two legs settle to
values that sum to exactly ``1`` (Decimal), for the whole reachable range of
venue ``settlementPrice`` -- ``0``, ``0.5``, and ``1``.

Plan `NO_SIDE_EDGE_2026-09-14.md` Sec 1 (settlement) / R3-5(ii)/(iii): the
venue publishes exactly one settlement price per market slug, denominated in
the YES outcome (`MarketSettlement`, SDK `types/markets.py:92-97`). This is
the pin the future `SettlementExitActor` and the tape's leg-aware accessor
must both honour, driven off a REAL captured market payload's
``marketSides`` (`parse_binary_option_pair`), never a synthetic pair
invented for this test.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE, leg_of
from breezy.settlement.exit_guard import settlement_price_for_leg

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT = 1_787_617_213_000_000_000


def _load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def market_payload() -> dict[str, Any]:
    return _load_raw("market_open_510636_by_slug.json")


@pytest.mark.parametrize("settlement_price", [Decimal(0), Decimal("0.5"), Decimal(1)])
def test_yes_and_no_settlement_sums_to_one_for_a_real_captured_pair(
    market_payload: dict[str, Any], settlement_price: Decimal
) -> None:
    yes, no = parse_binary_option_pair(
        market_payload, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT
    )
    assert no is not None

    yes_settlement = settlement_price_for_leg(
        leg=leg_of(yes.id), settlement_price=settlement_price
    )
    no_settlement = settlement_price_for_leg(
        leg=leg_of(no.id), settlement_price=settlement_price
    )

    assert leg_of(yes.id) == "yes"
    assert leg_of(no.id) == "no"
    assert yes_settlement + no_settlement == Decimal(1)
