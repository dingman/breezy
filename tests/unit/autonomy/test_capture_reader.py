"""AUT-1 WP1 part B: ``capture_reader`` (plan r12 section 3.9; build rulings WP0-R4, WP1-R1).

Every stream is written by the real ``CaptureStreamWriter`` over a real native
``StreamingFeatherWriter`` on ``tmp_path`` and read back from disk. The reader never re-derives
``eval_ns`` or ``eval_seq`` (the r8 L1 contract), maps streamed enum NAMES back to the
``str(enum)`` forms ``intent_fingerprint`` hashes (WP0-R4), and refuses symlinks.
"""

import dataclasses
import hashlib
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.events import PositionOpened
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.position import Position

from breezy.adapters.polymarket_us.exec.submit_chain import intent_fingerprint
from breezy.adapters.polymarket_us.symbology import no_leg_instrument_id
from breezy.persistence import exit_tags
from breezy.persistence.autonomy import capture_reader
from breezy.persistence.autonomy.capture_ids import (
    compute_exit_decision_id,
    compute_orphan_decision_id,
)
from breezy.persistence.autonomy.capture_reader import (
    FrameSource,
    JoinStatus,
    join_fills_to_decisions,
    project_c1,
    read_capture_stream,
    recompute_intent_fingerprint,
    resolve_frame_ref,
)
from breezy.persistence.autonomy.capture_records import DecisionRecord
from breezy.persistence.autonomy.single_read import SingleReadReason, SingleReadRefused
from tests.unit.aut1_premises_support import (
    RECORDED_ORDER_FILLED,
    _filled_from_recorded,
    _instrument,
    _recorded_lifecycle,
)
from tests.unit.capture_reader_support import (
    FAMILY,
    YES_INSTRUMENT,
    boot_dir,
    decision,
    detector,
    filled,
    forecast_point,
    frame_copy,
    heartbeat,
    limit_order,
    open_stream,
    order_event,
    write_all,
)

TAG = exit_tags.DECISION_ID_TAG_PREFIX
NO_INSTRUMENT = str(no_leg_instrument_id("tc-temp-laxhigh-2026-10-04-gte93lt94f"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(tmp_path: Path) -> Any:
    return read_capture_stream(boot_dir(tmp_path))


# -- read_capture_stream -----------------------------------------------------------------------


def test_read_returns_every_custom_type_in_stream_order(tmp_path: Path) -> None:
    stream = open_stream(tmp_path)
    write_all(
        stream,
        [
            decision(2),
            decision(1),
            frame_copy("d1"),
            order_event("OrderAccepted", "O-1"),
            detector(),
            heartbeat(1),
            forecast_point("TXN_Q10", 70.0),
        ],
    )
    stream.close()
    got = _read(tmp_path)
    assert [d.decision_id for d in got.decisions] == ["d2", "d1"]  # stream order, not sorted
    assert [c.decision_id for c in got.frame_copies] == ["d1"]
    assert got.frame_copies[0].frame_body == {"ask": "0.15"}
    assert [e.event_type for e in got.order_events] == ["OrderAccepted"]
    assert [d.detector for d in got.detector_events] == ["md_feed_freshness"]
    assert [h.seq for h in got.heartbeats] == [1]
    assert [(p.variable, p.value_f) for p in got.forecast_points] == [("TXN_Q10", 70.0)]
    assert got.instance_id == "inst-1" and got.source == "live"
    assert got.torn_tails == ()


def test_read_orders_a_multi_file_table_by_the_integer_timestamp_in_the_name(
    tmp_path: Path,
) -> None:
    """``..._99`` is older than ``..._1791...``: numeric order, never lexical."""
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1)])
    stream.close()
    other = open_stream(tmp_path, instance_id="inst-2")
    write_all(other, [decision(2)])
    other.close()
    (newer,) = boot_dir(tmp_path, instance_id="inst-2").glob("custom_decision_record_*.feather")
    (boot_dir(tmp_path) / "custom_decision_record_99.feather").write_bytes(newer.read_bytes())
    assert [d.decision_id for d in _read(tmp_path).decisions] == ["d2", "d1"]


def test_read_missing_directory_is_a_not_found_refusal(tmp_path: Path) -> None:
    with pytest.raises(SingleReadRefused) as caught:
        read_capture_stream(tmp_path / "live" / "nope")
    assert caught.value.reason is SingleReadReason.NOT_FOUND


