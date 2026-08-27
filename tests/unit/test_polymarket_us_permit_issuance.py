"""The live-trading permit has ONE issuer, a real expiry, and a real capability.

Authority: ``docs/plans/TRADING_SYSTEM_ARCHITECTURE.md`` §8.2 and §8.4
(revision 2, security review round 1).

THE DEFECT THIS MODULE CLOSES
-----------------------------

``LiveTradingPermit`` was a public frozen dataclass re-exported in the package
``__all__``. Anybody could self-issue an unlimited permit in one line::

    LiveTradingPermit(
        operator_id="anyone",
        max_order_notional_usd=Decimal("1e9"),
        issued_at_ns=1,
    )

So ``assert_live_order_submission_permitted`` asked *whether a permit object
exists*, never *whether the operator issued it*. The permit is the only thing
between the bot and live order submission and it was forgeable by the code it
was supposed to restrain. Two further holes travelled with it:

* ``issued_at_ns`` was validated positive at ``safety.py:28`` and then never
  read anywhere in ``src/``. A field with the shape of an expiry and none of
  its function.
* the chokepoint returned ``None``, so "never called the gate" and "called the
  gate" were indistinguishable downstream.

WHAT IS ASSERTED HERE
---------------------

* **Unforgeability** -- direct construction FAILS. Not "is discouraged".
* **No ceiling self-raise** -- the issuer takes no argument that can widen the
  spend cap, and ``dataclasses.replace`` cannot widen an issued one.
* **Real expiry** -- checked against an injected Nautilus ``Clock``, so it is
  testable without sleeping.
* **Capability** -- the chokepoint returns a single-use authorization bound to
  the request, so skipping it is a ``TypeError`` at the call site rather than
  a matter of discipline.

WHAT IS *NOT* ASSERTED, AND WHY
-------------------------------

This is not protection against hostile code running in the same interpreter.
Python offers no in-process capability isolation: the issuer's HMAC key is
reachable through ``_mint_authenticity.__closure__`` or ``gc.get_referents``
by anything already executing here. The mechanism defeats *accident*,
*mutation*, *serialisation laundering* and *replay* -- the four ways a permit
actually gets over-privileged in practice -- and nothing more.
"""

from __future__ import annotations

import ast
import dataclasses
import pickle
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.safety import (
    MAX_ORDER_NOTIONAL_USD_ENV_VAR,
    OPERATOR_ID_ENV_VAR,
    PERMIT_TTL_NS,
    SESSION_NOTIONAL_USD_ENV_VAR,
    SESSION_ORDER_COUNT_ENV_VAR,
    TRADING_ENABLED_ENV_VAR,
    LiveOrderSubmissionAuthorization,
    LiveTradingPermissionError,
    LiveTradingPermit,
    assert_live_order_submission_permitted,
    issue_live_trading_permit,
    live_trading_budget_remaining,
)
from breezy.adapters.polymarket_us.secure import RedactedSecureString

REPO_ROOT = Path(__file__).resolve().parents[2]

KEY_ID_VALUE = "pm_test_key_id_never_serialize"
SECRET_VALUE = "pm_test_secret_material_never_serialize"

#: A plausible wall-clock instant in nanoseconds (2026-08-27T00:00:00Z).
NOW_NS = 1_787_788_800_000_000_000

#: Opaque per-request binding handed to the chokepoint. Deliberately NOT an
#: HTTP method/path/body triple: ``safety.py`` is venue-touching, so barrier
#: B4 rule V1 bans write-method literals in it outright. The chokepoint takes
#: a digest the (future) egress module computes for itself.
FINGERPRINT = b"fingerprint-of-one-specific-request"
OTHER_FINGERPRINT = b"fingerprint-of-a-DIFFERENT-request"


def credentials() -> PolymarketUSCredentials:
    return PolymarketUSCredentials(
        key_id=RedactedSecureString(KEY_ID_VALUE, name="pm_key_id"),
        secret_key=RedactedSecureString(SECRET_VALUE, name="pm_secret_key"),
    )


def enable_operator_gate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ceiling: str = "5.00",
    enabled: str = "1",
    operator_id: str = "operator@example.com",
    session_notional: str = "1000.00",
    order_count: str = "100",
) -> None:
    """Set exactly what a real operator sets, and nothing else."""
    monkeypatch.setenv(TRADING_ENABLED_ENV_VAR, enabled)
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, ceiling)
    monkeypatch.setenv(OPERATOR_ID_ENV_VAR, operator_id)
    monkeypatch.setenv(SESSION_NOTIONAL_USD_ENV_VAR, session_notional)
    monkeypatch.setenv(SESSION_ORDER_COUNT_ENV_VAR, order_count)


@pytest.fixture(autouse=True)
def _isolate_the_permit_registries() -> Iterator[None]:
    """Snapshot and restore both module-global registries around every test.

    Without this, a test that mints a permit leaves a live nonce and a live
    budget entry behind, so ordering changes what later tests observe -- and
    the pruning path is never exercised from a known state.
    """
    from breezy.adapters.polymarket_us import safety

    nonces = dict(safety._UNSPENT_NONCES)
    budgets = dict(safety._PERMIT_BUDGETS)
    safety._UNSPENT_NONCES.clear()
    safety._PERMIT_BUDGETS.clear()
    try:
        yield
    finally:
        safety._UNSPENT_NONCES.clear()
        safety._UNSPENT_NONCES.update(nonces)
        safety._PERMIT_BUDGETS.clear()
        safety._PERMIT_BUDGETS.update(budgets)


def clock_at(now_ns: int = NOW_NS) -> TestClock:
    clock = TestClock()
    clock.set_time(now_ns)
    return clock


def issued(monkeypatch: pytest.MonkeyPatch, **kwargs: str) -> LiveTradingPermit:
    enable_operator_gate(monkeypatch, **kwargs)
    return issue_live_trading_permit(clock=clock_at())


# ==========================================================================
# THE test: a forged permit is REFUSED
# ==========================================================================


