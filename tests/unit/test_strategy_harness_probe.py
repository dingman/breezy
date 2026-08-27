"""Unit tests for `breezy.strategy.harness_probe` -- the reference strategy.

`BreezyHarnessProbe` exists so that a failure in
``tests/contract/test_backtest_harness_stop_gate.py`` is attributable to the
HARNESS. That only holds if the probe itself is trivial and if the three
properties it depends on are pinned here rather than assumed:

* it subscribes to weather by ``client_id`` and never by ``instrument_id``
  (an instrument-scoped weather subscription receives ZERO records, silently);
* its ``on_data`` type-checks before counting (``is_matching_py`` returns True
  for a topic that merely shares a PREFIX, so a record class named
  ``NwsClimateDayExtra`` would leak into this subscription); and
* it imports nothing from ``breezy.adapters.polymarket_us`` -- which is what
  keeps it out of classifier C4 of the read-only guard, and what keeps it
  portable to Kalshi.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.data.messages import (
    SubscribeData,
    SubscribeInstrumentClose,
    SubscribeOrderBook,
    SubscribeQuoteTicks,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.portfolio.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.ingest.nws_actor import nws_climate_day_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID
from breezy.strategy import harness_probe
from breezy.strategy.harness_probe import BreezyHarnessProbe, BreezyHarnessProbeConfig
from tests.support.synthetic_binary_tape import synthetic_binary_tape

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.instruments import Instrument

INSTRUMENT_ID = InstrumentId(Symbol("synthetic-probe-market"), Venue("POLYMARKET_US"))


def make_probe(*, instrument_id: InstrumentId = INSTRUMENT_ID) -> BreezyHarnessProbe:
    return BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=instrument_id,
            trade_quantity=Decimal(10),
        ),
    )


# ---------------------------------------------------------------------------
# It counts, and it starts at zero
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "counter",
    ["quotes", "depths", "weather", "closes", "events", "fills", "maker_fills", "own_fills"],
)
def test_every_counter_starts_at_zero(counter: str) -> None:
    assert getattr(make_probe(), counter) == 0


def test_the_decision_log_starts_empty() -> None:
    assert make_probe().decisions == []


def test_the_probe_has_not_yet_submitted_an_order() -> None:
    assert make_probe().orders_submitted == 0


# ---------------------------------------------------------------------------
# `on_data` guards on TYPE before counting
# ---------------------------------------------------------------------------


class _NotAClimateDay:
    """Stands in for a record that leaked in on a prefix-matching topic."""

    ts_event = 1
    ts_init = 1


def test_on_data_ignores_a_record_that_is_not_a_climate_day() -> None:
    probe = make_probe()

    probe.on_data(_NotAClimateDay())

    assert probe.weather == 0
    assert probe.decisions == []


# ---------------------------------------------------------------------------
# It never raises, and never asserts
# ---------------------------------------------------------------------------


def test_the_probe_module_contains_no_raise_and_no_assert() -> None:
    """A probe that can fail on its own makes the harness unfalsifiable.

    Read from source: "it raises nothing" cannot be asserted at runtime
    without enumerating every input.
    """
    tree = ast.parse(Path(harness_probe.__file__).read_text(encoding="utf-8"))
    offenders = [
        f"line {node.lineno}: {type(node).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise | ast.Assert)
    ]

    assert offenders == []


# ---------------------------------------------------------------------------
# Weather is subscribed by CLIENT, never by instrument
# ---------------------------------------------------------------------------
#
# Driven through a REAL registered `Strategy` and a REAL `MessageBus` rather
# than through patched methods: `Actor.cache` and `Actor.log` are read-only
# Cython attributes and cannot be replaced on an instance, and a test double
# for `subscribe_data` would stop testing the thing that actually carries the
# `client_id` -- the `SubscribeData` command on the bus.


def register(probe: BreezyHarnessProbe, *, instrument: Instrument | None) -> list[Any]:
    """Register `probe` and return the list commands are captured into."""
    clock = TestClock()
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    if instrument is not None:
        cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    commands: list[Any] = []
    msgbus.register(endpoint="DataEngine.execute", handler=commands.append)
    probe.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    return commands


def synthetic_instrument() -> Instrument:
    """The tape's captured instrument, re-keyed to nothing venue-specific.

    Parsed from disk, never fetched: the probe needs an instrument in the
    cache whose `make_qty` honours a real `size_precision`.
    """
    return synthetic_binary_tape(size_precision=0).instrument


def test_on_start_subscribes_to_weather_by_client_id_and_not_by_instrument() -> None:
    instrument = synthetic_instrument()
    probe = make_probe(instrument_id=instrument.id)
    commands = register(probe, instrument=instrument)

    probe.on_start()

    # Type-EXACT: `SubscribeQuoteTicks` and friends all SUBCLASS
    # `SubscribeData`, so an `isinstance` filter would match all four.
    subscriptions = [c for c in commands if type(c) is SubscribeData]
    assert len(subscriptions) == 1
    assert subscriptions[0].data_type is nws_climate_day_data_type()
    assert subscriptions[0].client_id is NWS_BACKTEST_CLIENT_ID
    # The hazard itself: an instrument-scoped weather subscription builds the
    # pattern `data.NwsClimateDay.<venue>.<symbol>`, which never matches
    # `DataType(NwsClimateDay).topic` -- ZERO records, silently.
    assert subscriptions[0].instrument_id is None


def test_on_start_subscribes_to_all_three_venue_streams() -> None:
    instrument = synthetic_instrument()
    probe = make_probe(instrument_id=instrument.id)
    commands = register(probe, instrument=instrument)

    probe.on_start()

    subscribed = {type(c): getattr(c, "instrument_id", None) for c in commands}

    assert subscribed[SubscribeQuoteTicks] == instrument.id
    assert subscribed[SubscribeOrderBook] == instrument.id
    assert subscribed[SubscribeInstrumentClose] == instrument.id


def test_an_unresolvable_instrument_stops_the_strategy_rather_than_raising() -> None:
    """Log and stop -- never raise. A probe that can fail on its own input
    makes every harness failure ambiguous.
    """
    probe = make_probe()
    commands = register(probe, instrument=None)

    probe.on_start()

    assert commands == []
    assert probe.decisions == []


# ---------------------------------------------------------------------------
# Portability: the probe is not venue-touching
# ---------------------------------------------------------------------------


def test_the_probe_imports_nothing_from_the_polymarket_us_adapter() -> None:
    """Classifier C4 of the read-only guard makes any importer of
    `breezy.adapters.polymarket_us` venue-touching, inheriting a write-egress
    cage the probe has no reason to carry. It is also what keeps the probe
    portable to Kalshi: its `InstrumentId` comes from config.
    """
    tree = ast.parse(Path(harness_probe.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert [m for m in imported if "polymarket" in m] == []
