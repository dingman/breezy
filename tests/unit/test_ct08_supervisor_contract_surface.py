"""CT-8: supervisor contract surface.

Pins, through the real parsers and writers (no doubles of the unit under
test):

* boot-retry budget ``8`` and gap ``15`` minutes
* log-marker strings parsed as API (``trade_supervisor_core`` markers)
* the permit-ceiling env-var literal, ``app.trade._resolve_permit_expiry_ceiling_ns``,
  and ``_do_midday_watch`` injecting that one key into the child env
* subscribe-marker class names
* ``spawn_node`` argv/env byte-pin (recording ``Popen``; no process, no
  ``preexec_fn`` call)
* FQ halt clearing (L-48): real ``set_family_halt`` -> ``_do_self_check``
  FAIL -> real ``clear_family_halt`` -> PASS

The set/clear CLIs refuse a manifest whose composition kind is not
``continuous_rung_hold``. The checked-in ``pm_us_crh_fq_v1`` manifest is
``forecast_quantile_ladder``, so the fixture copies it and changes only
that field. The family id stays ``pm_us_crh_fq_v1``, which is the halt key
the supervisor reads.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final, cast

import pytest

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.app.trade import _resolve_permit_expiry_ceiling_ns
from breezy.runtime.health import AlertPayload
from breezy.runtime.settings import SENDING_FAMILY_ID_VAR
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.trade_supervisor import (
    _SPAWNED_CHILDREN,
    _SUPERVISOR_SPAWNED,
    IncrementalLogReader,
    SupervisorPorts,
    _child_preexec,
    _do_midday_watch,
    _do_self_check,
    read_continuous_family_store_state,
    resolve_sending_family_id,
    sending_family_active,
    spawn_node,
)
from breezy.runtime.trade_supervisor_core import (
    BOOT_RETRY_MAX_ATTEMPTS,
    BOOT_RETRY_MIN_GAP,
    BOOT_RETRY_READINESS_TIMEOUT,
    COMPOSITION_KIND_SUBSCRIBED_MARKERS,
    CONTINUOUS_STARTUP_EVIDENCE_KEY,
    FATAL_EXEC_CLIENT_FAULT_MARKER,
    FATAL_MARKET_DATA_FAULT_MARKER,
    PERMIT_EXPIRY_CEILING_NS_ENV_VAR,
    PERMIT_ISSUED_MARKER,
    PERMIT_NOT_ISSUED_MARKER,
    PERMIT_NOT_REQUESTED_MARKER,
    TRADING_NODE_FAILED_MARKER,
    ZERO_INSTRUMENTS_REFUSAL_PREFIX,
    ZERO_INSTRUMENTS_REFUSAL_SUFFIX,
    AlertDetail,
    RelaunchCause,
    classify_exit1_cause,
    decide_boot_retry,
    initial_scheduler_state,
    latch_log_facts,
    launch_time_ns,
    parse_permit_expiry_ns,
    record_first_boot_permit_seen,
    record_readiness_observed,
    strategy_subscribed_in,
    zero_instruments_refusal_in,
)
from breezy.strategy.current_rung_hold.clear_family_halt_cli import (
    EXIT_OK as CLEAR_EXIT_OK,
)
from breezy.strategy.current_rung_hold.clear_family_halt_cli import (
    clear_family_halt,
)
from breezy.strategy.current_rung_hold.set_family_halt_cli import (
    EXIT_OK as SET_EXIT_OK,
)
from breezy.strategy.current_rung_hold.set_family_halt_cli import (
    set_family_halt,
)
from tests.unit.test_trade_supervisor import (
    _DAY,
    _FAR_FUTURE_EXPIRES_AT_NS,
    _TRADING_NODE_FAILED_LINE,
    _RecordingAlertSink,
    _utc,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_FQ_FAMILY_ID: Final[str] = "pm_us_crh_fq_v1"
_CEILING_LITERAL: Final[str] = "BREEZY_PERMIT_EXPIRY_CEILING_NS"
_SECRET_MARKERS: Final[tuple[str, ...]] = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "PRIVATE",
)
_HALT_REASON: Final[str] = "CT-8 L-48 characterization halt clearing path"


@pytest.fixture(autouse=True)
def _clear_retained_children() -> Iterator[None]:
    _SPAWNED_CHILDREN.clear()
    _SUPERVISOR_SPAWNED.clear()
    yield
    _SPAWNED_CHILDREN.clear()
    _SUPERVISOR_SPAWNED.clear()


def test_boot_retry_constants_are_eight_attempts_and_fifteen_minutes() -> None:
    assert BOOT_RETRY_MAX_ATTEMPTS == 8
    assert BOOT_RETRY_MIN_GAP.total_seconds() == 15 * 60
    assert BOOT_RETRY_READINESS_TIMEOUT.total_seconds() == 15 * 60
    now = _utc(18, 0)
    assert (
        decide_boot_retry(now=now, attempts_so_far=7, last_attempt_at=None).should_relaunch
        is True
    )
    assert (
        decide_boot_retry(now=now, attempts_so_far=8, last_attempt_at=None).should_relaunch
        is False
    )
    too_soon = now - BOOT_RETRY_MIN_GAP + dt.timedelta(seconds=1)
    assert (
        decide_boot_retry(now=now, attempts_so_far=1, last_attempt_at=too_soon).should_relaunch
        is False
    )
    assert (
        decide_boot_retry(
            now=now, attempts_so_far=1, last_attempt_at=now - BOOT_RETRY_MIN_GAP
        ).should_relaunch
        is True
    )


def test_log_marker_strings_are_parsed_as_api() -> None:
    """Literals, not only the imported names: renaming a marker value goes red."""
    assert PERMIT_ISSUED_MARKER == "live-trading permit issued issued_at_ns="
    assert PERMIT_NOT_ISSUED_MARKER == "order submission permit not issued"
    assert TRADING_NODE_FAILED_MARKER == "trading node failed"
    assert ZERO_INSTRUMENTS_REFUSAL_PREFIX == (
        "current_rung_hold: resolved 0 instruments for"
    )
    assert ZERO_INSTRUMENTS_REFUSAL_SUFFIX == "; refusing to start"
    assert PERMIT_NOT_REQUESTED_MARKER == (
        "order submission permit not minted: orders not requested"
    )
    assert FATAL_MARKET_DATA_FAULT_MARKER == "FATAL market-data fault"
    assert FATAL_EXEC_CLIENT_FAULT_MARKER == "FATAL execution-client fault"

    permit_line = (
        "live-trading permit issued issued_at_ns=1 expires_at_ns=99 ttl_s=1\n"
    )
    assert parse_permit_expiry_ns(permit_line) == 99
    assert classify_exit1_cause("order submission permit not issued") is (
        RelaunchCause.DETERMINISTIC
    )
    assert classify_exit1_cause("trading node failed") is RelaunchCause.TRANSIENT
    assert classify_exit1_cause("FATAL market-data fault") is RelaunchCause.TRANSIENT
    assert classify_exit1_cause("FATAL execution-client fault") is RelaunchCause.TRANSIENT
    refusal = (
        "current_rung_hold: resolved 0 instruments for STATION; refusing to start"
    )
    assert zero_instruments_refusal_in(refusal) is True
    assert classify_exit1_cause(refusal) is RelaunchCause.TRANSIENT
    split = (
        "current_rung_hold: resolved 0 instruments for STATION\n; refusing to start"
    )
    assert zero_instruments_refusal_in(split) is False

    state = latch_log_facts(
        initial_scheduler_state(_DAY),
        _utc(17, 10),
        "order submission permit not minted: orders not requested\n" + refusal + "\n",
    )
    assert state.orders_not_requested_seen is True
    assert state.boot_zero_instruments_seen is True


def test_subscribe_marker_class_names() -> None:
    assert COMPOSITION_KIND_SUBSCRIBED_MARKERS == {
        "current_rung_hold": "CurrentRungHoldStrategy subscribed",
        "continuous_rung_hold": "ContinuousRungHoldStrategy subscribed",
        "forecast_ladder": "ForecastLadderStrategy subscribed",
        "forecast_quantile_ladder": "ForecastQuantileLadderStrategy subscribed",
    }
    assert strategy_subscribed_in("ForecastQuantileLadderStrategy subscribed") is True
    assert strategy_subscribed_in("not a subscribe line") is False


def test_permit_ceiling_literal_is_what_trade_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    assert PERMIT_EXPIRY_CEILING_NS_ENV_VAR == _CEILING_LITERAL
    monkeypatch.setenv(_CEILING_LITERAL, "424242")
    assert _resolve_permit_expiry_ceiling_ns() == 424242
    monkeypatch.delenv(_CEILING_LITERAL, raising=False)
    assert _resolve_permit_expiry_ceiling_ns() is None


def test_midday_watch_injects_only_the_ceiling_key(tmp_path: Path) -> None:
    """Asserts the one injected key. Never compares the whole child env."""
    node_log = tmp_path / "node.log"
    node_log.write_text(_TRADING_NODE_FAILED_LINE, encoding="utf-8")
    ceilings: list[str] = []

    def _capture(
        *,
        node_bin: Path,
        repo_root: Path,
        env: Mapping[str, str],
        log_path: Path,
    ) -> subprocess.Popen[bytes]:
        del node_bin, repo_root, log_path
        ceilings.append(env[_CEILING_LITERAL])
        return cast(subprocess.Popen[bytes], _IdlePopen())

    state = record_readiness_observed(initial_scheduler_state(_DAY), _utc(17, 10))
    state = record_first_boot_permit_seen(state, _utc(17, 10), 424242)
    try:
        _do_midday_watch(
            ports=SupervisorPorts(
                find_node_pid=lambda: None,
                resolve_intent_lock_holder=lambda _path: None,
                intent_lock_free=lambda _path: True,
                count_intent_lock_holders=lambda _path: 0,
                terminate_after_recheck=lambda *_a, **_k: None,
                process_alive=lambda _pid: False,
                probe_open_intent_state=lambda *_a, **_k: False,
                spawn=_capture,
                read_log_new=lambda path: path.read_text(encoding="utf-8"),
                alert_sink=_RecordingAlertSink(),
            ),
            state=state,
            now=_utc(20, 0),
            tracked_pid=1001,
            node_log=node_log,
            store_path=tmp_path / "state" / "store.sqlite3",
            repo_root=tmp_path,
            node_bin=tmp_path / "node_bin",
            log_dir=tmp_path / "logs",
        )
    finally:
        _SPAWNED_CHILDREN.clear()
        _SUPERVISOR_SPAWNED.clear()
    assert ceilings == ["424242"]


class _IdlePopen:
    pid = 9101

    def poll(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


def _normalize_env_value(key: str, value: str) -> str:
    upper = key.upper()
    if any(marker in upper for marker in _SECRET_MARKERS):
        return "<secret>"
    if value.startswith("/"):
        return "<path>"
    return value


def test_spawn_node_argv_and_env_byte_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Recording Popen does not exec and does not call ``preexec_fn``."""
    captured: list[tuple[list[str], dict[str, object]]] = []

    class _RecordingPopen:
        def __init__(self, args: str | list[str], **kwargs: object) -> None:
            argv = [args] if isinstance(args, str) else list(args)
            captured.append((argv, dict(kwargs)))
            self.pid = 0

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

    monkeypatch.setattr(
        "breezy.runtime.trade_supervisor.subprocess.Popen", _RecordingPopen
    )
    node_bin = tmp_path / "breezy-trade"
    repo_root = tmp_path / "repo"
    supplied = {
        "PLAIN": "visible-value",
        "A_TOKEN": "not-a-real-token",
        "SOME_PATH": "/var/empty/ct08-not-real",
        _CEILING_LITERAL: "424242",
    }
    spawn_node(
        node_bin=node_bin,
        repo_root=repo_root,
        env=supplied,
        log_path=tmp_path / "logs" / "node.log",
    )
    assert len(captured) == 1
    argv, kwargs = captured[0]
    assert argv == [str(node_bin)]
    assert kwargs["cwd"] == str(repo_root)
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.STDOUT
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True
    assert kwargs["preexec_fn"] is _child_preexec
    assert getattr(kwargs["stdout"], "closed", None) is True
    raw_env = kwargs["env"]
    assert raw_env is not supplied
    assert isinstance(raw_env, dict)
    env_map: dict[str, str] = {}
    for key, value in raw_env.items():
        assert isinstance(key, str)
        assert isinstance(value, str)
        env_map[key] = value
    assert set(env_map) == set(supplied)
    normalized = {key: _normalize_env_value(key, env_map[key]) for key in supplied}
    assert normalized == {
        "PLAIN": "visible-value",
        "A_TOKEN": "<secret>",
        "SOME_PATH": "<path>",
        _CEILING_LITERAL: "424242",
    }


