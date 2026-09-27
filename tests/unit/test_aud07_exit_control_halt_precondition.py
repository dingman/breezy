"""AUD-07 step 7c: the halt-state precondition for the positive control
(read-only; builds and sends no order).

``read_exit_control_halt_precondition`` (``breezy.runtime.
exit_control_precondition``) is the sender-global halt-state read the
registration package's pre-control checklist gains (plan
``AUD-07-exit-seam-arming-verification-path.md`` §7 step 7c). It reuses
``read_continuous_family_store_state`` (``trade_supervisor.py``) and the
``FAMILY_HALT_KEY`` / ``CONTINUOUS_FAMILY_HALT_KEY`` the exit veto
(``exit_wiring.submit_exit``) and the strategy-layer latch already read and
write -- never a new mechanism, new key, or new veto.

Fixtures are built through the REAL writer path: ``open_submit_intent_latch``
-> ``open_trial_day_latch(CONTINUOUS_TRIAL_KEY_PREFIX)`` -> ``record_policy_
halt`` / ``clear_family_halt``, mirroring ``tests/unit/
test_set_family_halt_cli.py``.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from breezy.runtime.exit_control_precondition import (
    BLOCKED_FAMILY_HALT_SET,
    BLOCKED_HALT_STATE_UNREADABLE,
    HALT_CLEAR_NEXT_PRECONDITION,
    read_exit_control_halt_precondition,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.runtime.trade_supervisor_core import CONTINUOUS_LEGACY_FAMILY_HALT_KEY
from breezy.strategy.current_rung_hold.exit_wiring import _DIAG_FAMILY_HALT, submit_exit
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    LEGACY_FAMILY_HALT_KEY,
    open_trial_day_latch,
)

REASON = "AUD-07 step 7c: halt-state precondition fixture"


def _seed_open_submit_intent_and_close(store_path: Path) -> None:
    SqliteStateStore(store_path).close()


class _FakeDiagnostics:
    def __init__(self) -> None:
        self.recorded: list[str] = []

    def record(self, name: str) -> None:
        self.recorded.append(name)


class _FakeExitStrategy:
    """Minimal duck-typed stand-in for ``ContinuousRungHoldStrategy``,
    exercising the REAL ``exit_wiring.submit_exit`` function -- mirrors
    ``tests/unit/test_set_family_halt_cli.py::_FakeExitStrategy``. Only the
    fields the HALTED branch touches are populated; it returns before ever
    reaching ``proposal``/cache/instrument/position."""

    def __init__(self, latch: object) -> None:
        self._latch = latch
        self.diagnostics = _FakeDiagnostics()
        self.diagnostics_alerter = None
        self.order_submitted = False

    def _report_alerter(self, alerter: object, fail_message: str) -> tuple[object, ...]:
        return ()

    def submit_order(self, order: object, *, position_id: object) -> None:
        self.order_submitted = True


def test_the_positive_control_precondition_reads_the_sender_global_family_halt_state(
    tmp_path: Path,
) -> None:
    """EDGE-3 (AC-2): each family now reads its OWN per-family key, so a
    fresh store reads BOTH families as unhalted -- but they are no longer
    the SAME key (that cardinality-1 assumption is exactly what EDGE-3
    retires); ``halt_key`` legitimately differs between the two."""
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)

    reading_v4 = read_exit_control_halt_precondition(store_path, "pm_us_crh_v4", now_ns=1)
    reading_exit_v4 = read_exit_control_halt_precondition(
        store_path, "pm_us_crh_exit_v4", now_ns=1,
    )

    assert reading_v4.verdict == reading_exit_v4.verdict == HALT_CLEAR_NEXT_PRECONDITION
    assert reading_v4.halt_key != reading_exit_v4.halt_key


def test_a_set_family_halt_blocks_the_positive_control_as_BLOCKED_FAMILY_HALT_SET_not_as_a_failure(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(
        intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
    )
        trial_latch.record_policy_halt(reason=REASON, evidence_sha256="0" * 64, ts_ns=1)
    store.close()

    reading = read_exit_control_halt_precondition(store_path, "pm_us_crh_v4", now_ns=2)

    assert reading.verdict == BLOCKED_FAMILY_HALT_SET


def test_the_halt_precondition_reads_the_same_FAMILY_HALT_KEY_the_exit_veto_reads(
    tmp_path: Path,
) -> None:
    assert CONTINUOUS_LEGACY_FAMILY_HALT_KEY == LEGACY_FAMILY_HALT_KEY

    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(
        intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
    )
        trial_latch.record_policy_halt(reason=REASON, evidence_sha256="0" * 64, ts_ns=1)

        fake_strategy = _FakeExitStrategy(trial_latch)
        submit_exit(fake_strategy, None)  # type: ignore[arg-type]
        assert fake_strategy.order_submitted is False
        assert fake_strategy.diagnostics.recorded == [_DIAG_FAMILY_HALT]

        reading_blocked = read_exit_control_halt_precondition(store_path, "pm_us_crh_v4", now_ns=1)
        assert reading_blocked.verdict == BLOCKED_FAMILY_HALT_SET

        trial_latch.clear_family_halt(reason=REASON, evidence_sha256="0" * 64, ts_ns=2)

        assert trial_latch.is_family_halted() is False
        reading_clear = read_exit_control_halt_precondition(store_path, "pm_us_crh_v4", now_ns=2)
        assert reading_clear.verdict == HALT_CLEAR_NEXT_PRECONDITION
    store.close()


def test_corrupt_halt_bytes_read_as_blocked(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):
        store.set(LEGACY_FAMILY_HALT_KEY, b"not-valid-json{{{")
    store.close()

    reading = read_exit_control_halt_precondition(store_path, "pm_us_crh_v4", now_ns=3)

    assert reading.verdict == BLOCKED_FAMILY_HALT_SET


def test_the_cleared_sentinel_reads_as_halt_clear(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(
        intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
    )
        trial_latch.record_policy_halt(reason=REASON, evidence_sha256="0" * 64, ts_ns=1)
        trial_latch.clear_family_halt(reason=REASON, evidence_sha256="0" * 64, ts_ns=2)
    store.close()

    reading = read_exit_control_halt_precondition(store_path, "pm_us_crh_v4", now_ns=4)

    assert reading.verdict == HALT_CLEAR_NEXT_PRECONDITION


def test_the_precondition_performs_no_write(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(
        intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
    )
        trial_latch.record_policy_halt(reason=REASON, evidence_sha256="0" * 64, ts_ns=1)
    store.close()

    before = hashlib.sha256(store_path.read_bytes()).hexdigest()
    read_exit_control_halt_precondition(store_path, "pm_us_crh_v4", now_ns=5)
    read_exit_control_halt_precondition(store_path, "pm_us_crh_exit_v4", now_ns=6)
    after = hashlib.sha256(store_path.read_bytes()).hexdigest()

    assert before == after


def test_the_module_imports_no_order_or_strategy_surface() -> None:
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src" / "breezy" / "runtime" / "exit_control_precondition.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    banned_prefixes = ("breezy.strategy", "breezy.adapters")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            assert not node.module.startswith(banned_prefixes), node.module
            assert "order" not in node.module.lower(), node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(banned_prefixes), alias.name


def test_BLOCKED_HALT_STATE_UNREADABLE_fires_when_the_reader_raises(tmp_path: Path) -> None:
    store_path = tmp_path / "unreadable.db"
    store_path.touch()  # exists, so the missing-path guard does not short-circuit the reader

    def _raising_reader(path: Path, sending_family_id: str) -> object:
        raise RuntimeError("simulated unreadable store")

    reading = read_exit_control_halt_precondition(
        store_path, "pm_us_crh_v4", now_ns=7, reader=_raising_reader,
    )

    assert reading.verdict == BLOCKED_HALT_STATE_UNREADABLE


def test_a_nonexistent_store_path_is_BLOCKED_HALT_STATE_UNREADABLE_and_creates_nothing(
    tmp_path: Path,
) -> None:
    """The reused `read_continuous_family_store_state` opens
    `SqliteStateStore`, which `mkdir(parents=True)`s and `CREATE TABLE IF
    NOT EXISTS`s -- so a wrong/non-existent path would otherwise be
    silently treated as a fresh, unhalted store (fail-open: "clear" for a
    path that names nothing). The precondition must refuse to call the
    reader at all in that case, and must create neither the parent
    directory nor the file.
    """
    missing_parent = tmp_path / "does-not-exist-yet"
    store_path = missing_parent / "state.db"

    reading = read_exit_control_halt_precondition(store_path, "pm_us_crh_v4", now_ns=8)

    assert reading.verdict == BLOCKED_HALT_STATE_UNREADABLE
    assert not store_path.exists()
    assert not missing_parent.exists()


def test_self_check_and_aud07_are_per_family_and_block_every_family_on_unpinned_legacy(
    tmp_path: Path,
) -> None:
    """EDGE-3 test 27 (r1 36+38): both the self-check's own store-state
    reader (`read_continuous_family_store_state`) and AUD-07's precondition
    are per-family -- halting family A never blocks family B -- and an
    unpinned legacy value fails closed for EVERY family on both readers."""
    from breezy.runtime.trade_supervisor import read_continuous_family_store_state

    store_path = tmp_path / "state.db"
    _seed_open_submit_intent_and_close(store_path)
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        latch_a = open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
        )
        latch_a.record_policy_halt(reason=REASON, evidence_sha256="0" * 64, ts_ns=1)
    store.close()

    # AUD-07: A is blocked, B is not.
    reading_a = read_exit_control_halt_precondition(store_path, "pm_us_crh_v4", now_ns=10)
    reading_b = read_exit_control_halt_precondition(store_path, "pm_us_crh_exit_v4", now_ns=10)
    assert reading_a.verdict == BLOCKED_FAMILY_HALT_SET
    assert reading_b.verdict == HALT_CLEAR_NEXT_PRECONDITION

    # Self-check: same isolation, through the runtime's own store reader.
    state_a = read_continuous_family_store_state(store_path, "pm_us_crh_v4")
    state_b = read_continuous_family_store_state(store_path, "pm_us_crh_exit_v4")
    assert state_a.family_halted is True
    assert state_b.family_halted is False

    # Now write an unpinned legacy value -- both families, both readers,
    # both report blocked/halted.
    store2 = SqliteStateStore(store_path)
    store2.set(LEGACY_FAMILY_HALT_KEY, b"an-unattributable-legacy-value")
    store2.close()

    for family_id in ("pm_us_crh_v4", "pm_us_crh_exit_v4"):
        reading = read_exit_control_halt_precondition(store_path, family_id, now_ns=11)
        assert reading.verdict == BLOCKED_FAMILY_HALT_SET, family_id
        state = read_continuous_family_store_state(store_path, family_id)
        assert state.family_halted is True, family_id
        assert state.family_halt_source == "legacy_halts_all", family_id
