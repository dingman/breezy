#!/usr/bin/env python3
"""P0 -- verified off-device backup of Breezy's two irreplaceable datasets.

Implements ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` §4.P0 (revision 2).

The two datasets, and why each is irreplaceable:

**(a) the settlement-alignment archive** -- ~299 MB of IEM ASOS CSVs and CLI
AFOS retrievals under ``~/.local/share/breezy/archive/settlement-alignment-cache``.
It cannot be honestly re-fetched: IEM is a curated post-hoc product, so a
re-fetch returns a *later revision* rather than the same bytes, and three
published evidence documents would become unreproducible rather than merely
re-runnable (``docs/evidence/archive/ARCHIVE_RELOCATION_2026-08-27.md:13-20``).
**This is why the script imports no HTTP client, and a test asserts it.** A
re-fetch path is prohibited, not a fallback.

**(b) the quote tape** under ``<catalog_root>/live/``. Polymarket.us publishes
no public trade tape, so every uncaptured minute is permanently lost (Finding
A), and §4.P1.4's convert-then-prune *deletes* the feather runs this tree holds.

Design, per the plan: **policy is pure and directly testable; the I/O is thin.**
``parse_sha256_manifest``, ``build_manifest``, ``verify_tree`` and
``require_distinct_device`` carry every decision; ``write_archive`` and
``extract_archive`` do nothing but move bytes.

Four refusals, each of which is a way of *believing* you have a backup when you
do not:

1. **The primary is verified BEFORE anything is copied**, against the
   git-tracked SHA-256 manifest. A mismatch raises and writes nothing --
   backing up an already-corrupt primary is impossible.
2. **A same-device destination is refused**, by ``os.stat().st_dev``
   inequality. "Off-host satisfied by a sibling directory" is impossible.
3. **The restore is proven, not the copy.** The tarball is extracted to a
   scratch tree on the destination device and *that extraction* is verified
   against the per-file manifest. A backup never restored is a hypothesis.
4. **Dry run by default.** ``--apply`` is required to write a single byte.

This script never deletes anything -- not the primary, not the ``/tmp`` copy,
not a failed artifact. A test asserts the absence of every removal call.

Usage::

    # dry run (default) -- reports, writes nothing
    python scripts/archive/backup_irreplaceable_data.py --destination /mnt/storage/breezy-p0-backup

    # write, verify the restore, and report
    python scripts/archive/backup_irreplaceable_data.py \\
        --destination /mnt/storage/breezy-p0-backup --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import shutil
import subprocess  # drives the local `zstd` binary; no network primitive
import sys
import tarfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "BackupError",
    "DatasetBackupReport",
    "DigestMismatchError",
    "RestoreVerificationError",
    "SameDeviceError",
    "VerificationResult",
    "backup_dataset",
    "build_manifest",
    "extract_archive",
    "format_sha256_manifest",
    "main",
    "parse_sha256_manifest",
    "require_distinct_device",
    "verify_tree",
    "write_archive",
]

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The archive's canonical home, as every analysis script already resolves it
#: (``scripts/analysis/settlement_alignment_cache.py:8-10``).
DEFAULT_ARCHIVE_DIR: Final[Path] = (
    Path.home() / ".local/share/breezy/archive/settlement-alignment-cache"
)

#: The git-tracked per-file manifest. This is the record the primary is checked
#: against, and it travels to the destination UNCHANGED
#: (``ARCHIVE_RELOCATION_2026-08-27.md:28-31``).
DEFAULT_ARCHIVE_MANIFEST: Final[Path] = (
    REPO_ROOT / "docs" / "evidence" / "archive" / "settlement-alignment-cache.sha256"
)

#: The environment variable the recorder itself requires, with no default
#: (``src/breezy/runtime/settings.py:63``, consumed at ``:539``). The tape root
#: is deliberately NOT hardcoded here: a backup that reads a different path
#: from the one the recorder writes is not a backup. A unit test asserts this
#: literal still matches ``settings.py``.
QUOTE_TAPE_CATALOG_VAR: Final[str] = "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"

#: The streaming writer lands under ``<catalog_path>/<environment>/<instance_id>``
#: and the recorder's node config pins ``environment=Environment.LIVE``
#: (``src/breezy/runtime/node_config.py:452``, ``:465-473``).
QUOTE_TAPE_LIVE_SUBDIR: Final[str] = "live"

ARCHIVE_DATASET: Final[str] = "settlement-alignment-cache"
TAPE_DATASET: Final[str] = "quote-tape-live"

_READ_CHUNK_BYTES: Final[int] = 1024 * 1024


class BackupError(RuntimeError):
    """Base for every refusal this script can make."""


class DigestMismatchError(BackupError):
    """The PRIMARY failed verification. Nothing is copied."""


class SameDeviceError(BackupError):
    """Source and destination share an ``st_dev``, so this is not a backup."""


class RestoreVerificationError(BackupError):
    """The extracted tree does not match the manifest. The backup FAILED."""


# --------------------------------------------------------------------------
# Pure policy -- manifests
# --------------------------------------------------------------------------


def parse_sha256_manifest(text: str) -> dict[str, str]:
    """Parse ``sha256sum`` output into ``{relative path: digest}``.

    Rejects a duplicate name rather than letting the last line win: a manifest
    naming one file twice cannot be used to decide whether a tree is intact.
    """
    entries: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        digest, separator, name = line.partition("  ")
        if not separator:
            digest, separator, name = line.partition(" *")
        if not separator or not name:
            raise ValueError(f"manifest line {lineno} is not `<digest>  <name>`: {raw!r}")
        digest = digest.strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"manifest line {lineno} has a non-SHA-256 digest: {raw!r}")
        name = name.strip()
        if name in entries:
            raise ValueError(f"manifest names {name!r} more than once (duplicate entry)")
        entries[name] = digest
    return entries


def format_sha256_manifest(entries: Mapping[str, str]) -> str:
    """Render ``{relative path: digest}`` in ``sha256sum`` format, sorted."""
    return "".join(f"{entries[name]}  {name}\n" for name in sorted(entries))


def relative_file_paths(root: Path) -> tuple[str, ...]:
    """Every regular file under ``root``, as sorted POSIX-relative paths.

    Symlinks are excluded deliberately: a manifest entry for a link describes
    the link's target, which is not a property of this tree.
    """
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        found.append(path.relative_to(root).as_posix())
    return tuple(sorted(found))


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path, digest_of: Callable[[Path], str] = sha256_path) -> dict[str, str]:
    """Generate a per-file SHA-256 manifest for a tree that has none.

    The quote tape is exactly that case: unlike the settlement-alignment
    archive it carries no git-tracked manifest, so one is generated at backup
    time and the restored extraction is verified against it.
    """
    return {name: digest_of(root / name) for name in relative_file_paths(root)}


# --------------------------------------------------------------------------
# Pure policy -- verification
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Outcome of checking one tree against one manifest."""

    checked: int
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    mismatched: tuple[str, ...]
    unexpected: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.mismatched or self.unexpected)

    def summary(self) -> str:
        return (
            f"{len(self.matched)}/{self.checked} OK, "
            f"{len(self.mismatched)} mismatched, "
            f"{len(self.missing)} missing, "
            f"{len(self.unexpected)} unexpected"
        )

    def failure_detail(self) -> str:
        parts: list[str] = []
        if self.mismatched:
            parts.append(f"mismatched={list(self.mismatched)}")
        if self.missing:
            parts.append(f"missing={list(self.missing)}")
        if self.unexpected:
            parts.append(f"unexpected={list(self.unexpected)}")
        return "; ".join(parts)


