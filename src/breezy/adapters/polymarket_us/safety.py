"""Live-trading safety chokepoints for Polymarket.us order submission.

Authority: ``docs/plans/TRADING_SYSTEM_ARCHITECTURE.md`` §8.2 and §8.4.

WHAT THIS MODULE IS
-------------------

The single future chokepoint between this bot and a live order, plus the ONE
sanctioned issuer of the authority that chokepoint checks. It contains no
network code, no HTTP verb, no path and no order payload -- deliberately. This
module is venue-touching under the read-only cage's classifier C1, so barrier
B4 rule V1 forbids a write-method literal here outright. The chokepoint
therefore binds a request through an **opaque digest** the (future) egress
module computes for itself, which is both what the cage permits and the right
abstraction: authority does not need to know the wire format.

THE THREE DEFECTS THIS MODULE WAS FIXED FOR
-------------------------------------------

1. **The permit was forgeable in one line.** It was a public frozen dataclass
   re-exported in the package ``__all__`` with no issuer and no authenticity,
   so ``assert_live_order_submission_permitted`` asked whether a permit
   *object existed*, never whether the operator *issued* it. A permit with a
   $1e9 ceiling was constructed during review.
2. **``issued_at_ns`` was decorative.** Validated positive, then never read
   anywhere in ``src/``. It had the shape of an expiry and none of its
   function; one permit authorised every order for the process lifetime.
3. **The chokepoint returned ``None``.** Nothing structurally forced a caller
   through it, so a path that never called it was indistinguishable from one
   that did.

HOW EACH IS CLOSED
------------------

1. :class:`LiveTradingPermit` carries an authenticity tag: an HMAC over its own
   fields under a process-unique key minted at import into a closure. The tag
   is verified in ``__post_init__`` (so direct construction *fails*) **and
   again at use** (so ``object.__new__``, ``pickle`` and any other
   ``__init__``-bypassing route fails too).

   The tag covers **canonically encoded values, never their ``str()``
   projections**, and every field is checked with ``type(x) is T`` rather than
   ``isinstance``. This is not pedantry -- it was a measured, exploitable hole.
   A ``Decimal`` subclass whose ``__str__`` returned the issued ceiling
   verified cleanly through all three entry paths and the chokepoint
   authorised **$1e9 against a $5.00 permit**; an ``int`` subclass on
   ``expires_at_ns`` bought 250 hours past a 15-minute TTL. A tag over
   ``str(x)`` binds what a field *renders as*, never what it *is* or how it
   *compares* -- and detecting in-place mutation of a legitimately issued
   permit is the entire reason this is an HMAC rather than an identity
   registry.

   :func:`issue_live_trading_permit` is the only function that mints, and it
   derives every field from operator-supplied environment -- never from a
   caller argument. It takes no ``env`` parameter and no ceiling parameter,
   precisely so that no code path can raise its own ceiling.

2. ``issued_at_ns`` is load-bearing: the permit expires
   :data:`PERMIT_TTL_NS` after issuance, checked against an **injected clock**
   (``nautilus_trader.common.component.Clock`` -- ``TestClock`` and
   ``LiveClock`` both satisfy it). No wall clock is sampled inside this
   module, which is what makes expiry testable without sleeping and auditable
   by a static scan.

   Expiry alone was only a *narrowing*: a permit still authorised an unbounded
   number of orders at the full ceiling for its whole TTL. §8.2 item 4 is
   therefore also implemented -- the permit carries a **spend-down budget**
   (remaining aggregate notional and remaining order count), both inside the
   signed payload and both decremented on each granted authorization.

3. The chokepoint returns a :class:`LiveOrderSubmissionAuthorization` bound to
   one request AND to one notional. A dispatch surface that requires it
   positionally turns "skipped the gate" into a ``TypeError`` at the call site
   rather than a policy violation some static scan has to notice.

WHAT THIS DOES **NOT** PROTECT AGAINST -- stated plainly
--------------------------------------------------------

**Hostile code running in this interpreter.** Python provides no in-process
capability isolation. The issuer key lives in a closure cell reachable through
``_mint_authenticity.__closure__[0].cell_contents`` or ``gc.get_referents``;
anything already executing here can mint a valid permit for any ceiling. The
closure removes the *accidental* handle (there is no ``safety.SOME_KEY`` to
grab), not the deliberate one.

What the mechanism does defeat, and what actually happens in practice: casual
self-issue, ``dataclasses.replace`` widening an issued ceiling, in-place
mutation via a lying ``__str__``, serialisation laundering through ``pickle``,
capability replay inside the 30-second Ed25519 signing window, and a
capability minted for one request or one notional dispatching another.

Four further residuals:

* **The clock is injected**, so a caller that supplies a frozen or rewound
  clock controls expiry. Partially mitigated: a use-time earlier than issuance
  is refused outright. Fully mitigating it is impossible without sampling a
  wall clock here, which would trade a smaller hole for an untestable check.
* **The operator can set the ceilings wrongly.** No mechanism here can second
  guess :data:`MAX_ORDER_NOTIONAL_USD_ENV_VAR` or the session budgets; they
  are the enablement ceiling and are by design the operator's call alone.
  Note that :data:`_MONEY_RE` constrains only the *form* of an amount, never
  its magnitude: ``"1000000000.00"`` is a well-formed ceiling and will issue.
* **Budget state is process-local and in-memory.** A restart mints a new
  issuer key, which invalidates every outstanding permit -- so a restart can
  never *resurrect* spent budget, only refuse the old permit outright. But two
  processes holding separately issued permits do not share a budget.
* **Budget is spent at authorization, not at dispatch.** A capability that is
  minted and never consumed still costs budget. That is the fail-closed
  direction and is deliberate: decrementing at consume time would let a caller
  mint unbounded capabilities.
"""

