"""S4 WP2 (ARM maker-sharp B3): the two resting retirement reasons.

``ACCEPTED_RESTING`` and ``BOOT_SWEEP_RESTING_NO_FILL`` are written by a NODE
only after the supervisor advertises them (supervisor-first, L-48): an older
supervisor decoding a RETIRED singleton with an unknown member raises
``SubmitIntentCorrupt``, reads it as OPEN and refuses every launch. This module
pins the vocabulary half: the enum rows, the ``RETIRE_*`` names the submit chain
emits, the supervisor marker that advertises them, and the round trips.

The runtime admission guards (``_resting_accept_admitted`` and
``_sweep_retire_admitted``) live in ``exec/client.py`` and land with the
client slices; they are NOT tested here.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    RetirementReason,
    SubmitIntent,
    SubmitIntentState,
    history_key,
    open_submit_intent_latch,
)
from breezy.runtime.supervisor_decode_marker import (
    supervisor_admits_retirement_reason,
    supervisor_decode_marker_path,
    write_supervisor_decode_marker,
)
from tests.unit.test_retirement_reason_superset import emitted_reason_names

FINGERPRINT = "9f3ac0de" + "a1b2c3d4" * 7
NOW_NS = 1_700_000_000_000_000_000
NEW_REASONS = ("ACCEPTED_RESTING", "BOOT_SWEEP_RESTING_NO_FILL")

#: The reasons that existed before this change. The set is EQUALITY-pinned so a
#: ninth, tenth or eleventh member cannot slip in beside the two reviewed ones.
PRIOR_REASONS = frozenset(
    {
        "DEFINITIVE_REJECT",
        "ACCEPTED_WITH_DURABLE_FILL",
        "ACCEPTED_ZERO_FILL_TERMINAL",
        "STARTUP_FILL_RECORD_MATCH",
        "OPERATOR_CLEARED",
        "STATUS_REPORT_ZERO_FILL_TERMINAL",
        "STATUS_REPORT_ACCEPT_FILL_TERMINAL",
        "RESOLVER_NO_ID_NO_FILL",
    }
)

_ROOT = Path(__file__).resolve().parents[2]
_EXEC = _ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "exec"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "state" / "store.sqlite3"
    path.parent.mkdir(parents=True)
    return path


def test_retirement_reason_set_is_widened_by_exactly_two_rows() -> None:
    assert {m.value for m in RetirementReason} == PRIOR_REASONS | set(NEW_REASONS)
    assert len(RetirementReason) == len(PRIOR_REASONS) + 2


@pytest.mark.parametrize("name", NEW_REASONS)
def test_new_member_name_equals_value(name: str) -> None:
    assert RetirementReason[name].value == name


@pytest.mark.parametrize("name", NEW_REASONS)
def test_new_reason_round_trips_and_releases_the_slot(store_path: Path, name: str) -> None:
    reason = RetirementReason[name]
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as latch:
        intent = latch.arm(FINGERPRINT, now_ns=NOW_NS)
        assert latch.is_latched() is True
        retired = latch.retire(intent.intent_id, reason, now_ns=NOW_NS + 1)
        assert retired.state is SubmitIntentState.RETIRED
        assert retired.retirement_reason is reason
        assert latch.is_latched() is False
        assert SubmitIntent.from_bytes(retired.to_bytes()).retirement_reason is reason
        # the slot is genuinely free: the next intent arms
        assert latch.arm(FINGERPRINT, now_ns=NOW_NS + 2).state is SubmitIntentState.OPEN


@pytest.mark.parametrize("name", NEW_REASONS)
def test_reconcile_at_startup_leaves_a_resting_record_retired(store_path: Path, name: str) -> None:
    """OPEN current + a RETIRED history record with the new reason: the history
    bytes are copied verbatim and the latch is released (never re-opened)."""
    store = SqliteStateStore(store_path)
    reason = RetirementReason[name]
    with open_submit_intent_latch(store, store_path) as latch:
        armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
        record = SubmitIntent(
            intent_id=armed.intent_id,
            fingerprint=FINGERPRINT,
            created_ns=NOW_NS,
            state=SubmitIntentState.RETIRED,
            retired_ns=NOW_NS + 1,
            retirement_reason=reason,
        )
        store.set(history_key(armed.intent_id), record.to_bytes())

        result = latch.reconcile_at_startup(
            has_durable_fill_record=lambda *_a, **_k: False, now_ns=NOW_NS + 2
        )

        assert result is not None
        assert result.state is SubmitIntentState.RETIRED
        assert result.retirement_reason is reason
        assert store.get(CURRENT_INTENT_KEY) == record.to_bytes()
        assert latch.is_latched() is False


@pytest.mark.parametrize("name", NEW_REASONS)
def test_supervisor_marker_advertises_and_admits_the_new_reason(
    store_path: Path, name: str
) -> None:
    write_supervisor_decode_marker(store_path, revision="0123456789ab")
    payload = json.loads(supervisor_decode_marker_path(store_path).read_text())
    assert name in payload["retirement_reasons"]
    assert payload["pid"] == os.getpid()
    assert supervisor_admits_retirement_reason(store_path, name) is True


@pytest.mark.parametrize("name", NEW_REASONS)
def test_an_old_supervisor_marker_without_the_reason_does_not_admit_it(
    store_path: Path, name: str
) -> None:
    """Supervisor-first, mechanically: a marker listing only the prior reasons
    (what a not-yet-restarted supervisor wrote) must refuse the new names."""
    write_supervisor_decode_marker(store_path, revision="0123456789ab")
    marker_path = supervisor_decode_marker_path(store_path)
    payload = json.loads(marker_path.read_text())
    payload["retirement_reasons"] = sorted(PRIOR_REASONS)
    marker_path.write_text(json.dumps(payload))
    assert supervisor_admits_retirement_reason(store_path, name) is False
    assert supervisor_admits_retirement_reason(store_path, "RESOLVER_NO_ID_NO_FILL") is True


def test_submit_chain_names_the_two_reasons() -> None:
    assert submit_chain.RETIRE_ACCEPTED_RESTING == "ACCEPTED_RESTING"
    assert submit_chain.RETIRE_BOOT_SWEEP_RESTING_NO_FILL == "BOOT_SWEEP_RESTING_NO_FILL"


@pytest.mark.parametrize("name", NEW_REASONS)
def test_retirement_member_maps_the_reason_names_to_enum_members(name: str) -> None:
    assert submit_chain.retirement_member(RetirementReason, name) is RetirementReason[name]


def test_the_emitted_name_collector_sees_both_new_reasons_and_they_are_members() -> None:
    """Non-vacuity of the superset check: the collector finds the new names, and
    every one of them is a member (so the supervisor can decode it)."""
    emitted = emitted_reason_names(
        ast.parse((_EXEC / "client.py").read_text(encoding="utf-8")),
        ast.parse((_EXEC / "submit_chain.py").read_text(encoding="utf-8")),
    )
    assert set(NEW_REASONS) <= emitted
    assert emitted <= {m.value for m in RetirementReason}
