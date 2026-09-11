"""D1/D2 (plan rev 6.1): giving back a permit slot a no-fill IOC never spent.

``restore_live_trading_budget``/``unrestore_live_trading_budget`` are the
mechanism ``PolymarketUSExecutionClient._resolve_terminal_zero``/
``_resolve_accept_fill`` use to true a GET-confirmed terminal-zero's permit
spend-down back to what it actually cost (Resolution D), and to reverse that
exact restore if a later pass discovers the order actually filled
(Resolution D2). ``safety.py`` stores nothing of its own: idempotency is a
process-local registry, and the durable audit marker
(``exec/polymarket_us/budget_restore/{venue_order_id}``) is written by the
CALLER, in ``client.py``.
"""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us import safety
from breezy.adapters.polymarket_us.safety import (
    LiveTradingPermissionError,
    LiveTradingPermit,
    assert_live_order_submission_permitted,
    restore_live_trading_budget,
    unrestore_live_trading_budget,
)
from tests.unit.test_polymarket_us_permit_issuance import (
    _isolate_the_permit_registries,  # noqa: F401 -- reused as a fixture
    clock_at,
    credentials,
    issued,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT_SOURCE_PATH = REPO_ROOT / "src/breezy/adapters/polymarket_us/exec/client.py"

VENUE_ORDER_ID = "V-restore-1"


@pytest.fixture(autouse=True)
def _isolate_the_restore_registry() -> Iterator[None]:
    """Mirrors ``_isolate_the_permit_registries``: this module's own
    process-local dict must not leak state between tests."""
    snapshot = dict(safety._RESTORED_BUDGET_DELTAS)
    safety._RESTORED_BUDGET_DELTAS.clear()
    yield
    safety._RESTORED_BUDGET_DELTAS.clear()
    safety._RESTORED_BUDGET_DELTAS.update(snapshot)


def _spend_one(permit: LiveTradingPermit, *, notional_usd: Decimal, fingerprint: bytes) -> None:
    assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=False,
        order_notional_usd=notional_usd,
        request_fingerprint=fingerprint,
        now_ns=clock_at().timestamp_ns(),
    )


def _tampered(permit: LiveTradingPermit, **overrides: object) -> LiveTradingPermit:
    """The pickle-laundering trick from ``test_polymarket_us_permit_issuance.py``:
    bypass ``__init__`` entirely so the returned object carries the ORIGINAL
    authenticity tag over MUTATED fields -- the shape ``_verify_authenticity``
    must refuse."""
    tampered = object.__new__(LiveTradingPermit)
    for field in dataclasses.fields(permit):
        object.__setattr__(tampered, field.name, getattr(permit, field.name))
    for name, value in overrides.items():
        object.__setattr__(tampered, name, value)
    return tampered


# ---------------------------------------------------------------------------
# D1: restore
# ---------------------------------------------------------------------------


def test_restore_gives_back_the_slot_and_notional_a_spend_took(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, order_count="2", ceiling="5.00", session_notional="10.00")
    _spend_one(permit, notional_usd=Decimal("1.00"), fingerprint=b"fp-1")
    assert safety.live_trading_budget_remaining(permit) == (Decimal("9.00"), 1)

    applied = restore_live_trading_budget(
        permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("1.00"),
    )

    assert applied is True
    assert safety.live_trading_budget_remaining(permit) == (Decimal("10.00"), 2)


def test_a_second_restore_for_the_same_venue_order_id_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, order_count="2", ceiling="5.00", session_notional="10.00")
    _spend_one(permit, notional_usd=Decimal("1.00"), fingerprint=b"fp-1")

    first = restore_live_trading_budget(
        permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("1.00"),
    )
    after_first = safety.live_trading_budget_remaining(permit)
    second = restore_live_trading_budget(
        permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("1.00"),
    )

    assert (first, second) == (True, False)
    assert safety.live_trading_budget_remaining(permit) == after_first == (Decimal("10.00"), 2)


def test_restore_clamps_to_the_permits_issued_budget_never_past_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A far larger amount handed back than was ever spent must still land
    exactly on the permit's OWN issued ceiling, never beyond it."""
    permit = issued(monkeypatch, order_count="1", ceiling="5.00", session_notional="2.00")
    _spend_one(permit, notional_usd=Decimal("2.00"), fingerprint=b"fp-1")
    assert safety.live_trading_budget_remaining(permit) == (Decimal("0.00"), 0)

    restore_live_trading_budget(
        permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("999.00"),
    )

    assert safety.live_trading_budget_remaining(permit) == (Decimal("2.00"), 1)


