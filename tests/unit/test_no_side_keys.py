"""RED-first tests for `exec/no_side_keys.py` (S5 plan, Track B commit 1;
hardened by a safety-review follow-up, 2026-09-14).

E3-7 (safety 2): a structural AST scan proving the captured key
(`NO_SIDE_POSITION_SHAPE_CAPTURED_KEY`) is a write target ONLY in the CLI
module, and the first-order key (`NO_SIDE_FIRST_LIVE_ORDER_KEY`) is a write
target ONLY in `client.py`'s `_submit_order`/`_reconcile_no_side_first_
order_key` -- and NEVER anywhere under `scripts/`. Mirrors
`test_polymarket_us_readonly_guard.find_write_egress_violations`'s shape.

SAFETY-REVIEW HARDENING (2026-09-14): the original scan matched only a
DIRECT `Name`/`Constant` first argument, so `key = NO_SIDE_POSITION_SHAPE_
CAPTURED_KEY; store.set(key, ...)` evaded it silently -- no test caught
the gap because none planted that exact evasion. `find_no_side_key_write_
targets` below:

1. Resolves simple module-level and function-local ALIASES transitively
   (`Assign`/`AnnAssign` from an already-resolved `Name` or from a
   `Constant` string literal equal to a key's value) -- whole-file, not
   scope-precise, which only WIDENS the scan (a same-named local in an
   unrelated function still resolves, never narrows it).
2. Constant-FOLDS f-strings (`JoinedStr`) and `+`-concatenations
   (`BinOp(Add)`) that embed an aliased name OR a literal fragment of a
   key's value -- so a SPLIT literal (`"exec/.../no_side/" +
   "position_shape_captured"`) folds to the real value exactly like a
   single literal would.
3. FAILS CLOSED: an expression that cannot be fully folded but still
   TOUCHES a known alias name, or embeds a non-trivial literal fragment
   (>= 6 chars) of either key's value, is flagged as `key="unresolvable"`
   rather than silently passed through as unrelated -- e.g. an alias
   wrapped in an opaque call (`store.set(compute(key), ...)`). A `.set(`/
   `._store_set(` call that touches NEITHER key's alias NOR fragment at
   all is left unflagged (never vacuous, never a flood of unrelated
   `.set()` calls across the tree).
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,
    is_no_side_pending,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_ROOTS = ("src", "scripts")
_CLI_MODULE_PATH = "src/breezy/runtime/mark_no_side_position_captured_cli.py"
_CLIENT_MODULE_PATH = "src/breezy/adapters/polymarket_us/exec/client.py"
_FIRST_ORDER_ALLOWED_FUNCTIONS = frozenset({"_submit_order", "_reconcile_no_side_first_order_key"})
#: S5 Track C (adjudicated 2026-09-14, strategy-side placement): the
#: strategy is a THIRD legitimate writer of the first-order key, at arm
#: time (`_evaluate_no_side_shadow`), additive to the two client sites
#: above -- never a relaxation, every other module/function stays refused.
#: R3.4: the evaluator moved (unchanged) from `continuous_strategy.py` to
#: `continuous_no_side.py`; `continuous_strategy.py` no longer writes the key
#: and is therefore no longer allowed to.
_STRATEGY_MODULE_PATH = "src/breezy/strategy/current_rung_hold/continuous_no_side.py"
_STRATEGY_ALLOWED_FUNCTIONS = frozenset({"_evaluate_no_side_shadow"})

_KEY_VALUES: Mapping[str, str] = {
    "captured": NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,
    "first_order": NO_SIDE_FIRST_LIVE_ORDER_KEY,
}
_IMPORT_NAMES: Mapping[str, str] = {
    "NO_SIDE_POSITION_SHAPE_CAPTURED_KEY": "captured",
    "NO_SIDE_FIRST_LIVE_ORDER_KEY": "first_order",
}
_WRITE_METHOD_ATTRS = frozenset({"set", "_store_set"})
_MIN_FRAGMENT_LEN = 6


def _iter_python_sources() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            out.append((rel, path.read_text(encoding="utf-8")))
    return out


def _fold(node: ast.expr, aliases: Mapping[str, str]) -> str | None:
    """Best-effort constant fold to a literal string, or `None` if any
    part is not statically resolvable. `Constant`, alias `Name`,
    `JoinedStr` (f-strings) and `BinOp(Add)` (`+`-concatenation) all fold
    recursively, so a split literal or an f-string embedding an ALIASED
    name both resolve to their real value."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                folded = _fold(value.value, aliases)
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                folded = value.value
            else:
                folded = None
            if folded is None:
                return None
            parts.append(folded)
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _fold(node.left, aliases)
        right = _fold(node.right, aliases)
        if left is None or right is None:
            return None
        return left + right
    return None


