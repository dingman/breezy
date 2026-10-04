"""AUT-1 WP2: ``FqCaptureAdapter`` and the FQ plug-in entry (plan r12 sections 3.3, 3.5; r8 3.4).

Records are built from a Take or refusal plus a ``CaptureContext`` and published through a real
``CapturePublisher``. ``RecordingStream`` keeps ONE ordered event list, so the Take-path order
(FrameCopy, then DecisionRecord) is observed. One test publishes through the real
``CaptureStreamWriter`` and reads the Arrow rows back (L-42). Each test names its mutation.
"""

import ast
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from nautilus_trader.common.component import TestClock

from breezy.persistence.autonomy.capture_ids import compute_decision_id
from breezy.persistence.autonomy.capture_publish import CapturePublisher
from breezy.persistence.autonomy.capture_records import (
    DECISION_SCHEMA,
    FRAME_COPY_SCHEMA,
    DecisionRecord,
    FrameCopy,
)
from breezy.persistence.autonomy.capture_stream import CaptureStreamWriter
from breezy.persistence.autonomy.plugin import PluginRefused, is_complete
from breezy.persistence.exit_tags import DECISION_ID_TAG_PREFIX
from breezy.strategy.autonomy.node_plugins import NODE_PLUGINS
from breezy.strategy.forecast_quantile_ladder.capture_adapter import (
    CaptureContext,
    FqCaptureAdapter,
)
from breezy.strategy.forecast_quantile_ladder.decision import (
    NotDPlus1,
    NotExecutable,
    Refuse,
    Take,
)
from breezy.strategy.forecast_quantile_ladder.plugin import (
    FQ_COMPOSITION_KIND,
    FqNodePlugin,
    build_fq_node_plugin,
)
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from tests.support.capture_guard_fakes import (
    ARTEFACT,
    FAMILY,
    MANIFEST,
    NOW_NS,
    YES_ID,
    RecordingStream,
    build_depth,
    build_quote,
    identity,
)
from tests.unit.aut1_premises_support import _clock_at, _read_rows

DAY = date(2026, 10, 5)
FRAME_TS = NOW_NS - 3_000_000_000
NO_ID = "lax-80-81-no.POLYMARKET_US"


def _take(**overrides: Any) -> Take:
    fields: dict[str, Any] = {
        "instrument_id": str(YES_ID),
        "station": "LAX",
        "climate_day": DAY,
        "side": "yes",
        "rung_id": "i1",
        "qty": 1,
        "ev_net": 0.1,
        "p_hat": 0.2,
        "p_lower": 0.17,
        "p_upper": 0.23,
    }
    fields.update(overrides)
    return Take(**fields)


def _vector() -> ForecastQuantileVector:
    return ForecastQuantileVector(
        q10=1.0,
        q25=2.0,
        q50=3.0,
        q75=4.0,
        q90=5.0,
        mean=3.0,
        sd=1.0,
        available_at_ns=NOW_NS - 7_000_000_000,
        cycle_runtime_ns=NOW_NS - 9_000_000_000,
        climate_day=DAY,
        model_version="v4.2",
    )


def _ctx(trigger: str = "depth", **overrides: Any) -> CaptureContext:
    fields: dict[str, Any] = {
        "eval_ns": FRAME_TS,
        "eval_seq": 0,
        "wall_ns": NOW_NS,
        "trigger": trigger,
        "depth": build_depth(ts_event=FRAME_TS) if trigger == "depth" else None,
        "quote": build_quote(ts_event=FRAME_TS) if trigger == "quote_tick" else None,
        "vector": _vector(),
        "ask_px": Decimal("0.15"),
        "station": "LAX",
        "climate_day": DAY,
        "rung_id": "i1",
        "side": "yes",
        "instrument_id": str(YES_ID),
    }
    fields.update(overrides)
    return CaptureContext(**fields)


@dataclass
class Rig:
    adapter: FqCaptureAdapter
    stream: RecordingStream
    taken: list[Any]


