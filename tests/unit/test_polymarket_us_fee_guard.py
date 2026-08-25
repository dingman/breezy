"""Barrier F1: the venue fee schedule fails closed in SUBSTANCE, not in prose.

Why this file exists (the defect it pins). ``parsing.parse_binary_option``
constructs ``BinaryOption`` without passing ``maker_fee``/``taker_fee``.
Nautilus defaults them with ``maker_fee or Decimal(0)``
(``model/instruments/binary_option.pyx:148-149``), so every instrument this
adapter loads carries a *real, valid, typed* ``Decimal(0)`` in the two fields
that generic Nautilus machinery actually reads --
``MakerTakerFeeModel.get_commission`` multiplies notional by
``instrument.maker_fee``/``instrument.taker_fee`` and nothing else
(``backtest/models/fee.pyx:96-99``). The ``fee_schedule_status="UNKNOWN"``
marker lived only in the loosely-typed ``info`` dict, which nothing was forced
to consult. The module therefore shipped exactly the zero-fee illusion its
docstring claimed to prevent.

The venue fee is not negligible: ``fee = theta * C * p * (1 - p)`` with a
taker ``theta`` of 0.06, i.e. $1.50 per 100 contracts at p=0.50
(``polymarket-us-integration`` skill, "Fee Formula"). A silent zero inflates
apparent edge on every quote and bleeds real money once execution lands.

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
from nautilus_trader.model.objects import Price, Quantity

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


# ---------------------------------------------------------------------------
# The hazard itself, pinned rather than certified as acceptable
# ---------------------------------------------------------------------------


def test_the_typed_fee_fields_hold_a_real_zero_that_a_generic_fee_model_would_trust(
    open_instrument: BinaryOption,
) -> None:
    """Reproduce the CRITICAL finding: the zero is real, typed, and usable.

    This test does NOT certify ``Decimal(0)`` as acceptable -- it pins the
    hazard, so the guard below has something to guard. It replays the exact
    arithmetic of ``MakerTakerFeeModel.get_commission``
    (``backtest/models/fee.pyx:96-99``) and shows the commission it would
    charge is $0.00 where the venue's own schedule charges $1.50.
    """
    fill_qty = Quantity.from_int(100)
    fill_px = Price.from_str("0.500")
    notional = open_instrument.notional_value(
        quantity=fill_qty,
        price=fill_px,
        use_quote_for_inverse=False,
    )

    # The two lines a generic Nautilus fee model executes, verbatim.
    maker_commission = notional.as_decimal() * open_instrument.maker_fee
    taker_commission = notional.as_decimal() * open_instrument.taker_fee
    assert maker_commission == Decimal(0)
    assert taker_commission == Decimal(0)

    # What the venue would actually charge: theta * C * p * (1 - p).
    theta = Decimal(str(open_instrument.info["fee_coefficient"]))
    price = fill_px.as_decimal()
    venue_taker_fee = theta * fill_qty.as_decimal() * price * (Decimal(1) - price)
    assert theta == Decimal("0.06")
    assert venue_taker_fee == Decimal("1.500")
    assert taker_commission != venue_taker_fee


def test_the_info_marker_alone_binds_nobody_which_is_why_the_guard_exists(
    open_instrument: BinaryOption,
) -> None:
    """The marker is present and correct -- and is not, by itself, enforcement."""
    assert open_instrument.info[FEE_SCHEDULE_STATUS_KEY] == FEE_SCHEDULE_STATUS_UNKNOWN
    assert FEE_SCHEDULE_STATUS_UNKNOWN != FEE_SCHEDULE_STATUS_KNOWN


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_the_guard_refuses_an_instrument_whose_fee_schedule_is_unknown(
    open_instrument: BinaryOption,
) -> None:
    with pytest.raises(FeeScheduleUnknownError, match="fee schedule"):
        assert_fee_schedule_known(open_instrument)


def test_the_guard_failure_is_catchable_as_the_adapter_base_error(
    open_instrument: BinaryOption,
) -> None:
    with pytest.raises(PolymarketUSError):
        assert_fee_schedule_known(open_instrument)


def test_the_guard_names_the_two_fields_that_hold_the_misleading_zero(
    open_instrument: BinaryOption,
) -> None:
    """An operator reading the traceback must learn WHY the zero is not a fee."""
    with pytest.raises(FeeScheduleUnknownError) as excinfo:
        assert_fee_schedule_known(open_instrument)
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
