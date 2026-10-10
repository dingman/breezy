"""K=1 golden scenario for the submit-intent latch (EXEC-PAR WP2).

``run_k1_scenario`` drives the pre-WP2 public API through arm, retire, startup
reconcile (fill-probe path and history-repair path) with deterministic ids and
clocks, and returns the exact ordered ``(key, bytes)`` store write sequence.
The golden literal in ``test_submit_intent_slots.py`` was captured from the
code BEFORE any WP2 change.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from breezy.runtime.submit_intent import (
    RetirementReason,
    SubmitIntent,
    SubmitIntentState,
    history_key,
    open_submit_intent_latch,
)

FP_A = "9f3ac0de" + "a1b2c3d4" * 7
FP_B = "cafef00d" + "11" * 28
T0 = 1_700_000_000_000_000_000


class RecordingStore:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.writes: list[tuple[str, bytes]] = []

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.writes.append((key, value))
        self.data[key] = value


def run_k1_scenario() -> list[tuple[str, str]]:
    ids = iter(uuid.UUID(int=i) for i in range(1, 50))
    store = RecordingStore()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state.db"
        with patch("breezy.runtime.submit_intent.uuid.uuid4", lambda: next(ids)):  # noqa: SIM117
            with open_submit_intent_latch(store, path) as latch:
                a = latch.arm(FP_A, now_ns=T0)
                latch.retire(a.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=T0 + 1)
                b = latch.arm(FP_B, now_ns=T0 + 2)
                latch.retire(
                    b.intent_id,
                    RetirementReason.STATUS_REPORT_ACCEPT_FILL_TERMINAL,
                    now_ns=T0 + 3,
                )
                latch.arm(FP_A, now_ns=T0 + 4)
                latch.reconcile_at_startup(
                    has_durable_fill_record=lambda _f, _c: True, now_ns=T0 + 5
                )
                e = latch.arm(FP_B, now_ns=T0 + 6)
                crashed = SubmitIntent(
                    e.intent_id,
                    e.fingerprint,
                    e.created_ns,
                    SubmitIntentState.RETIRED,
                    T0 + 7,
                    RetirementReason.OPERATOR_CLEARED,
                )
                store.set(history_key(e.intent_id), crashed.to_bytes())
                latch.reconcile_at_startup(
                    has_durable_fill_record=lambda _f, _c: False, now_ns=T0 + 8
                )
                latch.arm(FP_A, now_ns=T0 + 9)
                latch.reconcile_at_startup(
                    has_durable_fill_record=lambda _f, _c: False, now_ns=T0 + 10
                )
    return [(k, v.decode("utf-8")) for k, v in store.writes]
