"""Tests for the SET sibling of the family-wide halt CLI (AUD-02b: enforce
the A1 ruling,
``docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md``).

Mirrors ``tests/unit/test_clear_family_halt_cli.py``'s structure: a tmp_path
SQLite store shared with R-7's submit-intent flock, since ``TrialDayLatch``
(and therefore the family halt key) lives in that SAME store. Every test here
injects its own ``positions_reader`` / ``proc_root`` / ``alert_sink`` -- no
test in this module ever performs the live GET or reads a real ``/proc``
entry. This module carries NO ``pytest.mark`` of any kind (see the X1
execution-egress pin this module widens).

**AUD-02b AMENDMENT plan-test mapping, as shipped:** plan §7 step 0a tests
(13) "stale-fallback" and (14) "newer-fill" are RETIRED along with the
durable-evidence fallback they exercised (see ``set_family_halt_cli.py``'s
module docstring for why: clause (b) is unreachable from a bare slug, and
the implemented clause (a) fill cross-check was mis-keyed and structurally
inert). They are RE-EXPRESSED here as "a live GET failure REFUSES, never
FLAT" -- one test per failure class: transport error, auth error, malformed
JSON, schema drift. Every other plan-numbered test below keeps its original
meaning; the numbers are noted in each section's comment.
"""

from __future__ import annotations

import ast
import io
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient
from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import SubmitIntentLockError, open_submit_intent_latch
from breezy.strategy.current_rung_hold.clear_family_halt_cli import (
    EXIT_OK as CLEAR_EXIT_OK,
)
from breezy.strategy.current_rung_hold.clear_family_halt_cli import (
    main as clear_main,
)
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.exit_wiring import _DIAG_FAMILY_HALT, submit_exit
from breezy.strategy.current_rung_hold.set_family_halt_cli import (
    EXIT_ALREADY_HALTED,
    EXIT_OK,
    EXIT_READBACK_FAILED,
    EXIT_REFUSED,
    check_pre_set_position,
    main,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    LEGACY_FAMILY_HALT_KEY,
    TrialDayLatch,
    family_halt_key,
    open_trial_day_latch,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

SET_TS_NS = 1_800_000_000_000_000_000
REASON = "AUD-02b: enforcing RULING_A1 disposition (ii)"


class _FakeAlertSink:
    def __init__(self, *, raises: bool = False) -> None:
        self.payloads: list[AlertPayload] = []
        self._raises = raises

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)
        if self._raises:
            raise RuntimeError("sink is down")


def _evidence_path(tmp_path: Path, name: str = "evidence.md") -> Path:
    path = tmp_path / name
    path.write_text("A1 ruling: STOP TRADING THIS SURFACE", encoding="utf-8")
    return path


def _env(store_path: Path) -> dict[str, str]:
    return {EXEC_STATE_DB_ENV_VAR: str(store_path)}


def _flat_live_reader() -> dict[str, Any]:
    return {"positions": {}, "eof": True}


def _open_live_reader(net: str = "5") -> Any:
    def _reader() -> dict[str, Any]:
        return {"positions": {"KSFO-2026-09-21-HIGH-70": {"netPosition": net}}, "eof": True}

    return _reader


def _raising_reader(exc: BaseException) -> Any:
    def _reader() -> dict[str, Any]:
        raise exc

    return _reader


#: The real, checked-in v4 manifest -- every test in this module that does
#: not exercise `--family-id`/`--families-dir` validation itself uses this
#: id against the repo's real `deploy/families/` (the default
#: `--families-dir`), so no test needs to fabricate a manifest just to reach
#: the halt mechanics `set_family_halt_cli` actually tests.
DEFAULT_TEST_FAMILY_ID = "pm_us_crh_v4"
_HALT_KEY = family_halt_key(DEFAULT_TEST_FAMILY_ID)


def _run(
    argv: list[str],
    store_path: Path,
    *,
    stdout: io.StringIO | None = None,
    stderr: io.StringIO | None = None,
    positions_reader: Any = None,
    alert_sink: Any = None,
    proc_root: Path | None = None,
    ts_ns: int = SET_TS_NS,
) -> int:
    if "--family-id" not in argv:
        argv = [*argv, "--family-id", DEFAULT_TEST_FAMILY_ID]
    with patch(
        "breezy.strategy.current_rung_hold.set_family_halt_cli.time.time_ns",
        return_value=ts_ns,
    ):
        reader = positions_reader if positions_reader is not None else _flat_live_reader
        kwargs: dict[str, Any] = {
            "env": _env(store_path),
            "stdout": stdout if stdout is not None else io.StringIO(),
            "stderr": stderr if stderr is not None else io.StringIO(),
            "positions_reader": reader,
            "alert_sink": alert_sink,
        }
        # Every test isolates `node_store_path_check` from the REAL host
        # `/proc` (this box may be running a real `breezy-trade` node): an
        # empty, freshly-made directory always yields `NO_NODE` (accepted),
        # unless a test explicitly injects its own `proc_root` to exercise
        # the MATCH/MISMATCH/DISCOVERY_FAILED branches.
        kwargs["proc_root"] = proc_root if proc_root is not None else Path(tempfile.mkdtemp())
        return main(argv, **kwargs)