def test_a_hand_constructed_permit_cannot_be_built_at_all() -> None:
    """The one-line forgery from the defect report must raise, not succeed."""
    with pytest.raises(LiveTradingPermissionError, match="issue_live_trading_permit"):
        LiveTradingPermit(
            operator_id="anyone",
            max_order_notional_usd=Decimal("1e9"),
            issued_at_ns=1,
            expires_at_ns=2,
            permit_id=b"0123456789abcdef",
            budget_notional_usd=Decimal("1e9"),
            budget_order_count=1000,
            authenticity=b"forged",
        )


def test_a_forged_permit_that_evades_construction_is_refused_at_use() -> None:
    """Construction is not the only entry: ``__init__`` can be bypassed.

    ``object.__new__`` plus ``object.__setattr__`` builds a structurally valid
    frozen-slots instance without ever running ``__post_init__``. If the
    chokepoint trusted the object it was handed, this would authorise a $1e9
    order. Verification therefore happens at USE, not only at construction.
    """
    forged = object.__new__(LiveTradingPermit)
    for field, value in (
        ("operator_id", "anyone"),
        ("max_order_notional_usd", Decimal("1e9")),
        ("issued_at_ns", NOW_NS),
        ("expires_at_ns", NOW_NS + PERMIT_TTL_NS),
        ("permit_id", b"0123456789abcdef"),
        ("budget_notional_usd", Decimal("1e9")),
        ("budget_order_count", 1000),
        ("authenticity", b"forged"),
    ):
        object.__setattr__(forged, field, value)

    with pytest.raises(LiveTradingPermissionError, match="not issued"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=forged,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1000000.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )


def test_an_issued_permit_cannot_have_its_ceiling_raised_by_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``dataclasses.replace`` is the quiet way to widen a frozen ceiling.

    It re-runs ``__init__`` with the *existing* authenticity tag, so a token
    carried as a plain field would travel with the mutation. The tag is an
    HMAC over the permit's own fields, which is what makes the mutation fail.
    """
    permit = issued(monkeypatch, ceiling="5.00")

    with pytest.raises(LiveTradingPermissionError, match="issue_live_trading_permit"):
        dataclasses.replace(permit, max_order_notional_usd=Decimal("1e9"))


def test_an_issued_permit_cannot_be_laundered_through_pickle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pickle bypasses ``__init__``; the use-time check is what catches it."""
    permit = issued(monkeypatch, ceiling="5.00")

    round_tripped = pickle.loads(pickle.dumps(permit))
    tampered = object.__new__(LiveTradingPermit)
    for field in dataclasses.fields(round_tripped):
        object.__setattr__(tampered, field.name, getattr(round_tripped, field.name))
    object.__setattr__(tampered, "max_order_notional_usd", Decimal("1e9"))

    with pytest.raises(LiveTradingPermissionError, match="not issued"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=tampered,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1000000.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )


# ==========================================================================
# Single issuer, driven only by operator-supplied enablement
# ==========================================================================


def test_the_issuer_refuses_when_the_operator_gate_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TRADING_ENABLED_ENV_VAR, raising=False)
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, "5.00")
    monkeypatch.setenv(OPERATOR_ID_ENV_VAR, "operator@example.com")

    with pytest.raises(LiveTradingPermissionError, match=TRADING_ENABLED_ENV_VAR):
        issue_live_trading_permit(clock=clock_at())


@pytest.mark.parametrize("value", ["", "0", "true", "TRUE", "yes", "on", "2", " 1", "1 "])
def test_only_the_exact_string_one_enables_trading(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    """No truthiness, no coercion, no inference (architecture guard N7)."""
    enable_operator_gate(monkeypatch, enabled=value)

    with pytest.raises(LiveTradingPermissionError, match=TRADING_ENABLED_ENV_VAR):
        issue_live_trading_permit(clock=clock_at())


def test_the_issuer_refuses_when_no_spend_ceiling_was_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No default ceiling exists. Absence means no trading, never a guess."""
    enable_operator_gate(monkeypatch)
    monkeypatch.delenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR)

    with pytest.raises(LiveTradingPermissionError, match=MAX_ORDER_NOTIONAL_USD_ENV_VAR):
        issue_live_trading_permit(clock=clock_at())


@pytest.mark.parametrize("value", ["0", "-1", "nan", "NaN", "Infinity", "abc", "", "1e400"])
def test_a_malformed_or_non_positive_ceiling_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    enable_operator_gate(monkeypatch, ceiling=value)

    with pytest.raises(LiveTradingPermissionError, match=MAX_ORDER_NOTIONAL_USD_ENV_VAR):
        issue_live_trading_permit(clock=clock_at())


def test_the_issuer_refuses_without_an_operator_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_operator_gate(monkeypatch, operator_id="   ")

    with pytest.raises(LiveTradingPermissionError, match=OPERATOR_ID_ENV_VAR):
        issue_live_trading_permit(clock=clock_at())


def test_the_issued_permit_carries_exactly_the_operator_supplied_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, ceiling="12.50", operator_id="ops@example.com")

    assert permit.max_order_notional_usd == Decimal("12.50")
    assert permit.operator_id == "ops@example.com"
    assert permit.issued_at_ns == NOW_NS
    assert permit.expires_at_ns == NOW_NS + PERMIT_TTL_NS


def test_no_issuer_parameter_can_supply_a_ceiling_or_an_environment() -> None:
    """The ceiling must be unreachable from the call site.

    An ``env=`` or ``max_notional=`` parameter would reintroduce exactly the
    defect one level up: a caller handing the issuer its own authority.
    """
    import inspect

    parameters = set(inspect.signature(issue_live_trading_permit).parameters)

    assert parameters == {"clock"}


# ==========================================================================
# Real expiry, against an injected clock
# ==========================================================================


def test_a_permit_expires_and_the_expiry_is_enforced_at_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch)

    with pytest.raises(LiveTradingPermissionError, match="expired"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=permit.expires_at_ns + 1,
        )


def test_a_permit_is_still_valid_at_the_exact_expiry_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The boundary is asserted, not assumed: expiry is inclusive of the tick."""
    permit = issued(monkeypatch)

    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=permit.expires_at_ns,
    )

    assert isinstance(authorization, LiveOrderSubmissionAuthorization)


