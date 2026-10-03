"""Filesystem write-site detection for the one-writer gate (ARCH-0 seam A; L-50; ruling A4-R2).

``find_write_sites(path, source)`` returns every place ``source`` can write the filesystem, with no
allowlist applied. One alias map is built from ``Import`` and ``ImportFrom`` for the tracked
modules, and every receiver is resolved through it, so ``import os as o``, ``from shutil import
copy as c`` and ``from pyarrow.parquet import write_table`` resolve to their canonical names.

A write site is:

* any *reference* (not only a call) to a write function of a tracked module, so ``w = os.replace``
  counts;
* ``getattr(<tracked module>, ...)``, ``__import__``, ``importlib.*`` and ``from <tracked> import
  *``, because each can name a write function the scan cannot see;
* ``os.open`` with a write flag or flags it cannot resolve, ``os.fdopen`` with a non-read or
  non-literal mode, ``sqlite3.connect``, ``logging.FileHandler`` and its ``handlers`` cousins, any
  ``subprocess.*``;
* ``open`` (builtin, ``io``, ``gzip``, ``codecs``, ``Path.open``) in a write, append, exclusive or
  update mode, with a non-literal mode, or with ``**kwargs`` (fail closed);
* the ``Path`` mutators and the dataframe and array writers, matched by method name because their
  receivers are untyped.

Out of scope on purpose: ``json.dump`` and ``pickle.dump`` to a passed-in file object. The opener
of that object is the write site, and it is judged here.
"""

from __future__ import annotations

import ast
import re
from typing import Final

from tests.support.autonomy_scan import Finding, walk_with_scope

__all__ = ["TRACKED_MODULES", "find_write_sites"]

TRACKED_MODULES: Final = frozenset(
    {
        "os", "shutil", "tempfile", "pathlib", "io", "builtins", "gzip", "codecs", "pyarrow",
        "numpy", "sqlite3", "logging", "subprocess", "importlib",
    }
)  # fmt: skip

_OS_WRITES: Final = frozenset(
    {
        "link", "symlink", "replace", "rename", "renames", "mkdir", "makedirs", "unlink", "remove",
        "rmdir", "removedirs", "truncate", "ftruncate", "write", "writev", "pwrite", "pwritev",
        "copy_file_range", "sendfile", "posix_fallocate", "chmod", "fchmod", "chown", "fchown",
        "lchown", "utime", "mkfifo", "mknod",
    }
)  # fmt: skip
_SHUTIL_WRITES: Final = frozenset(
    {"copy", "copy2", "copyfile", "copyfileobj", "copytree", "move", "rmtree", "make_archive",
     "unpack_archive", "chown"}
)  # fmt: skip
_TEMPFILE_WRITES: Final = frozenset(
    {"mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile",
     "TemporaryDirectory"}
)  # fmt: skip
_NUMPY_WRITES: Final = frozenset({"save", "savez", "savez_compressed", "savetxt", "memmap"})
_LOGGING_HANDLERS: Final = frozenset(
    {
        "logging.FileHandler", "logging.handlers.WatchedFileHandler",
        "logging.handlers.RotatingFileHandler", "logging.handlers.TimedRotatingFileHandler",
    }
)  # fmt: skip
_PYARROW_WRITERS: Final = frozenset(
    {"ParquetWriter", "CSVWriter", "new_file", "new_stream", "output_stream", "OSFile"}
)
#: Method names that mutate regardless of arguments; receivers are untyped, so matched by name.
#: ``replace`` is separate because ``str.replace`` exists: ``Path.replace`` takes one argument.
_PATH_MUTATORS: Final = frozenset(
    {"write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir", "rename", "symlink_to",
     "hardlink_to", "chmod", "lchmod"}
)  # fmt: skip
_DATA_WRITERS: Final = frozenset(
    {"to_csv", "to_parquet", "to_json", "to_feather", "write_table", "write_feather",
     "write_dataset", "save", "savez", "savez_compressed", "savetxt"}
)  # fmt: skip
_WRITE_OS_FLAGS: Final = frozenset(
    {"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC", "O_EXCL", "O_TMPFILE"}
)
_MODE_STRING_RE: Final = re.compile(r"\A[rwxabt+U]{1,4}\Z")
_MAX_ALIAS_DEPTH: Final = 8


def _qualified_write(name: str) -> bool:
    """True when the canonical dotted ``name`` is a write function of a tracked module."""
    head, _, tail = name.rpartition(".")
    if head == "os":
        return tail in _OS_WRITES
    if head == "shutil":
        return tail in _SHUTIL_WRITES
    if head == "tempfile":
        return tail in _TEMPFILE_WRITES
    if head == "numpy":
        return tail in _NUMPY_WRITES
    if name == "sqlite3.connect" or name in _LOGGING_HANDLERS:
        return True
    if name.startswith("subprocess."):
        return True
    if name.startswith("pyarrow."):
        return "write" in tail or tail in _PYARROW_WRITERS
    return False


def _alias_map(tree: ast.AST) -> tuple[dict[str, str], list[int]]:
    """Local name -> canonical dotted name for tracked imports, and star-import line numbers."""
    aliases: dict[str, str] = {}
    stars: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in TRACKED_MODULES:
                    continue
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    aliases[top] = top
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.split(".")[0] in TRACKED_MODULES
        ):
            for alias in node.names:
                if alias.name == "*":
                    stars.append(node.lineno)
                else:
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases, stars


