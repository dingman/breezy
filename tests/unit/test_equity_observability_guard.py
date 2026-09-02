"""Structural guards for T-4 -- the invariants the type annotation cannot hold.

`PortfolioSnapshot.equity` is `float | None`, and strict mypy DOES catch an
unguarded arithmetic read of it in a new method. It does NOT catch the two
things that actually matter here:

* ``portfolio.equity or 0.0`` type-checks clean and silently restores the
  exact fabrication this increment removes -- a fresh `10_000.0` by another
  name, only quieter.
* ``if portfolio.equity > 0 and order_notional > ...`` -- today's fail-open,
  where the one equity value that should stop a buy (zero) is the value that
  disables the cap.

Neither is a type error. So the invariant is pinned here, in source, and the
annotation is treated as the partial control it is.

Precedent for the shape: `test_backtest_harness_prose_guard.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from breezy.strategy.calibration_mean_reversion import config as calibration_config
from breezy.strategy.calibration_mean_reversion import strategy as calibration_strategy
from breezy.strategy.cli_settlement_print_lock import config as print_lock_config
from breezy.strategy.cli_settlement_print_lock import strategy as print_lock_strategy
from breezy.strategy.forecast_mispricing import config as mispricing_config
from breezy.strategy.forecast_mispricing import strategy as mispricing_strategy
from breezy.strategy.forecast_revision import config as revision_config
from breezy.strategy.forecast_revision import strategy as revision_strategy
from breezy.strategy.running_extreme_lock import config as extreme_config
from breezy.strategy.running_extreme_lock import strategy as extreme_strategy
from breezy.strategy.weather_common import risk as risk_module

CONFIG_MODULES: Final[tuple[object, ...]] = (
    mispricing_config,
    calibration_config,
    revision_config,
    extreme_config,
    print_lock_config,
)

STRATEGY_MODULES: Final[tuple[object, ...]] = (
    mispricing_strategy,
    calibration_strategy,
    revision_strategy,
    extreme_strategy,
    print_lock_strategy,
)

RISK_SOURCE: Final[str] = Path(risk_module.__file__).read_text(encoding="utf-8")


def _source(module: object) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")  # type: ignore[attr-defined]


def _module_id(module: object) -> str:
    return str(getattr(module, "__name__", module)).rsplit(".", 2)[-2]


# ---------------------------------------------------------------------------
# RED-7 -- the fabricated fallback is DELETED, not merely unused
#
# `starting_equity` was dead already (nothing in src/, scripts/ or tests/ set
# it), but a live-reachable constant that a config can re-enable IS the
# defect. Deleting it means a future `ImportableStrategyConfig` naming it
# fails construction loudly instead of silently restoring a fabricated
# denominator.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", CONFIG_MODULES, ids=_module_id)
def test_no_config_carries_a_starting_equity_field(module: object) -> None:
    source = _source(module)

    assert "starting_equity" not in source
    # The literal itself, so a rename of the field cannot smuggle the same
    # fabricated denominator back under a new name.
    assert "10_000.0" not in source


@pytest.mark.parametrize("module", STRATEGY_MODULES, ids=_module_id)
def test_no_strategy_reads_a_fabricated_equity_fallback(module: object) -> None:
    assert "starting_equity" not in _source(module)


@pytest.mark.parametrize("module", STRATEGY_MODULES, ids=_module_id)
def test_every_strategy_reads_equity_through_the_one_shared_observer(
    module: object,
) -> None:
    """Five byte-identical `_equity()` bodies became one `observed_equity`."""
    source = _source(module)

    assert "observed_equity(" in source
    assert "def _equity(" not in source


# ---------------------------------------------------------------------------
# RED-9 -- reduce-only, entered silently, is indistinguishable from a bot
# that saw no opportunity
#
# That is T-4's own diagnosis recurring one level up. The plan's falsifier
# ("do these refusals cluster anywhere but a start-up window?") is only
# runnable if each refusal reaches the journal with the tick clock it was
# decided on.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", STRATEGY_MODULES, ids=_module_id)
def test_every_strategy_logs_the_reduce_only_state_with_its_tick_timestamp(
    module: object,
) -> None:
    source = _source(module)

    assert "reduce_only_refusal_note(" in source
    assert "tick_ts_ns=self.clock.timestamp_ns()" in source


# ---------------------------------------------------------------------------
# RED-12 -- the two shapes mypy lets through
# ---------------------------------------------------------------------------


def _equity_reads(node: ast.AST) -> bool:
    """True if `node` is a read of something spelled `equity`."""
    if isinstance(node, ast.Attribute):
        return node.attr == "equity"
    if isinstance(node, ast.Name):
        return node.id == "equity"
    return False


def _fail_open_equity_guards(tree: ast.AST) -> list[int]:
    """Line numbers of any `equity > 0` comparison.

    The exact shape of the fail-open cap: false at zero, so the branch is
    skipped and the order passes at FULL size. Banned outright rather than
    only where it guards a cap -- `equity is None` and `equity <= 0` express
    everything this module legitimately needs to ask.
    """
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and _equity_reads(node.left)
        and any(isinstance(op, ast.Gt) for op in node.ops)
        and any(isinstance(c, ast.Constant) and c.value == 0 for c in node.comparators)
    ]


def _truthiness_defaulted_equity_reads(tree: ast.AST) -> list[int]:
    """Line numbers of any `equity`-defaulting truthiness expression.

    Two shapes, both of which type-check clean under strict mypy and both of
    which reinstate a fabricated denominator:

    * ``portfolio.equity or 0.0``
    * ``portfolio.equity if portfolio.equity else 0.0``

    They are worse than the constant they replace, because there is no field
    left for a reader to notice.
    """
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if any(_equity_reads(value) for value in node.values):
                hits.append(node.lineno)
        elif isinstance(node, ast.IfExp) and _equity_reads(node.test):
            hits.append(node.lineno)
    return hits


def test_risk_never_guards_the_equity_cap_on_a_greater_than_zero_test() -> None:
    """RED-12a: today's fail-open, banned by shape.

    `if portfolio.equity > 0 and order_notional > limits.max_equity_fraction
    * portfolio.equity` skipped the whole cap at zero -- no clip, no refusal,
    full size. The replacement asks `is None` and `<= 0`, which cannot
    fail open.
    """
    hits = _fail_open_equity_guards(ast.parse(RISK_SOURCE))

    assert hits == [], f"equity > 0 guard(s) at risk.py line(s) {hits}"


def test_risk_never_truthiness_defaults_an_equity_read() -> None:
    """RED-12b: tomorrow's regression, banned by shape.

    Vacuous TODAY -- and stated as such rather than presented as a defect
    test. It is in the same test module as RED-12a on purpose: the `> 0` ban
    alone would let `or 0.0` re-fabricate the number the moment `None`
    started reaching arithmetic.
    """
    hits = _truthiness_defaulted_equity_reads(ast.parse(RISK_SOURCE))

    assert hits == [], f"truthiness-defaulted equity read(s) at risk.py line(s) {hits}"


# --- positive controls: a detector that detects nothing guards nothing ------


@pytest.mark.parametrize(
    "source",
    [
        "if portfolio.equity > 0 and notional > cap: pass",
        "x = 1 if equity > 0 else 2",
        "assert snapshot.equity > 0",
    ],
)
def test_the_fail_open_detector_actually_fires(source: str) -> None:
    assert _fail_open_equity_guards(ast.parse(source)) != []


@pytest.mark.parametrize(
    "source",
    [
        "value = portfolio.equity or 0.0",
        "value = equity or 10_000.0",
        "value = portfolio.equity if portfolio.equity else 0.0",
    ],
)
def test_the_truthiness_default_detector_actually_fires(source: str) -> None:
    assert _truthiness_defaulted_equity_reads(ast.parse(source)) != []


@pytest.mark.parametrize(
    "source",
    [
        "if equity is None: pass",
        "if equity <= 0: pass",
        "value = other or 0.0",
        "if portfolio.equity > threshold: pass",
    ],
)
def test_neither_detector_fires_on_the_shapes_t4_actually_uses(source: str) -> None:
    tree = ast.parse(source)

    assert _fail_open_equity_guards(tree) == []
    assert _truthiness_defaulted_equity_reads(tree) == []
