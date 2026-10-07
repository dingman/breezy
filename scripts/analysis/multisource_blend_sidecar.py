"""F13 Phase A: the feature-file sidecar contract shared by the builder and the runner.

The builder writes ``<features>.manifest.json`` next to each feature file; the runner refuses to
score unless both sidecars are present, match their files and agree with each other (FB-R10/FB-R14).
This module holds the schema constants, the chunked file hash, and the checks. It imports no
script, so both ends can use it without a cycle; a failed check raises :class:`Refusal`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from breezy.analysis.multisource_blend_features import LAG_SHIFT_NS, FeatureRow
from scripts.analysis.multisource_blend_refusal import Refusal
from scripts.analysis.settlement_alignment_study import IEM_ASOS_IDS

__all__ = [
    "ANCHOR_VARIANTS",
    "HASH_CHUNK_BYTES",
    "PRIMARY_VARIANT",
    "SENSITIVITY_VARIANT",
    "SIDECAR_SCHEMA",
    "SIDECAR_SUFFIX",
    "check_rows_not_excluded",
    "check_sidecar",
    "check_sidecar_lags_match_prereg",
    "check_sidecar_pair",
    "check_sidecar_row_count",
    "draft_scratch_digest",
    "excluded_digest",
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
    "source_breaks_observed",
    "obs_excluded_station_years",
    "obs_excluded_station_years_sha256",
)
_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "role",
    "features_sha256",
    "n_rows",
    "lag_shift_ns",
    "scoring",
    *_SHARED_FIELDS,
)
_EXPECTED_SHIFT_NS: Final[Mapping[str, int]] = {"primary": 0, "lag": LAG_SHIFT_NS}


def draft_scratch_digest(prereg_digest: str) -> str:
    """The prereg digest a ``--draft-scratch`` build records (PIN-R8a).

    It can never equal a real prereg digest, so a draft sidecar edited to ``scoring: true`` still
    fails the digest binding in :func:`check_sidecar`.
    """
    return hashlib.sha256(f"{prereg_digest}:scoring=false".encode()).hexdigest()


def excluded_digest(station_years: Sequence[str]) -> str:
    """SHA-256 of the sorted excluded station-year list (PIN-R4), recorded next to the list."""
    body = json.dumps(sorted(station_years), separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


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
    if meta["scoring"] is not True:
        raise Refusal(
            f"{sidecar}: scoring is {meta['scoring']!r}: a --draft-scratch build is never scored "
            "(PIN-R8a); rebuild from the frozen prereg"
        )
    _check_excluded_binding(sidecar, meta)
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


def _check_excluded_binding(sidecar: Path, meta: Mapping[str, Any]) -> None:
    listed = meta["obs_excluded_station_years"]
    if not isinstance(listed, list) or not all(isinstance(item, str) for item in listed):
        raise Refusal(f"{sidecar}: obs_excluded_station_years must be a list of station-years")
    if meta["obs_excluded_station_years_sha256"] != excluded_digest(listed):
        raise Refusal(
            f"{sidecar}: obs_excluded_station_years {listed} does not match its recorded "
            "obs_excluded_station_years_sha256 (PIN-R4)"
        )


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


def _excluded_cells(meta: Mapping[str, Any], path: Path) -> dict[tuple[str, int], str]:
    """``{(station key, LST year): entry}`` for the sidecar's ``ICAO/year`` exclusion entries."""
    cells: dict[tuple[str, int], str] = {}
    for item in meta["obs_excluded_station_years"]:
        icao, _, year = str(item).partition("/")
        if not icao or not year.isdigit():
            raise Refusal(
                f"{path}: obs_excluded_station_years entry {item!r} is not '<station>/<year>'"
            )
        cells[(IEM_ASOS_IDS.get(icao, icao), int(year))] = str(item)
    return cells


def check_rows_not_excluded(
    rows: Sequence[FeatureRow], meta: Mapping[str, Any], path: Path
) -> None:
    """Refuse when a loaded row lies in a station-year the sidecar lists as excluded (PIN-R4).

    ``climate_day`` is the local-standard-time climate day, so its year is the LST climate year.
    A row's station is the settlement key (``NYC``); the list names ICAOs (``KNYC``).
    """
    cells = _excluded_cells(meta, path)
    hit = sorted(
        {
            cells[(row.station, row.climate_day.year)]
            for row in rows
            if (row.station, row.climate_day.year) in cells
        }
    )
    if hit:
        raise Refusal(
            f"{path}: {len(hit)} excluded station-year(s) {hit} still have rows although "
            "obs_excluded_station_years lists them (PIN-R4)"
        )


def check_sidecar_lags_match_prereg(
    meta: Mapping[str, Any], design: Mapping[str, Any], path: Path
) -> None:
    """The sidecar's ``source_lags_ns`` equals the prereg-pinned ``source_lags_ns`` (FB-R10)."""
    pinned = design["pins"]["source_lags_ns"]
    if meta["source_lags_ns"] != pinned:
        raise Refusal(
            f"{path}: sidecar source_lags_ns {meta['source_lags_ns']!r} differs from the "
            f"prereg-pinned source_lags_ns {pinned!r}"
        )
