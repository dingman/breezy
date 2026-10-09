"""AMBIG-LATCH-RESUME Phase A, T46: the supervisor decode marker (plan r6 2.11, delta R7).

The supervisor writes ``<store>.supervisor_decode`` at start, naming its own
pid + ``/proc`` start ticks and the ``RetirementReason`` members it can decode.
A node (Phase B) retires ``RESOLVER_NO_ID_NO_FILL`` only if
``supervisor_admits_retirement_reason`` is True. T46(v) (node_config wiring)
is Phase B code and lives in ``test_ambig_no_id_resolver.py`` as T46b.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

import breezy.runtime.trade_supervisor as ts
from breezy.runtime.build_sha import BUILD_REVISION_ENV_VAR
from breezy.runtime.health import AlertPayload
from breezy.runtime.stop_intent_marker import process_start_ticks
from breezy.runtime.submit_intent import RetirementReason
from breezy.runtime.supervisor_decode_marker import (
    read_supervisor_decode_marker,
    supervisor_admits_retirement_reason,
    supervisor_decode_marker_path,
    write_supervisor_decode_marker,
)
from breezy.runtime.trade_supervisor_core import SUPERVISOR_ARGV_TOKEN

NEW_REASON = "RESOLVER_NO_ID_NO_FILL"
REVISION = "0123456789ab"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "state" / "store.sqlite3"
    path.parent.mkdir(parents=True)
    return path


def _write(store_path: Path, **overrides: object) -> None:
    kwargs: dict[str, object] = {"revision": REVISION}
    kwargs.update(overrides)
    write_supervisor_decode_marker(store_path, **kwargs)  # type: ignore[arg-type]


def _marker_payload(store_path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(supervisor_decode_marker_path(store_path).read_text())
    return payload


def _rewrite(store_path: Path, **changes: object) -> None:
    payload = _marker_payload(store_path)
    payload.update(changes)
    supervisor_decode_marker_path(store_path).write_text(json.dumps(payload))


class TestMarkerWriteAndAdmit:
    def test_marker_sits_beside_the_store_and_is_not_a_store_key(self, store_path: Path) -> None:
        marker = supervisor_decode_marker_path(store_path)
        assert marker.parent == store_path.parent
        assert marker.name == store_path.name + ".supervisor_decode"
        _write(store_path)
        assert marker.is_file()
        assert not store_path.exists()  # the SQLite store was never created or opened

    def test_write_then_admit_is_true_for_the_live_test_process(self, store_path: Path) -> None:
        _write(store_path)
        payload = _marker_payload(store_path)
        assert payload["v"] == 1
        assert payload["pid"] == os.getpid()
        assert payload["start_ticks"] == process_start_ticks(os.getpid())
        assert payload["revision"] == REVISION
        assert payload["retirement_reasons"] == sorted(m.value for m in RetirementReason)
        assert NEW_REASON in payload["retirement_reasons"]
        assert supervisor_admits_retirement_reason(store_path, NEW_REASON) is True
        marker = read_supervisor_decode_marker(store_path)
        assert marker is not None
        assert marker.pid == os.getpid()
        assert marker.revision == REVISION

    def test_write_overwrites_a_previous_incarnations_marker(self, store_path: Path) -> None:
        _write(store_path, revision="aaaaaaaaaaaa")
        _write(store_path, revision="bbbbbbbbbbbb")
        assert _marker_payload(store_path)["revision"] == "bbbbbbbbbbbb"

    @pytest.mark.parametrize(
        "case",
        [
            "absent",
            "bad_json",
            "not_an_object",
            "wrong_version",
            "missing_reason",
            "reasons_not_a_list",
            "reasons_with_non_str",
            "pid_not_int",
            "pid_is_bool",
            "start_ticks_not_int",
            "revision_not_str",
        ],
    )
    def test_admit_is_false_for_an_absent_or_malformed_marker(
        self, store_path: Path, case: str
    ) -> None:
        marker = supervisor_decode_marker_path(store_path)
        if case != "absent":
            _write(store_path)
        changes: dict[str, object] = {
            "wrong_version": {"v": 2},
            "missing_reason": {
                "retirement_reasons": [m.value for m in RetirementReason if m.value != NEW_REASON]
            },
            "reasons_not_a_list": {"retirement_reasons": NEW_REASON},
            "reasons_with_non_str": {"retirement_reasons": [NEW_REASON, 7]},
            "pid_not_int": {"pid": "123"},
            "pid_is_bool": {"pid": True},
            "start_ticks_not_int": {"start_ticks": "9"},
            "revision_not_str": {"revision": 5},
        }.get(case, {})  # type: ignore[assignment]
        if case == "bad_json":
            marker.write_text("{not json")
        elif case == "not_an_object":
            marker.write_text(json.dumps([1, 2, 3]))
        elif changes:
            _rewrite(store_path, **changes)
        assert supervisor_admits_retirement_reason(store_path, NEW_REASON) is False

    def test_admit_is_false_for_a_dead_pid(self, store_path: Path) -> None:
        _write(store_path)
        assert (
            supervisor_admits_retirement_reason(
                store_path, NEW_REASON, process_start_ticks=lambda _pid: None
            )
            is False
        )

    def test_admit_is_false_for_a_reused_pid_with_different_start_ticks(
        self, store_path: Path
    ) -> None:
        _write(store_path)
        real = process_start_ticks(os.getpid())
        assert real is not None
        assert (
            supervisor_admits_retirement_reason(
                store_path, NEW_REASON, process_start_ticks=lambda _pid: real + 1
            )
            is False
        )
        assert (
            supervisor_admits_retirement_reason(
                store_path, NEW_REASON, process_start_ticks=lambda _pid: real
            )
            is True
        )

    def test_admit_is_false_for_a_reason_the_supervisor_cannot_decode(
        self, store_path: Path
    ) -> None:
        _write(store_path)
        assert supervisor_admits_retirement_reason(store_path, "NOT_A_MEMBER") is False

    def test_write_fails_closed_without_writing_when_the_start_ticks_are_unreadable(
        self, store_path: Path
    ) -> None:
        with pytest.raises(OSError):
            _write(store_path, process_start_ticks=lambda _pid: None)
        assert not supervisor_decode_marker_path(store_path).exists()


class TestMarkerWriteIsAtomic:
    def test_a_failed_replace_leaves_the_prior_marker_intact_and_no_tmp_file(
        self, store_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(store_path, revision="aaaaaaaaaaaa")
        before = supervisor_decode_marker_path(store_path).read_bytes()

        def _boom(_src: object, _dst: object) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr("breezy.runtime.supervisor_decode_marker.os.replace", _boom)
        with pytest.raises(OSError):
            _write(store_path, revision="bbbbbbbbbbbb")
        assert supervisor_decode_marker_path(store_path).read_bytes() == before
        assert sorted(p.name for p in store_path.parent.iterdir()) == [
            store_path.name + ".supervisor_decode"
        ]
        assert supervisor_admits_retirement_reason(store_path, NEW_REASON) is True


class TestMainWritesTheMarker:
    """T46(iv): ``main`` writes the marker right after ``supervisor_started``;
    a write failure is logged and never stops the supervisor."""

    def _rig(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, list[bool]]:
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True)
        monkeypatch.setenv("POLYMARKET_US_EXEC_STATE_DB", str(store_path))
        monkeypatch.setenv(BUILD_REVISION_ENV_VAR, "deadbeef123")
        monkeypatch.setattr(ts, "configure_supervisor_logging", lambda _log_dir: None)
        seen: list[bool] = []

        def _fake_run_forever(**_kwargs: object) -> None:
            seen.append(supervisor_decode_marker_path(store_path).exists())

        monkeypatch.setattr(ts, "_run_forever", _fake_run_forever)
        return store_path, seen

    def test_marker_is_written_after_supervisor_started_and_before_the_loop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        store_path, seen = self._rig(monkeypatch, tmp_path)
        with caplog.at_level(logging.INFO, logger="breezy.runtime.trade_supervisor"):
            assert ts.main([SUPERVISOR_ARGV_TOKEN], log_dir=tmp_path / "logs") == ts.EXIT_OK
        assert seen == [True]  # present by the time the daily loop starts
        marker = read_supervisor_decode_marker(store_path)
        assert marker is not None
        assert marker.pid == os.getpid()
        assert marker.revision == "deadbeef123"  # the SAME revision supervisor_started logged
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            m.startswith("supervisor_started") and "revision=deadbeef123" in m for m in messages
        )

    def test_a_marker_write_failure_is_logged_and_does_not_stop_the_supervisor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        store_path, seen = self._rig(monkeypatch, tmp_path)

        def _raising_writer(*_a: object, **_kw: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(ts, "write_supervisor_decode_marker", _raising_writer)
        with caplog.at_level(logging.INFO, logger="breezy.runtime.trade_supervisor"):
            assert ts.main([SUPERVISOR_ARGV_TOKEN], log_dir=tmp_path / "logs") == ts.EXIT_OK
        assert seen == [False]  # the daily loop still started, with no marker
        messages = [r.getMessage() for r in caplog.records]
        failed = [m for m in messages if m.startswith("supervisor_decode_marker_write_failed")]
        assert failed == ["supervisor_decode_marker_write_failed error_type=OSError"]
        assert "disk full" not in " ".join(messages)  # type name only, never the message
        assert supervisor_admits_retirement_reason(store_path, NEW_REASON) is False


class TestMarkerWriteFailureIsLoudAndLeavesNoStaleMarker:
    """Review fix 2: a failed write alerts WARN (type name only) and removes any
    pre-existing marker so a stale one cannot admit a reason."""

    def test_failure_emits_a_warn_and_unlinks_the_stale_marker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True)
        write_supervisor_decode_marker(store_path, revision="aaaaaaaaaaaa")  # stale, live pid
        assert supervisor_admits_retirement_reason(store_path, NEW_REASON) is True
        monkeypatch.setenv("POLYMARKET_US_EXEC_STATE_DB", str(store_path))
        monkeypatch.setattr(ts, "configure_supervisor_logging", lambda _d: None)
        monkeypatch.setattr(ts, "_run_forever", lambda **_kw: None)

        class _Sink:
            def __init__(self) -> None:
                self.payloads: list[AlertPayload] = []

            def emit(self, payload: AlertPayload) -> None:
                self.payloads.append(payload)

        sink = _Sink()
        monkeypatch.setattr(ts, "resolve_alert_sink", lambda *a, **k: sink)

        def _raising(*_a: object, **_kw: object) -> None:
            raise OSError("disk full secret")

        monkeypatch.setattr(ts, "write_supervisor_decode_marker", _raising)
        with caplog.at_level(logging.INFO, logger="breezy.runtime.trade_supervisor"):
            assert ts.main([SUPERVISOR_ARGV_TOKEN], log_dir=tmp_path / "logs") == ts.EXIT_OK
        assert not supervisor_decode_marker_path(store_path).exists()
        assert supervisor_admits_retirement_reason(store_path, NEW_REASON) is False
        [payload] = sink.payloads
        assert (payload.severity, payload.event) == (
            "WARN",
            "TRADE_SUPERVISOR_DECODE_MARKER_WRITE_FAILED",
        )
        assert "secret" not in repr(payload) + " ".join(r.getMessage() for r in caplog.records)

    def test_discard_is_best_effort_and_idempotent(self, tmp_path: Path) -> None:
        from breezy.runtime.supervisor_decode_marker import discard_supervisor_decode_marker

        store_path = tmp_path / "s.sqlite3"
        discard_supervisor_decode_marker(store_path)  # absent: no raise
        write_supervisor_decode_marker(store_path, revision=REVISION)
        discard_supervisor_decode_marker(store_path)
        assert not supervisor_decode_marker_path(store_path).exists()