def _fq_manifest_for_halt_writer(families_dir: Path) -> None:
    """Copy the real FQ manifest and flip only ``composition_kind``.

    ``resolve_continuous_family_arg`` refuses ``forecast_quantile_ladder``,
    so the real writer body would never run against the checked-in file.
    """
    source = _REPO_ROOT / "deploy" / "families" / f"{_FQ_FAMILY_ID}.json"
    loaded: object = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError("FQ manifest is not a JSON object")
    payload: dict[str, object] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise TypeError("FQ manifest key is not a string")
        payload[key] = value
    payload["composition_kind"] = "continuous_rung_hold"
    families_dir.mkdir(parents=True)
    (families_dir / f"{_FQ_FAMILY_ID}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _flat_positions() -> Mapping[str, Any]:
    return {"positions": {}, "eof": True}


class _HaltSink:
    def emit(self, payload: AlertPayload) -> None:
        del payload


def test_fq_halt_set_fails_self_check_then_clear_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store_path = tmp_path / "state.sqlite3"
    evidence = {
        "ts_ns": launch_time_ns(_DAY),
        "eof_complete": True,
        "position_read_refused": False,
    }
    with SqliteStateStore(store_path) as store:
        store.set(CONTINUOUS_STARTUP_EVIDENCE_KEY, json.dumps(evidence).encode("utf-8"))
    families = tmp_path / "families"
    _fq_manifest_for_halt_writer(families)
    evidence_path = tmp_path / "evidence.txt"
    evidence_path.write_text("ct-8 halt evidence\n", encoding="utf-8")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    env = {EXEC_STATE_DB_ENV_VAR: str(store_path)}
    argv = [
        "--family-id",
        _FQ_FAMILY_ID,
        "--families-dir",
        str(families),
        "--reason",
        _HALT_REASON,
        "--evidence-path",
        str(evidence_path),
    ]
    err = io.StringIO()
    code = set_family_halt(
        argv,
        env=env,
        stdout=io.StringIO(),
        stderr=err,
        positions_reader=_flat_positions,
        alert_sink=_HaltSink(),
        proc_root=proc_root,
    )
    assert code == SET_EXIT_OK, err.getvalue()

    log_path = tmp_path / "logs" / "node.log"
    log_path.parent.mkdir(parents=True)
    fq_marker = COMPOSITION_KIND_SUBSCRIBED_MARKERS["forecast_quantile_ladder"]
    # Padding longer than IncrementalLogReader's carry so the second read
    # no longer contains the permit or subscribe lines. PASS then depends
    # on the latched state returned by the first call.
    log_path.write_text(
        f"{PERMIT_ISSUED_MARKER}1 expires_at_ns={_FAR_FUTURE_EXPIRES_AT_NS} ttl_s=1\n"
        f"{fq_marker}\n" + ("x" * 300) + "\n",
        encoding="utf-8",
    )
    reader = IncrementalLogReader()
    sink = _RecordingAlertSink()
    ports = SupervisorPorts(
        find_node_pid=lambda: 4242,
        resolve_intent_lock_holder=lambda _path: 4242,
        intent_lock_free=lambda _path: False,
        count_intent_lock_holders=lambda _path: 1,
        terminate_after_recheck=lambda *_a, **_k: None,
        process_alive=lambda pid: pid == 4242,
        probe_open_intent_state=lambda *_a, **_k: False,
        spawn=_idle_spawn,
        read_log_new=reader.read_new,
        alert_sink=sink,
        continuous_family_active=sending_family_active,
        resolve_sending_family_id=resolve_sending_family_id,
        read_continuous_family_store_state=read_continuous_family_store_state,
    )
    monkeypatch.setenv(SENDING_FAMILY_ID_VAR, _FQ_FAMILY_ID)
    supervisor_log = logging.getLogger("breezy.runtime.trade_supervisor")
    monkeypatch.setattr(supervisor_log, "propagate", True)
    with caplog.at_level(logging.INFO, logger="breezy.runtime.trade_supervisor"):
        _tracked, _node_log, state = _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=store_path,
            log_dir=log_path.parent,
            tracked_pid=4242,
            node_log=log_path,
            state=initial_scheduler_state(_DAY),
        )
        assert state is not None
        assert state.strategy_subscribed_seen is True
        assert state.permit_issued_seen_expires_at_ns == _FAR_FUTURE_EXPIRES_AT_NS
        clear_err = io.StringIO()
        clear_code = clear_family_halt(
            argv,
            env=env,
            stdout=io.StringIO(),
            stderr=clear_err,
        )
        assert clear_code == CLEAR_EXIT_OK, clear_err.getvalue()
        _do_self_check(
            ports=ports,
            now=_utc(17, 6),
            store_path=store_path,
            log_dir=log_path.parent,
            tracked_pid=4242,
            node_log=log_path,
            state=state,
        )
    fail_details = [
        payload.detail
        for payload in sink.payloads
        if payload.detail == AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_FAMILY_HALTED.value
    ]
    assert fail_details == [AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_FAMILY_HALTED.value]
    assert "result=FAIL_CONTINUOUS_FAMILY_HALTED" in caplog.text
    fail_at = caplog.text.index("result=FAIL_CONTINUOUS_FAMILY_HALTED")
    assert "result=PASS " in caplog.text[fail_at:]


def _idle_spawn(**_kwargs: object) -> subprocess.Popen[bytes]:
    raise AssertionError("self-check must not spawn")
