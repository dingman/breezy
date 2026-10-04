"""Family bytes: E-14 root copies and the manifest-facts reader (ARCH-0 AC 21, AC 28).

``write_root_copy`` lays down the content-addressed copy of a root's artefact and its per-family
``root/v1`` record, both write-once (``O_TMPFILE``: no named temp file) and 0444,
through ``single_read`` only (this module performs no filesystem mutation of its own):

* ``derived/artefacts/<kind>:density_table/<sha>/artefact.json``
* ``derived/artefacts/<kind>:density_table/<sha>/roots/<family_id>.json``

Two roots that share an artefact sha share one ``artefact.json`` (``EXISTS_EQUAL`` for the second),
and each has its own record. Different bytes under either name raise :class:`RootCopyIntegrity`.
A rerun decides ``EXISTS_EQUAL`` by reading the existing file before any temp file is created, so
it still succeeds after the directories are sealed 0500; a *new* file in a sealed directory is
refused by mode bit (``DIR_NOT_WRITABLE``), which is why a refit writes into a fresh ``<sha>/``.

``read_manifest_facts`` is the ``ManifestFactsReader`` the store binds into
``transitions.validate``. It answers only from bytes whose sha256 equals the row's
``manifest_sha256``; anything it cannot read, parse, or attribute to that family is ``None``.
It never admits a draft manifest.

Refusals carry closed names, never paths.
"""

from __future__ import annotations

import hashlib
import os
from enum import StrEnum
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.lineage import RootRecord, root_model_class
from breezy.persistence.autonomy.paths import (
    AutonomyPaths,
    ShadowPaths,
    family_component,
    sha_component,
)
from breezy.persistence.autonomy.schemas import ManifestFacts
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    WriteOutcome,
    ensure_dir,
    open_root,
    read_once_at,
    walk_dirs,
    write_once_tmpfile,
)
from breezy.persistence.autonomy.wire import WireRefusalReason, WireRefused
from breezy.persistence.family_manifest import FamilyManifestError, parse_family_manifest
from breezy.persistence.mechanism_test_guard import assert_prereg_directory_eligible

__all__ = [
    "RootCopyIntegrity",
    "RootCopyResult",
    "read_manifest_facts",
    "write_root_copy",
]

_ROOT_COPY_MODE: Final[int] = 0o444
_ROOTS_DIR: Final[str] = "roots"
_MANIFEST_MAX_BYTES: Final[int] = 65536
_COMMITTED_PARTS: Final[tuple[str, ...]] = ("deploy", "families")
_REGISTRY_PARTS: Final[tuple[str, ...]] = ("registry", "families")
#: Everything ``read_manifest_facts`` turns into ``None`` (fail closed). ``ValueError`` covers
#: ``WireRefused``, an ineligible directory, undecodable bytes and the parquet/CSV marker readers.
_UNREADABLE: Final = (SingleReadRefused, FamilyManifestError, ValueError, OSError)


class RootCopyResult(StrEnum):
    """``WRITTEN`` when this call published at least one file; ``EXISTS_EQUAL`` when none."""

    WRITTEN = "written"
    EXISTS_EQUAL = "exists_equal"


class RootCopyIntegrity(Exception):
    """A root copy that cannot be reconciled with what is stored (E-14 rule 4); INTEGRITY."""

    def __init__(self, subject: str) -> None:
        super().__init__(subject)
        self.subject = subject


def _wrong_type(field: str) -> WireRefused:
    return WireRefused(WireRefusalReason.WRONG_TYPE, field)


def _publish(paths: AutonomyPaths | ShadowPaths, path: Path, data: bytes, subject: str) -> bool:
    """Write-once ``data`` at ``path``; ``True`` when it was newly written."""
    try:
        outcome = write_once_tmpfile(path, data, root=paths.root, mode=_ROOT_COPY_MODE)
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.EXISTS_DIFFERENT:
            raise RootCopyIntegrity(subject) from exc
        raise
    return outcome is WriteOutcome.WRITTEN


def _ensure_roots_dir(paths: AutonomyPaths | ShadowPaths, sha_dir: Path) -> None:
    """Create ``<sha>/roots/`` (and its parents) through ``single_read.ensure_dir``."""
    relative = (sha_dir / _ROOTS_DIR).relative_to(paths.root).parts
    rootfd = open_root(paths.root)
    try:
        os.close(ensure_dir(rootfd, relative))
    finally:
        os.close(rootfd)


