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

import pytest
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


def _flagged_order(**extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "venue_order_id": "FRGN00000001",
        "market_slug": "aec-nfl-lar-den-2026-09-27",
        "state": "ORDER_STATE_NEW",
        "own_resting": False,
        "non_weather_market": True,
    }
    row.update(extra)
    return row


def test_a_non_weather_market_open_order_does_not_refuse_to_arm(tmp_path: Path) -> None:
    """T-E1: a flagged non-weather order, with the cancel latch clear, does not refuse."""
    evidence = _evidence(
        open_orders=[_flagged_order()],
        resting_cancel_unconfirmed=False,
    )
    assert startup_evidence_refusal_reason(evidence) is None
    strategy = _start(tmp_path, evidence)
    missing = strategy.position_events.count("startup_evidence_missing")  # type: ignore[attr-defined]
    assert missing == 0
    assert strategy._latch is not None  # type: ignore[attr-defined]
    assert strategy._run_never_arm_walk() is True  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "flag",
    ["true", 1, "yes", None, "absent"],
    ids=["string-true", "one", "yes", "none", "absent"],
)
def test_a_non_weather_flag_that_is_not_exactly_true_still_refuses(flag: object) -> None:
    """T-E2 [CHAR]: only the boolean True exempts. Mutation: replace ``is True`` with truthiness."""
    order: dict[str, object] = {
        "venue_order_id": "FRGN00000001",
        "market_slug": "aec-nfl-lar-den-2026-09-27",
        "state": "ORDER_STATE_NEW",
        "own_resting": False,
    }
    if flag != "absent":
        order["non_weather_market"] = flag
    evidence = _evidence(open_orders=[order], resting_cancel_unconfirmed=False)
    assert startup_evidence_refusal_reason(evidence) == STARTUP_OPEN_ORDERS_PRESENT_REASON


def test_a_non_weather_order_does_not_mask_a_weather_order() -> None:
    """T-E3 [CHAR]: a flagged row does not exempt the weather row after it.

    Mutation: check only the first row.
    """
    weather: dict[str, object] = {
        "venue_order_id": "WTHR00000001",
        "market_slug": "tc-temp-miahigh-2026-09-16-gte91lt92f",
        "state": "ORDER_STATE_NEW",
        "own_resting": False,
    }
    evidence = _evidence(
        open_orders=[_flagged_order(market_slug="crossd-ba05d7244fbd670a"), weather],
        resting_cancel_unconfirmed=False,
    )
    assert startup_evidence_refusal_reason(evidence) == STARTUP_OPEN_ORDERS_PRESENT_REASON


def test_a_non_weather_only_book_still_honours_the_resting_cancel_latch() -> None:
    """T-E4: a flagged-only book still refuses when the cancel latch is set or unrecorded."""
    latched = _evidence(open_orders=[_flagged_order()], resting_cancel_unconfirmed=True)
    assert startup_evidence_refusal_reason(latched) == "resting_cancel_unconfirmed"
    absent = _evidence(open_orders=[_flagged_order()])
    absent.pop("resting_cancel_unconfirmed", None)
    assert startup_evidence_refusal_reason(absent) == "resting_cancel_unconfirmed"
