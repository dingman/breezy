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

import os
from datetime import UTC, datetime
from pathlib import Path

from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.trial_day_latch import open_trial_day_latch
from breezy.strategy.no_ladder_maker import composition
from breezy.strategy.no_ladder_maker.harm_stop import maker_loss_stop_artefact_path
from tests.strategy.no_ladder_maker.maker_strategy_support import (
    BANDS,
    FakeVenue,
    Harness,
    no_id,
    want,
)
from tests.support.fq_loss_stop_artefact import write_artefact

FAMILY = "pm_us_no_maker_sharp_v1"


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def test_harm_fail_halts_the_family_and_every_instrument_is_cancelled(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    sink = _Sink()
    with (
        SqliteStateStore(store_path) as store,
        open_submit_intent_latch(store, store_path) as intent_latch,
    ):
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

        # -- a PASS: the strategy rests two orders on two rungs ---------------------------------
        write_artefact(artefact, verdict="PASS")
        wiring.probe.probe_once()
        assert wiring.veto() is None
        h = Harness(veto=wiring.veto)
        venue = FakeVenue(h)
        rungs = [h.rung("gte70lt71f"), h.rung("gte72lt73f")]
        h.install(lambda ctx: want((rungs[0], 89), (rungs[1], 88)))
        h.book("gte70lt71f")
        h.book("gte72lt73f")
        venue.pump()
        ours = {f"tc-temp-sfohigh-2026-09-18-{b}" for b in ("gte70lt71f", "gte72lt73f")}
        assert set(venue.unfiltered_open_orders()) == ours

        # -- the harm stop fails: the probe sets the family halt --------------------------------
        write_artefact(artefact, verdict="FAIL")
        wiring.probe.probe_once()
        assert halt_latch.is_family_halted()
        assert wiring.veto() == "family_halt"

        # -- the strategy notices on its next poll tick (no book update needed) -----------------
        h.advance(31)
        venue.pump()
        assert sorted(map(str, h.cancel_all_calls)) == sorted(
            str(no_id("SFO", b)) for b in BANDS
        ), "cancel_all_orders was issued for EVERY instrument of the ladder"
        assert sorted(venue.cancel_all_seen) == sorted(
            str(no_id("SFO", b)) for b in ("gte70lt71f", "gte72lt73f")
        ), "and Nautilus put the command on the wire for each instrument that held an order"
        assert not (set(venue.unfiltered_open_orders()) & ours)
        assert venue.unfiltered_open_orders() == [], "unfiltered GET is empty of our slugs"

        # -- and nothing is posted again while the halt stands ----------------------------------
        h.book("gte70lt71f", bids=(("0.06", 10),))
        venue.pump()
        assert venue.unfiltered_open_orders() == []
        assert h.ladder.rests == {}


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
