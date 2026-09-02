"""Contract: the trade node's `RiskEngineConfig` really caps a real engine.

Pinned against **``nautilus-trader==1.231.0``** (asserted below).

Relationship to ``tests/contract/test_risk_engine_ordering_enforcement.py``
--------------------------------------------------------------------------
That file pins the ENGINE's ordering hazard -- every cap is inert until an
``AccountState`` is cached (``risk/engine.pyx:684-689``, and again at
``:691-692`` for a margin account). It builds its own cap by hand to do so.

This file pins the OTHER half, which nothing asserted before it: that the
cap the *shipped node config* carries is (a) present at all, (b) the
operator's value rather than one Breezy invented, and (c) actually denies an
over-cap order when driven through a real ``RiskEngine``. A config field
holding a number proves nothing; only a denial does. Neither file is
redundant with the other and neither may be weakened to satisfy the other.

Scope guards
------------
No socket, no node, no venue. A real ``Cache``, ``MessageBus``, ``Portfolio``
and ``RiskEngine`` are built in-process; the instrument is parsed from the
committed raw-capture corpus. Runs under ``scripts/ci/run_tests_no_egress.sh``.

Note on values: ``OPERATOR_CEILING_USD`` below is a TEST-LOCAL stand-in for
the operator's ``BREEZY_MAX_ORDER_NOTIONAL_USD``, chosen only to sit between
the two order notionals. It is not a production risk setting, and this file
assigns no value to either operator-reserved control (max daily budget, max
per position), neither of which appears here at all.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import nautilus_trader
import pytest
from nautilus_trader.accounting.factory import AccountFactory
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import MessageBus, TestClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import AccountType, OrderSide
from nautilus_trader.model.events import AccountState, OrderDenied
from nautilus_trader.model.identifiers import AccountId, StrategyId, TraderId
from nautilus_trader.model.objects import AccountBalance, Money, Price, Quantity
from nautilus_trader.portfolio.portfolio import Portfolio
from nautilus_trader.risk.engine import RiskEngine

from breezy.adapters.polymarket_us.config import (
    PolymarketUSDataClientConfig,
    PolymarketUSExecClientConfig,
)
from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.safety import (
    MAX_ORDER_NOTIONAL_USD_ENV_VAR,
    LiveTradingPermissionError,
)
from breezy.adapters.polymarket_us.symbology import slug_to_instrument_id
from breezy.runtime.node_config import build_trade_node_config
from breezy.runtime.settings import BreezyTradeSettings
from tests.unit.conftest import RAW_CAPTURE_DIR, iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.instruments import BinaryOption

pytestmark = pytest.mark.contract

PINNED_NAUTILUS_VERSION = "1.231.0"

TRADER_ID = TraderId("BREEZYCAPS-001")
STRATEGY_ID = StrategyId("S-NATIVE-CAPS")

#: Test-local stand-in for the operator's per-order USD ceiling.
OPERATOR_CEILING_USD = "25"

LIMIT_PRICE = 0.50
OVER_CAP_QUANTITY = 100  # 100 * 0.50 = 50.00 -> over a 25 ceiling
UNDER_CAP_QUANTITY = 10  # 10 * 0.50 =  5.00 -> under it

#: Free balance on the published account. Large enough that the balance check
#: (`risk/engine.pyx:949-954`) can never be the reason for a denial.
ACCOUNT_BALANCE = 1_000_000


def test_pinned_nautilus_version() -> None:
    """Every `path:line` in this module was read at this version."""
    assert nautilus_trader.__version__ == PINNED_NAUTILUS_VERSION


def _instrument() -> BinaryOption:
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"
    return parse_binary_option(payloads[0], ts_init=0)


def _trade_settings() -> BreezyTradeSettings:
    return BreezyTradeSettings(trader_id=str(TRADER_ID), log_level="INFO")


def _data_client_config(*slugs: str) -> PolymarketUSDataClientConfig:
    return PolymarketUSDataClientConfig(
        # Deliberate test-double origin off the venue domain.
        allow_foreign_origin=True,
        api_base_url="https://api.example.invalid",
        gateway_base_url="https://gateway.example.invalid",
        ws_url="wss://ws.example.invalid",
        instrument_reload_interval_mins=5,
        user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
        market_slugs=slugs,
    )


def _exec_client_config(*slugs: str) -> PolymarketUSExecClientConfig:
    """EXEC SPINE W. `state_store_opener` stays unset -- this file never
    builds a real `TradingNode`, so it is never read."""
    return PolymarketUSExecClientConfig(
        venue=_data_client_config(*slugs),
        account_number="001",
        state_store_path=str(Path(tempfile.mkdtemp()) / "exec_state.db"),
    )


def _account_state(instrument: BinaryOption) -> AccountState:
    """A CASH account whose issuer IS the instrument's venue.

    Both halves matter -- see the sibling contract file's `_account_state`.
    """
    currency = instrument.quote_currency
    return AccountState(
        account_id=AccountId(f"{instrument.id.venue}-001"),
        account_type=AccountType.CASH,
        base_currency=currency,
        reported=True,
        balances=[
            AccountBalance(
                Money(ACCOUNT_BALANCE, currency),
                Money(0, currency),
                Money(ACCOUNT_BALANCE, currency),
            ),
        ],
        margins=[],
        info={},
        event_id=UUID4(),
        ts_event=0,
        ts_init=0,
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class _Rig:
    engine: RiskEngine
    orders: OrderFactory
    instrument: BinaryOption
    denied: list[OrderDenied]
    forwarded: list[SubmitOrder]

    def submit(self, quantity: int) -> None:
        order = self.orders.limit(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,  # Breezy never shorts (`allow_short=False`)
            quantity=Quantity(quantity, self.instrument.size_precision),
            price=Price(LIMIT_PRICE, self.instrument.price_precision),
        )
        self.engine.execute(
            SubmitOrder(
                trader_id=TRADER_ID,
                strategy_id=STRATEGY_ID,
                order=order,
                command_id=UUID4(),
                ts_init=0,
            ),
        )


def _rig() -> _Rig:
    """A real risk engine configured from the SHIPPED trade node config.

    The engine is never handed a hand-rolled cap here: whatever
    `build_trade_node_config` produced is what gets enforced. That is the
    whole point of this file.
    """
    instrument = _instrument()
    slug = str(instrument.id.symbol.value)

    node_config = build_trade_node_config(
        _trade_settings(), _data_client_config(slug), _exec_client_config(slug)
    )

    clock = TestClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    cache.add_instrument(instrument)
    cache.add_account(AccountFactory.create(_account_state(instrument)))
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)

    engine = RiskEngine(
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        config=node_config.risk_engine,
    )

    denied: list[OrderDenied] = []
    forwarded: list[SubmitOrder] = []
    msgbus.register(endpoint="ExecEngine.process", handler=denied.append)
    msgbus.register(endpoint="ExecEngine.execute", handler=forwarded.append)

    return _Rig(
        engine=engine,
        orders=OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=clock),
        instrument=instrument,
        denied=denied,
        forwarded=forwarded,
    )


@pytest.fixture(name="operator_ceiling")
def _operator_ceiling(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, OPERATOR_CEILING_USD)
    return OPERATOR_CEILING_USD


# ---------------------------------------------------------------------------
# The cap denies
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("operator_ceiling")
def test_the_shipped_config_denies_an_over_cap_order_on_a_funded_account() -> None:
    """Behavioural, through the engine: an over-cap order is DENIED.

    Not an assertion that a config field holds a number -- a number the engine
    ignores is not a risk control.
    """
    rig = _rig()

    rig.submit(OVER_CAP_QUANTITY)

    assert rig.forwarded == []
    assert len(rig.denied) == 1
    assert isinstance(rig.denied[0], OrderDenied)
    assert "NOTIONAL_EXCEEDS_MAX_PER_ORDER" in rig.denied[0].reason


@pytest.mark.usefixtures("operator_ceiling")
def test_an_under_cap_order_is_still_accepted() -> None:
    """Non-vacuity: the denial above was the CAP, not the rig refusing all."""
    rig = _rig()

    rig.submit(UNDER_CAP_QUANTITY)

    assert rig.denied == []
    assert len(rig.forwarded) == 1


def test_the_enforced_cap_is_the_operator_value_not_a_breezy_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Change the operator control, and the enforced ceiling changes with it.

    A hardcoded literal or a default argument anywhere on this path makes this
    RED, which is exactly what it is for.
    """
    instrument = _instrument()
    slug = str(instrument.id.symbol.value)

    for raw in ("7", "31"):
        monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, raw)
        config = build_trade_node_config(
            _trade_settings(), _data_client_config(slug), _exec_client_config(slug)
        )

        # Keyed by the INSTRUMENT ID string, not the bare slug:
        # `_initialize_risk_checks` calls `InstrumentId.from_str_c` on every
        # key (`risk/engine.pyx:193-196`), so a slug-keyed mapping would
        # register a cap against an instrument that never trades.
        assert config.risk_engine.max_notional_per_order == {
            str(slug_to_instrument_id(slug)): int(raw)
        }


