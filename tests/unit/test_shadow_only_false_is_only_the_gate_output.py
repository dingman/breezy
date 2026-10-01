"""FQ-S5 item 5 (plan `FQ_GO_LIVE_PLAN_2026-10-01.md` §3 S5, peer review
item 5, security): an AST scan of every `src/**/*.py` for the shapes that
give `shadow_only` a value -- a keyword argument, an annotated-assignment
default, or a plain assignment. Exactly ONE non-`True` expression is
permitted anywhere in `src/`: `shadow_only=not live_orders.enabled`, in
`app/trade.py`'s `forecast_quantile_ladder` branch. Everything else,
including `ForecastQuantileLadderConfig.shadow_only`'s own default
(`strategy/forecast_quantile_ladder/config.py`) changing away from `True`,
fires.

Mirrors `test_operator_control_assignment_scan.py`'s AST-walk shape and
reuses its `iter_python_sources` file-enumeration helper -- one
implementation of "walk every `src/` module's AST", never two.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tests.unit.test_polymarket_us_readonly_guard import iter_python_sources

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Scan root -- `shadow_only` is a strategy-config field; tests and scripts
#: are deliberately out of scope (a test driving `shadow_only=False` through
#: a config constructor directly, e.g. `test_sl13_wiring.py`, is exercising
#: the mechanism, not shipping it).
SCAN_ROOTS: Final[tuple[str, ...]] = ("src",)

#: The ONE path allowed to carry the ONE non-`True` expression below.
_PERMITTED_PATH: Final[str] = "src/breezy/app/trade.py"

#: The ONE expression text permitted at `_PERMITTED_PATH` -- the gate's own
#: output, never a manifest field, an environment variable, or a literal
#: `False`. Textually exact: `ast.unparse` is deterministic for this shape.
_PERMITTED_EXPRESSION: Final[str] = "not live_orders.enabled"


@dataclass(frozen=True, slots=True)
class ShadowOnlyViolation:
    """One place `shadow_only` is given a value outside the permitted shape."""

    path: str
    lineno: int
    detail: str


def _shadow_only_assignments(node: ast.AST) -> list[ast.expr]:
    """Every value expression `node` gives something literally named
    `shadow_only` -- a call keyword, a plain/annotated assignment target,
    or a dict-literal key. The dict-key shape matters: `composition.py`
    forwards the value through `config_kwargs["shadow_only"] = shadow_only`
    / `{"shadow_only": shadow_only, ...}` and then calls
    `ForecastQuantileLadderConfig(**config_kwargs)`, which carries no
    literal `shadow_only=` keyword at the call site itself -- only the
    dict-literal/subscript assignment does.
    """
    values: list[ast.expr] = []
    if isinstance(node, ast.keyword) and node.arg == "shadow_only":
        values.append(node.value)
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "shadow_only" or (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "shadow_only"
            ):
                values.append(node.value)
    elif isinstance(node, ast.AnnAssign):
        if (
            isinstance(node.target, ast.Name)
            and node.target.id == "shadow_only"
            and node.value is not None
        ):
            values.append(node.value)
    elif isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "shadow_only":
                values.append(value)
    return values


def _is_permitted(path: str, value: ast.expr) -> bool:
    """`True` (the literal) is always fine. A bare `Name("shadow_only")` is
    pure pass-through forwarding -- it never introduces a value, only
    relays whatever its OWN caller decided -- and is permitted anywhere,
    not just `_PERMITTED_PATH` (closing the forwarding path, e.g.
    `composition.py`'s `config_kwargs`, requires tracing that caller's own
    parameter default separately, which stays pinned to `True`). The one
    non-pass-through, non-literal expression permitted at all is
    `_PERMITTED_EXPRESSION`, and ONLY at `_PERMITTED_PATH`.
    """
    if isinstance(value, ast.Constant) and value.value is True:
        return True
    if isinstance(value, ast.Name) and value.id == "shadow_only":
        return True
    return path == _PERMITTED_PATH and ast.unparse(value) == _PERMITTED_EXPRESSION


def find_shadow_only_violations(path: str, source: str) -> list[ShadowOnlyViolation]:
    """Every `shadow_only=`/`shadow_only:`/`shadow_only =`/dict-key value in
    `source` that `_is_permitted` refuses."""
    tree = ast.parse(source, filename=path)
    violations: list[ShadowOnlyViolation] = []
    for node in ast.walk(tree):
        for value in _shadow_only_assignments(node):
            if _is_permitted(path, value):
                continue
            violations.append(
                ShadowOnlyViolation(
                    path=path, lineno=getattr(value, "lineno", 0), detail=ast.unparse(value)
                )
            )
    return violations


def test_shadow_only_is_only_ever_true_or_the_gate_output_in_src() -> None:
    violations: list[ShadowOnlyViolation] = []
    for path, source in iter_python_sources(SCAN_ROOTS):
        violations.extend(find_shadow_only_violations(path, source))

    assert violations == [], (
        "shadow_only given a non-True, non-gate value: "
        f"{[(v.path, v.lineno, v.detail) for v in violations]}"
    )


def test_the_permitted_expression_actually_appears_in_trade_py() -> None:
    """A regression guard on the exemption itself: if `app/trade.py` ever
    stops computing `shadow_only` from the gate output (e.g. reverts to a
    bare `shadow_only=True`), this fails loudly rather than letting the
    scan above pass vacuously with zero violations for the wrong reason."""
    source = (_REPO_ROOT / _PERMITTED_PATH).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=_PERMITTED_PATH)
    present = any(
        isinstance(node, ast.keyword)
        and node.arg == "shadow_only"
        and ast.unparse(node.value) == _PERMITTED_EXPRESSION
        for node in ast.walk(tree)
    )
    assert present, "app/trade.py no longer computes shadow_only from the live-orders gate"
    assert find_shadow_only_violations(_PERMITTED_PATH, source) == []


def test_a_synthetic_shadow_only_false_is_flagged() -> None:
    """Positive control (plan-required): the scanner must actually fire."""
    violations = find_shadow_only_violations(
        "src/breezy/synthetic_planted.py", "shadow_only = False\n"
    )
    assert len(violations) == 1
    assert violations[0].detail == "False"


def test_a_synthetic_shadow_only_false_keyword_is_flagged() -> None:
    violations = find_shadow_only_violations(
        "src/breezy/synthetic_planted.py",
        "build(shadow_only=False)\n",
    )
    assert len(violations) == 1


def test_the_permitted_expression_is_refused_outside_the_permitted_path() -> None:
    """The exemption is PATH-scoped, not expression-scoped: the same text
    appearing anywhere else in `src/` still fires."""
    violations = find_shadow_only_violations(
        "src/breezy/strategy/elsewhere.py",
        "shadow_only=not live_orders.enabled\n",
    )
    assert len(violations) == 1


def test_a_synthetic_shadow_only_false_dict_key_is_flagged() -> None:
    """The `composition.py` forwarding shape (`{"shadow_only": ...}`) is
    scanned too -- a hardcoded `False` there must still fire."""
    violations = find_shadow_only_violations(
        "src/breezy/strategy/elsewhere.py",
        'd = {"shadow_only": False}\n',
    )
    assert len(violations) == 1


def test_a_passthrough_dict_key_is_not_a_violation() -> None:
    """`composition.py`'s real shape: a `shadow_only` parameter forwarded,
    unmodified, into a dict literal under the same key name -- never a
    hardcoded value, so never flagged."""
    violations = find_shadow_only_violations(
        "src/breezy/strategy/elsewhere.py",
        "def f(shadow_only=True):\n    d = {'shadow_only': shadow_only}\n    return d\n",
    )
    assert violations == []


def test_a_changed_config_default_is_flagged() -> None:
    """The `ForecastQuantileLadderConfig.shadow_only` default changing away
    from `True` is caught by the SAME generic rule, not a special case."""
    source = "class C:\n    shadow_only: bool = False\n"
    violations = find_shadow_only_violations(
        "src/breezy/strategy/forecast_quantile_ladder/config.py", source
    )
    assert len(violations) == 1
