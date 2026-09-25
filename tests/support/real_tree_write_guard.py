"""Attribute writes to a REAL on-disk tree to THIS test process, not to a
racy `(relpath, size, mtime)` snapshot diff.

`test_live_fill_scoring_chain_contract.py`'s
`_guard_real_derived_and_catalog_trees_untouched` (and the single-file
variants in `test_structural_pin_guard.py` / `test_trade_supervisor.py`)
used to snapshot the REAL `~/.local/share/breezy/...` trees before and
after a module ran and assert byte-for-byte equality. That flakes for real
on this host: live production processes -- the NWS ingest daemon writing
`polymarket_us/<CITY>/data/custom_nws_climate_day`, the trade node's
`state/breezy-state.sqlite3` WAL/SHM, and the scorer's own timers writing
`derived/scored_trials` -- mutate those exact trees concurrently, entirely
independent of anything a test does. A stat-diff cannot tell "this test
wrote here" apart from "some other process wrote here at the same moment";
excluding more subtrees to dodge that would WEAKEN the guard.

A `sys.addaudithook` sidesteps the race structurally rather than papering
over it: audit events fire only for operations THIS interpreter performs.
A concurrent write from another OS process (a different interpreter, or no
interpreter at all) never raises an event here, so the guard can watch the
real trees continuously, including subtrees the old exclusion had to carve
out (e.g. `quote_tape/`), without ever seeing another process's activity.

`sys.addaudithook` hooks cannot be removed once installed (CPython docs).
Recording is therefore gated on a per-guard `active` flag: a guarded
module's fixture flips it on for setup and off for teardown, so the hook
closure goes permanently inert for the rest of the test session the moment
that module's guarded window ends, without needing (or being able) to
uninstall anything.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["RealTreeWriteGuard", "install_real_tree_write_guard"]

#: `open()`/`os.open()` mode characters that indicate a write, append,
#: create, or truncate intent (a bare read is `"r"` with none of these).
_WRITE_MODE_CHARS = frozenset({"w", "a", "x", "+"})

#: The `os.open()` flag bits that indicate the same intent when `open()`
#: was called (or emulated) without a string `mode` -- `mode` is then
#: `None` and only `flags` is available on the `open` audit event.
_WRITE_FLAG_BITS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

#: Audit events (besides `open` and `sqlite3.connect`, handled separately)
#: whose first positional argument is the path acted on.
_PATH_ARG0_EVENTS = frozenset({"os.remove", "os.rmdir", "os.mkdir", "shutil.rmtree"})

#: `os.rename` covers BOTH `os.rename` and `os.replace` -- CPython raises
#: the same `os.rename` audit event for both (confirmed empirically: both
#: land here, never a separate `os.replace` event). Its args are
#: `(src, dst, src_dir_fd, dst_dir_fd)`; either endpoint can land under a
#: guarded root (a rename INTO the tree is as much a write as one out of it).
_RENAME_EVENT = "os.rename"


def _is_write_open(mode: object, flags: object) -> bool:
    if isinstance(mode, str):
        return any(ch in mode for ch in _WRITE_MODE_CHARS)
    if isinstance(flags, int):
        return bool(flags & _WRITE_FLAG_BITS)
    return False


def _resolve_or_none(candidate: object) -> Path | None:
    if not isinstance(candidate, (str, bytes, os.PathLike)):
        return None
    try:
        return Path(os.fspath(candidate)).resolve()
    except (OSError, ValueError):
        return None


@dataclass
class RealTreeWriteGuard:
    """Accumulates offending paths while `active`; inert while not.

    One instance per guarded module -- `install_real_tree_write_guard`
    installs a fresh `sys.addaudithook` closure over each instance, so
    guards for different roots never share state and never need to be
    told apart inside a single process-wide hook.
    """

    roots: tuple[Path, ...]
    active: bool = False
    offenses: list[str] = field(default_factory=list)

    def _root_containing(self, resolved: Path) -> Path | None:
        for root in self.roots:
            if resolved == root or root in resolved.parents:
                return root
        return None

    def _record_if_under_roots(self, event: str, candidate: object) -> None:
        resolved = _resolve_or_none(candidate)
        if resolved is None:
            return
        root = self._root_containing(resolved)
        if root is not None:
            self.offenses.append(f"{event}: {resolved} (under guarded root {root})")

    def __call__(self, event: str, args: tuple[object, ...]) -> None:
        if not self.active:
            return
        if event == "open":
            path, mode, flags = args
            if _is_write_open(mode, flags):
                self._record_if_under_roots(event, path)
        elif event == _RENAME_EVENT:
            src, dst = args[0], args[1]
            self._record_if_under_roots(event, src)
            self._record_if_under_roots(event, dst)
        elif event in _PATH_ARG0_EVENTS:
            self._record_if_under_roots(event, args[0] if args else None)
        elif event == "sqlite3.connect":
            (database,) = args
            self._record_if_under_roots(event, database)


def install_real_tree_write_guard(*roots: Path) -> RealTreeWriteGuard:
    """Install a new audit hook watching `roots` and return its guard.

    The guard starts inactive (`active=False`); the calling fixture flips
    it on for its guarded window and off at teardown. Each call installs an
    independent hook closure -- safe to call once per guarded test module.
    """
    guard = RealTreeWriteGuard(roots=tuple(root.resolve() for root in roots))
    sys.addaudithook(guard)
    return guard