def _seed_open_submit_intent_and_close(store_path: Path) -> None:
    SqliteStateStore(store_path).close()


def _is_halted(store_path: Path) -> bool:
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id=DEFAULT_TEST_FAMILY_ID,
        )
        halted = trial_latch.is_family_halted()
    store.close()
    return halted


# ---------------------------------------------------------------------------
# (1)/(2) happy path + idempotent re-set
# ---------------------------------------------------------------------------


def test_happy_path_sets_the_halt_and_alerts(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    sink = _FakeAlertSink()
    stdout = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stdout=stdout,
        alert_sink=sink,
    )
    assert code == EXIT_OK
    assert "halted" in stdout.getvalue()
    assert _is_halted(store_path) is True

    assert len(sink.payloads) == 1
    assert REASON in sink.payloads[0].detail
    assert "evidence_sha256=" in sink.payloads[0].detail


def test_idempotent_re_set_leaves_the_original_halt_byte_identical(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    sink = _FakeAlertSink()
    code1 = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        alert_sink=sink,
    )
    assert code1 == EXIT_OK

    store = SqliteStateStore(store_path)
    original = store.get(_HALT_KEY)
    store.close()

    stdout2 = io.StringIO()
    code2 = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stdout=stdout2,
        alert_sink=sink,
        ts_ns=SET_TS_NS + 1,
    )
    assert code2 == EXIT_ALREADY_HALTED
    assert "already halted" in stdout2.getvalue()
    assert len(sink.payloads) == 1, "no second alert on a no-op re-set"

    store2 = SqliteStateStore(store_path)
    assert store2.get(_HALT_KEY) == original
    store2.close()


# ---------------------------------------------------------------------------
# (3) clear still works against the new payload shape
# ---------------------------------------------------------------------------


def test_clear_family_halt_still_works_after_a_policy_set(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    assert (
        _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
            store_path,
        )
        == EXIT_OK
    )

    code = clear_main(
        [
            "--family-id",
            DEFAULT_TEST_FAMILY_ID,
            "--reason",
            "clearing the policy halt after manual review",
            "--evidence-path",
            str(_evidence_path(tmp_path, "clear-evidence.txt")),
        ],
        env=_env(store_path),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code == CLEAR_EXIT_OK
    assert _is_halted(store_path) is False


# ---------------------------------------------------------------------------
# (4) survives relaunch: a FRESH store/latch after close still reads halted
# ---------------------------------------------------------------------------


def test_halt_survives_a_fresh_store_open_after_close(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    assert (
        _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
            store_path,
        )
        == EXIT_OK
    )
    assert _is_halted(store_path) is True


# ---------------------------------------------------------------------------
# (5) refuses while the node holds the lock
# ---------------------------------------------------------------------------


def test_refuses_while_the_node_holds_the_lock(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    store = SqliteStateStore(store_path)
    stderr = io.StringIO()
    with open_submit_intent_latch(store, store_path):
        code = _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
            store_path,
            stderr=stderr,
        )
    store.close()
    assert code == EXIT_REFUSED
    assert "holds the lock" in stderr.getvalue()
    assert "NEXT:" in stderr.getvalue()

    store2 = SqliteStateStore(store_path)
    assert store2.get(_HALT_KEY) is None
    assert store2.get(LEGACY_FAMILY_HALT_KEY) is None
    store2.close()


# ---------------------------------------------------------------------------
# (6) logged AND alerted; a raising sink never undoes the halt -- extended
# per P3(viii) with the "nobody was told" stderr surfacing.
# ---------------------------------------------------------------------------


def test_a_raising_alert_sink_never_undoes_the_halt_or_the_exit_code(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    sink = _FakeAlertSink(raises=True)
    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        alert_sink=sink,
    )
    assert code == EXIT_OK
    assert len(sink.payloads) == 1
    assert _is_halted(store_path) is True
    assert "nobody was told" in stderr.getvalue()


# ---------------------------------------------------------------------------
# (8) store-path mismatch REFUSES, writes nothing
# ---------------------------------------------------------------------------


def test_store_path_mismatch_refuses_and_writes_nothing(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    proc_root = tmp_path / "proc"
    pid_dir = proc_root / "42"
    pid_dir.mkdir(parents=True)
    (pid_dir / "cmdline").write_bytes(b".venv/bin/breezy-trade\0")
    (pid_dir / "environ").write_bytes(
        f"{EXEC_STATE_DB_ENV_VAR}={tmp_path / 'a-different-store.db'}\0".encode()
    )

    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        proc_root=proc_root,
    )
    assert code == EXIT_REFUSED
    assert EXEC_STATE_DB_ENV_VAR in stderr.getvalue()
    assert str(store_path) not in stderr.getvalue()
    assert "NEXT:" in stderr.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


# ---------------------------------------------------------------------------
# P3(vi): DISCOVERY_FAILED store-path check REFUSES and writes nothing
# ---------------------------------------------------------------------------


def test_a_discovery_failed_store_path_check_refuses_and_writes_nothing(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    proc_root = tmp_path / "proc"
    pid_dir = proc_root / "42"
    pid_dir.mkdir(parents=True)
    # A directory standing in for `cmdline`: `read_bytes()` raises
    # `IsADirectoryError` (an `OSError`), which `_read_cmdline` turns into
    # `_CmdlineReadFailure` -> `node_store_path_check` returns
    # `DISCOVERY_FAILED` (`exec_state_db_path.py:110-126,163-167`).
    (pid_dir / "cmdline").mkdir()

    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        proc_root=proc_root,
    )
    assert code == EXIT_REFUSED
    assert "DISCOVERY_FAILED" in stderr.getvalue()
    assert str(store_path) not in stderr.getvalue()
    assert "NEXT:" in stderr.getvalue()
    # DISCOVERY_FAILED gets its OWN wording, distinct from MISMATCH's: the
    # cause is the node's /proc environment being unreadable, never an
    # env-var mismatch.
    assert "/proc environment could not be read" in stderr.getvalue()
    assert "NOT an env-var mismatch" in stderr.getvalue()
    assert "env var matches the live" not in stderr.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


# ---------------------------------------------------------------------------
# (9) --status is a read-only positive control: zero writes, zero network
# ---------------------------------------------------------------------------


def test_status_reports_not_halted_then_halted_with_no_writes_or_network(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)

    def _reader_should_never_be_called() -> dict[str, Any]:
        raise AssertionError("--status must never call the positions reader")

    stdout_before = io.StringIO()
    code_before = _run(
        ["--status"],
        store_path,
        stdout=stdout_before,
        positions_reader=_reader_should_never_be_called,
    )
    assert code_before == EXIT_OK
    assert "halted=False" in stdout_before.getvalue()

    store_before = SqliteStateStore(store_path)
    bytes_before = store_before.get(_HALT_KEY)
    store_before.close()
    assert bytes_before is None

    assert (
        _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
            store_path,
        )
        == EXIT_OK
    )

    stdout_after = io.StringIO()
    code_after = _run(
        ["--status"],
        store_path,
        stdout=stdout_after,
        positions_reader=_reader_should_never_be_called,
    )
    assert code_after == EXIT_OK
    assert "halted=True" in stdout_after.getvalue()

    store_after = SqliteStateStore(store_path)
    bytes_after_first_status = store_after.get(_HALT_KEY)
    store_after.close()

    # A second --status call must not mutate the halt record either.
    _run(["--status"], store_path, positions_reader=_reader_should_never_be_called)
    store_final = SqliteStateStore(store_path)
    assert store_final.get(_HALT_KEY) == bytes_after_first_status
    store_final.close()


