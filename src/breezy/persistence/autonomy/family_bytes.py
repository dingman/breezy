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

``verify_family_bytes`` (ARCH-0 seam A 8c; AC 17 steps 9-11, AUT-7 E10) is the one byte-binding
verifier the resolver and the engine share. It reads a family's manifest and artefact through the
single-read rule and answers ``FamilyBytes`` or ``ByteBindingFailure``:

* a root (origin ``ROOT``) reads its manifest only from the committed ``deploy/families/<id>.json``
  (REPO policy, never a registry copy: E-14 rule 3a; A6d-A2 M2), its artefact from
  ``<kind>:density_table`` and its ``root/v1`` record from ``roots/<id>.json`` (E-14 rule 3b);
* a child reads ``registry/families/<id>.json`` (STRICT), requires its id to be ``<root>_rNNNN``
  (the root named by the caller, if it names one), equal to the committed root manifest on every
  field outside ``CHILD_MANIFEST_ALLOWLIST`` (ARCH 4.2), and finds its artefact by probing
  ``pins.MODEL_CLASS_COMPONENTS`` (exactly one match, A8b-R2).

Choices ARCH leaves open, fixed here: ``verify_bound_bytes`` is the keyword form (the resolver binds
the fold's latest manifest sha and the introducing artefact sha, which no single row carries);
``verify_family_bytes(row, ...)`` is its thin wrapper over one row's columns.

Refusals carry closed names, never paths.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.fold import Origin
from breezy.persistence.autonomy.lineage import RootRecord, model_class_of, root_model_class
from breezy.persistence.autonomy.paths import (
    AutonomyPaths,
    ShadowPaths,
    family_component,
    sha_component,
    venue_component,
)
from breezy.persistence.autonomy.schemas import Kind, ManifestFacts, RefusalReason, TransitionRow
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
from breezy.persistence.autonomy.wire import WireRefusalReason, WireRefused, parse_json_exact
from breezy.persistence.family_manifest import (
    FamilyManifest,
    FamilyManifestError,
    UnpinnedBoundaryArtefactError,
    UnpinnedDensityArtefactError,
    UnregisteredFamilyManifestError,
    parse_family_manifest,
)
from breezy.persistence.live_orders_gate import CHILD_FAMILY_ID_RE
from breezy.persistence.mechanism_test_guard import (
    MechanismTestIneligibleError,
    assert_prereg_directory_eligible,
)

__all__ = [
    "CHILD_MANIFEST_ALLOWLIST",
    "ByteBindingFailure",
    "FamilyBytes",
    "RootCopyIntegrity",
    "RootCopyResult",
    "manifest_equal_modulo_allowlist",
    "probe_artefact",
    "read_artefact",
    "read_manifest_facts",
    "roots_of",
    "verify_bound_bytes",
    "verify_family_bytes",
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


def roots_of(rows: Iterable[TransitionRow]) -> frozenset[str]:
    """The families a BOOTSTRAP or ROOT_ADMIT introduced: their manifests are repo-only."""
    first: dict[str, Kind] = {}
    for row in rows:
        first.setdefault(row.family_id, row.kind)
    return frozenset(f for f, k in first.items() if k in (Kind.BOOTSTRAP, Kind.ROOT_ADMIT))


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
    family_id: str, paths: AutonomyPaths | ShadowPaths, repo_root: Path, *, repo_only: bool
) -> tuple[bytes, Path] | None:
    """The committed root manifest if the repo has one, else the registry copy (a child).

    A repo file that exists is the only source: a mismatch is never retried against the
    registry (E-14 rule 3a), so a drifted committed root cannot be papered over. With
    ``repo_only`` (a root: E-14 3a, A6d-A2 M2) the registry copy is never consulted at all.
    """
    raw = _read_family_file(repo_root, _COMMITTED_PARTS, family_id, ReadPolicy.REPO)
    if raw is not None:
        return raw, repo_root.joinpath(*_COMMITTED_PARTS, f"{family_id}.json")
    if repo_only:
        return None
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
    repo_only: bool = False,
    roots: Collection[str] = (),
) -> ManifestFacts | None:
    """The facts ``transitions.validate`` needs for ``family_id`` at ``manifest_sha256``.

    Bind ``paths`` and ``repo_root`` (``functools.partial``) to obtain a ``ManifestFactsReader``.
    ``repo_only`` is for a root: its manifest is the committed repo file or nothing, never a
    registry copy (E-14 rule 3a; the replay passes it for every family a root introduced).
    ``roots`` (the store binds a live set of them) makes any family named in it ``repo_only``.
    ``None`` for anything unreadable: a malformed id or sha, a missing, symlinked or oddly-owned
    source, bytes whose sha256 differs, a draft or invalid manifest, a PREREG-ineligible
    directory, or a manifest that names another family. Never raises for those.
    """
    try:
        family = family_component(family_id)
        sha = sha_component(manifest_sha256, "manifest_sha256")
        source = _manifest_source(family, paths, repo_root, repo_only=repo_only or family in roots)
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


