"""AUT-1 WP2: ``CaptureGuardedStrategy`` (plan r12 section 3.6; r8 section 3.5 tests re-targeted).

The guard is a library here: nothing composes it into the live node. Every test drives a real,
registered Nautilus ``Strategy`` subclass; a ``RiskEngine.queue_execute`` endpoint captures the
commands the base class routes, so "reaches super" and "never reaches the cache" are observed, not
assumed. Each test names the mutation it was shown red against.
"""

import time
from dataclasses import fields
from typing import Any

import pytest
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.orders import OrderList

from breezy.persistence.autonomy.canonical import canonical_json, sha256_hex
from breezy.persistence.autonomy.capture_ids import (
    compute_exit_decision_id,
    compute_orphan_decision_id,
)
from breezy.persistence.autonomy.capture_publish import CapturePublisher
from breezy.persistence.autonomy.capture_records import (
    DecisionRecord,
    DetectorEvent,
    FrameCopy,
    make_record,
)
from breezy.persistence.autonomy.veto import VetoReason
from breezy.persistence.exit_tags import (
    DECISION_ID_TAG_PREFIX,
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)
from breezy.strategy.autonomy_capture.guarded_strategy import (
    CaptureGuardedStrategy,
    CaptureIdentity,
)
from tests.support.capture_guard_fakes import (
    FAMILY,
    NOW_NS,
    YES_ID,
    GuardHarness,
    RecordingOutbox,
    RecordingStream,
    identity,
    registered_guard,
)

TAKE_ID = "1" * 32
KEY = ("LAX", "2026-10-05", "i1", "yes")
EVAL_NS = NOW_NS - 5_000_000_000


def _tag(decision_id: str = TAKE_ID) -> list[str]:
    return [f"{DECISION_ID_TAG_PREFIX}{decision_id}"]


def _exit_tags(**overrides: str) -> list[str]:
    values = {
        EXIT_RULE_TAG_PREFIX: "stop",
        EXIT_POSITION_TAG_PREFIX: "pos-1",
        EXIT_FAMILY_TAG_PREFIX: FAMILY,
        EXIT_CLIENT_ORDER_ID_TAG_PREFIX: "coid-1",
    }
    values.update(overrides)
    return [f"{prefix}{value}" for prefix, value in values.items() if value is not None]


def _take_record(decision_id: str = TAKE_ID) -> Any:
    return make_record(
        DecisionRecord,
        ts_event=EVAL_NS,
        ts_init=EVAL_NS,
        decision_id=decision_id,
        family_id=FAMILY,
        node_boot_id="boot-1",
        kind="Take",
        reason="take",
        eval_ns=EVAL_NS,
        eval_seq=1,
        wall_ns=EVAL_NS,
        station=KEY[0],
        climate_day=KEY[1],
        rung_id=KEY[2],
        side=KEY[3],
        instrument=str(YES_ID),
        ask_px="0.15",
        frame_kind="depth10",
        frame_ts_event=EVAL_NS,
        p_hat="0.2",
        p_hat_raw="0.2",
        p_lower="0.17",
        p_upper="0.23",
        ev_net="0.1",
        artefact_sha256="a" * 64,
        manifest_sha256="b" * 64,
    )


def _refused(h: GuardHarness) -> list[tuple[str, str, str]]:
    """The guard's own alerts: the publisher's CAPTURE_PUBLISH_FAILED is a separate event."""
    return [offer for offer in h.outbox.offers if offer[0] == "CAPTURE_REFUSED"]


def _with_take(h: GuardHarness) -> None:
    h.strategy.note_take(_take_record())


# -- construction (C8) -------------------------------------------------------------------------


def test_capture_guarded_strategy_without_publisher_refuses_construction() -> None:
    """MUTATION: dropping the publisher type check lets a guard with no writer boot."""
    from nautilus_trader.trading.config import StrategyConfig

    out = RecordingOutbox()
    for bad in (None, object(), RecordingStream()):
        with pytest.raises(TypeError, match="capture_publisher"):
            CaptureGuardedStrategy(
                StrategyConfig(),
                capture_publisher=bad,  # type: ignore[arg-type]
                alert_outbox=out,
                capture_identity=identity(),
            )