def _dotted(expr: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(expr, ast.Name):
        return aliases.get(expr.id, expr.id)
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value, aliases)
        return f"{base}.{expr.attr}" if base is not None else None
    return None


def _is_tracked(expr: ast.AST, aliases: dict[str, str]) -> bool:
    dotted = _dotted(expr, aliases)
    return dotted is not None and dotted.split(".")[0] in TRACKED_MODULES


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    constants: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
        ):
            constants[node.target.id] = node.value
    return constants


def _os_flags(
    expr: ast.expr, constants: dict[str, ast.expr], depth: int = 0
) -> tuple[set[str], bool]:
    """``os.O_*`` names an ``os.open`` flag expression uses, and whether any part is opaque."""
    if depth > _MAX_ALIAS_DEPTH:
        return set(), True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        left, left_opaque = _os_flags(expr.left, constants, depth + 1)
        right, right_opaque = _os_flags(expr.right, constants, depth + 1)
        return left | right, left_opaque or right_opaque
    if isinstance(expr, ast.Attribute) and expr.attr.startswith("O_"):
        return {expr.attr}, False
    if isinstance(expr, ast.Name):
        if expr.id in constants:
            return _os_flags(constants[expr.id], constants, depth + 1)
        if expr.id.startswith("O_"):
            return {expr.id}, False
    if isinstance(expr, ast.Constant) and expr.value == 0:
        return set(), False  # O_RDONLY
    return set(), True


def _mode_reason(call: ast.Call, *, mode_index: int, label: str) -> str | None:
    """A reason when an ``open``-like call may write, is not statically a read, or hides kwargs."""
    if any(kw.arg is None for kw in call.keywords):
        return f"{label} with **kwargs"
    for arg in call.args[:2]:
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and _MODE_STRING_RE.match(arg.value)
            and any(ch in arg.value for ch in "wax+")
        ):
            return f"{label} mode {arg.value!r}"
    mode_kw = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if mode_kw is not None:
        if not (isinstance(mode_kw, ast.Constant) and isinstance(mode_kw.value, str)):
            return f"{label} mode is not a literal"
        if any(ch in mode_kw.value for ch in "wax+"):
            return f"{label} mode {mode_kw.value!r}"
    if len(call.args) > mode_index and not isinstance(call.args[mode_index], ast.Constant):
        return f"{label} mode is not a literal"
    return None


def _os_open_reason(call: ast.Call, constants: dict[str, ast.expr]) -> str | None:
    flag_arg = call.args[1] if len(call.args) > 1 else None
    flags_expr = flag_arg or next((kw.value for kw in call.keywords if kw.arg == "flags"), None)
    if flags_expr is None:
        return None
    names, opaque = _os_flags(flags_expr, constants)
    if names & _WRITE_OS_FLAGS:
        return f"os.open flags {sorted(names & _WRITE_OS_FLAGS)}"
    return "os.open flags are not statically resolvable" if opaque else None


def _call_reason(
    call: ast.Call, aliases: dict[str, str], constants: dict[str, ast.expr]
) -> str | None:
    func = call.func
    dotted = _dotted(func, aliases)
    if dotted == "os.open":
        return _os_open_reason(call, constants)
    if dotted == "os.fdopen":
        return _mode_reason(call, mode_index=1, label="os.fdopen")
    if dotted == "getattr" and call.args and _is_tracked(call.args[0], aliases):
        return "getattr on a tracked module"
    if dotted == "__import__" or (dotted or "").startswith("importlib."):
        return f"dynamic import {dotted}"
    if dotted in {"open", "builtins.open", "io.open", "gzip.open", "codecs.open"}:
        return _mode_reason(call, mode_index=1, label="open")
    if isinstance(func, ast.Attribute) and not _qualified_write(dotted or ""):
        name = func.attr  # a qualified write is reported once, as a reference
        if name == "open":
            return _mode_reason(call, mode_index=0, label="Path.open")
        if name in _PATH_MUTATORS:
            return f".{name}()"
        if name == "replace" and len(call.args) == 1 and not call.keywords:
            return ".replace(target)"
        if name in _DATA_WRITERS:
            return f".{name}()"
    return None


def find_write_sites(path: str, source: str) -> list[Finding]:
    """Every filesystem write site in ``source`` (unfiltered by any allowlist)."""
    tree = ast.parse(source, filename=path)
    aliases, stars = _alias_map(tree)
    constants = _module_constants(tree)
    findings = [
        Finding(path, line, "write_site", "star import of a tracked module") for line in stars
    ]
    for node, scope in walk_with_scope(tree):
        if isinstance(node, ast.Call):
            reason = _call_reason(node, aliases, constants)
        elif isinstance(node, ast.Attribute | ast.Name) and isinstance(node.ctx, ast.Load):
            dotted = _dotted(node, aliases)
            reason = dotted if dotted is not None and _qualified_write(dotted) else None
        else:
            continue
        if reason is not None:
            findings.append(Finding(path, node.lineno, "write_site", reason, scope))
    return findings