# ---------------------------------------------------------------------------
# (12) pre-set open-position refusal, and the flat/positive counterpart
# ---------------------------------------------------------------------------


def test_a_non_zero_live_net_position_refuses_and_writes_nothing(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        positions_reader=_open_live_reader("5"),
    )
    assert code == EXIT_REFUSED
    assert "verdict=OPEN" in stderr.getvalue()
    assert "breezy-clear-family-halt" in stderr.getvalue()  # the documented sequence, verbatim
    assert "re-run breezy-set-family-halt" in stderr.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


def test_an_eof_page_with_zero_positions_is_flat_and_proceeds(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    stdout = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stdout=stdout,
        positions_reader=_flat_live_reader,
    )
    assert code == EXIT_OK
    assert "LIVE_GET" in stdout.getvalue()


# ---------------------------------------------------------------------------
# (18) a NEGATIVE net_position is an OPEN position (sign-agnostic)
# ---------------------------------------------------------------------------


def test_a_negative_net_position_is_open_not_flat(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        positions_reader=_open_live_reader("-3"),
    )
    assert code == EXIT_REFUSED
    assert "verdict=OPEN" in stderr.getvalue()


# ---------------------------------------------------------------------------
# (13)/(14) RETIRED with the fallback; RE-EXPRESSED (AUD-02b amendment P1):
# a live GET failure REFUSES, never FLAT -- one test per failure class.
# ---------------------------------------------------------------------------


def test_a_transport_error_from_the_live_get_refuses_never_flat(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        positions_reader=_raising_reader(ConnectionError("no route to venue")),
    )
    assert code == EXIT_REFUSED
    assert "LIVE_GET_FAILED:ConnectionError" in stderr.getvalue()
    assert "NEXT:" in stderr.getvalue()
    assert "durable-evidence fallback was removed" in stderr.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


def test_an_auth_error_from_the_live_get_refuses_never_flat(tmp_path: Path) -> None:
    from breezy.adapters.polymarket_us.errors import VenueAuthError

    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        positions_reader=_raising_reader(VenueAuthError("credentials rejected")),
    )
    assert code == EXIT_REFUSED
    assert "LIVE_GET_FAILED:VenueAuthError" in stderr.getvalue()
    assert "NEXT:" in stderr.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


def test_malformed_json_from_the_live_get_refuses_never_flat(tmp_path: Path) -> None:
    from breezy.adapters.polymarket_us.errors import VenueTransportError

    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        # The shape `http.py:_decode` raises when `json.loads` fails.
        positions_reader=_raising_reader(
            VenueTransportError("Polymarket.us returned a body that is not valid JSON")
        ),
    )
    assert code == EXIT_REFUSED
    assert "LIVE_GET_FAILED:VenueTransportError" in stderr.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


