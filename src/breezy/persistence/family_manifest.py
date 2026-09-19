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

`exit_rule` (optional, added for the intra-day position monitor, INC-1) is
an OPTIONAL widening of the exact-set key barrier: a manifest may declare
it, but declaring it does not itself grant exit capability -- that
requires the separate `persistence/exit_gate.py` allowlist to also name
the family (see that module's docstring for why the split is unforgeable).
A present `exit_rule` must be a non-empty string; an absent one loads as
`None`. Every other key in `_REQUIRED_KEYS` stays mandatory and the
exact-set refusal for a genuinely unknown key is unchanged (L-12).
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
    "CompositionKind",
    "FamilyManifest",
    "FamilyManifestError",
    "FamilyManifestValidationError",
    "UnpinnedBoundaryArtefactError",
    "UnpinnedDensityArtefactError",
    "UnregisteredFamilyManifestError",
    "load_family_manifest",
]

ManifestStatus = Literal["DRAFT_NOT_REGISTERED", "REGISTERED"]

#: WP-11b (active-family registry, cardinality-1): which strategy builder a
#: manifest dispatches to. ``forecast_ladder`` is wired here so the exact-set
#: is complete, but its strategy does not exist yet -- a boot attempt refuses
#: (``app/trade.py``) until WP-14 lands. Never a bool alongside another bool:
#: this is the ONE slot that names the composition, matching the manifest's
#: own cardinality-1 ``family_id``.
CompositionKind = Literal["current_rung_hold", "continuous_rung_hold", "forecast_ladder"]
_COMPOSITION_KINDS: Final[frozenset[str]] = frozenset(
    {"current_rung_hold", "continuous_rung_hold", "forecast_ladder"}
)

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
        "composition_kind",
        "density_artefact_path",
        "density_artefact_sha256",
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
    "composition_kind",
    "density_artefact_path",
    "density_artefact_sha256",
)
_OPTIONAL_KEYS: Final[frozenset[str]] = frozenset({"exit_rule"})
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


class UnpinnedDensityArtefactError(FamilyManifestError):
    """`density_artefact_sha256` is the all-zero placeholder and `allow_draft` is `False`.

    Same pin shape as :class:`UnpinnedBoundaryArtefactError` (WP-11b F2 /
    WP-13 L-12): a family's density table travels as a sha-pinned on-disk
    DATA artefact named by the manifest, never a `src/` constant.
    """


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
    #: WP-11b: which strategy builder this family dispatches to. Required
    #: (no default) -- every manifest, including every pre-existing one,
    #: was updated in the WP-11b commit to declare it.
    composition_kind: CompositionKind
    #: WP-11b F2 / WP-13 L-12: on-disk DATA artefact for the family's
    #: density/hold-probability table, sha-pinned the same way as
    #: ``boundary_artefact_path`` / ``boundary_inputs_sha256`` above.
    #: ``current_rung_hold`` / ``continuous_rung_hold`` families pin the
    #: committed sentinel (``deploy/families/artefacts/
    #: not_applicable_density.json``); ``forecast_ladder`` families pin the
    #: real table minted at WP-13.
    density_artefact_path: Path
    density_artefact_sha256: str
    exit_rule: str | None = None


def load_family_manifest(path: Path, *, allow_draft: bool = False) -> FamilyManifest:
    """Load and strictly validate one family manifest JSON file.

    Every key in `_REQUIRED_KEYS` is required; `exit_rule` is the sole
    optional key (`_OPTIONAL_KEYS`); any key outside that combined set is
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
    unknown = keys - _REQUIRED_KEYS - _OPTIONAL_KEYS
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

    composition_kind = payload["composition_kind"]
    if composition_kind not in _COMPOSITION_KINDS:
        raise FamilyManifestValidationError(
            f"{path}: composition_kind {composition_kind!r} not one of "
            f"{sorted(_COMPOSITION_KINDS)}"
        )

    density_sha = payload["density_artefact_sha256"]
    if not _SHA256_RE.match(density_sha):
        raise FamilyManifestValidationError(
            f"{path}: density_artefact_sha256 must be 64 lowercase hex characters"
        )
    if density_sha == _UNPINNED_SHA256 and not allow_draft:
        raise UnpinnedDensityArtefactError(
            f"{path}: density_artefact_sha256 is the unpinned all-zero placeholder; "
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

    exit_rule = payload.get("exit_rule")
    if exit_rule is not None and (not isinstance(exit_rule, str) or not exit_rule):
        raise FamilyManifestValidationError(
            f"{path}: exit_rule must be a non-empty string when present"
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
        composition_kind=composition_kind,
        density_artefact_path=Path(payload["density_artefact_path"]),
        density_artefact_sha256=density_sha,
        exit_rule=exit_rule,
    )
