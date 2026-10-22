"""ARM C2 / R12: a harm-stop FAIL actuates, end to end, against a fake venue.

The chain under test is the production one, every link real except the venue:

    FAIL artefact on disk -> ``LossStopProbe`` (strict) -> ``set_family_halted`` ->
    ``TrialDayLatch.record_policy_halt`` (real flock + sqlite store) -> ``family_halt_submit_veto``
    -> ``FqComposedVeto`` -> the strategy's entry veto -> ``cancel_all_orders`` on EVERY instrument
    -> the venue's open-orders book.

The venue is a double that implements what the execution client does for a ``CancelAllOrders``
command (cancel every open order on that instrument's slug) and what the unfiltered
``GET /v1/orders/open`` returns. The assertion that matters is the last one: the unfiltered read is
empty of every slug the strategy posted on.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.normalize.climate_day import local_standard_date
from breezy.registry.sites import default_registry
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.trial_day_latch import open_trial_day_latch
from breezy.strategy.no_ladder_maker import composition
from breezy.strategy.no_ladder_maker.harm_stop import maker_loss_stop_artefact_path
from tests.strategy.no_ladder_maker.maker_strategy_support import (
    FakeVenue,
    Harness,
    want,
)
from tests.support.fq_loss_stop_artefact import write_artefact
from tests.unit.ambig_latch_rig import (
    caps,
    response_sender,
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- fixture
)
from tests.unit.polymarket_us_exec_shapes import RAW, TS_INIT
from tests.unit.test_no_ladder_maker_max_rungs import _venue_order_on
from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate
from tests.unit.test_polymarket_us_resting_cancel import _rig
from tests.unit.test_polymarket_us_resting_submit import _create_body, _expire_ns, _id_n

FAMILY = "pm_us_no_maker_sharp_v1"


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


_BANDS: Final[tuple[str, str]] = ("gte70lt71f", "gte72lt73f")
_DESCRIPTION_FOR_BAND: Final[str] = "less than or equal to 78F"
_BAND_PHRASE: Final[dict[str, str]] = {
    "gte70lt71f": "between 70F and 71F",
    "gte72lt73f": "between 72F and 73F",
}


def _sfo_pair(day: dt.date, band: str, serial: int) -> tuple[BinaryOption, BinaryOption]:
    """The adapter-parsed YES/NO pair of one SFO rung (a captured market, re-slugged)."""
    market = copy.deepcopy(
        json.loads((RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8"))
    )
    body = market["market"]
    old = body["slug"]
    body.update(
        slug=f"tc-temp-sfohigh-{day.isoformat()}-{band}",
        id=str(610_000 + serial),
        title="70 to 71" if band == "gte70lt71f" else "72 to 73",
        titleShort="70 to 71" if band == "gte70lt71f" else "72 to 73",
        description=body["description"].replace(_DESCRIPTION_FOR_BAND, _BAND_PHRASE[band]),
    )
    for side in body["marketSides"]:
        for key, value in list(side.items()):
            if value == old:
                side[key] = body["slug"]
        side["id"] = str(int(side["id"]) + 1_000 * (serial + 1))
    yes, no = parse_binary_option_pair(market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    assert no is not None
    return yes, no


class _RealExecBridge:
    """The strategy's commands go through the REAL execution client; its events come back.

    ``SubmitOrder`` -> ``client._submit_order`` (real admission, ledger, confirm-by-read);
    ``CancelOrder`` -> ``client._cancel_order`` (real per-order cancel: ledger lookup by client
    order id, signed ``POST /v1/order/{id}/cancel``, confirm-by-read). The only doubles are the
    HTTP sender and the venue's order state it mutates. The unfiltered open-orders read is the set
    of orders that venue state still shows NEW.
    """

    def __init__(self, harness: Harness, rig: Any, instruments: dict[str, BinaryOption]) -> None:
        self.h, self.rig, self.instruments = harness, rig, instruments
        self.serial = 0
        self.venue_ids: dict[Any, str] = {}
        rig.sender.on_cancel = self._venue_cancels

    @property
    def client(self) -> Any:
        return self.rig.client

    def _venue_cancels(self, order_id: str) -> None:
        payloads: dict[str, Any] = self.client._private_read._payloads
        payloads[submit_chain.order_by_id_path(order_id)]["order"]["state"] = "ORDER_STATE_CANCELED"

    def unfiltered_open_orders(self) -> list[str]:
        payloads: dict[str, Any] = self.client._private_read._payloads
        rows = [p["order"] for k, p in payloads.items() if k.startswith("/v1/order/")]
        return sorted(r["marketSlug"] for r in rows if r["state"] == "ORDER_STATE_NEW")

    def _new_events(self, before: int) -> list[Any]:
        return list(self.rig.events[before:])

    async def submit(self, command: Any) -> None:
        n, self.serial = self.serial, self.serial + 1
        venue_id = _id_n(n)
        self.venue_ids[command.order.client_order_id] = venue_id
        instrument = self.instruments[str(command.order.instrument_id)]
        self.client._cache.add_order(command.order, position_id=None)
        self.rig.sender.response = response_sender(200, _create_body(venue_id)).response
        self.client._private_read._payloads[submit_chain.order_by_id_path(venue_id)] = (
            _venue_order_on(command, instrument, venue_id)
        )
        before = len(self.rig.events)
        await self.client._submit_order(command)
        names = [type(e).__name__ for e in self._new_events(before)]
        assert "OrderAccepted" in names, names
        self.h.accept(command)

    async def cancel(self, command: Any) -> str:
        """Run one strategy ``CancelOrder`` through the real client; return the event name."""
        order = self.h.cache.order(command.client_order_id)
        before = len(self.rig.events)
        await self.client._cancel_order(command)
        names = [type(e).__name__ for e in self._new_events(before)]
        if "OrderCanceled" in names:
            self.h.cancel_ack(order)
            return "OrderCanceled"
        assert names == ["OrderCancelRejected"], names
        self.h.cancel_reject(order, "execution client refused the cancel")
        return "OrderCancelRejected"


async def _pump_cancels(bridge: _RealExecBridge) -> list[str]:
    outcomes = []
    for command in bridge.h.cancels(bridge.h.drain()):
        outcomes.append(await bridge.cancel(command))
    return outcomes


@pytest.mark.asyncio
@pytest.mark.usefixtures("write_canonical_verified")
async def test_harm_fail_halts_the_family_and_the_real_exec_cancel_path_empties_the_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_operator_gate(monkeypatch, order_count="8")
    store_path = tmp_path / "state.sqlite"
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    sink = _Sink()
    with (
        caps(),
        SqliteStateStore(store_path) as store,
        open_submit_intent_latch(store, store_path) as intent_latch,
    ):
        rig = await _rig(tmp_path, monkeypatch)
        client = rig.client
        now_ns = int(client._clock.timestamp_ns())
        offset = default_registry().climate_day_window("polymarket_us", "SFO").std_utc_offset_hours
        day = local_standard_date(now_ns, offset) + dt.timedelta(days=1)
        pairs = {band: _sfo_pair(day, band, n) for n, band in enumerate(_BANDS)}
        instruments = {str(no.id): no for _yes, no in pairs.values()}
        for no in instruments.values():
            client._cache.add_instrument(no)
            client._instrument_provider.add(no)
        halt_latch = open_trial_day_latch(
            intent_latch, key_prefix=composition.TRIAL_KEY_PREFIX, family_id=FAMILY
        )
        wiring = composition.build_harm_stop_wiring(
            catalog_root=catalog_root,
            halt_veto=family_halt_submit_veto(halt_latch),
            set_family_halted=lambda reason, sha: halt_latch.record_policy_halt(
                reason=reason, evidence_sha256=sha, ts_ns=1
            ),
            clock=lambda: datetime.now(tz=UTC),
            alert_sink=sink,
            alert_every_probe=lambda: True,
            expected_uid=os.getuid(),
        )
        artefact = maker_loss_stop_artefact_path(catalog_root)

        # -- a PASS: the strategy rests two orders, each through the real client ----------------
        write_artefact(artefact, verdict="PASS")
        wiring.probe.probe_once()
        assert wiring.veto() is None
        h = Harness(
            veto=wiring.veto,
            instrument_ids=[yes.id for yes, _no in pairs.values()],
            day=day,
            now_ns=now_ns,
            permit_expires_at_ns=_expire_ns(client),
        )
        h.ladder.window_open_ns = 0  # the window gate is C2's own test; this one is about R12
        bridge = _RealExecBridge(h, rig, instruments)
        rungs = [h.rung(b) for b in _BANDS]
        h.install(lambda ctx: want((rungs[0], 89), (rungs[1], 88)))
        for band in _BANDS:
            h.book(band)
        commands = h.submits(h.drain())
        assert len(commands) == 2
        for command in commands:
            await bridge.submit(command)
        ours = sorted(f"tc-temp-sfohigh-{day.isoformat()}-{b}" for b in _BANDS)
        assert bridge.unfiltered_open_orders() == ours

        # -- the harm stop fails: the probe sets the family halt --------------------------------
        write_artefact(artefact, verdict="FAIL")
        wiring.probe.probe_once()
        assert halt_latch.is_family_halted()
        assert wiring.veto() == "family_halt"

        # -- the strategy notices on its next poll tick; the REAL client cancels per order ------
        h.advance(31)
        assert await _pump_cancels(bridge) == ["OrderCanceled", "OrderCanceled"]
        assert sorted(c["order_id"] for c in rig.sender.cancels) == [_id_n(0), _id_n(1)]
        assert rig.sender.cancel_alls == [], "no venue cancel-all from the strategy path"
        assert not (set(bridge.unfiltered_open_orders()) & set(ours))
        assert bridge.unfiltered_open_orders() == [], "unfiltered open-orders read is empty"
        assert h.ladder.rests == {}

        # -- and nothing is posted again while the halt stands ----------------------------------
        h.book("gte70lt71f", bids=(("0.06", 10),))
        assert h.drain() == [] and bridge.unfiltered_open_orders() == []
        await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("write_canonical_verified")
async def test_an_in_flight_order_cancelled_before_it_binds_is_cancelled_when_the_venue_accepts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V2 end to end: the veto lands while the order is SUBMITTED (no venue id yet).

    The real client REFUSES that cancel (nothing bound); the strategy must not orphan the order:
    when the venue accepts it, the strategy cancels it again and the real client succeeds.
    """
    enable_operator_gate(monkeypatch, order_count="8")
    with caps():
        rig = await _rig(tmp_path, monkeypatch)
        client = rig.client
        now_ns = int(client._clock.timestamp_ns())
        offset = default_registry().climate_day_window("polymarket_us", "SFO").std_utc_offset_hours
        day = local_standard_date(now_ns, offset) + dt.timedelta(days=1)
        yes, no = _sfo_pair(day, _BANDS[0], 0)
        client._cache.add_instrument(no)
        client._instrument_provider.add(no)
        veto: dict[str, str | None] = {"reason": None}
        h = Harness(
            veto=lambda: veto["reason"],
            instrument_ids=[yes.id],
            day=day,
            now_ns=now_ns,
            permit_expires_at_ns=_expire_ns(client),
        )
        h.ladder.window_open_ns = 0
        bridge = _RealExecBridge(h, rig, {str(no.id): no})
        rung = h.rung(_BANDS[0])
        h.install(lambda ctx: want((rung, 89)))
        h.book(_BANDS[0])
        (command,) = h.submits(h.drain())
        h.mark_submitted(command)  # in flight: the client has not bound it yet
        veto["reason"] = "family_halt"
        h.advance(31)
        assert await _pump_cancels(bridge) == ["OrderCancelRejected"], "nothing bound yet"
        await bridge.submit(command)  # the venue accepts it after all
        assert await _pump_cancels(bridge) == ["OrderCanceled"], "cancelled on acceptance"
        assert bridge.unfiltered_open_orders() == []
        assert h.ladder.rests == {}
        await client._disconnect()


def test_without_the_halt_the_same_chain_leaves_the_orders_resting(tmp_path: Path) -> None:
    """Control: the cancel in the test above is caused by the FAIL, not by the harness."""
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    write_artefact(maker_loss_stop_artefact_path(catalog_root), verdict="PASS")
    wiring = composition.build_harm_stop_wiring(
        catalog_root=catalog_root,
        halt_veto=lambda: None,
        set_family_halted=lambda r, e: None,
        clock=lambda: datetime.now(tz=UTC),
        alert_sink=_Sink(),
        alert_every_probe=lambda: True,
        expected_uid=os.getuid(),
    )
    wiring.probe.probe_once()
    h = Harness(veto=wiring.veto)
    venue = FakeVenue(h)
    rung = h.rung("gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    venue.pump()
    h.advance(31)
    venue.pump()
    assert venue.cancel_all_seen == []
    assert venue.unfiltered_open_orders() == ["tc-temp-sfohigh-2026-09-18-gte72lt73f"]
