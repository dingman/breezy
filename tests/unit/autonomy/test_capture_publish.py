"""AUT-1 WP1 part A: ``CapturePublisher`` (plan r12 section 3.4.3; r8 H8 dedupe rule)."""

import ast
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import MessageBus
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.persistence.autonomy import capture_publish
from breezy.persistence.autonomy.capture_publish import (
    FAILURE_DEDUPE_S,
    CaptureHealth,
    CapturePublisher,
    StreamCounters,
)
from breezy.persistence.autonomy.capture_records import (
    HEARTBEAT_SCHEMA,
    DecisionRecord,
    FrameCopy,
    make_record,
)
from breezy.persistence.autonomy.capture_stream import CaptureStreamWriter
from tests.unit.aut1_premises_support import _clock_at, _read_rows

NS = 10**9
FAMILY = "forecast-quantile-ladder-lax"


class FakeStream:
    """Duck-typed stream: scriptable failures, drops and flush results."""

    def __init__(self) -> None:
        self.health = CaptureHealth()
        self.written: list[Any] = []
        self.raise_on_write: Exception | None = None
        self.write_ok = True
        self.write_cause = "write_dropped:custom_decision_record"
        self.flush_ok = True
        self.raise_on_flush: Exception | None = None
        self.pending_drops = 0
        self.flushes = 0

    def write(self, obj: Any) -> bool:
        if self.raise_on_write is not None:
            raise self.raise_on_write
        if not self.write_ok:
            self.health.mark_failed(self.write_cause)
            return False
        self.written.append(obj)
        return True

    def flush(self) -> bool:
        self.flushes += 1
        if self.raise_on_flush is not None:
            raise self.raise_on_flush
        return self.flush_ok

    def consume_drops_since_submit_flush(self) -> int:
        drops, self.pending_drops = self.pending_drops, 0
        return drops

    def counters(self) -> StreamCounters:
        return StreamCounters(written_by_type={}, write_failures=0, write_drops=0)


class Clock:
    def __init__(self) -> None:
        self.now = 1_000 * NS

    def __call__(self) -> int:
        return self.now


class Harness:
    def __init__(self, *, offer_result: bool = True) -> None:
        self.stream = FakeStream()
        self.clock = Clock()
        self.offers: list[tuple[str, str, str]] = []
        self.logs: list[str] = []
        self.offer_result = offer_result
        self.publisher = CapturePublisher(
            self.stream,
            family_id=FAMILY,
            alert_offer=self._offer,
            log_error=self.logs.append,
            now_ns=self.clock,
        )

    def _offer(self, event: str, severity: str, detail: str) -> bool:
        self.offers.append((event, severity, detail))
        return self.offer_result


def _record() -> DecisionRecord:
    return make_record(DecisionRecord, ts_event=1, ts_init=2, decision_id="d" * 32)


def test_write_exception_never_raises_and_sets_health_not_ok() -> None:
    """MUTATION: letting the stream's exception propagate raises out of ``write``."""
    h = Harness()
    h.stream.raise_on_write = RuntimeError("boom")
    assert h.publisher.write(_record()) is False
    assert h.stream.health.ok is False
    assert "RuntimeError" in h.stream.health.cause
    assert h.logs == [
        f"CAPTURE_PUBLISH_FAILED family={FAMILY} type=DecisionRecord cause=RuntimeError"
    ]
    assert [(e, s) for e, s, _ in h.offers] == [("CAPTURE_PUBLISH_FAILED", "CRITICAL")]


def test_a_false_from_the_stream_is_a_failure_with_its_own_cause() -> None:
    h = Harness()
    h.stream.write_ok = False
    assert h.publisher.write(_record()) is False
    assert h.stream.health.ok is False
    assert h.logs == [
        (
            f"CAPTURE_PUBLISH_FAILED family={FAMILY} type=DecisionRecord "
            "cause=write_dropped:custom_decision_record"
        )
    ]


def test_a_successful_write_returns_true_and_touches_nothing() -> None:
    h = Harness()
    assert h.publisher.write(_record()) is True
    assert h.stream.health.ok is True and h.offers == [] and h.logs == []
    assert len(h.stream.written) == 1


