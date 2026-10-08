"""AUT-6 WP2: the alert canary CLI (plan r15 sections 3.7 and 3.7.1; ruling r3: no heartbeat).

The CLI delivers through ``deliver_with_proof``, so every case judges the delivery record the
unit leaves, the line it prints and its exit code. Time is injected through ``now_ns``.
"""

from __future__ import annotations

import ast
import datetime as dt
import fcntl
import json
import logging
import os
import stat
from pathlib import Path
from typing import Final

import httpx
import pytest

from breezy.persistence.autonomy import pins
from breezy.registry.health_model import AlertPayload
from breezy.runtime import autonomy_canary_cli
from breezy.runtime.alert_outbox import DeliveryRecordWriter, write_armed_marker
from breezy.runtime.alert_proof import COUNTERS
from breezy.runtime.autonomy_canary_cli import main
from breezy.runtime.health import LoggingAlertSink, TeeAlertSink, WebhookAlertSink

_NS: Final = 1_000_000_000
_URL: Final = "https://alerts.example.test/hook"
_DRILL_DAY: Final = "2026-10-21"


def _ns(day: int, hour: int, minute: int, second: int = 0, month: int = 10) -> int:
    moment = dt.datetime(2026, month, day, hour, minute, second, tzinfo=dt.UTC)
    return int(moment.timestamp()) * _NS


class _Webhook:
    """A MockTransport-backed sink that records the JSON bodies it was sent."""

    def __init__(self, status: int = 204) -> None:
        self.status = status
        self.bodies: list[dict[str, str]] = []
        self.clients: list[httpx.Client] = []

    def make_sink(self) -> TeeAlertSink:
        """A fresh sink per call, as each process gets one; the CLI closes it."""
        client = httpx.Client(transport=httpx.MockTransport(self._handle))
        self.clients.append(client)
        return TeeAlertSink(LoggingAlertSink(), WebhookAlertSink(_URL, client=client))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(self.status)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    alerts = tmp_path / "alerts"
    alerts.mkdir()
    (alerts / ".canary.lock").write_bytes(b"")
    for module in (
        "breezy.runtime.alert_delivery",
        "breezy.runtime.autonomy_canary_cli",
    ):
        monkeypatch.setattr(f"{module}.default_alerts_root", lambda: alerts)
    return alerts


@pytest.fixture
def webhook(monkeypatch: pytest.MonkeyPatch) -> _Webhook:
    hook = _Webhook()
    monkeypatch.setattr(autonomy_canary_cli, "resolve_alert_sink", hook.make_sink)
    return hook


def _run(at_ns: int, *argv: str) -> int:
    return main(list(argv), now_ns=lambda: at_ns)


def _records(root: Path) -> list[dict[str, object]]:
    found = []
    for path in sorted(root.glob("????-??-??/*.json")):
        body = json.loads(path.read_text())
        body["_name"] = path.name
        found.append(body)
    return found


def _seed(
    root: Path, at_ns: int, *, delivered: bool, kind: str = "canary", drill: bool = False
) -> None:
    DeliveryRecordWriter(root).write(
        event="autonomy_canary",
        ts_ns=at_ns,
        writer="canary",
        delivered=delivered,
        status_class="2xx" if delivered else "5xx",
        severity="INFO",
        attempt_kind=kind,
        drill=drill,
        site="global",
        outbox_entry="",
    )


def _line(capsys: pytest.CaptureFixture[str]) -> str:
    lines = [x for x in capsys.readouterr().out.splitlines() if x.startswith("AUTONOMY_CANARY")]
    assert lines, "the CLI printed no AUTONOMY_CANARY line"
    return lines[-1]


