"""S5 plan E2-1(ii)/E3-6/E4-3: the operator CLI that terminates the NO-side
bounded first-order containment window by writing
`NO_SIDE_POSITION_SHAPE_CAPTURED_KEY`. Mirrors
`test_clear_submit_intent_cli.py`'s structure and safety exactly."""

from __future__ import annotations

import io
import json
from pathlib import Path

from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,
)
from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.mark_no_side_position_captured_cli import (
    EXIT_NOT_PENDING,
    EXIT_OK,
    EXIT_REFUSED,
    OPERATOR_ACK_ENV_VAR,
    main,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch

_RULING_PATH = "docs/evidence/RULING_no_side_position_shape_2026-09-30.md"
_RULING_SHA = "a" * 40


def _env(store_path: Path, *, ack: bool = True) -> dict[str, str]:
    env = {EXEC_STATE_DB_ENV_VAR: str(store_path)}
    if ack:
        env[OPERATOR_ACK_ENV_VAR] = "1"
    return env


def _argv() -> list[str]:
    return ["--yes", "--ruling-path", _RULING_PATH, "--ruling-sha", _RULING_SHA]


def _write_first_order_key(store_path: Path) -> None:
    store = SqliteStateStore(store_path)
    store.set(NO_SIDE_FIRST_LIVE_ORDER_KEY, b'{"instrumentId":"x"}')
    store.close()


def test_refuses_while_the_node_holds_the_lock(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    store = SqliteStateStore(store_path)
    _write_first_order_key(store_path)
    stderr = io.StringIO()
    with open_submit_intent_latch(store, store_path):
        code = main(_argv(), env=_env(store_path), stdout=io.StringIO(), stderr=stderr)
    store.close()
    assert code == EXIT_REFUSED
    assert "holds the lock" in stderr.getvalue()


def test_refuses_without_yes_and_the_operator_ack(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _write_first_order_key(store_path)
    stderr = io.StringIO()
    code = main(
        ["--ruling-path", _RULING_PATH, "--ruling-sha", _RULING_SHA],
        env=_env(store_path, ack=True),
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == EXIT_REFUSED
    assert "--yes" in stderr.getvalue()

    stderr2 = io.StringIO()
    code2 = main(
        _argv(),
        env=_env(store_path, ack=False),
        stdout=io.StringIO(),
        stderr=stderr2,
    )
    assert code2 == EXIT_REFUSED
    assert "ack" in stderr2.getvalue()


def test_refuses_when_the_first_order_key_is_absent(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()
    stdout = io.StringIO()
    code = main(_argv(), env=_env(store_path), stdout=stdout, stderr=io.StringIO())
    assert code == EXIT_NOT_PENDING
    assert "nothing to terminate" in stdout.getvalue()
    store = SqliteStateStore(store_path)
    assert store.get(NO_SIDE_POSITION_SHAPE_CAPTURED_KEY) is None
    store.close()


def test_writes_the_captured_key_with_ruling_path_and_sha_payload(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _write_first_order_key(store_path)
    stdout = io.StringIO()
    code = main(_argv(), env=_env(store_path), stdout=stdout, stderr=io.StringIO())
    assert code == EXIT_OK
    assert "captured" in stdout.getvalue()
    store = SqliteStateStore(store_path)
    raw = store.get(NO_SIDE_POSITION_SHAPE_CAPTURED_KEY)
    store.close()
    assert raw is not None
    payload = json.loads(raw)
    assert payload["rulingPath"] == _RULING_PATH
    assert payload["rulingSha"] == _RULING_SHA
    assert isinstance(payload["tsNs"], int)


def test_a_second_run_after_capture_is_a_no_op_ok(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _write_first_order_key(store_path)
    first = main(_argv(), env=_env(store_path), stdout=io.StringIO(), stderr=io.StringIO())
    assert first == EXIT_OK
    stdout = io.StringIO()
    second = main(_argv(), env=_env(store_path), stdout=stdout, stderr=io.StringIO())
    assert second == EXIT_OK
    assert "already captured" in stdout.getvalue()


def test_refuses_when_exec_state_db_is_unset(tmp_path: Path) -> None:
    stderr = io.StringIO()
    code = main(
        _argv(),
        env={OPERATOR_ACK_ENV_VAR: "1"},
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == EXIT_REFUSED
    printed = stderr.getvalue()
    assert EXEC_STATE_DB_ENV_VAR in printed
    assert "refused" in printed
