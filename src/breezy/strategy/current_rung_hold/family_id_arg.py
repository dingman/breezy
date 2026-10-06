"""Shared family-id validation for current-rung-hold operator CLIs."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

from breezy.persistence.family_manifest import (
    FamilyManifest,
    FamilyManifestError,
    load_family_manifest,
)
from breezy.strategy.current_rung_hold.trial_day_latch import FAMILY_ID_PATTERN

#: The composition kinds the manual family-halt CLIs may act on. Both write and
#: read the SAME ``family_halt_key(family_id)`` row (the key namespace is the
#: family id, never the composition kind), so a kind is listed here only when
#: its strategy honours that row through ``family_halt_submit_veto``.
HALTABLE_COMPOSITION_KINDS: Final[frozenset[str]] = frozenset(
    {"continuous_rung_hold", "forecast_quantile_ladder"}
)

#: The haltable kinds whose strategy has an automated EXIT path
#: (``exit_wiring.submit_exit``), which the family halt also vetoes. Only these
#: kinds can have a position stranded by a halt, so only these keep the
#: pre-set open-position refusal. ``forecast_quantile_ladder`` buys IOC qty 1
#: and holds to settlement: no SELL, no exit seam. An explicit pin, never
#: derived from a heuristic.
KINDS_WITH_EXIT_PATH: Final[frozenset[str]] = frozenset({"continuous_rung_hold"})


class FamilyIdArgError(ValueError):
    """Raised when a CLI family id is syntactically or semantically invalid."""


#: The repository root, located from this file (``src/breezy/strategy/
#: current_rung_hold/family_id_arg.py`` -> ``parents[4]``), the same anchor
#: ``runtime.build_sha`` uses for ``breezy.__file__``. NEVER the process cwd:
#: a systemd unit runs the halt CLIs with an arbitrary cwd (2026-10-05).
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]

_FAMILIES_SUBDIR: Final[Path] = Path("deploy") / "families"


def default_families_dir() -> Path:
    """The registered-manifest directory under the repo root, independent of cwd.

    Fails closed: raises :class:`FamilyIdArgError` when it does not exist, never
    falling back to a cwd-relative path.
    """
    families_dir = _REPO_ROOT / _FAMILIES_SUBDIR
    if not families_dir.is_dir():
        raise FamilyIdArgError(
            f"families directory not found at {families_dir} (derived from the installed "
            "package location, not the cwd); pass an absolute --families-dir"
        )
    return families_dir


def evidence_path_arg(value: str) -> Path:
    """argparse ``type`` for ``--evidence-path``: absolute, existing file only.

    A relative path is refused rather than resolved: it used to bind to the
    cwd, and silently hashing a different file than the operator meant would
    corrupt the audit record.
    """
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError(
            f"--evidence-path must be an absolute path (got {value!r}); "
            "relative paths are refused because they depend on the cwd"
        )
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"--evidence-path does not exist: {value}")
    return path


def resolve_haltable_family_arg(family_id: str, families_dir: Path) -> FamilyManifest:
    """Validate and load a manifest of a haltable composition kind for ``family_id``."""
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
            f"no registered haltable-family manifest for --family-id {family_id!r} "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    if manifest.family_id != family_id:
        raise FamilyIdArgError(
            f"manifest family_id {manifest.family_id!r} does not match --family-id {family_id!r}"
        )
    if manifest.composition_kind not in HALTABLE_COMPOSITION_KINDS:
        raise FamilyIdArgError(
            f"manifest composition_kind {manifest.composition_kind!r} is not one of "
            f"{sorted(HALTABLE_COMPOSITION_KINDS)}"
        )
    return manifest
