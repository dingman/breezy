"""SL-12 forbidden-import contract (plan §7 row SL-12, R2-18).

FORBIDS importing, anywhere in ``breezy.strategy.forecast_quantile_ladder``:

* ``breezy.strategy.ladder_ev.decision.exclusion_filter`` and
  ``ExclusionInputs`` -- including the re-export
  ``breezy.strategy.ladder_ev.exclusion_filter`` (``ladder_ev/__init__.py``);
* ``breezy.strategy.current_rung_hold.archive_table`` (``P_HOLD_LOWER`` /
  ``P_HOLD_UPPER``) -- the closed model's collider cells (plan §1.2 item 2:
  "No dependence on the P_HOLD_* collider cells").

Scanned over the AST of every module in the package's import graph, not by
substring, mirroring ``test_forecast_actor_push.py``'s own AST-based purity
check. Runs on-disk source (never on already-imported, possibly-monkeypatched
module objects), so a re-export added later is still caught.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE_ROOT = (
    Path(__file__).resolve().parents[3] / "src/breezy/strategy/forecast_quantile_ladder"
)

_FORBIDDEN_MODULES = (
    "breezy.strategy.current_rung_hold.archive_table",
)

#: (module, name) pairs -- covers the re-export path too, since the re-export
#: itself is a ``from breezy.strategy.ladder_ev.decision import ...`` (or the
#: package-level ``from breezy.strategy.ladder_ev import exclusion_filter``)
#: inside THIS package -- neither of which this package's own source may do.
_FORBIDDEN_IMPORTED_NAMES = (
    ("breezy.strategy.ladder_ev.decision", "exclusion_filter"),
    ("breezy.strategy.ladder_ev.decision", "ExclusionInputs"),
    ("breezy.strategy.ladder_ev", "exclusion_filter"),
    ("breezy.strategy.ladder_ev", "ExclusionInputs"),
)


def _package_py_files() -> list[Path]:
    """Recursive: a later slice may nest modules under this package, and the
    contract must keep covering them without anyone remembering to widen a
    ``glob("*.py")`` (item 6, SL-12 review)."""
    files = sorted(_PACKAGE_ROOT.rglob("*.py"))
    assert files, f"expected at least one module under {_PACKAGE_ROOT}"
    return files


def _imports_of(path: Path) -> list[tuple[str | None, str]]:
    """Return ``(module, imported_name)`` for every ``ImportFrom`` in ``path``,
    and ``(None, module)`` for every plain ``Import``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pairs: list[tuple[str | None, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                pairs.append((node.module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                pairs.append((None, alias.name))
    return pairs


def test_no_module_in_the_package_imports_a_forbidden_module() -> None:
    for path in _package_py_files():
        for module, _name in _imports_of(path):
            if module is None:
                continue
            for forbidden in _FORBIDDEN_MODULES:
                assert not module.startswith(forbidden), (
                    f"{path.name} imports from forbidden module {module!r} "
                    f"(matches {forbidden!r})"
                )


def test_no_module_in_the_package_imports_a_forbidden_symbol() -> None:
    for path in _package_py_files():
        imported = _imports_of(path)
        for module, name in imported:
            for forbidden_module, forbidden_name in _FORBIDDEN_IMPORTED_NAMES:
                assert not (module == forbidden_module and name == forbidden_name), (
                    f"{path.name} imports forbidden symbol {name!r} from "
                    f"{module!r}"
                )


def test_no_module_in_the_package_imports_p_hold_bound_names_from_anywhere() -> None:
    """Belt-and-braces: refuse the bare names too, regardless of source module,
    since a future indirection could rename the module but keep the name."""
    for path in _package_py_files():
        for _module, name in _imports_of(path):
            assert name not in ("P_HOLD_LOWER", "P_HOLD_UPPER"), (
                f"{path.name} imports {name!r}, the closed model's collider cell"
            )


def _asdict_call_sites(path: Path) -> list[str]:
    """Mirror ``test_polymarket_us_credential_serialization.py``'s own
    ``find_unallowlisted_asdict_calls`` detection shape: a ``Call`` whose
    function name (attribute or bare name) is exactly ``"asdict"``.
    ``dataclasses.asdict`` is banned repo-wide outside that file's closed
    allowlist, and this package must never be on it -- the shadow log
    serialises every ``Decision`` variant via ``decision_log_fields``
    instead."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sites: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "asdict":
            sites.append(f"{path.name}:{node.lineno}")
    return sites


def test_no_module_in_the_package_calls_asdict() -> None:
    for path in _package_py_files():
        sites = _asdict_call_sites(path)
        assert not sites, (
            f"asdict() is banned repo-wide outside the closed allowlist in "
            f"test_polymarket_us_credential_serialization.py; found: {sites}"
        )
