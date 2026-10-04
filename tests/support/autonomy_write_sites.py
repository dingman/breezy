"""The AC6 read-allowlist predicate and the module-constant ``cache_dir`` predicate.

AUT-6 ruling AC6 replaced a growing denylist of write constructs with an
**allowlist**: in a non-writer closure the only permitted I/O calls are named
read-only functions, and every other call to a builtin, ``os``, ``io``, a
``pathlib`` write method, ``shutil``, ``subprocess``, ``multiprocessing`` or an
asyncio subprocess function is a write site. This module is that predicate, made
reusable so ARCH-0's ``SHARED_WRITE_SITES`` and the consumers' closure lints agree.

``cache_dir_is_own_module_constant`` is B-R2(a) (erratum E-7e(a)): a consumer may
admit the shared snapshot sites only when every snapshot call passes ``cache_dir=``
a module-level ``Final`` constant of its own module.

Test-support code only: it parses source, it never imports or runs it.
"""

from __future__ import annotations

import ast
from typing import Final

from breezy.runtime.autonomy_sandbox.write_sites import WriteSite

MODULE_LEVEL: Final = "<module>"
#: ``os`` calls that only observe. ``os.open`` is judged by its flags, below.
READ_ONLY_OS_CALLS: Final[frozenset[str]] = frozenset(
    {
        "os.stat",
        "os.lstat",
        "os.fstat",
        "os.statvfs",
        "os.fstatvfs",
        "os.scandir",
        "os.listdir",
        "os.readlink",
        "os.access",
        "os.fspath",
        "os.fsencode",
        "os.fsdecode",
        "os.getcwd",
        "os.getpid",
        "os.getppid",
        "os.getuid",
        "os.geteuid",
        "os.getgid",
        "os.getegid",
        "os.getenv",
        "os.environ.get",
        "os.close",
        "os.read",
        "os.strerror",
        "os.urandom",
    }
)
READ_ONLY_OPEN_FLAGS: Final[frozenset[str]] = frozenset(
    {"O_RDONLY", "O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_PATH", "O_NONBLOCK", "O_NOCTTY"}
)
READ_ONLY_MODES: Final[frozenset[str]] = frozenset({"r", "rb", "rt", "br", "tr"})
HARMLESS_IO_CALLS: Final[frozenset[str]] = frozenset({"io.StringIO", "io.BytesIO"})
#: Roots whose every call is a write site (with the exceptions named above and below).
WRITE_CAPABLE_ROOTS: Final[frozenset[str]] = frozenset(
    {"os", "io", "shutil", "subprocess", "multiprocessing"}
)
WRITE_BUILTINS: Final[frozenset[str]] = frozenset({"exec", "eval", "compile", "__import__"})
ASYNCIO_PROCESS_PREFIXES: Final = ("asyncio.create_subprocess", "asyncio.subprocess")
#: Method names that write regardless of the receiver. ``open`` is judged by its mode.
WRITE_METHODS: Final[frozenset[str]] = frozenset(
    {
        "write_text",
        "write_bytes",
        "mkdir",
        "touch",
        "unlink",
        "rmdir",
        "symlink_to",
        "hardlink_to",
        "chmod",
        "lchmod",
        "rename",
        "truncate",
    }
)
PATH_CONSTRUCTORS: Final[frozenset[str]] = frozenset({"Path", "PurePath", "PosixPath"})
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> the dotted module path it stands for, from every import statement."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.asname:
                    aliases[item.asname] = item.name
                else:
                    aliases[item.name.split(".")[0]] = item.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _dotted(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """The dotted name of a Name/Attribute chain rooted at a plain name, else ``None``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    root = aliases.get(node.id, node.id)
    return ".".join([root, *reversed(parts)])


def _argument(call: ast.Call, position: int, keyword: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == keyword:
            return kw.value
    return call.args[position] if len(call.args) > position else None


def _flag_names(node: ast.expr, aliases: dict[str, str]) -> list[str] | None:
    """The ``os.O_*`` names OR-ed together, or ``None`` if the expression is anything else."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, right = _flag_names(node.left, aliases), _flag_names(node.right, aliases)
        return None if left is None or right is None else left + right
    dotted = _dotted(node, aliases)
    if dotted is not None and dotted.startswith("os.O_"):
        return [dotted.removeprefix("os.")]
    return None


def _open_flags_are_read_only(call: ast.Call, aliases: dict[str, str]) -> bool:
    flags = _argument(call, 1, "flags")
    names = _flag_names(flags, aliases) if flags is not None else None
    return names is not None and set(names) <= READ_ONLY_OPEN_FLAGS


def _mode_is_read_only(mode: ast.expr | None) -> bool:
    if mode is None:
        return True
    return isinstance(mode, ast.Constant) and mode.value in READ_ONLY_MODES


def _sqlite_is_read_only(call: ast.Call) -> bool:
    target = call.args[0] if call.args else None
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return "mode=ro" in target.value
    if isinstance(target, ast.JoinedStr):
        return any(
            isinstance(part, ast.Constant) and "mode=ro" in str(part.value)
            for part in target.values
        )
    return False


def _module_call_write(name: str, call: ast.Call, aliases: dict[str, str]) -> bool:
    """Whether a call to the dotted ``name`` (rooted at a known module) writes."""
    root = name.split(".")[0]
    if name == "os.open":
        return not _open_flags_are_read_only(call, aliases)
    if name == "io.open":
        return not _mode_is_read_only(_argument(call, 1, "mode"))
    if root == "os":
        return name not in READ_ONLY_OS_CALLS and not name.startswith("os.path.")
    if root == "io":
        return name not in HARMLESS_IO_CALLS
    if root == "sqlite3":
        return name == "sqlite3.connect" and not _sqlite_is_read_only(call)
    if root == "asyncio":
        return name.startswith(ASYNCIO_PROCESS_PREFIXES)
    return root in WRITE_CAPABLE_ROOTS


def _method_write(func: ast.Attribute, call: ast.Call) -> str | None:
    attr = func.attr
    if attr in WRITE_METHODS:
        return attr
    if attr == "open" and not _mode_is_read_only(_argument(call, 0, "mode")):
        return attr
    receiver = func.value
    if attr == "replace" and isinstance(receiver, ast.Call):
        built = receiver.func
        built_name = built.id if isinstance(built, ast.Name) else getattr(built, "attr", "")
        if built_name in PATH_CONSTRUCTORS:
            return attr
    return None


def _write_call_name(call: ast.Call, aliases: dict[str, str]) -> str | None:
    """The reported name if ``call`` is not on the read allowlist, else ``None``."""
    func = call.func
    dotted = _dotted(func, aliases)
    if isinstance(func, ast.Name) and dotted is not None and "." not in dotted:
        if dotted == "open":
            return None if _mode_is_read_only(_argument(call, 1, "mode")) else "open"
        return dotted if dotted in WRITE_BUILTINS else None
    if dotted is not None and dotted.split(".")[0] in {
        *WRITE_CAPABLE_ROOTS,
        "sqlite3",
        "asyncio",
    }:
        return dotted if _module_call_write(dotted, call, aliases) else None
    return _method_write(func, call) if isinstance(func, ast.Attribute) else None


class _Scanner(ast.NodeVisitor):
    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = aliases
        self.scope: list[str] = []
        self.sites: list[tuple[str, str]] = []

    def _scoped(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scoped(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        name = _write_call_name(node, self.aliases)
        if name is not None:
            self.sites.append((".".join(self.scope) or MODULE_LEVEL, name))
        self.generic_visit(node)


def scan_write_sites(module: str, source: str) -> frozenset[WriteSite]:
    """Every call in ``source`` off the AC6 read allowlist, as (module, function, call)."""
    tree = ast.parse(source)
    scanner = _Scanner(_aliases(tree))
    scanner.visit(tree)
    return frozenset(WriteSite(module, function, call) for function, call in scanner.sites)


# --- cache_dir_is_own_module_constant ----------------------------------------------


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _enclosing_functions(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> list[ast.AST]:
    found: list[ast.AST] = []
    while node in parents:
        node = parents[node]
        if isinstance(node, _FUNCTION_NODES):
            found.append(node)
    return found


def _bound_in_function(function: ast.AST, name: str) -> bool:
    args = getattr(function, "args", None)
    if args is not None:
        params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        params += [a for a in (args.vararg, args.kwarg) if a is not None]
        if any(param.arg == name for param in params):
            return True
    return any(
        isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Store)
        for n in ast.walk(function)
    )


def _is_final(annotation: ast.expr) -> bool:
    node = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return (isinstance(node, ast.Name) and node.id == "Final") or (
        isinstance(node, ast.Attribute) and node.attr == "Final"
    )


def _module_final_constants(module_ast: ast.Module) -> set[str]:
    return {
        node.target.id
        for node in module_ast.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.value is not None
        and _is_final(node.annotation)
    }


def cache_dir_is_own_module_constant(call: ast.Call, module_ast: ast.Module) -> bool:
    """True iff ``call`` passes ``cache_dir=NAME`` where NAME is this module's own ``Final``.

    A literal, an f-string, a call, an attribute, a function parameter, a local that
    shadows the constant, a non-``Final`` module variable and an imported name are all
    refused, and so is a positional ``cache_dir``.
    """
    value = next((kw.value for kw in call.keywords if kw.arg == "cache_dir"), None)
    if not isinstance(value, ast.Name):
        return False
    functions = _enclosing_functions(call, _parents(module_ast))
    if any(_bound_in_function(function, value.id) for function in functions):
        return False
    return value.id in _module_final_constants(module_ast)