def _rig(**adapter_overrides: Any) -> Rig:
    stream = RecordingStream()
    publisher = CapturePublisher(stream, family_id=FAMILY)
    taken: list[Any] = []
    kwargs: dict[str, Any] = {
        "publisher": publisher,
        "identity": identity(),
        "recalibration": "none",
        "on_take": taken.append,
    }
    kwargs.update(adapter_overrides)
    return Rig(FqCaptureAdapter(**kwargs), stream, taken)


# -- the pure field map -------------------------------------------------------------------------


def test_decision_record_field_map_take() -> None:
    adapter = _rig().adapter
    take = _take()
    record = adapter.decision_record(take, _ctx())

    expected_id = compute_decision_id(
        FAMILY, MANIFEST, ARTEFACT, "LAX", "2026-10-05", "i1", "yes", FRAME_TS, 0
    )
    assert record.decision_id == expected_id
    assert (record.kind, record.reason, record.schema) == ("Take", "take", DECISION_SCHEMA)
    assert (record.family_id, record.node_boot_id, record.registry_seq) == (FAMILY, "boot-1", 7)
    assert (record.build_sha, record.drill, record.source) == ("c" * 40, False, "live")
    assert (record.station, record.climate_day, record.rung_id, record.side) == (
        "LAX",
        "2026-10-05",
        "i1",
        "yes",
    )
    assert record.instrument == str(YES_ID)
    assert record.ask_px == "0.15"
    assert (record.eval_ns, record.eval_seq, record.wall_ns) == (FRAME_TS, 0, NOW_NS)
    assert (cast(Any, record).ts_event, cast(Any, record).ts_init) == (FRAME_TS, NOW_NS)
    assert (record.p_hat, record.p_lower, record.p_upper, record.ev_net) == (
        "0.2",
        "0.17",
        "0.23",
        "0.1",
    )
    assert (record.artefact_sha256, record.manifest_sha256) == (ARTEFACT, MANIFEST)
    assert (record.frame_kind, record.frame_ts_event) == ("depth10", FRAME_TS)
    assert record.forecast_station == "LAX"
    assert record.forecast_cycle_ns == NOW_NS - 9_000_000_000
    assert record.forecast_available_at_ns == NOW_NS - 7_000_000_000


@pytest.mark.parametrize(
    ("decision", "kind", "reason"),
    [
        (Refuse(reason="below_margin"), "Refuse", "below_margin"),
        (NotExecutable(), "NotExecutable", "outside_permit_window"),
        (NotDPlus1(), "NotDPlus1", "not_d_plus_1"),
    ],
)
def test_decision_record_field_map_refusals_null_probabilities(
    decision: Any, kind: str, reason: str
) -> None:
    record = _rig().adapter.decision_record(decision, _ctx())
    assert (record.kind, record.reason) == (kind, reason)
    assert (record.p_hat, record.p_hat_raw, record.p_lower, record.p_upper) == ("",) * 4
    assert (record.ev_net, record.margin) == ("", "")
    assert record.ask_px == "0.15"
    assert record.station == "LAX" and record.rung_id == "i1" and record.side == "yes"
    assert (record.frame_kind, record.frame_ts_event) == ("depth10", FRAME_TS)


@dataclass(frozen=True, slots=True, kw_only=True)
class _RefuseWithInputs(Refuse):
    """What WP7's additive ``Refuse`` fields look like: keyword-only, ``None`` by default."""

    p_hat: float | None = None
    p_lower: float | None = None
    p_upper: float | None = None
    ev_net: float | None = None
    margin: float | None = None


def test_refusal_inputs_are_carried_when_the_decision_has_them() -> None:
    decision = _RefuseWithInputs(
        reason="below_margin", p_hat=0.2, p_lower=0.17, p_upper=0.23, ev_net=0.01, margin=0.02
    )
    record = _rig().adapter.decision_record(decision, _ctx())
    assert record.kind == "Refuse"
    assert (record.p_hat, record.p_hat_raw, record.p_lower, record.p_upper) == (
        "0.2",
        "0.2",
        "0.17",
        "0.23",
    )
    assert (record.ev_net, record.margin) == ("0.01", "0.02")


