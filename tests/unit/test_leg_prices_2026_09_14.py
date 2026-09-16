"""NO-side S5 Rev 5/5a/5b: `leg_prices.py` -- wire price translation, the
venue's side/intent echo table, and the E5-6 structural pin proving
complement arithmetic (`1 - x`) lives ONLY here, never back under `exec/`
where X3's AST control bans it.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.leg_prices import (
    assert_echo_matches_leg,
    assert_exit_echo_matches_leg,
    exit_wire_price_for_leg,
    instrument_price_for_leg,
    wire_price_for_leg,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_ROOT = REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us"
EXEC_PREFIX = "src/breezy/adapters/polymarket_us/exec/"
LEG_PRICES_PATH = "src/breezy/adapters/polymarket_us/leg_prices.py"

# ---------------------------------------------------------------------------
# Round-trip exactness and bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cents", range(1, 100))
def test_the_no_leg_round_trips_exactly_at_every_cent_tick(cents: int) -> None:
    price = Decimal(cents) / Decimal(100)
    wire = wire_price_for_leg("no", price)
    assert instrument_price_for_leg("no", wire) == price


@pytest.mark.parametrize("cents", range(1, 100))
def test_the_yes_leg_is_identity_at_every_cent_tick(cents: int) -> None:
    price = Decimal(cents) / Decimal(100)
    assert wire_price_for_leg("yes", price) == price
    assert instrument_price_for_leg("yes", price) == price


def test_a_no_buy_at_97_cents_sends_3_cents_on_the_wire() -> None:
    assert wire_price_for_leg("no", Decimal("0.97")) == Decimal("0.03")


def test_a_no_buy_at_5_cents_sends_95_cents_on_the_wire() -> None:
    assert wire_price_for_leg("no", Decimal("0.05")) == Decimal("0.95")


@pytest.mark.parametrize("bad", [Decimal("-0.01"), Decimal("1.01"), Decimal(2)])
def test_out_of_bounds_prices_refuse_on_both_functions(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        wire_price_for_leg("no", bad)
    with pytest.raises(ValueError):
        instrument_price_for_leg("no", bad)


def test_a_non_finite_price_refuses() -> None:
    with pytest.raises(ValueError):
        wire_price_for_leg("no", Decimal("NaN"))
    with pytest.raises(ValueError):
        instrument_price_for_leg("no", Decimal("Infinity"))


def test_a_non_decimal_price_refuses() -> None:
    with pytest.raises(ValueError):
        wire_price_for_leg("no", 0.5)  # type: ignore[arg-type]


def test_an_unknown_leg_refuses_on_both_functions() -> None:
    with pytest.raises(ValueError):
        wire_price_for_leg("maybe", Decimal("0.5"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        instrument_price_for_leg("maybe", Decimal("0.5"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Venue side/intent echo table
# ---------------------------------------------------------------------------


def test_the_yes_leg_echo_matches() -> None:
    assert_echo_matches_leg("yes", "ORDER_SIDE_BUY", "ORDER_INTENT_BUY_LONG")


def test_the_no_leg_echo_matches() -> None:
    assert_echo_matches_leg("no", "ORDER_SIDE_SELL", "ORDER_INTENT_BUY_SHORT")


def test_a_no_leg_echoed_as_a_yes_side_is_refused() -> None:
    with pytest.raises(ValueError, match="refusing"):
        assert_echo_matches_leg("no", "ORDER_SIDE_BUY", "ORDER_INTENT_BUY_LONG")


def test_a_yes_leg_echoed_as_a_no_side_is_refused() -> None:
    with pytest.raises(ValueError, match="refusing"):
        assert_echo_matches_leg("yes", "ORDER_SIDE_SELL", "ORDER_INTENT_BUY_SHORT")


def test_a_mismatched_intent_alone_is_refused() -> None:
    with pytest.raises(ValueError, match="refusing"):
        assert_echo_matches_leg("no", "ORDER_SIDE_SELL", "ORDER_INTENT_BUY_LONG")


def test_an_unknown_leg_refuses_the_echo_check() -> None:
    with pytest.raises(ValueError):
        assert_echo_matches_leg("maybe", "ORDER_SIDE_BUY", "ORDER_INTENT_BUY_LONG")


# ---------------------------------------------------------------------------
# INC-E1/E2 (POSITION_EXIT_EXECUTION_2026-09-16.md, Appendix A rows 1-2):
# the CLOSING-order (exit) echo table, disjoint from the BUY table above.
# ---------------------------------------------------------------------------


def test_a_yes_close_echo_matches() -> None:
    assert_exit_echo_matches_leg("yes", "ORDER_SIDE_SELL", "ORDER_INTENT_SELL_LONG")


def test_a_no_close_echo_matches() -> None:
    """PINNED-BY-CAPTURE 2026-09-16T03:19:32Z
    (``CLOSE_PREVIEW_no_20260916T031932Z.json``): a NO close is the exact
    mirror of a NO buy -- side ``ORDER_SIDE_BUY``, not ``SELL``, even though
    the request carried ``action: ORDER_ACTION_SELL``."""
    assert_exit_echo_matches_leg("no", "ORDER_SIDE_BUY", "ORDER_INTENT_SELL_SHORT")


def test_a_no_close_echoed_as_a_yes_close_intent_is_refused() -> None:
    """The NO-close SIDE (``ORDER_SIDE_BUY``) alone is not enough to pass --
    paired with YES's close intent (``ORDER_INTENT_SELL_LONG``) it must
    still refuse."""
    with pytest.raises(ValueError, match="refusing"):
        assert_exit_echo_matches_leg("no", "ORDER_SIDE_BUY", "ORDER_INTENT_SELL_LONG")


def test_a_yes_close_echoed_as_a_no_close_intent_is_refused() -> None:
    with pytest.raises(ValueError, match="refusing"):
        assert_exit_echo_matches_leg("yes", "ORDER_SIDE_SELL", "ORDER_INTENT_SELL_SHORT")


def test_an_unknown_leg_refuses_the_exit_echo_check() -> None:
    with pytest.raises(ValueError):
        assert_exit_echo_matches_leg("maybe", "ORDER_SIDE_SELL", "ORDER_INTENT_SELL_LONG")


def test_a_buy_echo_presented_to_the_exit_check_is_refused() -> None:
    """Refused in BOTH directions (E5-2, carried over): the entry table's
    exact pair is not a valid exit echo for either leg."""
    with pytest.raises(ValueError, match="refusing"):
        assert_exit_echo_matches_leg("yes", "ORDER_SIDE_BUY", "ORDER_INTENT_BUY_LONG")
    with pytest.raises(ValueError, match="refusing"):
        assert_exit_echo_matches_leg("no", "ORDER_SIDE_SELL", "ORDER_INTENT_BUY_SHORT")


def test_an_exit_echo_presented_to_the_buy_check_is_refused() -> None:
    """The other direction: the exit table's exact pair is not a valid BUY
    echo for either leg."""
    with pytest.raises(ValueError, match="refusing"):
        assert_echo_matches_leg("yes", "ORDER_SIDE_SELL", "ORDER_INTENT_SELL_LONG")
    with pytest.raises(ValueError, match="refusing"):
        assert_echo_matches_leg("no", "ORDER_SIDE_BUY", "ORDER_INTENT_SELL_SHORT")


def test_the_no_close_echo_and_the_yes_buy_echo_share_a_side_but_are_not_interchangeable() -> None:
    """PINNED-BY-CAPTURE: the corrected NO-close pair (``ORDER_SIDE_BUY``,
    ``ORDER_INTENT_SELL_SHORT``) and the YES-buy pair (``ORDER_SIDE_BUY``,
    ``ORDER_INTENT_BUY_LONG``) now share a SIDE and differ only by intent --
    both checks must key on the full (side, intent) PAIR, never side alone,
    or one leg's close would silently pass as the other leg's open."""
    with pytest.raises(ValueError, match="refusing"):
        assert_echo_matches_leg("yes", "ORDER_SIDE_BUY", "ORDER_INTENT_SELL_SHORT")
    with pytest.raises(ValueError, match="refusing"):
        assert_exit_echo_matches_leg("no", "ORDER_SIDE_BUY", "ORDER_INTENT_BUY_LONG")


def test_exit_wire_price_for_leg_is_identity_on_yes_and_complement_on_no() -> None:
    """`exit_wire_price_for_leg` reuses `wire_price_for_leg`'s exact
    arithmetic -- a NO close at X is sent as `1 - X`, the IDENTICAL
    complement a NO BUY uses (Appendix A row 3): no new formula for a close."""
    assert exit_wire_price_for_leg("yes", Decimal("0.63")) == Decimal("0.63")
    assert exit_wire_price_for_leg("no", Decimal("0.63")) == Decimal("0.37")
    assert exit_wire_price_for_leg("no", Decimal("0.63")) == wire_price_for_leg(
        "no", Decimal("0.63"),
    )


# ---------------------------------------------------------------------------
# E5-6 structural pin
# ---------------------------------------------------------------------------

#: WIDENED (not relaxed) to include `assert_echo_matches_leg`: E5-2's venue
#: side/intent cross-check lives in the SAME two mapper functions
#: (`parse_fill_report`/`parse_order_status_report`) that translate the
#: price -- the original E5-6 wording named only the price functions, but
#: the echo check is the other half of the same commit's safety net and
#: belongs to the same "outside exec/, imported narrowly" shape.
_PERMITTED_IMPORTED_NAMES = frozenset(
    {
        "wire_price_for_leg",
        "instrument_price_for_leg",
        "assert_echo_matches_leg",
        # `Leg`: the type alias, imported for signatures only -- carries no
        # arithmetic and is never called.
        "Leg",
        # WIDENED (not relaxed), INC-E2b (`POSITION_EXIT_EXECUTION_2026-09-16.md`
        # §3): `exec/submit_chain.py`'s `build_exit_order_body` imports the
        # exit-call-site alias of `wire_price_for_leg` (leg_prices module
        # docstring) to translate the closing order's wire price -- same
        # complement, named for its call site.
        "exit_wire_price_for_leg",
        # WIDENED (not relaxed), INC-E2 response-side leg check
        # (`POSITION_EXIT_EXECUTION_2026-09-16.md` §3): `exec/reports.py`'s
        # `_order_side_for_leg` imports the closing-order sibling of
        # `assert_echo_matches_leg` (same module, same "outside exec/,
        # imported narrowly" shape) so a closing response is cross-checked
        # against the disjoint exit echo table instead of the entry-only one.
        "assert_exit_echo_matches_leg",
    }
)
#: WIDENED (not relaxed), commit `feat(exec): book NO-leg fills as BUY at
#: the instrument price` -- `_cumulative_qty_and_cost`/`_filled_cost_from_
#: execution` are the CREATE path's OWN I1a total computation, reading
#: `avgPx`/`lastPx` directly off the raw execution/order body, entirely
#: independent of `parse_fill_report`'s mapped `FillReport.last_px`. Both
#: read a WIRE (YES-denominated) value and must translate it via the same
#: `leg`, or the NO leg's booked notional silently keeps the wire price.
_PERMITTED_CALLERS = frozenset(
    {
        "build_order_body",
        # WIDENED (not relaxed), INC-E2b: the closing-order counterpart of
        # `build_order_body`, calling `exit_wire_price_for_leg` for the exact
        # same reason -- one wire-price translation, one call site.
        "build_exit_order_body",
        "parse_fill_report",
        "parse_order_status_report",
        "_cumulative_qty_and_cost",
        "_filled_cost_from_execution",
        # Thin leg-aware wrappers around `_price_field`/`_price_decimal_field`
        # and the side/intent cross-check, called ONLY by the three mapper
        # functions above -- named separately here so the AST scan sees the
        # textual call site, not a second, drifting definition.
        "_leg_price_field",
        "_leg_price_decimal_field",
        "_order_side_for_leg",
    }
)

#: Pre-existing, unrelated complement arithmetic: `PolymarketUSFeeModel`'s
#: `theta * C * p * (1 - p)` fee-symmetry formula (`fees.py:238`) predates
#: this plan, is already reviewed, and has nothing to do with YES/NO leg
#: price translation -- it is `1 - p` on a probability inside a fee
#: calculation, never a wire-price inversion. Declared here (additive,
#: named, never a silent widening of the scan) rather than excluded from
#: `ADAPTER_ROOT`'s walk entirely, so a SECOND new module adding this
#: pattern still trips the pin.
_PRE_EXISTING_COMPLEMENT_MODULES = frozenset({"src/breezy/adapters/polymarket_us/fees.py"})


def _iter_py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _is_one(node: ast.expr) -> bool:
    """Same shape as the firewall guard's `_is_one` (unwidened form): a
    literal `1`/`1.0`, a one-arg `Decimal(...)` constructor, or a
    module-level-style `_ONE`/`ONE` name -- this module's own constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return bool(node.value == 1)
    if isinstance(node, ast.Name) and node.id in {"_ONE", "ONE"}:
        return True
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
    ):
        value = node.args[0].value
        if isinstance(value, str):
            return value.strip() in {"1", "1.0"}
        if isinstance(value, int | float):
            return bool(value == 1)
    return False


