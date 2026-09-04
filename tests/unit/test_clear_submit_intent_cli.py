"""R-7 operator clear tool for an OPEN submit-intent latch."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.clear_submit_intent_cli import (
    EXIT_NOTHING_OPEN,
    EXIT_OK,
    EXIT_REFUSED,
    OPERATOR_ACK_ENV_VAR,
    main,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    RetirementReason,
    SubmitIntentState,
    open_submit_intent_latch,
)

TS_NS = 1_787_617_213_000_000_000


def _evidence(tmp_path: Path, *, with_fill: bool = True) -> Path:
    payload: dict[str, object] = {"positions": {}}
    if with_fill:
        payload["fill_record"] = {"tradeId": "trd-1", "order": {"id": "ord-1"}}
    else:
        payload["fill_record"] = None
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _env(store_path: Path, *, ack: bool = True) -> dict[str, str]:
    env = {EXEC_STATE_DB_ENV_VAR: str(store_path)}
    if ack:
        env[OPERATOR_ACK_ENV_VAR] = "1"
    return env


def test_clear_submit_intent_refuses_while_the_node_holds_the_lock(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    store = SqliteStateStore(store_path)
    stdout = io.StringIO()
    stderr = io.StringIO()
    evidence = _evidence(tmp_path)
    with open_submit_intent_latch(store, store_path):
        code = main(
            [
                "--yes",
                "--resolution",
                "no-order-exists",
                "--evidence",
                str(evidence),
            ],
            env=_env(store_path),
            stdout=stdout,
            stderr=stderr,
        )
    store.close()
    assert code == EXIT_REFUSED
    assert "holds the lock" in stderr.getvalue()


def test_clear_submit_intent_refuses_without_yes_and_the_operator_ack(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    evidence = _evidence(tmp_path)
    stderr = io.StringIO()
    code = main(
        ["--resolution", "no-order-exists", "--evidence", str(evidence)],
        env=_env(store_path, ack=True),
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == EXIT_REFUSED
    assert "--yes" in stderr.getvalue()

    stderr2 = io.StringIO()
    code2 = main(
        ["--yes", "--resolution", "no-order-exists", "--evidence", str(evidence)],
        env=_env(store_path, ack=False),
        stdout=io.StringIO(),
        stderr=stderr2,
    )
    assert code2 == EXIT_REFUSED
    assert "ack" in stderr2.getvalue()


def test_clear_submit_intent_prints_the_open_intent_before_clearing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del capsys
    store_path = tmp_path / "state.db"
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as latch:
        intent = latch.arm("b" * 64, now_ns=TS_NS)
    store.close()
    stdout = io.StringIO()
    evidence = _evidence(tmp_path)
    code = main(
        [
            "--yes",
            "--resolution",
            "order-id=ord-1",
            "--evidence",
            str(evidence),
        ],
        env=_env(store_path),
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_OK
    printed = stdout.getvalue()
    assert intent.intent_id in printed
    assert intent.fingerprint in printed
    assert str(intent.created_ns) in printed
    assert "OPEN" in printed
    assert "X-PM-Signature" not in printed
    assert "X-PM-Access-Key" not in printed
    store2 = SqliteStateStore(store_path)
    with open_submit_intent_latch(store2, store_path) as latch:
        current = latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is RetirementReason.OPERATOR_CLEARED
    store2.close()


def test_clear_submit_intent_exit_3_when_nothing_open(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()
    stdout = io.StringIO()
    code = main(
        [
            "--yes",
            "--resolution",
            "no-order-exists",
            "--evidence",
            str(_evidence(tmp_path, with_fill=False)),
        ],
        env=_env(store_path),
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_NOTHING_OPEN