def _build_alias_map(tree: ast.AST) -> dict[str, str]:
    """name -> resolved literal key VALUE, for every identifier that is
    (a) imported (bare or `as`-renamed) from a module ending in
    `no_side_keys`, or (b) assigned, transitively, from an already-
    resolved name or a literal fold equal to a key's value. Fixed-point
    over `Assign`/`AnnAssign` so alias-of-alias chains resolve regardless
    of source order."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.endswith("no_side_keys")
        ):
            for alias in node.names:
                if alias.name in _IMPORT_NAMES:
                    value = _KEY_VALUES[_IMPORT_NAMES[alias.name]]
                    aliases[alias.name] = value
                    aliases[alias.asname or alias.name] = value
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            target: ast.expr | None = None
            value_node: ast.expr | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value_node = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                target, value_node = node.target, node.value
            if not isinstance(target, ast.Name) or value_node is None:
                continue
            resolved = _fold(value_node, aliases)
            if (
                resolved is not None
                and resolved in _KEY_VALUES.values()
                and aliases.get(target.id) != resolved
            ):
                aliases[target.id] = resolved
                changed = True
    return aliases


def _touched_key_values(node: ast.expr, aliases: Mapping[str, str]) -> frozenset[str]:
    """Fail-closed signal: which key VALUE(s) `node`'s subtree references
    via a known alias `Name`, or embeds as a non-trivial (>=
    `_MIN_FRAGMENT_LEN`) literal fragment -- used only when `_fold` could
    not fully resolve the expression, so an opaque wrapper around a known
    alias (`store.set(compute(key), ...)`) is still caught."""
    touched: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in aliases:
            touched.add(aliases[sub.id])
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            fragment = sub.value
            if len(fragment) >= _MIN_FRAGMENT_LEN:
                touched.update(value for value in _KEY_VALUES.values() if fragment in value)
    return frozenset(touched)


@dataclass(frozen=True, slots=True)
class KeyWriteFinding:
    lineno: int
    key: str  # "captured" | "first_order"
    resolved: bool  # False => fail-closed on an unresolvable-but-touching expression
    enclosing_function: str | None


class _KeyWriteVisitor(ast.NodeVisitor):
    def __init__(self, aliases: Mapping[str, str]) -> None:
        self._aliases = aliases
        self._func_stack: list[str] = []
        self.findings: list[KeyWriteFinding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _WRITE_METHOD_ATTRS
            and node.args
        ):
            arg0 = node.args[0]
            resolved_value = _fold(arg0, self._aliases)
            enclosing = self._func_stack[-1] if self._func_stack else None
            key_for_value = {v: k for k, v in _KEY_VALUES.items()}
            if resolved_value in key_for_value:
                self.findings.append(
                    KeyWriteFinding(node.lineno, key_for_value[resolved_value], True, enclosing)
                )
            elif resolved_value is None:
                for touched_value in _touched_key_values(arg0, self._aliases):
                    self.findings.append(
                        KeyWriteFinding(
                            node.lineno, key_for_value[touched_value], False, enclosing,
                        )
                    )
        self.generic_visit(node)


def find_no_side_key_write_targets(path: str, source: str) -> tuple[KeyWriteFinding, ...]:
    tree = ast.parse(source, filename=path)
    aliases = _build_alias_map(tree)
    visitor = _KeyWriteVisitor(aliases)
    visitor.visit(tree)
    return tuple(visitor.findings)


def _is_allowed_first_order_write(path: str, finding: KeyWriteFinding) -> bool:
    if path == _CLIENT_MODULE_PATH:
        return finding.enclosing_function in _FIRST_ORDER_ALLOWED_FUNCTIONS
    if path == _STRATEGY_MODULE_PATH:
        return finding.enclosing_function in _STRATEGY_ALLOWED_FUNCTIONS
    return False


# ---------------------------------------------------------------------------
# Key value/pending-helper tests (unchanged).
# ---------------------------------------------------------------------------


def test_no_side_first_live_order_key_value() -> None:
    assert NO_SIDE_FIRST_LIVE_ORDER_KEY == "exec/polymarket_us/no_side/first_live_order"


def test_no_side_position_shape_captured_key_value() -> None:
    assert (
        NO_SIDE_POSITION_SHAPE_CAPTURED_KEY
        == "exec/polymarket_us/no_side/position_shape_captured"
    )


def test_is_no_side_pending_true_only_while_first_order_present_and_captured_absent() -> None:
    class _Store:
        def __init__(self, values: dict[str, bytes]) -> None:
            self._values = values

        def get(self, key: str) -> bytes | None:
            return self._values.get(key)

    assert is_no_side_pending(_Store({})) is False
    assert is_no_side_pending(_Store({NO_SIDE_FIRST_LIVE_ORDER_KEY: b"{}"})) is True
    assert (
        is_no_side_pending(
            _Store(
                {
                    NO_SIDE_FIRST_LIVE_ORDER_KEY: b"{}",
                    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY: b"{}",
                }
            )
        )
        is False
    )


# ---------------------------------------------------------------------------
# The captured key: a write target ONLY in the CLI module.
# ---------------------------------------------------------------------------


def test_the_captured_key_is_a_write_target_only_in_the_cli_module() -> None:
    offenders = {
        path: findings
        for path, src in _iter_python_sources()
        if (
            findings := [
                f for f in find_no_side_key_write_targets(path, src) if f.key == "captured"
            ]
        )
        and path != _CLI_MODULE_PATH
    }
    assert offenders == {}


def test_the_cli_module_itself_is_expected_to_be_the_one_write_target() -> None:
    assert _CLI_MODULE_PATH == "src/breezy/runtime/mark_no_side_position_captured_cli.py"


def test_the_scan_detects_a_planted_direct_write_outside_the_cli() -> None:
    """Non-vacuity: the original, un-aliased form still fires."""
    planted = (
        "from breezy.adapters.polymarket_us.exec.no_side_keys import (\n"
        "    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,\n"
        ")\n"
        "\n"
        "def evil(store):\n"
        "    store.set(NO_SIDE_POSITION_SHAPE_CAPTURED_KEY, b'1')\n"
    )
    findings = find_no_side_key_write_targets("scripts/evil.py", planted)
    assert [(f.lineno, f.key, f.resolved) for f in findings] == [(6, "captured", True)]


def test_the_scan_detects_an_aliased_write_outside_the_cli() -> None:
    """RED on the reported evasion: `key = <constant>; store.set(key, ...)`."""
    planted = (
        "from breezy.adapters.polymarket_us.exec.no_side_keys import (\n"
        "    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,\n"
        ")\n"
        "\n"
        "def evil(store):\n"
        "    key = NO_SIDE_POSITION_SHAPE_CAPTURED_KEY\n"
        "    store.set(key, b'1')\n"
    )
    findings = find_no_side_key_write_targets("scripts/evil.py", planted)
    assert [(f.lineno, f.key, f.resolved) for f in findings] == [(7, "captured", True)]


def test_the_scan_detects_a_chained_alias_write_outside_the_cli() -> None:
    """Transitive alias-of-alias: `a = KEY; b = a; store.set(b, ...)`."""
    planted = (
        "from breezy.adapters.polymarket_us.exec.no_side_keys import (\n"
        "    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY as _RAW,\n"
        ")\n"
        "\n"
        "def evil(store):\n"
        "    a = _RAW\n"
        "    b = a\n"
        "    store.set(b, b'1')\n"
    )
    findings = find_no_side_key_write_targets("scripts/evil.py", planted)
    assert [(f.lineno, f.key, f.resolved) for f in findings] == [(8, "captured", True)]


def test_the_scan_detects_an_fstring_alias_write_outside_the_cli() -> None:
    """RED evasion form 2: an f-string embedding the ALIASED name."""
    planted = (
        "from breezy.adapters.polymarket_us.exec.no_side_keys import (\n"
        "    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,\n"
        ")\n"
        "\n"
        "def evil(store):\n"
        "    key = NO_SIDE_POSITION_SHAPE_CAPTURED_KEY\n"
        "    store.set(f'{key}', b'1')\n"
    )
    findings = find_no_side_key_write_targets("scripts/evil.py", planted)
    assert [(f.lineno, f.key, f.resolved) for f in findings] == [(7, "captured", True)]


def test_the_scan_detects_a_split_literal_concatenation_write_outside_the_cli() -> None:
    """RED evasion form 3: the literal VALUE split across a `+`-concat,
    with no import and no alias at all -- pure literal folding."""
    planted = (
        "def evil(store):\n"
        "    store.set('exec/polymarket_us/no_side/' + 'position_shape_captured', b'1')\n"
    )
    findings = find_no_side_key_write_targets("scripts/evil.py", planted)
    assert [(f.lineno, f.key, f.resolved) for f in findings] == [(2, "captured", True)]


def test_the_scan_fails_closed_on_an_unresolvable_wrapper_around_an_alias() -> None:
    """RED evasion form 4: the alias is wrapped in an opaque call this
    scanner cannot evaluate (`compute(key)`) -- `_fold` returns `None`,
    but `_touched_key_values` still finds the alias `Name` nested inside,
    so the call is flagged `resolved=False` rather than silently passed."""
    planted = (
        "from breezy.adapters.polymarket_us.exec.no_side_keys import (\n"
        "    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,\n"
        ")\n"
        "\n"
        "def evil(store):\n"
        "    key = NO_SIDE_POSITION_SHAPE_CAPTURED_KEY\n"
        "    store.set(compute(key), b'1')\n"
    )
    findings = find_no_side_key_write_targets("scripts/evil.py", planted)
    assert [(f.lineno, f.key, f.resolved) for f in findings] == [(7, "captured", False)]


def test_an_unrelated_set_call_is_never_flagged() -> None:
    """Non-vacuity in the other direction: a `.set()` call that touches
    NEITHER key's alias nor a literal fragment of either value is left
    alone -- the scan is bounded, not a flood of unrelated writes."""
    planted = (
        "FILL_KEY_PREFIX = 'exec/polymarket_us/fill/'\n"
        "\n"
        "def fine(store, venue_order_id):\n"
        "    store.set(f'{FILL_KEY_PREFIX}{venue_order_id}', b'1')\n"
    )
    findings = find_no_side_key_write_targets("scripts/fine.py", planted)
    assert findings == ()


# ---------------------------------------------------------------------------
# The first-order key: a write target ONLY in `client.py`'s two named
# functions, and NEVER anywhere under `scripts/`.
# ---------------------------------------------------------------------------


def test_the_first_order_key_is_written_only_by_the_allowed_client_functions() -> None:
    offenders = {
        path: [f for f in findings if not _is_allowed_first_order_write(path, f)]
        for path, src in _iter_python_sources()
        if (
            findings := [
                f for f in find_no_side_key_write_targets(path, src) if f.key == "first_order"
            ]
        )
    }
    offenders = {path: f for path, f in offenders.items() if f}
    assert offenders == {}


def test_the_first_order_key_is_never_written_anywhere_under_scripts() -> None:
    for path, src in _iter_python_sources():
        if not path.startswith("scripts/"):
            continue
        findings = [f for f in find_no_side_key_write_targets(path, src) if f.key == "first_order"]
        assert findings == [], f"{path}: {findings}"


def test_is_allowed_first_order_write_accepts_the_two_named_client_functions() -> None:
    for func_name in ("_submit_order", "_reconcile_no_side_first_order_key"):
        finding = KeyWriteFinding(1, "first_order", True, func_name)
        assert _is_allowed_first_order_write(_CLIENT_MODULE_PATH, finding) is True


def test_is_allowed_first_order_write_refuses_a_third_client_function() -> None:
    finding = KeyWriteFinding(1, "first_order", True, "_seed_spend_from_durable_fills")
    assert _is_allowed_first_order_write(_CLIENT_MODULE_PATH, finding) is False


def test_is_allowed_first_order_write_refuses_the_right_function_name_in_the_wrong_module() -> None:
    finding = KeyWriteFinding(1, "first_order", True, "_submit_order")
    assert _is_allowed_first_order_write("scripts/evil.py", finding) is False


def test_is_allowed_first_order_write_accepts_the_strategy_arm_time_write() -> None:
    """S5 Track C: the strategy-side write, additive to the two client
    sites -- never a widening of the client's own allowlist."""
    finding = KeyWriteFinding(1, "first_order", True, "_evaluate_no_side_shadow")
    assert _is_allowed_first_order_write(_STRATEGY_MODULE_PATH, finding) is True


