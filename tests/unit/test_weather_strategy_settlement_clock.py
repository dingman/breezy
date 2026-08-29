"""No weather strategy may carry a fabricated settlement clock.

The defect this pins. The operator's bundles computed hours-to-settlement from
``TemperatureContract.settlement_local_time`` -- a hardcoded ``time(23, 59)``
in a hardcoded ``"America/Chicago"``, applied to EVERY contract regardless of
station. Polymarket.us settles five cities (NYC, San Francisco, Miami,
Chicago-Midway, Los Angeles) off the local NWS Daily Climate Report, so that
default is wrong for four of the five, and the venue's own settlement instant
is 08:00 ET on the following day -- not 23:59 Central.

Breezy does not recompute that deadline at the strategy layer at all.
Settlement is driven by the native ``InstrumentClose`` event
(``breezy.runtime.backtest_harness``), and the only hours-to-settlement a
strategy may read is ``ForecastSnapshot.horizon_hours``, which the injected
``ForecastSource`` is contractually required to keep live as of the ``now`` it
was called with (see ``breezy.strategy.weather_common.forecast_source``).

This was deliberately removed during the first bundle's integration. These
tests exist so it cannot be reintroduced by a later port.

The scan is AST-based and looks at EXECUTABLE code only: the module docstrings
in this area necessarily quote the removed names to explain why they are gone,
and a substring scan would either fail on those or be defeated by them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Every module of every weather strategy package, plus the shared layer.
WEATHER_STRATEGY_DIRS = (
    "src/breezy/strategy/weather_common",
    "src/breezy/strategy/forecast_mispricing",
    "src/breezy/strategy/calibration_mean_reversion",
    "src/breezy/strategy/forecast_revision",
)

#: Fabricated-clock fingerprints from the bundles: identifiers a strategy must
#: not define, call, or read.
#:
#: Deliberately NOT in this set: the parameter name ``hours_to_settlement``
#: (``RiskManager.evaluate_order``). Naming the quantity is fine and necessary
#: -- the defect was DERIVING it from a hardcoded wall clock. What must not
#: exist is the derivation, so the fingerprints are the clock's own symbols.
FORBIDDEN_NAMES = frozenset({"settlement_local_time", "settlement_datetime_utc", "ZoneInfo"})

#: Timezone literals a strategy must not carry at all.
FORBIDDEN_LITERALS = frozenset({"America/Chicago", "US/Central"})


def _modules() -> list[Path]:
    found: list[Path] = []
    for directory in WEATHER_STRATEGY_DIRS:
        found.extend(sorted(Path(directory).glob("*.py")))
    return found


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """`id()` of every string Constant that is a docstring, not executable code."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            ids.add(id(body[0].value))
    return ids


def test_weather_strategy_packages_are_all_present() -> None:
    """Non-vacuity: the scan below must actually have files to scan."""
    for directory in WEATHER_STRATEGY_DIRS:
        assert Path(directory).is_dir(), f"{directory} does not exist"
    assert len(_modules()) >= 12


@pytest.mark.parametrize("module", _modules(), ids=str)
def test_no_module_uses_a_fabricated_settlement_clock_name(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    offenders = sorted(
        {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if (isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES)
            or (isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES)
        },
    )
    assert not offenders, f"{module}: fabricated settlement clock names {offenders}"


@pytest.mark.parametrize("module", _modules(), ids=str)
def test_no_module_carries_a_hardcoded_settlement_timezone(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    offenders = sorted(
        {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and node.value in FORBIDDEN_LITERALS
        },
    )
    assert not offenders, f"{module}: hardcoded settlement timezone {offenders}"