def verify_tree(
    root: Path,
    expected: Mapping[str, str],
    digest_of: Callable[[Path], str] = sha256_path,
) -> VerificationResult:
    """Check every file under ``root`` against ``expected``.

    ``unexpected`` is reported as a failure, not a curiosity: an extra file in
    a restored tree means the extraction is not the thing the manifest
    describes, and the whole point of P0 is that the copy is provably the
    original.
    """
    present = set(relative_file_paths(root))
    matched: list[str] = []
    missing: list[str] = []
    mismatched: list[str] = []

    for name in sorted(expected):
        if name not in present:
            missing.append(name)
            continue
        if digest_of(root / name) == expected[name].lower():
            matched.append(name)
        else:
            mismatched.append(name)

    unexpected = sorted(present - set(expected))
    return VerificationResult(
        checked=len(expected),
        matched=tuple(matched),
        missing=tuple(missing),
        mismatched=tuple(mismatched),
        unexpected=tuple(unexpected),
    )


# --------------------------------------------------------------------------
# Pure policy -- the device check
# --------------------------------------------------------------------------


def _device_of(path: Path) -> int:
    """``st_dev`` of ``path``, or of its nearest existing ancestor.

    The destination usually does not exist yet, and the device that matters is
    the one it *would* be created on.
    """
    candidate = path if path.exists() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return os.stat(candidate).st_dev


