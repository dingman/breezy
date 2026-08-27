"""Barrier F1: the venue fee schedule fails closed in SUBSTANCE, not in prose.

Why this file exists (the defect it pins). ``parsing.parse_binary_option``
originally constructed ``BinaryOption`` without passing
``maker_fee``/``taker_fee``. Nautilus defaults them with
``maker_fee or Decimal(0)`` (``model/instruments/binary_option.pyx:148-149``),
so every instrument this adapter loaded carried a *real, valid, typed*
``Decimal(0)`` in the two fields that generic Nautilus machinery actually
reads -- ``MakerTakerFeeModel.get_commission`` multiplies notional by
``instrument.maker_fee``/``instrument.taker_fee`` and nothing else
(``backtest/models/fee.pyx:96-99``). The ``fee_schedule_status="UNKNOWN"``
marker lived only in the loosely-typed ``info`` dict, which nothing was forced
to consult. The module therefore shipped exactly the zero-fee illusion its
docstring claimed to prevent.

The venue fee is not negligible: ``fee = theta * C * p * (1 - p)`` with a
taker ``theta`` of 0.06, i.e. $1.50 per 100 contracts at p=0.50
(``polymarket-us-integration`` skill, "Fee Formula"). A silent zero inflates
apparent edge on every quote and bleeds real money once execution lands.

UPDATE 2026-08-26 (G-15). ``theta`` is published per market in every captured
payload, so the schedule is now DERIVED and marked ``KNOWN``, the fee itself
is carried by ``fees.PolymarketUSFeeModel``, and the two flat fields carry
``theta`` rather than zero. This barrier is NOT thereby retired, for two
reasons that are each pinned by a test below: the zero still appears verbatim
whenever the venue omits ``feeCoefficient``, and ``theta`` read as a flat
notional rate is still the wrong number -- merely wrong in the safe
(overstating) direction.

The fix has two halves, and this file proves both:

1. **A guard.** ``parsing.assert_fee_schedule_known(instrument)`` raises
   ``FeeScheduleUnknownError`` unless the instrument's ``info`` carries
   ``fee_schedule_status == "KNOWN"``. Absence of the marker is treated as
   UNKNOWN, so a foreign instrument or a future refactor that drops the key
   fails closed rather than open.
2. **A barrier that forces the guard to be called.** Instruments must stay
   loadable (the read-only smoke test needs them to receive quotes), so the
   loader cannot simply refuse. Instead, rule F1 below makes it a *test
   failure* for any venue-touching module under ``src/`` or ``scripts/`` to
   read ``.maker_fee``/``.taker_fee`` unless the SAME RECEIVER is guarded in
   the same function scope or an enclosing one.

   Granularity was MODULE-level until 2026-08-25, and that was too weak: a
   module could call ``assert_fee_schedule_known(throwaway)`` once and then
   read ``.taker_fee`` freely on a completely different, unchecked instrument,
   fully satisfying the barrier. The rule is now call-site granular. It is
   still purely static and still infers no types: it compares the AST SHAPE of
   the guard's argument against the AST shape of the read's receiver
   (``ast.dump(..., include_attributes=False)``), and requires the guard's own
   innermost scope to enclose the read.

RULE F1, stated so it is falsifiable (and proved non-vacuous by the
``*_detects_*`` tests below):

  Step 1 -- classify the module with the shipped venue-touching classifier
  (C1-C4) from ``test_polymarket_us_readonly_guard``. Non-venue-touching
  modules are exempt, for the same reason B4 exempts them.

  Step 2 -- inside a venue-touching module, collect every
  ``ast.Attribute`` whose ``attr`` is ``maker_fee`` or ``taker_fee``, plus
  every ``getattr(x, "maker_fee")``-shaped call (without which the attribute
  rule is trivially bypassed).

  Step 3 -- a collected read is EXEMPT only if some call named
  ``assert_fee_schedule_known`` carries a first positional argument whose AST
  shape equals the read's receiver, and that call's innermost enclosing scope
  (``FunctionDef``/``AsyncFunctionDef``/``Lambda``/``Module``) also encloses
  the read. Everything else is a violation. Class bodies are deliberately NOT
  treated as scopes: a guard in a class body and a read in a method are not
  sequenced with respect to each other.

RESIDUAL GAPS, stated precisely rather than papered over. This barrier is
syntactic, not a dataflow analysis, so three holes remain OPEN and are pinned
by tests so they cannot be mistaken for closed:

  G1 -- **rebinding between guard and read.** ``i = checked;
  assert_fee_schedule_known(i); i = unchecked; return i.taker_fee`` passes,
  because ``i`` is syntactically identical at both sites. Closing this needs
  reaching-definitions analysis. Pinned by
  ``test_the_documented_residual_gap_is_real_and_reported_honestly``.

  G2 -- **fully dynamic attribute names.** ``getattr(inst, "maker" + "_fee")``
  is not statically detectable. Same class of gap that barrier B4 documents.

  G3 -- **cross-module reads.** A helper in module A that returns
  ``inst.taker_fee`` is caught in A, but the rule cannot relate A's guard to
  B's call site. Per-module analysis is the deliberate scope.

None of the three is reachable by accident, which is the failure mode this
barrier exists to stop. What IS now closed is the accidental case the reviewer
found: a guard on one object silently licensing a read on another.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.errors import (
    FeeScheduleUnknownError,
    PolymarketUSError,
)
from breezy.adapters.polymarket_us.parsing import (
    FEE_SCHEDULE_STATUS_KEY,
    FEE_SCHEDULE_STATUS_KNOWN,
    FEE_SCHEDULE_STATUS_UNKNOWN,
    assert_fee_schedule_known,
    parse_binary_option,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from tests.unit.test_polymarket_us_readonly_guard import (
    is_venue_touching,
    iter_python_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

TS_INIT = 1_787_617_213_000_000_000

#: Roots scanned by rule F1 (same shape as barrier B4).
FEE_SCAN_ROOTS = ("src", "scripts")

_FEE_ATTRS = frozenset({"maker_fee", "taker_fee"})
_GUARD_NAME = "assert_fee_schedule_known"


@dataclass(frozen=True, slots=True)
class FeeViolation:
    path: str
    lineno: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: [F1] {self.detail}"


#: AST nodes that open a new function scope. `Module` terminates the chain.
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Map every node to its parent. `ast` does not record this itself."""
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _scope_chain(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> list[ast.AST]:
    """Return `node`'s enclosing scopes, innermost first.

    Class bodies are intentionally NOT scopes here: a guard at class-body level
    and a read inside a method are not sequenced with respect to one another,
    so treating the class as an enclosing scope would re-open the module-level
    hole this rule exists to close.
    """
    chain: list[ast.AST] = []
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, _SCOPE_NODES):
            chain.append(current)
        current = parents.get(current)
    return chain