def test_capture_guarded_strategy_without_outbox_refuses_construction() -> None:
    """MUTATION: dropping the outbox check lets a guard that can never alert boot."""
    from nautilus_trader.trading.config import StrategyConfig

    publisher = CapturePublisher(RecordingStream(), family_id=FAMILY)
    for bad in (None, object()):
        with pytest.raises(TypeError, match="alert_outbox"):
            CaptureGuardedStrategy(
                StrategyConfig(),
                capture_publisher=publisher,
                alert_outbox=bad,  # type: ignore[arg-type]
                capture_identity=identity(),
            )


def test_capture_guarded_strategy_without_identity_refuses_construction() -> None:
    from nautilus_trader.trading.config import StrategyConfig

    publisher = CapturePublisher(RecordingStream(), family_id=FAMILY)
    with pytest.raises(TypeError, match="capture_identity"):
        CaptureGuardedStrategy(
            StrategyConfig(),
            capture_publisher=publisher,
            alert_outbox=RecordingOutbox(),
            capture_identity=None,  # type: ignore[arg-type]
        )


def test_guard_dependencies_are_keyword_only() -> None:
    from nautilus_trader.trading.config import StrategyConfig

    publisher = CapturePublisher(RecordingStream(), family_id=FAMILY)
    with pytest.raises(TypeError):
        CaptureGuardedStrategy(  # type: ignore[call-arg]
            StrategyConfig(), publisher, RecordingOutbox(), identity()
        )


def test_identity_rejects_an_unknown_source_and_an_empty_family() -> None:
    with pytest.raises(ValueError, match="source"):
        identity(source="paper")
    with pytest.raises(ValueError, match="family_id"):
        identity(family_id="")
    assert isinstance(identity(), CaptureIdentity)


# -- the happy path -----------------------------------------------------------------------------


def test_a_tagged_buy_with_healthy_capture_is_flushed_then_submitted() -> None:
    """MUTATION: submitting before the flush (or never flushing) breaks the EM4 order."""
    h = registered_guard()
    _with_take(h)
    order = h.order(tags=_tag())

    h.strategy.submit_order(order)

    assert len(h.commands) == 1
    assert h.in_cache(order)
    assert h.stream.flushes == 1
    assert h.outbox.offers == []


def test_guarded_submit_latency_independent_of_webhook() -> None:
    """The happy path never touches the outbox, so a slow webhook cannot slow a submit.

    MUTATION: offering an alert on the happy path makes this wait on the slow outbox.
    """

    class SlowOutbox(RecordingOutbox):
        def offer(self, event: str, severity: str, detail: str) -> bool:
            time.sleep(1.0)
            return super().offer(event, severity, detail)

    h = registered_guard(outbox=SlowOutbox())
    _with_take(h)
    order = h.order(tags=_tag())
    started = time.perf_counter()
    h.strategy.submit_order(order)
    assert time.perf_counter() - started < 0.5
    assert len(h.commands) == 1 and h.outbox.offers == []


# -- BUY tag check (step 3) ---------------------------------------------------------------------


def test_untagged_buy_refused_capture_untagged() -> None:
    """MUTATION: letting an untagged BUY through reaches super (a command is routed)."""
    h = registered_guard()
    order = h.order(tags=None)

    h.strategy.submit_order(order)

    assert h.commands == []
    assert [(e, s) for e, s, _ in h.outbox.offers] == [("CAPTURE_REFUSED", "CRITICAL")]
    assert "capture_untagged" in h.outbox.offers[0][2]


@pytest.mark.parametrize(
    "tags",
    [
        [f"{DECISION_ID_TAG_PREFIX}{TAKE_ID}", f"{DECISION_ID_TAG_PREFIX}{'2' * 32}"],
        [f"{DECISION_ID_TAG_PREFIX}{TAKE_ID}", f"{DECISION_ID_TAG_PREFIX}{TAKE_ID}"],
        [f"{DECISION_ID_TAG_PREFIX}{'A' * 32}"],
        [f"{DECISION_ID_TAG_PREFIX}{'1' * 31}"],
        [f"{DECISION_ID_TAG_PREFIX}{'1' * 33}"],
        [f"{DECISION_ID_TAG_PREFIX}{'g' * 32}"],
        [DECISION_ID_TAG_PREFIX],
        ["unrelated"],
    ],
)
def test_duplicate_or_malformed_tag_refused(tags: list[str]) -> None:
    h = registered_guard()
    h.strategy.submit_order(h.order(tags=tags))
    assert h.commands == []
    assert h.outbox.offers and "capture_untagged" in h.outbox.offers[0][2]