# --- the byte-binding verifier (seam 8c) ---------------------------------------------------------

#: ARCH 4.2: a child equals its committed root on every manifest field except these, and the
#: ``manifest_sha256`` that is the hash of the file itself.
CHILD_MANIFEST_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "family_id",
        "trial_id_prefix",
        "d0_climate_day",
        "density_artefact_path",
        "density_artefact_sha256",
        "live_orders_ruling",
    }
)
_ARTEFACT_NAME: Final = "artefact.json"
_RECORD_MAX_BYTES: Final = 4096
_UNPINNED: Final = (UnpinnedBoundaryArtefactError, UnpinnedDensityArtefactError)

ManifestSource = Literal["deploy", "registry"]


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyBytes:
    """The bytes a verified family stands on: its manifest, parsed, and its artefact, both raw.

    ``artefact_store_relpath`` is relative to the data root
    (``derived/artefacts/<model_class>/<sha>/artefact.json``): the node loads the artefact from
    there and re-verifies it by sha.
    """

    manifest: FamilyManifest
    manifest_raw: bytes
    manifest_sha256: str
    manifest_source: ManifestSource
    artefact_raw: bytes
    artefact_sha256: str
    artefact_store_relpath: str


@dataclass(frozen=True, slots=True)
class ByteBindingFailure:
    """The bytes cannot be bound to the row: ``reason`` is a closed ``RefusalReason``."""

    reason: RefusalReason


def manifest_equal_modulo_allowlist(
    child: object,
    root: object,
    *,
    fields_of: Callable[[type[FamilyManifest]], Iterable[object]] = dataclasses.fields,
) -> tuple[str, ...]:
    """The manifest fields (sorted) on which ``child`` differs from ``root``, allowlist excluded.

    Every field of ``FamilyManifest`` is compared, so a field added later is covered without an
    edit here (``fields_of`` is a test seam). ``manifest_sha256`` is the file's own hash and is
    never compared. An empty tuple means the child equals its root modulo the allowlist.
    """
    skipped = CHILD_MANIFEST_ALLOWLIST | {"manifest_sha256"}
    names = [str(getattr(f, "name")) for f in fields_of(FamilyManifest)]  # noqa: B009
    return tuple(
        sorted(
            n
            for n in names
            if n not in skipped and getattr(child, n, None) != getattr(root, n, None)
        )
    )


def read_artefact(paths: AutonomyPaths | ShadowPaths, model_class: str, sha: str) -> bytes | None:
    """The artefact's bytes, or ``None`` for anything but a clean STRICT read."""
    parts = paths.artefact_dir(model_class, sha).relative_to(paths.root).parts
    try:
        rootfd = open_root(paths.root)
    except SingleReadRefused:
        return None
    try:
        dirfd = walk_dirs(rootfd, parts)
        try:
            return read_once_at(
                dirfd, _ARTEFACT_NAME, max_bytes=pins.ARTEFACT_MAX_BYTES, policy=ReadPolicy.STRICT
            )
        finally:
            os.close(dirfd)
    except SingleReadRefused:
        return None
    finally:
        os.close(rootfd)


def probe_artefact(
    kind: str, sha: str, *, read: Callable[[str, str], bytes | None]
) -> tuple[str, bytes] | None:
    """``(model_class, bytes)`` of the one component of ``kind`` that holds ``sha``, else ``None``.

    Zero or several matches give ``None`` (A8b-R2). ``ValueError`` for a ``kind`` that is no path
    component propagates.
    """
    found: list[tuple[str, bytes]] = []
    for component in pins.MODEL_CLASS_COMPONENTS:
        model_class = model_class_of(kind, component)
        raw = read(model_class, sha)
        if raw is not None:
            found.append((model_class, raw))
    return found[0] if len(found) == 1 else None


