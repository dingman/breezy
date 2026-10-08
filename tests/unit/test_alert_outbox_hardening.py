"""AUT-6 WP1 fix round 1 (B1-B6, C1, C3): outbox robustness and no symlink following."""

from __future__ import annotations

import errno
import json
import logging
import os
import time
from pathlib import Path
from typing import Final

import httpx
import pytest

from breezy.registry.health_model import AlertPayload
from breezy.runtime import alert_outbox
from breezy.runtime.alert_delivery import (
    AlertOutbox,
    DeliveryRecordWriter,
    deliver_with_proof,
    drain_outbox,
)
from breezy.runtime.health import LoggingAlertSink, TeeAlertSink, WebhookAlertSink

_URL: Final = "https://alerts.example.test/hook"
_NS: Final = 1_000_000_000


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


def _payload(event: str = "CAPTURE_PUBLISH_FAILED") -> AlertPayload:
    return AlertPayload(severity="CRITICAL", event=event, site="t", detail="closed")


def _tee(handler: object) -> TeeAlertSink:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return TeeAlertSink(LoggingAlertSink(), WebhookAlertSink(_URL, client=client))


def _ok(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(204)


def _old(outbox: AlertOutbox, event: str = "OLD") -> Path:
    return outbox.write_entry(
        _payload(event), writer="health", drill=False, ts_ns=time.time_ns() - 120 * _NS
    )


# -- B1 ---------------------------------------------------------------------------------------


def test_complete_tolerates_a_claim_reclaimed_during_the_post(root: Path) -> None:
    outbox = AlertOutbox(root)
    claimed = outbox.claim(_old(outbox), "a")
    assert claimed is not None

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        other = root / "outbox" / "claimed" / "b"
        other.mkdir(parents=True, exist_ok=True)
        os.rename(claimed, other / claimed.name)  # a stale-claim reclaim by drainer b
        return httpx.Response(204)

    proof = deliver_with_proof(
        _tee(handler),
        _payload("OLD"),
        writer="a",
        records=DeliveryRecordWriter(root),
        attempt_kind="drain",
        outbox=outbox,
        claimed=claimed,
    )
    assert proof.delivered is True


# -- B2 ---------------------------------------------------------------------------------------


def test_publish_unlinks_its_partial_file_when_the_write_fails(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _enospc(fd: int, data: bytes) -> int:
        del fd, data
        raise OSError(errno.ENOSPC, "no space")

    monkeypatch.setattr(os, "write", _enospc)
    with pytest.raises(OSError, match="no space"):
        AlertOutbox(root).write_entry(_payload(), writer="health", drill=False, ts_ns=7)
    monkeypatch.undo()
    assert list((root / "outbox").glob(".*")) == []
    assert list((root / "outbox").glob("*")) == []


def test_publish_writes_the_whole_body_across_short_writes(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write

    def _short(fd: int, data: bytes) -> int:
        return real_write(fd, bytes(data[:3]))

    monkeypatch.setattr(os, "write", _short)
    entry = AlertOutbox(root).write_entry(_payload(), writer="health", drill=False, ts_ns=8)
    monkeypatch.undo()
    assert json.loads(entry.read_text(encoding="utf-8"))["event"] == "CAPTURE_PUBLISH_FAILED"


# -- B3 ---------------------------------------------------------------------------------------


def test_malformed_claim_is_logged_by_type_and_renamed_to_bad(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    outbox = AlertOutbox(root)
    entry = outbox.write_entry(_payload("BAD"), writer="health", drill=False, ts_ns=1)
    entry.write_text("{not json", encoding="utf-8")
    good = _old(outbox, "GOOD")
    caplog.set_level(logging.ERROR)
    summary = drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_tee(_ok),
        records=DeliveryRecordWriter(root),
        min_age_s=60,
    )
    assert summary.delivered == 1 and summary.failures == 1
    bad = list((root / "outbox" / "claimed" / "redeliver").glob("*.bad"))
    assert [p.name for p in bad] == [entry.name + ".bad"]
    assert any("alert_outbox_entry_unreadable" in m for m in caplog.messages)
    assert "{not json" not in caplog.text
    assert not good.exists()
    assert outbox.occupancy() == 0


def test_a_claim_that_raises_oserror_is_counted_and_the_drain_continues(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox = AlertOutbox(root)
    first = _old(outbox, "FIRST")
    _old(outbox, "SECOND")
    real_claim = AlertOutbox.claim

    def _claim(self: AlertOutbox, entry: Path, drainer: str) -> Path | None:
        if entry.name == first.name:
            raise OSError(errno.EIO, "io")
        return real_claim(self, entry, drainer)

    monkeypatch.setattr(AlertOutbox, "claim", _claim)
    summary = drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_tee(_ok),
        records=DeliveryRecordWriter(root),
        min_age_s=60,
    )
    assert summary.delivered == 1 and summary.failures == 1


# -- B4 / B6 ----------------------------------------------------------------------------------


def test_claim_fsyncs_the_source_directory_too(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outbox = AlertOutbox(root)
    entry = _old(outbox)
    synced: list[Path] = []
    real = alert_outbox._fsync_dir

    def _recording(directory: Path) -> None:
        synced.append(directory)
        real(directory)

    monkeypatch.setattr(alert_outbox, "_fsync_dir", _recording)
    assert outbox.claim(entry, "a") is not None
    assert root / "outbox" in synced and root / "outbox" / "claimed" / "a" in synced


def test_claim_never_overwrites_an_existing_destination(root: Path) -> None:
    outbox = AlertOutbox(root)
    entry = _old(outbox)
    held = root / "outbox" / "claimed" / "a"
    held.mkdir(parents=True)
    (held / entry.name).write_text("OTHER", encoding="utf-8")
    assert outbox.claim(entry, "a") is None
    assert (held / entry.name).read_text(encoding="utf-8") == "OTHER"
    assert entry.is_file()


# -- B5 ---------------------------------------------------------------------------------------


def test_claim_failure_after_a_durable_write_reuses_the_entry_and_does_not_send(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        posts.append(1)
        return httpx.Response(204)

    def _boom(self: AlertOutbox, entry: Path, drainer: str) -> Path | None:
        del self, entry, drainer
        raise OSError(errno.EIO, "claim failed")

    monkeypatch.setattr(AlertOutbox, "claim", _boom)
    before = alert_outbox_failures()
    proof = deliver_with_proof(
        _tee(handler),
        _payload(),
        writer="health",
        records=DeliveryRecordWriter(root),
        attempt_kind="alert",
        outbox=AlertOutbox(root),
    )
    assert proof.delivered is False and posts == []
    assert len(list((root / "outbox").glob("*.json"))) == 1  # the durable entry stays for a drainer
    assert alert_outbox_failures() == before  # not an outbox WRITE failure


def alert_outbox_failures() -> int:
    from breezy.runtime.alert_delivery import COUNTERS

    return COUNTERS.outbox_write_failures


# -- C1 ---------------------------------------------------------------------------------------


def test_symlinked_entries_are_never_followed(root: Path) -> None:
    outbox = AlertOutbox(root)
    secret = root / "secret.json"
    secret.write_text(
        json.dumps({"severity": "CRITICAL", "event": "LEAK", "site": "s", "detail": "TOPSECRET"}),
        encoding="utf-8",
    )
    old = time.time_ns() - 120 * _NS
    out = root / "outbox"
    out.mkdir(parents=True, exist_ok=True)
    link = out / f"{old}_LEAK.json"
    link.symlink_to(secret)
    held = out / "claimed" / "other"
    held.mkdir(parents=True)
    stale = held / f"{old}_LEAK2.json"
    stale.symlink_to(secret)
    assert outbox.claim(link, "redeliver") is None
    assert outbox.reclaim_stale("redeliver", now=time.time() + 3600) == []
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.decode())
        return httpx.Response(204)

    summary = drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_tee(handler),
        records=DeliveryRecordWriter(root),
        min_age_s=60,
    )
    assert summary.attempted == 0 and bodies == []
    assert link.is_symlink() and secret.read_text(encoding="utf-8")


def test_utime_does_not_follow_symlinks(root: Path) -> None:
    outbox = AlertOutbox(root)
    target = root / "t.json"
    target.write_text("{}", encoding="utf-8")
    os.utime(target, (1000, 1000))
    link = root / "outbox" / "claimed" / "a" / "1_X.json"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    assert outbox.restamp(link) in (True, False)
    assert os.stat(target).st_mtime == 1000


# -- C3 ---------------------------------------------------------------------------------------


def test_an_oversized_entry_is_rejected_and_long_fields_are_truncated(root: Path) -> None:
    outbox = AlertOutbox(root)
    huge = outbox.write_entry(_payload("HUGE"), writer="health", drill=False, ts_ns=1)
    huge.write_text(
        json.dumps({"severity": "CRITICAL", "event": "HUGE", "site": "s", "detail": "x" * 70_000}),
        encoding="utf-8",
    )
    long = outbox.write_entry(_payload("LONG"), writer="health", drill=False, ts_ns=2)
    long.write_text(
        json.dumps({"severity": "CRITICAL", "event": "LONG", "site": "s", "detail": "y" * 900}),
        encoding="utf-8",
    )
    bodies: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode()))
        return httpx.Response(204)

    summary = drain_outbox(
        drainer="redeliver",
        outbox=outbox,
        sink=_tee(handler),
        records=DeliveryRecordWriter(root),
        min_age_s=60,
        now_ns=lambda: 1_000 * _NS,
    )
    assert summary.delivered == 1 and summary.failures == 1
    assert [b["event"] for b in bodies] == ["LONG"]
    assert 0 < len(bodies[0]["detail"]) <= 512  # AlertPayload itself caps detail further