def test_schema_drift_from_the_live_get_refuses_never_flat(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)

    def _drifted_reader() -> dict[str, Any]:
        return {"eof": True}  # valid JSON, but no 'positions' key at all

    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        positions_reader=_drifted_reader,
    )
    assert code == EXIT_REFUSED
    assert "LIVE_PAGE_REJECTED" in stderr.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


# ---------------------------------------------------------------------------
# (15)/(16) a non-eof / drifted live page REFUSES rather than assuming flat
# ---------------------------------------------------------------------------


def test_a_non_eof_live_page_refuses(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)

    def _reader() -> dict[str, Any]:
        return {"positions": {}}  # no eof key at all

    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        positions_reader=_reader,
    )
    assert code == EXIT_REFUSED
    assert "LIVE_PAGE_REJECTED" in stderr.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


def test_a_drifted_live_shape_refuses(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)

    def _reader() -> dict[str, Any]:
        return {"positions": [], "eof": True}  # positions is a list, not a dict

    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        positions_reader=_reader,
    )
    assert code == EXIT_REFUSED

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


def test_a_named_slug_with_no_net_position_field_is_unknown_and_refuses(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)

    def _reader() -> dict[str, Any]:
        return {"positions": {"KSFO-...": {}}, "eof": True}

    stderr = io.StringIO()
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=stderr,
        positions_reader=_reader,
    )
    assert code == EXIT_REFUSED
    assert "verdict=UNKNOWN" in stderr.getvalue()


# ---------------------------------------------------------------------------
# (19) no instance, no connection: the live path never constructs a client
# ---------------------------------------------------------------------------


def test_the_live_page_parser_never_constructs_an_exec_client_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_if_constructed(self: object, *args: object, **kwargs: object) -> None:
        raise AssertionError("no PolymarketUSExecutionClient instance should ever be built")

    monkeypatch.setattr(PolymarketUSExecutionClient, "__init__", _raise_if_constructed)

    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        positions_reader=_flat_live_reader,
    )
    assert code == EXIT_OK


# ---------------------------------------------------------------------------
# P1b: check_pre_set_position takes no store and has exactly three outcomes
# ---------------------------------------------------------------------------


def test_check_pre_set_position_takes_no_store_and_has_only_three_outcomes() -> None:
    import inspect

    signature = inspect.signature(check_pre_set_position)
    assert set(signature.parameters) == {"positions_reader"}
    assert signature.parameters["positions_reader"].kind == inspect.Parameter.KEYWORD_ONLY

    flat = check_pre_set_position(positions_reader=_flat_live_reader)
    assert (flat.source, flat.verdict) == ("LIVE_GET", "FLAT_AND_KNOWN")

    open_ = check_pre_set_position(positions_reader=_open_live_reader("5"))
    assert (open_.source, open_.verdict) == ("LIVE_GET", "OPEN")

    unknown = check_pre_set_position(positions_reader=_raising_reader(ConnectionError()))
    assert (unknown.source, unknown.verdict) == ("LIVE_GET", "UNKNOWN")


# ---------------------------------------------------------------------------
# P3(ii): evidence is hashed BEFORE the store/flock/GET; unreadable => clean
# refusal, no store ever opened.
# ---------------------------------------------------------------------------


def _unreadable_at(target: Path):
    """EDGE-3: family-id resolution now reads a REAL manifest
    (``deploy/families/<id>.json``) before the evidence hash, through the
    SAME ``Path.read_bytes``. A blanket monkeypatch would make the manifest
    read fail too (it has no idea which instance called it) and never reach
    the evidence-hash step this test targets, so the patch raises only for
    ``target`` and delegates to the real implementation otherwise."""
    real_read_bytes = Path.read_bytes

    def _side_effect(self: Path, *args: object, **kwargs: object) -> bytes:
        if self == target:
            raise PermissionError("denied")
        return real_read_bytes(self, *args, **kwargs)

    return patch.object(Path, "read_bytes", autospec=True, side_effect=_side_effect)


