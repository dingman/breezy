"""RESTING_BID_HUNT Rev 2 §4.3 (2026-09-16): the boot never-arm walk fails
closed on the open-order enumeration.

Sequenced BEFORE any rest exists: nothing may rest that cannot be
enumerated. The walk (``continuous_strategy._run_never_arm_walk``) already
consults ``startup_evidence_permits_arm`` (``trial_day_latch.py``) for the
positions read; that single predicate now also requires the exec client's
open-order read to have SUCCEEDED and returned an EMPTY set. This file
drives the REAL strategy through the same rig
``test_continuous_rung_hold_never_arm_no_leg_2026_09_14.py`` uses, and
asserts the three outcomes the plan names:

* empty set -> arms;
* one open order -> refuses (``startup_open_orders_present``) and never arms;
* read refused (5xx / timeout / malformed) -> refuses, fail closed.

No strategy source is edited by this increment; the fixture
``_PERMISSIVE_EVIDENCE`` gained the two keys additively.
"""

from __future__ import annotations

from pathlib import Path

from nautilus_trader.model.instruments import BinaryOption

from breezy.strategy.current_rung_hold.trial_day_latch import (
    STARTUP_OPEN_ORDERS_PRESENT_REASON,
    startup_evidence_refusal_reason,
)
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
    _register_phase1_and_start,
)
from tests.unit.test_current_rung_hold_strategy import INTERIOR_ID, _instrument


def _interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


def _evidence(**overrides: object) -> dict[str, object]:
    return {**_PERMISSIVE_EVIDENCE, **overrides}


def _start(tmp_path: Path, evidence: dict[str, object]) -> object:
    return _register_phase1_and_start(
        store_path=tmp_path / "state.db",
        instruments=(_interior_instrument(),),
        position_evidence_reader=lambda: evidence,
    )


def _assert_refused_at_boot(strategy: object) -> None:
    """`on_start`'s never-arm walk halted the strategy: the evidence-missing
    counter fired once, the one summary line was emitted with no per-slug
    decision, and `on_stop` released the latch (`_latch is None`) -- so no
    later tick can arm anything through it."""
    assert strategy.position_events.count("startup_evidence_missing") == 1  # type: ignore[attr-defined]
    assert strategy.last_startup_evidence_summary is not None  # type: ignore[attr-defined]
    assert "decisions={}" in strategy.last_startup_evidence_summary  # type: ignore[attr-defined]
    assert strategy._latch is None  # type: ignore[attr-defined]


def test_an_empty_open_order_set_arms(tmp_path: Path) -> None:
    strategy = _start(tmp_path, _evidence(open_orders=[]))
    assert strategy.position_events.count("startup_evidence_missing") == 0  # type: ignore[attr-defined]
    assert strategy._latch is not None  # type: ignore[attr-defined]
    assert strategy._run_never_arm_walk() is True  # type: ignore[attr-defined]


def test_one_open_order_refuses_to_arm_with_the_named_reason(tmp_path: Path) -> None:
    evidence = _evidence(
        open_orders=[
            {
                "venue_order_id": "RESTING0001A",
                "market_slug": str(INTERIOR_ID.symbol.value),
                "state": "ORDER_STATE_NEW",
            }
        ],
    )
    assert startup_evidence_refusal_reason(evidence) == STARTUP_OPEN_ORDERS_PRESENT_REASON
    _assert_refused_at_boot(_start(tmp_path, evidence))


def test_a_foreign_slug_open_order_also_refuses(tmp_path: Path) -> None:
    """The gate is account-wide: an order on a market this strategy never
    configured is still an open order the bot cannot account for."""
    evidence = _evidence(
        open_orders=[
            {"venue_order_id": "R2", "market_slug": "tc-temp-miahigh-2026-09-16-gte91lt92f"},
        ],
    )
    _assert_refused_at_boot(_start(tmp_path, evidence))


def test_a_refused_open_order_read_refuses_to_arm(tmp_path: Path) -> None:
    """5xx / timeout / malformed body are all recorded by the exec client as
    ``open_orders_read_refused=True`` -- the walk sees one shape."""
    _assert_refused_at_boot(_start(tmp_path, _evidence(open_orders_read_refused=True)))


def test_a_record_without_open_order_fields_refuses_to_arm(tmp_path: Path) -> None:
    legacy = dict(_PERMISSIVE_EVIDENCE)
    del legacy["open_orders_read_refused"]
    del legacy["open_orders"]
    _assert_refused_at_boot(_start(tmp_path, legacy))