def test_unrecognised_feather_files_are_listed_never_silently_dropped(tmp_path: Path) -> None:
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1)])
    stream.close()
    (boot_dir(tmp_path) / "custom_mystery_5.feather").write_bytes(b"x")
    (boot_dir(tmp_path) / "notes.txt").write_text("x", encoding="utf-8")
    got = _read(tmp_path)
    assert got.unrecognised_files == ("custom_mystery_5.feather", "notes.txt")


def test_reader_refuses_symlinks(tmp_path: Path) -> None:
    """MUTATION (red): opening without ``O_NOFOLLOW`` reads the link target instead of refusing."""
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1)])
    stream.close()
    directory = boot_dir(tmp_path)
    (real,) = directory.glob("custom_decision_record_*.feather")
    target = tmp_path / "elsewhere.feather"
    target.write_bytes(real.read_bytes())
    os.symlink(target, directory / "custom_decision_record_7.feather")
    with pytest.raises(SingleReadRefused) as caught:
        _read(tmp_path)
    assert caught.value.reason is SingleReadReason.SYMLINK


def test_reader_refuses_a_symlinked_non_feather_entry_too(tmp_path: Path) -> None:
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1)])
    stream.close()
    os.symlink(tmp_path, boot_dir(tmp_path) / "sideways")
    with pytest.raises(SingleReadRefused) as caught:
        _read(tmp_path)
    assert caught.value.reason is SingleReadReason.SYMLINK


def test_reader_refuses_a_symlinked_boot_directory(tmp_path: Path) -> None:
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1)])
    stream.close()
    link = tmp_path / "live" / "linked"
    os.symlink(boot_dir(tmp_path), link)
    with pytest.raises(SingleReadRefused) as caught:
        read_capture_stream(link)
    assert caught.value.reason is SingleReadReason.SYMLINK


def test_truncated_final_batch_is_stream_torn_tail(tmp_path: Path) -> None:
    """A chopped last batch keeps the readable prefix and is NAMED, with the bytes it lost.

    MUTATION (red): reading with ``read_all`` (all-or-nothing) loses every complete row, and a
    reader that never classifies leaves ``torn_tails`` empty.
    """
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1), decision(2), decision(3)])
    directory = boot_dir(tmp_path)
    (path,) = directory.glob("custom_decision_record_*.feather")
    size = path.stat().st_size
    with path.open("r+b") as handle:
        handle.truncate(size - 9)
    got = _read(tmp_path)
    assert [d.decision_id for d in got.decisions] == ["d1", "d2"]
    (torn,) = got.torn_tails
    assert torn.table == "custom_decision_record"
    assert torn.file_name == path.name
    assert torn.size_bytes == size - 9
    assert 0 < torn.lost_bytes < torn.size_bytes
    assert got.has_torn_tail is True


def test_a_clean_stream_has_no_torn_tail_even_without_the_end_marker(tmp_path: Path) -> None:
    """A running boot's files end on a message boundary with no end-of-stream marker: not torn."""
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1), decision(2)])  # flushed, never closed
    got = _read(tmp_path)
    assert got.torn_tails == () and got.has_torn_tail is False
    assert len(got.decisions) == 2


# -- C1 projection -----------------------------------------------------------------------------


def test_projection_yields_c1_record_names_and_fields(tmp_path: Path) -> None:
    stream = open_stream(tmp_path)
    take = decision(
        1,
        eval_seq=3,
        ask_px="0.15",
        p_hat="0.4",
        frame_kind="depth10",
        frame_ts_event=501,
        forecast_station="KLAX",
        forecast_cycle_ns=100,
        forecast_available_at_ns=102,
    )
    quote = decision(2, frame_kind="quote", frame_ts_event=77)
    exit_ = decision(3, kind="Exit", frame_kind="", frame_ts_event=0, forecast_station="")
    write_all(stream, [take, quote, exit_, detector()])
    stream.close()
    view = project_c1(_read(tmp_path))
    d1, d2, d3 = view.decisions
    assert d1.instrument_id == YES_INSTRUMENT
    assert d1.ts_ns == 1001  # ts_init is C1's ts_ns
    assert d1.eval_ns == 1 and d1.eval_seq == 3
    assert d1.depth_ref == f"depth10:{YES_INSTRUMENT}@501" and d1.quote_ref == ""
    assert d2.quote_ref == f"quote:{YES_INSTRUMENT}@77" and d2.depth_ref == ""
    assert d3.depth_ref == "" and d3.quote_ref == ""  # Exit cites no frame
    assert d1.forecast_input_ref == "nbp:KLAX@100@102"
    assert d3.forecast_input_ref == ""
    assert (d1.ask_px, d1.p_hat, d1.family_id) == ("0.15", "0.4", FAMILY)
    for gone in ("instrument", "ts_init", "frame_kind", "frame_ts_event", "forecast_station"):
        assert not hasattr(d1, gone), gone
    assert [d.detector for d in view.detector_events] == ["md_feed_freshness"]  # as stored


