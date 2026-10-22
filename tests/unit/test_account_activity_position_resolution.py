"""ARM D1 S-COL: the venue's YES resolution read from ``ACTIVITY_TYPE_POSITION_RESOLUTION`` rows.

The only recorded payload is the 2026-09-05 SFO capture (two resolved markets whose long-YES
holders lost, so both resolve YES = false). The YES-paid-out case is a SYNTHETIC mutation of that
capture (the two side prices swapped) and is named as such: a live capture of one is still owed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.adapters.polymarket_us.account_activity import (
    MarketResolution,
    parse_position_resolutions,
)

CAPTURE: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json"
)
NYC: Final[str] = "tc-temp-nychigh-2026-08-09-gte94lt95f"
SFO: Final[str] = "tc-temp-sfohigh-2026-08-08-gte74lt75f"


def _page() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(CAPTURE.read_text())["payload"]
    return payload


def _resolution_rows(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in page["activities"] if a["type"] == "ACTIVITY_TYPE_POSITION_RESOLUTION"]


def test_the_recorded_capture_has_two_resolved_markets_both_with_yes_false() -> None:
    scan = parse_position_resolutions(_page())
    assert scan.unreadable == 0
    assert set(scan.resolutions) == {MarketResolution(NYC, False), MarketResolution(SFO, False)}


def test_other_activity_types_are_ignored() -> None:
    page = _page()
    page["activities"] = [a for a in page["activities"] if "RESOLUTION" not in a["type"]]
    assert page["activities"], "the capture also holds trade / deposit rows"
    scan = parse_position_resolutions(page)
    assert scan.resolutions == () and scan.unreadable == 0


def test_a_synthetic_yes_paid_out_market_reads_true() -> None:
    page = _page()
    row = _resolution_rows(page)[0]["positionResolution"]
    for side in row["market"]["marketSides"]:
        side["price"] = "1" if side["long"] else "0"
    scan = parse_position_resolutions({"activities": [_resolution_rows(page)[0]]})
    assert scan.resolutions == (MarketResolution(NYC, True),)


def _mutated(mutate: Any) -> dict[str, Any]:
    page = copy.deepcopy(_page())
    rows = _resolution_rows(page)
    mutate(rows[0]["positionResolution"])
    page["activities"] = rows[:1]
    return page


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["market"].update(status="MARKET_STATUS_OPEN"),
        lambda r: r["market"].update(closed=False),
        lambda r: r["market"].update(slug="tc-temp-other-2026-08-09-gte94lt95f"),
        lambda r: r["market"].update(marketSides=r["market"]["marketSides"][:1]),
        lambda r: [s.update(price="0") for s in r["market"]["marketSides"]],
        lambda r: [s.update(price="1") for s in r["market"]["marketSides"]],
        lambda r: [s.update(price="0.5") for s in r["market"]["marketSides"]],
        lambda r: [s.update(price=None) for s in r["market"]["marketSides"]],
        lambda r: [s.update(long=True) for s in r["market"]["marketSides"]],
        lambda r: r["market"]["marketSides"][0].update(identifier="another-slug"),
        lambda r: r.pop("market"),
        lambda r: r.update(market="nope"),
        lambda r: r.pop("marketSlug"),
        lambda r: r.update(marketSlug=""),
    ],
    ids=[
        "not_resolved",
        "not_closed",
        "slug_mismatch",
        "one_side",
        "both_zero",
        "both_one",
        "half",
        "null_price",
        "two_longs",
        "identifier_mismatch",
        "no_market",
        "market_not_a_mapping",
        "no_slug",
        "empty_slug",
    ],
)
def test_an_ambiguous_resolution_row_is_unreadable_never_guessed(mutate: Any) -> None:
    scan = parse_position_resolutions(_mutated(mutate))
    assert scan.resolutions == ()
    assert scan.unreadable == 1


def test_a_page_without_an_activities_list_is_unreadable_not_empty() -> None:
    assert parse_position_resolutions({}).unreadable == 1
    assert parse_position_resolutions({"activities": "x"}).unreadable == 1
    assert parse_position_resolutions({"activities": []}).unreadable == 0


def test_a_row_that_is_not_a_mapping_is_skipped() -> None:
    scan = parse_position_resolutions({"activities": [None, 3, "x", []]})
    assert scan.resolutions == () and scan.unreadable == 0
