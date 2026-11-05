"""Filesystem-locality probe for the station-catalog writer lock.

The mount table parser and the fail-closed ``flock`` precondition live here,
not in :mod:`breezy.persistence.catalog`. That module re-exports every public
and private name below: ``persistence``'s package init and already-running
processes import them from the old path. The probe looks those names up in
*this* module, so a patch on the catalog re-export does not redirect it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Final

__all__ = [
    "NETWORK_FILESYSTEM_TYPES",
    "FilesystemLocality",
    "FilesystemProbe",
    "WriterLockFilesystemError",
    "assert_writer_lock_filesystem_supported",
    "probe_filesystem",
]

# ---------------------------------------------------------------------------
# `flock` local-filesystem startup assertion
# ---------------------------------------------------------------------------
#
# `flock` is unreliable over NFS (pre-v4 outright; v4 depending on lock-manager
# configuration), CIFS/SMB, sshfs and other network-backed mounts. Moving a
# station root onto shared storage would weaken "at most one writer per station
# root" with NO exception and NO log -- exactly the silent degradation this
# module exists to prevent. The precondition is not enforceable by `flock`
# itself, so it is asserted at startup instead, mirroring
# `breezy.ingest.gate.assert_state_store_durable`. Both are SS6 step-0
# preconditions run once by `SharedIngestState.__init__`.


class FilesystemLocality(str, Enum):
    """Whether a path's filesystem is one `flock` can be trusted on."""

    LOCAL = "LOCAL"
    NETWORK = "NETWORK"
    UNDETERMINED = "UNDETERMINED"


#: Mount types where `flock` does NOT reliably exclude writers on other hosts.
#:
#: Deliberately a targeted list, not "everything that is not a local disk".
#: Containers routinely run on ``overlay`` and ``tmpfs``, where `flock` is
#: perfectly correct locally; rejecting those would be a false positive that
#: gets the check disabled in frustration, which is worse than not having it.
#:
#: FUSE mounts are matched on their ``fuse.<subtype>`` name, so a network-backed
#: FUSE filesystem is caught while a local one (``fuse.gocryptfs``,
#: ``fuse.ntfs-3g``) is not; a bare ``fuse`` with no subtype is not rejected,
#: because it carries no evidence either way.
#:
#: ``gfs2`` and ``ocfs2`` are excluded on purpose: they are shared-BLOCK cluster
#: filesystems that implement cluster-wide `flock` correctly, so listing them
#: would reject a configuration that is in fact safe.
NETWORK_FILESYSTEM_TYPES: Final[frozenset[str]] = frozenset(
    {
        "9p",
        "afs",
        "afpfs",
        "beegfs",
        "ceph",
        "cifs",
        "coda",
        "davfs",
        "fuse.cephfs",
        "fuse.curlftpfs",
        "fuse.davfs2",
        "fuse.gcsfuse",
        "fuse.glusterfs",
        "fuse.rclone",
        "fuse.s3fs",
        "fuse.sshfs",
        "fuse.blobfuse",
        "fuse.blobfuse2",
        "glusterfs",
        "lustre",
        "ncpfs",
        "nfs",
        "nfs4",
        "orangefs",
        "pvfs2",
        "smb2",
        "smb3",
        "smbfs",
        "sshfs",
    }
)

# Linux-only. There is no stdlib call that returns a filesystem TYPE:
# `os.statvfs` carries no type field and CPython ships no `os.statfs`.
_MOUNTINFO_PATH: Final[Path] = Path("/proc/self/mountinfo")

# `mountinfo` octal-escapes space, tab, newline and backslash in path fields.
_MOUNTINFO_ESCAPE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\\(\d{3})")

# id, parent, maj:min, root, mount point, options -- then optional fields, then
# the `-` separator. So the separator can never appear before index 6.
_MOUNTINFO_MOUNT_POINT_FIELD: Final[int] = 4
_MOUNTINFO_MIN_SEPARATOR_FIELD: Final[int] = 6


class WriterLockFilesystemError(Exception):
    """Raised when a station root's filesystem cannot be trusted for `flock`.

    Either it is a known network-shared type, or its type could not be
    determined at all -- both fail closed, because "cannot verify" reported as
    "verified local" is precisely the silent degradation being guarded against.
    """


@dataclass(frozen=True, slots=True)
class FilesystemProbe:
    """What :func:`probe_filesystem` could determine about one path.

    Attributes
    ----------
    path : str
        The resolved path that was probed.
    mount_point : str or None
        The mount covering it, or ``None`` when nothing could be determined.
    fs_type : str or None
        That mount's filesystem type, e.g. ``"ext4"``, ``"overlay"``, ``"nfs4"``.
    locality : FilesystemLocality
    detail : str
        Human-readable provenance for the verdict, for logs and error messages.

    """

    path: str
    mount_point: str | None
    fs_type: str | None
    locality: FilesystemLocality
    detail: str