def test_decision_view_field_set_is_the_stored_set_with_the_c1_renames() -> None:
    stored_fields = {f.name for f in dataclasses.fields(cast(Any, DecisionRecord))} - {
        "ts_event",
        "ts_init",
    }
    view_fields = {f.name for f in dataclasses.fields(capture_reader.DecisionView)}
    renamed_away = {"instrument", "frame_kind", "frame_ts_event"} | {
        "forecast_station",
        "forecast_cycle_ns",
        "forecast_available_at_ns",
    }
    added = {"instrument_id", "ts_ns", "depth_ref", "quote_ref", "forecast_input_ref"}
    assert view_fields == (stored_fields - renamed_away) | added


def test_forecast_input_ref_carries_available_at_ns(tmp_path: Path) -> None:
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1, forecast_available_at_ns=123_456)])
    stream.close()
    (d,) = project_c1(_read(tmp_path)).decisions
    assert d.forecast_input_ref.endswith("@123456")
    assert d.forecast_input_ref.startswith("nbp:KLAX@")


@pytest.mark.parametrize(
    ("instrument_id", "price"), [(YES_INSTRUMENT, "0.15"), (NO_INSTRUMENT, "0.85")]
)
def test_order_link_projected_from_order_initialized_tags(
    tmp_path: Path, instrument_id: str, price: str
) -> None:
    """WP0-R4: streamed enum NAMES map back to ``str(enum)`` and the price comes from ``options``,
    so the recomputed fingerprint equals the one of the REAL order, on the YES and the NO leg.

    MUTATION (red): hashing the streamed names (``BUY``/``IOC``) instead of the mapped forms, or
    reading the null ``price`` column, gives a different digest.
    """
    order = limit_order(InstrumentId.from_str(instrument_id), price, [f"{TAG}abc123"])
    stream = open_stream(tmp_path)
    write_all(stream, [order.init_event])
    stream.close()
    (link,) = project_c1(_read(tmp_path)).order_links
    assert link.decision_id == "abc123"
    assert link.client_order_id == str(order.client_order_id)
    assert link.instrument_id == instrument_id
    assert (link.side, link.qty, link.px, link.time_in_force) == ("1", "1.00", price, "2")
    assert link.intent_fingerprint == intent_fingerprint(order)
    assert recompute_intent_fingerprint(link) == intent_fingerprint(order)


def test_intent_fingerprint_differs_without_the_enum_name_map(tmp_path: Path) -> None:
    """The negative control the mutation row relies on: raw names do not recompute."""
    order = limit_order(InstrumentId.from_str(YES_INSTRUMENT), "0.15", [f"{TAG}x"])
    stream = open_stream(tmp_path)
    write_all(stream, [order.init_event])
    stream.close()
    (link,) = project_c1(_read(tmp_path)).order_links
    raw = dataclasses.replace(link, side="BUY", time_in_force="IOC")
    assert recompute_intent_fingerprint(raw) != intent_fingerprint(order)


def test_order_link_decision_id_for_exit_tags_and_untagged_orders(tmp_path: Path) -> None:
    exit_tags_list = [
        f"{exit_tags.EXIT_RULE_TAG_PREFIX}r1",
        f"{exit_tags.EXIT_POSITION_TAG_PREFIX}p1",
        f"{exit_tags.EXIT_FAMILY_TAG_PREFIX}f1",
        f"{exit_tags.EXIT_CLIENT_ORDER_ID_TAG_PREFIX}c1",
    ]
    exit_order = limit_order(InstrumentId.from_str(YES_INSTRUMENT), "0.20", exit_tags_list)
    plain = limit_order(InstrumentId.from_str(YES_INSTRUMENT), "0.15", None, ordinal=2)
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1), exit_order.init_event, plain.init_event])
    stream.close()
    links = {link.client_order_id: link for link in project_c1(_read(tmp_path)).order_links}
    assert links[str(exit_order.client_order_id)].decision_id == compute_exit_decision_id(
        "r1", "p1", "f1", "c1"
    )
    assert links[str(plain.client_order_id)].decision_id == compute_orphan_decision_id(
        FAMILY, str(plain.client_order_id)
    )