def test_p_hat_raw_equals_p_hat_only_while_recalibration_none() -> None:
    """MUTATION: dropping the construction assert lets a recalibrated artefact write a raw
    probability that is not the raw one."""
    record = _rig().adapter.decision_record(_take(), _ctx())
    assert record.p_hat_raw == record.p_hat == "0.2"
    with pytest.raises(ValueError, match="recalibration"):
        _rig(recalibration="isotonic")


def test_no_vector_means_null_forecast_reference() -> None:
    record = _rig().adapter.decision_record(
        Refuse(reason="forecast_unavailable"), _ctx(vector=None)
    )
    assert (record.forecast_station, record.forecast_cycle_ns) == ("", 0)
    assert record.forecast_available_at_ns == 0


def test_no_leg_take_records_side_no() -> None:
    take = _take(side="no", instrument_id=NO_ID)
    record = _rig().adapter.decision_record(take, _ctx(side="no", instrument_id=NO_ID))
    assert (record.side, record.instrument) == ("no", NO_ID)
    expected = compute_decision_id(
        FAMILY, MANIFEST, ARTEFACT, "LAX", "2026-10-05", "i1", "no", FRAME_TS, 0
    )
    assert record.decision_id == expected


def test_order_tags_single_decision_tag() -> None:
    assert _rig().adapter.order_tags("f" * 32) == (f"{DECISION_ID_TAG_PREFIX}{'f' * 32}",)


# -- quote-triggered decisions (D2, U8) ---------------------------------------------------------


def test_quote_triggered_take_stores_quote_payload_and_ref() -> None:
    adapter = _rig().adapter
    ctx = _ctx("quote_tick")
    record = adapter.decision_record(_take(), ctx)
    copy = adapter.frame_copy(record, ctx)
    assert (record.frame_kind, record.frame_ts_event) == ("quote", FRAME_TS)
    assert copy.frame_kind == "quote" and copy.schema == FRAME_COPY_SCHEMA
    assert copy.frame_body == {"ask": "0.15", "bid": "0.14", "ts_event": FRAME_TS}
    assert (cast(Any, copy).ts_event, copy.frame_ts_event) == (FRAME_TS, FRAME_TS)


def test_quote_triggered_record_has_null_depth_ref() -> None:
    """A quote trigger cites the QUOTE even when an older depth is in hand.

    MUTATION: citing the depth for a quote-triggered record fails the kind and ts checks."""
    ctx = _ctx("quote_tick", depth=build_depth(ts_event=FRAME_TS - 5))
    record = _rig().adapter.decision_record(_take(), ctx)
    assert (record.frame_kind, record.frame_ts_event) == ("quote", FRAME_TS)


def test_quote_take_without_prior_depth_is_not_capture_gap() -> None:
    rig = _rig()
    decision_id = rig.adapter.capture(_take(), _ctx("quote_tick", depth=None))
    assert decision_id is not None
    assert [type(o).__name__ for o in rig.stream.written] == ["FrameCopy", "DecisionRecord"]


def test_depth_frame_body_keeps_populated_levels_and_drops_ts_init() -> None:
    adapter = _rig().adapter
    ctx = _ctx(depth=build_depth(ts_event=FRAME_TS))
    copy = adapter.frame_copy(adapter.decision_record(_take(), ctx), ctx)
    assert copy.frame_body == {
        "ts_event": FRAME_TS,
        "bids": [["0.14", "10"]],
        "asks": [["0.15", "20"], ["0.16", "5"]],
    }


def test_context_must_carry_the_frame_its_trigger_names() -> None:
    with pytest.raises(ValueError, match="depth"):
        _ctx("depth", depth=None)
    with pytest.raises(ValueError, match="quote"):
        _ctx("quote_tick", quote=None)
    with pytest.raises(ValueError, match="trigger"):
        _ctx("bogus", depth=build_depth(ts_event=1))


# -- publishing: the Take path -----------------------------------------------------------------


