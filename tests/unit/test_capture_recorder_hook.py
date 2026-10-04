"""AUT-1 WP3 step 1 (X-4, EM1): the evidence-only recorder stop hook.

The hook writes a write-once stall record and the trading day's ``recorder_watchdog/v1`` count
on ``SERVICE_RESULT=watchdog``; it is a no-op otherwise, sends no alert, and exits 0 on every
failure path after logging ``RECORDER_HOOK_FAILED``.
"""

from __future__ import annotations

import ast
import fcntl
import json
import os
from pathlib import Path

import pytest

import breezy.runtime.capture_recorder_hook_cli as hook
from breezy.adapters.polymarket_us.recorder_watchdog import RECORDER_WATCHDOG_STORM_KILLS
from tests.support.recorder_watchdog import NS, utc_ns

INVOCATION = "0cf7c4b59b06405e83e7097ebc3d8dce"
OTHER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
WATCHDOG_ENV = {
    "SERVICE_RESULT": "watchdog",
    "INVOCATION_ID": INVOCATION,
    "EXIT_CODE": "killed",
    "EXIT_STATUS": "TERM",
}


@pytest.fixture(name="root")
def _root(tmp_path: Path) -> Path:
    (tmp_path / "evidence" / "capture" / "stall").mkdir(parents=True)
    (tmp_path / "health" / "recorder_watchdog").mkdir(parents=True)
    return tmp_path


def _health(root: Path) -> dict[str, object]:
    path = root / "health" / "recorder_watchdog" / "polymarket_us.json"
    parsed: dict[str, object] = json.loads(path.read_text())
    return parsed


def _records(root: Path) -> list[Path]:
    return sorted((root / "evidence" / "capture" / "stall").glob("*/*_recorder_watchdog.json"))


def test_watchdog_result_writes_stall_record_with_invocation_id_and_state(root: Path) -> None:
    now = utc_ns(10, 0, 0, day=5)
    assert hook.run_hook(WATCHDOG_ENV, data_root=root, now_ns=now) == 0
    (record_path,) = _records(root)
    assert record_path.parent.name == "2026-10-05"
    assert record_path.name == f"{now}_{INVOCATION}_recorder_watchdog.json"
    record = json.loads(record_path.read_text())
    assert record["unit"] == "breezy-quote-tape.service"
    assert record["cause"] == "watchdog" and record["result"] == "watchdog"
    assert record["invocation_id"] == INVOCATION
    assert (record["exit_code"], record["exit_status"]) == ("killed", "TERM")
    assert record["detected_ns"] == now
    assert len(record["observation_sha256"]) == 64
    assert (record_path.stat().st_mode & 0o777) == 0o600
    health = _health(root)
    assert health == {
        "schema": "recorder_watchdog/v1",
        "watchdog_kills_trading_day": 1,
        "last_watchdog_kill_ns": now,
        "last_invocation_id": INVOCATION,
        "trading_date": "2026-10-04",
    }


def test_record_is_write_once(root: Path) -> None:
    now = utc_ns(10, 0, 0, day=5)
    hook.run_hook(WATCHDOG_ENV, data_root=root, now_ns=now)
    (record_path,) = _records(root)
    original = record_path.read_bytes()
    hook.run_hook({**WATCHDOG_ENV, "EXIT_CODE": "changed"}, data_root=root, now_ns=now)
    assert record_path.read_bytes() == original
    assert _health(root)["watchdog_kills_trading_day"] == 1