def _receiver_key(node: ast.expr) -> str:
    """A structural fingerprint of an expression, ignoring source positions.

    `ast.dump` with `include_attributes=False` compares SHAPE, so `self._a`
    and `self._b` differ while `self._a` written twice matches. This is pure
    syntax: no type is inferred and no name is resolved.
    """
    return ast.dump(node, include_attributes=False)


def _fee_reads(tree: ast.AST) -> Iterator[tuple[ast.AST, ast.expr, int, str]]:
    """Yield `(node, receiver_expr, lineno, detail)` for every fee read."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _FEE_ATTRS:
            yield node, node.value, node.lineno, f"reads .{node.attr}"
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value in _FEE_ATTRS
        ):
            yield node, node.args[0], node.lineno, f"getattr bypass to .{node.args[1].value}"


def _guard_calls(tree: ast.AST) -> Iterator[tuple[ast.AST, str]]:
    """Yield `(call_node, receiver_key)` for each guard call carrying an argument.

    A guard call with NO positional argument names no receiver and therefore
    licenses nothing -- it is skipped rather than treated as a wildcard.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != _GUARD_NAME or not node.args:
            continue
        yield node, _receiver_key(node.args[0])


def find_unguarded_fee_reads(path: str, source: str) -> list[FeeViolation]:
    """Apply rule F1 to one module. Non-venue-touching modules pass.

    A fee read is guarded only when some ``assert_fee_schedule_known(x)`` call
    exists whose argument ``x`` is structurally identical to the read's
    receiver, in the read's own function scope or an enclosing one.
    """
    tree = ast.parse(source, filename=path)
    if not is_venue_touching(path, tree):
        return []
    parents = _parents(tree)
    # A guard covers exactly its OWN innermost scope and everything nested
    # inside it. Comparing whole scope chains instead would put `Module` in
    # every intersection and re-open the module-level hole this rule closes.
    guards = [(_scope_chain(call, parents)[0], key) for call, key in _guard_calls(tree)]

    violations: list[FeeViolation] = []
    for node, receiver, lineno, detail in _fee_reads(tree):
        key = _receiver_key(receiver)
        enclosing = set(_scope_chain(node, parents))
        if any(k == key and scope in enclosing for scope, k in guards):
            continue
        violations.append(FeeViolation(path, lineno, detail))
    return violations


def scan_unguarded_fee_reads(roots: tuple[str, ...] = FEE_SCAN_ROOTS) -> list[FeeViolation]:
    return [
        v for path, src in iter_python_sources(roots) for v in find_unguarded_fee_reads(path, src)
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def open_market() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8")
    )
    return payload


@pytest.fixture
def open_instrument(open_market: dict[str, Any]) -> BinaryOption:
    return parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