def test_a_clock_that_ran_backwards_past_issuance_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A use-time earlier than issuance means the clock is not trustworthy."""
    permit = issued(monkeypatch)

    with pytest.raises(LiveTradingPermissionError, match="before it was issued"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=permit.issued_at_ns - 1,
        )


def test_expiry_is_testable_without_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """The injected clock is the whole point: no wall-clock read inside the check.

    ``TestClock`` advances instantly, so the expiry boundary above runs in
    microseconds. A ``time.time_ns()`` read inside the check would make these
    tests either untestable or a fifteen-minute sleep.
    """
    clock = clock_at()
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=clock)

    clock.set_time(NOW_NS + PERMIT_TTL_NS + 1)

    with pytest.raises(LiveTradingPermissionError, match="expired"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=clock.timestamp_ns(),
        )


def test_an_object_that_is_not_a_clock_is_refused_by_the_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``@runtime_checkable`` on the clock protocol is a check, not decoration."""
    enable_operator_gate(monkeypatch)

    with pytest.raises(LiveTradingPermissionError, match="timestamp_ns"):
        issue_live_trading_permit(clock=object())  # type: ignore[arg-type]


#: Names that read a wall clock. ``timestamp_ns`` is deliberately absent: that
#: is the INJECTED clock's method and is the whole point of the design.
_WALL_CLOCK_NAMES = frozenset(
    {"time_ns", "time", "monotonic", "monotonic_ns", "perf_counter", "now", "utcnow"}
)


def find_wall_clock_reads(tree: ast.AST) -> list[str]:
    """Every direct wall-clock read in ``tree``.

    P-M8: the original scan matched ``ast.Attribute`` only, so
    ``from time import time_ns`` followed by a bare ``time_ns()`` walked
    straight through a test whose docstring called itself "static proof".
    Bare-name calls and the imports that create them are both covered now.
    """
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _WALL_CLOCK_NAMES:
                offenders.append(f"line {node.lineno}: .{func.attr}()")
            elif isinstance(func, ast.Name) and func.id in _WALL_CLOCK_NAMES:
                offenders.append(f"line {node.lineno}: {func.id}()")
        elif isinstance(node, ast.ImportFrom) and node.module in {"time", "datetime"}:
            for alias in node.names:
                if alias.name in _WALL_CLOCK_NAMES:
                    offenders.append(f"line {node.lineno}: imports {alias.name}")
    return offenders


def test_the_safety_module_never_reads_a_wall_clock_itself() -> None:
    """Static proof that the clock is injected rather than sampled.

    A ``time.time_ns()`` call inside the check would make expiry both
    untestable and unauditable, and is the exact shape the brief forbids.
    """
    source = (REPO_ROOT / "src/breezy/adapters/polymarket_us/safety.py").read_text(
        encoding="utf-8"
    )

    offenders = find_wall_clock_reads(ast.parse(source))

    assert offenders == [], f"safety.py samples a clock directly: {offenders}"


# ==========================================================================
# The capability: skipping the gate is a TypeError, not a policy violation
# ==========================================================================


def test_the_chokepoint_returns_a_capability_bound_to_this_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch)

    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )

    assert isinstance(authorization, LiveOrderSubmissionAuthorization)
    assert authorization.order_notional_usd == Decimal("1.00")


def test_a_capability_authorises_the_request_it_was_minted_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch)
    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )

    authorization.consume(
        request_fingerprint=FINGERPRINT,
        order_notional_usd=Decimal("1.00"),
        now_ns=NOW_NS,
    )


def test_a_capability_cannot_dispatch_a_different_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The binding is what stops a cheap $1 gate from authorising a $10k order."""
    permit = issued(monkeypatch)
    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )

    with pytest.raises(LiveTradingPermissionError, match="different request"):
        authorization.consume(
            request_fingerprint=OTHER_FINGERPRINT,
            order_notional_usd=Decimal("1.00"),
            now_ns=NOW_NS,
        )


def test_a_capability_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """A replay inside the 30s Ed25519 signing window must not re-dispatch."""
    permit = issued(monkeypatch)
    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )
    authorization.consume(
        request_fingerprint=FINGERPRINT,
        order_notional_usd=Decimal("1.00"),
        now_ns=NOW_NS,
    )

    with pytest.raises(LiveTradingPermissionError, match="already been used"):
        authorization.consume(
        request_fingerprint=FINGERPRINT,
        order_notional_usd=Decimal("1.00"),
        now_ns=NOW_NS,
    )


def test_a_replayed_capability_is_refused_even_after_a_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``replace`` resets any per-instance flag; the nonce registry does not."""
    permit = issued(monkeypatch)
    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )
    authorization.consume(
        request_fingerprint=FINGERPRINT,
        order_notional_usd=Decimal("1.00"),
        now_ns=NOW_NS,
    )

    clone = object.__new__(LiveOrderSubmissionAuthorization)
    for field in dataclasses.fields(authorization):
        object.__setattr__(clone, field.name, getattr(authorization, field.name))

    with pytest.raises(LiveTradingPermissionError, match="already been used"):
        clone.consume(
            request_fingerprint=FINGERPRINT,
            order_notional_usd=Decimal("1.00"),
            now_ns=NOW_NS,
        )


def test_a_hand_constructed_capability_cannot_be_built_at_all() -> None:
    with pytest.raises(LiveTradingPermissionError, match="assert_live_order_submission_permitted"):
        LiveOrderSubmissionAuthorization(
            request_digest=b"whatever",
            order_notional_usd=Decimal("1e9"),
            expires_at_ns=NOW_NS + PERMIT_TTL_NS,
            nonce=b"nonce",
            authenticity=b"forged",
        )


def test_a_capability_forged_past_construction_is_refused_at_consume() -> None:
    forged = object.__new__(LiveOrderSubmissionAuthorization)
    for field, value in (
        ("request_digest", b"whatever"),
        ("order_notional_usd", Decimal("1e9")),
        ("expires_at_ns", NOW_NS + PERMIT_TTL_NS),
        ("nonce", b"nonce"),
        ("authenticity", b"forged"),
    ):
        object.__setattr__(forged, field, value)

    with pytest.raises(LiveTradingPermissionError, match="not issued"):
        forged.consume(
            request_fingerprint=FINGERPRINT,
            order_notional_usd=Decimal("1.00"),
            now_ns=NOW_NS,
        )