def test_refused_order_never_reaches_cache() -> None:
    """The refusal precedes ``super().submit_order``, so the cache never sees the order."""
    h = registered_guard()
    untagged = h.order(tags=None)
    h.strategy.submit_order(untagged)
    assert not h.in_cache(untagged)


def test_a_buy_carrying_exit_tags_is_not_exempt() -> None:
    """A BUY with exit tags still needs a decision tag: the exit exemption is SELL-only.

    MUTATION: keying the exemption on the exit tags alone lets a BUY bypass capture.
    """
    h = registered_guard()
    order = h.order(side=OrderSide.BUY, tags=_exit_tags())
    h.strategy.submit_order(order)
    assert h.commands == [] and not h.in_cache(order)


def test_untagged_buy_without_known_take_writes_detector_event_not_decision_record() -> None:
    h = registered_guard()
    h.strategy.submit_order(h.order(tags=None))
    assert h.stream.written_of(DecisionRecord) == []
    [event] = h.stream.written_of(DetectorEvent)
    assert event.detector == "capture_writer_health"
    assert event.state == "DISAGREE"
    assert len(event.observation_sha256) == 64


def test_untagged_buy_naming_a_known_take_writes_an_entry_veto() -> None:
    h = registered_guard()
    _with_take(h)
    h.strategy.submit_order(h.order(tags=[f"{DECISION_ID_TAG_PREFIX}{TAKE_ID}", "extra"] * 2))
    [veto] = h.stream.written_of(DecisionRecord)
    assert (veto.kind, veto.reason, veto.decision_id) == ("EntryVeto", "capture_untagged", TAKE_ID)


def test_capture_untagged_is_a_veto_reason() -> None:
    """ARCH section 4.7: both guard refusals are members of the closed VetoReason set."""
    assert VetoReason("capture_untagged") is VetoReason.CAPTURE_UNTAGGED
    assert VetoReason("capture_gap") is VetoReason.CAPTURE_GAP


# -- health and flush (steps 4 and 5) -----------------------------------------------------------


class _LenientPublisher(CapturePublisher):
    """A publisher whose flush claims success, to isolate the guard's own health gate."""

    def flush_for_submit(self) -> bool:
        return True


def test_publisher_health_not_ok_refuses_buy_capture_gap() -> None:
    """Replaces r8's link-write-failure test. The publisher's flush would say True here, so only
    the guard's own health gate can refuse.

    MUTATION: deleting the guard's ``health.ok`` check lets this BUY reach super.
    """
    h = registered_guard(publisher_cls=_LenientPublisher)
    _with_take(h)
    h.stream.health.mark_failed("write_dropped:test")
    order = h.order(tags=_tag())

    h.strategy.submit_order(order)

    assert h.commands == [] and not h.in_cache(order)
    [veto] = h.stream.written_of(DecisionRecord)
    assert (veto.kind, veto.reason) == ("EntryVeto", "capture_gap")
    assert [(e, s) for e, s, _ in h.outbox.offers] == [("CAPTURE_REFUSED", "CRITICAL")]
    assert "capture_gap" in h.outbox.offers[0][2]


def test_a_health_refusal_does_not_flush() -> None:
    h = registered_guard()
    _with_take(h)
    h.stream.health.mark_failed("write_dropped:test")
    h.strategy.submit_order(h.order(tags=_tag()))
    assert h.stream.flushes == 0


def test_a_failed_flush_refuses_the_buy_capture_gap() -> None:
    """MUTATION: ignoring ``flush_for_submit``'s result submits a Take that is not durable."""
    h = registered_guard()
    _with_take(h)
    h.stream.flush_ok = False
    order = h.order(tags=_tag())

    h.strategy.submit_order(order)

    assert h.commands == [] and not h.in_cache(order)
    [veto] = h.stream.written_of(DecisionRecord)
    assert (veto.kind, veto.reason) == ("EntryVeto", "capture_gap")


def test_a_write_drop_since_the_last_flush_refuses_the_buy() -> None:
    h = registered_guard()
    _with_take(h)
    h.stream.pending_drops = 1
    h.strategy.submit_order(h.order(tags=_tag()))
    assert h.commands == []