def test_take_publishes_frame_copy_before_decision_record() -> None:
    """A reader that sees the Take sees its copy: the copy is published first (section 3.3.2).

    MUTATION: writing the record before the copy fails the order assertion."""
    rig = _rig()
    decision_id = rig.adapter.capture(_take(), _ctx())

    assert decision_id is not None
    assert [type(o).__name__ for o in rig.stream.written] == ["FrameCopy", "DecisionRecord"]
    copy, record = rig.stream.written
    assert copy.decision_id == record.decision_id == decision_id
    assert rig.taken == [record]


def test_a_failed_frame_copy_means_no_decision_record_and_no_id() -> None:
    """MUTATION: publishing the Take's record after a failed copy cites a frame nobody holds."""
    rig = _rig()
    rig.stream.write_ok = False
    assert rig.adapter.capture(_take(), _ctx()) is None
    assert rig.stream.written == [] and rig.taken == []


def test_a_failed_decision_record_write_returns_no_id() -> None:
    rig = _rig()
    real_write = rig.stream.write

    def write(obj: object) -> bool:
        return False if isinstance(obj, DecisionRecord) else real_write(obj)

    rig.stream.write = write  # type: ignore[method-assign]
    assert rig.adapter.capture(_take(), _ctx()) is None
    assert rig.taken == []


@pytest.mark.parametrize("decision", [Refuse(reason="below_margin"), NotExecutable(), NotDPlus1()])
def test_refusal_never_publishes_frame_copy(decision: Any) -> None:
    """MUTATION: copying the frame for a refusal turns every refusal into a by-value citation."""
    rig = _rig()
    assert rig.adapter.capture(decision, _ctx()) is not None
    assert rig.stream.written_of(FrameCopy) == []
    assert len(rig.stream.written_of(DecisionRecord)) == 1
    assert rig.taken == []


def test_repeated_identical_refusals_are_written_once_but_every_take_is() -> None:
    rig = _rig()
    for seq in range(3):
        rig.adapter.capture(Refuse(reason="below_margin"), _ctx(eval_seq=seq))
    assert len(rig.stream.written_of(DecisionRecord)) == 1
    for seq in range(3):
        rig.adapter.capture(_take(), _ctx(eval_seq=10 + seq))
    assert len(rig.stream.written_of(DecisionRecord)) == 4
    assert len(rig.stream.written_of(FrameCopy)) == 3


def test_an_unadmitted_refusal_still_returns_its_id() -> None:
    rig = _rig()
    first = rig.adapter.capture(Refuse(reason="below_margin"), _ctx(eval_seq=0))
    second = rig.adapter.capture(Refuse(reason="below_margin"), _ctx(eval_seq=1))
    assert first is not None and second is not None and first != second


def test_a_record_build_failure_never_raises() -> None:
    rig = _rig()
    assert rig.adapter.capture(object(), _ctx()) is None  # type: ignore[arg-type]
    assert rig.stream.written == []


def test_an_on_take_callback_that_raises_is_a_capture_failure_not_an_exception() -> None:
    def boom(record: object) -> None:
        raise RuntimeError("registry full")

    rig = _rig(on_take=boom)
    assert rig.adapter.capture(_take(), _ctx()) is None


# -- follow-up records (TrySubmit / EntryVeto) --------------------------------------------------


def test_try_submit_copies_the_takes_clock_and_publishes_no_frame_copy() -> None:
    rig = _rig()
    rig.adapter.capture(_take(), _ctx(eval_seq=2))
    [take_record] = rig.taken
    copies_before = len(rig.stream.written_of(FrameCopy))

    ok = rig.adapter.follow_up(
        take_record, kind="TrySubmit", reason="submitted", wall_ns=NOW_NS + 9
    )

    assert ok is True
    follow = rig.stream.written_of(DecisionRecord)[-1]
    assert (follow.kind, follow.reason, follow.decision_id) == (
        "TrySubmit",
        "submitted",
        take_record.decision_id,
    )
    assert (follow.eval_ns, follow.eval_seq, follow.wall_ns) == (FRAME_TS, 2, NOW_NS + 9)
    assert follow.p_hat == "" and follow.ev_net == ""
    assert len(rig.stream.written_of(FrameCopy)) == copies_before


