"""AUT-1 read-only closure lint (plan r12 section 3.15; E-7, E-7a rule 4; AUT-6 r9 AC6).

An AST ALLOWLIST over only the AUT-1 module globs (``AUT1_GLOBS``). Other owners' modules are judged
under their own tables. ``AUT1_WRITE_AUTHORITY`` lists, per module, the only places it may write
the filesystem, the literal subprocess argvs and the SQLite opens it may make. Anything not on its
row fails, and so does a judged module that has no row at all, so a new AUT-1 module cannot land
without a reviewed row.

Judged, per file:

* every filesystem write site ``find_write_sites`` knows (write-mode ``open`` / ``os.open``, a
  NON-LITERAL mode or flags, which fail closed, ``sqlite3.connect``, ``subprocess``, dynamic
  imports), allowed only inside the row's ``writes`` scopes, or, for a subprocess or SQLite open,
  with a literal first argument listed on the row;
* ``os.system``, ``os.popen``, ``os.exec*``, ``os.spawn*``, ``os.posix_spawn*``, ``ctypes`` and
  ``cffi``: never allowed;
* ``eval``, ``exec``, ``compile``, ``sys.modules``, any reference to the builtin ``open`` that is
  not a direct call (an alias, an argument) and any ``builtins.open``: never allowed (WP1-R3);
* a name imported from a cross-unit write module (``WRITE_MODULE_FUNCTIONS``): only when the row
  lists it in ``write_imports``. A non-writer therefore reaches such a module only through the
  read-only names it does not list here;
* every ``reason=`` keyword passed to a capture-record or refusal constructor (``REASON_SINKS``: the
  record classes, ``make_record``, and any callee named ``*Record``, ``*Refuse``, ``*Refused`` or
  ``*Veto``): a module-level constant (an UPPER_CASE name or attribute), never an inline literal or
  a computed value. A read-side view that copies a stored reason is not a sink.

The lint is non-vacuous: each row names the minimum number of call sites its file must hold, and
``lint_source`` is a pure function so a test can plant a violation in a scratch source string.
"""

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final, NamedTuple

from tests.support.autonomy_scan import Finding, relative_path, walk_with_scope
from tests.support.autonomy_write_scan import find_write_sites
from tests.support.entry_points import SRC_DIR

__all__ = [
    "AUT1_GLOBS",
    "AUT1_WRITE_AUTHORITY",
    "REASON_SINKS",
    "WRITE_MODULE_FUNCTIONS",
    "AuthorityRow",
    "aut1_files",
    "lint_files",
    "lint_source",
    "module_of",
]

_BREEZY: Final[Path] = SRC_DIR / "breezy"
_PERSISTENCE: Final = "breezy.persistence.autonomy"

#: The only places this lint walks (section 3.15), as ``src/breezy``-relative globs.
AUT1_GLOBS: Final[tuple[str, ...]] = (
    "persistence/autonomy/capture_*.py",
    "strategy/autonomy_capture/*.py",
    "strategy/forecast_quantile_ladder/capture_adapter.py",
    "strategy/forecast_quantile_ladder/plugin.py",
    "adapters/polymarket_us/recorder_watchdog.py",
    "runtime/capture_*.py",
    "analysis/capture_*.py",
)

#: Cross-unit modules that own writes, and the names of theirs that write. A module may import one
#: of these names only when its row lists it. Plain ``import <module>`` of one needs ``"*"``.
WRITE_MODULE_FUNCTIONS: Final[Mapping[str, frozenset[str]]] = {
    f"{_PERSISTENCE}.single_read": frozenset(
        {"write_once", "write_once_tmpfile", "replace_atomic", "ensure_dir"}
    ),
    f"{_PERSISTENCE}.registry_store": frozenset({"*"}),
    f"{_PERSISTENCE}.hwm": frozenset({"write_monotone"}),
    f"{_PERSISTENCE}.family_bytes": frozenset({"write_root_copy"}),
}