def test_an_unreadable_evidence_file_refuses_before_the_store_is_opened(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    # Deliberately NOT seeded: the store must never even be CREATED on this
    # path, which is the strongest form of "opened after the hash, not before".
    stderr = io.StringIO()
    evidence_path = _evidence_path(tmp_path)
    with _unreadable_at(evidence_path):
        code = _run(
            ["--reason", REASON, "--evidence-path", str(evidence_path)],
            store_path,
            stderr=stderr,
        )
    assert code == EXIT_REFUSED
    assert "unreadable" in stderr.getvalue()
    assert "PermissionError" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()
    assert store_path.exists() is False


# ---------------------------------------------------------------------------
# P3(iii): a lock-infrastructure failure (SubmitIntentLockError, a SIBLING of
# SubmitIntentLockHeld/SubmitIntentLockNotHeld under SubmitIntentError, never
# a subclass of either) refuses with its own distinct reason.
# ---------------------------------------------------------------------------


def test_a_lock_infrastructure_failure_refuses_with_a_distinct_reason(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    stderr = io.StringIO()
    with patch(
        "breezy.strategy.current_rung_hold.set_family_halt_cli.open_submit_intent_latch",
        side_effect=SubmitIntentLockError(),
    ):
        code = _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
            store_path,
            stderr=stderr,
        )
    assert code == EXIT_REFUSED
    assert "lock infrastructure failure" in stderr.getvalue()
    assert "SubmitIntentLockError" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()
    assert "NEXT:" in stderr.getvalue()


# ---------------------------------------------------------------------------
# P3(iv): a failed read-back after a successful write exits DISTINCTLY.
# ---------------------------------------------------------------------------


def test_a_failed_read_back_after_the_write_exits_distinctly(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    sink = _FakeAlertSink()
    stderr = io.StringIO()
    # Forces BOTH the pre-write check (must read False to proceed) and the
    # post-write read-back (must ALSO read False, simulating "wrote but the
    # veto may not be armed") to the same value.
    with patch.object(TrialDayLatch, "is_family_halted", return_value=False):
        code = _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
            store_path,
            stderr=stderr,
            alert_sink=sink,
        )
    assert code == EXIT_READBACK_FAILED
    assert "UNPROTECTED" in stderr.getvalue()
    assert "NEXT:" in stderr.getvalue()
    assert len(sink.payloads) == 0, "no alert on an undefined-safety read-back failure"


# ---------------------------------------------------------------------------
# P3(v): a programming bug in the reader is LOGGED (type + traceback), not
# just tokenised.
# ---------------------------------------------------------------------------


def test_a_programming_bug_in_the_reader_is_logged_not_just_tokenised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    stderr = io.StringIO()
    bug = AttributeError("'NoneType' object has no attribute 'x'")
    with caplog.at_level(
        logging.ERROR, logger="breezy.strategy.current_rung_hold.set_family_halt_cli",
    ):
        code = _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
            store_path,
            stderr=stderr,
            positions_reader=_raising_reader(bug),
        )
    assert code == EXIT_REFUSED
    assert "LIVE_GET_FAILED:AttributeError" in stderr.getvalue()
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) == 1
    assert error_records[0].exc_info is not None


# ---------------------------------------------------------------------------
# P3(vii): every non-zero-exit branch prints a NEXT: line (all ten).
# ---------------------------------------------------------------------------


def test_every_refusal_prints_a_next_step(tmp_path: Path) -> None:
    # (a) not-configured
    stderr = io.StringIO()
    code = main(
        [
            "--family-id", DEFAULT_TEST_FAMILY_ID,
            "--reason", REASON,
            "--evidence-path", str(_evidence_path(tmp_path)),
        ],
        env={},
        stdout=io.StringIO(),
        stderr=stderr,
        positions_reader=_flat_live_reader,
        proc_root=Path(tempfile.mkdtemp()),
    )
    assert code == EXIT_REFUSED and "NEXT:" in stderr.getvalue()

    # (b) MISMATCH -- covered by test_store_path_mismatch_refuses_and_writes_nothing
    # (c) DISCOVERY_FAILED -- covered by
    #     test_a_discovery_failed_store_path_check_refuses_and_writes_nothing
    # (h) verdict=OPEN -- covered by test_a_non_zero_live_net_position_refuses_and_writes_nothing
    # (i) verdict=UNKNOWN -- covered by test_a_transport_error_from_the_live_get_refuses_never_flat
    # (j) read-back failure -- covered by test_a_failed_read_back_after_the_write_exits_distinctly

    # (d) unreadable evidence
    store_path_d = tmp_path / "d.db"
    stderr_d = io.StringIO()
    evidence_path_d = _evidence_path(tmp_path, "d.md")
    with _unreadable_at(evidence_path_d):
        code_d = _run(
            ["--reason", REASON, "--evidence-path", str(evidence_path_d)],
            store_path_d,
            stderr=stderr_d,
        )
    assert code_d == EXIT_REFUSED and "NEXT:" in stderr_d.getvalue()

    # (e) lock-held
    store_path_e = tmp_path / "e.db"
    _seed_open_submit_intent_and_close(store_path_e)
    store_e = SqliteStateStore(store_path_e)
    stderr_e = io.StringIO()
    with open_submit_intent_latch(store_e, store_path_e):
        code_e = _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path, "e.md"))],
            store_path_e,
            stderr=stderr_e,
        )
    store_e.close()
    assert code_e == EXIT_REFUSED and "NEXT:" in stderr_e.getvalue()

    # (g) lock-error
    store_path_g = tmp_path / "g.db"
    _seed_open_submit_intent_and_close(store_path_g)
    stderr_g = io.StringIO()
    with patch(
        "breezy.strategy.current_rung_hold.set_family_halt_cli.open_submit_intent_latch",
        side_effect=SubmitIntentLockError(),
    ):
        code_g = _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path, "g.md"))],
            store_path_g,
            stderr=stderr_g,
        )
    assert code_g == EXIT_REFUSED and "NEXT:" in stderr_g.getvalue()


# ---------------------------------------------------------------------------
# P3(i): factories/exec-client public delegations, exercised end to end.
# ---------------------------------------------------------------------------


