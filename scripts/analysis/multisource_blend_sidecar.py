"""F13 Phase A: the feature-file sidecar contract shared by the builder and the runner.

The builder writes ``<features>.manifest.json`` next to each feature file; the runner refuses to
score unless both sidecars are present, match their files and agree with each other (FB-R10/FB-R14).
This module holds the schema constants, the chunked file hash, and the checks. It imports no
script, so both ends can use it without a cycle; a failed check raises :class:`Refusal`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from breezy.analysis.multisource_blend_features import LAG_SHIFT_NS
from scripts.analysis.multisource_blend_refusal import Refusal

__all__ = [
    "ANCHOR_VARIANTS",
    "HASH_CHUNK_BYTES",
    "PRIMARY_VARIANT",
    "SENSITIVITY_VARIANT",
    "SIDECAR_SCHEMA",
    "SIDECAR_SUFFIX",
    "check_sidecar",
    "check_sidecar_pair",
    "check_sidecar_row_count",
    "sha256_file",
]

#: FB-R10: ``<features>.manifest.json`` written by ``multisource_blend_features_build.py``.
SIDECAR_SUFFIX: Final[str] = ".manifest.json"
SIDECAR_SCHEMA: Final[str] = "f13_features_manifest_v1"
PRIMARY_VARIANT: Final[str] = "primary"
SENSITIVITY_VARIANT: Final[str] = "d0_12lst"
ANCHOR_VARIANTS: Final[tuple[str, ...]] = (PRIMARY_VARIANT, SENSITIVITY_VARIANT)
HASH_CHUNK_BYTES: Final[int] = 1 << 20
#: fields the two files of one build must share exactly
_SHARED_FIELDS: Final[tuple[str, ...]] = (
    "anchor_variant",
    "anchors",
    "source_lags_ns",
    "obs_routine_minute_by_station",
    "prereg_content_sha256",
)
_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "role",
    "features_sha256",
    "n_rows",
    "lag_shift_ns",
    *_SHARED_FIELDS,
)
_EXPECTED_SHIFT_NS: Final[Mapping[str, int]] = {"primary": 0, "lag": LAG_SHIFT_NS}


def sha256_file(path: Path, chunk_size: int = HASH_CHUNK_BYTES) -> str:
    """Hex SHA-256 of a file, read in chunks (a feature file can be large)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_path(features: Path) -> Path:
    return Path(str(features) + SIDECAR_SUFFIX)


def _read_sidecar(features: Path) -> dict[str, Any]:
    sidecar = sidecar_path(features)
    if not sidecar.exists():
        raise Refusal(
            f"{features}: no sidecar {sidecar.name}; a scoring run requires the builder's manifest "
            "binding the features to the prereg (FB-R14)"
        )
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refusal(f"cannot read the sidecar {sidecar}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(meta, dict):
        raise Refusal(f"cannot read the sidecar {sidecar}: not a JSON object")
    missing = [key for key in _REQUIRED_FIELDS if key not in meta]
    if missing:
        raise Refusal(f"{sidecar}: required sidecar field(s) missing: {missing}")
    return meta


def check_sidecar(
    path: Path, *, role: str, prereg_digest: str, expected_variant: str
) -> dict[str, Any]:
    """The sidecar of ``path`` against the file and the prereg; returns its parsed body.

    A missing sidecar is a Refusal (no production bypass). So is one that cannot be read, lacks a
    cross-checked field, names another role, schema or anchor variant, records a lag shift that is
    wrong for its role, or disagrees with the file's bytes or the prereg digest.
    """
    meta = _read_sidecar(path)
    sidecar = sidecar_path(path)
    if meta["schema"] != SIDECAR_SCHEMA:
        raise Refusal(f"{sidecar}: schema {meta['schema']!r} is not {SIDECAR_SCHEMA!r}")
    if meta["role"] != role:
        raise Refusal(f"{sidecar}: role {meta['role']!r} but {path} is loaded as the {role!r} file")
    actual_sha = sha256_file(path)
    if meta["features_sha256"] != actual_sha:
        raise Refusal(
            f"{path}: sha256 {actual_sha} does not match the sidecar's {meta['features_sha256']}; "
            "the feature file changed since the builder wrote it"
        )
    if meta["prereg_content_sha256"] != prereg_digest:
        raise Refusal(
            f"{sidecar}: built under prereg digest {meta['prereg_content_sha256']}, but this "
            f"run's prereg digest is {prereg_digest}"
        )
    if meta["anchor_variant"] != expected_variant:
        raise Refusal(
            f"{sidecar}: anchor_variant {meta['anchor_variant']!r} but this run scores the "
            f"{expected_variant!r} pair (the 12 LST sensitivity is selected explicitly)"
        )
    expected_shift = _EXPECTED_SHIFT_NS[role]
    if meta["lag_shift_ns"] != expected_shift:
        raise Refusal(
            f"{sidecar}: lag_shift_ns {meta['lag_shift_ns']!r} but the {role!r} file must "
            f"record {expected_shift}"
        )
    return meta


def check_sidecar_pair(primary: Mapping[str, Any], lag: Mapping[str, Any]) -> None:
    """Both files of one build record the same variant, pins and prereg digest."""
    for field in _SHARED_FIELDS:
        if primary[field] != lag[field]:
            raise Refusal(
                f"the primary and lag sidecars disagree on {field}: "
                f"{primary[field]!r} vs {lag[field]!r}"
            )


def check_sidecar_row_count(meta: Mapping[str, Any], path: Path, n_rows: int) -> None:
    """The sidecar's ``n_rows`` equals the rows actually loaded from the file."""
    recorded = meta["n_rows"]
    if isinstance(recorded, bool) or recorded != n_rows:
        raise Refusal(f"{path}: sidecar n_rows {recorded!r} but the file holds {n_rows} rows")
