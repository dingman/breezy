"""Byte binding: the one verifier the resolver and the engine share (ARCH-0 seam A 8c).

``verify_family_bytes`` (AC 17 steps 9-11, AUT-7 E10) reads a family's manifest and artefact through
the single-read rule and answers ``FamilyBytes`` or ``ByteBindingFailure``:

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

Split out of ``family_bytes`` (A8c-R7) so the store, which needs only the manifest-facts reader,
does not pull in ``live_orders_gate``. Refusals carry closed names, never paths.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.family_bytes import (
    _COMMITTED_PARTS,
    _REGISTRY_PARTS,
    _read_family_file,
)
from breezy.persistence.autonomy.fold import Origin
from breezy.persistence.autonomy.lineage import RootRecord, model_class_of, root_model_class
from breezy.persistence.autonomy.paths import (
    AutonomyPaths,
    ShadowPaths,
    family_component,
    sha_component,
    venue_component,
)
from breezy.persistence.autonomy.schemas import RefusalReason, TransitionRow
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadRefused,
    open_root,
    read_once_at,
    walk_dirs,
)
from breezy.persistence.autonomy.wire import WireRefused, parse_json_exact
from breezy.persistence.family_manifest import (
    FamilyManifest,
    FamilyManifestError,
    UnpinnedBoundaryArtefactError,
    UnpinnedDensityArtefactError,
    UnregisteredFamilyManifestError,
    parse_family_manifest,
)
from breezy.persistence.live_orders_gate import CHILD_FAMILY_ID_RE
from breezy.persistence.mechanism_test_guard import MechanismTestIneligibleError

__all__ = [
    "CHILD_MANIFEST_ALLOWLIST",
    "ByteBindingFailure",
    "FamilyBytes",
    "manifest_equal_modulo_allowlist",
    "probe_artefact",
    "read_artefact",
    "verify_bound_bytes",
    "verify_family_bytes",
]

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