def test_a_capability_expires_with_its_permit(monkeypatch: pytest.MonkeyPatch) -> None:
    """P-HIGH-3: pin the capability's expiry to the PERMIT's, not to itself.

    ``now_ns > self.expires_at_ns`` refuses for any value, so an
    implementation setting ``expires_at_ns = 2**63 - 1`` passed this test
    while granting a capability valid for 292 years.
    """
    permit = issued(monkeypatch)
    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )

    assert authorization.expires_at_ns == permit.expires_at_ns

    with pytest.raises(LiveTradingPermissionError, match="expired"):
        authorization.consume(
            request_fingerprint=FINGERPRINT,
            order_notional_usd=Decimal("1.00"),
            now_ns=authorization.expires_at_ns + 1,
        )


def test_the_chokepoint_cannot_be_called_without_binding_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omission is a ``TypeError`` from Python itself, not a lint rule."""
    permit = issued(monkeypatch)

    with pytest.raises(TypeError):
        assert_live_order_submission_permitted(  # type: ignore[call-arg]
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
        )


# ==========================================================================
# Every pre-existing refusal survives
# ==========================================================================


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"credentials": None}, "credentials"),
        ({"permit": None}, "live-trading permit"),
        ({"manual_order_indicator": None}, "manualOrderIndicator"),
        ({"order_notional_usd": Decimal(0)}, "must be positive"),
        ({"order_notional_usd": Decimal(-1)}, "must be positive"),
        ({"order_notional_usd": Decimal("5.01")}, "exceeds permit"),
    ],
)
def test_each_original_refusal_still_fires(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    message: str,
) -> None:
    permit = issued(monkeypatch, ceiling="5.00")
    kwargs: dict[str, object] = {
        "credentials": credentials(),
        "permit": permit,
        "manual_order_indicator": True,
        "order_notional_usd": Decimal("1.00"),
        "request_fingerprint": FINGERPRINT,
        "now_ns": NOW_NS,
    }
    kwargs.update(overrides)

    with pytest.raises(LiveTradingPermissionError, match=message):
        assert_live_order_submission_permitted(**kwargs)  # type: ignore[arg-type]


def test_incomplete_credentials_are_refused_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch)
    cleared = credentials()
    cleared.secret_key.clear()

    with pytest.raises(LiveTradingPermissionError, match="credentials"):
        assert_live_order_submission_permitted(
            credentials=cleared,
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )


def test_the_notional_at_exactly_the_permit_ceiling_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behaviour preservation: the old chokepoint allowed ``==`` and must still."""
    permit = issued(monkeypatch, ceiling="5.00")

    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=False,
        order_notional_usd=Decimal("5.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )

    assert authorization.order_notional_usd == Decimal("5.00")


# ==========================================================================
# Static guard: exactly one issuer, and the permit type is not constructed
# anywhere else in the repo (architecture guard N1)
# ==========================================================================


def _constructor_sites(class_name: str) -> list[str]:
    sites: list[str] = []
    for root in ("src", "scripts", "tests"):
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == class_name
                ):
                    sites.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
    return sites


#: The only files allowed to name the permit constructor: the issuer itself,
#: and the suites that prove the issuer is the only issuer.
PERMIT_CONSTRUCTION_ALLOWLIST = frozenset(
    {
        "src/breezy/adapters/polymarket_us/safety.py",
        "tests/unit/test_polymarket_us_permit_issuance.py",
        # The Phase-0 fuse module keeps its own forgery-refusal proof, because
        # that is the module a reader opens to learn what the cage guarantees.
        # Every construction there is inside a ``pytest.raises``.
        "tests/unit/test_polymarket_us_phase0_safety.py",
    }
)


def test_the_permit_is_constructed_only_by_its_issuer_and_this_suite() -> None:
    offenders = [
        site
        for site in _constructor_sites("LiveTradingPermit")
        if site.rsplit(":", 1)[0] not in PERMIT_CONSTRUCTION_ALLOWLIST
    ]

    assert offenders == [], f"LiveTradingPermit constructed outside the issuer: {offenders}"


def test_the_capability_is_constructed_only_by_the_chokepoint_and_this_suite() -> None:
    offenders = [
        site
        for site in _constructor_sites("LiveOrderSubmissionAuthorization")
        if site.rsplit(":", 1)[0] not in PERMIT_CONSTRUCTION_ALLOWLIST
    ]

    assert offenders == [], f"capability constructed outside the chokepoint: {offenders}"


def test_the_constructor_scan_is_not_vacuous() -> None:
    """Proof the detector fires: it finds this suite's own deliberate forgeries."""
    sites = _constructor_sites("LiveTradingPermit")

    assert any(
        site.startswith("tests/unit/test_polymarket_us_permit_issuance.py") for site in sites
    )
    assert any(site.startswith("src/breezy/adapters/polymarket_us/safety.py") for site in sites)


def test_the_issuer_key_is_not_reachable_as_a_module_attribute() -> None:
    """Weak, but real: no ``safety.SOME_KEY`` handle to grab by accident.

    Stated honestly -- this is not isolation. The key remains reachable via
    ``_mint_authenticity.__closure__``. It removes the *accidental* handle,
    not the deliberate one.
    """
    from breezy.adapters.polymarket_us import safety

    byte_attrs = [
        name
        for name in dir(safety)
        if isinstance(getattr(safety, name, None), bytes | bytearray)
    ]

    assert byte_attrs == []


# ==========================================================================
# S-HIGH-1 -- the tag must bind VALUES, not their ``str()`` projections
#
# Reproduced end to end before the fix: a ``Decimal`` subclass whose
# ``__str__`` lies verified cleanly through all three entry paths and the
# chokepoint authorised $1e9 against a $5.00 permit. An ``int`` subclass on
# ``expires_at_ns`` bought 250 hours past a 15-minute TTL.
# ==========================================================================


class LyingDecimal(Decimal):
    """A Decimal whose ``str()`` claims to be the issued ceiling."""

    def __str__(self) -> str:
        return "5.00"


