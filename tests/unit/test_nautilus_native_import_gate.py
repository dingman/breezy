"""Adopting a native Nautilus API must require ZERO configuration edits --
while importing the Polymarket **.com** adapter must still be impossible.

The gate this file holds
------------------------

``pyproject.toml`` carries one import-linter ``forbidden`` contract named
"Breezy never imports the Nautilus Polymarket .com adapter". Its ban is on the
``.com`` adapter, and on nothing else: ``nautilus_trader.adapters.polymarket``.

It was once written as a ban on ``nautilus_trader`` -- the WHOLE framework --
unblocked by a hand-maintained per-module allow-list. That made "reuse a
native" a two-file change whose second file is invisible from the author's
seat, in a repo whose first principle is that Nautilus already provides what
we need. The blanket form is also a poor proxy for the real ban: it says
nothing about the ``.com`` adapter specifically, so the allow-list -- not the
contract -- was what actually held the line.

Why these tests SYNTHESISE modules rather than asserting on config text
-----------------------------------------------------------------------

A test that reads ``pyproject.toml`` cannot tell whether the tools implement
the ban the text appears to describe. ``grimp`` squashes EXTERNAL packages to
their top-level name, so ``forbidden_modules = ["nautilus_trader.adapters
.polymarket"]`` is only expressible while ``nautilus_trader`` is a *root*
package -- a fact no amount of reading the contract stanza reveals. So modules
are really written to disk and the real ``lint-imports`` is really run over
them; what is asserted is the exit status of the command CI runs.

The structural counterpart lives in
``tests/unit/test_test_safety_tooling_config.py``. Same shape as
``tests/unit/test_strategy_module_gate.py``, which holds the sibling gate for
strategy modules.

The synthesised modules are deleted in a ``finally``. They are named with a
leading underscore and a ``_gate_`` marker so a leftover from a crashed run is
identifiable at a glance.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Final, Protocol

import pytest

#: Repository root -- the working directory `lint-imports` must run from,
#: since it reads `pyproject.toml` relative to it.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Where synthesised probe modules are written. `runtime` is a package that
#: legitimately names natives, so a probe planted here tests the forbidden
#: contract without also tripping the LAYERS contract.
_PROBE_PACKAGE: Final[Path] = REPO_ROOT / "src" / "breezy" / "runtime"

_LINT_IMPORTS: Final[Path] = REPO_ROOT / ".venv" / "bin" / "lint-imports"

#: A brand-new module adopting a native, non-Polymarket Nautilus API. Under
#: the old framework-wide ban this module broke `lint-imports` until somebody
#: added a line to `pyproject.toml`.
_GENERATED_NATIVE: Final[str] = '''"""Synthesised by a gate test; deleted after."""

from __future__ import annotations

from nautilus_trader.model.identifiers import ClientId

__all__ = ["ClientId"]
'''

#: The real ban, in two shapes: the adapter package itself...
_GENERATED_COM_PACKAGE: Final[str] = '''"""Synthesised by a gate test; deleted after."""

from __future__ import annotations

from nautilus_trader.adapters import polymarket

__all__ = ["polymarket"]
'''

#: ...and a module deep inside it. Both must be rejected.
_GENERATED_COM_SUBMODULE: Final[str] = '''"""Synthesised by a gate test; deleted after."""

from __future__ import annotations

from nautilus_trader.adapters.polymarket.common.enums import PolymarketOrderSide

__all__ = ["PolymarketOrderSide"]
'''

_CONTRACT_NAME: Final[str] = "Breezy never imports the Nautilus Polymarket .com adapter"


class _PlantModule(Protocol):
    """Writes a probe module into `breezy.runtime` and returns its path."""

    def __call__(self, stem: str, source: str) -> Path: ...


def _run_lint_imports() -> subprocess.CompletedProcess[str]:
    # Fixed argv, no shell, repo-local tool.
    return subprocess.run(
        [str(_LINT_IMPORTS)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def plant_module() -> Iterator[_PlantModule]:
    """Write a probe module into `breezy.runtime`, then remove it."""
    written: list[Path] = []

    def _plant(stem: str, source: str) -> Path:
        path = _PROBE_PACKAGE / f"_gate_generated_{stem}.py"
        path.write_text(source, encoding="utf-8")
        written.append(path)
        return path

    try:
        yield _plant
    finally:
        for path in written:
            path.unlink(missing_ok=True)


def test_a_brand_new_module_may_import_a_native_with_no_pyproject_edit(
    plant_module: _PlantModule,
) -> None:
    """`lint-imports` must accept a native import it was never told about.

    The whole contract set is run, not just the forbidden one: narrowing the
    forbidden contract must not be achieved by relaxing the LAYER contract.
    """
    plant_module("native", _GENERATED_NATIVE)

    result = _run_lint_imports()

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("stem", "source"),
    [
        ("com_package", _GENERATED_COM_PACKAGE),
        ("com_submodule", _GENERATED_COM_SUBMODULE),
    ],
)
def test_a_module_importing_the_polymarket_com_adapter_is_rejected(
    plant_module: _PlantModule, stem: str, source: str
) -> None:
    """The real ban still fires on a planted violation.

    This is the test the narrowing had to earn: a contract that no longer
    names the whole framework must still make the `.com` adapter unreachable
    from every Breezy module, at the package root and deep inside it alike.
    """
    path = plant_module(stem, source)

    result = _run_lint_imports()

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert _CONTRACT_NAME in output, output
    assert "nautilus_trader.adapters.polymarket" in output, output
    assert path.stem in output, output