def test_a_repeated_entry_veto_is_on_change_per_key() -> None:
    rig = _rig()
    rig.adapter.capture(_take(), _ctx())
    [take_record] = rig.taken
    for _ in range(3):
        rig.adapter.follow_up(take_record, kind="EntryVeto", reason="family_halt", wall_ns=NOW_NS)
    vetoes = [r for r in rig.stream.written_of(DecisionRecord) if r.kind == "EntryVeto"]
    assert len(vetoes) == 1


# -- the real writer (L-42) ---------------------------------------------------------------------


def test_published_take_round_trips_through_the_real_stream_writer(tmp_path: Path) -> None:
    stream = CaptureStreamWriter(root=tmp_path, instance_id="inst-1")
    publisher = CapturePublisher(stream, family_id=FAMILY)
    adapter = FqCaptureAdapter(
        publisher=publisher, identity=identity(), recalibration="none", on_take=lambda _r: None
    )
    clock: TestClock = _clock_at("2026-10-05T10:00:00.000000000Z")
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    assert stream.open(TestComponentStubs.cache(), clock)
    try:
        assert adapter.capture(_take(), _ctx()) is not None
        assert publisher.flush_for_submit() is True
    finally:
        stream.close()
    [decision] = _read_rows(stream.stream_dir, "custom_decision_record")
    [copy] = _read_rows(stream.stream_dir, "custom_frame_copy")
    assert decision["kind"] == "Take" and decision["decision_id"] == copy["decision_id"]
    assert decision["ts_event"] == FRAME_TS
    assert json.loads(copy["frame_body"])["asks"] == [["0.15", "20"], ["0.16", "5"]]


# -- the plug-in entry --------------------------------------------------------------------------


def test_fq_plugin_is_a_full_capture_plugin_that_is_not_yet_registered() -> None:
    adapter = _rig().adapter
    plugin = build_fq_node_plugin(adapter)
    assert FQ_COMPOSITION_KIND == "forecast_quantile_ladder"
    assert plugin.refusing is False and is_complete(plugin) and is_complete(FqNodePlugin)
    assert plugin.capture_adapter is adapter
    assert plugin.order_tags("e" * 32) == adapter.order_tags("e" * 32)
    record = plugin.decision_record(_take(), _ctx())
    assert record.kind == "Take"
    # WP2 is a library: the live node's registry still refuses every kind.
    assert not is_complete(NODE_PLUGINS[FQ_COMPOSITION_KIND])


_MEMBER_ARITY = {"label": 3, "offline": 2, "forward_shadow": 3, "live": 1, "refit": 1}


@pytest.mark.parametrize("member", sorted(_MEMBER_ARITY))
def test_fq_plugin_refuses_the_members_other_plans_own(member: str) -> None:
    plugin = build_fq_node_plugin(_rig().adapter)
    with pytest.raises(PluginRefused):
        getattr(plugin, member)(*range(_MEMBER_ARITY[member]))
    with pytest.raises(PluginRefused):
        _ = plugin.detectors


def test_wp2_modules_do_not_import_the_live_strategy_and_the_guard_is_family_agnostic() -> None:
    """WP2 is library-only: no new module imports FQ's live ``strategy`` module, and the guard
    imports nothing from the FQ package at all.

    MUTATION: an ``import ...forecast_quantile_ladder.strategy`` in any of them fails this."""
    root = Path(__file__).resolve().parents[3] / "src/breezy/strategy"
    live = "breezy.strategy.forecast_quantile_ladder.strategy"
    fq_package = "breezy.strategy.forecast_quantile_ladder"
    files = {
        root / "forecast_quantile_ladder/capture_adapter.py": False,
        root / "forecast_quantile_ladder/plugin.py": False,
        root / "autonomy_capture/guarded_strategy.py": True,
    }
    for path, family_agnostic in files.items():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            assert live not in names, (path.name, names)
            if family_agnostic:
                assert not any(n.startswith(fq_package) for n in names), (path.name, names)