def _has_complement_arithmetic(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub) and _is_one(node.left)
        for node in ast.walk(tree)
    )


def _imported_names_from_leg_prices(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.endswith("leg_prices")
        ):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _function_ranges(tree: ast.Module) -> list[tuple[str, int, int]]:
    ranges: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            ranges.append((node.name, node.lineno, node.end_lineno or node.lineno))
    return ranges


def _innermost_function(ranges: list[tuple[str, int, int]], lineno: int) -> str | None:
    candidates = [r for r in ranges if r[1] <= lineno <= r[2]]
    if not candidates:
        return None
    return min(candidates, key=lambda r: r[2] - r[1])[0]


def test_exec_imports_complement_arithmetic_only_from_leg_prices() -> None:
    """(i) `exec/` imports only the two translation functions from
    `leg_prices`; (ii) those functions are called ONLY inside
    `build_order_body`/`parse_fill_report`/`parse_order_status_report`;
    (iii) `leg_prices.py` is the only module under `adapters/polymarket_us/`
    (outside `exec/`) carrying complement arithmetic on a price."""
    complement_modules: list[str] = []

    for path in _iter_py_files(ADAPTER_ROOT):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        rel = path.relative_to(REPO_ROOT).as_posix()
        under_exec = rel.startswith(EXEC_PREFIX)

        if under_exec:
            imported = _imported_names_from_leg_prices(tree)
            extra = imported - _PERMITTED_IMPORTED_NAMES
            assert not extra, (
                f"{rel} imports {extra} from leg_prices; only "
                f"{_PERMITTED_IMPORTED_NAMES} are permitted under exec/"
            )
            ranges = _function_ranges(tree)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in _PERMITTED_IMPORTED_NAMES
                ):
                    enclosing = _innermost_function(ranges, node.lineno)
                    assert enclosing in _PERMITTED_CALLERS, (
                        f"{rel}:{node.lineno}: {node.func.id}() called inside "
                        f"{enclosing!r}, not one of {sorted(_PERMITTED_CALLERS)}"
                    )

        if (
            rel != LEG_PRICES_PATH
            and rel not in _PRE_EXISTING_COMPLEMENT_MODULES
            and not under_exec
            and _has_complement_arithmetic(tree)
        ):
            complement_modules.append(rel)

    assert complement_modules == [], (
        "complement arithmetic found outside leg_prices.py: " + ", ".join(complement_modules)
    )