class LyingInt(int):
    """An int whose ``str()`` claims to be some other instant."""

    _claim: str = "0"

    def __str__(self) -> str:
        return self._claim


def test_a_decimal_subclass_with_a_lying_str_cannot_widen_a_ceiling_via_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, ceiling="5.00")

    with pytest.raises(LiveTradingPermissionError, match="max_order_notional_usd"):
        dataclasses.replace(permit, max_order_notional_usd=LyingDecimal("1E+9"))


def test_a_decimal_subclass_with_a_lying_str_cannot_widen_a_ceiling_via_the_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, ceiling="5.00")

    with pytest.raises(LiveTradingPermissionError, match="max_order_notional_usd"):
        LiveTradingPermit(
            operator_id=permit.operator_id,
            max_order_notional_usd=LyingDecimal("1E+9"),
            issued_at_ns=permit.issued_at_ns,
            expires_at_ns=permit.expires_at_ns,
            permit_id=permit.permit_id,
            budget_notional_usd=permit.budget_notional_usd,
            budget_order_count=permit.budget_order_count,
            authenticity=permit.authenticity,
        )


def test_a_decimal_subclass_with_a_lying_str_is_refused_at_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``__new__`` path skips ``__post_init__``, so USE must catch it too."""
    permit = issued(monkeypatch, ceiling="5.00")
    widened = object.__new__(LiveTradingPermit)
    for field in dataclasses.fields(permit):
        object.__setattr__(widened, field.name, getattr(permit, field.name))
    object.__setattr__(widened, "max_order_notional_usd", LyingDecimal("1E+9"))

    with pytest.raises(LiveTradingPermissionError, match="max_order_notional_usd"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=widened,
            manual_order_indicator=True,
            order_notional_usd=Decimal(1000000000),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )


def test_an_int_subclass_with_a_lying_str_cannot_extend_an_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch)
    far = LyingInt(permit.expires_at_ns + 250 * 3600 * 10**9)
    far._claim = str(permit.expires_at_ns)

    with pytest.raises(LiveTradingPermissionError, match="expires_at_ns"):
        dataclasses.replace(permit, expires_at_ns=far)


def test_a_str_subclass_cannot_impersonate_the_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LyingStr(str):
        def __str__(self) -> str:
            return "operator@example.com"

    permit = issued(monkeypatch, operator_id="operator@example.com")

    with pytest.raises(LiveTradingPermissionError, match="operator_id"):
        dataclasses.replace(permit, operator_id=LyingStr("attacker"))


def test_the_capability_fields_are_type_exact_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The capability signs a notional; the same projection hole applied to it."""
    permit = issued(monkeypatch)
    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )

    class LyingOne(Decimal):
        def __str__(self) -> str:
            return "1.00"

    with pytest.raises(LiveTradingPermissionError, match="order_notional_usd"):
        dataclasses.replace(authorization, order_notional_usd=LyingOne("1E+9"))