#: Callees whose ``reason=`` keyword EMITS a reason (section 3.15).
REASON_SINKS: Final[frozenset[str]] = frozenset(
    {
        "make_record",
        "DecisionRecord",
        "OrderEventRecord",
        "DetectorEvent",
        "CaptureHeartbeat",
        "FrameCopy",
        "Refuse",
        "EntryVeto",
        "NotExecutable",
        "NotDPlus1",
        "TrySubmit",
    }
)
_REASON_SINK_SUFFIXES: Final[tuple[str, ...]] = ("Record", "Refuse", "Refused", "Veto")
_FORBIDDEN_OS: Final[frozenset[str]] = frozenset({"system", "popen"})
_FORBIDDEN_OS_PREFIXES: Final[tuple[str, ...]] = ("exec", "spawn", "posix_spawn")
_FORBIDDEN_MODULES: Final[frozenset[str]] = frozenset({"ctypes", "cffi"})


class AuthorityRow(NamedTuple):
    """What one AUT-1 module may do. Every field defaults to nothing."""

    module: str
    #: Function qualified-name prefixes inside which write sites are allowed (``"*"``: anywhere).
    writes: tuple[str, ...] = ()
    #: Names a module may import from ``WRITE_MODULE_FUNCTIONS`` modules.
    write_imports: frozenset[str] = frozenset()
    #: Literal argvs a ``subprocess`` call may pass as its first argument.
    argvs: tuple[tuple[str, ...], ...] = ()
    #: Literal first arguments an ``sqlite3.connect`` may pass.
    sqlite: tuple[str, ...] = ()
    #: The file must hold at least this many call sites, or the row is vacuous.
    min_calls: int = 1


def _core(name: str, **kw: Any) -> AuthorityRow:
    return AuthorityRow(f"{_PERSISTENCE}.{name}", **kw)


#: Rows for the AUT-1 modules that exist. A module that lands later adds its row in its own commit.
#: Writers (section 3.15): the trade-node capture closure. Its stream bytes are written ONLY by the
#: native ``StreamingFeatherWriter`` owned by ``CaptureStreamWriter``, so the AST holds no write
#: site; ``capture_stream`` creates its own private directory through ``ensure_dir`` and
#: ``capture_epoch`` publishes the epoch through ``write_once``. Every other module is a non-writer.
AUT1_WRITE_AUTHORITY: Final[tuple[AuthorityRow, ...]] = (
    _core("capture_publish", min_calls=18),
    _core("capture_stream", write_imports=frozenset({"ensure_dir"}), min_calls=28),
    _core("capture_epoch", write_imports=frozenset({"write_once", "ensure_dir"}), min_calls=20),
    _core("capture_records", min_calls=2),
    _core("capture_ids", min_calls=10),
    _core("capture_on_change", min_calls=4),
    _core("capture_alerts", min_calls=5),
    _core("capture_schedule", min_calls=4),
    _core("capture_reader", min_calls=90),
    AuthorityRow("breezy.analysis.capture_forecast_ref", min_calls=6),
    AuthorityRow("breezy.strategy.autonomy_capture.guarded_strategy", min_calls=80),
    AuthorityRow("breezy.strategy.forecast_quantile_ladder.capture_adapter", min_calls=45),
    AuthorityRow("breezy.strategy.forecast_quantile_ladder.plugin", min_calls=8),
    AuthorityRow("breezy.adapters.polymarket_us.recorder_watchdog", min_calls=60),
    AuthorityRow(
        "breezy.runtime.capture_recorder_hook_cli",
        writes=("_open_child_dir", "_write_once", "_atomic_replace", "_acquire_lock"),
        min_calls=80,
    ),
)


def aut1_files(src_root: Path = _BREEZY) -> list[Path]:
    found: set[Path] = set()
    for pattern in AUT1_GLOBS:
        found.update(p for p in src_root.glob(pattern) if p.name != "__init__.py")
    return sorted(found)


def module_of(path: Path) -> str:
    relative = path.resolve().relative_to(_BREEZY.resolve()).with_suffix("")
    return ".".join(("breezy", *relative.parts))