@pytest.mark.usefixtures("operator_ceiling")
def test_the_cap_is_keyed_by_every_declared_market_and_nothing_else() -> None:
    """The mapping covers exactly the statically declared slugs.

    ``RiskEngineConfig.max_notional_per_order`` is a per-instrument mapping
    (``risk/config.py:44``), not a scalar, so it can only cover instrument IDs
    that exist when the config is built. With no declared slugs the mapping is
    EMPTY and this native cap protects nothing -- a documented residual, not a
    claim of coverage. The per-order chokepoint that always applies is
    ``breezy.adapters.polymarket_us.safety.authorize_live_order_submission``.
    """
    payloads = iter_captured_market_payloads()
    slugs = tuple(dict.fromkeys(str(p["market"]["slug"]) for p in payloads[:3]))
    assert len(slugs) >= 2, "need at least two distinct captured slugs"

    with_slugs = build_trade_node_config(
        _trade_settings(), _data_client_config(*slugs), _exec_client_config(*slugs)
    )
    assert set(with_slugs.risk_engine.max_notional_per_order) == {
        str(slug_to_instrument_id(slug)) for slug in slugs
    }

    without_slugs = build_trade_node_config(
        _trade_settings(), _data_client_config(), _exec_client_config()
    )
    assert without_slugs.risk_engine.max_notional_per_order == {}


