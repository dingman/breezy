"""Operator clear tool for the `pm_us_crh_cont` family-wide halt.

Mirrors `tests/unit/test_clear_submit_intent_cli.py`'s structure: a tmp_path
SQLite store shared with R-7's submit-intent flock, since `TrialDayLatch`
(and therefore the family halt key) lives in that SAME store.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.clear_family_halt_cli import (
    EXIT_NOTHING_TO_CLEAR,
    EXIT_OK,
    EXIT_REFUSED,
    main,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    FAMILY_HALT_KEY,
    HALT_CLEARED_KEY_PREFIX,
    open_trial_day_latch,
)

DUP_FILL_TS_NS = 1_787_617_213_000_000_000
CLEAR_TS_NS = 1_787_700_000_000_000_000


def _evidence(tmp_path: Path, name: str = "evidence.txt") -> Path:
    path = tmp_path / name
    path.write_text("positions snapshot + fill record attached out of band", encoding="utf-8")
    return path


def _env(store_path: Path) -> dict[str, str]:
    return {EXEC_STATE_DB_ENV_VAR: str(store_path)}


def _seed_halt(store_path: Path) -> None:
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch)
        trial_latch.record_duplicate_fill(
            "KSFO",
            "2026-09-12",
            venue_order_id="v-dup-1",
            qty=Decimal(1),
            fill_px=Decimal("0.4"),
            fee=Decimal(0),
            ts_ns=DUP_FILL_TS_NS,
        )
    store.close()


def _run(
    argv: list[str],
    store_path: Path,
    *,
    stdout: io.StringIO,
    stderr: io.StringIO,
    ts_ns: int = CLEAR_TS_NS,
) -> int:
    with patch(
        "breezy.strategy.current_rung_hold.clear_family_halt_cli.time.time_ns",
        return_value=ts_ns,
    ):
        return main(argv, env=_env(store_path), stdout=stdout, stderr=stderr)


def _seed_raw_halt(store_path: Path, raw: bytes) -> None:
    """Write `raw` directly under `FAMILY_HALT_KEY`, bypassing
    `record_duplicate_fill` -- used to simulate a corrupt or legacy-schema
    halt record that no writer in this codebase produces today."""
    store = SqliteStateStore(store_path)
    store.set(FAMILY_HALT_KEY, raw)
    store.close()


def test_refuses_when_the_halt_key_is_absent(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()
    stdout = io.StringIO()
    code = _run(
        [
            "--reason",
            "false alarm, verified via venue console",
            "--evidence-path",
            str(_evidence(tmp_path)),
        ],
        store_path,
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_NOTHING_TO_CLEAR
    assert "nothing to clear" in stdout.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(FAMILY_HALT_KEY) is None
    store.close()


def test_refuses_while_the_node_holds_the_lock(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    store = SqliteStateStore(store_path)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with open_submit_intent_latch(store, store_path):
        code = _run(
            [
                "--reason",
                "confirmed duplicate fill was a resend, not a new order",
                "--evidence-path",
                str(_evidence(tmp_path)),
            ],
            store_path,
            stdout=stdout,
            stderr=stderr,
        )
    store.close()
    assert code == EXIT_REFUSED
    assert "holds the lock" in stderr.getvalue()

    store2 = SqliteStateStore(store_path)
    with open_submit_intent_latch(store2, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch)
        assert trial_latch.is_family_halted() is True
    assert store2.get(f"{HALT_CLEARED_KEY_PREFIX}{CLEAR_TS_NS}") is None
    store2.close()


def test_happy_path_clears_the_halt_and_writes_an_audit_record(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    evidence = _evidence(tmp_path)
    stdout = io.StringIO()
    reason = "verified via venue console: duplicate fill was a websocket resend"
    code = _run(
        ["--reason", reason, "--evidence-path", str(evidence)],
        store_path,
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_OK
    assert "cleared" in stdout.getvalue()

    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch)
        assert trial_latch.is_family_halted() is False
    audit_raw = store.get(f"{HALT_CLEARED_KEY_PREFIX}{CLEAR_TS_NS}")
    store.close()
    assert audit_raw is not None
    audit = json.loads(audit_raw.decode("utf-8"))
    assert audit["reason"] == reason
    assert audit["tsNs"] == CLEAR_TS_NS
    assert audit["priorHalt"]["venueOrderId"] == "v-dup-1"
    assert len(audit["evidenceSha256"]) == 64


def test_second_run_after_clearing_is_idempotent(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    evidence = _evidence(tmp_path)
    reason = "verified via venue console, duplicate was a resend"
    code1 = _run(
        ["--reason", reason, "--evidence-path", str(evidence)],
        store_path,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code1 == EXIT_OK

    stdout2 = io.StringIO()
    code2 = _run(
        ["--reason", reason, "--evidence-path", str(evidence)],
        store_path,
        stdout=stdout2,
        stderr=io.StringIO(),
    )
    assert code2 == EXIT_NOTHING_TO_CLEAR
    assert "nothing to clear" in stdout2.getvalue()


def test_argparse_rejects_a_too_short_reason(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    raised = False
    try:
        main(
            ["--reason", "too short", "--evidence-path", str(_evidence(tmp_path))],
            env=_env(store_path),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    except SystemExit as exc:
        raised = True
        assert exc.code == 2
    assert raised
    store = SqliteStateStore(store_path)
    assert store.get(FAMILY_HALT_KEY) is not None  # unchanged: still the live halt payload
    store.close()


def test_argparse_rejects_a_missing_evidence_file(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    missing = tmp_path / "does-not-exist.json"
    raised = False
    try:
        main(
            [
                "--reason",
                "verified via venue console, duplicate was a resend",
                "--evidence-path",
                str(missing),
            ],
            env=_env(store_path),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    except SystemExit as exc:
        raised = True
        assert exc.code == 2
    assert raised
    store = SqliteStateStore(store_path)
    assert store.get(FAMILY_HALT_KEY) is not None  # unchanged
    store.close()


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"\xff\xfe\x00garbage-not-utf8", id="garbage_bytes"),
        pytest.param(b"", id="empty_string"),
        pytest.param(
            b'{"schemaVersion": 0, "note": "pre-halt-audit legacy format"}',
            id="old_version_json",
        ),
    ],
)
def test_a_corrupt_or_legacy_halt_payload_fails_closed_and_is_still_clearable(
    tmp_path: Path, raw: bytes
) -> None:
    """MEDIUM gap: `is_family_halted` must fail CLOSED (True) on garbage
    bytes, an empty value, or an unrecognised/legacy schema -- and the CLI
    must still be able to clear it with evidence rather than raising."""
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()
    _seed_raw_halt(store_path, raw)

    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch)
        assert trial_latch.is_family_halted() is True
    store.close()

    stdout = io.StringIO()
    code = _run(
        [
            "--reason",
            "cleared a corrupt/legacy halt payload after manual review",
            "--evidence-path",
            str(_evidence(tmp_path)),
        ],
        store_path,
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_OK
    assert "cleared" in stdout.getvalue()

    store2 = SqliteStateStore(store_path)
    audit_raw = store2.get(f"{HALT_CLEARED_KEY_PREFIX}{CLEAR_TS_NS}")
    with open_submit_intent_latch(store2, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch)
        assert trial_latch.is_family_halted() is False
    store2.close()
    assert audit_raw is not None
    audit = json.loads(audit_raw.decode("utf-8"))
    assert "priorHalt" in audit


def test_clearing_never_blocks_a_later_genuine_halt_and_each_clear_gets_its_own_audit_key(
    tmp_path: Path,
) -> None:
    """MEDIUM gap: after a clear, a FRESH `record_duplicate_fill` must be
    able to re-halt the family (not be silently swallowed by a stale
    "already halted" read of the cleared sentinel), and a second clear of
    that fresh halt must succeed and land under its OWN audit key -- never
    overwriting the first clear's audit record."""
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    first_clear_ts_ns = CLEAR_TS_NS
    second_clear_ts_ns = CLEAR_TS_NS + 1

    code1 = _run(
        [
            "--reason",
            "first clear: confirmed duplicate fill was a resend",
            "--evidence-path",
            str(_evidence(tmp_path, "evidence-1.txt")),
        ],
        store_path,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        ts_ns=first_clear_ts_ns,
    )
    assert code1 == EXIT_OK

    # A second, genuinely new duplicate fill re-halts the family with a
    # FRESH payload -- not the cleared sentinel left behind above.
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch)
        assert trial_latch.is_family_halted() is False
        trial_latch.record_duplicate_fill(
            "KLAX",
            "2026-09-13",
            venue_order_id="v-dup-2",
            qty=Decimal(1),
            fill_px=Decimal("0.5"),
            fee=Decimal(0),
            ts_ns=DUP_FILL_TS_NS + 1,
        )
        assert trial_latch.is_family_halted() is True
    store.close()

    stdout2 = io.StringIO()
    code2 = _run(
        [
            "--reason",
            "second clear: confirmed the second duplicate fill was also a resend",
            "--evidence-path",
            str(_evidence(tmp_path, "evidence-2.txt")),
        ],
        store_path,
        stdout=stdout2,
        stderr=io.StringIO(),
        ts_ns=second_clear_ts_ns,
    )
    assert code2 == EXIT_OK
    assert "cleared" in stdout2.getvalue()

    store2 = SqliteStateStore(store_path)
    first_audit = store2.get(f"{HALT_CLEARED_KEY_PREFIX}{first_clear_ts_ns}")
    second_audit = store2.get(f"{HALT_CLEARED_KEY_PREFIX}{second_clear_ts_ns}")
    with open_submit_intent_latch(store2, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch)
        assert trial_latch.is_family_halted() is False
    store2.close()

    assert first_audit is not None
    assert second_audit is not None
    assert first_audit != second_audit
    second_payload = json.loads(second_audit.decode("utf-8"))
    assert second_payload["priorHalt"]["venueOrderId"] == "v-dup-2"
