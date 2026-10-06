"""AUT-4 WP2: a same-slot recompute on identical inputs yields the same `verdict_id` (P4-11)."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

from breezy.analysis.autonomy import windows
from breezy.persistence.autonomy.verdict import ActionClass, Verdict, VerdictKind, VerdictOutcome

_SLOT = windows.slot_start_ns(dt.date(2026, 10, 6), "14:45")


def _verdict(produced_at_ns: int) -> Verdict:
    return Verdict(
        kind=VerdictKind.LIVE_SEQUENTIAL,
        subject_family_id="forecast_quantile_ladder_v1",
        outcome=VerdictOutcome.UNDERPOWERED,
        detector="aut4_eval_live",
        declared_action_class=ActionClass.NONE,
        produced_at_ns=produced_at_ns,
        valid_until_ns=windows.valid_until_ns(_SLOT),
        producer_code_sha="d" * 64,
        policy_ruling_sha256="e" * 64,
        n=7,
        n_min=10,
    )


def test_recompute_same_slot_same_inputs_same_verdict_id() -> None:
    first = _verdict(_SLOT + 60 * 10**9)
    recompute = _verdict(_SLOT + 900 * 10**9)  # later start jitter, same slot, same inputs
    assert first.produced_at_ns != recompute.produced_at_ns
    assert first.verdict_id == recompute.verdict_id
    assert first.body_wire() == recompute.body_wire()


def test_a_different_input_or_slot_changes_the_verdict_id() -> None:
    base = _verdict(_SLOT)
    assert replace(base, n=8).verdict_id != base.verdict_id
    next_slot = windows.slot_start_ns(dt.date(2026, 10, 7), "14:45")
    assert (
        replace(base, valid_until_ns=windows.valid_until_ns(next_slot)).verdict_id
        != base.verdict_id
    )
