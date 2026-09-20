"""WP-B2: the submit-time permit-expiry hole, closed at the kernel chokepoint.

THE HOLE
--------
``OrderSubmissionPermit.issue`` (``runtime/order_enablement.py:207``) tests
``clock.timestamp_ns() > live_trading_permit.expires_at_ns`` **only at mint**.
Once the permit object is handed to a strategy, nothing re-checks expiry at
submit time: the strategy-side gates (``current_rung_hold/strategy.py:734``,
``continuous_strategy.py:672``) ask only ``self._order_submission_permit is
not None``. The live permit is minted once at boot with a 10 h TTL
(``PERMIT_TTL_NS``) and then lapses for ~14 h a day while the node runs
healthy, with the strategy gate still reading "granted".

WHY THE KERNEL SEAM AND NOT A PER-STRATEGY GATE (plan §B-5)
-----------------------------------------------------------
A per-strategy gate violates DRY and a new strategy simply forgets it. The
guard installed by :func:`install_live_order_guard` is already subscribed to
``events.order.*`` -- ONE subscription covering every strategy in the run,
including one added later -- and is the same seam the long-only
(``allow_short = False``) rule uses. The new rule is a third sibling of
``_refuse_post_only`` / ``_refuse_naked_short``, raising a third member of
that CLOSED refusal-class set, so the whole existing reporting path
(``_order_guard_reporter`` -> stderr + ``record_fatal_exec_fault`` + logger)
carries it with no new channel.

DEFENCE IN DEPTH, NOT A REPLACEMENT (security review §A-5)
-----------------------------------------------------------
``safety.assert_live_order_submission_permitted`` (``safety.py:940``, expiry
at ``:986``) stays AUTHORITATIVE. This guard fires EARLIER, on a different
object (the ``OrderSubmissionPermit``, not the ``LiveTradingPermit``), and is
not a reason to judge the later check redundant --
``test_the_exec_chokepoint_still_refuses_an_expired_permit_with_this_guard_passing``
pins that with this guard's rule stubbed to PASS.

NOTHING HERE EXTENDS, RENEWS OR RE-MINTS A PERMIT (security review §A-6).
The one-caller barrier on ``issue_live_trading_permit`` already exists and
stays green: ``test_polymarket_us_readonly_guard.py::
test_permit_issuer_has_no_caller_in_this_slice`` (B7), as does the TTL pin
``test_polymarket_us_permit_issuance.py::
test_the_permit_ttl_is_pinned_to_ten_hours``.

WHICH CLOCK
-----------
The guard is given the clock the surrounding path already uses -- in
production ``node.kernel.clock``, the Nautilus clock of the very node whose
message bus publishes the event being screened. No wall-clock read appears
anywhere in the new rule, for the same reason ``safety._read_clock`` refuses
one: expiry sampled from a second, unrelated time source is a second policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.events import OrderInitialized
from nautilus_trader.model.identifiers import (
    ClientOrderId,
    InstrumentId,
    StrategyId,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.model.objects import Quantity

from breezy.runtime.backtest_order_guard import (
    ORDER_EVENT_TOPIC,
    BacktestOrderGuard,
    NakedShortRefusedError,
    PermitExpiredRefusedError,
    PostOnlyRefusedError,
    install_live_order_guard,
    install_order_guard,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Sequence

INSTRUMENT = InstrumentId(Symbol("synthetic-permit-expiry-market"), Venue("POLYMARKET_US"))

#: An arbitrary, fixed permit expiry. Every clock below is placed relative to
#: THIS, never to real time, so the tests are deterministic and never read a
#: wall clock themselves.
EXPIRES_AT_NS = 1_700_000_000_000_000_000


@dataclass(frozen=True)
class _PermitWithExpiry:
    """The ONE field the guard reads off an ``OrderSubmissionPermit``.

    A real ``OrderSubmissionPermit`` is unforgeable by construction and
    obtainable only from ``issue`` (which needs the operator caps, the write
    barrier and a genuine ``LiveTradingPermit`` in the environment). The
    guard re-checks EXPIRY only -- authenticity was already established at
    mint, at the single site B11 pins -- so the narrow shape it consumes is
    exactly this. Nothing here mints, extends or renews anything.
    """

    expires_at_ns: int


class _FixedClock:
    """The ``timestamp_ns()`` surface, fixed. Mirrors ``ClockLike`` in
    ``order_enablement`` and ``SupportsTimestampNs`` in ``safety``."""

    def __init__(self, now_ns: int) -> None:
        self._now_ns = now_ns

    def timestamp_ns(self) -> int:
        return self._now_ns


class _FakePortfolio:
    def __init__(self, net: Decimal) -> None:
        self._net = net

    def net_position(self, instrument_id: InstrumentId) -> Decimal:
        del instrument_id
        return self._net


class _FakeCache:
    def orders(self, *, instrument_id: InstrumentId | None = None) -> Sequence[Any]:
        del instrument_id
        return ()

    def order(self, client_order_id: ClientOrderId) -> None:
        del client_order_id


class _FakeLiveMessageBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, Callable[[object], None]]] = []

    def subscribe(self, *, topic: str, handler: Callable[[object], None]) -> None:
        self.subscriptions.append((topic, handler))


def _initialized(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: int = 5,
    post_only: bool = False,
    client_order_id: ClientOrderId | None = None,
) -> OrderInitialized:
    return OrderInitialized(
        trader_id=TraderId("BREEZYTRADE-001"),
        strategy_id=StrategyId("EXTERNAL"),
        instrument_id=INSTRUMENT,
        client_order_id=client_order_id or ClientOrderId("O-1"),
        order_side=side,
        order_type=OrderType.MARKET,
        quantity=Quantity(quantity, 0),
        time_in_force=TimeInForce.GTC,
        post_only=post_only,
        reduce_only=False,
        quote_quantity=False,
        options={},
        emulation_trigger=0,
        trigger_instrument_id=None,
        contingency_type=0,
        order_list_id=None,
        linked_order_ids=None,
        parent_order_id=None,
        exec_algorithm_id=None,
        exec_algorithm_params=None,
        exec_spawn_id=None,
        tags=None,
        event_id=UUID4(),
        ts_init=0,
        reconciliation=False,
    )


def _guard(*, now_ns: int | None, permit: _PermitWithExpiry | None) -> BacktestOrderGuard:
    return BacktestOrderGuard(
        _FakePortfolio(Decimal(100)),
        _FakeCache(),
        order_submission_permit=permit,
        clock=None if now_ns is None else _FixedClock(now_ns),
    )


# ---------------------------------------------------------------------------
# RED-B2-1 -- an order under a LAPSED permit is refused at the kernel guard
# ---------------------------------------------------------------------------


def test_an_order_under_an_expired_permit_is_refused_at_the_kernel_guard() -> None:
    """The hole itself. One nanosecond past ``expires_at_ns`` is expired --
    the same strict ``>`` comparison ``OrderSubmissionPermit.issue`` uses at
    mint, so the guard and the mint agree on the boundary rather than
    inventing a second one."""
    guard = _guard(
        now_ns=EXPIRES_AT_NS + 1,
        permit=_PermitWithExpiry(expires_at_ns=EXPIRES_AT_NS),
    )

    with pytest.raises(PermitExpiredRefusedError) as excinfo:
        guard.on_order_event(_initialized())

    # Names the FAILED PRECONDITION and the two timestamps only -- never the
    # operator id, never a cap, never any other permit field (L-22 shape).
    message = str(excinfo.value)
    assert "expired" in message
    assert str(EXPIRES_AT_NS) in message


def test_the_expiry_boundary_is_exactly_the_mint_sites_boundary() -> None:
    """``now == expires_at_ns`` is NOT expired at mint (``>``), so it must not
    be expired here either. A ``>=`` here would refuse an order the mint would
    have permitted -- a different policy wearing the same name."""
    guard = _guard(
        now_ns=EXPIRES_AT_NS,
        permit=_PermitWithExpiry(expires_at_ns=EXPIRES_AT_NS),
    )

    guard.on_order_event(_initialized())  # must not raise


# ---------------------------------------------------------------------------
# RED-B2-2 -- a VALID permit changes nothing; behaviour stays byte-identical
# ---------------------------------------------------------------------------


def test_a_valid_permit_leaves_a_clean_order_untouched() -> None:
    guard = _guard(
        now_ns=EXPIRES_AT_NS - 1,
        permit=_PermitWithExpiry(expires_at_ns=EXPIRES_AT_NS),
    )

    guard.on_order_event(_initialized())

    assert guard.refusal_counts == {}


def test_a_valid_permit_leaves_the_two_existing_rules_byte_identical() -> None:
    """The pre-existing refusals keep their exact classes and precedence under
    a valid permit: post-only still beats naked-short, and a naked short is
    still a naked short."""
    guard = _guard(
        now_ns=EXPIRES_AT_NS - 1,
        permit=_PermitWithExpiry(expires_at_ns=EXPIRES_AT_NS),
    )

    with pytest.raises(PostOnlyRefusedError):
        guard.on_order_event(_initialized(post_only=True, side=OrderSide.SELL, quantity=9_999))
    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(_initialized(side=OrderSide.SELL, quantity=9_999))


def test_no_permit_and_no_clock_leaves_the_guard_exactly_as_it_was() -> None:
    """The shadow-mode / backtest shape: no permit object at all. The rule is
    INERT -- not "passes because the expiry is far away", but never consulted,
    because there is no permit to consult."""
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(100)), _FakeCache())

    guard.on_order_event(_initialized())

    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(_initialized(side=OrderSide.SELL, quantity=9_999))


def test_an_expired_permit_is_refused_before_the_two_order_shape_rules() -> None:
    """Authority is screened before order shape: an order submitted with NO
    authority is refused for that, not for being post-only. Otherwise the
    operator reads a fee-model complaint when the real fact is a lapsed
    permit."""
    guard = _guard(
        now_ns=EXPIRES_AT_NS + 1,
        permit=_PermitWithExpiry(expires_at_ns=EXPIRES_AT_NS),
    )

    with pytest.raises(PermitExpiredRefusedError):
        guard.on_order_event(_initialized(post_only=True, side=OrderSide.SELL, quantity=9_999))


# ---------------------------------------------------------------------------
# RED-B2-3 -- the refusal is COUNTED and VISIBLE, never a silent no-op
# ---------------------------------------------------------------------------


def test_a_permit_expiry_refusal_is_counted_on_the_guard() -> None:
    """A silent refusal is how the 2026-09-17 halt hid for three days. The
    count is keyed by the refusal CLASS NAME -- a closed set of exactly three
    -- never by free text composed from a value."""
    guard = _guard(
        now_ns=EXPIRES_AT_NS + 1,
        permit=_PermitWithExpiry(expires_at_ns=EXPIRES_AT_NS),
    )

    for index in range(3):
        with pytest.raises(PermitExpiredRefusedError):
            guard.on_order_event(_initialized(client_order_id=ClientOrderId(f"O-{index}")))

    assert guard.refusal_counts == {"PermitExpiredRefusedError": 3}


def test_the_existing_refusals_are_counted_in_the_same_closed_set() -> None:
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())

    with pytest.raises(PostOnlyRefusedError):
        guard.on_order_event(_initialized(post_only=True, client_order_id=ClientOrderId("O-a")))
    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(
            _initialized(side=OrderSide.SELL, quantity=1, client_order_id=ClientOrderId("O-b")),
        )

    assert guard.refusal_counts == {
        "PostOnlyRefusedError": 1,
        "NakedShortRefusedError": 1,
    }
    assert set(guard.refusal_counts) <= {
        "PermitExpiredRefusedError",
        "PostOnlyRefusedError",
        "NakedShortRefusedError",
    }


def test_a_live_permit_expiry_refusal_reaches_the_existing_reporter() -> None:
    """Visibility on the LIVE path: the SAME ``on_refusal`` channel the other
    two refusals already use (stderr + the fatal-exec latch + the logger), so
    the run cannot end in ``EXIT_OK`` while orders were being refused."""
    msgbus = _FakeLiveMessageBus()
    reported: list[ValueError] = []

    install_live_order_guard(
        _FakePortfolio(Decimal(100)),
        _FakeCache(),
        msgbus,
        on_refusal=reported.append,
        order_submission_permit=_PermitWithExpiry(expires_at_ns=EXPIRES_AT_NS),
        clock=_FixedClock(EXPIRES_AT_NS + 1),
    )
    topic, handler = msgbus.subscriptions[0]
    assert topic == ORDER_EVENT_TOPIC

    with pytest.raises(PermitExpiredRefusedError) as excinfo:
        handler(_initialized())

    assert len(reported) == 1
    assert reported[0] is excinfo.value


def test_the_live_installer_still_defaults_to_no_permit() -> None:
    """Shadow mode: ``install_live_order_guard`` without a permit installs a
    guard whose expiry rule is inert, exactly as before this work package."""
    msgbus = _FakeLiveMessageBus()

    guard = install_live_order_guard(
        _FakePortfolio(Decimal(100)),
        _FakeCache(),
        msgbus,
        on_refusal=lambda exc: None,
    )
    _, handler = msgbus.subscriptions[0]

    handler(_initialized())
    assert guard.refusal_counts == {}


# ---------------------------------------------------------------------------
# RED-B2-4 -- chokepoint independence (security review constraint 1)
# ---------------------------------------------------------------------------


def test_the_exec_chokepoint_still_refuses_an_expired_permit_with_this_guard_passing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``safety.py:986`` stays AUTHORITATIVE.

    The new guard is stubbed to PASS unconditionally -- i.e. the entire
    defence-in-depth layer is removed -- and
    ``assert_live_order_submission_permitted`` must STILL refuse an expired
    ``LiveTradingPermit``. Moving enforcement earlier must never make the
    later check judgeable as redundant.
    """
    from breezy.adapters.polymarket_us.safety import (
        MAX_ORDER_NOTIONAL_USD_ENV_VAR,
        OPERATOR_ID_ENV_VAR,
        SESSION_NOTIONAL_USD_ENV_VAR,
        SESSION_ORDER_COUNT_ENV_VAR,
        TRADING_ENABLED_ENV_VAR,
        LiveTradingPermissionError,
        assert_live_order_submission_permitted,
        issue_live_trading_permit,
    )
    from breezy.adapters.polymarket_us.safety import (
        PERMIT_TTL_NS as _TTL,
    )

    monkeypatch.setenv(TRADING_ENABLED_ENV_VAR, "1")
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, "5.00")
    monkeypatch.setenv(OPERATOR_ID_ENV_VAR, "operator@example.com")
    monkeypatch.setenv(SESSION_NOTIONAL_USD_ENV_VAR, "50.00")
    monkeypatch.setenv(SESSION_ORDER_COUNT_ENV_VAR, "10")

    issued_at_ns = EXPIRES_AT_NS
    permit = issue_live_trading_permit(clock=_FixedClock(issued_at_ns))

    # The guard's rule, stubbed to PASS -- the layer is gone.
    monkeypatch.setattr(
        BacktestOrderGuard,
        "_refuse_expired_permit",
        lambda self, event: None,
    )
    guard = _guard(
        now_ns=issued_at_ns + _TTL + 1,
        permit=_PermitWithExpiry(expires_at_ns=issued_at_ns + _TTL),
    )
    guard.on_order_event(_initialized())  # the stub lets it through

    class _Credentials:
        def is_complete(self) -> bool:
            return True

    with pytest.raises(LiveTradingPermissionError, match="expired"):
        assert_live_order_submission_permitted(
            credentials=_Credentials(),  # type: ignore[arg-type]
            permit=permit,
            manual_order_indicator=False,
            order_notional_usd=Decimal("1.00"),
            request_fingerprint=b"wp-b2-chokepoint-independence",
            now_ns=issued_at_ns + _TTL + 1,
        )


