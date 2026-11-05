"""The symlink hops the sandbox must recreate for the venv interpreter (B11, ruling B11-R1).

The wrapper hides the passwd home behind a tmpfs and re-binds only the repo, the python
prefix and the data root. A venv interpreter (``<repo>/.venv/bin/python3``) and the
``pyvenv.cfg`` ``home`` directory reach the base python through symlinks; any hop that lies
under the home but outside those binds would dangle in the sandbox. ``interpreter_symlinks``
walks both paths component by component and returns each such hop as ``(link, readlink)``
for ``bwrap --symlink`` (not a bind: it widens no mount). It reads the host, makes no
change, and fails closed: a hop whose resolution leaves the bound python prefix, a loop,
or more than ``MAX_HOPS`` hops raises ``InterpreterLinkError``.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Final

from breezy.runtime.autonomy_sandbox.table import SandboxRoots

MAX_HOPS: Final = 8
VENV_DIR: Final = ".venv"
PYVENV_CFG: Final = "pyvenv.cfg"
_PYVENV_HOME_KEY: Final = "home"
_MAX_CFG_BYTES: Final = 65536


class InterpreterLinkError(ValueError):
    """A hop the sandbox cannot safely recreate (outside the prefix, a loop, too many hops)."""


def _pyvenv_home(cfg: Path) -> Path | None:
    """The ``home`` CPython would read (``site.py``: strip, lowercase keys, last wins).

    ``None`` when there is no ``pyvenv.cfg``; ``InterpreterLinkError`` when it exists but
    cannot be read or yields no absolute ``home``.
    """
    try:
        with cfg.open("rb") as handle:
            text = handle.read(_MAX_CFG_BYTES).decode("utf-8", "replace")
    except FileNotFoundError:
        return None
    except OSError:
        raise InterpreterLinkError("cfg_unreadable") from None
    home = ""
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == _PYVENV_HOME_KEY:
            home = value.strip()
    if not home.startswith("/"):
        raise InterpreterLinkError("cfg_home")
    return Path(home)


def _real(path: Path) -> Path:
    return Path(os.path.realpath(path))


class _Scope:
    """Where a hop may be recreated: under the hidden home, outside every bound path."""

    def __init__(self, roots: SandboxRoots, excluded: Iterable[Path]) -> None:
        bound = {*excluded, roots.data_root}
        self.bound = {*bound, *(_real(b) for b in bound)}
        self.homes = {roots.home, _real(roots.home)}
        self.link_parent = roots.python_prefix.parent

    def judge(self, link: Path) -> bool:
        """True to recreate ``link``; False to leave it; raises when it cannot be handled."""
        if link in self.homes or any(link in b.parents for b in self.bound):
            raise InterpreterLinkError("bound_ancestor")
        if not any(link.is_relative_to(h) for h in self.homes):
            return False
        if any(link == b or link.is_relative_to(b) for b in self.bound):
            return False
        if not link.is_relative_to(self.link_parent):
            raise InterpreterLinkError("link_location")
        return True


def _walk(start: Path, scope: _Scope, found: dict[str, str]) -> None:
    pending = list(PurePosixPath(start).parts[1:])
    current = Path("/")
    hops = 0
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        candidate = current / part
        try:
            target = os.readlink(candidate)
        except OSError as exc:
            if exc.errno != errno.EINVAL:
                raise InterpreterLinkError("walk_error") from None
            current = candidate
            continue
        hops += 1
        if hops > MAX_HOPS:
            raise InterpreterLinkError("too_many_hops")
        if scope.judge(candidate):
            found[str(candidate)] = target
        parts = PurePosixPath(target).parts
        if target.startswith("/"):
            current, parts = Path("/"), parts[1:]
        pending = [*parts, *pending]


def _inside_prefix(link: str, roots: SandboxRoots) -> bool:
    try:
        final = Path(os.path.realpath(link, strict=True))
    except OSError:
        return False
    return final == roots.python_prefix or final.is_relative_to(roots.python_prefix)


def interpreter_symlinks(
    roots: SandboxRoots, excluded: Iterable[Path] | None = None
) -> tuple[tuple[str, str], ...]:
    """Sorted ``(link path, exact readlink text)`` hops to recreate; ``()`` when there are none.

    ``excluded`` are the destinations the argv already binds (default: repo, prefix, data root).
    """
    venv = roots.repo_root / VENV_DIR
    if not os.path.lexists(venv):
        return ()
    scope = _Scope(roots, excluded or (roots.repo_root, roots.python_prefix, roots.data_root))
    starts = [venv / "bin" / "python3"]
    home = _pyvenv_home(venv / PYVENV_CFG)
    if home is not None:
        starts.append(home)
    found: dict[str, str] = {}
    for start in starts:
        _walk(start, scope, found)
    for link in found:
        if not _inside_prefix(link, roots):
            raise InterpreterLinkError("outside_prefix")
    return tuple(sorted(found.items()))
