"""AUT-6 WP1 redeliver CLI and drain_outbox budget, age and dead-man."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest

from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_delivery import (
    ALERT_OUTBOX_STALE_S,
    REDELIVER_MIN_AGE_S,
    AlertOutbox,
    DeliveryRecordWriter,
    drain_outbox,
    run_deadman_drain,
)
from breezy.runtime.alert_redeliver_cli import main
from breezy.runtime.health import LoggingAlertSink, TeeAlertSink, WebhookAlertSink

_URL = "https://alerts.example.test/hook"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("breezy.runtime.alert_delivery.default_alerts_root", lambda: tmp_path)
    monkeypatch.setattr("breezy.runtime.alert_redeliver_cli.default_alerts_root", lambda: tmp_path)
    return tmp_path


def _sink(status: int = 204) -> TeeAlertSink:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TeeAlertSink(LoggingAlertSink(), WebhookAlertSink(_URL, client=client))


def _entry(outbox: AlertOutbox, event: str, age_s: int) -> Path:
    return outbox.write_entry(
        AlertPayload(severity="CRITICAL", event=event, site="redeliver", detail="closed"),
        writer="node",
        drill=False,
        ts_ns=time.time_ns() - age_s * 1_000_000_000,
    )


def test_redeliver_claims_unclaimed_entries_older_than_60s_only(root: Path) -> None:
    outbox = AlertOutbox(root)
    young = _entry(outbox, "YOUNG", REDELIVER_MIN_AGE_S - 1)
    old = _entry(outbox, "OLD", REDELIVER_MIN_AGE_S + 1)
    os.utime(old, None)
    summary = drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_sink(),
        records=DeliveryRecordWriter(root),
        min_age_s=REDELIVER_MIN_AGE_S,
        now_ns=time.time_ns,
    )
    assert summary.delivered == 1
    assert young.is_file()
    assert not old.is_file()


def test_redeliver_stops_claiming_after_40s_budget(root: Path) -> None:
    outbox = AlertOutbox(root)
    for index in range(3):
        _entry(outbox, f"BUDGET_{index}", 120)
    clock = iter((0.0, 0.0, 50.0, 50.0))

    def monotonic() -> float:
        return next(clock)

    summary = drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_sink(),
        records=DeliveryRecordWriter(root),
        min_age_s=60,
        budget_s=40,
        monotonic=monotonic,
        now_ns=time.time_ns,
    )
    assert summary.delivered == 1
    left = list((root / "outbox").glob("*.json"))
    assert len(left) == 2


def test_abandoned_entry_still_attempted_and_named(root: Path) -> None:
    outbox = AlertOutbox(root)
    path = _entry(outbox, "ABANDONED_EVENT", 24 * 3600 + 5)
    summary = drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_sink(),
        records=DeliveryRecordWriter(root),
        min_age_s=60,
        now_ns=time.time_ns,
    )
    assert summary.delivered == 1
    assert path.name in summary.abandoned
    assert not path.is_file()


def test_write_on_change_alert_resent_after_failed_delivery(root: Path) -> None:
    outbox = AlertOutbox(root)
    path = _entry(outbox, "PENDING", 120)
    failed = drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_sink(500),
        records=DeliveryRecordWriter(root),
        min_age_s=60,
        now_ns=time.time_ns,
    )
    assert failed.delivered == 0
    kept = list((root / "outbox").rglob("*.json"))
    assert kept
    retried = drain_outbox(
        drainer="redeliver",
        outbox=AlertOutbox(root),
        sink=_sink(204),
        records=DeliveryRecordWriter(root),
        min_age_s=0,
        now_ns=time.time_ns,
    )
    assert retried.delivered == 1
    assert not path.is_file()
    bodies = [json.loads(item.read_text(encoding="utf-8")) for item in root.rglob("*_d.json")]
    assert any(body.get("delivered") is True for body in bodies)


def test_redeliver_runs_the_production_default_once(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from breezy.runtime.alert_delivery import COUNTERS

    monkeypatch.setattr(COUNTERS, "journal_write_failures", 0)
    monkeypatch.setattr(COUNTERS, "outbox_write_failures", 0)
    lock = root / ".redeliver.lock"
    lock.write_text("", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def _drain(**kwargs: object) -> object:
        calls.append(kwargs)
        from breezy.runtime.alert_delivery import DrainSummary

        return DrainSummary(0, 0, 0, 0, ())

    monkeypatch.setattr("breezy.runtime.alert_redeliver_cli.drain_outbox", _drain)
    monkeypatch.setattr(
        "breezy.runtime.alert_redeliver_cli.resolve_alert_sink", lambda env=None: LoggingAlertSink()
    )
    assert main([]) == 0
    assert len(calls) == 1
    assert calls[0]["drainer"] == "redeliver"
    assert calls[0]["min_age_s"] == REDELIVER_MIN_AGE_S
    assert calls[0]["budget_s"] == 40
    text = capsys.readouterr().out
    assert "AUTONOMY_REDELIVER" in text
    assert "delivered=0" in text
    # plan r15 §3.6.2-3.6.3: the unit summary line carries both process counters
    assert "journal_write_failures=0" in text
    assert "outbox_write_failures=0" in text
    assert "abandoned=0" in text


def test_drain_outbox_deadman_call_runs_the_production_default_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _drain(**kwargs: object) -> object:
        calls.append(kwargs)
        from breezy.runtime.alert_delivery import DrainSummary

        return DrainSummary(0, 0, 0, 0, ())

    monkeypatch.setattr("breezy.runtime.alert_delivery.drain_outbox", _drain)
    monkeypatch.setattr(
        "breezy.runtime.alert_delivery.resolve_alert_sink", lambda env=None: LoggingAlertSink()
    )
    run_deadman_drain()
    assert len(calls) == 1
    assert calls[0]["drainer"] == "deadman"
    assert calls[0]["min_age_s"] == ALERT_OUTBOX_STALE_S


def test_redeliver_missing_lock_is_integrity_and_exit_3(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "breezy.runtime.alert_redeliver_cli.resolve_alert_sink", lambda env=None: LoggingAlertSink()
    )
    code = main([])
    text = capsys.readouterr().out + capsys.readouterr().err
    assert code == 3
    assert "INTEGRITY lock_file_missing" in text


def test_redeliver_lock_held_skips(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import fcntl

    lock = root / ".redeliver.lock"
    lock.write_text("", encoding="utf-8")
    fd = os.open(lock, os.O_RDONLY | os.O_CLOEXEC)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        code = main([])
    finally:
        os.close(fd)
    text = capsys.readouterr().out + capsys.readouterr().err
    assert code == 0
    assert "SKIPPED lock_held" in text


def test_redeliver_names_an_abandoned_entry_on_its_summary_output(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / ".redeliver.lock").write_text("", encoding="utf-8")
    path = _entry(AlertOutbox(root), "ABANDONED_EVENT", 24 * 3600 + 5)
    monkeypatch.setattr(
        "breezy.runtime.alert_redeliver_cli.resolve_alert_sink", lambda env=None: LoggingAlertSink()
    )
    assert main([]) == 0
    text = capsys.readouterr().out
    assert f"abandoned_entry={path.name}" in text
    assert "abandoned=1" in text
