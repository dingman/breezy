"""ARM C2 / plan r2 delta D4: the evidence for shipping MAX_RUNGS 2.

D4 allows MAX_RUNGS 2 only with a C2 test proving the SECOND NO-leg admission path, "do not rely on
the flag's name", plus per-instrument reconciliation with the venue's NO-as-short-YES netting.
Three independent pieces of evidence:

1. STATIC: no module on the maker -> execution-client route imports or names the exclusive-bucket
   machinery (``RiskManager`` / ``RiskLimits`` / ``exclusive_conflict`` /
   ``allow_overlapping_exclusive_yes``), and no ``src`` module sets that flag True -- so the
   ``exclusive_bucket_conflict`` refusal, which would block a second NO leg on one ladder, is not
   on this path at all (the flag keeps its default False and nothing needs a reviewed True row).
2. DYNAMIC: the real execution client, through its real admission (permit order count, notional
   budget, K=1 latch, ledger), accepts and books a second resting NO-leg order on a DIFFERENT
   instrument of the same ladder, each under its own venue id and ledger exposure.
3. RECONCILIATION: the venue's position mapper turns each rung's negative ``netPosition`` into a
   LONG on that rung's own NO leg -- netting is per market slug, never across the ladder.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Quantity

from breezy.adapters.polymarket_us.exec.reports import parse_position_status_report
from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE, base_slug_of
from breezy.strategy.no_ladder_maker.params import SHARP_V1
from breezy.strategy.weather_common.risk import RiskLimits
from tests.unit.ambig_latch_rig import (
    caps,
    response_sender,
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- fixture
)
from tests.unit.polymarket_us_exec_shapes import (
    ACCOUNT_ID,
    RAW,
    REPORT_ID,
    TS_INIT,
    build_instrument,
    build_no_leg_instrument,
    build_position,
)
from tests.unit.test_current_rung_hold_pre_arm_race import STRATEGY_ID, TRADER_ID
from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate
from tests.unit.test_polymarket_us_resting_submit import (
    _FACTORY,
    _create_body,
    _expire_ns,
    _id_n,
    _rig,
)

REPO: Final[Path] = Path(__file__).resolve().parents[2]
SRC: Final[Path] = REPO / "src" / "breezy"
FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset(
    {"RiskManager", "RiskLimits", "exclusive_conflict", "allow_overlapping_exclusive_yes"}
)
ROUTE_GLOBS: Final[tuple[str, ...]] = (
    "strategy/no_ladder_maker/*.py",
    "adapters/polymarket_us/exec/*.py",
    "adapters/polymarket_us/*.py",
)


def test_the_shipped_rule_runs_two_rungs() -> None:
    assert SHARP_V1.max_rungs == 2


# --- 1. static ----------------------------------------------------------------------------------


def _named(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            found.add(node.arg)
        elif isinstance(node, ast.alias):
            found.add(node.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.update(node.module.split("."))
    return found


def _route_files() -> list[Path]:
    files = sorted({p for pattern in ROUTE_GLOBS for p in SRC.glob(pattern)})
    assert any(p.name == "strategy.py" for p in files)
    assert any(p.name == "client.py" for p in files)
    return files


def test_no_exclusive_bucket_machinery_is_on_the_maker_to_exec_route() -> None:
    offenders = {
        str(p.relative_to(REPO)): sorted(
            _named(ast.parse(p.read_text(encoding="utf-8"))) & (FORBIDDEN_NAMES | {"risk"})
        )
        for p in _route_files()
    }
    assert {k: v for k, v in offenders.items() if v} == {}


def test_the_static_scan_is_not_vacuous() -> None:
    planted = ast.parse(
        "from breezy.strategy.weather_common.risk import RiskManager\nRiskManager()"
    )
    assert _named(planted) & FORBIDDEN_NAMES == {"RiskManager"}


def test_the_overlap_flag_keeps_its_default_and_nothing_in_src_sets_it_true() -> None:
    assert RiskLimits().allow_overlapping_exclusive_yes is False
    assert RiskLimits().allow_short is False
    setters: list[str] = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "allow_overlapping_exclusive_yes"
                and not (isinstance(node.value, ast.Constant) and node.value.value is False)
            ):
                setters.append(str(path.relative_to(REPO)))
    assert setters == []


# --- 2. dynamic: the second NO leg through the real client --------------------------------------


def _second_rung_instruments() -> tuple[BinaryOption, BinaryOption]:
    """The YES/NO pair of a SECOND rung of the shared ladder (``lt69f``; shared: ``lt79f``)."""
    market = json.loads((RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8"))
    market = copy.deepcopy(market)
    body = market["market"]
    old = body["slug"]
    body.update(
        slug="tc-temp-nychigh-2026-08-25-lt69f", id="510637", title="68 or below",
        titleShort="68 or below", description=body["description"].replace("78F", "68F"),
    )  # fmt: skip
    for side in body["marketSides"]:
        for key, value in list(side.items()):
            if value == old:
                side[key] = body["slug"]
        side["id"] = str(int(side["id"]) + 10)
    yes, no = parse_binary_option_pair(market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    assert no is not None
    return yes, no


def _rest_on(client: Any, instrument: BinaryOption) -> SubmitOrder:
    expire = pd.Timestamp(_expire_ns(client), unit="ns", tz="UTC")
    order = _FACTORY.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, instrument.size_precision),
        price=instrument.make_price("0.40"),
        time_in_force=TimeInForce.GTD,
        expire_time=expire,
        post_only=False,
    )
    client._cache.add_order(order, position_id=None)
    return SubmitOrder(
        trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(),
        ts_init=client._clock.timestamp_ns(),
    )  # fmt: skip


def _venue_order_on(
    command: SubmitOrder, instrument: BinaryOption, venue_id: str
) -> dict[str, Any]:
    posted = submit_chain.build_resting_order_body(command.order, instrument)
    return {
        "order": {
            "id": venue_id, "marketSlug": posted["marketSlug"], "side": "ORDER_SIDE_SELL",
            "intent": "ORDER_INTENT_BUY_SHORT", "type": posted["type"], "tif": posted["tif"],
            "state": "ORDER_STATE_NEW", "price": posted["price"], "quantity": posted["quantity"],
            "cumQuantity": 0, "leavesQuantity": posted["quantity"],
            "createTime": "2026-08-25T00:00:14.120237895Z", "goodTillTime": posted["goodTillTime"],
            "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        }
    }  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.usefixtures("write_canonical_verified")
async def test_a_second_no_leg_on_another_rung_of_the_ladder_is_admitted_and_booked_per_instrument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_operator_gate(monkeypatch, order_count="8")
    with caps():
        rig = await _rig(tmp_path, monkeypatch)
        client = rig.client
        first_no = build_no_leg_instrument()
        _yes2, second_no = _second_rung_instruments()
        client._cache.add_instrument(second_no)
        client._instrument_provider.add(second_no)
        assert base_slug_of(first_no.id) != base_slug_of(second_no.id)
        assert (
            base_slug_of(first_no.id).rsplit("-", 1)[0]
            == base_slug_of(second_no.id).rsplit("-", 1)[0]
        )

        for n, instrument in enumerate((first_no, second_no)):
            rig.sender.response = response_sender(200, _create_body(_id_n(n))).response
            command = _rest_on(client, instrument)
            client._private_read._payloads[submit_chain.order_by_id_path(_id_n(n))] = (
                _venue_order_on(command, instrument, _id_n(n))
            )
            await client._submit_order(command)
            assert client._latch.open_slot_count() == 0, "K=1 released after each bind"

        assert rig.event_names().count("OrderAccepted") == 2
        assert "OrderDenied" not in rig.event_names(), "no exclusive-bucket refusal on the route"
        assert sorted(client._resting_bookings) == [_id_n(0), _id_n(1)]
        assert all(
            client._ledger.has_open_exposure(intent_id)
            for intent_id, _booking in client._resting_bookings.values()
        ), "each order carries its own open exposure"
        assert len(rig.sender.calls) == 2
        slugs = {json.loads(call["body"])["marketSlug"] for call in rig.sender.calls}
        assert slugs == {base_slug_of(first_no.id), base_slug_of(second_no.id)}
        await client._disconnect()


# --- 3. reconciliation: NO-as-short-YES netting is per market slug --------------------------


def test_each_rungs_short_yes_position_maps_to_that_rungs_own_no_leg() -> None:
    first_yes, second_yes = build_instrument(), _second_rung_instruments()[0]
    mapped = {}
    for yes in (first_yes, second_yes):
        slug = str(yes.raw_symbol)
        mapped[slug] = parse_position_status_report(
            {**build_position(slug), "netPosition": "-1"},
            market_slug=slug,
            instrument=yes,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )
    assert {m.leg for m in mapped.values()} == {"no"}
    assert {m.report.instrument_id for m in mapped.values()} == {first_yes.id, second_yes.id}
    assert all(m.report.signed_decimal_qty == 1 for m in mapped.values())
    # a second leg never nets against the first: each report is its own market's holding
    assert len({m.report.instrument_id for m in mapped.values()}) == 2
