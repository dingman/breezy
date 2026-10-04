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

import os
from pathlib import Path, PurePosixPath
from typing import Final

from breezy.runtime.autonomy_sandbox.table import SandboxRoots

MAX_HOPS: Final = 8
VENV_DIR: Final = ".venv"
PYVENV_CFG: Final = "pyvenv.cfg"
_PYVENV_HOME_KEY: Final = "home"
_MAX_CFG_BYTES: Final = 4096


class InterpreterLinkError(ValueError):
    """A hop the sandbox cannot safely recreate (outside the prefix, a loop, too many hops)."""


def _pyvenv_home(cfg: Path) -> Path | None:
    try:
        with cfg.open("rb") as handle:
            text = handle.read(_MAX_CFG_BYTES).decode("utf-8", "replace")
    except OSError:
        return None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == _PYVENV_HOME_KEY and value.strip().startswith("/"):
            return Path(value.strip())
    return None


def _needs_link(link: Path, roots: SandboxRoots) -> bool:
    """True when ``link`` is under the hidden home and outside every bound root."""
    bound = (roots.repo_root, roots.python_prefix, roots.data_root)
    return link.is_relative_to(roots.home) and not any(link.is_relative_to(b) for b in bound)


def _walk(start: Path, roots: SandboxRoots, found: dict[str, str]) -> None:
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
        except FileNotFoundError:
            return
        except OSError:
            current = candidate
            continue
        hops += 1
        if hops > MAX_HOPS:
            raise InterpreterLinkError("too_many_hops")
        if _needs_link(candidate, roots):
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


def interpreter_symlinks(roots: SandboxRoots) -> tuple[tuple[str, str], ...]:
    """Sorted ``(link path, exact readlink text)`` hops to recreate; ``()`` when there are none."""
    venv = roots.repo_root / VENV_DIR
    starts = [venv / "bin" / "python3"]
    home = _pyvenv_home(venv / PYVENV_CFG)
    if home is not None:
        starts.append(home)
    found: dict[str, str] = {}
    for start in starts:
        _walk(start, roots, found)
    for link in found:
        if not _inside_prefix(link, roots):
            raise InterpreterLinkError("outside_prefix")
    return tuple(sorted(found.items()))