def _read_root_record(
    paths: AutonomyPaths | ShadowPaths, model_class: str, sha: str, family_id: str
) -> RootRecord | None:
    """The family's ``root/v1`` record beside the artefact, or ``None`` for any unclean read."""
    parts = paths.root_record(model_class, sha, family_id).relative_to(paths.root).parts
    try:
        rootfd = open_root(paths.root)
    except SingleReadRefused:
        return None
    try:
        dirfd = walk_dirs(rootfd, parts[:-1])
        try:
            raw = read_once_at(
                dirfd, parts[-1], max_bytes=_RECORD_MAX_BYTES, policy=ReadPolicy.STRICT
            )
        finally:
            os.close(dirfd)
        return RootRecord.from_wire(parse_json_exact(raw))
    except (SingleReadRefused, ValueError):
        return None
    finally:
        os.close(rootfd)


def _refusal_of(exc: Exception) -> RefusalReason:
    """The closed reason a manifest read or parse failure maps to (no path, no message)."""
    if isinstance(exc, MechanismTestIneligibleError):
        return RefusalReason.PREREG_INELIGIBLE
    if isinstance(exc, UnregisteredFamilyManifestError):
        return RefusalReason.MANIFEST_DRAFT
    if isinstance(exc, _UNPINNED):
        return RefusalReason.MANIFEST_UNPINNED
    if isinstance(exc, FamilyManifestError):
        return RefusalReason.MANIFEST_INVALID
    return RefusalReason.MANIFEST_UNREADABLE


def _load_manifest(
    family: str, sha: str, *, paths: AutonomyPaths | ShadowPaths, repo_root: Path, origin: Origin
) -> tuple[bytes, FamilyManifest, ManifestSource] | RefusalReason:
    """The manifest of ``family`` read from its one source and bound to ``sha``."""
    root_origin = origin is Origin.ROOT
    base, parts = (repo_root, _COMMITTED_PARTS) if root_origin else (paths.root, _REGISTRY_PARTS)
    policy = ReadPolicy.REPO if root_origin else ReadPolicy.STRICT
    try:
        raw = _read_family_file(base, parts, family, policy)
        if raw is None:
            return RefusalReason.MANIFEST_UNREADABLE
        if hashlib.sha256(raw).hexdigest() != sha:
            return RefusalReason.MANIFEST_SHA_MISMATCH
        manifest = parse_family_manifest(raw, path=base.joinpath(*parts, f"{family}.json"))
    except (SingleReadRefused, FamilyManifestError, ValueError, OSError) as exc:
        return _refusal_of(exc)
    source: ManifestSource = "deploy" if root_origin else "registry"
    return raw, manifest, source


def _child_problem(
    manifest: FamilyManifest, family: str, *, repo_root: Path, expected_root: str | None
) -> RefusalReason | None:
    """A child's id must be ``<root>_rNNNN`` and its manifest equal the committed root's."""
    matched = CHILD_FAMILY_ID_RE.match(family)
    if matched is None or (expected_root is not None and matched.group("root") != expected_root):
        return RefusalReason.CHILD_ROOT_MISMATCH
    root_id = matched.group("root")
    try:
        root_raw = _read_family_file(repo_root, _COMMITTED_PARTS, root_id, ReadPolicy.REPO)
        if root_raw is None:
            return RefusalReason.MANIFEST_UNREADABLE
        root = parse_family_manifest(
            root_raw, path=repo_root.joinpath(*_COMMITTED_PARTS, f"{root_id}.json")
        )
    except (SingleReadRefused, FamilyManifestError, ValueError, OSError) as exc:
        return _refusal_of(exc)
    if manifest_equal_modulo_allowlist(manifest, root):
        return RefusalReason.CHILD_NOT_EQUAL_ROOT
    return None