def probe_filesystem(path: Path | str) -> FilesystemProbe:
    """Determine whether `path` sits on a filesystem `flock` can be trusted on.

    Reads ``/proc/self/mountinfo`` and takes the longest mount point covering the
    RESOLVED path (later entries win a tie, because an over-mount shadows the
    mount beneath it). `path` need not exist yet: a mount point always does, so
    longest-prefix matching gives the same answer for a path about to be created.

    Never raises and never has side effects -- it is a query. The refusal is
    :func:`assert_writer_lock_filesystem_supported`'s job, so a caller that only
    wants to log what it is running on does not need a ``try``.
    """
    resolved = Path(path).resolve()

    try:
        raw = _MOUNTINFO_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        return FilesystemProbe(
            path=str(resolved),
            mount_point=None,
            fs_type=None,
            locality=FilesystemLocality.UNDETERMINED,
            detail=(
                f"{_MOUNTINFO_PATH} could not be read ({exc}); filesystem type "
                f"detection is Linux-only"
            ),
        )

    matched = _match_mount(raw, resolved)

    if matched is None:
        return FilesystemProbe(
            path=str(resolved),
            mount_point=None,
            fs_type=None,
            locality=FilesystemLocality.UNDETERMINED,
            detail=f"no mount point in {_MOUNTINFO_PATH} covers {resolved}",
        )

    mount_point, fs_type = matched
    is_network = fs_type in NETWORK_FILESYSTEM_TYPES

    return FilesystemProbe(
        path=str(resolved),
        mount_point=mount_point,
        fs_type=fs_type,
        locality=FilesystemLocality.NETWORK if is_network else FilesystemLocality.LOCAL,
        detail=f"{mount_point} is {fs_type} (per {_MOUNTINFO_PATH})",
    )


def assert_writer_lock_filesystem_supported(probe: FilesystemProbe) -> None:
    """Raise unless `probe` shows a filesystem `flock` can be trusted on.

    Call this **once at startup, per station root** -- it is deliberately not
    invoked from :func:`open_station_catalog` or :func:`write_records`, because
    import-time or per-write filesystem probing is hostile to tests and tooling::

        assert_writer_lock_filesystem_supported(
            probe_filesystem(station_catalog_path(base, venue, city)),
        )

    Takes the probe rather than the path, for the same reason
    :func:`breezy.ingest.gate.assert_state_store_durable` takes an opener
    rather than a filesystem path: every verdict is then reachable in a test
    without a real mount.

    Raises
    ------
    WriterLockFilesystemError
        If the root is on a known network filesystem, or if its filesystem could
        not be determined.

    """
    if probe.locality is FilesystemLocality.LOCAL:
        return

    if probe.locality is FilesystemLocality.NETWORK:
        raise WriterLockFilesystemError(
            f"station root {probe.path} is on {probe.fs_type} mounted at "
            f"{probe.mount_point}, where `flock` does not reliably exclude "
            f"writers on other hosts. The single-writer-per-station-root "
            f"invariant would degrade silently, so this configuration is "
            f"refused. Put settlement data on local storage.",
        )

    raise WriterLockFilesystemError(
        f"the filesystem backing station root {probe.path} could not be "
        f"determined ({probe.detail}), so `flock`'s single-host precondition "
        f"cannot be verified. Failing closed: an unverified precondition is not "
        f"reported as a satisfied one.",
    )


def _unescape_mountinfo(field: str) -> str:
    return _MOUNTINFO_ESCAPE_PATTERN.sub(lambda m: chr(int(m.group(1), 8)), field)


def _iter_mount_entries(raw: str) -> Iterator[tuple[str, str]]:
    """Yield `(mount_point, fs_type)` for every well-formed `mountinfo` line.

    Malformed lines are skipped rather than raising: an unparseable mount table
    must degrade to ``UNDETERMINED`` (which fails closed at the assertion), never
    to an exception out of a query function.
    """
    for line in raw.splitlines():
        fields = line.split(" ")

        try:
            separator = fields.index("-")
        except ValueError:
            continue

        if separator < _MOUNTINFO_MIN_SEPARATOR_FIELD or separator + 1 >= len(fields):
            continue

        yield _unescape_mountinfo(fields[_MOUNTINFO_MOUNT_POINT_FIELD]), fields[separator + 1]


def _match_mount(raw: str, resolved: Path) -> tuple[str, str] | None:
    """Return the longest mount point covering `resolved`, latest entry winning."""
    target = PurePosixPath(resolved)
    best: tuple[str, str] | None = None
    best_depth = -1

    for mount_point, fs_type in _iter_mount_entries(raw):
        candidate = PurePosixPath(mount_point)

        if candidate != target and candidate not in target.parents:
            continue

        depth = len(candidate.parts)

        if depth >= best_depth:
            best = (mount_point, fs_type)
            best_depth = depth

    return best
