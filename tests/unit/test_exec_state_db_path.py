"""RED-first tests for the leaf exec state-DB resolver + node-env pre-flight
(R8/REVISE-1/REVISE-2/REVISE-4/REVISE-5).

``resolve_store_path``/``ExecStateDbNotConfiguredError`` moved here verbatim
from ``tests/unit/test_trade_supervisor.py`` (previously :743-751) plus new
validation and sentinel coverage; ``node_store_path_check`` and the
``--check`` ``main`` are new.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.exec_state_db_path import (
    ExecStateDbNotConfiguredError,
    main,
    node_store_path_check,
    resolve_store_path,
)

_SENTINEL = "sentinel-value-should-never-leak"


def _write_process(
    proc_root: Path,
    pid: int,
    argv: list[str],
    environ: dict[str, str] | None = None,
) -> Path:
    """Write a fake ``/proc/<pid>/{cmdline,environ}`` pair, kernel-shaped.

    ``cmdline`` carries the kernel's trailing NUL after every element
    (including the last); ``environ`` does the same for each ``KEY=value``
    entry.
    """
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True)
    cmdline = b"".join(part.encode("utf-8") + b"\0" for part in argv)
    (pid_dir / "cmdline").write_bytes(cmdline)
    if environ is not None:
        env_bytes = b"".join(f"{k}={v}".encode() + b"\0" for k, v in environ.items())
        (pid_dir / "environ").write_bytes(env_bytes)
    return pid_dir


# ---------------------------------------------------------------------------
# resolve_store_path -- moved (verbatim behaviour) + new validation + sentinel
# ---------------------------------------------------------------------------


def test_resolve_store_path_requires_the_env_var() -> None:
    with pytest.raises(ExecStateDbNotConfiguredError):
        resolve_store_path({})


def test_resolve_store_path_reads_the_configured_path() -> None:
    path = resolve_store_path({EXEC_STATE_DB_ENV_VAR: "/tmp/x/store.sqlite3"})
    assert path == Path("/tmp/x/store.sqlite3")


def test_resolve_store_path_refuses_a_relative_path() -> None:
    with pytest.raises(ExecStateDbNotConfiguredError):
        resolve_store_path({EXEC_STATE_DB_ENV_VAR: "relative/store.sqlite3"})


def test_resolve_store_path_refuses_a_dotdot_segment() -> None:
    with pytest.raises(ExecStateDbNotConfiguredError):
        resolve_store_path({EXEC_STATE_DB_ENV_VAR: "/abs/../store.sqlite3"})


def test_resolve_store_path_unset_message_names_the_var_not_a_value() -> None:
    with pytest.raises(ExecStateDbNotConfiguredError) as exc_info:
        resolve_store_path({})
    assert EXEC_STATE_DB_ENV_VAR in str(exc_info.value)


@pytest.mark.parametrize(
    "raw",
    [
        f"relative/{_SENTINEL}.sqlite3",
        f"/abs/../{_SENTINEL}.sqlite3",
    ],
)
def test_resolve_store_path_error_messages_never_contain_the_value(raw: str) -> None:
    with pytest.raises(ExecStateDbNotConfiguredError) as exc_info:
        resolve_store_path({EXEC_STATE_DB_ENV_VAR: raw})
    assert _SENTINEL not in str(exc_info.value)


# ---------------------------------------------------------------------------
# node_store_path_check -- the four enum outcomes
# ---------------------------------------------------------------------------


def test_node_store_path_check_match(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    expected = tmp_path / "store.sqlite3"
    _write_process(
        proc_root,
        111,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(expected), "OTHER": "x"},
    )

    assert node_store_path_check(expected, proc_root=proc_root) == "MATCH"


def test_node_store_path_check_mismatch_on_a_different_path(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    expected = tmp_path / "store.sqlite3"
    other = tmp_path / "other-store.sqlite3"
    _write_process(
        proc_root,
        111,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(other)},
    )

    assert node_store_path_check(expected, proc_root=proc_root) == "MISMATCH"


def test_node_store_path_check_no_node_when_only_the_supervisor_is_present(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    expected = tmp_path / "store.sqlite3"
    _write_process(
        proc_root,
        222,
        ["breezy-trade-supervisor", "breezy-trade-supervisor-daily"],
    )

    assert node_store_path_check(expected, proc_root=proc_root) == "NO_NODE"


def test_node_store_path_check_discovery_failed_when_proc_root_is_missing(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "does-not-exist"
    expected = tmp_path / "store.sqlite3"

    assert node_store_path_check(expected, proc_root=proc_root) == "DISCOVERY_FAILED"


def test_node_store_path_check_two_disagreeing_nodes_is_mismatch(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    expected = tmp_path / "store.sqlite3"
    _write_process(
        proc_root,
        111,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(expected)},
    )
    _write_process(
        proc_root,
        112,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(tmp_path / "other.sqlite3")},
    )

    assert node_store_path_check(expected, proc_root=proc_root) == "MISMATCH"


def test_node_store_path_check_unreadable_environ_is_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc_root = tmp_path / "proc"
    expected = tmp_path / "store.sqlite3"
    pid_dir = _write_process(
        proc_root,
        111,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(expected)},
    )

    real_read_bytes = Path.read_bytes

    def _fake_read_bytes(self: Path) -> bytes:
        if self == pid_dir / "environ":
            raise PermissionError("simulated: environ unreadable")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _fake_read_bytes)

    assert node_store_path_check(expected, proc_root=proc_root) == "MISMATCH"


def test_node_store_path_check_skips_a_vanished_pid(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    expected = tmp_path / "store.sqlite3"
    # A pid directory with no cmdline file at all -- the read raises
    # FileNotFoundError, exactly the shape a dir removed mid-scan produces.
    vanished_dir = proc_root / "999"
    vanished_dir.mkdir(parents=True)
    _write_process(
        proc_root,
        111,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(expected)},
    )

    assert node_store_path_check(expected, proc_root=proc_root) == "MATCH"


def test_node_store_path_check_never_leaks_the_compared_value(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    proc_root = tmp_path / "proc"
    expected = tmp_path / f"{_SENTINEL}.sqlite3"
    _write_process(
        proc_root,
        111,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(tmp_path / f"other-{_SENTINEL}.sqlite3")},
    )

    with caplog.at_level("DEBUG"):
        result = node_store_path_check(expected, proc_root=proc_root)

    assert result == "MISMATCH"
    assert _SENTINEL not in caplog.text
    captured = capsys.readouterr()
    assert _SENTINEL not in captured.out
    assert _SENTINEL not in captured.err


# ---------------------------------------------------------------------------
# main() -- the ``--check`` contract (REVISE-5)
# ---------------------------------------------------------------------------


def test_main_check_prints_one_token_and_exits_0_on_match(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    store = tmp_path / "store.sqlite3"
    _write_process(
        proc_root,
        111,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(store)},
    )

    exit_code = main(
        ["--check"],
        environ={EXEC_STATE_DB_ENV_VAR: str(store)},
        proc_root=proc_root,
    )

    assert exit_code == 0


@pytest.mark.parametrize(
    ("fake_result", "expected_exit"),
    [
        ("MATCH", 0),
        ("NO_NODE", 0),
        ("MISMATCH", 3),
        ("DISCOVERY_FAILED", 3),
    ],
)
def test_main_check_maps_each_enum_to_its_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_result: str,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        "breezy.runtime.exec_state_db_path.node_store_path_check",
        lambda expected_path, *, proc_root=Path("/proc"): fake_result,
    )

    exit_code = main(["--check"], environ={EXEC_STATE_DB_ENV_VAR: "/abs/store.sqlite3"})

    captured = capsys.readouterr()
    assert captured.out.strip() == fake_result
    assert captured.err == ""
    assert exit_code == expected_exit


def test_main_check_exits_2_on_unset_var_with_a_value_free_stderr_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--check"], environ={})

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert EXEC_STATE_DB_ENV_VAR in captured.err


def test_main_check_never_leaks_the_compared_value_for_any_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = f"/abs/{_SENTINEL}/store.sqlite3"
    for fake_result in ("MATCH", "MISMATCH", "NO_NODE", "DISCOVERY_FAILED"):
        monkeypatch.setattr(
            "breezy.runtime.exec_state_db_path.node_store_path_check",
            lambda expected_path, *, proc_root=Path("/proc"), _r=fake_result: _r,
        )
        exit_code = main(["--check"], environ={EXEC_STATE_DB_ENV_VAR: store})
        captured = capsys.readouterr()
        assert _SENTINEL not in captured.out
        assert _SENTINEL not in captured.err
        assert exit_code in (0, 3)
