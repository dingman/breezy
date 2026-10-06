"""AUT-2 r7 WP2 / section 3.4.2: the capture epoch decides which fills C1 may attribute.

A fill is POST_EPOCH iff ``ts_event >= capture_epoch_start`` and its ``client_order_id`` has a C1
OrderLink. An epoch that C1 contradicts (P10) is UNRESOLVED with a CRITICAL, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from breezy.analysis.labeling.epoch import (
    C1Epoch,
    EpochClass,
    EpochOutcome,
    EpochUnreadableInput,
    UnresolvedCause,
    fill_epoch_class,
)
from breezy.persistence import exit_tags
from breezy.persistence.autonomy.capture_epoch import EpochUnreadable, write_epoch_once
from breezy.persistence.autonomy.capture_reader import OrderLinkView
from tests.support.aut2_fixtures import durable_fill
from tests.unit.capture_reader_support import (
    FAMILY,
    YES_INSTRUMENT,
    decision,
    limit_order,
    open_stream,
    write_all,
)

START = 1_000_000


def _link(coid: str, ts_ns: int) -> OrderLinkView:
    return OrderLinkView(
        decision_id=f"dec-{coid}",
        client_order_id=coid,
        venue_order_id_sha256="",
        instrument_id=YES_INSTRUMENT,
        side="1",
        qty="1.00",
        px="0.15",
        time_in_force="2",
        intent_fingerprint="f" * 64,
        ts_ns=ts_ns,
        source="live",
    )


@dataclass
class _Reader:
    """A hand-built epoch reader: the seam the production ``C1Epoch`` fills."""

    start: int | None = START
    unreadable: bool = False
    links: dict[str, OrderLinkView] = field(default_factory=dict)

    def epoch_start_ns(self) -> int | None:
        if self.unreadable:
            raise EpochUnreadable("planted")
        return self.start

    def order_link(self, client_order_id: str) -> OrderLinkView | None:
        return self.links.get(client_order_id)

    def earliest_order_link_ns(self) -> int | None:
        return min((link.ts_ns for link in self.links.values()), default=None)


def _fill(coid: str = "O-1", ts: int = START + 10) -> object:
    return durable_fill(venue_order_id=f"vo-{coid}", client_order_id=coid, ts_event=ts)


def test_absent_epoch_without_order_links_makes_every_fill_pre_epoch() -> None:
    reader = _Reader(start=None)
    for ts in (0, START, START * 1000):
        outcome = fill_epoch_class(_fill("O-1", ts), reader)  # type: ignore[arg-type]
        assert outcome == EpochOutcome(EpochClass.PRE_EPOCH, None, critical=False)


def test_post_epoch_requires_order_link() -> None:
    reader = _Reader(links={"O-1": _link("O-1", START + 5)})

    linked = fill_epoch_class(_fill("O-1", START + 10), reader)  # type: ignore[arg-type]
    assert linked == EpochOutcome(EpochClass.POST_EPOCH, None, critical=False)
    # before the epoch, with or without a link elsewhere, a fill is PRE_EPOCH
    before = fill_epoch_class(_fill("O-9", START - 1), reader)  # type: ignore[arg-type]
    assert before.epoch_class is EpochClass.PRE_EPOCH


def test_post_epoch_fill_without_order_link_is_unresolved() -> None:
    reader = _Reader(links={"O-1": _link("O-1", START + 5)})

    outcome = fill_epoch_class(_fill("O-2", START + 10), reader)  # type: ignore[arg-type]

    assert outcome.epoch_class is None
    assert outcome.unresolved_cause is UnresolvedCause.POST_EPOCH_WITHOUT_ORDER_LINK
    assert outcome.critical is True


def test_missing_epoch_with_order_links_is_unresolved_critical() -> None:
    reader = _Reader(start=None, links={"O-1": _link("O-1", 500)})

    linked = fill_epoch_class(_fill("O-1", 600), reader)  # type: ignore[arg-type]
    later = fill_epoch_class(_fill("O-7", 900), reader)  # type: ignore[arg-type]  # no link, after
    earlier = fill_epoch_class(_fill("O-8", 100), reader)  # type: ignore[arg-type]

    for outcome in (linked, later):
        assert outcome.epoch_class is None
        assert outcome.unresolved_cause is UnresolvedCause.EPOCH_INCONSISTENT_WITH_C1
        assert outcome.critical is True
    assert earlier.epoch_class is EpochClass.PRE_EPOCH  # before any C1 link: still storage-only


def test_unreadable_epoch_with_order_links_is_unresolved_critical() -> None:
    reader = _Reader(unreadable=True, links={"O-1": _link("O-1", 500)})

    outcome = fill_epoch_class(_fill("O-1", 600), reader)  # type: ignore[arg-type]

    assert outcome.epoch_class is None
    assert outcome.unresolved_cause is UnresolvedCause.EPOCH_INCONSISTENT_WITH_C1
    assert outcome.critical is True


def test_order_link_before_epoch_is_unresolved_critical() -> None:
    reader = _Reader(links={"O-1": _link("O-1", START - 1)})  # C1 claims a decision pre-epoch

    outcome = fill_epoch_class(_fill("O-1", START + 10), reader)  # type: ignore[arg-type]

    assert outcome.epoch_class is None
    assert outcome.unresolved_cause is UnresolvedCause.ORDER_LINK_BEFORE_EPOCH
    assert outcome.critical is True


def test_unreadable_epoch_without_order_links_exits_one() -> None:
    reader = _Reader(unreadable=True)

    with pytest.raises(EpochUnreadableInput):
        fill_epoch_class(_fill("O-1", 600), reader)  # type: ignore[arg-type]


def test_real_default_epoch_reader_over_real_epoch_and_c1_streams(tmp_path: Path) -> None:
    """L-55: the production ``C1Epoch`` over a real epoch file and a real capture stream."""
    assert (
        write_epoch_once(
            tmp_path, family_id=FAMILY, node_boot_id="boot-1", build_sha="b" * 40, now_ns=START
        ).epoch_start_ns
        == START
    )
    stream_root = tmp_path / "derived" / "capture_stream" / "polymarket_us"
    stream_root.mkdir(parents=True, mode=0o700)
    order = limit_order(
        InstrumentId.from_str(YES_INSTRUMENT), "0.15", [f"{exit_tags.DECISION_ID_TAG_PREFIX}d1"]
    )
    stream = open_stream(stream_root)
    write_all(stream, [decision(1), order.init_event])
    stream.close()

    reader = C1Epoch(tmp_path, venue="polymarket_us", family_id=FAMILY)

    assert reader.epoch_start_ns() == START
    link = reader.order_link(str(order.client_order_id))
    assert link is not None and link.instrument_id == YES_INSTRUMENT
    assert reader.order_link("O-unknown") is None
    assert reader.earliest_order_link_ns() == link.ts_ns
    outcome = fill_epoch_class(
        durable_fill(client_order_id=str(order.client_order_id), ts_event=link.ts_ns + 10),
        reader,
    )
    assert outcome == EpochOutcome(EpochClass.POST_EPOCH, None, critical=False)
    # the same real link read against a later epoch is C1 claiming a decision before the epoch
    assert link is not None
    link_ts = link.ts_ns
    later = durable_fill(client_order_id=str(order.client_order_id), ts_event=link_ts + 10)

    class _LaterEpoch(C1Epoch):
        def epoch_start_ns(self) -> int | None:
            return link_ts + 1

    outcome = fill_epoch_class(
        later, _LaterEpoch(tmp_path, venue="polymarket_us", family_id=FAMILY)
    )
    assert outcome.unresolved_cause is UnresolvedCause.ORDER_LINK_BEFORE_EPOCH

    absent = C1Epoch(tmp_path / "empty", venue="polymarket_us", family_id=FAMILY)
    (tmp_path / "empty").mkdir()
    assert absent.epoch_start_ns() is None
    assert absent.earliest_order_link_ns() is None
