"""RED/GREEN coverage for ``breezy.runtime.liveness_probe_cli`` (SP-6 A12,
row 18)."""

from __future__ import annotations

import datetime as dt
import io
from collections.abc import Callable

import pytest

from breezy.runtime import liveness_probe_cli
from breezy.runtime.health import AlertPayload
from breezy.runtime.process_probe import PidProbe, ProbeOutcome
from breezy.runtime.trade_supervisor_core import NODE_ARGV_ANCHOR, SUPERVISOR_ARGV_ANCHOR

_ALIVE_EXPECTED = dt.datetime(2026, 9, 12, 2, 0, tzinfo=dt.UTC)
_NOT_ALIVE_EXPECTED = dt.datetime(2026, 9, 12, 16, 41, tzinfo=dt.UTC)

_FOUND = PidProbe(ProbeOutcome.FOUND, 12345)
_ABSENT = PidProbe(ProbeOutcome.ABSENT, None)
_FAILED = PidProbe(ProbeOutcome.FAILED, None)


class _FakeSink:
    def __init__(self) -> None:
        self.received: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.received.append(payload)


def _make_probe(
    sequences: dict[str, list[PidProbe]],
) -> tuple[Callable[[str], PidProbe], dict[str, int]]:
    calls: dict[str, int] = {}

    def _probe(anchor: str) -> PidProbe:
        idx = calls.get(anchor, 0)
        calls[anchor] = idx + 1
        sequence = sequences[anchor]
        return sequence[min(idx, len(sequence) - 1)]

    return _probe, calls


def _no_sleep(_seconds: float) -> None:
    return None


def test_silent_when_both_are_present() -> None:
    probe, calls = _make_probe(
        {SUPERVISOR_ARGV_ANCHOR: [_FOUND], NODE_ARGV_ANCHOR: [_FOUND]}
    )
    sink = _FakeSink()

    exit_code = liveness_probe_cli.run(
        sink=sink, now=_ALIVE_EXPECTED, probe=probe, sleep=_no_sleep, stdout=io.StringIO()
    )

    assert exit_code == liveness_probe_cli.EXIT_OK
    assert sink.received == []
    assert calls[SUPERVISOR_ARGV_ANCHOR] == 1  # exactly one probe -- FOUND ends it
    assert calls[NODE_ARGV_ANCHOR] == 1


def test_reports_absent_when_neither_supervisor_nor_node_is_present() -> None:
    probe, _ = _make_probe(
        {SUPERVISOR_ARGV_ANCHOR: [_ABSENT, _ABSENT], NODE_ARGV_ANCHOR: [_ABSENT, _ABSENT]}
    )
    sink = _FakeSink()

    exit_code = liveness_probe_cli.run(
        sink=sink, now=_ALIVE_EXPECTED, probe=probe, sleep=_no_sleep, stdout=io.StringIO()
    )

    assert exit_code == liveness_probe_cli.EXIT_ABSENCE_REPORTED
    events = {p.event for p in sink.received}
    assert events == {"SUPERVISOR_ABSENT", "TRADE_NODE_ABSENT"}
    assert all(p.severity == "CRITICAL" for p in sink.received)


def test_a_probe_failure_is_reported_as_probe_failed_not_absence() -> None:
    probe, _ = _make_probe(
        {SUPERVISOR_ARGV_ANCHOR: [_FAILED, _FAILED], NODE_ARGV_ANCHOR: [_FOUND]}
    )
    sink = _FakeSink()

    exit_code = liveness_probe_cli.run(
        sink=sink, now=_ALIVE_EXPECTED, probe=probe, sleep=_no_sleep, stdout=io.StringIO()
    )

    assert exit_code == liveness_probe_cli.EXIT_OK
    assert len(sink.received) == 1
    assert sink.received[0].event == "LIVENESS_PROBE_FAILED"
    assert sink.received[0].severity == "WARN"


