"""Shared family-id validation for current-rung-hold operator CLIs."""

from __future__ import annotations

from pathlib import Path

from breezy.persistence.family_manifest import (
    FamilyManifest,
    FamilyManifestError,
    load_family_manifest,
)
from breezy.strategy.current_rung_hold.trial_day_latch import FAMILY_ID_PATTERN


class FamilyIdArgError(ValueError):
    """Raised when a CLI family id is syntactically or semantically invalid."""


def resolve_continuous_family_arg(family_id: str, families_dir: Path) -> FamilyManifest:
    """Validate and load a continuous-rung-hold manifest for ``family_id``."""
    if FAMILY_ID_PATTERN.fullmatch(family_id) is None:
        raise FamilyIdArgError(f"invalid --family-id: {family_id!r}")
    root = families_dir.resolve()
    manifest_path = (root / f"{family_id}.json").resolve()
    if not manifest_path.is_relative_to(root):
        raise FamilyIdArgError(f"--family-id resolves outside --families-dir: {family_id!r}")
    try:
        manifest = load_family_manifest(manifest_path)
    except (FamilyManifestError, OSError) as exc:
        raise FamilyIdArgError(
            f"no registered continuous-rung-hold manifest for --family-id {family_id!r} "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    if manifest.family_id != family_id:
        raise FamilyIdArgError(
            f"manifest family_id {manifest.family_id!r} does not match --family-id {family_id!r}"
        )
    if manifest.composition_kind != "continuous_rung_hold":
        raise FamilyIdArgError(
            f"manifest composition_kind {manifest.composition_kind!r} is not continuous_rung_hold"
        )
    return manifest