def test_capture_gap_refusal_cites_frame_by_reference_only() -> None:
    """The r8-final MEDIUM question: a capture_gap refusal is not a Take-path record. Its
    ``EntryVeto`` cites the Take's frame by reference (kind and ts_event) and publishes NO
    ``FrameCopy`` of its own.

    MUTATION: publishing a copy (a citation by value) on the refusal fails the empty-copy check.
    """
    h = registered_guard()
    _with_take(h)
    h.stream.health.mark_failed("write_dropped:test")

    h.strategy.submit_order(h.order(tags=_tag()))

    assert h.stream.written_of(FrameCopy) == []
    [veto] = h.stream.written_of(DecisionRecord)
    assert (veto.frame_kind, veto.frame_ts_event) == ("depth10", EVAL_NS)
    assert not hasattr(veto, "frame_body")
    assert all(f.name != "frame_body" for f in fields(veto))


def test_entry_veto_copies_the_takes_identity_and_nulls_the_probabilities() -> None:
    h = registered_guard()
    _with_take(h)
    h.stream.flush_ok = False
    h.strategy.submit_order(h.order(tags=_tag()))
    [veto] = h.stream.written_of(DecisionRecord)
    assert (veto.eval_ns, veto.eval_seq, veto.ask_px) == (EVAL_NS, 1, "0.15")
    assert (veto.station, veto.climate_day, veto.rung_id, veto.side) == KEY
    assert veto.wall_ns == NOW_NS and veto.ts_event == EVAL_NS
    assert (veto.p_hat, veto.p_hat_raw, veto.p_lower, veto.p_upper, veto.ev_net) == ("",) * 5
    assert veto.artefact_sha256 == "a" * 64


# -- SELL paths (steps 1 and 2) -----------------------------------------------------------------


def test_untagged_sell_links_orphan_id_alerts_and_submits() -> None:
    """D12: SELLs reduce risk, so an untagged one is alerted and still submitted.

    MUTATION: refusing the SELL (or staying silent) fails the submit / alert pair.
    """
    h = registered_guard()
    order = h.order(side=OrderSide.SELL, tags=None)

    h.strategy.submit_order(order)

    assert len(h.commands) == 1 and h.in_cache(order)
    [event] = h.stream.written_of(DetectorEvent)
    assert event.detector == "capture_writer_health" and event.state == "DISAGREE"
    assert [(e, s) for e, s, _ in h.outbox.offers] == [("CAPTURE_REFUSED", "CRITICAL")]
    assert "untagged_sell" in h.outbox.offers[0][2]
    coid = str(order.client_order_id)
    expected = {
        "cause": "untagged_sell",
        "client_order_id": coid,
        "instrument": str(YES_ID),
        "orphan_decision_id": compute_orphan_decision_id(FAMILY, coid),
    }
    assert event.observation_sha256 == sha256_hex(canonical_json(expected))


def test_exit_tagged_order_is_never_refused() -> None:
    """MUTATION: applying the health or flush refusal to an exit blocks a risk-reducing order."""
    h = registered_guard()
    h.stream.health.mark_failed("write_dropped:test")
    h.stream.flush_ok = False
    order = h.order(side=OrderSide.SELL, tags=_exit_tags())
    h.strategy.submit_order(order)
    assert len(h.commands) == 1


def test_legitimate_exit_raises_no_critical() -> None:
    h = registered_guard()
    h.strategy.submit_order(h.order(side=OrderSide.SELL, tags=_exit_tags()))
    assert h.outbox.offers == []
    assert len(h.commands) == 1


def test_exit_with_missing_tag_still_submits_and_alerts() -> None:
    h = registered_guard()
    tags = [t for t in _exit_tags() if not t.startswith(EXIT_POSITION_TAG_PREFIX)]
    h.strategy.submit_order(h.order(side=OrderSide.SELL, tags=tags))
    assert len(h.commands) == 1
    [event] = h.stream.written_of(DetectorEvent)
    assert event.state == "DISAGREE"
    assert h.stream.written_of(DecisionRecord) == []
    assert "exit_capture_gap" in h.outbox.offers[0][2]


def test_exit_whose_publish_fails_still_submits_and_alerts() -> None:
    h = registered_guard()
    h.stream.write_ok = False
    h.strategy.submit_order(h.order(side=OrderSide.SELL, tags=_exit_tags()))
    assert len(h.commands) == 1
    assert any("exit_capture_gap" in detail for _, _, detail in _refused(h))


