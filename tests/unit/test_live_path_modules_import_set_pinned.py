"""Pin the `breezy.*` import sets of the live-path persistence modules and the
`parse_family_manifest` / `load_family_manifest` split (ARCH-0 seam A, 1c)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import ModuleType

import pytest

from breezy.persistence import family_manifest, live_orders_gate

_EXPECTED_BREEZY_IMPORTS = {
    family_manifest: {"breezy.persistence.mechanism_test_guard"},
    live_orders_gate: {"breezy.persistence.family_manifest"},
}


def _breezy_imports(module: ModuleType) -> set[str]:
    source = Path(str(inspect.getsourcefile(module))).read_text(encoding="utf-8")
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "breezy" or node.module.startswith("breezy."):
                found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.split(".")[0] == "breezy")
    return found


@pytest.mark.parametrize("module", list(_EXPECTED_BREEZY_IMPORTS), ids=lambda m: m.__name__)
def test_live_path_modules_import_set_pinned(module: ModuleType) -> None:
    assert _breezy_imports(module) == _EXPECTED_BREEZY_IMPORTS[module]


def test_parse_family_manifest_signature() -> None:
    assert "parse_family_manifest" in family_manifest.__all__
    sig = inspect.signature(family_manifest.parse_family_manifest)
    params = sig.parameters
    assert list(params) == ["raw", "path", "allow_draft"]
    assert params["raw"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params["path"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["allow_draft"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["allow_draft"].default is False


def test_load_family_manifest_delegates_to_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_bytes(b"{}")
    calls: list[tuple[bytes, Path, bool]] = []
    sentinel = object()

    def _fake(raw: bytes, *, path: Path, allow_draft: bool = False) -> object:
        calls.append((raw, path, allow_draft))
        return sentinel

    monkeypatch.setattr(family_manifest, "parse_family_manifest", _fake)
    result = family_manifest.load_family_manifest(manifest, allow_draft=True)
    assert result is sentinel
    assert calls == [(b"{}", manifest, True)]