def test_the_live_page_parser_uses_the_public_declared_positions_name() -> None:
    """`declared_positions` (public) and `_declared_positions` (private)
    agree on the same payloads -- exhaustive coverage of the same claim
    lives in `tests/unit/test_polymarket_us_exec_client.py`; this asserts
    the CLI module itself calls the PUBLIC name, not the private one."""
    import inspect

    from breezy.strategy.current_rung_hold import set_family_halt_cli

    source = inspect.getsource(set_family_halt_cli._positions_from_live_payload)
    assert "PolymarketUSExecutionClient.declared_positions(" in source
    assert "._declared_positions(" not in source


# ---------------------------------------------------------------------------
# Coordinator round-2: test (7) -- the raw halt-key symbols' reader set.
# ---------------------------------------------------------------------------

_RAW_HALT_KEY_SYMBOLS = frozenset(
    {"LEGACY_FAMILY_HALT_KEY", "FAMILY_HALT_KEY_PREFIX", "family_halt_key"}
)


def test_family_halt_key_symbol_is_read_only_inside_trial_day_latch() -> None:
    """Plan §7 step 0a test (7), EDGE-3 re-point (AM-2/"Existing pins
    re-pointed"): "no capture/tally/shadow path reads the raw halt key" --
    asserted by an AST scan (never a grep, which cannot distinguish a real
    `Name` reference from a docstring/comment MENTION of the token, e.g.
    `trade_supervisor_core.py`'s own comment naming it while deliberately
    duplicating the STRING as its own separate pinned
    `CONTINUOUS_LEGACY_FAMILY_HALT_KEY` literal). The veto (`composition.py`)
    and both CLIs call `TrialDayLatch.is_family_halted()`/
    `family_halt_state()`, never a raw `Name` reference to
    `LEGACY_FAMILY_HALT_KEY`, `FAMILY_HALT_KEY_PREFIX`, or the
    `family_halt_key` constructor. A positive control (grep) proves the
    token exists in source at all, so an empty AST result cannot be mistaken
    for a tool that found nothing (repo lesson:
    `grep-tool-is-blind-under-venv.md`).
    """
    grep_control = subprocess.run(
        ["/usr/bin/grep", "-rl", "FAMILY_HALT_KEY", "src/breezy", "--include=*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert grep_control.stdout.strip(), "positive control failed: grep found zero matches"

    files_with_a_real_reference: set[str] = set()
    for path in (REPO_ROOT / "src" / "breezy").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in _RAW_HALT_KEY_SYMBOLS:
                files_with_a_real_reference.add(str(path.relative_to(REPO_ROOT)))
                break
    assert files_with_a_real_reference == {
        "src/breezy/strategy/current_rung_hold/trial_day_latch.py"
    }


# ---------------------------------------------------------------------------
# Coordinator round-2: test (10) -- forced-submit veto, independent of any
# market data (no order, no instrument, no exec client instance).
# ---------------------------------------------------------------------------


def test_forced_submit_via_the_veto_is_refused_independent_of_market_data(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    assert (
        _run(
            ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
            store_path,
        )
        == EXIT_OK
    )

    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id=DEFAULT_TEST_FAMILY_ID,
        )
        veto = family_halt_submit_veto(trial_latch)
        # The "forced submit": the exact zero-argument callable the exec
        # client consults immediately before the permit spend -- called
        # directly here, with no order, no instrument, no exec client
        # instance, and no market data of any kind.
        assert veto() == "family_halt"
    store.close()


# ---------------------------------------------------------------------------
# Coordinator round-2: test (11) -- the exit seam is refused identically
# (pin, not a change: exit_wiring.submit_exit already checks
# is_family_halted() first, exit_wiring.py:246,269-275).
# ---------------------------------------------------------------------------


class _FakeDiagnostics:
    def __init__(self) -> None:
        self.recorded: list[str] = []

    def record(self, name: str) -> None:
        self.recorded.append(name)


class _FakeExitStrategy:
    """A minimal duck-typed stand-in for `ContinuousRungHoldStrategy`,
    exercising the REAL `exit_wiring.submit_exit` function. Only the fields
    the HALTED branch touches are populated -- it returns before ever
    reaching `proposal`/cache/instrument/position, so none of those need a
    real Nautilus object."""

    def __init__(self, latch: Any) -> None:
        self._latch = latch
        self.diagnostics = _FakeDiagnostics()
        self.diagnostics_alerter = None
        self.order_submitted = False

    def _report_alerter(self, alerter: Any, fail_message: str) -> tuple[object, ...]:
        return ()

    def submit_order(self, order: Any, *, position_id: Any) -> None:
        self.order_submitted = True


def test_the_exit_seam_is_refused_identically_when_the_family_is_halted(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id=DEFAULT_TEST_FAMILY_ID,
        )
        trial_latch.record_policy_halt(
            reason=REASON, evidence_sha256="0" * 64, ts_ns=1,
        )
        fake_strategy = _FakeExitStrategy(trial_latch)
        submit_exit(fake_strategy, None)  # type: ignore[arg-type]
    store.close()
    assert fake_strategy.order_submitted is False
    assert fake_strategy.diagnostics.recorded == [_DIAG_FAMILY_HALT]


# ---------------------------------------------------------------------------
# Final fix batch item 3: `_default_live_positions_reader`'s `config.venue`
# guard is type-narrowing / defence-in-depth (`PolymarketUSExecClientConfig.
# __post_init__` already refuses a bad `venue` at construction) -- but this
# hermetic test proves the CLI-side guard ALSO holds on its own terms, by
# injecting a stand-in `exec_config_from_env` that returns an object
# `__post_init__` never validated (never a real dataclass instance), so no
# real env, no real credentials, and no network are anywhere in this test.
# ---------------------------------------------------------------------------


class _StandInExecConfig:
    """NOT a `PolymarketUSExecClientConfig` -- `__post_init__` never ran on
    this object, so it is the only way to hand `_default_live_positions_reader`
    a `venue` value the real dataclass would have already refused."""

    def __init__(self, venue: Any) -> None:
        self.venue = venue


@pytest.mark.parametrize(
    "venue",
    [None, "not-a-venue-config", object()],
    ids=["none", "wrong-type-str", "wrong-type-object"],
)
def test_default_live_reader_refuses_a_bad_venue_config_and_builds_no_client(
    venue: Any,
) -> None:
    from breezy.strategy.current_rung_hold import set_family_halt_cli

    client_calls: list[Any] = []

    def _fake_exec_config_from_env(env: Any) -> _StandInExecConfig:
        return _StandInExecConfig(venue=venue)

    def _fake_shared_http_client(*args: Any, **kwargs: Any) -> Any:
        client_calls.append((args, kwargs))
        raise AssertionError("no HTTP client should ever be built for a bad venue config")

    with patch(
        "breezy.adapters.polymarket_us.factories.exec_config_from_env",
        _fake_exec_config_from_env,
    ), patch(
        "breezy.adapters.polymarket_us.factories.shared_polymarket_us_http_client",
        _fake_shared_http_client,
    ), pytest.raises(Exception) as exc_info:
        set_family_halt_cli._default_live_positions_reader({})

    assert type(exc_info.value).__name__ == "SettingsError"
    assert client_calls == []


def test_default_live_reader_bad_venue_guard_is_reached_through_the_cli(
    tmp_path: Path,
) -> None:
    """End-to-end: when no `positions_reader` is injected, `set_family_halt`
    falls back to `_default_live_positions_reader`, whose guard converts a
    bad venue config into a REFUSED/UNKNOWN verdict -- never a raw traceback
    out of `main`."""
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)

    def _fake_exec_config_from_env(env: Any) -> _StandInExecConfig:
        return _StandInExecConfig(venue=None)

    stderr = io.StringIO()
    with patch(
        "breezy.adapters.polymarket_us.factories.exec_config_from_env",
        _fake_exec_config_from_env,
    ):
        code = main(
            [
                "--family-id", DEFAULT_TEST_FAMILY_ID,
                "--reason", REASON,
                "--evidence-path", str(_evidence_path(tmp_path)),
            ],
            env=_env(store_path),
            stdout=io.StringIO(),
            stderr=stderr,
            positions_reader=None,
            proc_root=Path(tempfile.mkdtemp()),
        )
    assert code == EXIT_REFUSED
    assert "LIVE_GET_FAILED:SettingsError" in stderr.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(_HALT_KEY) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


# ---------------------------------------------------------------------------
# EDGE-3 §6.3: CLI input safety and per-family isolation (tests 21, 23, 24).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_family_id",
    [
        pytest.param("../x", id="dotdot_slash"),
        pytest.param("a/b", id="slash"),
        pytest.param("/etc/passwd", id="absolute_path"),
        pytest.param("..", id="dotdot"),
        pytest.param("x\x00y", id="nul"),
        pytest.param("x" * 65, id="65_chars"),
    ],
)
def test_set_refuses_family_id_containing_path_traversal_before_touching_the_filesystem(
    tmp_path: Path, bad_family_id: str,
) -> None:
    """EDGE-3 test 21 (AC-7): a `--family-id` that fails the regex is
    refused by the regex ALONE -- no `Path.resolve`, `load_family_manifest`,
    or `SqliteStateStore` call ever happens, proven by patching all three
    to raise if called."""
    store_path = tmp_path / "state.db"

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not be called: family-id validation must precede this")

    with (
        patch(
            "breezy.strategy.current_rung_hold.family_id_arg.load_family_manifest", _boom,
        ),
        patch.object(Path, "resolve", _boom),
        patch("breezy.strategy.current_rung_hold.set_family_halt_cli.SqliteStateStore", _boom),
    ):
        code = main(
            [
                "--family-id", bad_family_id,
                "--reason", REASON,
                "--evidence-path", str(_evidence_path(tmp_path)),
            ],
            env=_env(store_path),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            positions_reader=_flat_live_reader,
            proc_root=Path(tempfile.mkdtemp()),
        )
    assert code == EXIT_REFUSED
    assert store_path.exists() is False