def test_order_link_venue_order_id_comes_from_accepted_or_fill_never_raw(tmp_path: Path) -> None:
    accepted_order = limit_order(InstrumentId.from_str(YES_INSTRUMENT), "0.15", [f"{TAG}a"])
    filled_order = limit_order(
        InstrumentId.from_str(YES_INSTRUMENT), "0.16", [f"{TAG}b"], ordinal=2
    )
    bare_order = limit_order(InstrumentId.from_str(YES_INSTRUMENT), "0.17", [f"{TAG}c"], ordinal=3)
    stream = open_stream(tmp_path)
    write_all(
        stream,
        [
            accepted_order.init_event,
            filled_order.init_event,
            bare_order.init_event,
            order_event(
                "OrderAccepted",
                str(accepted_order.client_order_id),
                venue_order_id_sha256=_sha("VENUE-A"),
            ),
            filled(str(filled_order.client_order_id), venue_order_id="VENUE-F"),
        ],
    )
    stream.close()
    links = {link.client_order_id: link for link in project_c1(_read(tmp_path)).order_links}
    assert links[str(accepted_order.client_order_id)].venue_order_id_sha256 == _sha("VENUE-A")
    assert links[str(filled_order.client_order_id)].venue_order_id_sha256 == _sha("VENUE-F")
    assert links[str(bare_order.client_order_id)].venue_order_id_sha256 == ""


def test_lifecycle_events_from_fills_and_order_event_records(tmp_path: Path) -> None:
    stream = open_stream(tmp_path)
    write_all(
        stream,
        [
            order_event("OrderSubmitted", "O-1", decision_id="d1", ts_event=10),
            order_event("OrderDenied", "O-2", reason="capture_gap", ts_event=11),
            filled("O-3", trade_id="T-9"),
        ],
    )
    stream.close()
    events = project_c1(_read(tmp_path)).lifecycle_events
    by_client = {e.client_order_id: e for e in events}
    assert by_client["O-1"].event == "SUBMITTED" and by_client["O-1"].decision_id == "d1"
    assert by_client["O-2"].event == "DENIED" and by_client["O-2"].reason == "capture_gap"
    fill = by_client["O-3"]
    assert (fill.event, fill.trade_id, fill.qty, fill.px, fill.fee) == (
        "FILLED",
        "T-9",
        "1.00",
        "0.15",
        "0.01",
    )
    assert fill.venue_order_id_sha256 == _sha("V-1")


def _no_leg_opened() -> PositionOpened:
    no_id = NO_INSTRUMENT
    recorded = RECORDED_ORDER_FILLED.replace(
        "tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US", no_id
    ).replace("last_qty=1.00", "last_qty=2.00")
    fill = _filled_from_recorded(recorded)
    position = Position(_instrument(InstrumentId.from_str(no_id)), fill)
    return PositionOpened.create(position, fill, UUID4(), fill.ts_event)


def test_position_mark_projection_applies_no_leg_sign(tmp_path: Path) -> None:
    """A NO holding counts as short YES (L-44): long 2 NO is ``net_qty`` -2; long 1 YES is +1.

    MUTATION (red): dropping the leg sign leaves the NO leg at +2.
    """
    life = _recorded_lifecycle()
    stream = open_stream(tmp_path)
    write_all(stream, [life.opened, _no_leg_opened()])
    stream.close()
    marks = {m.instrument_id: m for m in project_c1(_read(tmp_path)).position_marks}
    yes = marks[str(life.opened.instrument_id)]
    no = marks[NO_INSTRUMENT]
    assert (yes.leg, Decimal(yes.net_qty)) == ("yes", Decimal(1))
    assert (no.leg, Decimal(no.net_qty)) == ("no", Decimal(-2))
    assert yes.reconciliation_source == no.reconciliation_source == "node_belief"
    assert yes.source == "live"
    assert yes.mark_px == "0.15"


