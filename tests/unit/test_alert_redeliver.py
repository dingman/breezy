"""AUT-6 WP1 redeliver CLI and drain_outbox budget, age and dead-man."""

from __future__ import annotations

import errno
import json
import logging
import os
import stat
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
from breezy.runtime.alert_drain import DrainSummary
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


_NS = 1_000_000_000
_NOW = 1_700_000_000 * _NS
_BACKOFF = "webhook.backoff"


def _counting_sink(statuses: list[int]) -> tuple[TeeAlertSink, list[int]]:
    seen: list[int] = []
    coming = iter(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        code = next(coming)
        seen.append(code)
        return httpx.Response(code)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TeeAlertSink(LoggingAlertSink(), WebhookAlertSink(_URL, client=client)), seen


def _due(
    outbox: AlertOutbox,
    event: str,
    age_s: int,
    *,
    severity: str = "CRITICAL",
    now: int = _NOW,
) -> Path:
    return outbox.write_entry(
        AlertPayload(severity=severity, event=event, site="redeliver", detail="closed"),
        writer="node",
        drill=False,
        ts_ns=now - age_s * _NS,
    )


def _drain(
    root: Path,
    sink: object,
    *,
    now: int = _NOW,
    min_age_s: int = 60,
    budget_s: int = 40,
    monotonic: object | None = None,
) -> DrainSummary:
    kwargs: dict[str, object] = {
        "drainer": "redeliver",
        "outbox": AlertOutbox(root),
        "sink": sink,
        "records": DeliveryRecordWriter(root),
        "min_age_s": min_age_s,
        "budget_s": budget_s,
        "now_ns": lambda: now,
    }
    if monotonic is not None:
        kwargs["monotonic"] = monotonic
    return drain_outbox(**kwargs)  # type: ignore[arg-type]


def _plant(root: Path, *, failures: int, next_ns: int, last_status: int) -> Path:
    path = root / _BACKOFF
    path.write_text(
        json.dumps({"failures": failures, "next_attempt_ns": next_ns, "last_status": last_status}),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    return path


def test_future_backoff_posts_nothing(root: Path) -> None:
    """288-probes/day guard: next_attempt_ns in the future means zero POSTs and no claim."""
    outbox = AlertOutbox(root)
    entry = _due(outbox, "HELD", 120)
    _plant(root, failures=1, next_ns=_NOW + 300 * _NS, last_status=429)
    sink, seen = _counting_sink([204])
    summary = _drain(root, sink)
    assert seen == []
    assert summary.attempted == 0
    assert summary.skipped_backoff == 1
    assert summary.probe == 0
    assert entry.is_file()
    assert not (root / "outbox" / "claimed").exists()


def test_payload_4xx_on_one_entry_does_not_back_off_siblings(root: Path) -> None:
    outbox = AlertOutbox(root)
    _due(outbox, "BAD_PAYLOAD", 200)
    _due(outbox, "SIBLING", 120)
    sink, seen = _counting_sink([400, 400])
    summary = _drain(root, sink)
    assert seen == [400, 400]
    assert summary.http_4xx == 2
    assert not (root / _BACKOFF).exists()


def test_backoff_class_429_stops_the_pass_and_sets_the_global_file(root: Path) -> None:
    outbox = AlertOutbox(root)
    _due(outbox, "FIRST", 300)
    _due(outbox, "SECOND", 120)
    sink, seen = _counting_sink([429, 204])
    summary = _drain(root, sink)
    assert seen == [429]
    assert summary.probe == 0
    body = json.loads((root / _BACKOFF).read_text(encoding="utf-8"))
    assert body["failures"] == 1
    assert body["last_status"] == 429
    assert body["next_attempt_ns"] == _NOW + 300 * _NS
    assert stat.S_IMODE((root / _BACKOFF).stat().st_mode) == 0o600
    later, seen_later = _counting_sink([204, 204])
    held = _drain(root, later, now=_NOW + 100 * _NS)
    assert seen_later == []
    assert held.skipped_backoff == 2


def test_critical_4xx_reattempted_within_cap(root: Path) -> None:
    """The oldest due entry is the probe, so a CRITICAL is posted again inside 1800 s."""
    outbox = AlertOutbox(root)
    _due(outbox, "CRIT", 400, severity="CRITICAL")
    sink, seen = _counting_sink([429])
    _drain(root, sink)
    again, seen_again = _counting_sink([429])
    summary = _drain(root, again, now=_NOW + 300 * _NS)
    assert seen == [429]
    assert seen_again == [429]
    assert summary.probe == 1
    body = json.loads((root / _BACKOFF).read_text(encoding="utf-8"))
    assert body["failures"] == 2
    assert body["next_attempt_ns"] == _NOW + 300 * _NS + 600 * _NS


def test_backoff_doubling_caps_at_1800s(root: Path) -> None:
    outbox = AlertOutbox(root)
    _due(outbox, "CRIT", 400)
    _plant(root, failures=4, next_ns=_NOW, last_status=429)
    sink, seen = _counting_sink([429, 204])
    _drain(root, sink)
    assert seen == [429]
    body = json.loads((root / _BACKOFF).read_text(encoding="utf-8"))
    assert body["failures"] == 5
    assert body["next_attempt_ns"] == _NOW + 1800 * _NS


def test_2xx_probe_clears_backoff_and_the_pass_continues(root: Path) -> None:
    outbox = AlertOutbox(root)
    _due(outbox, "OLDER", 400, severity="WARN")
    _due(outbox, "NEWER", 120, severity="CRITICAL")
    _plant(root, failures=2, next_ns=_NOW, last_status=429)
    sink, seen = _counting_sink([204, 204])
    summary = _drain(root, sink)
    assert seen == [204, 204]
    assert summary.probe == 1
    assert summary.delivered == 2
    assert not (root / _BACKOFF).exists()


def test_5xx_probe_clears_backoff_and_one_pass_continues(root: Path) -> None:
    outbox = AlertOutbox(root)
    _due(outbox, "OLDER", 400)
    _due(outbox, "NEWER", 120)
    _plant(root, failures=1, next_ns=_NOW - _NS, last_status=429)
    sink, seen = _counting_sink([500, 500])
    summary = _drain(root, sink)
    assert seen == [500, 500]
    assert summary.probe == 1
    assert not (root / _BACKOFF).exists()


def _outcome_sink(outcome: str) -> tuple[object, list[int]]:
    """One probe response for the R3 backoff matrix. ``not_configured`` has no webhook branch."""
    if outcome == "not_configured":
        return LoggingAlertSink(), []
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        if outcome == "transport":
            raise httpx.ConnectError("down")
        code = {"2xx": 204, "5xx": 500, "3xx": 302, "payload_4xx": 400}.get(outcome)
        if code is None:
            code = int(outcome)
        seen.append(code)
        return httpx.Response(code)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TeeAlertSink(LoggingAlertSink(), WebhookAlertSink(_URL, client=client)), seen


@pytest.mark.parametrize(
    ("outcome", "effect"),
    [
        ("2xx", "clear"),
        ("5xx", "clear"),
        ("transport", "clear"),
        ("payload_4xx", "clear"),
        ("3xx", "unchanged"),
        ("not_configured", "unchanged"),
        ("429", "set"),
        ("401", "set"),
        ("403", "set"),
        ("404", "set"),
        ("410", "set"),
    ],
)
def test_r3_backoff_outcome_matrix(root: Path, outcome: str, effect: str) -> None:
    """R3 matrix: clear on 2xx/5xx/transport/payload-4xx; unchanged on 3xx and not_configured;
    set only on 429/401/403/404/410.
    """
    outbox = AlertOutbox(root)
    _due(outbox, "PROBE", 300)
    planted = _plant(root, failures=1, next_ns=_NOW, last_status=429)
    before = planted.read_text(encoding="utf-8")
    sink, _seen = _outcome_sink(outcome)
    _drain(root, sink)
    path = root / _BACKOFF
    if effect == "clear":
        assert not path.exists()
        return
    if effect == "unchanged":
        assert path.read_text(encoding="utf-8") == before
        return
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["failures"] == 2
    assert body["last_status"] == int(outcome)
    assert body["next_attempt_ns"] == _NOW + 600 * _NS


def test_new_critical_attempted_when_older_due_noncritical_entries_exist(root: Path) -> None:
    outbox = AlertOutbox(root)
    older = _due(outbox, "OLDER_WARN", 500, severity="WARN")
    critical = _due(outbox, "NEW_CRITICAL", 120, severity="CRITICAL")
    sink, seen = _counting_sink([204, 204, 204])
    summary = _drain(root, sink, monotonic=iter((0.0, 0.0, 50.0, 50.0)).__next__)
    assert seen == [204]
    assert summary.delivered == 1
    assert not critical.is_file()
    assert older.is_file()


def test_abandoned_does_not_grow_while_backoff_is_active(root: Path) -> None:
    outbox = AlertOutbox(root)
    entry = _due(outbox, "STALE", 24 * 3600 + 5)
    _plant(root, failures=1, next_ns=_NOW + 300 * _NS, last_status=410)
    sink, seen = _counting_sink([204])
    summary = _drain(root, sink)
    assert seen == []
    assert summary.abandoned == ()
    assert entry.is_file()


def test_probe_entry_is_claimed_and_may_be_abandoned(root: Path) -> None:
    outbox = AlertOutbox(root)
    entry = _due(outbox, "STALE_PROBE", 24 * 3600 + 5)
    _plant(root, failures=1, next_ns=_NOW, last_status=404)
    sink, seen = _counting_sink([204])
    summary = _drain(root, sink)
    assert seen == [204]
    assert summary.probe == 1
    assert entry.name in summary.abandoned


def test_malformed_backoff_fails_open_and_logs_the_exception_type(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (root / _BACKOFF).write_text("not-json", encoding="utf-8")
    outbox = AlertOutbox(root)
    _due(outbox, "DUE", 120)
    caplog.set_level(logging.ERROR, logger="breezy.runtime.alert_drain")
    sink, seen = _counting_sink([204])
    _drain(root, sink)
    assert seen == [204]
    text = "\n".join(caplog.messages)
    assert "alert_backoff_unreadable" in text
    assert "exception_type=" in text
    assert str(root) not in text


def test_next_attempt_more_than_1800s_ahead_is_corrupt_and_due(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _plant(root, failures=1, next_ns=_NOW + 1801 * _NS, last_status=429)
    outbox = AlertOutbox(root)
    _due(outbox, "DUE", 120)
    caplog.set_level(logging.ERROR, logger="breezy.runtime.alert_drain")
    sink, seen = _counting_sink([204])
    _drain(root, sink)
    assert seen == [204]
    assert "alert_backoff_unreadable" in "\n".join(caplog.messages)


def test_sidecar_write_oserror_does_not_abort_pass(
    root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real = os.replace

    def _boom(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if str(dst).endswith(_BACKOFF):
            raise OSError(errno.EIO, "disk")
        real(src, dst)

    monkeypatch.setattr("breezy.runtime.alert_outbox.os.replace", _boom)
    caplog.set_level(logging.ERROR, logger="breezy.runtime.alert_outbox")
    outbox = AlertOutbox(root)
    _due(outbox, "FIRST", 300)
    _due(outbox, "SECOND", 120)
    sink, seen = _counting_sink([429, 204])
    _drain(root, sink)
    assert seen == [429, 204]
    text = "\n".join(caplog.messages)
    assert "alert_backoff_unwritable" in text
    assert "exception_type=OSError" in text
    assert "basename=webhook.backoff" in text
    assert str(root) not in text


def test_symlinked_webhook_backoff_is_refused_then_fails_open(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    secret = root / "secret-target"
    secret.write_text("TOPSECRET", encoding="utf-8")
    (root / _BACKOFF).symlink_to(secret)
    outbox = AlertOutbox(root)
    _due(outbox, "DUE", 120)
    caplog.set_level(logging.ERROR, logger="breezy.runtime.alert_drain")
    sink, seen = _counting_sink([204])
    _drain(root, sink)
    assert seen == [204]
    assert (root / _BACKOFF).is_symlink()
    assert secret.read_text(encoding="utf-8") == "TOPSECRET"
    text = "\n".join(caplog.messages)
    assert "alert_backoff_unreadable" in text
    assert str(secret) not in text


def test_one_warning_per_backoff_episode_names_the_status_and_no_url(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    outbox = AlertOutbox(root)
    _due(outbox, "CRIT", 400)
    caplog.set_level(logging.WARNING, logger="breezy.runtime.alert_drain")
    sink, _seen = _counting_sink([401])
    _drain(root, sink)
    again, _again_seen = _counting_sink([401])
    _drain(root, again, now=_NOW + 300 * _NS)
    warnings = [rec.message for rec in caplog.records if rec.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "status=401" in warnings[0]
    assert "://" not in warnings[0]
    assert "http" not in warnings[0]


def test_eight_payload_4xx_attempts_log_a_streak(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    outbox = AlertOutbox(root)
    for index in range(8):
        _due(outbox, f"P{index}", 120 + index)
    caplog.set_level(logging.ERROR, logger="breezy.runtime.alert_drain")
    sink, seen = _counting_sink([400] * 8)
    summary = _drain(root, sink)
    assert seen == [400] * 8
    assert summary.http_4xx == 8
    assert "alert_delivery_4xx_streak" in "\n".join(caplog.messages)
    assert not (root / _BACKOFF).exists()


def test_deadman_drain_honours_the_backoff_filter(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = time.time_ns()
    outbox = AlertOutbox(root)
    entry = outbox.write_entry(
        AlertPayload(severity="CRITICAL", event="DEAD", site="redeliver", detail="closed"),
        writer="node",
        drill=False,
        ts_ns=now - 400 * _NS,
    )
    _plant(root, failures=1, next_ns=now + 600 * _NS, last_status=403)
    sink, seen = _counting_sink([204])
    monkeypatch.setattr("breezy.runtime.alert_delivery.resolve_alert_sink", lambda env=None: sink)
    run_deadman_drain()
    assert seen == []
    assert entry.is_file()


def test_summary_line_names_backoff_skips_and_4xx_count(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from breezy.runtime.alert_delivery import COUNTERS, DrainSummary

    monkeypatch.setattr(COUNTERS, "journal_write_failures", 0)
    monkeypatch.setattr(COUNTERS, "outbox_write_failures", 0)
    (root / ".redeliver.lock").write_text("", encoding="utf-8")

    def _fake(**kwargs: object) -> DrainSummary:
        del kwargs
        return DrainSummary(0, 0, 0, 0, (), skipped_backoff=2, http_4xx=1, probe=1)

    monkeypatch.setattr("breezy.runtime.alert_redeliver_cli.drain_outbox", _fake)
    monkeypatch.setattr(
        "breezy.runtime.alert_redeliver_cli.resolve_alert_sink", lambda env=None: LoggingAlertSink()
    )
    assert main([]) == 0
    text = capsys.readouterr().out
    assert "skipped_backoff=2" in text
    assert "http4xx=1" in text
    assert "probe=1" in text
    assert "delivered=0" in text
    assert "journal_write_failures=0" in text


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
