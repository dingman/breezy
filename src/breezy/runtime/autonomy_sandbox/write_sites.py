"""The shared write-site allowlist and the wrapper-code manifest (plan r5 AC-4, V11).

``SHARED_WRITE_SITES`` is the exact set of (module, function, call) write sites
owned by the shared sandbox modules listed in ``SHARED_WRITE_MODULES`` (the
self-probe in WP-B2b-3, ``bus_handoff`` in WP-B2c and ``wal_snapshot`` in WP-B3). A
consumer's read-only-closure lint (AUT-6 ruling AC6) may admit these sites and no others,
and only where every snapshot call passes ``cache_dir=`` a module-level ``Final`` constant
of the caller
(``tests/support/autonomy_write_sites.cache_dir_is_own_module_constant``).

``test_shared_write_sites_equal_package_scan`` re-derives the set from the source
with the AC6 read allowlist, so adding a write call without widening this set (or
the reverse) fails the gate (L-12).

``WRAPPER_CODE_FILES`` is the V11 manifest: the wrapper script plus every package
module, repo-relative. The deployed-blob check hashes exactly these files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class WriteSite:
    """One write call: the package module, the enclosing function and the called name."""

    module: str
    function: str
    call: str


#: Package modules whose write sites are shared with consumers (module file stems).
SHARED_WRITE_MODULES: Final[tuple[str, ...]] = ("self_probe", "bus_handoff", "wal_snapshot")

#: The self-probe's sites: the ``O_TMPFILE`` negative/positive opens (no directory entry), and
#: the subdir positive's create and unlink inside an existing ``.bwrap_probe/``. The bus
#: handoff's sites: the ``.bus_snapshot`` ``mkdirat``, the ``O_EXCL`` snapshot create (open,
#: write, fsync and the unlink of a partial file), the sweep unlink, the in-sandbox
#: read-and-unlink, the process-group kill of a hung read (with its own-group guard) and the
#: read-deadline exception. Its ``Popen`` is an injected
#: parameter (default ``subprocess.Popen``), so a call-site scan cannot see it; its argv set is
#: pinned by ``table.validate_bus_read`` at table build and again at spawn. The WAL snapshot's
#: sites are all on the *cache copy*: the ``snap.*`` ``mkdirat`` (and its failure ``rmdir``), the
#: ``O_EXCL`` copy create and its writes, the removal of a snapshot directory, and the
#: read-write recovery connection. Opening and fingerprinting the live source, the cache
#: directory and the intent lock are ``O_RDONLY`` opens and are not sites.
SHARED_WRITE_SITES: Final[frozenset[WriteSite]] = frozenset(
    {
        WriteSite("self_probe", "_tmpfile_outcome", "os.open"),
        WriteSite("self_probe", "_subdir_positive", "os.open"),
        WriteSite("self_probe", "_subdir_positive", "os.unlink"),
        WriteSite("bus_handoff", "_open_snapshot_dir", "os.mkdir"),
        WriteSite("bus_handoff", "_create_snapshot", "os.open"),
        WriteSite("bus_handoff", "_create_snapshot", "os.write"),
        WriteSite("bus_handoff", "_create_snapshot", "os.fsync"),
        WriteSite("bus_handoff", "_create_snapshot", "os.unlink"),
        WriteSite("bus_handoff", "_sweep", "os.unlink"),
        WriteSite("bus_handoff", "_consume", "os.unlink"),
        WriteSite("bus_handoff", "_kill_group", "os.killpg"),
        WriteSite("bus_handoff", "_kill_group", "os.getpgrp"),
        WriteSite("bus_handoff", "_read_stdout", "subprocess.TimeoutExpired"),
        WriteSite("wal_snapshot", "_make_snap_dir", "os.mkdir"),
        WriteSite("wal_snapshot", "_make_snap_dir", "os.rmdir"),
        WriteSite("wal_snapshot", "_create_copy", "os.open"),
        WriteSite("wal_snapshot", "_create_copy", "os.write"),
        WriteSite("wal_snapshot", "_remove_tree", "os.unlink"),
        WriteSite("wal_snapshot", "_remove_tree", "os.rmdir"),
        WriteSite("wal_snapshot", "_recover", "sqlite3.connect"),
    }
)

_PACKAGE: Final = "src/breezy/runtime/autonomy_sandbox"

#: V11: ``sha256sum`` of each of these must equal the merge sha's blob. Sorted, exact.
WRAPPER_CODE_FILES: Final[tuple[str, ...]] = (
    "deploy/systemd/breezy-autonomy-bwrap",
    f"{_PACKAGE}/__init__.py",
    f"{_PACKAGE}/binds.py",
    f"{_PACKAGE}/bus_handoff.py",
    f"{_PACKAGE}/bwrap.py",
    f"{_PACKAGE}/interp_links.py",
    f"{_PACKAGE}/run_mounts.py",
    f"{_PACKAGE}/self_probe.py",
    f"{_PACKAGE}/selftest_cli.py",
    f"{_PACKAGE}/studies_lock.py",
    f"{_PACKAGE}/table.py",
    f"{_PACKAGE}/unit_lint.py",
    f"{_PACKAGE}/wal_snapshot.py",
    f"{_PACKAGE}/write_sites.py",
)
