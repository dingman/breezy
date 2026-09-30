"""SL-13p contract tests: the A-5 firewall between the live and batch paths.

`docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md` §12 A-5: "A contract
test pins that (ii) [the batch path] imports none of (i)'s [the live path's]
classes, which rules out a vacuous self-comparison." Plan
`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §4.4 item 3: "A
contract test pins that the parity tool imports no settlement, CLI-label or
P&L module."

Mirrors the AST-scan shape already established by
``tests/strategy/forecast_quantile_ladder/test_forbidden_imports.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BATCH_MODULE = _REPO_ROOT / "scripts/analysis/nbp_shadow_parity_pure.py"
_HARNESS_MODULES = (
    _BATCH_MODULE,
    _REPO_ROOT / "scripts/analysis/nbp_shadow_parity.py",
)

#: The live path's own classes/modules (ruling §12 A-5(ii): "no import of
#: the strategy/actor classes"). Covers both the module path and the bare
#: imported name, so a re-export or a `from X import *` style indirection
#: cannot quietly satisfy a narrower check.
_FORBIDDEN_LIVE_PATH_MODULES = (
    "breezy.strategy.forecast_quantile_ladder.decision",
    "breezy.strategy.forecast_quantile_ladder.strategy",
    "breezy.strategy.ladder_ev.forecast_subscriber",
    "breezy.ingest.nbm_quantile_actor",
    "breezy.ingest.nbm_forecast_actor",
    "nautilus_trader",
)
_FORBIDDEN_LIVE_PATH_NAMES = (
    "Decision",
    "NotDPlus1",
    "NotExecutable",
    "Refuse",
    "SidedAsk",
    "Take",
    "evaluate",
    "ForecastQuantileLadderStrategy",
    "SupportsExpiresAtNs",
    "ForecastQuantileStateActor",
    "ForecastStateActor",
    "NbmQuantileActor",
    "NbmForecastActor",
    "BacktestEngine",
    "Actor",
    "Strategy",
)

#: Plan §4.4 item 3: "no settlement, CLI-label or P&L module." Module-path
#: substrings, checked case-sensitively against the dotted import path.
_FORBIDDEN_SUBSTRINGS = (
    "settlement",
    "_cli",
    "replay_results",
    "run_weather_strategy_backtests",
    "pnl",
)


def _imports_of(path: Path) -> list[tuple[str | None, str]]:
    """``(module, imported_name)`` for every ``ImportFrom``, and
    ``(None, module)`` for every plain ``Import`` -- mirrors
    ``test_forbidden_imports.py``'s own helper exactly."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pairs: list[tuple[str | None, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                pairs.append((node.module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                pairs.append((None, alias.name))
    return pairs


def test_the_batch_module_imports_none_of_the_live_paths_forbidden_modules() -> None:
    for module, _name in _imports_of(_BATCH_MODULE):
        if module is None:
            continue
        for forbidden in _FORBIDDEN_LIVE_PATH_MODULES:
            assert not module.startswith(forbidden), (
                f"{_BATCH_MODULE.name} imports from forbidden live-path module "
                f"{module!r} (matches {forbidden!r}); this would make A-5 parity "
                f"a vacuous self-comparison"
            )


def test_the_batch_module_imports_none_of_the_live_paths_forbidden_names() -> None:
    for _module, name in _imports_of(_BATCH_MODULE):
        assert name not in _FORBIDDEN_LIVE_PATH_NAMES, (
            f"{_BATCH_MODULE.name} imports forbidden live-path name {name!r}; "
            f"this would make A-5 parity a vacuous self-comparison"
        )


def test_the_batch_module_never_does_a_bare_import_of_nautilus_trader() -> None:
    for module, name in _imports_of(_BATCH_MODULE):
        target = module if module is not None else name
        assert not target.startswith("nautilus_trader"), (
            f"{_BATCH_MODULE.name} imports {target!r}; the batch path is pure "
            f"Python, no Nautilus dependency (ruling §12 A-5(ii))"
        )


def test_the_batch_module_imports_no_strategy_decision_or_strategy_module() -> None:
    forbidden = {
        "breezy.strategy.forecast_quantile_ladder.decision",
        "breezy.strategy.forecast_quantile_ladder.strategy",
    }
    for module, _name in _imports_of(_BATCH_MODULE):
        if module is None:
            continue
        assert module not in forbidden, (
            f"{_BATCH_MODULE.name} imports {module!r}; A-5 requires the pure "
            "batch path to implement the PLAN formulas independently"
        )


def test_neither_harness_module_imports_a_settlement_cli_or_pnl_module() -> None:
    for path in _HARNESS_MODULES:
        for module, name in _imports_of(path):
            target = module if module is not None else name
            lowered = target.lower()
            for forbidden in _FORBIDDEN_SUBSTRINGS:
                assert forbidden not in lowered, (
                    f"{path.name} imports {target!r}, which looks like a "
                    f"settlement/CLI/P&L module (matches {forbidden!r}); plan "
                    f"§4.4 item 3 forbids this"
                )
