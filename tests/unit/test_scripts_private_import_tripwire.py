"""Tripwire: scripts that import private breezy names keep resolving them.

An AST scan of ``scripts/**/*.py`` finds ``from breezy... import _name``
(including aliases and imports nested in functions). Each name must still be
an attribute of the module it is imported from. A rename in src then fails
here instead of failing a nightly job.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"

#: Anchor so a scanner that matches nothing cannot pass. Not a count pin.
_ANCHORED_IMPORT = ("breezy.strategy.current_rung_hold.strategy", "_local_hour")


def private_breezy_imports(source: str, *, filename: str) -> list[tuple[str, str]]:
    """``(module, name)`` pairs for ``from breezy... import _name`` in ``source``."""
    tree = ast.parse(source, filename=filename)
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level or node.module is None:
            continue
        module = node.module
        if module != "breezy" and not module.startswith("breezy."):
            continue
        for alias in node.names:
            if alias.name.startswith("_"):
                found.append((module, alias.name))
    return found


def scan_scripts(root: Path) -> list[tuple[str, str, str]]:
    """``(relpath, module, name)`` for every private breezy import under ``root``."""
    refs: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.parts:
            continue
        relpath = path.relative_to(root.parent).as_posix()
        text = path.read_text(encoding="utf-8")
        for module, name in private_breezy_imports(text, filename=relpath):
            refs.append((relpath, module, name))
    return refs


def unresolved_private_imports(
    refs: list[tuple[str, str]],
) -> list[str]:
    """Import each module and report symbols ``hasattr`` rejects."""
    missing: list[str] = []
    loaded: dict[str, ModuleType] = {}
    for module_name, symbol in sorted(set(refs)):
        module = loaded.get(module_name)
        if module is None:
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 — import side effects raise arbitrarily
                missing.append(
                    f"{module_name}.{symbol}: import failed ({exc.__class__.__name__}: {exc})"
                )
                continue
            loaded[module_name] = module
        if not hasattr(module, symbol):
            missing.append(f"{module_name}.{symbol}: attribute is gone")
    return missing


def test_scripts_private_breezy_imports_still_resolve() -> None:
    refs = scan_scripts(_SCRIPTS)
    pairs = [(module, name) for _rel, module, name in refs]
    assert pairs, "scanner found no private breezy imports under scripts/"
    assert _ANCHORED_IMPORT in pairs, pairs
    missing = unresolved_private_imports(pairs)
    assert missing == [], "\n".join(missing)


def test_scanner_sees_a_nested_private_import_and_ignores_public_names() -> None:
    source = (
        "import breezy.runtime.settings\n"
        "from breezy.runtime.settings import PUBLIC\n"
        "def load():\n"
        "    from breezy.strategy.current_rung_hold.strategy import _local_hour as hour\n"
    )
    assert private_breezy_imports(source, filename="sample.py") == [
        ("breezy.strategy.current_rung_hold.strategy", "_local_hour"),
    ]


def test_a_renamed_private_symbol_is_unresolved() -> None:
    missing = unresolved_private_imports(
        [("breezy.strategy.current_rung_hold.strategy", "_local_hour_r0a_absent")],
    )
    assert missing == [
        "breezy.strategy.current_rung_hold.strategy._local_hour_r0a_absent: attribute is gone",
    ]


def test_scanner_rejects_a_script_tree_whose_private_import_was_renamed(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "analysis"
    script.mkdir(parents=True)
    (script / "job.py").write_text(
        "from breezy.strategy.current_rung_hold.strategy import _local_hour_r0a_absent\n",
        encoding="utf-8",
    )
    refs = scan_scripts(tmp_path / "scripts")
    pairs = [(module, name) for _rel, module, name in refs]
    missing = unresolved_private_imports(pairs)
    assert any("_local_hour_r0a_absent" in item for item in missing)