# ---------------------------------------------------------------------------
# RED-B2-5 -- backtest PERMIT ISOLATION is preserved (constraint 2)
# ---------------------------------------------------------------------------


def test_the_backtest_strategy_override_stays_permit_object_free() -> None:
    """``ContinuousRungHoldBacktestStrategy`` overrides
    ``_has_order_submission_permit`` with a PRIVATE FLAG and no permit object.
    This work package must not push it toward a synthetic ``expires_at_ns``:
    manufacturing a permit shape in backtest is precisely the isolation this
    pins.
    """
    import inspect

    from breezy.strategy.current_rung_hold.continuous_backtest_only import (
        ContinuousRungHoldBacktestStrategy,
    )

    source = inspect.getsource(ContinuousRungHoldBacktestStrategy)
    assert "expires_at_ns" not in source
    assert "_PermitWithExpiry" not in source
    # The subclass exposes no ``order_submission_permit`` parameter at all,
    # and constructs the parent with ``order_submission_permit=None``.
    assert "order_submission_permit=None" in source
    signature = inspect.signature(ContinuousRungHoldBacktestStrategy.__init__)
    assert "order_submission_permit" not in signature.parameters


def test_the_backtest_installer_installs_a_guard_with_no_permit() -> None:
    """``install_order_guard`` (the BACKTEST installer) grows no permit
    parameter: a backtest has no permit and must never be given a synthetic
    one."""
    import inspect

    signature = inspect.signature(install_order_guard)
    assert list(signature.parameters) == ["engine"]