def test_canary_delivers_through_proof_and_prints_status(
    root: Path, webhook: _Webhook, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(_ns(9, 15, 45, 1)) == 0
    assert _line(capsys) == "AUTONOMY_CANARY delivered=1 status_class=2xx slot=1545"
    assert webhook.bodies == [
        {
            "severity": "INFO",
            "event": "autonomy_canary",
            "site": "global",
            "detail": "canary_ok",
        }
    ]
    (record,) = _records(root)
    assert record["attempt_kind"] == "canary" and record["delivered"] is True
    assert str(record["_name"]).endswith("_canary_d.json")


@pytest.mark.parametrize(
    ("hour", "minute", "slot"), [(15, 45, "1545"), (16, 30, "1630"), (16, 45, "1645")]
)
def test_canary_slots_1545_1630_1645_always_send(
    root: Path,
    webhook: _Webhook,
    capsys: pytest.CaptureFixture[str],
    hour: int,
    minute: int,
    slot: str,
) -> None:
    now = _ns(9, hour, minute, 1)
    _seed(root, now - 60 * _NS, delivered=True)  # a delivered canary one minute ago changes nothing
    assert _run(now) == 0
    assert _line(capsys) == f"AUTONOMY_CANARY delivered=1 status_class=2xx slot={slot}"
    assert len(webhook.bodies) == 1


def test_canary_retry_only_after_failure_on_other_45_firings(
    root: Path, webhook: _Webhook, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(root, _ns(9, 1, 0), delivered=True)
    _seed(root, _ns(8, 15, 45), delivered=True)
    # healthy: the 12:45 firing is not due
    assert _run(_ns(9, 12, 45, 1)) == 0
    assert _line(capsys) == "AUTONOMY_CANARY skipped=not_due"
    assert webhook.bodies == []
    # the newest canary attempt failed and nothing delivered since: retry
    _seed(root, _ns(9, 13, 0), delivered=False)
    assert _run(_ns(9, 14, 45, 1)) == 0
    assert _line(capsys) == "AUTONOMY_CANARY delivered=1 status_class=2xx slot=retry"
    assert len(webhook.bodies) == 1
    # delivered since the failure: not due again
    assert _run(_ns(9, 18, 45, 1)) == 0
    assert _line(capsys) == "AUTONOMY_CANARY skipped=not_due"
    assert len(webhook.bodies) == 1


def test_canary_retry_gate_sends_when_records_unreadable(
    root: Path, webhook: _Webhook, capsys: pytest.CaptureFixture[str]
) -> None:
    # neither record directory exists: the gate fails toward sending
    assert _run(_ns(9, 12, 45, 1)) == 0
    assert _line(capsys).endswith("slot=retry")
    assert len(webhook.bodies) == 1
    # today's directory now exists; yesterday's does not
    assert _run(_ns(9, 13, 45, 1)) == 0
    assert _line(capsys).endswith("slot=retry")
    assert len(webhook.bodies) == 2
    # an unreadable directory counts as unreadable
    _seed(root, _ns(8, 15, 45), delivered=True)
    _seed(root, _ns(9, 15, 45), delivered=True)
    today = root / "2026-10-09"
    today.chmod(0)
    try:
        if os.access(today, os.R_OK):
            pytest.skip("running with privileges that ignore directory modes")
        assert _run(_ns(9, 19, 45, 1)) == 0
        assert _line(capsys).endswith("slot=retry")
    finally:
        today.chmod(0o700)


def test_canary_retry_suppressed_in_launch_window_and_runs_at_1710(
    root: Path, webhook: _Webhook, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(root, _ns(8, 15, 45), delivered=True)
    # a failed 16:45 canary is recorded and its retry deferred to the 17:10 firing
    webhook.status = 503
    assert _run(_ns(9, 16, 45, 1)) == 0
    out = capsys.readouterr().out
    assert "AUTONOMY_CANARY delivered=0 status_class=5xx slot=1645" in out
    assert "AUTONOMY_CANARY retry_deferred until=17:10Z" in out
    sent = len(webhook.bodies)
    # an unscheduled firing inside [16:30Z, 17:10Z) never retries
    webhook.status = 204
    assert _run(_ns(9, 16, 50, 0)) == 0
    assert _line(capsys) == "AUTONOMY_CANARY retry_deferred until=17:10Z"
    assert len(webhook.bodies) == sent
    # at 17:10 the gate opens: failed newest attempt, nothing delivered since
    assert _run(_ns(9, 17, 10, 1)) == 0
    assert _line(capsys) == "AUTONOMY_CANARY delivered=1 status_class=2xx slot=1710"
    assert len(webhook.bodies) == sent + 1


def test_canary_failure_queues_critical_and_exits_0(
    root: Path, webhook: _Webhook, capsys: pytest.CaptureFixture[str]
) -> None:
    webhook.status = 500
    assert _run(_ns(9, 15, 45, 1)) == 0
    assert _line(capsys) == "AUTONOMY_CANARY delivered=0 status_class=5xx slot=1545"
    events = [b["event"] for b in webhook.bodies]
    assert events == ["autonomy_canary", "autonomy_canary_undelivered"]
    assert webhook.bodies[1]["severity"] == "CRITICAL"
    entries = [json.loads(p.read_text()) for p in (root / "outbox").rglob("*.json")]
    assert [e["event"] for e in entries] == ["autonomy_canary_undelivered"]
    kinds = sorted((r["attempt_kind"], r["delivered"]) for r in _records(root))
    assert kinds == [("alert", False), ("canary", False)]


def test_canary_runs_the_production_sink_default_once(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _Webhook()
    calls: list[int] = []

    def factory() -> TeeAlertSink:
        calls.append(1)
        return hook.make_sink()

    monkeypatch.setattr(autonomy_canary_cli, "resolve_alert_sink", factory)
    assert _run(_ns(9, 15, 45, 1)) == 0
    assert calls == [1]
    assert [client.is_closed for client in hook.clients] == [True]


def _drill_args(monkeypatch: pytest.MonkeyPatch, dates: frozenset[str]) -> None:
    monkeypatch.setattr(autonomy_canary_cli, "CANARY_SUPPRESSION_DRILL_DATES", dates)


def test_suppress_drill_only_on_preregistered_dates_and_only_1545_slot(
    root: Path,
    webhook: _Webhook,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drill_args(monkeypatch, frozenset({_DRILL_DAY}))
    _seed(root, _ns(20, 16, 45, 1), delivered=True)  # the previous day's 16:45 canary
    # not a registered date: sends normally
    _seed(root, _ns(21, 1, 0), delivered=True)
    assert _run(_ns(22, 15, 45, 1), "--suppress-drill") == 0
    assert _line(capsys).endswith("delivered=1 status_class=2xx slot=1545")
    assert len(webhook.bodies) == 1
    # registered date but the 16:30 slot: sends normally
    assert _run(_ns(21, 16, 30, 1), "--suppress-drill") == 0
    assert _line(capsys).endswith("delivered=1 status_class=2xx slot=1630")
    assert len(webhook.bodies) == 2
    # registered date, 15:45 slot: the drill records and sends nothing
    assert _run(_ns(21, 15, 45, 1), "--suppress-drill") == 0
    assert _line(capsys) == "AUTONOMY_CANARY delivered=0 status_class=not_configured slot=1545"
    assert len(webhook.bodies) == 2
    drills = [r for r in _records(root) if r["drill"] is True]
    assert len(drills) == 1
    assert drills[0]["delivered"] is False and drills[0]["status_class"] == "not_configured"
    assert drills[0]["attempt_kind"] == "canary"
    # a drill is deliberate: it queues no CRITICAL
    assert not (root / "outbox").exists() or list((root / "outbox").rglob("*.json")) == []


def test_suppress_drill_requires_previous_1645_delivered(
    root: Path,
    webhook: _Webhook,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drill_args(monkeypatch, frozenset({_DRILL_DAY}))
    _seed(root, _ns(20, 16, 45, 1), delivered=False)  # the 16:45 canary failed
    _seed(root, _ns(20, 15, 45, 1), delivered=True)  # another slot's delivery does not count
    assert _run(_ns(21, 15, 45, 1), "--suppress-drill") == 0
    out = capsys.readouterr().out
    assert "AUTONOMY_CANARY drill_skipped precondition" in out
    assert "AUTONOMY_CANARY delivered=1 status_class=2xx slot=1545" in out
    assert len(webhook.bodies) == 1


def test_suppress_drill_inert_while_no_dates_are_registered(
    root: Path, webhook: _Webhook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ruling r3 item 4: the code exists, the date list is empty, so the flag changes nothing."""
    assert pins.CANARY_SUPPRESSION_DRILL_DATES == frozenset()
    assert vars(autonomy_canary_cli)["CANARY_SUPPRESSION_DRILL_DATES"] is (
        pins.CANARY_SUPPRESSION_DRILL_DATES
    )
    _seed(root, _ns(20, 16, 45, 1), delivered=True)
    assert _run(_ns(21, 15, 45, 1), "--suppress-drill") == 0
    out = capsys.readouterr().out
    assert "AUTONOMY_CANARY drill_ignored" in out
    assert "AUTONOMY_CANARY delivered=1 status_class=2xx slot=1545" in out
    assert len(webhook.bodies) == 1
    assert [r["drill"] for r in _records(root)][-1] is False


def test_first_delivered_canary_writes_armed_marker_once(root: Path, webhook: _Webhook) -> None:
    marker = root / "armed.json"
    _run(_ns(9, 15, 45, 1))
    assert stat.S_IMODE(marker.stat().st_mode) == 0o444
    body = json.loads(marker.read_text())
    (record,) = _records(root)
    assert body == {
        "schema": "alerts_armed/v1",
        "ts_ns": body["ts_ns"],
        "record": record["_name"],
    }
    assert isinstance(body["ts_ns"], int)
    before = marker.stat().st_ino, marker.read_bytes()
    _run(_ns(9, 16, 30, 1))
    assert (marker.stat().st_ino, marker.read_bytes()) == before
    assert not list(root.glob(".*.partial"))


def test_failed_canary_and_drill_never_arm(
    root: Path, webhook: _Webhook, monkeypatch: pytest.MonkeyPatch
) -> None:
    webhook.status = 500
    _run(_ns(9, 15, 45, 1))
    assert not (root / "armed.json").exists()
    webhook.status = 204
    _drill_args(monkeypatch, frozenset({_DRILL_DAY}))
    _seed(root, _ns(20, 16, 45, 1), delivered=True)
    _run(_ns(21, 15, 45, 1), "--suppress-drill")
    assert not (root / "armed.json").exists()


def test_armed_marker_write_failure_counted_and_retried_on_next_delivery(
    root: Path, webhook: _Webhook, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = write_armed_marker
    attempts: list[int] = []

    def flaky(*args: object, **kwargs: object) -> object:
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("disk full")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(autonomy_canary_cli, "write_armed_marker", flaky)
    before = COUNTERS.journal_write_failures
    assert _run(_ns(9, 15, 45, 1)) == 0
    assert COUNTERS.journal_write_failures == before + 1
    assert not (root / "armed.json").exists()
    assert _run(_ns(9, 16, 30, 1)) == 0
    assert (root / "armed.json").is_file() and len(attempts) == 2
    assert _run(_ns(9, 16, 45, 1)) == 0
    assert len(attempts) == 2  # present: never written again


def test_canary_cli_pins_httpx_and_httpcore_loggers_to_warning(
    root: Path, webhook: _Webhook
) -> None:
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    _run(_ns(9, 15, 45, 1))
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_canary_missing_lock_is_integrity_exit_3(
    root: Path, webhook: _Webhook, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / ".canary.lock").unlink()
    assert _run(_ns(9, 15, 45, 1)) == 3
    assert "INTEGRITY lock_file_missing" in capsys.readouterr().out
    assert [b["severity"] for b in webhook.bodies] == ["CRITICAL"]


def test_canary_lock_held_elsewhere_skips_with_exit_0(
    root: Path, webhook: _Webhook, capsys: pytest.CaptureFixture[str]
) -> None:
    fd = os.open(root / ".canary.lock", os.O_RDONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert _run(_ns(9, 15, 45, 1)) == 0
    finally:
        os.close(fd)
    assert "SKIPPED lock_held" in capsys.readouterr().out
    assert webhook.bodies == []


def test_canary_source_names_no_url_and_opens_the_lock_read_only() -> None:
    source = Path(autonomy_canary_cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    strings = [
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert not [s for s in strings if "://" in s or "BREEZY_ALERT" in s]
    lock_opens: list[ast.Call] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
            and node.args
            and "lock" in ast.unparse(node.args[0]).lower()
        ):
            assert ast.unparse(node.args[1]) == "os.O_RDONLY | os.O_CLOEXEC"
            lock_opens.append(node)
    assert len(lock_opens) == 1
    assert '".canary.lock"' in source


def test_canary_payload_is_info_and_not_proof_bearing() -> None:
    payload = AlertPayload(
        severity="INFO", event="autonomy_canary", site="global", detail="canary_ok"
    )
    from breezy.runtime.alert_proof import is_proof_bearing

    assert not is_proof_bearing(payload)
