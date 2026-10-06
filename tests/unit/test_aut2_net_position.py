"""AUT-2 r7 WP2: leg-signed netting (``persistence/autonomy/net_position.py``, owned by ARCH-0).

The venue nets a NO holding as short YES: a NO buy of q counts ``-q`` on the base slug. The sign is
applied before any comparison with the venue (memory: venue-nets-no-holding-as-short-yes).
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling.fill_source import (
    leg_fill_of,
    net_by_base_slug,
    read_durable_fills,
)
from breezy.persistence.autonomy import net_position
from breezy.persistence.autonomy.net_position import LegFill, UnknownSide, net_signed_qty
from tests.support.aut2_fixtures import durable_fill

_SRC = Path(__file__).resolve().parents[2] / "src"


def _leg(leg: str, side: str, qty: str, ts: int = 0) -> LegFill:
    return LegFill(leg=leg, side=side, qty=Decimal(qty), ts_event_ns=ts)  # type: ignore[arg-type]


def test_no_fill_offsets_yes_holding_to_netted_venue_qty() -> None:
    # 5 YES and 3 NO on one base slug: the venue reports the netted +2, never 5 and 3 separately
    fills = [_leg("yes", "BUY", "5"), _leg("no", "BUY", "3")]
    assert net_signed_qty(fills) == Decimal(2)
    # an equal NO holding nets a YES holding to flat
    assert net_signed_qty([_leg("yes", "BUY", "4"), _leg("no", "BUY", "4")]) == Decimal(0)
    # the NO leg alone is short YES
    assert net_signed_qty([_leg("no", "BUY", "3")]) == Decimal(-3)


@pytest.mark.parametrize(
    ("leg", "side", "expected"),
    [("yes", "BUY", 2), ("yes", "SELL", -2), ("no", "BUY", -2), ("no", "SELL", 2)],
)
def test_each_leg_terminal_state(leg: str, side: str, expected: int) -> None:
    assert net_signed_qty([_leg(leg, side, "2")]) == Decimal(expected)
    with pytest.raises(UnknownSide):
        net_signed_qty([_leg(leg, "HOLD", "2")])
    with pytest.raises(UnknownSide):
        net_signed_qty([_leg("maybe", side, "2")])


def test_sell_nets_against_long() -> None:
    assert net_signed_qty([_leg("yes", "BUY", "4"), _leg("yes", "SELL", "1")]) == Decimal(3)
    assert net_signed_qty([_leg("no", "BUY", "4"), _leg("no", "SELL", "4")]) == Decimal(0)
    assert net_signed_qty([]) == Decimal(0)


def test_net_position_imports_no_adapters() -> None:
    tree = ast.parse(Path(net_position.__file__).read_text(encoding="utf-8"))
    roots = {
        (node.module or "") if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name="")])
    }
    assert not {r for r in roots if r.startswith("breezy.adapters")}
    assert (_SRC / "breezy" / "persistence" / "autonomy" / "net_position.py").is_file()


@pytest.mark.asyncio
async def test_no_leg_sign_reconciles_through_real_record_fill_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The NO fill goes in through the real exec client's ``record_fill`` (L-42), comes back out
    through the AUT-2 reader, and its leg-signed net equals what the venue reports for the slug."""
    from nautilus_trader.model.instruments import BinaryOption

    from breezy.runtime.venue_positions_read import read_venue_positions
    from tests.unit import test_no_side_fill_attribution_2026_09_14 as rig

    payload = rig._load_raw("market_open_510636_by_slug.json")
    from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair

    yes, no = parse_binary_option_pair(payload, ts_init=rig.TS_INIT)
    assert isinstance(no, BinaryOption)
    fixture = rig._build_client(tmp_path, legs=(yes, no), monkeypatch=monkeypatch)
    await fixture.client._connect()
    try:
        fill = durable_fill(
            venue_order_id="venue-no-1",
            client_order_id="O-20261002-120000-001-001-1",
            instrument_id=str(no.id),
            qty=Decimal(3),
            cost=Decimal("1.89"),
            ts_event=fixture.client._clock.timestamp_ns(),
        )
        fixture.client.record_fill(fill)  # the real writer, never a hand-built store row
        result = read_durable_fills(fixture.store_path)
    finally:
        await fixture.client._disconnect()

    (stored,) = result.fills
    assert stored.instrument_id == str(no.id) and stored.order_side == "BUY"
    base_slug = str(no.raw_symbol).removesuffix("^no")
    ledger = net_by_base_slug(result.fills)
    assert leg_fill_of(stored).leg == "no"
    assert ledger == {base_slug: Decimal(-3)}  # a NO buy of 3 is -3 on the base slug

    # the venue's own page for the same holding: a NO holding is a negative, short-YES netPosition
    from tests.unit.test_venue_positions_read import _client, _page, _pos, _resp, _ScriptedTransport

    page = _page({base_slug: _pos("-3")}, eof=True)
    venue: Any = await read_venue_positions(
        _client(_ScriptedTransport([_resp(page)])), deadline_s=30.0
    )
    assert venue.complete is True
    venue_net = {slug: qty for slug, qty, _expired in venue.rows}
    assert venue_net == ledger  # sign applied before the compare: MATCH
    unsigned = sum((f.cumulative_qty for f in result.fills), Decimal(0))
    assert unsigned != venue_net[base_slug]  # the unsigned sum would be a false MISMATCH