# ---------------------------------------------------------------------------
# RED-B2-6 -- nothing here re-mints, extends or renews (constraint 3)
# ---------------------------------------------------------------------------


def test_the_guard_module_never_mints_or_extends_a_permit() -> None:
    """The TTL pin (``test_the_permit_ttl_is_pinned_to_ten_hours``) and the
    one-caller barrier (``test_permit_issuer_has_no_caller_in_this_slice``,
    B7) both stay green because this module does not touch either: no mint,
    no TTL arithmetic, no write to an ``expires_at_ns``."""
    import ast
    import inspect

    from breezy.runtime import backtest_order_guard

    source = inspect.getsource(backtest_order_guard)
    tree = ast.parse(source)

    # No CALL to the issuer, and no IMPORT of the TTL -- an AST walk rather
    # than a substring scan, so the prose above (which names both, because
    # explaining the hole requires naming them) cannot trip it and a real
    # re-mint cannot hide inside a docstring-shaped string either.
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "issue_live_trading_permit" not in called

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "PERMIT_TTL_NS" not in imported

    # Nothing ASSIGNS an expiry: no ``permit.expires_at_ns = ...``, no
    # ``replace(permit, expires_at_ns=...)``. The rule reads the field and
    # never writes it.
    assigned = {
        target.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
    }
    assert "expires_at_ns" not in assigned
    assert "replace" not in called