def test_the_tag_covers_the_value_not_its_repr_for_equal_looking_decimals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Decimal('5.00')`` and ``Decimal('5')`` compare equal but are not the same.

    Substituting one for the other must be refused rather than silently
    accepted: a tag that cannot tell them apart is a tag over a projection.
    """
    permit = issued(monkeypatch, ceiling="5.00")

    with pytest.raises(LiveTradingPermissionError, match="not issued|issue_live_trading_permit"):
        dataclasses.replace(permit, max_order_notional_usd=Decimal(5))


# ==========================================================================
# P-HIGH-1 -- the nonce registry must be thread-safe
# ==========================================================================


def test_pruning_under_concurrent_minting_never_escapes_the_permission_boundary() -> None:
    """A bare ``dict`` comprehension raised ``RuntimeError`` 20/20 under load.

    ``RuntimeError`` is not a ``LiveTradingPermissionError``, so a caller's
    refusal handler does not catch it: the chokepoint crashed the caller
    instead of refusing it.

    The minter here takes ``_REGISTRY_LOCK`` because that is precisely what
    every production mutation site does -- the guarantee being asserted is
    "all mutators agree on one lock", not "the dict survives a hostile
    unlocked writer", which no code in this module is. That every mutation
    site really does hold the lock is pinned separately and statically by
    :func:`test_the_registry_mutation_sites_are_lock_guarded`; without that
    sibling this test could be satisfied by a minter that simply never wrote.
    """
    import sys
    import threading

    from breezy.adapters.polymarket_us import safety

    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    minted = 0
    try:
        for _ in range(5):
            with safety._REGISTRY_LOCK:
                safety._UNSPENT_NONCES.clear()
                for index in range(200_000):
                    safety._UNSPENT_NONCES[b"x%d" % index] = 1000 + index

            errors: list[BaseException] = []
            stop = threading.Event()

            def mint(stop: threading.Event = stop) -> None:
                nonlocal minted
                index = 0
                while not stop.is_set():
                    with safety._REGISTRY_LOCK:
                        safety._UNSPENT_NONCES[b"n%d" % index] = 10**19
                    index += 1
                    minted += 1

            def prune(errors: list[BaseException] = errors) -> None:
                try:
                    safety._prune_expired_nonces(2500)
                except BaseException as exc:  # noqa: BLE001 - that is the assertion
                    errors.append(exc)

            minter = threading.Thread(target=mint, daemon=True)
            minter.start()
            pruner = threading.Thread(target=prune)
            pruner.start()
            pruner.join()
            stop.set()
            minter.join(timeout=5)

            assert errors == [], f"prune escaped the permission boundary: {errors!r}"
    finally:
        sys.setswitchinterval(previous_interval)
        with safety._REGISTRY_LOCK:
            safety._UNSPENT_NONCES.clear()

    assert minted > 0, "the minter never wrote; the race was never actually run"


#: The module-global registries whose every mutation must hold the lock.
_REGISTRIES = frozenset({"_UNSPENT_NONCES", "_PERMIT_BUDGETS"})


def find_unguarded_registry_mutations(tree: ast.AST) -> list[str]:
    """Every registry write NOT lexically inside a ``with _REGISTRY_LOCK`` block.

    A count-based assertion is not enough: dropping the lock from ONE site
    leaves the others in place and the count still passing. This walks each
    function body tracking whether we are inside the lock, so a single
    unguarded write is named.
    """
    unguarded: list[str] = []

    def touches_registry(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id in _REGISTRIES

    def walk(node: ast.AST, *, locked: bool) -> None:
        if isinstance(node, ast.With):
            now_locked = locked or any(
                isinstance(item.context_expr, ast.Name)
                and item.context_expr.id == "_REGISTRY_LOCK"
                for item in node.items
            )
            for statement in node.body:
                walk(statement, locked=now_locked)
            return

        if not locked:
            if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Subscript) and touches_registry(target.value):
                        unguarded.append(f"line {node.lineno}: assigns into a registry")
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    if isinstance(target, ast.Subscript) and touches_registry(target.value):
                        unguarded.append(f"line {node.lineno}: deletes from a registry")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"pop", "popitem", "clear", "update", "setdefault"}
                and touches_registry(node.func.value)
            ):
                unguarded.append(f"line {node.lineno}: registry .{node.func.attr}()")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "items"
                and touches_registry(node.func.value)
            ):
                unguarded.append(f"line {node.lineno}: iterates a registry unlocked")

        for descendant in ast.iter_child_nodes(node):
            walk(descendant, locked=locked)

    walk(tree, locked=False)
    return unguarded


def test_every_registry_mutation_site_is_lock_guarded() -> None:
    """Static backstop: the race is timing-dependent, the lock is not."""
    import threading

    from breezy.adapters.polymarket_us import safety

    assert isinstance(safety._REGISTRY_LOCK, type(threading.Lock()))

    source = (REPO_ROOT / "src/breezy/adapters/polymarket_us/safety.py").read_text(
        encoding="utf-8"
    )
    unguarded = find_unguarded_registry_mutations(ast.parse(source))

    assert unguarded == [], "unguarded registry access:\n" + "\n".join(unguarded)


def test_the_lock_guard_scan_is_not_vacuous() -> None:
    """Proof by construction: the unlocked comprehension that raised 20/20."""
    source = (
        "_UNSPENT_NONCES = {}\n"
        "\n"
        "\n"
        "def prune(now):\n"
        "    for n in [k for k, v in _UNSPENT_NONCES.items() if v < now]:\n"
        "        del _UNSPENT_NONCES[n]\n"
    )

    assert len(find_unguarded_registry_mutations(ast.parse(source))) == 2


def test_the_lock_guard_scan_accepts_a_guarded_site() -> None:
    source = (
        "_UNSPENT_NONCES = {}\n"
        "\n"
        "\n"
        "def prune(now):\n"
        "    with _REGISTRY_LOCK:\n"
        "        for n in [k for k, v in _UNSPENT_NONCES.items() if v < now]:\n"
        "            _UNSPENT_NONCES.pop(n, None)\n"
    )

    assert find_unguarded_registry_mutations(ast.parse(source)) == []

# ==========================================================================
# P-HIGH-2 -- the sanctioned construction path keeps its static guarantees
# ==========================================================================


def test_the_module_contains_no_init_bypassing_construction_helper() -> None:
    """``_draft`` erased mypy's view of the only sanctioned mint path.

    ``**values: object`` typechecked a misspelled field name and a wholly
    omitted field alike, yielding a half-built instance whose ``repr()`` and
    ``hash()`` raise. In a module whose thesis is "``__init__`` validates", an
    untyped ``__init__``-bypassing helper is the wrong shape.
    """
    source = (REPO_ROOT / "src/breezy/adapters/polymarket_us/safety.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    bypasses = [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "__setattr__"
    ]

    assert bypasses == [], f"safety.py bypasses __init__ at: {bypasses}"
    assert "_draft" not in source


# ==========================================================================
# P-HIGH-4 -- §8.2 item 4: spend-down budget and use count
# ==========================================================================


def test_the_issuer_refuses_without_a_session_notional_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_operator_gate(monkeypatch)
    monkeypatch.delenv(SESSION_NOTIONAL_USD_ENV_VAR)

    with pytest.raises(LiveTradingPermissionError, match=SESSION_NOTIONAL_USD_ENV_VAR):
        issue_live_trading_permit(clock=clock_at())


def test_the_issuer_refuses_without_a_session_order_count_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_operator_gate(monkeypatch)
    monkeypatch.delenv(SESSION_ORDER_COUNT_ENV_VAR)

    with pytest.raises(LiveTradingPermissionError, match=SESSION_ORDER_COUNT_ENV_VAR):
        issue_live_trading_permit(clock=clock_at())


@pytest.mark.parametrize("value", ["0", "-1", "abc", "", "1.5", "1e3"])
def test_a_malformed_order_count_budget_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    enable_operator_gate(monkeypatch, order_count=value)

    with pytest.raises(LiveTradingPermissionError, match=SESSION_ORDER_COUNT_ENV_VAR):
        issue_live_trading_permit(clock=clock_at())


def test_the_notional_budget_is_spent_down_across_authorizations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect: one permit authorised UNBOUNDED orders at the full ceiling."""
    permit = issued(monkeypatch, ceiling="5.00", session_notional="12.00", order_count="10")

    assert live_trading_budget_remaining(permit) == (Decimal("12.00"), 10)

    for _ in range(2):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("5.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )

    assert live_trading_budget_remaining(permit) == (Decimal("2.00"), 8)

    with pytest.raises(LiveTradingPermissionError, match="remaining notional budget"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("5.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )


def test_the_order_count_budget_is_spent_down_and_then_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch, ceiling="5.00", session_notional="1000.00", order_count="2")

    for _ in range(2):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )

    assert live_trading_budget_remaining(permit) == (Decimal("998.00"), 0)

    with pytest.raises(LiveTradingPermissionError, match="order-count budget"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )


def test_a_refused_authorization_does_not_spend_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a granted capability costs budget; a refusal must be free."""
    permit = issued(monkeypatch, ceiling="5.00", session_notional="12.00", order_count="10")

    with pytest.raises(LiveTradingPermissionError, match="exceeds permit"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("5.01"),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )

    assert live_trading_budget_remaining(permit) == (Decimal("12.00"), 10)


def test_the_budget_is_inside_the_signed_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    permit = issued(monkeypatch, session_notional="12.00", order_count="10")

    with pytest.raises(LiveTradingPermissionError, match="issue_live_trading_permit|not issued"):
        dataclasses.replace(permit, budget_notional_usd=Decimal("99999.00"))
    with pytest.raises(LiveTradingPermissionError, match="issue_live_trading_permit|not issued"):
        dataclasses.replace(permit, budget_order_count=9999)


def test_a_permit_whose_budget_this_process_never_issued_is_refused() -> None:
    """A permit_id absent from the ledger cannot be spent against."""
    from breezy.adapters.polymarket_us import safety

    with safety._REGISTRY_LOCK:
        safety._PERMIT_BUDGETS.clear()

    forged = object.__new__(LiveTradingPermit)
    with pytest.raises(LiveTradingPermissionError):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=forged,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=NOW_NS,
        )


def test_the_docstring_does_not_claim_the_spend_down_is_absent() -> None:
    """P-HIGH-4: the module must not narrate a control it does not ship."""
    source = (REPO_ROOT / "src/breezy/adapters/polymarket_us/safety.py").read_text(
        encoding="utf-8"
    )

    assert "budget_notional_usd" in source
    assert "budget_order_count" in source


# ==========================================================================
# S-MEDIUM-1 -- the TTL value itself is pinned, not tested against itself
# ==========================================================================


def test_the_permit_ttl_is_pinned_to_fifteen_minutes() -> None:
    """Every other expiry test derives its expectation from this constant.

    Rebinding it to ``10**19`` (about 317 years) left the ENTIRE suite green.
    Expiry was tested relative to itself; this is the only assertion that
    makes the number mean something.
    """
    assert PERMIT_TTL_NS == 15 * 60 * 1_000_000_000
    assert PERMIT_TTL_NS == 900_000_000_000


# ==========================================================================
# S-MEDIUM-2 -- no code in this repo may set the operator gate
# ==========================================================================


def find_environ_mutations(roots: tuple[str, ...] = ("src", "scripts")) -> list[str]:
    """Any write to the process environment from shipped code.

    ``GO_LIVE_PLAN.md`` §5: "No agent, and no automation in this repo, may set
    D4." That rule was quoted in ``safety.py`` and enforced by nothing. The
    blanket form is deliberate: an allowlist keyed on the gate's NAME is
    defeated by building the string, so no environment write is permitted at
    all. The tree already satisfies this.
    """
    banned_attrs = {"setdefault", "update", "pop", "popitem", "clear"}
    found: list[str] = []
    for root in roots:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
                    targets = (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                    for target in targets:
                        if (
                            isinstance(target, ast.Subscript)
                            and isinstance(target.value, ast.Attribute)
                            and target.value.attr == "environ"
                        ):
                            found.append(f"{rel}:{node.lineno}: assigns os.environ[...]")
                elif isinstance(node, ast.Call):
                    func = node.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr in banned_attrs
                        and isinstance(func.value, ast.Attribute)
                        and func.value.attr == "environ"
                    ):
                        found.append(f"{rel}:{node.lineno}: os.environ.{func.attr}()")
                    if isinstance(func, ast.Attribute) and func.attr in {
                        "putenv",
                        "unsetenv",
                    }:
                        found.append(f"{rel}:{node.lineno}: os.{func.attr}()")
                    if isinstance(func, ast.Name) and func.id in {
                        "putenv",
                        "unsetenv",
                        "load_dotenv",
                    }:
                        found.append(f"{rel}:{node.lineno}: {func.id}()")
                elif isinstance(node, ast.ImportFrom) and node.module in {"dotenv", "os"}:
                    for alias in node.names:
                        if alias.name in {"putenv", "unsetenv", "load_dotenv"}:
                            found.append(f"{rel}:{node.lineno}: imports {alias.name}")
    return found


def test_no_shipped_code_can_set_the_operator_trading_gate() -> None:
    offenders = find_environ_mutations()

    assert offenders == [], "shipped code writes the environment:\n" + "\n".join(offenders)


def test_the_environ_mutation_scan_is_not_vacuous(tmp_path: Path) -> None:
    """Proof by construction, exercising each rule the scan implements."""
    probe = REPO_ROOT / "src" / "breezy" / "__environ_probe__.py"
    probe.write_text(
        "import os\n"
        "from dotenv import load_dotenv\n"
        "\n"
        "\n"
        "def go() -> None:\n"
        "    os.environ['BREEZY_TRADING_ENABLED'] = '1'\n"
        "    os.environ.setdefault('BREEZY_TRADING_ENABLED', '1')\n"
        "    os.environ.update({'BREEZY_TRADING_ENABLED': '1'})\n"
        "    os.putenv('BREEZY_TRADING_ENABLED', '1')\n"
        "    load_dotenv()\n",
        encoding="utf-8",
    )
    try:
        offenders = [o for o in find_environ_mutations() if "__environ_probe__" in o]
    finally:
        probe.unlink()

    assert len(offenders) == 6, offenders


# ==========================================================================
# S-MEDIUM-3 -- the tag never reaches a log line
# ==========================================================================


def test_the_permit_repr_does_not_publish_its_authenticity_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A traceback or log line would otherwise print a valid tag within its TTL."""
    permit = issued(monkeypatch)

    rendered = repr(permit)

    assert permit.authenticity.hex() not in rendered
    assert "authenticity" not in rendered
    assert permit.permit_id.hex() not in rendered
    assert permit.operator_id in rendered  # still useful for an audit line


def test_the_capability_repr_does_not_publish_its_nonce_or_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit = issued(monkeypatch)
    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )

    rendered = repr(authorization)

    assert authorization.nonce.hex() not in rendered
    assert authorization.authenticity.hex() not in rendered
    assert "nonce" not in rendered
    assert "authenticity" not in rendered