from __future__ import annotations

import hmac
import os
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Final, Protocol, runtime_checkable

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials

#: Operator gate D4. No default, no coercion, no inference: the value must be
#: exactly ``"1"``. ``docs/plans/GO_LIVE_PLAN.md`` §5: "No agent, and no
#: automation in this repo, may set D4." That rule is enforced by the AST
#: barrier ``test_no_shipped_code_can_set_the_operator_trading_gate``, which
#: bans every environment write from ``src/`` and ``scripts/`` outright.
TRADING_ENABLED_ENV_VAR: Final = "BREEZY_TRADING_ENABLED"

#: Operator gate D3/D5 -- the per-order spend ceiling, in USD. No default. A
#: missing ceiling means no trading; it is never guessed and never inferred.
MAX_ORDER_NOTIONAL_USD_ENV_VAR: Final = "BREEZY_MAX_ORDER_NOTIONAL_USD"

#: Operator gate D5 -- the aggregate notional one permit may ever authorise.
#: This is what stops a single permit authorising unbounded orders at the full
#: per-order ceiling for its whole TTL (§8.2 item 4). No default.
SESSION_NOTIONAL_USD_ENV_VAR: Final = "BREEZY_MAX_SESSION_NOTIONAL_USD"

#: Operator gate D5 -- the number of orders one permit may ever authorise.
#: No default.
SESSION_ORDER_COUNT_ENV_VAR: Final = "BREEZY_MAX_SESSION_ORDER_COUNT"

#: The accountable human. Recorded on the permit so a journal entry names one.
OPERATOR_ID_ENV_VAR: Final = "BREEZY_TRADING_OPERATOR_ID"

#: How long an issued permit stays valid. Chosen to be shorter than any
#: plausible unattended session: enablement should not outlive the operator's
#: attention. Fifteen minutes, in nanoseconds. Pinned directly by
#: ``test_the_permit_ttl_is_pinned_to_fifteen_minutes`` -- every other expiry
#: test derives its expectation from this constant, so without that assertion
#: the whole suite stayed green with the TTL rebound to ~317 years.
PERMIT_TTL_NS: Final = 15 * 60 * 1_000_000_000