def _finding(path: str, node: ast.AST, rule: str, detail: str, scope: str = "") -> Finding:
    return Finding(path, getattr(node, "lineno", 0), rule, detail, scope)


def _in_scope(scope: str, allowed: Iterable[str]) -> bool:
    return any(a == "*" or scope == a or scope.startswith(f"{a}.") for a in allowed)


def _literal_argv(call: ast.Call) -> tuple[str, ...] | None:
    first = call.args[0] if call.args else None
    if isinstance(first, ast.List | ast.Tuple) and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in first.elts
    ):
        return tuple(str(e.value) for e in first.elts if isinstance(e, ast.Constant))
    return None


def _literal_first_arg(call: ast.Call) -> str | None:
    first = call.args[0] if call.args else None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _calls_at(tree: ast.AST) -> dict[int, list[ast.Call]]:
    by_line: dict[int, list[ast.Call]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            by_line.setdefault(node.lineno, []).append(node)
    return by_line


def _site_findings(path: str, tree: ast.Module, source: str, row: AuthorityRow) -> list[Finding]:
    calls = _calls_at(tree)
    out: list[Finding] = []
    for site in find_write_sites(path, source):
        detail = site.detail
        if detail.startswith("subprocess.") or detail == "subprocess":
            argvs = {_literal_argv(c) for c in calls.get(site.lineno, [])}
            if any(argv in row.argvs for argv in argvs if argv is not None):
                continue
        elif detail == "sqlite3.connect":
            literals = {_literal_first_arg(c) for c in calls.get(site.lineno, [])}
            if any(lit in row.sqlite for lit in literals if lit is not None):
                continue
        elif _in_scope(site.scope, row.writes):
            continue
        out.append(Finding(path, site.lineno, "aut1_write_authority", detail, site.scope))
    return out


def _alias_for_os(tree: ast.Module) -> set[str]:
    names = {"os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.asname for a in node.names if a.name == "os" and a.asname)
    return names


def _forbidden_findings(path: str, tree: ast.Module) -> list[Finding]:
    out: list[Finding] = []
    os_names = _alias_for_os(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(
                _finding(path, node, "aut1_forbidden", f"import {a.name}")
                for a in node.names
                if a.name.split(".")[0] in _FORBIDDEN_MODULES
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in _FORBIDDEN_MODULES:
                out.append(_finding(path, node, "aut1_forbidden", f"from {node.module}"))
            if node.module == "os":
                out.extend(
                    _finding(path, node, "aut1_forbidden", f"os.{a.name}")
                    for a in node.names
                    if _forbidden_os_name(a.name)
                )
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in os_names
            and _forbidden_os_name(node.attr)
        ):
            out.append(_finding(path, node, "aut1_forbidden", f"os.{node.attr}"))
    return out


_FORBIDDEN_BUILTIN_CALLS: Final[frozenset[str]] = frozenset({"eval", "exec", "compile"})


def _module_aliases(tree: ast.Module, module: str) -> set[str]:
    names = {module}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.asname for a in node.names if a.name == module and a.asname)
    return names


def _dynamic_findings(path: str, tree: ast.Module) -> list[Finding]:
    """``eval`` / ``exec`` / ``compile``, ``sys.modules`` and the builtin ``open`` as a value."""
    out: list[Finding] = []
    sys_names = _module_aliases(tree, "sys")
    builtins_names = _module_aliases(tree, "builtins")
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in _FORBIDDEN_BUILTIN_CALLS:
                out.append(_finding(path, node, "aut1_forbidden", node.id))
            elif node.id == "open" and id(node) not in called:
                out.append(_finding(path, node, "aut1_forbidden", "open as a value"))
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in sys_names and node.attr == "modules":
                out.append(_finding(path, node, "aut1_forbidden", "sys.modules"))
            elif node.value.id in builtins_names and node.attr == "open":
                out.append(_finding(path, node, "aut1_forbidden", "builtins.open"))
        elif isinstance(node, ast.ImportFrom) and node.module in {"sys", "builtins"}:
            out.extend(
                _finding(path, node, "aut1_forbidden", f"from {node.module} import {a.name}")
                for a in node.names
                if (node.module, a.name) in {("sys", "modules"), ("builtins", "open")}
            )
    return out


def _forbidden_os_name(name: str) -> bool:
    return name in _FORBIDDEN_OS or name.startswith(_FORBIDDEN_OS_PREFIXES)


def _import_findings(path: str, tree: ast.Module, row: AuthorityRow) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in WRITE_MODULE_FUNCTIONS and "*" not in row.write_imports:
                    out.append(_finding(path, node, "aut1_write_import", f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.extend(_from_import_findings(path, node, row))
    return out


def _from_import_findings(path: str, node: ast.ImportFrom, row: AuthorityRow) -> list[Finding]:
    out: list[Finding] = []
    write_names = WRITE_MODULE_FUNCTIONS.get(node.module or "")
    for alias in node.names:
        dotted = f"{node.module}.{alias.name}"
        if dotted in WRITE_MODULE_FUNCTIONS and "*" not in row.write_imports:
            out.append(_finding(path, node, "aut1_write_import", f"import module {dotted}"))
        if write_names is None or "*" in row.write_imports:
            continue
        if (alias.name in write_names or "*" in write_names or alias.name == "*") and (
            alias.name not in row.write_imports
        ):
            out.append(_finding(path, node, "aut1_write_import", dotted))
    return out


def _module_constants(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
    return names


def _is_constant_reference(value: ast.expr, constants: set[str]) -> bool:
    if isinstance(value, ast.Name):
        return value.id in constants and value.id.isupper()
    if isinstance(value, ast.Attribute):
        return value.attr.isupper()
    return False


def _callee_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _is_reason_sink(call: ast.Call) -> bool:
    name = _callee_name(call)
    return name in REASON_SINKS or name.endswith(_REASON_SINK_SUFFIXES)


def _reason_findings(path: str, tree: ast.Module) -> list[Finding]:
    constants = _module_constants(tree)
    out: list[Finding] = []
    for node, scope in walk_with_scope(tree):
        if not isinstance(node, ast.Call) or not _is_reason_sink(node):
            continue
        for keyword in node.keywords:
            if keyword.arg == "reason" and not _is_constant_reference(keyword.value, constants):
                out.append(_finding(path, keyword.value, "aut1_reason_constant", "reason=", scope))
    return out


def _call_count(tree: ast.AST) -> int:
    return sum(isinstance(n, ast.Call) for n in ast.walk(tree))


def lint_source(
    path: str,
    source: str,
    *,
    module: str,
    authority: Iterable[AuthorityRow] = AUT1_WRITE_AUTHORITY,
) -> list[Finding]:
    """Every violation of the allowlist in ``source``, a file of ``module``. Pure."""
    tree = ast.parse(source, filename=path)
    rows = {row.module: row for row in authority}
    row = rows.get(module)
    if row is None:
        return [Finding(path, 1, "aut1_no_authority_row", f"no AUT1_WRITE_AUTHORITY row: {module}")]
    findings = [
        *_site_findings(path, tree, source, row),
        *_forbidden_findings(path, tree),
        *_dynamic_findings(path, tree),
        *_import_findings(path, tree, row),
        *_reason_findings(path, tree),
    ]
    if _call_count(tree) < row.min_calls:
        findings.append(
            Finding(path, 1, "aut1_vacuous", f"fewer than {row.min_calls} call sites judged")
        )
    return findings


def lint_files(
    files: Iterable[Path], authority: Iterable[AuthorityRow] = AUT1_WRITE_AUTHORITY
) -> list[Finding]:
    rows = tuple(authority)
    out: list[Finding] = []
    for file in files:
        out.extend(
            lint_source(
                relative_path(file),
                file.read_text(encoding="utf-8"),
                module=module_of(file),
                authority=rows,
            )
        )
    return out