def test_is_allowed_first_order_write_refuses_the_strategy_function_name_in_the_client_module() -> (
    None
):
    finding = KeyWriteFinding(1, "first_order", True, "_evaluate_no_side_shadow")
    assert _is_allowed_first_order_write(_CLIENT_MODULE_PATH, finding) is False


def test_is_allowed_first_order_write_refuses_a_different_function_in_the_strategy_module() -> None:
    finding = KeyWriteFinding(1, "first_order", True, "_run_never_arm_walk")
    assert _is_allowed_first_order_write(_STRATEGY_MODULE_PATH, finding) is False


def test_the_scan_detects_a_planted_first_order_alias_write_in_a_disallowed_function() -> None:
    planted = (
        "from breezy.adapters.polymarket_us.exec.no_side_keys import (\n"
        "    NO_SIDE_FIRST_LIVE_ORDER_KEY,\n"
        ")\n"
        "\n"
        "class Client:\n"
        "    def _some_other_method(self):\n"
        "        key = NO_SIDE_FIRST_LIVE_ORDER_KEY\n"
        "        self._store_set(key, b'1')\n"
    )
    findings = find_no_side_key_write_targets(_CLIENT_MODULE_PATH, planted)
    matches = [f for f in findings if f.key == "first_order"]
    assert len(matches) == 1
    assert matches[0].enclosing_function == "_some_other_method"
    assert _is_allowed_first_order_write(_CLIENT_MODULE_PATH, matches[0]) is False