def write_root_copy(
    paths: AutonomyPaths | ShadowPaths,
    *,
    record: RootRecord,
    artefact_raw: bytes,
    composition_kind: str,
) -> RootCopyResult:
    """Write one root's content-addressed artefact copy and its ``root/v1`` record (E-14).

    ``composition_kind`` is the manifest's kind: the model class is ``"<kind>:density_table"``
    (rule 2). ``artefact_raw`` must hash to ``record.artefact_sha256`` or nothing is written.
    Order: ``artefact.json`` then ``roots/<family_id>.json``, so a crash between them is completed
    by the rerun. Idempotent, including after the directories are sealed 0500.

    Raises :class:`RootCopyIntegrity` on different bytes under either name,
    ``SingleReadRefused`` (``DIR_NOT_WRITABLE`` for a new file in a sealed directory) and
    ``WireRefused`` for a malformed argument.
    """
    if not isinstance(paths, AutonomyPaths | ShadowPaths):
        raise _wrong_type("paths")
    if not isinstance(record, RootRecord):
        raise _wrong_type("record")
    if not isinstance(artefact_raw, bytes):
        raise _wrong_type("artefact_raw")
    model_class = root_model_class(composition_kind)
    if hashlib.sha256(artefact_raw).hexdigest() != record.artefact_sha256:
        raise RootCopyIntegrity("artefact_bytes")
    sha_dir = paths.artefact_dir(model_class, record.artefact_sha256)
    record_path = paths.root_record(model_class, record.artefact_sha256, record.family_id)
    _ensure_roots_dir(paths, sha_dir)
    wrote_artefact = _publish(
        paths,
        paths.artefact_file(model_class, record.artefact_sha256),
        artefact_raw,
        "artefact.json",
    )
    wrote_record = _publish(paths, record_path, canonical_json(record.to_wire()), "root_record")
    if wrote_artefact or wrote_record:
        return RootCopyResult.WRITTEN
    return RootCopyResult.EXISTS_EQUAL


def _read_family_file(
    root: Path, parts: tuple[str, ...], family_id: str, policy: ReadPolicy
) -> bytes | None:
    """The family's manifest bytes under ``root/<parts>``; ``None`` when the file is absent.

    Any other refusal (a symlink, a foreign owner, an open mode under STRICT) propagates.
    """
    rootfd = open_root(root)
    try:
        try:
            dirfd = walk_dirs(rootfd, parts)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return None
            raise
        try:
            assert_prereg_directory_eligible(root.joinpath(*parts))
            return read_once_at(
                dirfd, f"{family_id}.json", max_bytes=_MANIFEST_MAX_BYTES, policy=policy
            )
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return None
            raise
        finally:
            os.close(dirfd)
    finally:
        os.close(rootfd)


def _manifest_source(
    family_id: str, paths: AutonomyPaths | ShadowPaths, repo_root: Path
) -> tuple[bytes, Path] | None:
    """The committed root manifest if the repo has one, else the registry copy (a child).

    A repo file that exists is the only source: a mismatch is never retried against the
    registry (E-14 rule 3a), so a drifted committed root cannot be papered over.
    """
    raw = _read_family_file(repo_root, _COMMITTED_PARTS, family_id, ReadPolicy.REPO)
    if raw is not None:
        return raw, repo_root.joinpath(*_COMMITTED_PARTS, f"{family_id}.json")
    raw = _read_family_file(paths.root, _REGISTRY_PARTS, family_id, ReadPolicy.STRICT)
    if raw is not None:
        return raw, paths.family_file(family_id)
    return None


def read_manifest_facts(
    family_id: str,
    manifest_sha256: str,
    *,
    paths: AutonomyPaths | ShadowPaths,
    repo_root: Path,
) -> ManifestFacts | None:
    """The facts ``transitions.validate`` needs for ``family_id`` at ``manifest_sha256``.

    Bind ``paths`` and ``repo_root`` (``functools.partial``) to obtain a ``ManifestFactsReader``.
    ``None`` for anything unreadable: a malformed id or sha, a missing, symlinked or oddly-owned
    source, bytes whose sha256 differs, a draft or invalid manifest, a PREREG-ineligible
    directory, or a manifest that names another family. Never raises for those.
    """
    try:
        family = family_component(family_id)
        sha = sha_component(manifest_sha256, "manifest_sha256")
        source = _manifest_source(family, paths, repo_root)
        if source is None:
            return None
        raw, path = source
        if hashlib.sha256(raw).hexdigest() != sha:
            return None
        manifest = parse_family_manifest(raw, path=path)
        if manifest.family_id != family:
            return None
        return ManifestFacts(
            family_id=manifest.family_id,
            manifest_sha256=sha,
            d0_climate_day=manifest.d0_climate_day,
            trial_id_prefix=manifest.trial_id_prefix,
            composition_kind=manifest.composition_kind,
        )
    except _UNREADABLE:
        return None
