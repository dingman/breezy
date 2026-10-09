"""AMBIG-LATCH-RESUME Phase A check script (U2): scripts/ops/ambig_latch_phase_a_check.py.

The checks are driven through injected ``Probes`` (no systemctl, no live log,
no network). Non-vacuity: every check has a FAIL case, and an absent marker
(the pre-merge supervisor) fails checks 1 and 2.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts" / "ops").as_posix())

import ambig_latch_phase_a_check as chk  # type: ignore[import-not-found]

from breezy.runtime.stop_intent_marker import process_start_ticks
from breezy.runtime.supervisor_decode_marker import (
    supervisor_decode_marker_path,
    write_supervisor_decode_marker,
)

PHASE_A_SHA = "a" * 40
REVISION = "0123456789ab"
NODE_PID = 4242
MAIN_PID = os.getpid()  # the marker is written for this live test process


def _log(*, revision: str = REVISION, after: tuple[str, ...] = ()) -> str:
    started = (
        "2026-10-09T17:30:00Z INFO breezy.runtime.trade_supervisor supervisor_started "
        f"stop_prior_utc=16:40:00 log_dir=/x revision={revision}"
    )
    old = (
        "2026-10-08T01:00:00Z INFO breezy.runtime.trade_supervisor supervisor_started revision=old"
    )
    return "\n".join((old, started, *after)) + "\n"


def _adopted(pid: int = NODE_PID) -> str:
    return (
        "2026-10-09T17:30:00Z INFO breezy.runtime.trade_supervisor "
        f"permit_watch_adopted_live_node pid={pid}"
    )


def _raise_mainpid_absent() -> int:
    raise chk.ProbeFailed("mainpid_absent")


def _probes(**overrides: Any) -> chk.Probes:
    base: dict[str, Any] = {
        "main_pid": lambda: MAIN_PID,
        "main_environ_names_revision_override": lambda _pid: False,
        "process_start_ticks": process_start_ticks,
        "supervisor_log_text": lambda: _log(after=(_adopted(),)),
        "is_ancestor": lambda _sha, _rev: True,
        "lock_holder_pid": lambda: NODE_PID,
    }
    base.update(overrides)
    return chk.Probes(**base)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "state" / "store.sqlite3"
    path.parent.mkdir(parents=True)
    write_supervisor_decode_marker(path, revision=REVISION)
    return path


def _run(
    store_path: Path | None,
    probes: chk.Probes,
    *,
    node: int | None = NODE_PID,
    sha: str = PHASE_A_SHA,
) -> tuple[bool, bool, bool]:
    a, b, c = _run_full(store_path, probes, node=node, sha=sha)
    return a[0], b[0], c[0]


def _run_full(
    store_path: Path | None,
    probes: chk.Probes,
    *,
    node: int | None = NODE_PID,
    sha: str = PHASE_A_SHA,
) -> tuple[tuple[bool, str], tuple[bool, str], tuple[bool, str]]:
    results: tuple[tuple[bool, str], tuple[bool, str], tuple[bool, str]] = chk.run_checks(
        store_path=store_path, phase_a_sha=sha, pre_restart_node_pid=node, probes=probes
    )
    return results


def test_all_three_checks_pass_for_a_fully_consistent_restart(store_path: Path) -> None:
    assert _run(store_path, _probes()) == (True, True, True)


def test_a_pre_merge_supervisor_with_no_marker_fails_checks_one_and_two(tmp_path: Path) -> None:
    bare = tmp_path / "state" / "store.sqlite3"
    bare.parent.mkdir(parents=True)
    assert not supervisor_decode_marker_path(bare).exists()
    c1, c2, _c3 = _run(bare, _probes())
    assert (c1, c2) == (False, False)


def test_a_revision_that_does_not_descend_from_phase_a_fails_check_one(store_path: Path) -> None:
    probes = _probes(is_ancestor=lambda _sha, _rev: False)
    assert _run(store_path, probes) == (False, True, True)


def test_ancestry_alone_decides_and_receives_the_marker_revision(store_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    def _record(sha: str, rev: str) -> bool:
        seen.append((sha, rev))
        return True

    _run(store_path, _probes(is_ancestor=_record))
    assert seen == [(PHASE_A_SHA, REVISION)]


@pytest.mark.parametrize(
    "mutation",
    ["env_override", "log_revision_differs", "marker_pid_not_mainpid", "no_mainpid", "no_started"],
)
def test_check_one_fails_closed_on_each_inconsistency(store_path: Path, mutation: str) -> None:
    probes = {
        "env_override": _probes(main_environ_names_revision_override=lambda _p: True),
        "log_revision_differs": _probes(supervisor_log_text=lambda: _log(revision="ffffffffffff")),
        "marker_pid_not_mainpid": _probes(main_pid=lambda: MAIN_PID + 1),
        "no_mainpid": _probes(main_pid=_raise_mainpid_absent),
        "no_started": _probes(supervisor_log_text=lambda: "nothing here\n"),
    }[mutation]
    assert _run(store_path, probes)[0] is False


@pytest.mark.parametrize("fallback", ["unknown", "0.1.0", "deadbee"[:6], "XYZXYZXYZ"])
def test_a_non_sha_revision_fallback_fails_check_one(tmp_path: Path, fallback: str) -> None:
    path = tmp_path / "state" / "store.sqlite3"
    path.parent.mkdir(parents=True)
    write_supervisor_decode_marker(path, revision=fallback)
    probes = _probes(supervisor_log_text=lambda: _log(revision=fallback, after=(_adopted(),)))
    assert _run(path, probes)[0] is False


@pytest.mark.parametrize("bad_sha", ["", "xyz", "A" * 40, "a" * 6, "a" * 41, "--help", "a;b"])
def test_an_invalid_phase_a_sha_fails_check_one(store_path: Path, bad_sha: str) -> None:
    assert _run(store_path, _probes(), sha=bad_sha)[0] is False


def test_check_two_fails_when_the_marker_pid_is_not_the_mainpid(store_path: Path) -> None:
    assert _run(store_path, _probes(main_pid=lambda: MAIN_PID + 1))[1] is False


def test_check_two_fails_for_a_marker_that_does_not_list_the_new_member(store_path: Path) -> None:
    import json

    marker = supervisor_decode_marker_path(store_path)
    payload = json.loads(marker.read_text())
    payload["retirement_reasons"] = [
        r for r in payload["retirement_reasons"] if r != chk.NEW_REASON
    ]
    marker.write_text(json.dumps(payload))
    assert _run(store_path, _probes())[1] is False


def test_check_two_fails_when_the_synthetic_round_trip_fails(
    store_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chk, "_synthetic_retired_round_trips", lambda: False)
    assert _run(store_path, _probes())[1] is False


@pytest.mark.parametrize(
    "case", ["adopted_other_pid", "holder_differs", "no_adoption_line", "adoption_before_start"]
)
def test_check_three_fails_closed(store_path: Path, case: str) -> None:
    if case == "adopted_other_pid":
        probes = _probes(supervisor_log_text=lambda: _log(after=(_adopted(NODE_PID + 1),)))
    elif case == "holder_differs":
        probes = _probes(lock_holder_pid=lambda: NODE_PID + 1)
    elif case == "no_adoption_line":
        probes = _probes(supervisor_log_text=lambda: _log())
    else:
        # An adoption line from BEFORE the newest supervisor_started does not count.
        probes = _probes(supervisor_log_text=lambda: _adopted() + "\n" + _log())
    assert _run(store_path, probes)[2] is False


def test_node_down_path_passes_only_on_adoption_or_a_spawn_after_the_new_start(
    store_path: Path,
) -> None:
    launched = "2026-10-09T17:31:00Z INFO breezy.runtime.trade_supervisor launched pid=777"
    adopted = (
        "2026-10-09T17:31:00Z INFO breezy.runtime.trade_supervisor launch_adopted_live_node pid=777"
    )
    for line, expected in ((launched, True), (adopted, True), (_adopted(), False)):
        probes = _probes(supervisor_log_text=lambda line=line: _log(after=(line,)))
        assert _run(store_path, probes, node=None)[2] is expected
    assert _run(store_path, _probes(supervisor_log_text=lambda: _log()), node=None)[2] is False


def test_no_store_path_fails_every_store_dependent_check() -> None:
    assert _run(None, _probes()) == (False, False, False)


def test_main_prints_only_pass_fail_lines_and_exits_zero_iff_all_pass(
    store_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(chk, "_build_probes", lambda _s, _l: _probes())
    argv = [PHASE_A_SHA, str(NODE_PID), "--store-path", str(store_path)]
    assert chk.main(argv) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "check1_descends_from_phase_a PASS",
        "check2_decode_marker PASS",
        "check3_same_pid_adoption PASS",
        "RESULT PASS",
    ]
    for secret in (REVISION, str(NODE_PID), str(MAIN_PID), str(store_path)):
        assert secret not in out
    monkeypatch.setattr(chk, "_build_probes", lambda _s, _l: _probes(is_ancestor=lambda *_: False))
    assert chk.main(argv) == 1
    assert "RESULT FAIL" in capsys.readouterr().out


def test_node_pid_argument_accepts_none_and_rejects_garbage() -> None:
    assert chk._parse_node_pid("none") is None
    assert chk._parse_node_pid("1234") == 1234
    for bad in ("abc", "0", "-5", ""):
        with pytest.raises(argparse.ArgumentTypeError):
            chk._parse_node_pid(bad)


def test_node_pid_zero_is_invalid_input_with_exit_two(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        chk.main([PHASE_A_SHA, "0"])
    assert excinfo.value.code == 2
    capsys.readouterr()


def test_check_one_requires_the_marker_start_ticks_to_match_mainpid(store_path: Path) -> None:
    real = process_start_ticks(MAIN_PID)
    assert real is not None
    reused = _run_full(store_path, _probes(process_start_ticks=lambda _p: real + 1))
    assert reused[0] == (False, "marker_start_ticks_mismatch")
    unknown = _run_full(store_path, _probes(process_start_ticks=lambda _p: None))
    assert unknown[0] == (False, "marker_start_ticks_mismatch")


def _boom(exc: BaseException) -> Any:
    def _raise(*_a: object, **_kw: object) -> Any:
        raise exc

    return _raise


@pytest.mark.parametrize(
    ("probe", "exc", "expected_cause"),
    [
        ("main_pid", chk.ProbeFailed("systemctl_timeout"), "systemctl_timeout"),
        ("main_pid", FileNotFoundError("systemctl"), "probe_error_FileNotFoundError"),
        (
            "main_environ_names_revision_override",
            chk.ProbeFailed("environ_unreadable"),
            "environ_unreadable",
        ),
        (
            "main_environ_names_revision_override",
            PermissionError("x"),
            "probe_error_PermissionError",
        ),
        ("is_ancestor", chk.ProbeFailed("git_timeout"), "git_timeout"),
        ("is_ancestor", RuntimeError("secret detail"), "probe_error_RuntimeError"),
        ("supervisor_log_text", chk.ProbeFailed("log_unreadable"), "log_unreadable"),
    ],
)
def test_every_probe_failure_is_a_fail_with_a_fixed_cause_never_a_traceback_or_pass(
    store_path: Path, probe: str, exc: BaseException, expected_cause: str
) -> None:
    results = _run_full(store_path, _probes(**{probe: _boom(exc)}))
    causes = [cause for ok, cause in results if not ok]
    assert expected_cause in causes
    assert all("secret" not in cause for _ok, cause in results)


def test_an_unreadable_supervisor_log_fails_checks_one_and_three_naming_the_cause(
    store_path: Path, tmp_path: Path
) -> None:
    probes = chk._build_probes(store_path, tmp_path / "no_such_log_dir")
    with pytest.raises(chk.ProbeFailed) as excinfo:
        probes.supervisor_log_text()
    assert excinfo.value.cause == "log_unreadable"


def test_systemctl_probe_failures_map_to_fixed_causes(monkeypatch: pytest.MonkeyPatch) -> None:
    def _run_raising(exc: BaseException) -> Any:
        def _r(*_a: object, **_kw: object) -> Any:
            raise exc

        return _r

    for exc, cause in (
        (FileNotFoundError("systemctl"), "systemctl_missing"),
        (subprocess.TimeoutExpired("systemctl", 1), "systemctl_timeout"),
        (PermissionError("x"), "systemctl_failed"),
    ):
        monkeypatch.setattr(chk.subprocess, "run", _run_raising(exc))
        with pytest.raises(chk.ProbeFailed) as excinfo:
            chk._systemctl_main_pid()
        assert excinfo.value.cause == cause

    def _fake(stdout: str, code: int = 0) -> Any:
        return lambda *_a, **_kw: subprocess.CompletedProcess([], code, stdout=stdout)

    for stdout, code, cause in (
        ("", 0, "systemctl_empty"),
        ("MainPID=0\n", 0, "mainpid_absent"),
        ("garbage\n", 0, "mainpid_absent"),
        ("MainPID=5\n", 1, "systemctl_failed"),
    ):
        monkeypatch.setattr(chk.subprocess, "run", _fake(stdout, code))
        with pytest.raises(chk.ProbeFailed) as excinfo:
            chk._systemctl_main_pid()
        assert excinfo.value.cause == cause
    monkeypatch.setattr(chk.subprocess, "run", _fake("MainPID=77\n"))
    assert chk._systemctl_main_pid() == 77


def test_proc_environ_probe_reads_the_process_environment_for_the_key_only(
    tmp_path: Path,
) -> None:
    script = "import os,sys,time; sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(30)"
    env = {"PATH": os.environ.get("PATH", ""), "BREEZY_BUILD_REVISION": "feedface"}
    clean = {"PATH": os.environ.get("PATH", ""), "OTHER": "1"}
    for environ, expected in ((env, True), (clean, False)):
        child = subprocess.Popen(
            [sys.executable, "-c", script], env=environ, stdout=subprocess.PIPE, text=True
        )
        try:
            assert child.stdout is not None
            child.stdout.readline()
            assert chk._proc_environ_names_revision_override(child.pid) is expected
        finally:
            child.terminate()
            child.wait()
    with pytest.raises(chk.ProbeFailed) as excinfo:
        chk._proc_environ_names_revision_override(2**30)
    assert excinfo.value.cause == "environ_unreadable"


def test_main_prints_a_one_line_cause_for_each_failing_check(
    store_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        chk,
        "_build_probes",
        lambda _s, _l: _probes(main_pid=_boom(chk.ProbeFailed("systemctl_timeout"))),
    )
    assert chk.main([PHASE_A_SHA, str(NODE_PID), "--store-path", str(store_path)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "check1_descends_from_phase_a FAIL systemctl_timeout"
    assert lines[1] == "check2_decode_marker FAIL systemctl_timeout"
    assert lines[-1] == "RESULT FAIL"


def test_the_real_ancestry_probe_is_git_merge_base_is_ancestor() -> None:
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert chk._is_ancestor(head, head) is True
    # An unknown object is a git error (exit 128): a FAIL with a cause, not "False".
    with pytest.raises(chk.ProbeFailed) as excinfo:
        chk._is_ancestor("0" * 40, head)
    assert excinfo.value.cause == "git_error"
    parent = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD~1"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert chk._is_ancestor(head, parent) is False  # a child is not an ancestor of its parent


def test_script_source_is_read_only_no_store_write_signal_or_network() -> None:
    import ast

    tree = ast.parse((REPO_ROOT / "scripts" / "ops" / "ambig_latch_phase_a_check.py").read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not {
        m
        for m in imported
        if m.split(".")[0] in {"socket", "http", "urllib", "httpx", "requests", "signal"}
    }
    assert "breezy.runtime.sqlite_store" not in imported
    called = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert not called & {"kill", "killpg", "set", "write_text", "write_bytes", "unlink", "replace"}
