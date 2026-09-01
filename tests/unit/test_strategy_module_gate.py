"""Writing a strategy must require ZERO configuration edits.

The gate this file holds
------------------------

``pyproject.toml`` carries a mypy ``disallow_subclassing_any = false``
override that a strategy module must appear in, because
``nautilus_trader.trading.strategy.Strategy`` is a compiled Cython class and
without the override ``Class cannot subclass "Strategy" (has type "Any")``
fails ``mypy src``.

It was once written PER MODULE, alongside a second per-module entry in the
import-linter forbidden contract's ``ignore_imports`` (which then banned the
whole of ``nautilus_trader``). That made "add a strategy" a three-file change
whose two other files are invisible from the strategy author's seat, and whose
omission is not caught by ``pytest`` at all -- the suite stays green while two
other gates go red. The mypy override is now a wildcard over
``breezy.strategy``; the import-linter side no longer needs an entry at all,
because that contract now forbids only the Polymarket ``.com`` adapter
(``tests/unit/test_nautilus_native_import_gate.py``).

Why the test SYNTHESISES a module rather than asserting on config text
----------------------------------------------------------------------

A test that reads ``pyproject.toml`` and looks for the string ``strategy.*``
passes for any wildcard syntax, including one the tools do not implement --
and import-linter's ``*`` (direct children) and ``**`` (whole subtree) are
different operators, only one of which survives a strategy in a subpackage.
So the module is really written to disk, and the real ``mypy`` and real
``lint-imports`` are really run over it. What is asserted is the exit status
of the same commands CI runs.

The synthesised module is deleted in a ``finally``. It is named with a leading
underscore and a ``_gate_`` marker so a leftover from a crashed run is
identifiable at a glance.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

#: The strategy package under test.
STRATEGY_PACKAGE: Final[Path] = (
    Path(__file__).resolve().parents[2] / "src" / "breezy" / "strategy"
)

#: Repository root -- the working directory both gates must run from, since
#: each reads `pyproject.toml` relative to it.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: A module that subclasses `Strategy` and imports `nautilus_trader`: the two
#: facts that made every previous strategy a configuration change. Nothing
#: else about it matters -- it is never instantiated or run.
_GENERATED_STRATEGY: Final[str] = '''"""Synthesised by the strategy gate test; deleted after."""

from __future__ import annotations

from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

__all__ = ["GateProbe", "GateProbeConfig"]


class GateProbeConfig(StrategyConfig, frozen=True):
    """No fields; the subclassing itself is the whole point."""


class GateProbe(Strategy):
    """Subclasses the compiled `Strategy`, which is what mypy erases to Any."""

    def __init__(self, config: GateProbeConfig) -> None:
        super().__init__(config)
'''


@pytest.fixture
def generated_strategy() -> object:
    """Write a brand-new strategy module, yield its path, then remove it."""
    path = STRATEGY_PACKAGE / "_gate_generated_strategy.py"
    path.write_text(_GENERATED_STRATEGY, encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _run(*command: str) -> subprocess.CompletedProcess[str]:
    # Fixed argv, no shell, repo-local tools.
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_brand_new_strategy_module_typechecks_with_no_pyproject_edit(
    generated_strategy: Path,
) -> None:
    """`mypy` must accept a `Strategy` subclass it has never been told about."""
    result = _run(sys.executable, "-m", "mypy", str(generated_strategy.relative_to(REPO_ROOT)))

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_brand_new_strategy_module_keeps_the_import_contract(
    generated_strategy: Path,
) -> None:
    """`lint-imports` must accept its `nautilus_trader` import.

    The whole contract set is run, not just the forbidden one: a strategy is
    the TOP layer, so a new strategy module must satisfy the LAYER contract
    as well as the `.com`-adapter ban.
    """
    del generated_strategy
    result = _run(str(REPO_ROOT / ".venv" / "bin" / "lint-imports"))

    assert result.returncode == 0, result.stdout + result.stderr


def test_no_strategy_module_is_named_individually_in_pyproject(
    generated_strategy: Path,
) -> None:
    """The cheap structural counterpart, so the intent survives a refactor.

    Naming ONE strategy module individually is how the per-module regime
    starts again; the subprocess tests above would still pass while the next
    author was quietly expected to add a line.
    """
    del generated_strategy
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    modules = sorted(
        path.stem for path in STRATEGY_PACKAGE.glob("*.py") if path.stem != "__init__"
    )

    named = [module for module in modules if f"breezy.strategy.{module}" in pyproject]

    assert named == [], (
        f"{named} are named individually in pyproject.toml; the mypy allowlist "
        f"must cover `breezy.strategy` by WILDCARD so writing a strategy needs "
        f"no config edit"
    )