@pytest.fixture
def unknown_instrument(open_market: dict[str, Any]) -> BinaryOption:
    """A market whose ``feeCoefficient`` the venue did not send.

    The guard tests below need a genuinely UNKNOWN instrument. Since
    2026-08-26 the captured open market parses to KNOWN, so the UNKNOWN case
    is constructed by removing the field rather than by relying on the
    adapter never resolving a schedule.
    """
    del open_market["market"]["feeCoefficient"]
    return parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


# ---------------------------------------------------------------------------
# The hazard itself, pinned rather than certified as acceptable
# ---------------------------------------------------------------------------


def test_the_flat_fee_fields_carry_theta_and_are_defended_only_by_barrier_f2(
    open_instrument: BinaryOption,
) -> None:
    """The zero is gone; what replaced it is NOT thereby "conservative".

    Until 2026-08-26 these fields held ``Decimal(0)`` -- a real, typed,
    usable zero that ``MakerTakerFeeModel.get_commission`` would have charged
    as a FREE venue (``backtest/models/fee.pyx:96-99``). They now carry the
    market's own ``theta``.

    That is better, and it is still wrong. Read as a flat notional rate
    ``theta`` overstates by ``theta * C * p^2``, and the RELATIVE error is
    ``1/(1-p)`` -- unbounded as ``p -> 1``, and it destroys the venue fee's
    symmetry about ``p = 0.50``. That is a directional tilt toward the cheap
    side of every book, not a conservative haircut. The full comparison of
    the two REAL models lives in ``test_polymarket_us_fee_model.py``; kept
    out of this file so the property has exactly one home.

    Setting the fields back to zero would be strictly WORSE, because the
    status is now KNOWN: the guard would open and a default
    ``MakerTakerFeeModel`` would charge nothing at all. Neither value is safe
    while a default fee model can reach a venue, which is what barrier F2
    below forbids.
    """
    assert_fee_schedule_known(open_instrument)

    theta = Decimal(open_instrument.info["fee_coefficient"])
    assert theta == Decimal("0.06")
    assert open_instrument.maker_fee == theta
    assert open_instrument.taker_fee == theta
    assert open_instrument.taker_fee != Decimal(0), "a zero here would read as a FREE venue"


def test_an_instrument_whose_coefficient_the_venue_never_sent_still_holds_the_zero(
    open_market: dict[str, Any],
) -> None:
    """The original hazard is unchanged wherever the venue stays silent.

    This is why barrier F1 below is still load-bearing rather than historical.
    """
    del open_market["market"]["feeCoefficient"]
    instrument = parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)

    assert instrument.info[FEE_SCHEDULE_STATUS_KEY] == FEE_SCHEDULE_STATUS_UNKNOWN
    assert instrument.maker_fee == Decimal(0)
    assert instrument.taker_fee == Decimal(0)


def test_the_info_marker_is_derived_from_the_payload_and_binds_nobody_by_itself(
    open_instrument: BinaryOption,
    open_market: dict[str, Any],
) -> None:
    """KNOWN is written only when a coefficient was actually parsed."""
    assert open_instrument.info[FEE_SCHEDULE_STATUS_KEY] == FEE_SCHEDULE_STATUS_KNOWN

    del open_market["market"]["feeCoefficient"]
    silent = parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    assert silent.info[FEE_SCHEDULE_STATUS_KEY] == FEE_SCHEDULE_STATUS_UNKNOWN
    assert FEE_SCHEDULE_STATUS_UNKNOWN != FEE_SCHEDULE_STATUS_KNOWN


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_the_guard_refuses_an_instrument_whose_fee_schedule_is_unknown(
    unknown_instrument: BinaryOption,
) -> None:
    with pytest.raises(FeeScheduleUnknownError, match="fee schedule"):
        assert_fee_schedule_known(unknown_instrument)


def test_the_guard_failure_is_catchable_as_the_adapter_base_error(
    unknown_instrument: BinaryOption,
) -> None:
    with pytest.raises(PolymarketUSError):
        assert_fee_schedule_known(unknown_instrument)


def test_the_guard_names_the_two_fields_that_hold_the_misleading_zero(
    unknown_instrument: BinaryOption,
) -> None:
    """An operator reading the traceback must learn WHY the zero is not a fee."""
    with pytest.raises(FeeScheduleUnknownError) as excinfo:
        assert_fee_schedule_known(unknown_instrument)
    message = str(excinfo.value)
    assert "maker_fee" in message
    assert "taker_fee" in message


def test_the_guard_treats_a_missing_marker_as_unknown_not_as_known(
    open_instrument: BinaryOption,
) -> None:
    """Fail closed on absence: a foreign instrument must not read as KNOWN."""
    stripped = dict(open_instrument.info)
    del stripped[FEE_SCHEDULE_STATUS_KEY]
    foreign = _rebuild_with_info(open_instrument, stripped)
    with pytest.raises(FeeScheduleUnknownError):
        assert_fee_schedule_known(foreign)


