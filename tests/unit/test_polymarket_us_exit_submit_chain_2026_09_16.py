"""INC-E2b (`docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` §3): the
closing-order mapping seam in `submit_chain.py` --
`unmappable_exit_order_reason` and `build_exit_order_body`.

Sibling to `tests/unit/test_no_side_submit_chain_2026_09_14.py` (plan §3
pinned test #1): that module's naked-short pin
(`test_a_sell_on_the_no_leg_is_still_unmappable`) stays byte-unchanged --
this module proves the two refusal paths are pinned APART, not merged, by
showing the SAME SELL order is refused on the plain BUY-only path and
accepted on the new exit seam once it carries a matching authorisation.

Nothing here wires the seam into `exec/client.py` (INC-E2c, later): every
test below calls `submit_chain` functions directly.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

import pytest
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, StrategyId, TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair
from breezy.persistence.family_manifest import FamilyManifest
from breezy.strategy.current_rung_hold.exit_authorization import ExitAuthorization, ExitRule

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
RAW: Final[Path] = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT: Final[int] = 1_787_617_213_000_000_000
TRADER_ID: Final[TraderId] = TraderId("BREEZY-R7-001")
STRATEGY_ID: Final[StrategyId] = StrategyId("WEATHER-001")
DECIDED_AT_NS: Final[int] = 1_800_000_000_000_000_000

REGISTERED_FAMILY_ID: Final[str] = "pm_us_crh_exit_v4"
REGISTERED_EXIT_RULE: Final[str] = "crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP"

#: `exit_authorization.py` declares this same two-value literal locally
#: (never imported -- it is not in that module's `__all__`); restated here
#: for the same reason: a `strategy/`-layer type must not leak into a test
#: that also exercises the `adapters/`-layer protocol it structurally
#: matches.
Leg = Literal["yes", "no"]


def _load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def legs() -> tuple[BinaryOption, BinaryOption]:
    payload = _load_raw("market_open_510636_by_slug.json")
    yes, no = parse_binary_option_pair(payload, ts_init=TS_INIT)
    assert no is not None
    return yes, no


def _limit_sell(
    instrument: BinaryOption,
    *,
    price: str,
    client_order_id: str = "O-1",
    quantity: int = 1,
) -> Any:
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
    return factory.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.SELL,
        quantity=Quantity(quantity, instrument.size_precision),
        price=Price.from_str(price),
        time_in_force=TimeInForce.IOC,
        client_order_id=ClientOrderId(client_order_id),
    )


def _limit_buy(instrument: BinaryOption, *, price: str, client_order_id: str = "O-1") -> Any:
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
    return factory.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, instrument.size_precision),
        price=Price.from_str(price),
        time_in_force=TimeInForce.IOC,
        client_order_id=ClientOrderId(client_order_id),
    )


class _OrderWithPositionId:
    """Delegates every attribute to the wrapped order except `position_id`.

    A real Nautilus `Order` only carries a non-`None` `position_id` after a
    fill is applied (`model/orders/base.pyx`: ``self.position_id =
    fill.position_id``); the attribute is not writable directly. This
    fixture stands in for what INC-E3's wiring will pass once the strategy
    attributes an exit to its opening fill, without needing to replay a
    whole fill lifecycle here.
    """

    def __init__(self, order: Any, position_id: str) -> None:
        self._order = order
        self._position_id = position_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._order, name)

    @property
    def position_id(self) -> str:
        return self._position_id


def _manifest(*, family_id: str, exit_rule: str | None) -> FamilyManifest:
    return FamilyManifest(
        family_id=family_id,
        venue="polymarket_us",
        trial_id_prefix="crh_exit_v4",
        d0_climate_day="2026-09-16",
        boundary_artefact_path=Path("deploy/boundaries/pm_us_crh_exit_v4.json"),
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("sfo",),
        status="DRAFT_NOT_REGISTERED",
        manifest_sha256="b" * 64,
        exit_rule=exit_rule,
    )


def _registered_manifest() -> FamilyManifest:
    return _manifest(family_id=REGISTERED_FAMILY_ID, exit_rule=REGISTERED_EXIT_RULE)


def _threat_exit_authorization(
    *,
    leg: Leg,
    position_id: str,
    client_order_id: str,
    family_id: str = REGISTERED_FAMILY_ID,
    limit_price: Decimal = Decimal("0.55"),
) -> ExitAuthorization:
    return ExitAuthorization(
        family_id=family_id,
        position_id=position_id,
        client_order_id=client_order_id,
        leg=leg,
        attributed_net_long=1,
        working_sell_qty=0,
        quantity=1,
        limit_price=limit_price,
        rule=ExitRule.R_THREAT,
        expected_settlement_value=Decimal("0.50"),
        fee_coefficient=Decimal("0.06"),
        decided_at_ns=DECIDED_AT_NS,
        book_staleness_ns=0,
    )


def _dead_exit_authorization(
    *,
    leg: Leg,
    position_id: str,
    client_order_id: str,
    family_id: str = REGISTERED_FAMILY_ID,
    limit_price: Decimal = Decimal("0.09"),
) -> ExitAuthorization:
    return ExitAuthorization(
        family_id=family_id,
        position_id=position_id,
        client_order_id=client_order_id,
        leg=leg,
        attributed_net_long=1,
        working_sell_qty=0,
        quantity=1,
        limit_price=limit_price,
        rule=ExitRule.R_DEAD,
        expected_settlement_value=Decimal(0),
        fee_coefficient=Decimal("0.06"),
        decided_at_ns=DECIDED_AT_NS,
        book_staleness_ns=0,
    )


# ---------------------------------------------------------------------------
# Authorised exit -> SELL-action body, per leg (L-44)
# ---------------------------------------------------------------------------


def test_an_authorised_yes_exit_maps_to_a_sell_action_body(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, _no = legs
    order = _limit_sell(yes, price="0.55", client_order_id="O-YES-1")
    authorization = _threat_exit_authorization(
        leg="yes", position_id="POS-YES-1", client_order_id="O-YES-1"
    )
    manifest = _registered_manifest()

    assert submit_chain.unmappable_exit_order_reason(order, yes, authorization, manifest) is None

    body = submit_chain.build_exit_order_body(order, yes, authorization)
    assert body["action"] == "ORDER_ACTION_SELL"
    assert body["outcomeSide"] == "OUTCOME_SIDE_YES"
    assert body["price"] == {"value": "0.55", "currency": "USD"}
    assert body["quantity"] == 1
    assert set(body) == submit_chain.ORDER_BODY_KEYS
    assert "intent" not in body


def test_an_authorised_no_exit_maps_to_a_sell_action_body_with_complemented_price(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """NO at instrument price 0.09 -> wire price 0.91 (plan §3 INC-E2b)."""
    _yes, no = legs
    order = _limit_sell(no, price="0.09", client_order_id="O-NO-1")
    authorization = _dead_exit_authorization(
        leg="no", position_id="POS-NO-1", client_order_id="O-NO-1"
    )
    manifest = _registered_manifest()

    assert submit_chain.unmappable_exit_order_reason(order, no, authorization, manifest) is None

    body = submit_chain.build_exit_order_body(order, no, authorization)
    assert body["action"] == "ORDER_ACTION_SELL"
    assert body["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert body["price"] == {"value": "0.91", "currency": "USD"}
    assert set(body) == submit_chain.ORDER_BODY_KEYS
    assert "intent" not in body


# ---------------------------------------------------------------------------
# The two paths, pinned apart (plan §3 pinned test #1)
# ---------------------------------------------------------------------------


def test_a_sell_order_is_naked_short_on_the_plain_path_but_mappable_on_the_exit_seam(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """The exact SAME order: `unmappable_order_reason` still refuses it
    (byte-identical to `test_no_side_submit_chain_2026_09_14.py`'s pin), and
    the exit seam accepts it once authorised -- the two paths pinned apart,
    never merged.
    """
    yes, _no = legs
    order = _limit_sell(yes, price="0.55", client_order_id="O-PIN-1")

    assert (
        submit_chain.unmappable_order_reason(order, yes)
        == "only a BUY is mappable (a SELL is a naked short); refusing"
    )

    authorization = _threat_exit_authorization(
        leg="yes", position_id="POS-PIN-1", client_order_id="O-PIN-1"
    )
    assert (
        submit_chain.unmappable_exit_order_reason(order, yes, authorization, _registered_manifest())
        is None
    )


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_buy_side_order_refuses_on_the_exit_seam(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, _no = legs
    order = _limit_buy(yes, price="0.55", client_order_id="O-BUY-1")
    authorization = _threat_exit_authorization(
        leg="yes", position_id="POS-BUY-1", client_order_id="O-BUY-1"
    )

    reason = submit_chain.unmappable_exit_order_reason(
        order, yes, authorization, _registered_manifest()
    )
    assert reason == (
        "only a SELL is mappable for a closing exit (a BUY does not close a long); refusing"
    )
    with pytest.raises(ValueError, match="only a SELL is mappable"):
        submit_chain.build_exit_order_body(order, yes, authorization)


def test_an_exit_naming_a_different_client_order_id_refuses(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, _no = legs
    order = _limit_sell(yes, price="0.55", client_order_id="O-RIGHT-1")
    authorization = _threat_exit_authorization(
        leg="yes", position_id="POS-COID-1", client_order_id="O-WRONG-1"
    )

    reason = submit_chain.unmappable_exit_order_reason(
        order, yes, authorization, _registered_manifest()
    )
    assert reason == "authorization client_order_id does not match the order; refusing"
    with pytest.raises(ValueError, match="client_order_id does not match"):
        submit_chain.build_exit_order_body(order, yes, authorization)


def test_an_exit_naming_a_different_position_id_refuses(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, _no = legs
    order = _limit_sell(yes, price="0.55", client_order_id="O-POS-1")
    wrapped = _OrderWithPositionId(order, "POS-WRONG")
    authorization = _threat_exit_authorization(
        leg="yes", position_id="POS-RIGHT", client_order_id="O-POS-1"
    )

    reason = submit_chain.unmappable_exit_order_reason(
        wrapped, yes, authorization, _registered_manifest()
    )
    assert reason == "authorization position_id does not match the order; refusing"
    with pytest.raises(ValueError, match="position_id does not match"):
        submit_chain.build_exit_order_body(wrapped, yes, authorization)


def test_a_2_contract_order_refuses(legs: tuple[BinaryOption, BinaryOption]) -> None:
    yes, _no = legs
    order = _limit_sell(yes, price="0.55", client_order_id="O-QTY-1", quantity=2)
    authorization = _threat_exit_authorization(
        leg="yes", position_id="POS-QTY-1", client_order_id="O-QTY-1"
    )

    reason = submit_chain.unmappable_exit_order_reason(
        order, yes, authorization, _registered_manifest()
    )
    assert reason == "only a 1-contract order is mappable; refusing"
    with pytest.raises(ValueError, match="only a 1-contract order"):
        submit_chain.build_exit_order_body(order, yes, authorization)


def test_a_manifest_without_a_declared_exit_rule_refuses(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, _no = legs
    order = _limit_sell(yes, price="0.55", client_order_id="O-GATE-1")
    authorization = _threat_exit_authorization(
        leg="yes", position_id="POS-GATE-1", client_order_id="O-GATE-1"
    )
    manifest = _manifest(family_id=REGISTERED_FAMILY_ID, exit_rule=None)

    reason = submit_chain.unmappable_exit_order_reason(order, yes, authorization, manifest)
    assert reason == "family does not declare a registered exit rule; refusing"


def test_a_family_not_code_registered_refuses_even_with_a_declared_exit_rule(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """`pm_us_crh_cont` holds to settlement (plan §2): declaring `exit_rule`
    on its own manifest is not enough without the code-side registration in
    `persistence/exit_gate.py`."""
    yes, _no = legs
    order = _limit_sell(yes, price="0.55", client_order_id="O-UNREG-1")
    authorization = _threat_exit_authorization(
        leg="yes",
        position_id="POS-UNREG-1",
        client_order_id="O-UNREG-1",
        family_id="pm_us_crh_cont",
    )
    manifest = _manifest(family_id="pm_us_crh_cont", exit_rule="some_exit_rule_v1")

    reason = submit_chain.unmappable_exit_order_reason(order, yes, authorization, manifest)
    assert reason == "family does not declare a registered exit rule; refusing"


def test_manifest_family_id_mismatched_against_the_authorization_refuses(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, _no = legs
    order = _limit_sell(yes, price="0.55", client_order_id="O-FID-1")
    authorization = _threat_exit_authorization(
        leg="yes",
        position_id="POS-FID-1",
        client_order_id="O-FID-1",
        family_id="some_other_family",
    )

    reason = submit_chain.unmappable_exit_order_reason(
        order, yes, authorization, _registered_manifest()
    )
    assert reason == "manifest family_id does not match the authorization; refusing"


def test_authorization_none_raises_type_error(legs: tuple[BinaryOption, BinaryOption]) -> None:
    yes, _no = legs
    order = _limit_sell(yes, price="0.55")
    manifest = _registered_manifest()

    with pytest.raises(TypeError, match="authorization is required"):
        submit_chain.unmappable_exit_order_reason(order, yes, None, manifest)
    with pytest.raises(TypeError, match="authorization is required"):
        submit_chain.build_exit_order_body(order, yes, None)


# ---------------------------------------------------------------------------
# Structural compatibility (Protocol, not inheritance)
# ---------------------------------------------------------------------------


def test_the_real_exit_authorization_satisfies_the_adapter_protocol_structurally(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """`ExitAuthorization` lives in `strategy/`; `submit_chain.py` never
    imports it (adapters never import strategy/). Assigning the real
    dataclass instance to the `ExitAuthorizationLike` type proves it
    satisfies the protocol structurally, with no inheritance and no
    adapter-side import -- checked by mypy on this line, and exercised at
    runtime by the call below.
    """
    yes, _no = legs
    authorization: submit_chain.ExitAuthorizationLike = _threat_exit_authorization(
        leg="yes", position_id="POS-STRUCT-1", client_order_id="O-STRUCT-1"
    )
    order = _limit_sell(yes, price="0.55", client_order_id="O-STRUCT-1")

    assert (
        submit_chain.unmappable_exit_order_reason(
            order, yes, authorization, _registered_manifest()
        )
        is None
    )
    body = submit_chain.build_exit_order_body(order, yes, authorization)
    assert body["action"] == "ORDER_ACTION_SELL"
