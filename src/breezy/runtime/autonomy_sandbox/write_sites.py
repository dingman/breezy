"""The shared write-site allowlist and the wrapper-code manifest (plan r5 AC-4, V11).

``SHARED_WRITE_SITES`` is the exact set of (module, function, call) write sites
owned by the shared sandbox modules listed in ``SHARED_WRITE_MODULES`` (the
self-probe in WP-B2b-3; ``bus_handoff`` and ``wal_snapshot`` add theirs in their own
WPs, in the same commit as the code). A consumer's read-only-closure lint (AUT-6
ruling AC6) may admit these sites and no others, and only where every snapshot
call passes ``cache_dir=`` a module-level ``Final`` constant of the caller
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
SHARED_WRITE_MODULES: Final[tuple[str, ...]] = ("self_probe",)

#: The self-probe's sites: the ``O_TMPFILE`` negative/positive opens (no directory entry), and
#: the subdir positive's create and unlink inside an existing ``.bwrap_probe/``.
SHARED_WRITE_SITES: Final[frozenset[WriteSite]] = frozenset(
    {
        WriteSite("self_probe", "_tmpfile_outcome", "os.open"),
        WriteSite("self_probe", "_subdir_positive", "os.open"),
        WriteSite("self_probe", "_subdir_positive", "os.unlink"),
    }
)

_PACKAGE: Final = "src/breezy/runtime/autonomy_sandbox"

#: V11: ``sha256sum`` of each of these must equal the merge sha's blob. Sorted, exact.
WRAPPER_CODE_FILES: Final[tuple[str, ...]] = (
    "deploy/systemd/breezy-autonomy-bwrap",
    f"{_PACKAGE}/__init__.py",
    f"{_PACKAGE}/binds.py",
    f"{_PACKAGE}/bwrap.py",
    f"{_PACKAGE}/run_mounts.py",
    f"{_PACKAGE}/self_probe.py",
    f"{_PACKAGE}/selftest_cli.py",
    f"{_PACKAGE}/table.py",
    f"{_PACKAGE}/unit_lint.py",
    f"{_PACKAGE}/write_sites.py",
)