def test_the_guard_treats_an_instrument_with_no_info_at_all_as_unknown() -> None:
    class InfolessInstrument:
        pass

    with pytest.raises(FeeScheduleUnknownError):
        assert_fee_schedule_known(InfolessInstrument())


def test_the_guard_passes_once_the_schedule_is_marked_known(
    open_instrument: BinaryOption,
) -> None:
    """Non-vacuity: the guard is not an unconditional raise."""
    resolved = dict(open_instrument.info)
    resolved[FEE_SCHEDULE_STATUS_KEY] = FEE_SCHEDULE_STATUS_KNOWN
    # Returns None; the assertion IS that it does not raise. Written as a bare
    # call because `assert f(...) is None` reads as a value check and is not one.
    assert_fee_schedule_known(_rebuild_with_info(open_instrument, resolved))


def _rebuild_with_info(instrument: BinaryOption, info: dict[str, Any]) -> BinaryOption:
    """Clone ``instrument`` with a replaced ``info`` (``info`` is read-only)."""
    return BinaryOption(
        instrument_id=instrument.id,
        raw_symbol=instrument.raw_symbol,
        outcome=instrument.outcome,
        description=instrument.description,
        asset_class=instrument.asset_class,
        currency=instrument.quote_currency,
        price_precision=instrument.price_precision,
        price_increment=instrument.price_increment,
        size_precision=instrument.size_precision,
        size_increment=instrument.size_increment,
        activation_ns=instrument.activation_ns,
        expiration_ns=instrument.expiration_ns,
        min_quantity=instrument.min_quantity,
        ts_event=instrument.ts_event,
        ts_init=instrument.ts_init,
        info=info,
    )


# ---------------------------------------------------------------------------
# Barrier F1
# ---------------------------------------------------------------------------


def test_no_venue_module_reads_a_fee_field_without_calling_the_guard() -> None:
    violations = scan_unguarded_fee_reads()
    assert violations == [], (
        "F1 violations (the venue fee schedule is [UNKNOWN]; maker_fee/taker_fee "
        "hold a placeholder Decimal(0), so any module reading them must first call "
        f"{_GUARD_NAME}):\n" + "\n".join(str(v) for v in violations)
    )


def test_f1_detects_an_unguarded_fee_read_inside_the_adapter_package() -> None:
    source = "def edge(inst, notional):\n    return notional * inst.taker_fee\n"
    path = "src/breezy/adapters/polymarket_us/sizing.py"
    assert [v.detail for v in find_unguarded_fee_reads(path, source)] == ["reads .taker_fee"]


def test_f1_detects_an_unguarded_fee_read_in_a_venue_touching_script() -> None:
    """Classifier rule C3 pulls a bare script into scope via the venue host."""
    source = 'BASE = "https://api.polymarket.us"\n\n\ndef f(i):\n    return i.maker_fee\n'
    assert find_unguarded_fee_reads("scripts/analysis/edge.py", source) != []


def test_f1_detects_the_getattr_bypass_of_the_attribute_rule() -> None:
    source = 'import polymarket_us\n\n\ndef f(i):\n    return getattr(i, "taker_fee")\n'
    details = [v.detail for v in find_unguarded_fee_reads("scripts/evil.py", source)]
    assert details == ["getattr bypass to .taker_fee"]


def test_f1_permits_a_fee_read_in_a_module_that_calls_the_guard() -> None:
    source = (
        "from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known\n"
        "\n"
        "\n"
        "def edge(inst, notional):\n"
        "    assert_fee_schedule_known(inst)\n"
        "    return notional * inst.taker_fee\n"
    )
    path = "src/breezy/adapters/polymarket_us/sizing.py"
    assert find_unguarded_fee_reads(path, source) == []


def test_f1_does_not_fire_on_a_non_venue_module() -> None:
    source = "def f(i):\n    return i.taker_fee\n"
    assert find_unguarded_fee_reads("src/breezy/runtime/health.py", source) == []


def test_f1_does_not_fire_on_a_keyword_argument_named_maker_fee() -> None:
    """Constructing an instrument WITH a fee is not a fee read."""
    source = "def build(c):\n    return c(maker_fee=None, taker_fee=None)\n"
    path = "src/breezy/adapters/polymarket_us/parsing.py"
    assert find_unguarded_fee_reads(path, source) == []


def test_f1_scan_covers_both_src_and_scripts() -> None:
    scanned = {path for path, _ in iter_python_sources(FEE_SCAN_ROOTS)}
    assert any(p.startswith("src/") for p in scanned)
    assert any(p.startswith("scripts/") for p in scanned)


