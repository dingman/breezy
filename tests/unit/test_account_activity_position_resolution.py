"""ARM D1 S-COL: the venue's YES resolution read from ``ACTIVITY_TYPE_POSITION_RESOLUTION`` rows.

The only recorded payload is the 2026-09-05 SFO capture (two resolved markets whose long-YES
holders lost, so both resolve YES = false). Every other case is a SYNTHETIC mutation of that
capture, named as such (``synthetic`` in the test name): a live capture of a YES-paid-out market
or of a NO holder is still owed.

The reading from ``market.marketSides`` must be CORROBORATED by the holder's own side
(``beforePosition.netPosition`` sign) and PnL (``afterPosition.realized`` against
``beforePosition.realized`` / ``cost``); a disagreement is unreadable, never trusted.
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


def _swap_sides(row: dict[str, Any]) -> None:
    for side in row["market"]["marketSides"]:
        side["price"] = "1" if side["long"] else "0"


def _holder(row: dict[str, Any], *, net: str, realized_after: str) -> None:
    row["beforePosition"]["netPosition"] = net
    row["afterPosition"]["realized"]["value"] = realized_after


def test_both_recorded_rows_are_corroborated_by_the_long_holders_loss() -> None:
    rows = _resolution_rows(_page())
    assert len(rows) == 2
    for row in rows:
        resolution = row["positionResolution"]
        before, after = resolution["beforePosition"], resolution["afterPosition"]
        assert float(before["netPosition"]) > 0 and float(after["realized"]["value"]) < 0
        assert parse_position_resolutions({"activities": [row]}).resolutions != ()


def test_a_synthetic_yes_paid_out_market_with_a_long_winner_reads_true() -> None:
    page = _page()
    row = _resolution_rows(page)[0]
    _swap_sides(row["positionResolution"])
    _holder(row["positionResolution"], net="19", realized_after="0.8100")  # long holder WON
    scan = parse_position_resolutions({"activities": [row]})
    assert scan.resolutions == (MarketResolution(NYC, True),) and scan.unreadable == 0


def test_a_synthetic_no_holder_who_won_reads_yes_false() -> None:
    row = _resolution_rows(_page())[0]
    _holder(row["positionResolution"], net="-19", realized_after="0.8100")  # NO holder WON
    scan = parse_position_resolutions({"activities": [row]})
    assert scan.resolutions == (MarketResolution(NYC, False),) and scan.unreadable == 0


def test_a_synthetic_no_holder_who_lost_reads_yes_true() -> None:
    row = _resolution_rows(_page())[0]
    _swap_sides(row["positionResolution"])
    _holder(row["positionResolution"], net="-19", realized_after="-0.9500")  # NO holder LOST
    scan = parse_position_resolutions({"activities": [row]})
    assert scan.resolutions == (MarketResolution(NYC, True),) and scan.unreadable == 0


def _no_holder_won_on_a_yes_market(row: dict[str, Any]) -> None:
    _swap_sides(row)
    _holder(row, net="-19", realized_after="0.8100")


def _unset(row: dict[str, Any], *path: str) -> None:
    node = row
    for key in path[:-1]:
        node = node[key]
    node.pop(path[-1])


@pytest.mark.parametrize(
    "mutate",
    [
        # the market says YES paid out but the long holder LOST (the old swap-only mutation)
        _swap_sides,
        # the market says NO won, so a NO holder must have WON, but the record shows a loss
        lambda r: _holder(r, net="-19", realized_after="-0.9500"),
        # the market says YES paid out, a NO holder must have LOST, but the record shows a win
        _no_holder_won_on_a_yes_market,
        lambda r: _holder(r, net="0", realized_after="-0.9500"),
        lambda r: _holder(r, net="19", realized_after="0.0000"),
        lambda r: _holder(r, net="19", realized_after="-5.0000"),
        lambda r: _holder(r, net="x", realized_after="-0.9500"),
        lambda r: r.pop("beforePosition"),
        lambda r: r.pop("afterPosition"),
        lambda r: _unset(r, "afterPosition", "realized"),
        lambda r: _unset(r, "beforePosition", "cost"),
        lambda r: r["beforePosition"]["cost"].update(value="0.0000"),
    ],
    ids=[
        "market_yes_but_long_holder_lost",
        "market_no_but_no_holder_lost",
        "market_yes_but_no_holder_won",
        "zero_net_position",
        "zero_pnl",
        "loss_larger_than_cost",
        "net_not_a_number",
        "no_before_position",
        "no_after_position",
        "no_realized",
        "no_cost",
        "zero_cost",
    ],
)
def test_a_holder_that_disagrees_with_the_market_sides_is_unreadable(mutate: Any) -> None:
    scan = parse_position_resolutions(_mutated(mutate))
    assert scan.resolutions == () and scan.unreadable == 1


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
        lambda r: r["market"].pop("slug"),
        lambda r: r["market"]["marketSides"][0].pop("identifier"),
        lambda r: [s.pop("identifier") for s in r["market"]["marketSides"]],
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
        "market_slug_absent",
        "identifier_absent_on_one_side",
        "identifier_absent_on_both_sides",
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