# -- frame reference resolution ----------------------------------------------------------------


class _Tape:
    def __init__(self, rows: dict[tuple[str, str, int], dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str, int]] = []

    def __call__(self, kind: str, instrument: str, ts_event: int) -> dict[str, Any] | None:
        self.calls.append((kind, instrument, ts_event))
        return self.rows.get((kind, instrument, ts_event))


def _stream_with_copy(tmp_path: Path) -> Any:
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1), frame_copy("d1", body={"ask": "0.15", "src": "copy"})])
    stream.close()
    return _read(tmp_path)


def test_frame_ref_resolution_order_copy_then_tape(tmp_path: Path) -> None:
    """The Take-path copy wins and the tape is not even consulted.

    MUTATION (red): trying the tape first returns the tape body and records a tape call.
    """
    got = _stream_with_copy(tmp_path)
    ref = f"depth10:{YES_INSTRUMENT}@501"
    tape = _Tape({("depth10", YES_INSTRUMENT, 501): {"ask": "0.15", "src": "tape"}})
    resolved = resolve_frame_ref(got, "d1", ref, tape=tape)
    assert resolved.source is FrameSource.COPY
    assert resolved.body == {"ask": "0.15", "src": "copy"}
    assert tape.calls == []


def test_frame_ref_falls_back_to_the_tape_then_unresolved(tmp_path: Path) -> None:
    got = _stream_with_copy(tmp_path)
    ref = f"depth10:{YES_INSTRUMENT}@999"
    tape = _Tape({("depth10", YES_INSTRUMENT, 999): {"ask": "0.20"}})
    via_tape = resolve_frame_ref(got, "d-other", ref, tape=tape)
    assert (via_tape.source, via_tape.body) == (FrameSource.TAPE, {"ask": "0.20"})
    assert tape.calls == [("depth10", YES_INSTRUMENT, 999)]
    assert resolve_frame_ref(got, "d-other", ref, tape=_Tape({})).source is FrameSource.UNRESOLVED
    assert resolve_frame_ref(got, "d-other", ref).source is FrameSource.UNRESOLVED  # no tape given


def test_frame_ref_with_no_frame_resolves_to_none_and_malformed_is_unresolved(
    tmp_path: Path,
) -> None:
    got = _stream_with_copy(tmp_path)
    assert resolve_frame_ref(got, "d1", "").source is FrameSource.NONE
    assert resolve_frame_ref(got, "d1", "garbage").source is FrameSource.UNRESOLVED


# -- fill to decision join ---------------------------------------------------------------------


def _join_fixture(tmp_path: Path) -> Any:
    take = limit_order(InstrumentId.from_str(YES_INSTRUMENT), "0.15", [f"{TAG}d1"])
    ghost = limit_order(
        InstrumentId.from_str(YES_INSTRUMENT), "0.16", [f"{TAG}d-missing"], ordinal=2
    )
    untagged = limit_order(InstrumentId.from_str(YES_INSTRUMENT), "0.17", None, ordinal=3)
    stream = open_stream(tmp_path)
    write_all(
        stream,
        [
            decision(1, eval_ns=5_000, eval_seq=7),
            take.init_event,
            ghost.init_event,
            untagged.init_event,
            filled(str(take.client_order_id), trade_id="T-take"),
            filled(str(ghost.client_order_id), trade_id="T-ghost"),
            filled(str(untagged.client_order_id), trade_id="T-untagged"),
            filled("O-never-linked", trade_id="T-none"),
        ],
    )
    stream.close()
    view = project_c1(_read(tmp_path))
    fills = [e for e in view.lifecycle_events if e.event == "FILLED"]
    return view, fills, take, untagged


def test_join_exposes_stored_eval_seq_never_recomputed(tmp_path: Path) -> None:
    """The decision carries its STORED ``eval_seq`` (7), not an ordinal recomputed from the stream.

    MUTATION (red): replaying an ``EvalSeqCounter`` over the decisions yields 0.
    """
    view, fills, take, _ = _join_fixture(tmp_path)
    joins = {j.fill.trade_id: j for j in join_fills_to_decisions(view, fills)}
    joined = joins["T-take"]
    assert joined.status is JoinStatus.JOINED
    assert joined.decision is not None and joined.decision.decision_id == "d1"
    assert (joined.decision.eval_ns, joined.decision.eval_seq) == (5_000, 7)
    assert joined.link is not None and joined.link.client_order_id == str(take.client_order_id)