# ---------------------------------------------------------------------------
# Rule F1 tightened to the CALL SITE (SEC finding 3, 2026-08-25)
# ---------------------------------------------------------------------------
#
# Module granularity let a module guard a THROWAWAY instrument and then read
# `.maker_fee` on a completely different, unchecked one. The barrier was
# satisfied by the mere presence of the guard's name anywhere in the file.
#
# The tightening is still statically decidable and still needs no receiver-type
# inference: a fee read is guarded only when some `assert_fee_schedule_known(x)`
# call exists whose argument `x` is SYNTACTICALLY IDENTICAL to the receiver of
# the fee read, in the same function scope or an enclosing one.


def test_module_granular_guard_on_a_different_object_is_now_a_violation() -> None:
    """The exploit the reviewer described must no longer satisfy the barrier."""
    source = (
        "from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known\n"
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient\n"
        "\n"
        "def charge(checked, unchecked):\n"
        "    assert_fee_schedule_known(checked)\n"
        "    return unchecked.taker_fee\n"
    )

    violations = find_unguarded_fee_reads("src/breezy/adapters/polymarket_us/x.py", source)

    assert violations, "guarding a throwaway object must not license an unchecked read"
    assert violations[0].lineno == 6


def test_guarding_the_same_receiver_in_the_same_scope_still_passes() -> None:
    source = (
        "from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known\n"
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient\n"
        "\n"
        "def charge(instrument):\n"
        "    assert_fee_schedule_known(instrument)\n"
        "    return instrument.taker_fee\n"
    )

    assert find_unguarded_fee_reads("src/breezy/adapters/polymarket_us/x.py", source) == []


def test_a_guard_in_an_enclosing_scope_covers_a_nested_read() -> None:
    """Enclosing scopes count; a closure cannot be forced to re-guard."""
    source = (
        "from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known\n"
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient\n"
        "\n"
        "def outer(instrument):\n"
        "    assert_fee_schedule_known(instrument)\n"
        "    def inner():\n"
        "        return instrument.maker_fee\n"
        "    return inner\n"
    )

    assert find_unguarded_fee_reads("src/breezy/adapters/polymarket_us/x.py", source) == []


def test_a_guard_in_a_sibling_scope_does_not_cover_the_read() -> None:
    """Scope containment is real containment, not 'somewhere in the file'."""
    source = (
        "from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known\n"
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient\n"
        "\n"
        "def guarded(instrument):\n"
        "    assert_fee_schedule_known(instrument)\n"
        "\n"
        "def unguarded(instrument):\n"
        "    return instrument.taker_fee\n"
    )

    violations = find_unguarded_fee_reads("src/breezy/adapters/polymarket_us/x.py", source)

    assert violations
    assert violations[0].lineno == 8


def test_attribute_receivers_are_compared_structurally_not_by_name() -> None:
    """`self._a.maker_fee` is not guarded by `assert_fee_schedule_known(self._b)`."""
    source = (
        "from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known\n"
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient\n"
        "\n"
        "class C:\n"
        "    def f(self):\n"
        "        assert_fee_schedule_known(self._b)\n"
        "        return self._a.maker_fee\n"
    )

    assert find_unguarded_fee_reads("src/breezy/adapters/polymarket_us/x.py", source)

    ok = source.replace("assert_fee_schedule_known(self._b)", "assert_fee_schedule_known(self._a)")
    assert find_unguarded_fee_reads("src/breezy/adapters/polymarket_us/x.py", ok) == []


def test_getattr_bypass_is_held_to_the_same_receiver_rule() -> None:
    source = (
        "from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known\n"
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient\n"
        "\n"
        "def charge(checked, unchecked):\n"
        "    assert_fee_schedule_known(checked)\n"
        "    return getattr(unchecked, 'taker_fee')\n"
    )

    assert find_unguarded_fee_reads("src/breezy/adapters/polymarket_us/x.py", source)


def test_a_bare_guard_call_with_no_argument_guards_nothing() -> None:
    """A no-arg call cannot name a receiver, so it cannot license any read."""
    source = (
        "from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known\n"
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient\n"
        "\n"
        "def charge(instrument):\n"
        "    assert_fee_schedule_known()\n"
        "    return instrument.taker_fee\n"
    )

    assert find_unguarded_fee_reads("src/breezy/adapters/polymarket_us/x.py", source)


def test_the_documented_residual_gap_is_real_and_reported_honestly() -> None:
    """Rebinding the name between guard and read defeats syntactic identity.

    Asserted so the gap is a KNOWN, tested property rather than an assumption.
    Closing it needs dataflow analysis, which this barrier deliberately does
    not attempt; see the RESIDUAL GAP note in the module docstring.
    """
    source = (
        "from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known\n"
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient\n"
        "\n"
        "def charge(checked, unchecked):\n"
        "    instrument = checked\n"
        "    assert_fee_schedule_known(instrument)\n"
        "    instrument = unchecked\n"
        "    return instrument.taker_fee\n"
    )

    assert find_unguarded_fee_reads("src/breezy/adapters/polymarket_us/x.py", source) == []