def test_success_result_is_a_no_op(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The 09:00Z rotate's clean try-restart ends ``Result=success``."""
    for result in ("success", "exit-code", "timeout", "oom-kill"):
        env = {**WATCHDOG_ENV, "SERVICE_RESULT": result}
        assert hook.run_hook(env, data_root=root, now_ns=utc_ns(9, 0, 5)) == 0
    assert _records(root) == []
    assert not (root / "health" / "recorder_watchdog" / "polymarket_us.json").exists()
    assert capsys.readouterr().err == ""


def test_trading_day_boundary_is_1645z(root: Path) -> None:
    before = utc_ns(16, 44, 59, day=5)
    after = utc_ns(16, 45, 0, day=5)
    assert hook.trading_day_bounds_ns(before)[0] == "2026-10-04"
    assert hook.trading_day_bounds_ns(after)[0] == "2026-10-05"
    assert hook.trading_day_bounds_ns(after)[1] == after
    assert hook.trading_day_bounds_ns(after)[2] - after == 86_400 * NS
    # Two kills straddling the boundary belong to two trading days; the count restarts.
    hook.run_hook({**WATCHDOG_ENV, "INVOCATION_ID": INVOCATION}, data_root=root, now_ns=before)
    hook.run_hook({**WATCHDOG_ENV, "INVOCATION_ID": OTHER}, data_root=root, now_ns=after)
    health = _health(root)
    assert health["watchdog_kills_trading_day"] == 1
    assert health["trading_date"] == "2026-10-05" and health["last_invocation_id"] == OTHER


def test_kills_in_one_trading_day_are_counted_across_the_utc_midnight(root: Path) -> None:
    ids = ["1" * 32, "2" * 32, "3" * 32]
    times = [utc_ns(18, 0, 0, day=4), utc_ns(23, 59, 0, day=4), utc_ns(1, 0, 0, day=5)]
    for invocation, now in zip(ids, times, strict=True):
        hook.run_hook({**WATCHDOG_ENV, "INVOCATION_ID": invocation}, data_root=root, now_ns=now)
    health = _health(root)
    assert health["watchdog_kills_trading_day"] == 3 == RECORDER_WATCHDOG_STORM_KILLS
    assert health["last_invocation_id"] == ids[-1] and health["last_watchdog_kill_ns"] == times[-1]
    assert health["trading_date"] == "2026-10-04"


def test_hook_takes_its_own_lock(root: Path) -> None:
    hook.run_hook(WATCHDOG_ENV, data_root=root, now_ns=utc_ns(10, 0, 0, day=5))
    lock = root / "health" / "recorder_watchdog" / "hook.lock"
    assert lock.is_file() and (lock.stat().st_mode & 0o777) == 0o600
    # While another holder has it, the hook waits and then gives up (next test); once free it works.
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with pytest.raises(hook.HookError, match="lock_timeout"):
            hook.record_watchdog_kill(
                WATCHDOG_ENV,
                data_root=root,
                now_ns=utc_ns(11, 0, 0, day=5),
                lock_timeout_s=0.0,
                sleep=lambda s: None,
            )
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    # The attempt that timed out on the lock still wrote its write-once stall record (the
    # evidence); the next hook run's count includes it.
    assert len(_records(root)) == 2
    hook.run_hook(
        {**WATCHDOG_ENV, "INVOCATION_ID": OTHER}, data_root=root, now_ns=utc_ns(11, 30, 0, day=5)
    )
    assert _health(root)["watchdog_kills_trading_day"] == 3


def test_lock_timeout_logs_recorder_hook_failed_and_exits_zero(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = root / "health" / "recorder_watchdog" / "hook.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        code = hook.run_hook(
            WATCHDOG_ENV,
            data_root=root,
            now_ns=utc_ns(10, 0, 0, day=5),
            lock_timeout_s=0.1,
            sleep=lambda s: None,
        )
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert code == 0
    assert (
        f"RECORDER_HOOK_FAILED cause=lock_timeout invocation_id={INVOCATION}"
        in capsys.readouterr().err
    )
    assert not (root / "health" / "recorder_watchdog" / "polymarket_us.json").exists()


def test_missing_invocation_id_logs_recorder_hook_failed_and_exits_zero(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {"SERVICE_RESULT": "watchdog"}
    assert hook.run_hook(env, data_root=root, now_ns=utc_ns(10, 0, 0, day=5)) == 0
    err = capsys.readouterr().err
    assert "RECORDER_HOOK_FAILED cause=missing_invocation_id invocation_id=unknown" in err
    assert _records(root) == []
    # A malformed id is refused too: it would become a path component.
    bad = {"SERVICE_RESULT": "watchdog", "INVOCATION_ID": "../../etc/passwd"}
    assert hook.run_hook(bad, data_root=root, now_ns=utc_ns(10, 0, 0, day=5)) == 0
    assert "cause=invalid_invocation_id" in capsys.readouterr().err
    assert _records(root) == []
    # And a missing SERVICE_RESULT is a logged failure, not a silent no-op.
    assert hook.run_hook({"INVOCATION_ID": INVOCATION}, data_root=root) == 0
    assert "cause=missing_service_result" in capsys.readouterr().err


def test_write_error_logs_recorder_hook_failed_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The bound stall directory does not exist: the wrapper never mkdirs, and neither does the hook.
    code = hook.run_hook(WATCHDOG_ENV, data_root=tmp_path, now_ns=utc_ns(10, 0, 0, day=5))
    assert code == 0
    assert (
        f"RECORDER_HOOK_FAILED cause=write_error_FileNotFoundError invocation_id={INVOCATION}"
        in capsys.readouterr().err
    )


def test_unexpected_exception_still_exits_zero(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("surprise")

    monkeypatch.setattr(hook, "record_watchdog_kill", boom)
    assert hook.run_hook(WATCHDOG_ENV, data_root=root) == 0
    assert "cause=unexpected_RuntimeError" in capsys.readouterr().err


def test_hook_module_imports_no_alert_sender() -> None:
    tree = ast.parse(Path(hook.__file__).read_text())
    imported: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Name | ast.Attribute):
            names.add(node.id if isinstance(node, ast.Name) else node.attr)
    forbidden_names = {
        "deliver_with_proof",
        "emit_alert",
        "RECORDER_WATCHDOG_KILL",
        "RECORDER_WATCHDOG_STORM",
        "AlertPayload",
    }
    assert not names & forbidden_names
    assert not [m for m in imported if "alert" in m or m.startswith("breezy.runtime.health")]
    assert not [m for m in imported if m.startswith("breezy.adapters")]
    assert "RECORDER_WATCHDOG_KILL" not in Path(hook.__file__).read_text()