def test_publish_failure_offers_critical_deduped_per_cause_per_300s() -> None:
    """The first failure of a cause in a 300 s window offers; repeats only count; the window end
    logs the suppressed count; another cause has its own window.

    MUTATION: removing the dedupe offers on every failure (``len(offers) == 5`` not 3).
    """
    assert FAILURE_DEDUPE_S == 300
    h = Harness()
    h.stream.raise_on_write = RuntimeError("a")
    for _ in range(3):  # t = 1000, 1010, 1020
        h.publisher.write(_record())
        h.clock.now += 10 * NS
    assert len(h.offers) == 1
    h.stream.raise_on_write = ValueError("b")  # a different cause
    h.publisher.write(_record())
    assert [d for _, _, d in h.offers if "ValueError" in d] and len(h.offers) == 2
    h.stream.raise_on_write = RuntimeError("a")
    h.clock.now = 1_000 * NS + 299 * NS + 999_999_999  # still inside the first window
    h.publisher.write(_record())
    assert len(h.offers) == 2
    h.clock.now = 1_000 * NS + 300 * NS  # the window has ended: offer again, log the suppressed
    h.publisher.write(_record())
    assert len(h.offers) == 3
    suppressed = [line for line in h.logs if "SUPPRESSED" in line]
    assert suppressed == [
        f"CAPTURE_PUBLISH_FAILED_SUPPRESSED family={FAMILY} cause=RuntimeError count=3 window_s=300"
    ]
    # every failure still vetoed
    assert h.stream.health.ok is False


def test_an_undelivered_offer_is_counted_never_raised() -> None:
    h = Harness(offer_result=False)
    h.stream.raise_on_write = RuntimeError("a")
    assert h.publisher.write(_record()) is False
    assert h.publisher.alert_drops == 1

    def boom(*_a: str) -> bool:
        raise OSError("outbox down")

    h.publisher = CapturePublisher(
        h.stream, family_id=FAMILY, alert_offer=boom, log_error=h.logs.append, now_ns=h.clock
    )
    assert h.publisher.write(_record()) is False
    assert h.publisher.alert_drops == 1


def test_health_clears_only_on_heartbeat_flush_and_per_type_pass() -> None:
    """Positive control: all three of heartbeat written, flush True, per-type check passed.

    MUTATION: clearing on any two of the three turns six of the seven non-clearing rows red.
    """
    for heartbeat, flush, per_type in itertools.product((True, False), repeat=3):
        h = Harness()
        h.stream.health.mark_failed("write_dropped:x")
        cleared = h.publisher.positive_control(
            heartbeat_written=heartbeat, flush_ok=flush, per_type_passed=per_type
        )
        assert cleared is (heartbeat and flush and per_type), (heartbeat, flush, per_type)
        assert h.stream.health.ok is (heartbeat and flush and per_type)
        if h.stream.health.ok:
            assert h.stream.health.cause == ""
    healthy = Harness()
    assert healthy.publisher.positive_control(
        heartbeat_written=False, flush_ok=False, per_type_passed=False
    )  # an already-healthy publisher is untouched by a failed tick
    assert healthy.stream.health.ok is True


def test_flush_for_submit_failure_returns_false() -> None:
    h = Harness()
    h.stream.flush_ok = False
    assert h.publisher.flush_for_submit() is False
    h.stream.flush_ok = True
    h.stream.raise_on_flush = OSError("disk")
    assert h.publisher.flush_for_submit() is False  # an exception is a False, never a raise
    assert h.stream.health.ok is False
    assert h.stream.flushes == 2
    h.stream.raise_on_flush = None
    h.stream.health.clear()
    assert h.publisher.flush_for_submit() is True


def test_flush_for_submit_false_after_any_drop_since_previous_submit_flush() -> None:
    """A dropped record of any table since the previous submit flush refuses the Take once; the
    counter then resets. MUTATION: ignoring the drop counter returns True on the first call."""
    h = Harness()
    h.stream.pending_drops = 1
    assert h.publisher.flush_for_submit() is False
    assert h.stream.pending_drops == 0
    assert h.publisher.flush_for_submit() is True


def test_flush_for_submit_with_a_real_stream_sees_a_real_drop(tmp_path: Path) -> None:
    stream = CaptureStreamWriter(root=tmp_path, instance_id="inst-1")
    publisher = CapturePublisher(stream, family_id=FAMILY, now_ns=Clock())
    assert stream.open(_cache(), _clock_at("2026-10-04T10:00:00.000000000Z"))
    assert publisher.write(_record()) is True
    assert publisher.flush_for_submit() is True
    stream.native_writer._writers["custom_decision_record"] = _Raising()
    assert publisher.write(_record()) is False
    assert publisher.flush_for_submit() is False
    # the drop was consumed; the standing veto is the guard's separate ``health.ok`` check (step 4)
    assert publisher.flush_for_submit() is True
    assert publisher.health.ok is False
    stream.close()


