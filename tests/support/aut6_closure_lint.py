"""AUT-6 read allowlist for non-writer closures (plan r15 section 3.1, r10 AC6, r11 LOW-r11-5).

``read_allowlist_findings`` turns the closure check into an ALLOWLIST: in a non-writer module only
the named read-only calls of ``AUT6_READ_ALLOWLIST`` may be made from the I/O modules, ``open`` and
``os.open`` only in read forms, and no write-method call or dynamic-code builtin at all. Pure
functions of ``(path, source)``, so a test runs them over the real tree and over planted strings.
This complements ``capture_closure_lint`` (the per-function write-scope rows), not replaces it.
"""

from __future__ import annotations

import ast
from typing import Final

from breezy.persistence.autonomy.detector_catalog import (
    AUT6_READ_ALLOWLIST,
    AUT6_ROLLBACK_JOURNAL_STORES,
)
from tests.support.autonomy_scan import Finding

__all__ = [
    "IO_ROOTS",
    "read_allowlist_findings",
    "sqlite_findings",
    "wal_in_place_findings",
]

IO_ROOTS: Final[frozenset[str]] = frozenset(
    {"os", "shutil", "tempfile", "subprocess", "sqlite3", "fcntl", "socket", "ctypes", "importlib"}
)
WRITE_METHODS: Final[frozenset[str]] = frozenset(
    {"write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir", "rename", "symlink_to",
     "hardlink_to", "chmod", "truncate"}
)  # fmt: skip
DANGEROUS_BUILTINS: Final[frozenset[str]] = frozenset(
    {"exec", "eval", "compile", "__import__", "setattr", "delattr", "input", "breakpoint"}
)
READ_FLAGS: Final[frozenset[str]] = frozenset(
    {"O_RDONLY", "O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW"}
)
READ_MODES: Final[frozenset[str]] = frozenset({"r", "rb"})
_STD_STREAMS: Final[frozenset[str]] = frozenset({"sys.stdout", "sys.stderr"})


def _aliases(tree: ast.AST) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def _chain(expr: ast.expr) -> list[str] | None:
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if isinstance(expr, ast.Name):
        return [expr.id, *reversed(parts)]
    return None


def _resolved(call: ast.Call, aliases: dict[str, str]) -> str | None:
    chain = _chain(call.func)
    if chain is None or chain[0] not in aliases:
        return None
    return ".".join([aliases[chain[0]], *chain[1:]])


def _flags_are_read(expr: ast.expr) -> bool:
    """``os.O_RDONLY`` alone or OR-ed with CLOEXEC, DIRECTORY and NOFOLLOW."""
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        return _flags_are_read(expr.left) and _flags_are_read(expr.right)
    chain = _chain(expr)
    return chain is not None and len(chain) == 2 and chain[0] == "os" and chain[1] in READ_FLAGS


def _has_rdonly(expr: ast.expr) -> bool:
    if isinstance(expr, ast.BinOp):
        return _has_rdonly(expr.left) or _has_rdonly(expr.right)
    chain = _chain(expr)
    return chain == ["os", "O_RDONLY"]


def _open_mode_is_read(call: ast.Call) -> bool:
    """No mode (read), or a literal ``"r"`` / ``"rb"``; ``encoding`` and ``errors`` are fine."""
    index = 0 if isinstance(call.func, ast.Attribute) else 1  # Path.open(mode) vs open(p, mode)
    if len(call.args) > index:
        mode: ast.expr | None = call.args[index]
    else:
        mode = next((k.value for k in call.keywords if k.arg == "mode"), None)
    if any(k.arg is None for k in call.keywords):
        return False
    if mode is None:
        return True
    return isinstance(mode, ast.Constant) and mode.value in READ_MODES


def read_allowlist_findings(path: str, source: str) -> list[Finding]:
    """Every call in a non-writer module that is not on the read allowlist."""
    tree = ast.parse(source, filename=path)
    aliases = _aliases(tree)
    found: list[Finding] = []

    def hit(node: ast.AST, detail: str) -> None:
        found.append(Finding(path, getattr(node, "lineno", 0), "aut6_off_allowlist", detail))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _resolved(node, aliases)
        chain = _chain(node.func)
        if name is not None and name.split(".")[0] in IO_ROOTS:
            if name not in AUT6_READ_ALLOWLIST:
                hit(node, name)
            elif name == "os.open" and not (
                len(node.args) >= 2 and _flags_are_read(node.args[1]) and _has_rdonly(node.args[1])
            ):
                hit(node, "os.open flags")
            continue
        if chain == ["open"] and not _open_mode_is_read(node):
            hit(node, "open mode")
        elif chain is not None and len(chain) == 1 and chain[0] in DANGEROUS_BUILTINS:
            hit(node, chain[0])
        elif isinstance(node.func, ast.Attribute):
            owner = ".".join(chain[:-1]) if chain else ""
            if node.func.attr in WRITE_METHODS and owner not in _STD_STREAMS:
                hit(node, f".{node.func.attr}")
            elif node.func.attr == "open" and not _open_mode_is_read(node):
                hit(node, ".open mode")
    return found


def _connect_calls(tree: ast.AST) -> list[ast.Call]:
    aliases = _aliases(tree)
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _resolved(n, aliases) == "sqlite3.connect"
    ]


def sqlite_findings(path: str, source: str) -> list[Finding]:
    """Every ``sqlite3.connect`` must open a ``file:...?mode=ro`` URI and the module must issue
    ``PRAGMA query_only=ON`` (E-7 rule 3)."""
    tree = ast.parse(source, filename=path)
    calls = _connect_calls(tree)
    pragma = any(
        isinstance(n, ast.Constant) and isinstance(n.value, str) and "query_only=ON" in n.value
        for n in ast.walk(tree)
    )
    found: list[Finding] = []
    for call in calls:
        first = call.args[0] if call.args else None
        literal = isinstance(first, ast.Constant) and isinstance(first.value, str)
        uri_ok = any(
            k.arg == "uri" and isinstance(k.value, ast.Constant) and k.value.value is True
            for k in call.keywords
        )
        if not (literal and "mode=ro" in str(first.value) and uri_ok and pragma):  # type: ignore[union-attr]
            found.append(Finding(path, call.lineno, "aut6_sqlite_not_ro", "sqlite3.connect"))
    return found


def wal_in_place_findings(path: str, source: str) -> list[Finding]:
    """A ``sqlite3.connect`` whose first argument is not a literal naming a rollback-journal store
    opens a live WAL database in place (E-7a rule 3)."""
    found: list[Finding] = []
    for call in _connect_calls(ast.parse(source, filename=path)):
        first = call.args[0] if call.args else None
        named = isinstance(first, ast.Constant) and any(
            str(first.value).startswith(f"file:{store}") or first.value == store
            for store in AUT6_ROLLBACK_JOURNAL_STORES
        )
        if not named:
            found.append(Finding(path, call.lineno, "aut6_wal_in_place", "sqlite3.connect"))
    return found