#: A plain money amount, to the cent. ASCII-only ``[0-9]`` rather than ``\d``
#: (which matches fullwidth and Arabic-Indic digits) and ``\Z`` rather than
#: ``$`` (which matches before a trailing newline). Constrains FORM only --
#: magnitude is the operator's call, as the module docstring states.
_MONEY_RE: Final = re.compile(r"^[0-9]+(?:\.[0-9]{1,2})?\Z")

#: A plain positive count. Same ASCII/anchoring discipline as ``_MONEY_RE``.
_COUNT_RE: Final = re.compile(r"^[0-9]+\Z")


class LiveTradingPermissionError(PermissionError):
    """Raised when a live order submission lacks an explicit runtime permit."""


@runtime_checkable
class SupportsTimestampNs(Protocol):
    """The one method this module needs from a clock.

    Satisfied by ``nautilus_trader.common.component.Clock`` and both of its
    concrete subclasses. Declared structurally rather than importing the
    Cython base, so a test may inject a plain stub without the adapter
    depending on the kernel.
    """

    def timestamp_ns(self) -> int: ...


# ---------------------------------------------------------------------------
# Authenticity: a process-unique key, and canonical value encoding
# ---------------------------------------------------------------------------


def _make_authenticity_functions() -> tuple[
    Callable[[bytes], bytes],
    Callable[[bytes, object], bool],
]:
    """Mint the process-unique issuer key into a closure, not a module attribute.

    See the module docstring's residual note: this is not isolation, and is not
    claimed to be. It removes the accidental handle only.
    """
    key = secrets.token_bytes(32)

    def mint(payload: bytes) -> bytes:
        return hmac.new(key, payload, sha256).digest()

    def verify(payload: bytes, tag: object) -> bool:
        if type(tag) is not bytes:
            return False
        return hmac.compare_digest(mint(payload), tag)

    return mint, verify


_mint_authenticity, _verify_authenticity = _make_authenticity_functions()


def _encode(*parts: bytes) -> bytes:
    """Length-prefixed concatenation, so no two field tuples collide."""
    return b"".join(len(part).to_bytes(8, "big") + part for part in parts)


def _refuse(label: str, value: object, expected: str) -> LiveTradingPermissionError:
    return LiveTradingPermissionError(
        f"{label} must be exactly {expected}, not {type(value).__name__}: a subclass "
        f"can lie in __str__ and would otherwise verify against a tag it does not match"
    )


def _enc_str(value: object, label: str) -> bytes:
    if type(value) is not str:
        raise _refuse(label, value, "str")
    return value.encode("utf-8")


def _enc_bytes(value: object, label: str) -> bytes:
    if type(value) is not bytes:
        raise _refuse(label, value, "bytes")
    return value


