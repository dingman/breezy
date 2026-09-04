"""Family manifest -- declared provenance boundary for a v2 family (6f).

Lives under `persistence/`, not `settlement/`: this loader does real file
I/O (`Path.read_bytes`, `json.loads`) and parses a real calendar date
(`datetime.date.fromisoformat`), which the AST-enforced pure `settlement`
package (`tests/unit/test_settlement_purity_guard.py`, rule D1) forbids.
The layer contract (`pyproject.toml` `[tool.importlinter]`) places
`persistence` ABOVE `settlement`, matching `scored_trial_store.py`'s own
direction; `settlement/family_barrier.py` therefore never imports this
module, and instead accepts anything shaped like `FamilyIdentity`
structurally (see that module's docstring).

Blueprint "Family provenance" (`FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md`):
a trial-id prefix separates venues/latches, but cannot separate two
families sharing one latch (PM v1 vs PM v2 both mint
`current_rung_hold/trial/...`). The manifest's own `d0_climate_day` is the
second discriminant -- registered before the family's first fill, never
retroactive (blueprint "Manifest is a declaration, not a cryptographic
fact": a post-D0 edit would relabel rows, so `manifest_sha256` echoes the
canonical file bytes into every report header and any later edit shows up
in git and in the report diff).

`status` guards against exactly that risk for manifests authored before
their family is actually registered: a manifest committed as scaffolding
(this commit's two data files) carries `"status":
"DRAFT_NOT_REGISTERED"` and a placeholder `boundary_inputs_sha256` of
64 zeros, and `load_family_manifest` refuses both unless the caller
explicitly opts in with `allow_draft=True` -- a caller who forgets the flag
gets a loud refusal, never a silently-accepted stub feeding a real tally.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Literal

__all__ = [
    "FamilyManifest",
    "FamilyManifestError",
    "FamilyManifestValidationError",
    "UnregisteredFamilyManifestError",
    "UnpinnedBoundaryArtefactError",
    "load_family_manifest",
]

ManifestStatus = Literal["DRAFT_NOT_REGISTERED", "REGISTERED"]

_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "family_id",
        "venue",
        "trial_id_prefix",
        "d0_climate_day",
        "boundary_artefact_path",
        "boundary_inputs_sha256",
        "stations",
        "status",
    }
)
_STRING_FIELDS: Final[tuple[str, ...]] = (
    "family_id",
    "venue",
    "trial_id_prefix",
    "d0_climate_day",
    "boundary_artefact_path",
    "boundary_inputs_sha256",
    "status",
)
_STATUSES: Final[frozenset[str]] = frozenset({"DRAFT_NOT_REGISTERED", "REGISTERED"})
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_UNPINNED_SHA256: Final[str] = "0" * 64


class FamilyManifestError(Exception):
    """Base for every family-manifest load failure."""


class FamilyManifestValidationError(FamilyManifestError):
    """Malformed manifest: missing/unknown key, wrong type, bad date, bad sha, empty stations."""


class UnregisteredFamilyManifestError(FamilyManifestError):
    """`status == "DRAFT_NOT_REGISTERED"` and the caller did not pass `allow_draft=True`."""


class UnpinnedBoundaryArtefactError(FamilyManifestError):
    """`boundary_inputs_sha256` is the all-zero placeholder and `allow_draft` is `False`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyManifest:
    """One family's declared provenance boundary, plus its own content hash.

    `manifest_sha256` is computed over the manifest file's canonical (raw,
    on-disk) bytes -- never re-serialized -- so reports that echo it detect
    any edit to the committed file, including whitespace-only changes.
    """

    family_id: str
    venue: str
    trial_id_prefix: str
    d0_climate_day: str
    boundary_artefact_path: Path
    boundary_inputs_sha256: str
    stations: tuple[str, ...]
    status: ManifestStatus
    manifest_sha256: str


def load_family_manifest(path: Path, *, allow_draft: bool = False) -> FamilyManifest:
    """Load and strictly validate one family manifest JSON file.

    Every field in `FamilyManifest` is required; any key not in that set is
    refused. `status="DRAFT_NOT_REGISTERED"` and an unpinned (all-zero)
    `boundary_inputs_sha256` are each refused unless `allow_draft=True`.
    """
    raw = path.read_bytes()
    manifest_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FamilyManifestValidationError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise FamilyManifestValidationError(f"{path}: manifest must be a JSON object")

    keys = set(payload)
    missing = _REQUIRED_KEYS - keys
    if missing:
        raise FamilyManifestValidationError(
            f"{path}: missing required key(s): {sorted(missing)}"
        )
    unknown = keys - _REQUIRED_KEYS
    if unknown:
        raise FamilyManifestValidationError(f"{path}: unknown key(s): {sorted(unknown)}")

    for field in _STRING_FIELDS:
        if not isinstance(payload[field], str):
            raise FamilyManifestValidationError(f"{path}: {field!r} must be a string")

    d0_climate_day = payload["d0_climate_day"]
    try:
        date.fromisoformat(d0_climate_day)
    except ValueError as exc:
        raise FamilyManifestValidationError(
            f"{path}: d0_climate_day {d0_climate_day!r} is not a real ISO-8601 date"
        ) from exc

    status = payload["status"]
    if status not in _STATUSES:
        raise FamilyManifestValidationError(
            f"{path}: status {status!r} not one of {sorted(_STATUSES)}"
        )
    if status == "DRAFT_NOT_REGISTERED" and not allow_draft:
        raise UnregisteredFamilyManifestError(
            f"{path}: family is DRAFT_NOT_REGISTERED; pass allow_draft=True to load anyway"
        )

    sha = payload["boundary_inputs_sha256"]
    if not _SHA256_RE.match(sha):
        raise FamilyManifestValidationError(
            f"{path}: boundary_inputs_sha256 must be 64 lowercase hex characters"
        )
    if sha == _UNPINNED_SHA256 and not allow_draft:
        raise UnpinnedBoundaryArtefactError(
            f"{path}: boundary_inputs_sha256 is the unpinned all-zero placeholder; "
            "pass allow_draft=True to load anyway"
        )

    stations_raw = payload["stations"]
    if (
        not isinstance(stations_raw, list)
        or not stations_raw
        or not all(isinstance(station, str) for station in stations_raw)
    ):
        raise FamilyManifestValidationError(
            f"{path}: stations must be a non-empty list of strings"
        )

    return FamilyManifest(
        family_id=payload["family_id"],
        venue=payload["venue"],
        trial_id_prefix=payload["trial_id_prefix"],
        d0_climate_day=d0_climate_day,
        boundary_artefact_path=Path(payload["boundary_artefact_path"]),
        boundary_inputs_sha256=sha,
        stations=tuple(stations_raw),
        status=status,
        manifest_sha256=manifest_sha256,
    )