def test_set_on_fresh_family_writes_only_its_key_while_v4_stays_halted(
    tmp_path: Path,
) -> None:
    """EDGE-3 test 23: setting a halt on a fresh (non-v4) family writes only
    that family's per-family key, and does not disturb v4's own (already
    set) halt in the SAME store."""
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)

    families = tmp_path / "families"
    families.mkdir()
    import json as _json

    payload = _json.loads(Path("deploy/families/pm_us_crh_v4.json").read_text())
    payload["family_id"] = "pm_us_crh_fresh"
    (families / "pm_us_crh_v4.json").write_text(
        Path("deploy/families/pm_us_crh_v4.json").read_text()
    )
    (families / "pm_us_crh_fresh.json").write_text(_json.dumps(payload))

    # First, halt v4 through the CLI.
    code_v4 = _run(
        [
            "--family-id", "pm_us_crh_v4",
            "--families-dir", str(families),
            "--reason", REASON,
            "--evidence-path", str(_evidence_path(tmp_path, "v4.txt")),
        ],
        store_path,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code_v4 == EXIT_OK

    # Then halt the fresh family, in the SAME store.
    code_fresh = _run(
        [
            "--family-id", "pm_us_crh_fresh",
            "--families-dir", str(families),
            "--reason", REASON,
            "--evidence-path", str(_evidence_path(tmp_path, "fresh.txt")),
        ],
        store_path,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code_fresh == EXIT_OK

    store = SqliteStateStore(store_path)
    assert store.get(family_halt_key("pm_us_crh_v4")) is not None
    assert store.get(family_halt_key("pm_us_crh_fresh")) is not None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        v4_latch = open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
        )
        fresh_latch = open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_fresh",
        )
        assert v4_latch.is_family_halted() is True
        assert fresh_latch.is_family_halted() is True