# ==========================================================================
# P-M1 -- every direct-construction refusal is a LiveTradingPermissionError
# ==========================================================================


@pytest.mark.parametrize(
    "overrides",
    [
        {"operator_id": ""},
        {"max_order_notional_usd": Decimal(0)},
        {"issued_at_ns": 0},
        {"expires_at_ns": 1},
        {"budget_order_count": 0},
    ],
)
def test_direct_construction_always_raises_the_permission_error(
    overrides: dict[str, object],
) -> None:
    """The docstring says "direct construction raises LiveTradingPermissionError".

    Four of five checks used to raise ``ValueError`` first, so the sentence
    was false for most inputs. The tag check runs first now: a caller outside
    the issuer gets one answer, and it is the forgery answer.
    """
    kwargs: dict[str, object] = {
        "operator_id": "anyone",
        "max_order_notional_usd": Decimal("1.00"),
        "issued_at_ns": NOW_NS,
        "expires_at_ns": NOW_NS + PERMIT_TTL_NS,
        "permit_id": b"0123456789abcdef",
        "budget_notional_usd": Decimal("1.00"),
        "budget_order_count": 1,
        "authenticity": b"forged",
    }
    kwargs.update(overrides)

    with pytest.raises(LiveTradingPermissionError):
        LiveTradingPermit(**kwargs)  # type: ignore[arg-type]