def test_the_repository_still_has_no_unguarded_fee_reads() -> None:
    """The tightened rule must not regress the shipped tree."""
    assert scan_unguarded_fee_reads() == []


# ---------------------------------------------------------------------------
# Barrier F2: no backtest venue may take the DEFAULT fee model
# ---------------------------------------------------------------------------
#
# The defect this exists to stop, stated plainly. `PolymarketUSFeeModel`
# computes the venue's real `theta * C * p * (1 - p)`. It had ZERO production
# callers: no module under `src/` or `scripts/` constructed a `BacktestEngine`
# venue at all, and the class was not even exported from the package root.
#
# Meanwhile `BacktestEngine.add_venue` DEFAULTS its `fee_model` argument to
# `MakerTakerFeeModel()` (`backtest/engine.pyx:643-644`, verified):
#
#     if fee_model is None:
#         fee_model = MakerTakerFeeModel()
#
# and the `BacktestNode` path lands in the same place: `BacktestVenueConfig`
# defaults `fee_model=None`, `get_fee_model` returns `None` for it
# (`backtest/node.py:872-875`), and `node.py:401` passes that straight to
# `add_venue`. So on BOTH paths, the accurate model sits on the shelf while
# the generic one is what actually runs, reading `instrument.taker_fee` and
# nothing else (`backtest/models/fee.pyx:96-99`).
#
# That generic read is not a conservative haircut. It computes `theta*C*p`
# against the venue's `theta*C*p*(1-p)`: absolute error `theta*C*p^2`,
# RELATIVE error `1/(1-p)` -- unbounded as `p -> 1` -- and it destroys the
# venue fee's symmetry about `p = 0.50`, so a YES at p=0.90 and a NO at p=0.10
# (identically priced by the venue, $0.54 each) are charged $5.40 and $0.60.
# For a weather bot, confident forecasts land exactly in the worst region.
#
# Setting the flat fields back to `Decimal(0)` is NOT the fix: the schedule is
# now KNOWN, so the F1 guard opens, and a generic model would then charge
# NOTHING -- a real, valid zero that reads as a free venue. Understating is
# strictly worse than overstating. Neither flat value is safe while a default
# fee model can reach a venue.
#
# Hence: keep the flat fields at `theta` (so a circumvention errs in the
# overstating direction) and make them UNREACHABLE. There is no such call site
# in the repository today. This barrier lands NOW, before one appears, so it
# goes RED the moment somebody adds a default-fee-model venue.
#
# RULE F2, stated so it is falsifiable:
#
#   Step 1 -- scan EVERY module under `src/` and `scripts/`. Unlike F1 there
#   is no venue-touching filter: a backtest-wiring module need not import the
#   adapter or name the venue host to construct an engine that trades
#   Polymarket.us instruments, so classifier exemption would be a hole.
#
#   Step 2 -- collect every `ast.Call` whose callee name is `add_venue` (the
#   engine path) or `BacktestVenueConfig` (the node path, which reaches
#   `add_venue` through `node.py:401`).
#
#   Step 3 -- a call is EXEMPT only if it carries a `fee_model=` keyword whose
#   value expression mentions `PolymarketUSFeeModel`, as a `Name`, as an
#   `Attribute`, or inside a string constant (which is how
#   `ImportableFeeModelConfig(fee_model_path=...)` names a class). Anything
#   else -- omitted, `None`, a different model, or a `**kwargs` splat that
#   hides the argument -- is a violation.
#
# RESIDUAL GAPS, stated rather than papered over:
#
#   H1 -- indirection. `fee_model=pick()` where `pick()` returns the default
#   passes if the returned expression is not visible at the call site. Same
#   class of gap as F1's G3, and the same deliberate per-call-site scope.
#
#   H2 -- a fee model wired through a config file or environment lookup rather
#   than source. Nothing in the repository does this; if it ever does, this
#   barrier must be extended rather than exempted.

#: Venue-construction callees that reach `BacktestEngine.add_venue`.
_VENUE_CONSTRUCTORS = frozenset({"add_venue", "BacktestVenueConfig"})

#: The only fee model a Polymarket.us backtest venue may be given.
_REQUIRED_FEE_MODEL = "PolymarketUSFeeModel"


@dataclass(frozen=True, slots=True)
class VenueFeeViolation:
    path: str
    lineno: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: [F2] {self.detail}"