def test_join_classifies_every_non_joined_fill(tmp_path: Path) -> None:
    view, fills, _, _ = _join_fixture(tmp_path)
    joins = {j.fill.trade_id: j for j in join_fills_to_decisions(view, fills)}
    assert joins["T-ghost"].status is JoinStatus.NO_DECISION
    assert joins["T-untagged"].status is JoinStatus.UNTAGGED_ORDER
    assert joins["T-none"].status is JoinStatus.NO_LINK
    assert all(j.decision is None for k, j in joins.items() if k != "T-take")


def test_join_flags_conflicting_links_for_one_client_order_id(tmp_path: Path) -> None:
    first = limit_order(InstrumentId.from_str(YES_INSTRUMENT), "0.15", [f"{TAG}d1"])
    second = limit_order(InstrumentId.from_str(YES_INSTRUMENT), "0.15", [f"{TAG}d2"])
    assert first.client_order_id == second.client_order_id  # same factory clock and counter
    stream = open_stream(tmp_path)
    write_all(
        stream,
        [
            decision(1),
            decision(2),
            first.init_event,
            second.init_event,
            filled(str(first.client_order_id), trade_id="T-c"),
        ],
    )
    stream.close()
    view = project_c1(_read(tmp_path))
    fills = [e for e in view.lifecycle_events if e.event == "FILLED"]
    (joined,) = join_fills_to_decisions(view, fills)
    assert joined.status is JoinStatus.LINK_CONFLICT


def test_reader_module_exports_are_pinned() -> None:
    assert {
        "CaptureStream",
        "C1View",
        "read_capture_stream",
        "project_c1",
        "join_fills_to_decisions",
        "resolve_frame_ref",
        "recompute_intent_fingerprint",
    } <= set(capture_reader.__all__)


# -- malformed rows and entries fail loudly ----------------------------------------------------


def _initialized_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "client_order_id": "O-1",
        "instrument_id": YES_INSTRUMENT,
        "order_side": "BUY",
        "time_in_force": "IOC",
        "quantity": "1.00",
        "options": b'{"price":"0.15"}',
        "tags": b"null",
        "ts_init": 5,
    }
    row.update(overrides)
    return row


def _project_row(row: dict[str, Any]) -> Any:
    stream = capture_reader.CaptureStream(instance_id="i", source="live", order_initialized=(row,))
    return project_c1(stream)


@pytest.mark.parametrize(
    "overrides",
    [
        {"order_side": "SIDEWAYS"},
        {"order_side": ""},
        {"order_side": None},
        {"time_in_force": "FOREVER"},
        {"tags": b"{not json"},
        {"tags": b'{"a": 1}'},
        {"tags": b"[1, 2]"},
        {"options": b"{not json"},
    ],
)
# The unknown-name rows are why the reader checks the member set first: native ``*_from_str``
# PANICS the whole interpreter (a Rust abort) on an unknown name instead of raising.
def test_malformed_order_rows_raise_a_projection_error(overrides: dict[str, Any]) -> None:
    with pytest.raises(capture_reader.CaptureProjectionError):
        _project_row(_initialized_row(**overrides))


def test_an_order_without_a_price_option_projects_an_empty_px() -> None:
    (link,) = _project_row(_initialized_row(options=b"{}")).order_links
    assert link.px == ""


def test_a_non_regular_entry_is_refused(tmp_path: Path) -> None:
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1)])
    stream.close()
    os.mkfifo(boot_dir(tmp_path) / "custom_decision_record_5.feather")
    with pytest.raises(SingleReadRefused) as caught:
        _read(tmp_path)
    assert caught.value.reason is SingleReadReason.NOT_REGULAR


def test_an_empty_file_is_not_a_torn_tail_and_yields_no_rows(tmp_path: Path) -> None:
    stream = open_stream(tmp_path)
    write_all(stream, [decision(1)])
    stream.close()
    (boot_dir(tmp_path) / "custom_frame_copy_5.feather").write_bytes(b"")
    got = _read(tmp_path)
    assert got.frame_copies == () and got.torn_tails == ()