def test_node_absence_at_0200z_alerts(never_signals: None) -> None:
    probe, _ = _make_probe(
        {SUPERVISOR_ARGV_ANCHOR: [_FOUND], NODE_ARGV_ANCHOR: [_ABSENT, _ABSENT]}
    )
    sink = _FakeSink()

    exit_code = liveness_probe_cli.run(
        sink=sink, now=_ALIVE_EXPECTED, probe=probe, sleep=_no_sleep, stdout=io.StringIO()
    )

    assert exit_code == liveness_probe_cli.EXIT_ABSENCE_REPORTED
    assert len(sink.received) == 1
    assert sink.received[0].event == "TRADE_NODE_ABSENT"
    assert sink.received[0].severity == "CRITICAL"


def test_node_absence_at_1641z_is_silent() -> None:
    probe, _ = _make_probe(
        {SUPERVISOR_ARGV_ANCHOR: [_FOUND], NODE_ARGV_ANCHOR: [_ABSENT, _ABSENT]}
    )
    sink = _FakeSink()

    exit_code = liveness_probe_cli.run(
        sink=sink, now=_NOT_ALIVE_EXPECTED, probe=probe, sleep=_no_sleep, stdout=io.StringIO()
    )

    assert exit_code == liveness_probe_cli.EXIT_OK
    assert sink.received == []


def test_supervisor_absence_alerts_at_any_hour(never_signals: None) -> None:
    probe, _ = _make_probe(
        {SUPERVISOR_ARGV_ANCHOR: [_ABSENT, _ABSENT], NODE_ARGV_ANCHOR: [_FOUND]}
    )
    sink = _FakeSink()

    exit_code = liveness_probe_cli.run(
        sink=sink, now=_NOT_ALIVE_EXPECTED, probe=probe, sleep=_no_sleep, stdout=io.StringIO()
    )

    assert exit_code == liveness_probe_cli.EXIT_ABSENCE_REPORTED
    assert len(sink.received) == 1
    assert sink.received[0].event == "SUPERVISOR_ABSENT"


def test_never_signals_any_process(
    monkeypatch: pytest.MonkeyPatch, never_signals: None
) -> None:
    """CX-N2: (a) the injected probe port is the ONLY process lookup
    reached -- a bomb over the REAL (forking) probe fails the test if it
    is ever called; (b) a token scan confirms no signal-sending call
    anywhere in the module source."""
    import breezy.runtime.process_probe as process_probe_module

    def _bomb(*args: object, **kwargs: object) -> PidProbe:
        raise AssertionError("the real (forking) probe must never be reached")

    monkeypatch.setattr(process_probe_module, "probe_pid_by_argv", _bomb)

    probe, _ = _make_probe({SUPERVISOR_ARGV_ANCHOR: [_FOUND], NODE_ARGV_ANCHOR: [_FOUND]})
    sink = _FakeSink()

    exit_code = liveness_probe_cli.run(
        sink=sink, now=_ALIVE_EXPECTED, probe=probe, sleep=_no_sleep, stdout=io.StringIO()
    )
    assert exit_code == liveness_probe_cli.EXIT_OK

    import inspect

    source = inspect.getsource(liveness_probe_cli)
    for forbidden in ("os.kill", "signal.", ".terminate(", "pkill"):
        assert forbidden not in source


def test_detail_passes_assert_payload_detail_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_assert = liveness_probe_cli.assert_payload_detail_is_safe

    def _recording(detail: str) -> None:
        calls.append(detail)
        real_assert(detail)

    monkeypatch.setattr(liveness_probe_cli, "assert_payload_detail_is_safe", _recording)

    probe, _ = _make_probe(
        {SUPERVISOR_ARGV_ANCHOR: [_ABSENT, _ABSENT], NODE_ARGV_ANCHOR: [_FOUND]}
    )
    sink = _FakeSink()

    liveness_probe_cli.run(
        sink=sink, now=_ALIVE_EXPECTED, probe=probe, sleep=_no_sleep, stdout=io.StringIO()
    )

    assert "supervisor_absent" in calls


def test_never_raises_on_an_internal_error() -> None:
    def _raising_probe(_anchor: str) -> PidProbe:
        raise RuntimeError("boom")

    sink = _FakeSink()

    exit_code = liveness_probe_cli.run(
        sink=sink,
        now=_ALIVE_EXPECTED,
        probe=_raising_probe,
        sleep=_no_sleep,
        stdout=io.StringIO(),
    )  # must not raise

    assert exit_code == liveness_probe_cli.EXIT_INTERNAL_ERROR


