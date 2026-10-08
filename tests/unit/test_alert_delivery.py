"""AUT-6 WP1 delivery proof, records and the durable outbox (plan r15 §3.6).

RED until ``breezy.runtime.alert_delivery`` exists. These names are the plan's
WP1 list (l.1131–1140); the systemd names live in the contract module.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from breezy.analysis.capture_aut6_contract import DELIVERY_RECORD_NAME_RE, DELIVERY_SCHEMA
from breezy.persistence.autonomy.capture_alerts import CAPTURE_ALERT_SEVERITIES
from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_delivery import (
    ALERT_CLAIM_STALE_S,
    ALERT_OUTBOX_CRITICAL_RESERVED,
    ALERT_OUTBOX_MAX,
    PROOF_BEARING_EVENTS,
    AlertNotDeliveredError,
    AlertOutbox,
    DeliveryProof,
    DeliveryRecordWriter,
    JournalingWebhookAlertSink,
    deliver_with_proof,
    enqueue_alert,
    is_proof_bearing,
)
from breezy.runtime.check_alerts_cli import EXIT_DELIVERY_FAILED, main
from breezy.runtime.health import (
    ALERT_WEBHOOK_URL_ENV_VAR,
    LoggingAlertSink,
    TeeAlertSink,
    WebhookAlertSink,
    emit_alert,
    resolve_alert_sink,
)

_URL = "https://alerts.example.test/hook"
_ATTEMPT_KINDS = ("alert", "retry", "canary", "drain")
_RECORD_KEYS = frozenset(
    {
        "event",
        "ts_ns",
        "delivered",
        "status_class",
        "severity",
        "attempt_kind",
        "drill",
        "schema",
        "site",
        "outbox_entry",
    }
)


@pytest.fixture(autouse=True)
def alerts_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("breezy.runtime.alert_delivery.default_alerts_root", lambda: tmp_path)
    return tmp_path


def _payload(event: str = "CAPTURE_PUBLISH_FAILED", severity: str = "CRITICAL") -> AlertPayload:
    return AlertPayload(severity=severity, event=event, site="unit_test", detail="closed")


def _client(status: int = 200, exc: BaseException | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        if exc is not None:
            raise exc
        return httpx.Response(status)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _tee(client: httpx.Client) -> TeeAlertSink:
    return TeeAlertSink(LoggingAlertSink(), WebhookAlertSink(_URL, client=client))


def _proof(
    sink: TeeAlertSink,
    payload: AlertPayload,
    root: Path,
    *,
    writer: str = "health",
    attempt_kind: str = "alert",
    outbox: AlertOutbox | None = None,
) -> DeliveryProof:
    return deliver_with_proof(
        sink,
        payload,
        writer=writer,
        records=DeliveryRecordWriter(root),
        attempt_kind=attempt_kind,  # type: ignore[arg-type]
        outbox=outbox if outbox is not None else AlertOutbox(root),
    )


def _at(ns: int) -> Callable[[], int]:
    return lambda: ns


def _records(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.json")
        if path.parent.name != "outbox" and "claimed" not in path.parts
    )


def _one_record(root: Path) -> tuple[Path, dict[str, object]]:
    found = [
        path
        for path in _records(root)
        if path.name.endswith("_d.json") or path.name.endswith("_f.json")
    ]
    assert len(found) == 1, [path.name for path in found]
    body = json.loads(found[0].read_text(encoding="utf-8"))
    assert isinstance(body, dict)
    return found[0], body


class _RecordingOs:
    """Proxy os that records utime, rename, open and fsync in call order."""

    def __init__(self, real: object) -> None:
        self._real = real
        self.ops: list[tuple[object, ...]] = []

    def utime(self, path: object, times: object = None, **kwargs: object) -> None:
        self.ops.append(("utime", Path(str(path))))
        if times is None:
            self._real.utime(path, **kwargs)  # type: ignore[attr-defined]
        else:
            self._real.utime(path, times, **kwargs)  # type: ignore[attr-defined]

    def rename(self, src: object, dst: object) -> None:
        self.ops.append(("rename", Path(str(src)), Path(str(dst))))
        self._real.rename(src, dst)  # type: ignore[attr-defined]

    def open(self, path: object, flags: int, mode: int = 0o777, **kwargs: object) -> int:
        self.ops.append(("open", Path(str(path)), flags))
        return int(self._real.open(path, flags, mode, **kwargs))  # type: ignore[attr-defined]

    def fsync(self, fd: int) -> None:
        self.ops.append(("fsync", fd))
        self._real.fsync(fd)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


def test_check_alerts_reports_not_delivered_through_the_production_tee(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """G26: a 500 on the production tee is exit 3, not a swallowed success."""
    monkeypatch.setattr(
        "breezy.runtime.health._build_webhook_client", lambda timeout_s: _client(500)
    )
    code = main([], env={ALERT_WEBHOOK_URL_ENV_VAR: _URL})
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert code == EXIT_DELIVERY_FAILED
    assert "not delivered" in text.lower()
    assert "alerts.example.test" not in text
    _path, body = _one_record(alerts_root)
    assert body["delivered"] is False
    assert body["status_class"] == "5xx"
    assert body["attempt_kind"] == "alert"
    assert "_check_f.json" in _path.name


def test_deliver_with_proof_reports_non_2xx_through_tee(alerts_root: Path) -> None:
    proof = _proof(_tee(_client(500)), _payload(), alerts_root)
    assert proof == DeliveryProof(False, "5xx", "CAPTURE_PUBLISH_FAILED", proof.ts_ns, True)
    _path, body = _one_record(alerts_root)
    assert body["status_class"] == "5xx"
    assert body["delivered"] is False
    assert _path.name.endswith("_f.json")


def test_deliver_with_proof_treats_3xx_as_not_delivered(alerts_root: Path) -> None:
    proof = _proof(_tee(_client(302)), _payload(), alerts_root)
    assert proof.delivered is False
    assert proof.status_class == "3xx"
    _path, _body = _one_record(alerts_root)
    assert _path.name.endswith("_f.json")


def test_deliver_with_proof_reports_transport_failure_without_the_url(
    alerts_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "https://hooks.example.test/T000/zzSECRETzz"
    caplog.set_level(logging.ERROR, logger="breezy.runtime.alert_delivery")
    proof = _proof(
        _tee(_client(exc=httpx.ConnectError(f"failed {secret}"))), _payload(), alerts_root
    )
    assert proof.delivered is False
    assert proof.status_class == "transport"
    _path, body = _one_record(alerts_root)
    blob = _path.read_text(encoding="utf-8") + "\n".join(caplog.messages)
    assert secret not in blob
    assert "zzSECRETzz" not in blob
    assert "hooks.example.test" not in blob
    assert body["status_class"] == "transport"
    assert "detail" not in body
    assert "message" not in body


def test_deliver_with_proof_keeps_the_local_log_line(
    alerts_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="breezy.runtime.health")
    proof = _proof(_tee(_client(500)), _payload(), alerts_root)
    assert proof.delivered is False
    assert any(
        "breezy alert" in rec.message and "CAPTURE_PUBLISH_FAILED" in rec.message
        for rec in caplog.records
    )


def test_record_path_matches_arch_and_one_writer_per_file(alerts_root: Path) -> None:
    proof = _proof(_tee(_client(200)), _payload(), alerts_root, writer="legacy_runtime")
    assert proof.delivered is True
    path, body = _one_record(alerts_root)
    assert DELIVERY_RECORD_NAME_RE.fullmatch(path.name)
    assert body["schema"] == DELIVERY_SCHEMA
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    writer = DeliveryRecordWriter(alerts_root)
    first = writer.write(
        event="CAPTURE_PUBLISH_FAILED",
        ts_ns=proof.ts_ns,
        writer="legacy_runtime",
        delivered=True,
        status_class="2xx",
        severity="CRITICAL",
        attempt_kind="alert",
        drill=False,
        site="unit_test",
        outbox_entry="",
    )
    second = writer.write(
        event="CAPTURE_PUBLISH_FAILED",
        ts_ns=proof.ts_ns,
        writer="legacy_runtime",
        delivered=True,
        status_class="2xx",
        severity="CRITICAL",
        attempt_kind="alert",
        drill=False,
        site="unit_test",
        outbox_entry="",
    )
    assert first != second
    assert int(second.name.split("_", 1)[0]) == int(first.name.split("_", 1)[0]) + 1
    assert json.loads(second.read_text(encoding="utf-8"))["ts_ns"] == int(
        second.name.split("_", 1)[0]
    )


def test_record_carries_arch_fields_severity_attempt_kind_drill(alerts_root: Path) -> None:
    deliver_with_proof(
        _tee(_client(200)),
        _payload(severity="WARN", event="autonomy_canary_undelivered"),
        writer="canary",
        records=DeliveryRecordWriter(alerts_root),
        attempt_kind="canary",
        drill=True,
        outbox=AlertOutbox(alerts_root),
    )
    _path, body = _one_record(alerts_root)
    assert set(body) <= _RECORD_KEYS
    assert body["severity"] == "WARN"
    assert body["attempt_kind"] == "canary"
    assert body["drill"] is True
    assert body["schema"] == "alert_delivery/v1"
    assert body["site"] == "unit_test"
    assert "://" not in json.dumps(body)


def test_attempt_kind_enum_is_alert_retry_canary_drain(alerts_root: Path) -> None:
    for kind in _ATTEMPT_KINDS:
        deliver_with_proof(
            _tee(_client(200)),
            _payload(event=f"EV_{kind.upper()}", severity="INFO"),
            writer="health",
            records=DeliveryRecordWriter(alerts_root),
            attempt_kind=kind,  # type: ignore[arg-type]
            now_ns=_at(1_700_000_000_000_000_000 + _ATTEMPT_KINDS.index(kind)),
        )
    kinds = {
        json.loads(path.read_text(encoding="utf-8"))["attempt_kind"]
        for path in _records(alerts_root)
    }
    assert kinds == set(_ATTEMPT_KINDS)
    with pytest.raises(ValueError):
        deliver_with_proof(
            _tee(_client(200)),
            _payload(),
            writer="health",
            records=DeliveryRecordWriter(alerts_root),
            attempt_kind="inline",  # type: ignore[arg-type]
        )


def test_record_write_failure_never_blocks_delivery_and_counts_journal_write_failures(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> Path:
        raise OSError("journal down")

    monkeypatch.setattr(DeliveryRecordWriter, "write", _boom)
    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        posts.append(1)
        return httpx.Response(204)

    proof = _proof(
        _tee(httpx.Client(transport=httpx.MockTransport(handler))), _payload(), alerts_root
    )
    assert proof.delivered is True
    assert proof.recorded is False
    assert posts == [1]
    from breezy.runtime import alert_delivery as delivery

    assert delivery.COUNTERS.journal_write_failures >= 1


def test_outbox_entry_written_fsynced_before_http_attempt(alerts_root: Path) -> None:
    seen: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        seen.append(sorted(path.name for path in (alerts_root / "outbox").rglob("*.json")))
        raise httpx.ReadTimeout("stalled", request=None)

    proof = _proof(
        _tee(httpx.Client(transport=httpx.MockTransport(handler))),
        _payload(),
        alerts_root,
    )
    assert proof.delivered is False
    assert seen and seen[0], "the entry must exist under outbox/ before the POST returns"
    left = list((alerts_root / "outbox").rglob("*.json"))
    assert left, "a kill during the POST leaves the entry in the outbox tree"


def test_outbox_claim_stamps_utime_before_rename(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import breezy.runtime.alert_outbox as outbox_module

    recorder = _RecordingOs(os)
    monkeypatch.setattr(outbox_module, "os", recorder)
    outbox = AlertOutbox(alerts_root)
    entry = outbox.write_entry(_payload(), writer="health", drill=False, ts_ns=10)
    recorder.ops.clear()
    claimed = outbox.claim(entry, "redeliver")
    assert claimed is not None
    utime_at = next(i for i, op in enumerate(recorder.ops) if op[0] == "utime")
    rename_at = next(i for i, op in enumerate(recorder.ops) if op[0] == "rename")
    assert utime_at < rename_at
    assert not any(op[0] == "rename" for op in recorder.ops[:utime_at])
    rename = next(op for op in recorder.ops if op[0] == "rename")
    target = Path(str(rename[2]))
    assert "claimed" in target.parts and target.parent.name == "redeliver"
    assert any(
        op[0] == "open" and isinstance(op[2], int) and op[2] & os.O_DIRECTORY
        for op in recorder.ops[rename_at:]
    )
    assert any(op[0] == "fsync" for op in recorder.ops[rename_at:])


def test_claim_loser_gets_enoent_and_never_sends(alerts_root: Path) -> None:
    outbox = AlertOutbox(alerts_root)
    entry = outbox.write_entry(_payload(), writer="health", drill=False, ts_ns=11)
    assert outbox.claim(entry, "a") is not None
    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        posts.append(1)
        return httpx.Response(204)

    loser = deliver_with_proof(
        _tee(httpx.Client(transport=httpx.MockTransport(handler))),
        _payload(),
        writer="health",
        records=DeliveryRecordWriter(alerts_root),
        attempt_kind="alert",
        outbox=outbox,
        claimed=entry,
    )
    assert loser.delivered is False
    assert posts == []


def test_crash_between_utime_and_rename_leaves_entry_drainable(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import breezy.runtime.alert_delivery as delivery

    outbox = AlertOutbox(alerts_root)
    old_ns = time.time_ns() - 120 * 1_000_000_000
    entry = outbox.write_entry(_payload(), writer="health", drill=False, ts_ns=old_ns)
    real_rename = os.rename

    def _boom(src: object, dst: object) -> None:
        raise OSError("killed between utime and rename")

    monkeypatch.setattr(os, "rename", _boom)
    with pytest.raises(OSError, match="killed"):
        outbox.claim(entry, "redeliver")
    monkeypatch.setattr(os, "rename", real_rename)
    assert entry.is_file()
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request.content.decode())
        return httpx.Response(204)

    summary = delivery.drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_tee(httpx.Client(transport=httpx.MockTransport(handler))),
        records=DeliveryRecordWriter(alerts_root),
        min_age_s=60,
        now_ns=time.time_ns,
    )
    assert summary.delivered == 1
    assert posts


def test_outbox_age_read_from_filename_not_mtime(alerts_root: Path) -> None:
    import breezy.runtime.alert_delivery as delivery

    outbox = AlertOutbox(alerts_root)
    fresh_ns = time.time_ns()
    old_ns = fresh_ns - 120 * 1_000_000_000
    young = outbox.write_entry(
        _payload(event="YOUNG_EVENT"), writer="health", drill=False, ts_ns=fresh_ns
    )
    old = outbox.write_entry(
        _payload(event="OLD_EVENT"), writer="health", drill=False, ts_ns=old_ns
    )
    os.utime(old, (time.time(), time.time()))
    os.utime(young, (time.time() - 10_000, time.time() - 10_000))
    claimed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        claimed.append(json.loads(request.content.decode())["event"])
        return httpx.Response(204)

    delivery.drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_tee(httpx.Client(transport=httpx.MockTransport(handler))),
        records=DeliveryRecordWriter(alerts_root),
        min_age_s=60,
        now_ns=lambda: fresh_ns,
    )
    assert claimed == ["OLD_EVENT"]
    assert young.is_file()


def test_stale_claim_reclaimed_after_alert_claim_stale_s(alerts_root: Path) -> None:
    outbox = AlertOutbox(alerts_root)
    entry = outbox.write_entry(_payload(), writer="health", drill=False, ts_ns=12)
    claimed = outbox.claim(entry, "stall")
    assert claimed is not None
    now = time.time()
    os.utime(claimed, (now - ALERT_CLAIM_STALE_S, now - ALERT_CLAIM_STALE_S))
    assert outbox.reclaim_stale("rescue", now=now) == []
    os.utime(claimed, (now - ALERT_CLAIM_STALE_S - 1, now - ALERT_CLAIM_STALE_S - 1))
    got = outbox.reclaim_stale("rescue", now=now)
    assert len(got) == 1
    assert got[0].parent.name == "rescue"
    assert not claimed.exists()


def test_retry_restamps_claim_and_stops_on_enoent(alerts_root: Path) -> None:
    outbox = AlertOutbox(alerts_root)
    entry = outbox.write_entry(_payload(), writer="health", drill=False, ts_ns=13)
    claimed = outbox.claim(entry, "redeliver")
    assert claimed is not None
    assert outbox.restamp(claimed) is True
    claimed.unlink()
    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        posts.append(1)
        return httpx.Response(204)

    proof = deliver_with_proof(
        _tee(httpx.Client(transport=httpx.MockTransport(handler))),
        _payload(),
        writer="redeliver",
        records=DeliveryRecordWriter(alerts_root),
        attempt_kind="retry",
        outbox=outbox,
        claimed=claimed,
    )
    assert proof.delivered is False
    assert posts == []


def test_claimed_file_removed_only_after_delivery_record_written(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox = AlertOutbox(alerts_root)
    entry = outbox.write_entry(_payload(), writer="health", drill=False, ts_ns=14)
    claimed = outbox.claim(entry, "health")
    assert claimed is not None

    def _boom(*_a: object, **_k: object) -> Path:
        raise OSError("record disk full")

    monkeypatch.setattr(DeliveryRecordWriter, "write", _boom)
    proof = deliver_with_proof(
        _tee(_client(204)),
        _payload(),
        writer="health",
        records=DeliveryRecordWriter(alerts_root),
        attempt_kind="alert",
        outbox=outbox,
        claimed=claimed,
    )
    assert proof.delivered is True
    assert proof.recorded is False
    assert claimed.is_file()


def test_critical_survives_sigkill(alerts_root: Path) -> None:
    import subprocess
    import sys
    import textwrap

    outbox = AlertOutbox(alerts_root)
    now = time.time_ns()
    for name, ts in (
        ("STALL_POST", now - 90 * 1_000_000_000),
        ("BETWEEN", now - 80 * 1_000_000_000),
    ):
        outbox.write_entry(_payload(event=name), writer="node", drill=False, ts_ns=ts)
    script = textwrap.dedent(
        """
        import os, sys, time
        from breezy.runtime.alert_delivery import AlertOutbox
        root = sys.argv[1]
        event = sys.argv[2]
        ready = sys.argv[3]
        outbox = AlertOutbox(__import__("pathlib").Path(root))
        entry = next(p for p in (outbox.root / "outbox").glob("*.json") if event in p.name)
        claimed = outbox.claim(entry, "stall")
        open(ready, "w").write(str(claimed))
        time.sleep(60)
        """
    )
    py = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    procs: list[subprocess.Popen[str]] = []
    readies: list[Path] = []
    for event in ("STALL_POST", "BETWEEN"):
        ready = alerts_root / f"ready-{event}"
        readies.append(ready)
        procs.append(
            subprocess.Popen(
                [py, "-c", script, str(alerts_root), event, str(ready)],
                env=env,
                text=True,
            )
        )
    deadline = time.time() + 10
    while time.time() < deadline and not all(path.is_file() for path in readies):
        time.sleep(0.05)
    assert all(path.is_file() for path in readies)
    for proc in procs:
        proc.kill()
        proc.wait(timeout=5)
    import breezy.runtime.alert_delivery as delivery

    # E-1 reclaims only once the claim mtime is strictly older than ALERT_CLAIM_STALE_S.
    stale_at = time.time() - (delivery.ALERT_CLAIM_STALE_S + 1)
    for ready in readies:
        os.utime(Path(ready.read_text(encoding="utf-8")), (stale_at, stale_at))
    summary = delivery.drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_tee(_client(204)),
        records=DeliveryRecordWriter(alerts_root),
        min_age_s=60,
        now_ns=time.time_ns,
    )
    assert summary.delivered == 2
    names = [path.name for path in _records(alerts_root)]
    assert sum(name.endswith("_d.json") for name in names) == 2


def test_critical_alerts_use_delivery_proof(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "breezy.runtime.health._build_webhook_client", lambda timeout_s: _client(204)
    )
    sink = resolve_alert_sink({ALERT_WEBHOOK_URL_ENV_VAR: _URL})
    try:
        emit_alert(sink, _payload())
    finally:
        sink.close()  # type: ignore[attr-defined]
    _path, body = _one_record(alerts_root)
    assert body["delivered"] is True
    assert body["event"] == "CAPTURE_PUBLISH_FAILED"
    assert _path.name.split("_", 1)[1].startswith("legacy_")


def test_detector_and_failure_mode_alerts_use_delivery_proof() -> None:
    import breezy.persistence.autonomy.detector_catalog as catalog

    assert hasattr(catalog, "CATALOG")  # WP5 lands the catalogue (WP1 pinned its absence)
    critical = {
        event for event, severity in CAPTURE_ALERT_SEVERITIES.items() if severity == "CRITICAL"
    }
    assert "CAPTURE_VENUE_SILENT" not in critical
    assert critical <= PROOF_BEARING_EVENTS
    assert {"autonomy_canary_undelivered", "bwrap_self_probe_failed"} <= PROOF_BEARING_EVENTS
    assert is_proof_bearing(_payload(event="CAPTURE_VENUE_SILENT", severity="WARNING")) is False
    assert is_proof_bearing(_payload(event="autonomy_canary_undelivered", severity="WARN")) is True
    assert is_proof_bearing(_payload(event="OTHER", severity="CRITICAL")) is True
    assert is_proof_bearing(_payload(event="OTHER", severity="INFO")) is False


def test_legacy_noncritical_non_detector_failure_is_recorded_not_queued(alerts_root: Path) -> None:
    proof = _proof(
        _tee(_client(500)),
        _payload(event="FEE_SCHEDULE_STALE", severity="WARN"),
        alerts_root,
    )
    assert proof.delivered is False
    assert proof.recorded is True
    assert list((alerts_root / "outbox").rglob("*.json")) == []
    _path, body = _one_record(alerts_root)
    assert body["delivered"] is False
    assert _path.name.endswith("_f.json")


def test_resolve_alert_sink_webhook_branch_records_and_queues_proof_bearing(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        seen.append(len(list((alerts_root / "outbox").rglob("*.json"))))
        return httpx.Response(204)

    monkeypatch.setattr(
        "breezy.runtime.health._build_webhook_client",
        lambda timeout_s: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    sink = resolve_alert_sink({ALERT_WEBHOOK_URL_ENV_VAR: _URL})
    try:
        branch_types = [type(branch) for branch in sink.sinks]  # type: ignore[attr-defined]
        assert WebhookAlertSink in branch_types
        assert LoggingAlertSink in branch_types
        emit_alert(sink, _payload())
    finally:
        sink.close()  # type: ignore[attr-defined]
    assert seen == [1]
    _path, body = _one_record(alerts_root)
    assert body["delivered"] is True
    assert body["outbox_entry"]
    assert list((alerts_root / "outbox").rglob("*.json")) == []


def test_outbox_overflow_records_status_and_fails_23(alerts_root: Path) -> None:
    out = alerts_root / "outbox"
    out.mkdir(parents=True)
    os.chmod(out, 0o700)
    for index in range(ALERT_OUTBOX_MAX):
        (out / f"{index}_FULL.json").write_text("{}", encoding="utf-8")
    proof = _proof(_tee(_client(204)), _payload(), alerts_root)
    assert proof.delivered is False
    assert proof.status_class == "outbox_overflow"
    _path, body = _one_record(alerts_root)
    assert body["status_class"] == "outbox_overflow"


def test_outbox_reserves_16_slots_for_critical(alerts_root: Path) -> None:
    assert ALERT_OUTBOX_CRITICAL_RESERVED < ALERT_OUTBOX_MAX
    out = alerts_root / "outbox"
    out.mkdir(parents=True)
    os.chmod(out, 0o700)
    for index in range(ALERT_OUTBOX_MAX - ALERT_OUTBOX_CRITICAL_RESERVED):
        (out / f"{index}_USED.json").write_text("{}", encoding="utf-8")
    outbox = AlertOutbox(alerts_root)
    warn = _proof(
        _tee(_client(204)),
        _payload(event="CAPTURE_REFUSED", severity="WARN"),
        alerts_root,
        outbox=outbox,
    )
    assert warn.status_class == "outbox_overflow"
    critical = _proof(_tee(_client(204)), _payload(event="CRIT_OK"), alerts_root, outbox=outbox)
    assert critical.delivered is True
    occupied = len(list(out.rglob("*.json")))
    for index in range(ALERT_OUTBOX_MAX - occupied):
        (out / f"{1000 + index}_PAD.json").write_text("{}", encoding="utf-8")
    refused = _proof(
        _tee(_client(204)),
        _payload(event="CRIT_FULL"),
        alerts_root,
        outbox=AlertOutbox(alerts_root),
    )
    assert refused.status_class == "outbox_overflow"


def test_outbox_write_failure_is_logged_counted_recorded_and_still_attempted(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom(*_a: object, **_k: object) -> Path:
        raise OSError("outbox ro")

    monkeypatch.setattr(AlertOutbox, "write_entry", _boom)
    caplog.set_level(logging.ERROR, logger="breezy.runtime.alert_delivery")
    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        posts.append(1)
        return httpx.Response(204)

    proof = _proof(
        _tee(httpx.Client(transport=httpx.MockTransport(handler))), _payload(), alerts_root
    )
    assert proof.delivered is True
    assert posts == [1]
    assert any("alert_outbox_unwritable" in message for message in caplog.messages)
    _path, body = _one_record(alerts_root)
    assert body["outbox_write_failed"] is True
    from breezy.runtime import alert_delivery as delivery

    assert delivery.COUNTERS.outbox_write_failures >= 1


def test_tee_containment_unchanged_with_journaling_branch(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        "breezy.runtime.health._build_webhook_client", lambda timeout_s: _client(500)
    )
    caplog.set_level(logging.INFO, logger="breezy.runtime.health")
    sink = resolve_alert_sink({ALERT_WEBHOOK_URL_ENV_VAR: _URL})
    try:
        emit_alert(sink, _payload())
        assert any("breezy alert" in rec.message for rec in caplog.records)
        hook = next(branch for branch in sink.sinks if isinstance(branch, WebhookAlertSink))  # type: ignore[attr-defined]
        with pytest.raises(AlertNotDeliveredError):
            hook.emit(_payload(event="DIRECT"))
    finally:
        sink.close()  # type: ignore[attr-defined]


def test_enqueue_alert_writes_no_failure_record_and_does_not_post(alerts_root: Path) -> None:
    # enqueue_alert takes no sink, so a successful enqueue cannot POST.
    queued = enqueue_alert(
        _payload(event="NETWORK_NONE_CRIT"),
        writer="engine",
        outbox=AlertOutbox(alerts_root),
        records=DeliveryRecordWriter(alerts_root),
    )
    assert queued is True
    assert _records(alerts_root) == []
    assert list((alerts_root / "outbox").glob("*.json"))


def test_delivery_record_matches_capture_aut6_contract(alerts_root: Path) -> None:
    """The one AUT-1 reader contract: name regex plus schema, and no URL field."""
    deliver_with_proof(
        _tee(_client(200)),
        _payload(),
        writer="legacy_runtime",
        records=DeliveryRecordWriter(alerts_root),
        attempt_kind="alert",
        outbox=AlertOutbox(alerts_root),
    )
    path, body = _one_record(alerts_root)
    assert DELIVERY_RECORD_NAME_RE.fullmatch(path.name)
    assert body["schema"] == DELIVERY_SCHEMA
    assert "://" not in json.dumps(body)


def test_non_proof_bearing_alert_is_still_posted_when_the_outbox_is_full(
    alerts_root: Path,
) -> None:
    out = alerts_root / "outbox"
    out.mkdir(parents=True)
    os.chmod(out, 0o700)
    for index in range(ALERT_OUTBOX_MAX):
        (out / f"{index}_FULL.json").write_text("{}", encoding="utf-8")
    proof = _proof(
        _tee(_client(204)), _payload(event="FEE_SCHEDULE_STALE", severity="WARN"), alerts_root
    )
    assert proof.delivered is True
    assert proof.status_class == "2xx"


def test_reclaim_tolerates_a_claim_vanishing_before_its_stat(
    alerts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox = AlertOutbox(alerts_root)
    entry = outbox.write_entry(_payload(), writer="health", drill=False, ts_ns=5)
    held = outbox.claim(entry, "other")
    assert held is not None
    real_stat = Path.stat

    def _gone(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self.name == held.name:
            raise FileNotFoundError(self.name)
        return real_stat(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "stat", _gone)
    assert outbox.reclaim_stale("redeliver") == []


def test_drain_attempts_a_reclaimed_claim_even_when_younger_than_min_age(
    alerts_root: Path,
) -> None:
    from breezy.runtime import alert_delivery as delivery

    outbox = AlertOutbox(alerts_root)
    entry = outbox.write_entry(_payload(), writer="health", drill=False, ts_ns=time.time_ns())
    held = outbox.claim(entry, "stalled")
    assert held is not None
    stale_at = time.time() - (ALERT_CLAIM_STALE_S + 1)
    os.utime(held, (stale_at, stale_at))
    summary = delivery.drain_outbox(
        drainer="deadman",
        outbox=outbox,
        sink=_tee(_client(204)),
        records=DeliveryRecordWriter(alerts_root),
        min_age_s=300,
    )
    assert summary.reclaims == 1
    assert summary.delivered == 1


def test_journaling_sink_is_a_webhook_alert_sink_instance() -> None:
    sink = JournalingWebhookAlertSink(_URL, client=_client(204), writer="legacy_runtime")
    try:
        assert type(sink) is WebhookAlertSink
        assert isinstance(sink, WebhookAlertSink)
    finally:
        sink.close()