def test_restore_raises_for_a_permit_unknown_to_this_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, order_count="2", ceiling="5.00", session_notional="10.00")
    safety._PERMIT_BUDGETS.pop(permit.permit_id)

    with pytest.raises(LiveTradingPermissionError, match="unknown to this process"):
        restore_live_trading_budget(
            permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("1.00"),
        )


def test_restore_raises_for_a_permit_whose_authenticity_was_tampered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, order_count="2", ceiling="5.00", session_notional="10.00")
    tampered = _tampered(permit, budget_order_count=999)

    with pytest.raises(LiveTradingPermissionError, match="not issued"):
        restore_live_trading_budget(
            permit=tampered, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("1.00"),
        )


# ---------------------------------------------------------------------------
# D2: unrestore
# ---------------------------------------------------------------------------


def test_unrestore_returns_exactly_to_the_pre_restore_value_even_after_a_clamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, order_count="1", ceiling="5.00", session_notional="2.00")
    _spend_one(permit, notional_usd=Decimal("2.00"), fingerprint=b"fp-1")
    pre_restore = safety.live_trading_budget_remaining(permit)
    restore_live_trading_budget(
        permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("999.00"),
    )
    assert safety.live_trading_budget_remaining(permit) != pre_restore

    reversed_ = unrestore_live_trading_budget(
        permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("999.00"),
    )

    assert reversed_ is True
    assert safety.live_trading_budget_remaining(permit) == pre_restore


def test_unrestore_ignores_its_own_notional_argument_and_reverses_the_recorded_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signature symmetry with ``restore`` does not mean the passed amount is
    what gets subtracted -- only the RECORDED, already-clamped delta is."""
    permit = issued(monkeypatch, order_count="2", ceiling="5.00", session_notional="10.00")
    _spend_one(permit, notional_usd=Decimal("1.00"), fingerprint=b"fp-1")
    pre_restore = safety.live_trading_budget_remaining(permit)
    restore_live_trading_budget(
        permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("1.00"),
    )

    unrestore_live_trading_budget(
        permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("1000000.00"),
    )

    assert safety.live_trading_budget_remaining(permit) == pre_restore


def test_unrestore_for_an_id_never_restored_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    permit = issued(monkeypatch, order_count="2", ceiling="5.00", session_notional="10.00")
    before = safety.live_trading_budget_remaining(permit)

    result = unrestore_live_trading_budget(
        permit=permit, venue_order_id="never-restored", order_notional_usd=Decimal("1.00"),
    )

    assert result is False
    assert safety.live_trading_budget_remaining(permit) == before


def test_unrestore_raises_for_a_permit_unknown_to_this_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, order_count="2", ceiling="5.00", session_notional="10.00")
    safety._PERMIT_BUDGETS.pop(permit.permit_id)

    with pytest.raises(LiveTradingPermissionError, match="unknown to this process"):
        unrestore_live_trading_budget(
            permit=permit, venue_order_id=VENUE_ORDER_ID, order_notional_usd=Decimal("1.00"),
        )


# ---------------------------------------------------------------------------
# D2: the AST pin -- `restore_live_trading_budget` is called from exactly
# `_resolve_terminal_zero`, never from a REJECT/AMBIGUOUS/deny-after-assert/
# ACCEPT_FILL branch.
# ---------------------------------------------------------------------------


def _functions_calling_bare_name(name: str, source: str) -> set[str]:
    """Every ``def``/``async def`` whose body directly calls the bare name
    ``name`` (a plain ``Name`` callee, e.g. ``restore_live_trading_budget(...)``,
    never a ``self.``-qualified attribute)."""
    tree = ast.parse(source)
    callers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == name
            ):
                callers.add(node.name)
    return callers


def test_restore_live_trading_budget_is_called_from_exactly_the_terminal_zero_site() -> None:
    source = CLIENT_SOURCE_PATH.read_text(encoding="utf-8")
    assert _functions_calling_bare_name("restore_live_trading_budget", source) == {
        "_resolve_terminal_zero",
    }


@pytest.mark.parametrize(
    "planted_in",
    ["_cancel_order", "_submit_order", "_resolve_accept_fill"],
)
def test_a_restore_call_planted_outside_terminal_zero_breaks_the_pin(planted_in: str) -> None:
    """Non-vacuity: a call in any REJECT/AMBIGUOUS/deny-after-assert/
    ACCEPT_FILL-shaped branch must fail this pin, proving it looks at call
    SITES and not merely at whether the name appears anywhere in the module."""
    planted = (
        '"""Docstring."""\n\n\n'
        f"def {planted_in}(self, command):\n"
        "    restore_live_trading_budget(\n"
        "        permit=self._permit, venue_order_id='x', order_notional_usd=0,\n"
        "    )\n"
    )
    found = _functions_calling_bare_name("restore_live_trading_budget", planted)
    assert found == {planted_in}
    assert found != {"_resolve_terminal_zero"}