# ==========================================================================
# S-LOW-1 -- the money pattern is ASCII-only and anchored at end-of-string
# ==========================================================================


@pytest.mark.parametrize("value", ["５.００", "5.00\n", "5.00\r", "٥.٠٠"])
def test_a_unicode_or_trailing_newline_ceiling_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    """``\\d`` matches fullwidth and Arabic-Indic digits; ``$`` matches before ``\\n``."""
    enable_operator_gate(monkeypatch, ceiling=value)

    with pytest.raises(LiveTradingPermissionError, match=MAX_ORDER_NOTIONAL_USD_ENV_VAR):
        issue_live_trading_permit(clock=clock_at())


# ==========================================================================
# P-M6 -- the pruning path is tested, and the boundary is pinned
# ==========================================================================


def test_pruning_removes_strictly_expired_nonces_only() -> None:
    """Pins ``<`` against ``<=``: a nonce expiring exactly now is still live."""
    from breezy.adapters.polymarket_us import safety

    with safety._REGISTRY_LOCK:
        safety._UNSPENT_NONCES.clear()
        safety._UNSPENT_NONCES[b"past"] = 999
        safety._UNSPENT_NONCES[b"exactly-now"] = 1000
        safety._UNSPENT_NONCES[b"future"] = 1001

    safety._prune_expired_nonces(1000)

    assert set(safety._UNSPENT_NONCES) == {b"exactly-now", b"future"}


def test_a_capability_expiring_exactly_now_is_still_consumable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prune boundary and the consume boundary must agree."""
    permit = issued(monkeypatch)
    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )

    authorization.consume(
        request_fingerprint=FINGERPRINT,
        order_notional_usd=Decimal("1.00"),
        now_ns=authorization.expires_at_ns,
    )


def test_the_registry_does_not_leak_across_tests() -> None:
    """The autouse fixture must restore the registries it snapshots."""
    from breezy.adapters.polymarket_us import safety

    assert safety._UNSPENT_NONCES == {}


# ==========================================================================
# P-M7 -- consume re-checks the notional it was minted for
# ==========================================================================


def test_a_capability_cannot_dispatch_a_different_notional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The claim was "stops a cheap $1 gate authorising a $10k order".

    Nothing enforced it: the fingerprint is caller-computed and ``consume``
    never re-checked the notional. Now it does, so the sentence is true.
    """
    permit = issued(monkeypatch, ceiling="5.00")
    authorization = assert_live_order_submission_permitted(
        credentials=credentials(),
        permit=permit,
        manual_order_indicator=True,
        order_notional_usd=Decimal("1.00"),
        request_fingerprint=FINGERPRINT,
        now_ns=NOW_NS,
    )

    with pytest.raises(LiveTradingPermissionError, match="different notional"):
        authorization.consume(
            request_fingerprint=FINGERPRINT,
            order_notional_usd=Decimal("10000.00"),
            now_ns=NOW_NS,
        )


# ==========================================================================
# P-M8 -- the wall-clock scan follows bare-name imports too
# ==========================================================================


def test_the_wall_clock_scan_catches_a_bare_name_import() -> None:
    """``from time import time_ns; time_ns()`` evaded the attribute-only scan."""
    source = "from time import time_ns\n\n\ndef go() -> int:\n    return time_ns()\n"

    assert find_wall_clock_reads(ast.parse(source)) != []


def test_the_wall_clock_scan_catches_an_attribute_call() -> None:
    source = "import time\n\n\ndef go() -> int:\n    return time.time_ns()\n"

    assert find_wall_clock_reads(ast.parse(source)) != []


def test_the_wall_clock_scan_does_not_fire_on_an_injected_clock() -> None:
    source = "def go(clock: object) -> int:\n    return clock.timestamp_ns()\n"

    assert find_wall_clock_reads(ast.parse(source)) == []


# ==========================================================================
# S-LOW-2 -- pruning is reachable even once the issuing permit has expired
# ==========================================================================


def test_an_expired_permit_still_lets_the_registry_be_pruned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pruning used to run only AFTER every permit check passed.

    Once the issuing permit expired, nothing could ever prune again and the
    registry grew without bound for the life of the process.
    """
    from breezy.adapters.polymarket_us import safety

    permit = issued(monkeypatch)
    with safety._REGISTRY_LOCK:
        safety._UNSPENT_NONCES[b"stale"] = NOW_NS

    with pytest.raises(LiveTradingPermissionError, match="expired"):
        assert_live_order_submission_permitted(
            credentials=credentials(),
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
            request_fingerprint=FINGERPRINT,
            now_ns=permit.expires_at_ns + 10**12,
        )

    assert b"stale" not in safety._UNSPENT_NONCES


# ==========================================================================
# P-LOW -- a clock returning a non-number refuses rather than TypeErrors
# ==========================================================================


def test_a_clock_returning_a_non_number_is_refused_as_a_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``runtime_checkable`` checks attribute presence, never the return type."""
    enable_operator_gate(monkeypatch)

    class BadClock:
        def timestamp_ns(self) -> int:
            return "not-a-number"  # type: ignore[return-value]

    with pytest.raises(LiveTradingPermissionError, match="timestamp_ns"):
        issue_live_trading_permit(clock=BadClock())