def test_custom_records_never_cross_the_msgbus(tmp_path: Path) -> None:
    """R-A: the publisher calls the stream directly. A wildcard bus subscriber sees nothing, and
    neither module touches a bus publish API.

    MUTATION: adding ``msgbus.publish`` to the publisher delivers to the subscriber (red).
    """
    bus: MessageBus = TestComponentStubs.msgbus()
    seen: list[object] = []
    bus.subscribe(topic="*", handler=seen.append)
    stream = CaptureStreamWriter(root=tmp_path, instance_id="inst-1")
    publisher = CapturePublisher(stream, family_id=FAMILY, now_ns=Clock())
    assert stream.open(_cache(), _clock_at("2026-10-04T10:00:00.000000000Z"))
    assert publisher.write(_record())
    assert publisher.write(make_record(FrameCopy, ts_event=1, ts_init=2, decision_id="d" * 32))
    stream.close()
    assert seen == []
    for module in ("capture_publish", "capture_stream"):
        source = (Path(capture_publish.__file__).parent / f"{module}.py").read_text("utf-8")
        tree = ast.parse(source)
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not {"publish", "send", "msgbus"} & (attrs | names), module


def test_heartbeat_written_by_type_excludes_itself(tmp_path: Path) -> None:
    """GL1: the snapshot is taken immediately BEFORE the heartbeat's own write, so
    ``written_by_type["custom_capture_heartbeat"]`` counts only EARLIER heartbeats.

    MUTATION: snapshotting after the write makes the first heartbeat count itself (1, not absent).
    """
    stream = CaptureStreamWriter(root=tmp_path, instance_id="inst-1")
    publisher = CapturePublisher(stream, family_id=FAMILY, now_ns=Clock())
    assert stream.open(_cache(), _clock_at("2026-10-04T10:00:00.000000000Z"))
    publisher.write(_record())
    publisher.write(_record())
    assert publisher.write_heartbeat(node_boot_id="inst-1", final=False, now_ns=5 * NS)
    assert publisher.write_heartbeat(node_boot_id="inst-1", final=True, now_ns=6 * NS)
    stream.flush()
    rows = _read_rows(stream.stream_dir, "custom_capture_heartbeat")
    assert [r["seq"] for r in rows] == [1, 2]
    assert [r["final"] for r in rows] == [False, True]
    by_type = [json.loads(r["written_by_type"]) for r in rows]
    assert by_type[0] == {"custom_decision_record": 2}
    assert by_type[1] == {"custom_decision_record": 2, "custom_capture_heartbeat": 1}
    assert [r["records_written"] for r in rows] == [2, 3]
    assert {r["schema"] for r in rows} == {HEARTBEAT_SCHEMA}
    assert {r["node_boot_id"] for r in rows} == {"inst-1"}
    assert rows[0]["health_ok"] is True and rows[0]["health_cause"] == ""
    assert rows[0]["ts_event"] == 5 * NS
    stream.close()


def test_heartbeat_carries_failures_drops_and_health(tmp_path: Path) -> None:
    stream = CaptureStreamWriter(root=tmp_path, instance_id="inst-1")
    publisher = CapturePublisher(stream, family_id=FAMILY, now_ns=Clock())
    assert stream.open(_cache(), _clock_at("2026-10-04T10:00:00.000000000Z"))
    publisher.write(_record())
    stream.native_writer._writers["custom_decision_record"] = _Raising()
    assert publisher.write(_record()) is False
    assert publisher.write_heartbeat(node_boot_id="inst-1", final=False, now_ns=NS)
    stream.flush()
    [row] = _read_rows(stream.stream_dir, "custom_capture_heartbeat")
    assert row["write_drops"] == 1 and row["write_failures"] == 0
    assert row["health_ok"] is False
    assert row["health_cause"] == "write_dropped:custom_decision_record"
    stream.close()


def test_a_heartbeat_write_failure_returns_false_without_raising() -> None:
    h = Harness()
    h.stream.raise_on_write = RuntimeError("boom")
    assert h.publisher.write_heartbeat(node_boot_id="b", final=False, now_ns=1) is False
    assert h.stream.health.ok is False


class _Raising:
    def write_table(self, table: Any) -> None:
        raise OSError("premise: write_table failed")

    def close(self) -> None:
        return None


def _cache() -> Any:
    return TestComponentStubs.cache()


@pytest.mark.parametrize("bad", ["", "a b", "a/b"])
def test_publisher_requires_a_family_id(bad: str) -> None:
    with pytest.raises(ValueError):
        CapturePublisher(FakeStream(), family_id=bad)