def require_distinct_device(
    source: Path,
    destination: Path,
    dev_of: Callable[[Path], int] | None = None,
) -> tuple[int, int]:
    """Return ``(source st_dev, destination st_dev)``, or refuse if equal.

    This is the whole definition of "off-device" in P0. Success is written
    against ``st_dev`` precisely so that "I copied it next to itself" cannot
    pass, and neither can a bind mount or a symlink pointing back at the
    primary's own filesystem.
    """
    resolve = _device_of if dev_of is None else dev_of
    source_dev = resolve(source)
    destination_dev = resolve(destination)
    if source_dev == destination_dev:
        raise SameDeviceError(
            f"refusing to back up {source} to {destination}: both are on "
            f"st_dev={source_dev}. A second directory on the same device is "
            "not a backup -- it dies with the device it lives on."
        )
    return source_dev, destination_dev


# --------------------------------------------------------------------------
# Thin I/O -- compression and extraction
# --------------------------------------------------------------------------


def _zstd_binary() -> str:
    found = shutil.which("zstd")
    if found is None:  # pragma: no cover - environment-dependent
        raise BackupError(
            "the `zstd` binary is not on PATH; P0 writes `.tar.zst` and will "
            "not silently downgrade the archive format"
        )
    return found


def write_archive(source: Path, arcname: str, destination: Path) -> Path:
    """Stream ``source`` into ``destination`` as a zstd-compressed tar.

    Streamed rather than staged so no full-size temporary copy is written on
    the primary's device -- the device this exists to stop depending on.
    """
    command = [_zstd_binary(), "-T0", "-q", "-o", str(destination)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        assert process.stdin is not None
        with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
            archive.add(source, arcname=arcname, recursive=True)
    finally:
        if process.stdin is not None:
            process.stdin.close()
        returncode = process.wait()
    if returncode != 0:
        raise BackupError(f"zstd failed with exit code {returncode} writing {destination}")
    return destination


def extract_archive(tarball: Path, into: Path) -> Path:
    """Extract ``tarball`` under ``into`` and return the extracted root.

    Extraction happens on the DESTINATION device, so the read path that a
    real recovery would take is the read path that gets verified.
    """
    into.mkdir(parents=True, exist_ok=True)
    command = [_zstd_binary(), "-d", "-c", str(tarball)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    try:
        assert process.stdout is not None
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            archive.extractall(path=into, filter="data")
    finally:
        if process.stdout is not None:
            process.stdout.close()
        returncode = process.wait()
    if returncode != 0:
        raise BackupError(f"zstd failed with exit code {returncode} reading {tarball}")
    roots = [child for child in into.iterdir() if child.is_dir()]
    if len(roots) != 1:
        raise RestoreVerificationError(
            f"expected exactly one extracted root under {into}, found {len(roots)}"
        )
    return roots[0]


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DatasetBackupReport:
    """Everything the evidence document needs about one dataset."""

    dataset: str
    source: Path
    destination_dir: Path
    file_count: int
    total_bytes: int
    source_device: int
    destination_device: int
    manifest_generated: bool
    applied: bool
    tarball: Path | None = None
    tarball_bytes: int | None = None
    tarball_sha256: str | None = None
    detached_digest_path: Path | None = None
    manifest_path: Path | None = None
    restore_root: Path | None = None
    restore: VerificationResult | None = None
    primary: VerificationResult | None = None


def _utc_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def backup_dataset(
    *,
    dataset: str,
    source: Path,
    destination_dir: Path,
    expected_manifest_text: str | None = None,
    apply: bool = False,
    stamp: str | None = None,
    dev_of: Callable[[Path], int] | None = None,
) -> DatasetBackupReport:
    """Verify, copy off-device, and prove the restore. In that order.

    The ordering is load-bearing, and each step is a separate refusal:

    1. **census** -- an empty source is refused, because a zero-file backup
       verifies vacuously and reports success;
    2. **verify the primary** against ``expected_manifest_text`` (the
       git-tracked manifest) or a freshly generated one. A mismatch raises
       here, before the destination directory is so much as created;
    3. **refuse a same-device destination** -- in DRY RUN as well as under
       ``--apply``. A dry run reports what would happen, and what would happen
       to a sibling directory on the primary's own device is a refusal;
    4. **write** ``.tar.zst`` + a detached ``.sha256`` of the tar + the
       per-file manifest, unchanged;
    5. **extract and verify the extraction**. Anything short of a clean
       restore raises: the backup is not established until it has been
       restored.
    """
    if not source.is_dir():
        raise BackupError(f"{dataset}: source {source} is not a directory")

    names = relative_file_paths(source)
    if not names:
        raise ValueError(
            f"{dataset}: source {source} contains no files; refusing to write a "
            "backup that would verify vacuously"
        )
    total_bytes = sum((source / name).stat().st_size for name in names)

    manifest_generated = expected_manifest_text is None
    manifest_text = (
        format_sha256_manifest(build_manifest(source))
        if expected_manifest_text is None
        else expected_manifest_text
    )
    expected = parse_sha256_manifest(manifest_text)

    # (2) The primary, first. Deliberately before the device check: if the
    # device check ran first, a corrupt primary written to a legitimately
    # separate device would be reported as a success.
    primary = verify_tree(source, expected)
    if not primary.ok:
        raise DigestMismatchError(
            f"{dataset}: PRIMARY at {source} failed verification against its "
            f"manifest ({primary.summary()}): {primary.failure_detail()}. "
            "Nothing was written -- backing up an already-corrupt primary "
            "would launder the corruption into the only surviving copy."
        )

    # (3) The device.
    source_device, destination_device = require_distinct_device(
        source, destination_dir, dev_of=dev_of
    )

    resolved_stamp = stamp or _utc_stamp()

    if not apply:
        return DatasetBackupReport(
            dataset=dataset,
            source=source,
            destination_dir=destination_dir,
            file_count=len(names),
            total_bytes=total_bytes,
            source_device=source_device,
            destination_device=destination_device,
            manifest_generated=manifest_generated,
            applied=False,
            primary=primary,
        )

    # (4) Write. Nothing above this line creates a byte or a directory.
    destination_dir.mkdir(parents=True, exist_ok=True)
    base = f"{dataset}-{resolved_stamp}"
    tarball = destination_dir / f"{base}.tar.zst"
    detached = destination_dir / f"{base}.tar.zst.sha256"
    manifest_path = destination_dir / f"{base}.files.sha256"

    if tarball.exists():
        raise BackupError(f"{dataset}: {tarball} already exists; refusing to overwrite it")

    write_archive(source, arcname=dataset, destination=tarball)
    tarball_sha256 = sha256_path(tarball)
    detached.write_text(f"{tarball_sha256}  {tarball.name}\n")
    manifest_path.write_text(manifest_text)

    # (5) Prove the restore, not the copy.
    restore_root = extract_archive(tarball, destination_dir / f"{base}.restore")
    restore = verify_tree(restore_root, expected)
    if not restore.ok:
        raise RestoreVerificationError(
            f"{dataset}: the RESTORED extraction at {restore_root} does not "
            f"match the manifest ({restore.summary()}): {restore.failure_detail()}. "
            "The artifacts are left in place as evidence of the failure; this "
            "backup must not be counted."
        )

    return DatasetBackupReport(
        dataset=dataset,
        source=source,
        destination_dir=destination_dir,
        file_count=len(names),
        total_bytes=total_bytes,
        source_device=source_device,
        destination_device=destination_device,
        manifest_generated=manifest_generated,
        applied=True,
        tarball=tarball,
        tarball_bytes=tarball.stat().st_size,
        tarball_sha256=tarball_sha256,
        detached_digest_path=detached,
        manifest_path=manifest_path,
        restore_root=restore_root,
        restore=restore,
        primary=primary,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def resolve_tape_live_dir(env: Mapping[str, str]) -> Path:
    """Locate ``<catalog_root>/live`` the way the recorder locates it.

    The recorder requires :data:`QUOTE_TAPE_CATALOG_VAR` with no default and
    refuses to start without it (``settings.py:539-543``). This function makes
    the same demand rather than guessing, because a backup of a *different*
    directory from the one the recorder writes is worse than no backup: it
    reports success while the tape stays unprotected.
    """
    raw = env.get(QUOTE_TAPE_CATALOG_VAR, "").strip()
    if not raw:
        raise BackupError(
            f"{QUOTE_TAPE_CATALOG_VAR} is not set, so the quote-tape catalog "
            "root cannot be resolved the way the recorder resolves it "
            "(src/breezy/runtime/settings.py:63). Set it, or pass "
            "--tape-live-dir explicitly."
        )
    root = Path(raw)
    if not root.is_absolute():
        raise BackupError(f"{QUOTE_TAPE_CATALOG_VAR} must be an absolute path, was {raw!r}")
    return root / QUOTE_TAPE_LIVE_SUBDIR


def _render(report: DatasetBackupReport) -> str:
    lines = [
        f"[{report.dataset}]",
        f"  source            : {report.source}",
        f"  files             : {report.file_count}",
        f"  bytes             : {report.total_bytes}",
        f"  source st_dev     : {report.source_device}",
        f"  destination st_dev: {report.destination_device}",
        f"  manifest          : {'GENERATED' if report.manifest_generated else 'git-tracked'}",
    ]
    if report.primary is not None:
        lines.append(f"  primary verify    : {report.primary.summary()}")
    if not report.applied:
        lines.append("  mode              : DRY RUN (no bytes written; pass --apply)")
        return "\n".join(lines)
    lines += [
        f"  tarball           : {report.tarball} ({report.tarball_bytes} bytes)",
        f"  tarball sha256    : {report.tarball_sha256}",
        f"  detached digest   : {report.detached_digest_path}",
        f"  per-file manifest : {report.manifest_path}",
        f"  restored to       : {report.restore_root}",
    ]
    if report.restore is not None:
        lines.append(f"  RESTORE VERIFY    : {report.restore.summary()}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verified off-device backup of the settlement-alignment archive and "
            "the quote tape. Dry run unless --apply."
        )
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Directory on a DIFFERENT device (st_dev) to write the backup into.",
    )
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument(
        "--archive-manifest",
        type=Path,
        default=DEFAULT_ARCHIVE_MANIFEST,
        help="Git-tracked per-file SHA-256 manifest the PRIMARY is checked against.",
    )
    parser.add_argument(
        "--tape-live-dir",
        type=Path,
        default=None,
        help=f"Defaults to ${QUOTE_TAPE_CATALOG_VAR}/{QUOTE_TAPE_LIVE_SUBDIR}.",
    )
    parser.add_argument(
        "--no-manifest-check",
        action="store_true",
        help=(
            "Generate the archive's manifest instead of reading the git-tracked "
            "one. For fixtures only; the real run must check the tracked record."
        ),
    )
    parser.add_argument("--stamp", default=None, help="UTC stamp for artifact names.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Without this the run reports and writes zero bytes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stamp = args.stamp or _utc_stamp()

    try:
        tape_live_dir = (
            args.tape_live_dir
            if args.tape_live_dir is not None
            else resolve_tape_live_dir(os.environ)
        )
        manifest_text = None if args.no_manifest_check else Path(args.archive_manifest).read_text()

        reports = [
            backup_dataset(
                dataset=ARCHIVE_DATASET,
                source=Path(args.archive_dir),
                destination_dir=Path(args.destination),
                expected_manifest_text=manifest_text,
                apply=bool(args.apply),
                stamp=stamp,
            ),
            backup_dataset(
                dataset=TAPE_DATASET,
                source=Path(tape_live_dir),
                destination_dir=Path(args.destination),
                expected_manifest_text=None,
                apply=bool(args.apply),
                stamp=stamp,
            ),
        ]
    except (BackupError, ValueError, OSError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    for report in reports:
        print(_render(report))
    if not any(report.applied for report in reports):
        print("\nDRY RUN complete. Zero bytes written. Re-run with --apply.")
    else:
        print("\nBackup complete and RESTORE-VERIFIED on the destination device.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