@pytest.mark.usefixtures("operator_ceiling")
def test_pre_trade_risk_checks_are_never_bypassed() -> None:
    """``bypass=True`` would silently disable every check above."""
    config = build_trade_node_config(
        _trade_settings(), _data_client_config(), _exec_client_config()
    )

    assert config.risk_engine is not None
    assert config.risk_engine.bypass is False


# ---------------------------------------------------------------------------
# Absence fails closed
# ---------------------------------------------------------------------------


def test_an_unset_operator_control_refuses_instead_of_running_uncapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ceiling -> no trading process. Never a default, never uncapped."""
    monkeypatch.delenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, raising=False)

    with pytest.raises(LiveTradingPermissionError) as excinfo:
        build_trade_node_config(_trade_settings(), _data_client_config(), _exec_client_config())

    assert MAX_ORDER_NOTIONAL_USD_ENV_VAR in str(excinfo.value)


@pytest.mark.parametrize("raw", ["", "   "])
def test_a_blank_operator_control_is_absence_not_a_zero_ceiling(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, raw)

    with pytest.raises(LiveTradingPermissionError) as excinfo:
        build_trade_node_config(_trade_settings(), _data_client_config(), _exec_client_config())

    assert MAX_ORDER_NOTIONAL_USD_ENV_VAR in str(excinfo.value)


def test_a_sub_dollar_ceiling_refuses_rather_than_disabling_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``dict[str, int]`` cannot express $0.50, and 0 DISABLES the check.

    ``risk/engine.pyx:678`` guards with a truthiness test
    (``if max_notional_setting:``), so a ceiling that rounds to 0 is not a
    tight cap -- it is no cap at all. Refusing is the only fail-closed answer.
    """
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, "0.50")

    with pytest.raises(LiveTradingPermissionError) as excinfo:
        build_trade_node_config(_trade_settings(), _data_client_config(), _exec_client_config())

    assert MAX_ORDER_NOTIONAL_USD_ENV_VAR in str(excinfo.value)


@pytest.mark.parametrize("raw", ["", "   ", "0.50", "not-money", "12.345"])
def test_the_refusal_names_the_control_never_the_value(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    """A refusal that echoes the ceiling leaks it into logs and tickets."""
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, raw)

    with pytest.raises(LiveTradingPermissionError) as excinfo:
        build_trade_node_config(_trade_settings(), _data_client_config(), _exec_client_config())

    message = str(excinfo.value)
    assert MAX_ORDER_NOTIONAL_USD_ENV_VAR in message
    if raw.strip():
        assert raw.strip() not in message


# ---------------------------------------------------------------------------
# The venue does not state a maximum trade quantity
# ---------------------------------------------------------------------------


def test_the_venue_payload_states_no_maximum_trade_quantity() -> None:
    """Pins WHY ``BinaryOption.max_quantity`` is left unset.

    ``risk/engine.pyx:1063-1065`` enforces ``instrument.max_quantity`` inside
    ``_check_order`` (reached at ``:449``), which runs BEFORE the account
    lookup -- so unlike the notional cap it is not subject to the fail-open at
    ``:684-689``. It would be the strongest control available here, and it is
    still not set, because the venue states no maximum: every captured market
    object carries ``minimumTradeQty`` and no maximum of any kind. Inventing
    one would be fabricating a venue limit.

    If this goes RED the venue payload gained a ``max``-shaped field. Read it,
    and if it is a trade-size maximum, wire it into ``parse_binary_option``.
    """
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"

    offenders: set[str] = set()
    for payload in payloads:
        market: dict[str, Any] = payload["market"]
        offenders.update(key for key in market if "max" in key.lower())

    assert offenders == set(), (
        f"captured market payloads gained {sorted(offenders)}; if any of these "
        f"is a maximum trade size, set `BinaryOption.max_quantity` from it in "
        f"`parse_binary_option`. Corpus: {RAW_CAPTURE_DIR}"
    )
    assert any("minimumTradeQty" in payload["market"] for payload in payloads), (
        "the minimum-only shape this pin describes is gone"
    )


def test_parsed_instruments_carry_a_minimum_but_no_maximum_quantity() -> None:
    """The parse-level consequence of the pin above, on every captured market."""
    for payload in iter_captured_market_payloads():
        instrument = parse_binary_option(payload, ts_init=0)
        assert instrument.min_quantity is not None
        assert instrument.max_quantity is None


def test_the_corpus_is_real_and_non_empty() -> None:
    """Guards the two pins above from passing on an empty directory."""
    files = sorted(RAW_CAPTURE_DIR.glob("*.json"))
    assert files, f"no captured payloads under {RAW_CAPTURE_DIR}"
    assert any(json.loads(path.read_text(encoding="utf-8")) for path in files)