@pytest.mark.parametrize(
    ("raw", "expected_legacy"),
    [
        pytest.param(None, "absent", id="absent"),
        pytest.param(b'{"v":1,"state":"cleared"}', "cleared", id="cleared"),
        pytest.param(None, "attributable_to_v4", id="pinned"),  # bytes filled in below
        pytest.param(b"an-unattributable-legacy-value", "halts_all", id="halts_all"),
    ],
)
def test_status_is_lock_free_read_only_while_the_flock_is_held_and_reports_legacy_state(
    tmp_path: Path, raw: bytes | None, expected_legacy: str,
) -> None:
    """EDGE-3 test 24 (AC-8): `--status` succeeds while the node holds the
    flock (a lock-free `mode=ro` read), for all four legacy classes, and
    never mutates the store."""
    if expected_legacy == "attributable_to_v4":
        raw = _fixture_bytes_for_status_test()
    store_path = tmp_path / "state.db"
    store = SqliteStateStore(store_path)
    if raw is not None:
        store.set(LEGACY_FAMILY_HALT_KEY, raw)

    before = store_path.read_bytes()
    stdout = io.StringIO()
    with open_submit_intent_latch(store, store_path):
        code = _run(
            ["--status"],
            store_path,
            stdout=stdout,
            positions_reader=lambda: (_ for _ in ()).throw(
                AssertionError("--status must never call the positions reader"),
            ),
        )
    after = store_path.read_bytes()
    store.close()

    assert code == EXIT_OK
    assert f"legacy={expected_legacy}" in stdout.getvalue()
    assert before == after


def _fixture_bytes_for_status_test() -> bytes:
    return (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "family_halt"
        / "legacy_v4_halt_2026-09-24.bin"
    ).read_bytes()


# ---------------------------------------------------------------------------
# cwd independence (2026-10-05: a systemd unit ran the CLI with cwd=/home/jon)
# ---------------------------------------------------------------------------


def test_set_family_halt_resolves_manifest_independent_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    foreign = tmp_path / "foreign_cwd"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    assert not Path("deploy/families").exists()

    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
    )

    assert code == EXIT_OK
    assert _is_halted(store_path)


def test_status_works_from_foreign_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    foreign = tmp_path / "foreign_cwd"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    out = io.StringIO()

    code = _run(["--status"], store_path, stdout=out)

    assert code == EXIT_OK
    assert "halted=False" in out.getvalue()


def test_missing_families_dir_fails_closed_rc2_never_cwd_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.strategy.current_rung_hold import family_id_arg

    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    # A decoy manifest dir in the cwd must never be picked up.
    decoy = tmp_path / "cwd" / "deploy"
    decoy.mkdir(parents=True)
    (decoy / "families").symlink_to(Path(family_id_arg._REPO_ROOT) / "deploy" / "families")
    monkeypatch.chdir(tmp_path / "cwd")
    monkeypatch.setattr(family_id_arg, "_REPO_ROOT", tmp_path / "no_such_root")
    err = io.StringIO()

    code = _run(
        ["--reason", REASON, "--evidence-path", str(_evidence_path(tmp_path))],
        store_path,
        stderr=err,
    )

    assert code == 2
    assert "families directory not found" in err.getvalue()
    assert not _is_halted(store_path)


def test_relative_evidence_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    evidence = _evidence_path(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        _run(["--reason", REASON, "--evidence-path", evidence.name], store_path)

    assert excinfo.value.code == 2
    assert "must be an absolute path" in capsys.readouterr().err
    assert not _is_halted(store_path)