def test_exit_whose_flush_fails_still_submits_and_raises_a_critical() -> None:
    h = registered_guard()
    h.stream.flush_ok = False
    h.strategy.submit_order(h.order(side=OrderSide.SELL, tags=_exit_tags()))
    assert len(h.commands) == 1
    assert [(e, s) for e, s, _ in _refused(h)] == [("CAPTURE_REFUSED", "CRITICAL")]


def test_exit_record_id_recomputes_from_four_exit_tags_and_has_no_frame_ref() -> None:
    """P1-8: the Exit id hashes the four tag values only; the record cites no frame; its
    FrameCopy holds the order price and is published BEFORE the record (Take-path order).

    MUTATION: swapping the two writes fails the order check.
    """
    h = registered_guard()
    order = h.order(side=OrderSide.SELL, tags=_exit_tags(), price="0.40")

    h.strategy.submit_order(order)

    [record] = h.stream.written_of(DecisionRecord)
    [copy] = h.stream.written_of(FrameCopy)
    expected = compute_exit_decision_id("stop", "pos-1", FAMILY, "coid-1")
    assert record.decision_id == expected == copy.decision_id
    assert record.kind == "Exit"
    assert (record.frame_kind, record.frame_ts_event) == ("", 0)
    assert (copy.frame_kind, copy.frame_ts_event) == ("", 0)
    assert copy.frame_body == {"price": "0.40"}
    assert record.ask_px == "0.40" and record.eval_seq == 0
    assert record.ts_event == record.eval_ns == order.ts_init
    kinds = [type(obj).__name__ for obj in h.stream.written]
    assert kinds == ["FrameCopy", "DecisionRecord"]
    assert h.stream.events[-1] == ("flush", None)


# -- order lists --------------------------------------------------------------------------------


def _list(h: GuardHarness, *orders: Any) -> OrderList:
    return OrderList(h.strategy.order_factory.generate_order_list_id(), list(orders))


def test_submit_order_list_with_untagged_buy_refuses_whole_list() -> None:
    """MUTATION: refusing only the bad order lets the rest of the list through."""
    h = registered_guard()
    _with_take(h)
    good = h.order(tags=_tag())
    bad = h.order(tags=None)

    h.strategy.submit_order_list(_list(h, good, bad))

    assert h.commands == []
    assert not h.in_cache(good) and not h.in_cache(bad)
    causes = " ".join(d for _, _, d in h.outbox.offers)
    assert "capture_untagged" in causes and "capture_order_list_refused" in causes


def test_submit_order_list_of_tagged_orders_submits_once_after_one_flush() -> None:
    h = registered_guard()
    _with_take(h)
    h.strategy.note_take(_take_record("2" * 32))
    a = h.order(tags=_tag())
    b = h.order(tags=_tag("2" * 32))

    h.strategy.submit_order_list(_list(h, a, b))

    assert len(h.commands) == 1
    assert h.stream.flushes == 1
    assert h.in_cache(a) and h.in_cache(b)


def test_submit_order_list_refused_on_a_failed_flush() -> None:
    h = registered_guard()
    _with_take(h)
    h.stream.flush_ok = False
    h.strategy.submit_order_list(_list(h, h.order(tags=_tag())))
    assert h.commands == []


# -- misc -------------------------------------------------------------------------------------


def test_the_capture_key_hook_defaults_to_none() -> None:
    h = registered_guard()
    assert h.strategy._capture_key_of(YES_ID) is None


def test_known_takes_are_bounded() -> None:
    from breezy.strategy.autonomy_capture.guarded_strategy import KNOWN_TAKES_CAP

    h = registered_guard()
    for i in range(KNOWN_TAKES_CAP + 5):
        h.strategy.note_take(_take_record(f"{i:032x}"))
    assert h.strategy.known_take_count() == KNOWN_TAKES_CAP
    h.strategy.note_take(make_record(DecisionRecord, ts_event=1, ts_init=1, kind="Refuse"))
    assert h.strategy.known_take_count() == KNOWN_TAKES_CAP


def test_an_outbox_that_raises_never_breaks_the_refusal() -> None:
    class Boom(RecordingOutbox):
        def offer(self, event: str, severity: str, detail: str) -> bool:
            raise RuntimeError("webhook down")

    h = registered_guard(outbox=Boom())
    h.strategy.submit_order(h.order(tags=None))
    assert h.commands == []
    assert h.strategy.guard_alert_drops == 1