def _mentions_required_fee_model(node: ast.AST) -> bool:
    """True when ``PolymarketUSFeeModel`` appears anywhere in ``node``.

    Covers the three ways it can legitimately be named: bare (``Name``),
    qualified (``Attribute``, e.g. ``fees.PolymarketUSFeeModel``), and as a
    string inside an ``ImportableFeeModelConfig(fee_model_path=...)``.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == _REQUIRED_FEE_MODEL:
            return True
        if isinstance(child, ast.Attribute) and child.attr == _REQUIRED_FEE_MODEL:
            return True
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and _REQUIRED_FEE_MODEL in child.value
        ):
            return True
    return False


def find_default_fee_model_venues(path: str, source: str) -> list[VenueFeeViolation]:
    """Apply rule F2 to one module. No venue-touching exemption -- see Step 1."""
    tree = ast.parse(source, filename=path)

    violations: list[VenueFeeViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _VENUE_CONSTRUCTORS:
            continue

        keyword = next((kw for kw in node.keywords if kw.arg == "fee_model"), None)
        if keyword is None:
            violations.append(
                VenueFeeViolation(
                    path,
                    node.lineno,
                    f"{name}(...) omits `fee_model=`; BacktestEngine.add_venue then "
                    f"defaults to MakerTakerFeeModel (backtest/engine.pyx:643-644), "
                    f"which reads instrument.taker_fee as a flat notional rate. Pass "
                    f"fee_model={_REQUIRED_FEE_MODEL}().",
                )
            )
        elif not _mentions_required_fee_model(keyword.value):
            violations.append(
                VenueFeeViolation(
                    path,
                    node.lineno,
                    f"{name}(...) passes a `fee_model=` that does not name "
                    f"{_REQUIRED_FEE_MODEL}; the Polymarket.us fee is "
                    f"theta * C * p * (1 - p) and no flat rate can express it.",
                )
            )
    return violations


def scan_default_fee_model_venues(
    roots: tuple[str, ...] = FEE_SCAN_ROOTS,
) -> list[VenueFeeViolation]:
    return [
        v
        for path, src in iter_python_sources(roots)
        for v in find_default_fee_model_venues(path, src)
    ]


def test_no_module_constructs_a_backtest_venue_without_the_venue_fee_model() -> None:
    """THE barrier. Goes RED the moment a default-fee-model venue appears."""
    violations = scan_default_fee_model_venues()
    assert violations == [], (
        "F2 violations (a BacktestEngine venue would silently use "
        "MakerTakerFeeModel, which reads the flat maker_fee/taker_fee fields as "
        "notional rates -- unbounded relative error as p -> 1):\n"
        + "\n".join(str(v) for v in violations)
    )


def test_f2_detects_an_add_venue_call_with_no_fee_model() -> None:
    """Non-vacuity: exactly the call site that does not exist yet."""
    source = (
        "from nautilus_trader.backtest.engine import BacktestEngine\n"
        "\n"
        "def build():\n"
        "    engine = BacktestEngine()\n"
        "    engine.add_venue(venue=V, oms_type=O, account_type=A, starting_balances=B)\n"
        "    return engine\n"
    )
    violations = find_default_fee_model_venues("src/breezy/runtime/backtest.py", source)

    assert len(violations) == 1
    assert violations[0].lineno == 5
    assert "omits `fee_model=`" in violations[0].detail


def test_f2_detects_an_add_venue_call_passing_an_explicit_none() -> None:
    """`fee_model=None` is the DEFAULT spelled out, not an opt-out."""
    source = "def build(engine):\n    engine.add_venue(venue=V, fee_model=None)\n"

    assert find_default_fee_model_venues("src/breezy/runtime/backtest.py", source) != []


def test_f2_detects_an_add_venue_call_passing_a_different_fee_model() -> None:
    source = (
        "from nautilus_trader.backtest.models import MakerTakerFeeModel\n"
        "\n"
        "def build(engine):\n"
        "    engine.add_venue(venue=V, fee_model=MakerTakerFeeModel())\n"
    )
    violations = find_default_fee_model_venues("src/breezy/runtime/backtest.py", source)

    assert len(violations) == 1
    assert "does not name PolymarketUSFeeModel" in violations[0].detail


def test_f2_detects_a_kwargs_splat_that_hides_the_fee_model_argument() -> None:
    """`add_venue(**settings)` names no fee model, so it fails closed."""
    source = "def build(engine, settings):\n    engine.add_venue(**settings)\n"

    assert find_default_fee_model_venues("src/breezy/runtime/backtest.py", source) != []


def test_f2_detects_the_backtest_node_config_path_as_well_as_the_engine_path() -> None:
    """`BacktestVenueConfig(fee_model=None)` reaches the same default.

    `get_fee_model` returns `None` for it (`backtest/node.py:872-875`) and
    `node.py:401` passes that straight into `add_venue`.
    """
    source = (
        "from nautilus_trader.backtest.config import BacktestVenueConfig\n"
        "\n"
        "CONFIG = BacktestVenueConfig(\n"
        '    name="POLYMARKET_US", oms_type="NETTING", account_type="CASH",\n'
        '    starting_balances=["1000 USD"],\n'
        ")\n"
    )
    violations = find_default_fee_model_venues("src/breezy/runtime/backtest.py", source)

    assert len(violations) == 1
    assert "BacktestVenueConfig" in violations[0].detail


def test_f2_accepts_an_add_venue_call_that_passes_the_venue_fee_model() -> None:
    """Non-vacuity in the other direction: the barrier is satisfiable."""
    source = (
        "from breezy.adapters.polymarket_us import PolymarketUSFeeModel\n"
        "\n"
        "def build(engine):\n"
        "    engine.add_venue(venue=V, fee_model=PolymarketUSFeeModel())\n"
    )

    assert find_default_fee_model_venues("src/breezy/runtime/backtest.py", source) == []


def test_f2_accepts_a_qualified_reference_to_the_venue_fee_model() -> None:
    source = (
        "from breezy.adapters.polymarket_us import fees\n"
        "\n"
        "def build(engine):\n"
        "    engine.add_venue(venue=V, fee_model=fees.PolymarketUSFeeModel())\n"
    )

    assert find_default_fee_model_venues("src/breezy/runtime/backtest.py", source) == []


def test_f2_accepts_the_importable_config_spelling_used_by_backtest_node() -> None:
    """`ImportableFeeModelConfig` names the class as a STRING path."""
    source = (
        "from nautilus_trader.backtest.config import BacktestVenueConfig\n"
        "from nautilus_trader.backtest.config import ImportableFeeModelConfig\n"
        "\n"
        "CONFIG = BacktestVenueConfig(\n"
        '    name="POLYMARKET_US",\n'
        "    fee_model=ImportableFeeModelConfig(\n"
        '        fee_model_path="breezy.adapters.polymarket_us.fees:PolymarketUSFeeModel",\n'
        '        config_path="x:Y", config={},\n'
        "    ),\n"
        ")\n"
    )

    assert find_default_fee_model_venues("src/breezy/runtime/backtest.py", source) == []


def test_f2_scans_every_module_not_only_the_venue_touching_ones() -> None:
    """A backtest-wiring module need not look venue-touching to F1's classifier.

    Pinned because exempting it would be the obvious hole: the module below
    imports no adapter symbol and names no venue host, so F1's C1-C4
    classifier would let it through, yet its venue trades Polymarket.us
    instruments loaded from the catalog.
    """
    source = (
        "from nautilus_trader.backtest.engine import BacktestEngine\n"
        "\n"
        "def build():\n"
        "    engine = BacktestEngine()\n"
        "    engine.add_venue(venue=V)\n"
        "    return engine\n"
    )
    path = "src/breezy/runtime/health.py"

    tree = ast.parse(source)
    assert not is_venue_touching(path, tree), "precondition: F1 would exempt this module"
    assert find_default_fee_model_venues(path, source) != []


def test_f2_scan_covers_both_src_and_scripts() -> None:
    scanned = {path for path, _ in iter_python_sources(FEE_SCAN_ROOTS)}
    assert any(p.startswith("src/") for p in scanned)
    assert any(p.startswith("scripts/") for p in scanned)


def test_f2_ignores_an_unrelated_call_that_merely_takes_a_venue_keyword() -> None:
    """The rule keys on the CALLEE, not on the presence of a `venue=` argument."""
    source = "def f(client):\n    return client.add_instrument(venue=V)\n"

    assert find_default_fee_model_venues("src/breezy/runtime/backtest.py", source) == []


def test_the_engine_default_this_barrier_exists_to_stop_is_still_the_default() -> None:
    """Contract test on the immutable foundation.

    Read from the shipped ``engine.pyx`` because ``BacktestEngine.add_venue``
    is a compiled ``cython_function_or_method`` and ``inspect.getsource``
    raises ``TypeError`` on it.

    If a future Nautilus stops defaulting ``fee_model`` to
    ``MakerTakerFeeModel``, barrier F2's premise changes and the rationale
    above must be re-verified rather than carried forward.
    """
    import nautilus_trader

    engine_pyx = Path(nautilus_trader.__file__).parent / "backtest" / "engine.pyx"
    assert engine_pyx.is_file(), f"Nautilus source not shipped at {engine_pyx}"

    source = engine_pyx.read_text(encoding="utf-8")

    assert "fee_model = MakerTakerFeeModel()" in source, (
        "BacktestEngine.add_venue no longer defaults to MakerTakerFeeModel; "
        "re-verify barrier F2's premise against the new Nautilus version"
    )