def _artefact_for(
    manifest: FamilyManifest, sha: str, *, paths: AutonomyPaths | ShadowPaths, origin: Origin
) -> tuple[str, bytes] | RefusalReason:
    """``(model_class, bytes)`` of the artefact whose sha256 is ``sha``."""
    try:
        if origin is Origin.ROOT:
            model_class = root_model_class(manifest.composition_kind)
            raw = read_artefact(paths, model_class, sha)
            found = None if raw is None else (model_class, raw)
        else:
            found = probe_artefact(
                manifest.composition_kind, sha, read=lambda mc, s: read_artefact(paths, mc, s)
            )
    except ValueError:
        return RefusalReason.ARTEFACT_UNREADABLE
    if found is None:
        return RefusalReason.ARTEFACT_UNREADABLE
    if hashlib.sha256(found[1]).hexdigest() != sha:
        return RefusalReason.ARTEFACT_SHA_MISMATCH
    return found


def _root_record_problem(
    paths: AutonomyPaths | ShadowPaths, model_class: str, family: str, msha: str, asha: str
) -> RefusalReason | None:
    """E-14 rule 3b: ``roots/<family>.json`` names this family, manifest, artefact and path."""
    record = _read_root_record(paths, model_class, asha, family)
    if record is None or (record.family_id, record.manifest_sha256, record.artefact_sha256) != (
        family,
        msha,
        asha,
    ):
        return RefusalReason.ROOT_RECORD_MISMATCH
    return None


def verify_bound_bytes(
    *,
    venue: str,
    family_id: str,
    manifest_sha256: str | None,
    artefact_sha256: str | None,
    paths: AutonomyPaths | ShadowPaths,
    repo_root: Path,
    origin: Origin,
    expected_root: str | None = None,
) -> FamilyBytes | ByteBindingFailure:
    """Bind a family's manifest and artefact bytes to the shas its rows name (see module doc).

    ``expected_root`` is the lineage root the fold names for a child; a regex root that differs is
    ``child_root_mismatch``. Never raises for an unreadable or mismatched file.
    """
    try:
        family = family_component(family_id)
        venue_component(venue)
        msha = sha_component(manifest_sha256, "manifest_sha256")
    except WireRefused:
        return ByteBindingFailure(RefusalReason.MANIFEST_UNREADABLE)
    loaded = _load_manifest(family, msha, paths=paths, repo_root=repo_root, origin=origin)
    if isinstance(loaded, RefusalReason):
        return ByteBindingFailure(loaded)
    raw, manifest, source = loaded
    if manifest.family_id != family or manifest.venue != venue:
        return ByteBindingFailure(RefusalReason.MANIFEST_IDENTITY_MISMATCH)
    if origin is Origin.CHILD:
        problem = _child_problem(manifest, family, repo_root=repo_root, expected_root=expected_root)
        if problem is not None:
            return ByteBindingFailure(problem)
    try:
        asha = sha_component(artefact_sha256, "artefact_sha256")
    except WireRefused:
        return ByteBindingFailure(RefusalReason.ARTEFACT_UNREADABLE)
    artefact = _artefact_for(manifest, asha, paths=paths, origin=origin)
    if isinstance(artefact, RefusalReason):
        return ByteBindingFailure(artefact)
    model_class, artefact_raw = artefact
    if origin is Origin.ROOT:
        problem = _root_record_problem(paths, model_class, family, msha, asha)
        if problem is not None:
            return ByteBindingFailure(problem)
    relpath = paths.artefact_file(model_class, asha).relative_to(paths.root).as_posix()
    return FamilyBytes(
        manifest=manifest,
        manifest_raw=raw,
        manifest_sha256=msha,
        manifest_source=source,
        artefact_raw=artefact_raw,
        artefact_sha256=asha,
        artefact_store_relpath=relpath,
    )


def verify_family_bytes(
    row: TransitionRow,
    *,
    paths: AutonomyPaths | ShadowPaths,
    repo_root: Path,
    origin: Origin,
    expected_root: str | None = None,
) -> FamilyBytes | ByteBindingFailure:
    """``verify_bound_bytes`` over one row's own ``manifest_sha256`` and ``artefact_sha256``."""
    return verify_bound_bytes(
        venue=row.venue,
        family_id=row.family_id,
        manifest_sha256=row.manifest_sha256,
        artefact_sha256=row.artefact_sha256,
        paths=paths,
        repo_root=repo_root,
        origin=origin,
        expected_root=expected_root,
    )