def _enc_int(value: object, label: str) -> bytes:
    if type(value) is not int:
        raise _refuse(label, value, "int")
    length = max(1, (value.bit_length() + 8) // 8)
    return value.to_bytes(length, "big", signed=True)


def _enc_decimal(value: object, label: str) -> bytes:
    """Encode a Decimal from ``as_tuple()`` -- its value, not its rendering.

    ``Decimal('5.00')`` and ``Decimal('5')`` compare equal but encode
    differently. That asymmetry is deliberate and conservative: substituting
    one for the other is refused rather than silently accepted.
    """
    if type(value) is not Decimal:
        raise _refuse(label, value, "Decimal")
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # NaN / Infinity carry 'n' / 'N' / 'F'
        raise LiveTradingPermissionError(f"{label} must be a finite decimal amount")
    return _encode(
        _enc_int(int(sign), f"{label}.sign"),
        bytes(digits),
        _enc_int(int(exponent), f"{label}.exponent"),
    )


def _permit_payload(
    *,
    operator_id: str,
    max_order_notional_usd: Decimal,
    issued_at_ns: int,
    expires_at_ns: int,
    permit_id: bytes,
    budget_notional_usd: Decimal,
    budget_order_count: int,
) -> bytes:
    """The exact bytes a permit's tag covers -- every field but the tag itself."""
    return _encode(
        b"breezy.live-trading-permit.v2",
        _enc_str(operator_id, "operator_id"),
        _enc_decimal(max_order_notional_usd, "max_order_notional_usd"),
        _enc_int(issued_at_ns, "issued_at_ns"),
        _enc_int(expires_at_ns, "expires_at_ns"),
        _enc_bytes(permit_id, "permit_id"),
        _enc_decimal(budget_notional_usd, "budget_notional_usd"),
        _enc_int(budget_order_count, "budget_order_count"),
    )


def _authorization_payload(
    *,
    request_digest: bytes,
    order_notional_usd: Decimal,
    expires_at_ns: int,
    nonce: bytes,
) -> bytes:
    return _encode(
        b"breezy.live-order-submission-authorization.v2",
        _enc_bytes(request_digest, "request_digest"),
        _enc_decimal(order_notional_usd, "order_notional_usd"),
        _enc_int(expires_at_ns, "expires_at_ns"),
        _enc_bytes(nonce, "nonce"),
    )


# ---------------------------------------------------------------------------
# Process-local registries
# ---------------------------------------------------------------------------

#: One lock for both registries. ``dict.pop`` is atomic, but ITERATING a dict
#: while another thread inserts raises ``RuntimeError: dictionary changed size
#: during iteration`` -- reproduced 20/20 under load. ``RuntimeError`` is not a
#: ``LiveTradingPermissionError``, so it escaped the permission boundary and
#: crashed the caller instead of refusing it.
_REGISTRY_LOCK: Final = threading.Lock()

#: Nonces of capabilities minted and not yet spent, mapped to their expiry.
#: A frozen dataclass has no place to record "already used" that survives
#: ``dataclasses.replace`` or a ``__new__`` clone, so single-use is enforced
#: here rather than on the instance.
_UNSPENT_NONCES: Final[dict[bytes, int]] = {}


@dataclass(slots=True)
class _Budget:
    """The remaining spend-down for one issued permit (§8.2 item 4)."""

    remaining_notional_usd: Decimal
    remaining_order_count: int


#: Remaining budget per issued permit, keyed by ``permit_id``.
_PERMIT_BUDGETS: Final[dict[bytes, _Budget]] = {}


def _prune_expired_nonces(now_ns: int) -> None:
    """Drop every nonce that can no longer be consumed.

    Boundary is ``<``, matching ``consume``'s ``now_ns > expires_at_ns``: a
    capability expiring exactly now is still live and must not be pruned.
    """
    with _REGISTRY_LOCK:
        stale = [n for n, expiry in _UNSPENT_NONCES.items() if expiry < now_ns]
        for nonce in stale:
            _UNSPENT_NONCES.pop(nonce, None)


# ---------------------------------------------------------------------------
# The permit
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveTradingPermit:
    """Operator-issued, expiring, spend-limited approval for order submission.

    Construct ONLY via :func:`issue_live_trading_permit`. Direct construction
    raises :class:`LiveTradingPermissionError` -- the tag check runs FIRST, so
    a caller outside the issuer gets the forgery answer rather than a
    ``ValueError`` about some field it happened to get wrong.
    """

    operator_id: str
    max_order_notional_usd: Decimal
    issued_at_ns: int
    expires_at_ns: int
    permit_id: bytes = field(repr=False)
    budget_notional_usd: Decimal
    budget_order_count: int
    authenticity: bytes = field(repr=False)

    def _payload(self) -> bytes:
        return _permit_payload(
            operator_id=self.operator_id,
            max_order_notional_usd=self.max_order_notional_usd,
            issued_at_ns=self.issued_at_ns,
            expires_at_ns=self.expires_at_ns,
            permit_id=self.permit_id,
            budget_notional_usd=self.budget_notional_usd,
            budget_order_count=self.budget_order_count,
        )

    def __post_init__(self) -> None:
        if not _verify_authenticity(self._payload(), self.authenticity):
            raise LiveTradingPermissionError(
                "LiveTradingPermit carries no valid issuer tag: it is obtainable "
                "only from issue_live_trading_permit()"
            )
        # Reached only for a genuinely issued permit, so these are the
        # issuer's own invariants rather than a caller-facing refusal.
        if not self.operator_id.strip():
            raise LiveTradingPermissionError("operator_id must not be empty")
        if self.max_order_notional_usd <= Decimal(0):
            raise LiveTradingPermissionError("max_order_notional_usd must be positive")
        if self.issued_at_ns <= 0:
            raise LiveTradingPermissionError("issued_at_ns must be positive")
        if self.expires_at_ns <= self.issued_at_ns:
            raise LiveTradingPermissionError("expires_at_ns must be after issued_at_ns")
        if self.budget_order_count < 1:
            raise LiveTradingPermissionError("budget_order_count must be at least one")


# ---------------------------------------------------------------------------
# The capability
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveOrderSubmissionAuthorization:
    """Single-use capability proving the chokepoint ran for ONE request.

    Obtainable only from :func:`assert_live_order_submission_permitted`. A
    dispatch surface that takes this positionally makes "never called the
    gate" a ``TypeError`` rather than a discipline question.
    """

    request_digest: bytes = field(repr=False)
    order_notional_usd: Decimal
    expires_at_ns: int
    nonce: bytes = field(repr=False)
    authenticity: bytes = field(repr=False)

    def _payload(self) -> bytes:
        return _authorization_payload(
            request_digest=self.request_digest,
            order_notional_usd=self.order_notional_usd,
            expires_at_ns=self.expires_at_ns,
            nonce=self.nonce,
        )

    def __post_init__(self) -> None:
        if not _verify_authenticity(self._payload(), self.authenticity):
            raise LiveTradingPermissionError(
                "LiveOrderSubmissionAuthorization carries no valid issuer tag: it "
                "is obtainable only from assert_live_order_submission_permitted()"
            )

    def consume(
        self,
        *,
        request_fingerprint: bytes,
        order_notional_usd: Decimal,
        now_ns: int,
    ) -> None:
        """Spend this capability for exactly the request it was minted for.

        Both the request AND the notional are re-checked here. Without the
        notional check the binding was only as strong as whatever the caller
        chose to put in its fingerprint, which is not a mechanism.

        Raises:
            LiveTradingPermissionError: on a forged, expired, mismatched or
                already-spent capability. Never returns a boolean: there is no
                value here a caller can accidentally ignore.
        """
        if not _verify_authenticity(_payload_of(self), self.authenticity):
            raise LiveTradingPermissionError(
                "authorization was not issued by assert_live_order_submission_permitted"
            )
        if now_ns > self.expires_at_ns:
            raise LiveTradingPermissionError("authorization has expired")
        if not hmac.compare_digest(sha256(request_fingerprint).digest(), self.request_digest):
            raise LiveTradingPermissionError("authorization was minted for a different request")
        if order_notional_usd != self.order_notional_usd:
            raise LiveTradingPermissionError("authorization was minted for a different notional")
        _prune_expired_nonces(now_ns)
        with _REGISTRY_LOCK:
            spent = _UNSPENT_NONCES.pop(self.nonce, None)
        if spent is None:
            raise LiveTradingPermissionError(
                "authorization has already been used, or is no longer known to this process"
            )


def _payload_of(obj: LiveTradingPermit | LiveOrderSubmissionAuthorization) -> bytes:
    """Compute an object's signed payload, refusing a half-built instance.

    An ``object.__new__`` forgery missing a field raises ``AttributeError``,
    which is not a ``LiveTradingPermissionError`` and would escape the
    permission boundary exactly as the prune race did.
    """
    try:
        return obj._payload()
    except AttributeError as exc:
        raise LiveTradingPermissionError(
            f"{type(obj).__name__} is missing required fields"
        ) from exc


# ---------------------------------------------------------------------------
# The single issuer
# ---------------------------------------------------------------------------


def _require_operator_value(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise LiveTradingPermissionError(
            f"{name} is not set; live trading is operator-enabled only and has no default"
        )
    return value


def _read_operator_money(name: str) -> Decimal:
    """Read one operator-supplied USD ceiling. No default, no inference."""
    raw = _require_operator_value(name)
    if not _MONEY_RE.match(raw):
        raise LiveTradingPermissionError(f"{name} must be a plain USD amount to the cent")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:  # pragma: no cover - guarded by _MONEY_RE
        raise LiveTradingPermissionError(f"{name} is not a decimal amount") from exc
    if amount <= Decimal(0):
        raise LiveTradingPermissionError(f"{name} must be greater than zero")
    return amount


def _read_operator_count(name: str) -> int:
    raw = _require_operator_value(name)
    if not _COUNT_RE.match(raw):
        raise LiveTradingPermissionError(f"{name} must be a plain positive whole number")
    count = int(raw)
    if count < 1:
        raise LiveTradingPermissionError(f"{name} must be at least one")
    return count


def operator_max_order_notional_whole_usd() -> int:
    """The operator's per-order notional ceiling, floored to whole USD.

    The SAME control the permit issuer reads
    (:data:`MAX_ORDER_NOTIONAL_USD_ENV_VAR`), read through the SAME mechanism,
    so there is exactly one reader and one refusal policy for it. Absence,
    blankness and malformation all raise here; nothing defaults.

    Why whole USD, and why this lives with the control rather than at the call
    site: ``RiskEngineConfig.max_notional_per_order`` is typed
    ``dict[str, int]`` (``risk/config.py:44``), so the native cap can only
    carry an integer. Flooring is the conservative direction -- a $25.99
    ceiling becomes a $25 native cap, tighter than the operator asked for,
    never looser. The exact ``Decimal`` ceiling is still enforced to the cent
    by :func:`authorize_live_order_submission`; this is defence in depth
    beneath it, not a replacement for it.

    A ceiling below one whole USD has no integer representation: ``0`` is
    falsy and ``risk/engine.pyx:678`` (``if max_notional_setting:``) skips the
    check entirely for it, so a sub-dollar ceiling would silently mean NO cap.
    That is refused rather than rounded in either direction.

    Returns:
        The floored ceiling in whole USD, always >= 1.

    Raises:
        LiveTradingPermissionError: if the control is unset, blank, malformed,
            non-positive, or cannot be expressed as a whole-USD cap. The
            message names the control and never echoes its value.
    """
    ceiling = _read_operator_money(MAX_ORDER_NOTIONAL_USD_ENV_VAR)
    whole = int(ceiling)  # Truncation toward zero; `_read_operator_money` is > 0.
    if whole < 1:
        raise LiveTradingPermissionError(
            f"{MAX_ORDER_NOTIONAL_USD_ENV_VAR} is below one whole USD and cannot "
            f"be expressed as a native per-order cap: "
            f"`RiskEngineConfig.max_notional_per_order` is typed dict[str, int] "
            f"and a zero there disables the check outright"
        )
    return whole


def issue_live_trading_permit(*, clock: SupportsTimestampNs) -> LiveTradingPermit:
    """Mint the ONE kind of authority the chokepoint accepts.

    Every field is derived from operator-supplied environment. There is
    deliberately no ``env`` parameter and no ceiling parameter: either would
    reintroduce the original defect one level up, letting a caller hand the
    issuer its own authority.

    Raises:
        LiveTradingPermissionError: if the operator gate is absent, if any
            ceiling is missing or malformed, if no operator identity is
            recorded, or if the injected clock is unusable. Absence is always
            a refusal, never a default.
    """
    if os.environ.get(TRADING_ENABLED_ENV_VAR) != "1":
        raise LiveTradingPermissionError(
            f"{TRADING_ENABLED_ENV_VAR} must be exactly '1' to enable live trading; "
            f"there is no default and no truthiness coercion"
        )

    ceiling = _read_operator_money(MAX_ORDER_NOTIONAL_USD_ENV_VAR)
    budget_notional = _read_operator_money(SESSION_NOTIONAL_USD_ENV_VAR)
    budget_orders = _read_operator_count(SESSION_ORDER_COUNT_ENV_VAR)
    operator_id = _require_operator_value(OPERATOR_ID_ENV_VAR).strip()
    issued_at_ns = _read_clock(clock)

    permit_id = secrets.token_bytes(16)
    expires_at_ns = issued_at_ns + PERMIT_TTL_NS
    payload = _permit_payload(
        operator_id=operator_id,
        max_order_notional_usd=ceiling,
        issued_at_ns=issued_at_ns,
        expires_at_ns=expires_at_ns,
        permit_id=permit_id,
        budget_notional_usd=budget_notional,
        budget_order_count=budget_orders,
    )
    permit = LiveTradingPermit(
        operator_id=operator_id,
        max_order_notional_usd=ceiling,
        issued_at_ns=issued_at_ns,
        expires_at_ns=expires_at_ns,
        permit_id=permit_id,
        budget_notional_usd=budget_notional,
        budget_order_count=budget_orders,
        authenticity=_mint_authenticity(payload),
    )
    with _REGISTRY_LOCK:
        _PERMIT_BUDGETS[permit_id] = _Budget(
            remaining_notional_usd=budget_notional,
            remaining_order_count=budget_orders,
        )
    return permit


def _read_clock(clock: SupportsTimestampNs) -> int:
    """Sample the INJECTED clock, refusing anything that is not one.

    ``runtime_checkable`` verifies that ``timestamp_ns`` exists, never what it
    returns, so the conversion is guarded too: a clock returning a string must
    refuse, not ``TypeError`` out of the permission boundary.
    """
    if not isinstance(clock, SupportsTimestampNs):
        raise LiveTradingPermissionError(
            "clock must provide timestamp_ns(); expiry is never sampled from a wall clock here"
        )
    try:
        now_ns = int(clock.timestamp_ns())
    except (TypeError, ValueError) as exc:
        raise LiveTradingPermissionError(
            "clock.timestamp_ns() must return an integer number of nanoseconds"
        ) from exc
    if now_ns <= 0:
        raise LiveTradingPermissionError("the injected clock reports a non-positive timestamp")
    return now_ns


def live_trading_budget_remaining(permit: LiveTradingPermit) -> tuple[Decimal, int]:
    """Report a permit's remaining spend-down, for alarms and audit lines.

    Read-only: nothing here can raise a ceiling. Raises if the permit was not
    issued by this process, because an unknown budget is not a zero budget.
    """
    if not _verify_authenticity(_payload_of(permit), permit.authenticity):
        raise LiveTradingPermissionError(
            "live-trading permit was not issued by issue_live_trading_permit"
        )
    with _REGISTRY_LOCK:
        budget = _PERMIT_BUDGETS.get(permit.permit_id)
    if budget is None:
        raise LiveTradingPermissionError("permit budget is unknown to this process")
    return budget.remaining_notional_usd, budget.remaining_order_count


# ---------------------------------------------------------------------------
# The chokepoint
# ---------------------------------------------------------------------------


def assert_live_order_submission_permitted(
    *,
    credentials: PolymarketUSCredentials | None,
    permit: LiveTradingPermit | None,
    manual_order_indicator: bool | None,
    order_notional_usd: Decimal,
    request_fingerprint: bytes,
    now_ns: int,
) -> LiveOrderSubmissionAuthorization:
    """Authorize the single future live create-order chokepoint.

    Call immediately before dispatching an order-submission request, and pass
    the returned capability to the dispatch surface. Credentials alone are
    never permission to trade, and neither is possession of a permit object:
    the permit's issuer tag is verified here, so an ``__init__``-bypassing
    forgery is refused at use as well as at construction.

    Args:
        request_fingerprint: opaque bytes identifying THIS request, computed by
            the caller over whatever uniquely determines it. The returned
            capability is bound to it and will refuse any other.
        now_ns: the current time from the injected clock. Never sampled here.

    Returns:
        A single-use capability bound to ``request_fingerprint`` and to
        ``order_notional_usd``.

    Raises:
        LiveTradingPermissionError: on any refusal. Nothing here returns a
            falsey value a caller could ignore.
    """
    # Pruning runs FIRST so it stays reachable once the issuing permit has
    # expired. Behind every permit check, an expired permit meant the registry
    # could never be pruned again and grew unbounded for the process lifetime.
    _prune_expired_nonces(now_ns)

    if credentials is None or not credentials.is_complete():
        raise LiveTradingPermissionError("valid credentials are required for live trading")
    if permit is None:
        raise LiveTradingPermissionError("explicit live-trading permit is required")
    if not _verify_authenticity(_payload_of(permit), permit.authenticity):
        raise LiveTradingPermissionError(
            "live-trading permit was not issued by issue_live_trading_permit"
        )
    if now_ns < permit.issued_at_ns:
        raise LiveTradingPermissionError("permit used before it was issued; clock is untrusted")
    if now_ns > permit.expires_at_ns:
        raise LiveTradingPermissionError("live-trading permit has expired")
    if manual_order_indicator is None:
        raise LiveTradingPermissionError("manualOrderIndicator must be explicit")
    if type(order_notional_usd) is not Decimal:
        raise _refuse("order_notional_usd", order_notional_usd, "Decimal")
    if order_notional_usd <= Decimal(0):
        raise LiveTradingPermissionError("order notional must be positive")
    if order_notional_usd > permit.max_order_notional_usd:
        raise LiveTradingPermissionError("order notional exceeds permit maximum")

    nonce = secrets.token_bytes(16)
    request_digest = sha256(request_fingerprint).digest()
    payload = _authorization_payload(
        request_digest=request_digest,
        order_notional_usd=order_notional_usd,
        expires_at_ns=permit.expires_at_ns,
        nonce=nonce,
    )
    authorization = LiveOrderSubmissionAuthorization(
        request_digest=request_digest,
        order_notional_usd=order_notional_usd,
        expires_at_ns=permit.expires_at_ns,
        nonce=nonce,
        authenticity=_mint_authenticity(payload),
    )

    # Spend-down and nonce registration are one transaction: a capability must
    # never exist without having cost budget, and budget must never be spent
    # without a capability to show for it.
    with _REGISTRY_LOCK:
        budget = _PERMIT_BUDGETS.get(permit.permit_id)
        if budget is None:
            raise LiveTradingPermissionError("permit budget is unknown to this process")
        if budget.remaining_order_count < 1:
            raise LiveTradingPermissionError("permit order-count budget is exhausted")
        if order_notional_usd > budget.remaining_notional_usd:
            raise LiveTradingPermissionError(
                "order notional exceeds the permit's remaining notional budget"
            )
        budget.remaining_order_count -= 1
        budget.remaining_notional_usd -= order_notional_usd
        _UNSPENT_NONCES[nonce] = authorization.expires_at_ns

    return authorization
