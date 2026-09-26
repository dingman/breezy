"""T-META (ING-2 S3a, A7/R3-2): no test may spy on the two native read/bulk
methods this module's mirror replaces, outside an explicit, exact allowlist.

Retargeting :func:`breezy.runtime.quote_tape_ingest_cli._convert_stream_natively`
and :func:`breezy.persistence.feather_read.read_feather_coalesced` only earns
its safety if nothing in the suite can quietly keep patching the OLD native
seam (``ParquetDataCatalog.convert_stream_to_data`` /
``ParquetDataCatalog._read_feather_file``) and pass vacuously. This module
``ast``-parses every ``tests/**/*.py`` file (excluding itself) and flags any
patching call or attribute assignment that targets either name, however it is
spelled, aliased, or string-folded -- see the module docstring sections below
for the exact forms.

Two allowlisted ``(relpath, function qualname)`` pairs wrap the native
methods as an oracle rather than replacing them; the allowlist is enforced in
BOTH directions, so a stale entry (zero findings) fails just as loudly as an
unlisted one.
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

BANNED: tuple[str, ...] = ("convert_stream_to_data", "_read_feather_file")

#: Exact (relpath, function qualname, reason). No wildcards -- enforced by
#: :func:`test_the_allowlist_has_no_wildcards`.
ALLOWLIST: tuple[tuple[str, str, str], ...] = (
    (
        "tests/contract/test_quote_tape_ingest_native_pin.py",
        "TestNativeConvertStreamToDataCallSequence.test_the_call_sequence_and_kwargs_without_other_catalog",
        "wrapping oracle: calls through to native",
    ),
    (
        "tests/unit/test_quote_tape_ingest_bounded_read.py",
        "test_no_path_calls_the_native_reader",
        "T-R3 tripwire; paired positive control",
    ),
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Finding:
    relpath: str
    qualname: str
    lineno: int
    form: str


# ---------------------------------------------------------------------------
# AST resolution helpers
# ---------------------------------------------------------------------------


def _dotted(node: ast.AST) -> str | None:
    """Reconstruct ``a.b.c`` from a ``Name``/``Attribute`` chain, else ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _fold_string(node: ast.AST, local_to_string: dict[str, str]) -> str | None:
    """Resolve ``node`` to a literal string, or ``None`` if not resolvable."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return local_to_string.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _fold_string(node.left, local_to_string)
        right = _fold_string(node.right, local_to_string)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    return None


def _resolve_dotted(
    dotted: str,
    local_to_dotted: dict[str, str],
    import_map: dict[str, str],
    depth: int = 0,
) -> str:
    """Expand the LEFTMOST segment of ``dotted`` through import/local aliases."""
    no_dot_no_alias = (
        "." not in dotted and dotted not in local_to_dotted and dotted not in import_map
    )
    if depth > 8 or no_dot_no_alias:
        head = dotted
    else:
        head = dotted.split(".", 1)[0]
    rest = dotted[len(head) + 1 :] if "." in dotted else ""
    replacement = import_map.get(head) or local_to_dotted.get(head)
    if replacement is None or replacement == head:
        return dotted
    new_dotted = f"{replacement}.{rest}" if rest else replacement
    if new_dotted == dotted or depth > 8:
        return new_dotted
    return _resolve_dotted(new_dotted, local_to_dotted, import_map, depth + 1)


def _classify_callee(resolved: str) -> str | None:
    terminal = resolved.rsplit(".", 1)[-1]
    if terminal == "setattr":
        return "setattr"
    if terminal == "__setattr__":
        return "dunder_setattr"
    if terminal == "patch":
        return "patch"
    if terminal in ("object", "multiple"):
        prior = resolved.rsplit(".", 1)[0] if "." in resolved else ""
        prior_terminal = prior.rsplit(".", 1)[-1]
        if prior_terminal == "patch":
            return "patch_object_or_multiple"
    return None


class _AliasCollector(ast.NodeVisitor):
    """First pass: collect import aliases and Name-bound aliases file-wide."""

    def __init__(self) -> None:
        self.import_map: dict[str, str] = {}
        self.local_to_dotted: dict[str, str] = {}
        self.local_to_string: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.import_map[local] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            self.import_map[local] = f"{module}.{alias.name}" if module else alias.name

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                dotted = _dotted(node.value)
                if dotted is not None:
                    self.local_to_dotted[target.id] = dotted
                    continue
                literal = _fold_string(node.value, {})
                if literal is not None:
                    self.local_to_string[target.id] = literal
        self.generic_visit(node)


class _SpyFinder(ast.NodeVisitor):
    def __init__(
        self,
        relpath: str,
        import_map: dict[str, str],
        local_to_dotted: dict[str, str],
        local_to_string: dict[str, str],
    ) -> None:
        self.relpath = relpath
        self.import_map = import_map
        self.local_to_dotted = local_to_dotted
        self.local_to_string = local_to_string
        self.findings: list[Finding] = []
        self._scope_stack: list[str] = []

    def _qualname(self) -> str:
        return ".".join(self._scope_stack) if self._scope_stack else "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def _resolve_callee(self, func: ast.AST) -> str | None:
        dotted = _dotted(func)
        if dotted is None:
            return None
        return _resolve_dotted(dotted, self.local_to_dotted, self.import_map)

    def visit_Call(self, node: ast.Call) -> None:
        resolved = self._resolve_callee(node.func)
        if resolved is not None:
            kind = _classify_callee(resolved)
            if kind is not None:
                self._check_call(node, kind)
        self.generic_visit(node)

    def _check_call(self, node: ast.Call, kind: str) -> None:
        strings: list[str] = []
        for arg in node.args:
            folded = _fold_string(arg, self.local_to_string)
            if folded is not None:
                strings.append(folded)
        for kw in node.keywords:
            if kw.arg is None:
                continue
            if kind == "patch_object_or_multiple" and kw.arg in BANNED:
                strings.append(kw.arg)
            folded = _fold_string(kw.value, self.local_to_string)
            if folded is not None:
                strings.append(folded)

        for banned in BANNED:
            if any(s.endswith(banned) for s in strings):
                self.findings.append(
                    Finding(self.relpath, self._qualname(), node.lineno, f"call:{kind}")
                )
                return

    def _check_attr_target(self, target: ast.AST, node: ast.stmt) -> None:
        targets = target.elts if isinstance(target, (ast.Tuple, ast.List)) else [target]
        for element in targets:
            if isinstance(element, ast.Attribute) and element.attr in BANNED:
                self.findings.append(
                    Finding(self.relpath, self._qualname(), node.lineno, "attr-assign")
                )

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_attr_target(target, node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_attr_target(node.target, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_attr_target(node.target, node)
        self.generic_visit(node)


def _scan_source(source: str, relpath: str) -> list[Finding]:
    tree = ast.parse(source)
    aliases = _AliasCollector()
    aliases.visit(tree)
    finder = _SpyFinder(
        relpath, aliases.import_map, aliases.local_to_dotted, aliases.local_to_string
    )
    finder.visit(tree)
    return finder.findings


def _scan_file(path: Path) -> list[Finding]:
    relpath = path.relative_to(_REPO_ROOT).as_posix()
    return _scan_source(path.read_text(), relpath)


# ---------------------------------------------------------------------------
# Real scan over the whole tree
# ---------------------------------------------------------------------------


def test_no_unallowlisted_native_read_spy_exists_in_the_suite() -> None:
    allowlist_keys = {(relpath, qualname) for relpath, qualname, _reason in ALLOWLIST}
    seen_keys: set[tuple[str, str]] = set()
    unlisted: list[Finding] = []

    self_relpath = Path(__file__).resolve().relative_to(_REPO_ROOT).as_posix()
    for path in sorted((_REPO_ROOT / "tests").rglob("*.py")):
        relpath = path.relative_to(_REPO_ROOT).as_posix()
        if relpath == self_relpath:
            continue
        for finding in _scan_file(path):
            key = (finding.relpath, finding.qualname)
            if key in allowlist_keys:
                seen_keys.add(key)
                continue
            unlisted.append(finding)

    assert not unlisted, "\n".join(
        f"{f.relpath}:{f.lineno}:{f.form} ({f.qualname}) is not allowlisted" for f in unlisted
    )

    stale = allowlist_keys - seen_keys
    assert not stale, f"stale allowlist entries with zero findings: {sorted(stale)}"


def test_the_allowlist_has_no_wildcards() -> None:
    for relpath, qualname, _reason in ALLOWLIST:
        assert "*" not in relpath
        assert "*" not in qualname


# ---------------------------------------------------------------------------
# Self-tests: evasion forms (each must be flagged) and negative controls
# ---------------------------------------------------------------------------

_FAKE_RELPATH = "tests/unit/_synthetic_not_on_allowlist.py"

_EVASION_SOURCES: dict[str, str] = {
    "S1": """
        def test_s1(monkeypatch, ParquetDataCatalog):
            monkeypatch.setattr(ParquetDataCatalog, "_read_feather_file", f)
        """,
    "S2": """
        def test_s2(ParquetDataCatalog):
            setattr(ParquetDataCatalog, "convert_stream_to_data", f)
        """,
    "S3": """
        def test_s3(catalog):
            setattr(catalog, "_read_feather_file", f)
        """,
    "S4": """
        def test_s4(monkeypatch, catalog):
            monkeypatch.setattr(type(catalog), "_read_feather_file", f)
        """,
    "S5": """
        def test_s5(mp, ParquetDataCatalog):
            C = ParquetDataCatalog
            mp.setattr(C, "convert_stream_to_data", f)
        """,
    "S6": """
        def test_s6(monkeypatch, C):
            NAME = "_read_feather_file"
            monkeypatch.setattr(C, NAME, f)
        """,
    "S7": """
        def test_s7(monkeypatch, C):
            monkeypatch.setattr(C, "_read_" + "feather_file", f)
        """,
    "S8": """
        from unittest.mock import patch
        def test_s8():
            patch(
                "nautilus_trader.persistence.catalog.parquet.ParquetDataCatalog._read_feather_file",
                f,
            )
        """,
    "S9": """
        from unittest.mock import patch as p
        def test_s9(C):
            p.object(C, "convert_stream_to_data")
        """,
    "S10": """
        from unittest import mock
        class TestS10:
            @mock.patch.object(ParquetDataCatalog, "_read_feather_file")
            def test_it(self):
                pass
        """,
    "S11": """
        def test_s11(mocker, C):
            mocker.patch.object(C, "_read_feather_file")
        """,
    "S12": """
        from unittest.mock import patch
        def test_s12(C):
            patch.multiple(C, _read_feather_file=f)
        """,
    "S13": """
        def test_s13(C):
            type.__setattr__(C, "_read_feather_file", f)
        """,
    "S14": """
        def test_s14(monkeypatch, C):
            sa = monkeypatch.setattr
            sa(C, "_read_feather_file", f)
        """,
    "S15": """
        def test_s15(catalog):
            catalog._read_feather_file = f
        """,
    "S16": """
        def test_s16(catalog):
            type(catalog).convert_stream_to_data = f
        """,
    "S17": """
        def test_s17(ParquetDataCatalog):
            C = ParquetDataCatalog
            C._read_feather_file = f
        """,
    "S18": """
        def test_s18(catalog, g):
            catalog._read_feather_file += g
        """,
    "S19a": """
        def test_s19a(catalog, f):
            a, catalog._read_feather_file = 1, f
        """,
    "S19b": """
        def test_s19b(catalog, f):
            catalog._read_feather_file: Any = f
        """,
    "S20": """
        def test_s20(mocker):
            mocker.patch("nautilus_trader.persistence.catalog.parquet.ParquetDataCatalog.convert_stream_to_data")
        """,
}

_NEGATIVE_SOURCES: dict[str, str] = {
    "N1": """
        def test_n1(catalog, p):
            catalog._read_feather_file(p)
        """,
    "N2": """
        def test_n2(ParquetDataCatalog, catalog):
            ParquetDataCatalog.convert_stream_to_data(catalog, "iid", QuoteTick)
        """,
    "N3": """
        def test_n3(ParquetDataCatalog):
            real_read = ParquetDataCatalog._read_feather_file
        """,
    "N4": """
        def test_n4(monkeypatch, quote_tape_ingest_cli, f):
            monkeypatch.setattr(quote_tape_ingest_cli, "read_feather_coalesced", f)
        """,
    "N5": """
        def test_n5(monkeypatch, quote_tape_ingest_cli, f):
            monkeypatch.setattr(quote_tape_ingest_cli, "_convert_stream_natively", f)
        """,
    "N6": '''
        def test_n6():
            """monkeypatch.setattr(ParquetDataCatalog, '_read_feather_file', f)"""
        ''',
}


@pytest.mark.parametrize("name", sorted(_EVASION_SOURCES))
def test_each_evasion_form_is_flagged(name: str) -> None:
    source = textwrap.dedent(_EVASION_SOURCES[name])
    findings = _scan_source(source, _FAKE_RELPATH)
    assert findings, f"evasion form {name} was not flagged:\n{source}"


@pytest.mark.parametrize("name", sorted(_NEGATIVE_SOURCES))
def test_each_negative_control_is_not_flagged(name: str) -> None:
    source = textwrap.dedent(_NEGATIVE_SOURCES[name])
    findings = _scan_source(source, _FAKE_RELPATH)
    assert not findings, f"negative control {name} was wrongly flagged: {findings}"


def test_a_banned_spy_in_a_sibling_function_of_an_allowlisted_file_is_still_reported() -> None:
    source = textwrap.dedent(
        """
        def test_no_path_calls_the_native_reader(monkeypatch, ParquetDataCatalog):
            monkeypatch.setattr(ParquetDataCatalog, "_read_feather_file", f)

        def test_a_sibling(monkeypatch, ParquetDataCatalog):
            monkeypatch.setattr(ParquetDataCatalog, "_read_feather_file", f)
        """
    )
    findings = _scan_source(source, "tests/unit/test_quote_tape_ingest_bounded_read.py")
    allowlist_keys = {(relpath, qualname) for relpath, qualname, _reason in ALLOWLIST}
    unlisted = [f for f in findings if (f.relpath, f.qualname) not in allowlist_keys]
    assert len(unlisted) == 1
    assert unlisted[0].qualname == "test_a_sibling"
