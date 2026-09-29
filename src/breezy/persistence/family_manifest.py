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

`taker_fee_coefficient` (REQUIRED) is the venue taker theta this family's
break-even was computed against. It lives HERE rather than as a `src/`
constant or an environment variable for the reason `d0_climate_day` does:
the cost basis is part of the family's ESTIMAND, so a different theta is a
different family, and a family is only real once its manifest is committed,
content-hashed (`manifest_sha256`), and `REGISTERED`. Re-pricing a running
family in place would silently change what its in-flight sequential test is
measuring (L-34). The value travels as a STRING-DECIMAL and is parsed to
`Decimal` through a deliberately narrow ``0.`` + 1-6 digits screen -- never
`float`, and never `Decimal`'s own permissive grammar, which accepts
`6.95E-2`, `NaN`, `Infinity`, and surrounding whitespace.

`terminal_climate_day` (optional) closes a family's tally at the TOP.
`d0_climate_day` alone is a lower bound, so a superseded family would go on
admitting its successor's rows -- pooling trials priced at a different cost
basis into an in-flight alpha-spending sequence. A family that has been
superseded declares its last climate day here; `settlement/family_barrier.py`
enforces it inclusively. Absent means unbounded above, exactly the
pre-existing behaviour.

`exit_rule` (optional, added for the intra-day position monitor, INC-1) is
an OPTIONAL widening of the exact-set key barrier: a manifest may declare
it, but declaring it does not itself grant exit capability -- that
requires the separate `persistence/exit_gate.py` allowlist to also name
the family (see that module's docstring for why the split is unforgeable).
A present `exit_rule` must be a non-empty string; an absent one loads as
`None`. Every other key in `_REQUIRED_KEYS` stays mandatory and the
exact-set refusal for a genuinely unknown key is unchanged (L-12).

`no_leg_exit` (optional, FU-1d) declares that this family's armed exit rule
also covers a NO-leg position, not just YES. It is a SECOND, narrower gate
layered on top of `exit_rule`/`persistence/exit_gate.family_declares_exit_rule`
(see `exit_gate.family_declares_no_leg_exit`) -- a family with `exit_rule` but
no `no_leg_exit` still gates every NO-leg exit closed. The key accepts ONLY
the literal JSON `true` (identity-checked, never `==`, so the integer `1`
cannot slip through): `false`, `1`, `"true"` and every other spelling are
refused with a message telling the author to omit the key instead (matching
`taker_fee_coefficient`'s one-spelling-per-meaning precedent). `true` without
`exit_rule` also present is refused as incoherent -- a NO-leg exit
declaration with no armed exit rule to extend has nothing to attach to. An
absent key loads as `False`, and `dump_family_manifest` omits the key
whenever it is `False`, so every manifest committed before this key existed
loads with byte-identical `manifest_sha256`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

from breezy.persistence.mechanism_test_guard import assert_prereg_directory_eligible

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
#: (``app/trade.py``) until WP-14 lands. ``forecast_quantile_ladder`` (SL-13,
#: plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §7 row SL-13,
#: hypothesis H-FC-NBP-EV-2026-09) DOES boot -- ``ForecastQuantileLadderStrategy``
#: exists (SL-12) and is wired by ``app/trade.py`` -- but every manifest
#: naming it committed so far stays ``DRAFT_NOT_REGISTERED`` (see
#: ``deploy/families/pm_us_crh_fq_v1.json``), so it never becomes the sending
#: family. Never a bool alongside another bool: this is the ONE slot that
#: names the composition, matching the manifest's own cardinality-1
#: ``family_id``.
CompositionKind = Literal[
    "current_rung_hold", "continuous_rung_hold", "forecast_ladder", "forecast_quantile_ladder"
]
_COMPOSITION_KINDS: Final[frozenset[str]] = frozenset(
    {"current_rung_hold", "continuous_rung_hold", "forecast_ladder", "forecast_quantile_ladder"}
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
        "taker_fee_coefficient",
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
    "taker_fee_coefficient",
)
_OPTIONAL_KEYS: Final[frozenset[str]] = frozenset(
    {"exit_rule", "terminal_climate_day", "no_leg_exit"}
)

#: Deliberately NARROWER than ``Decimal``'s own grammar. ``Decimal`` accepts
#: ``" 0.0695 "``, ``6.95E-2``, ``NaN``, ``Infinity``, ``+0.06`` and
#: ``-0.06``; every one of those would either compare unequal to the venue's
#: own wire coefficient in a way no reader could predict, or (NaN) make the
#: exact ``!=`` gate in ``strategy.current_rung_hold.decision`` silently
#: true forever. A taker coefficient is a small positive fraction written
#: plainly, so that is the only spelling accepted: leading ``0.`` and one to
#: six decimal digits. Anchored with ``\A``/``\Z`` rather than ``^``/``$``:
#: ``$`` also matches immediately BEFORE a trailing newline, so ``"0.0695\n"``
#: would otherwise slip through.
_TAKER_FEE_COEFFICIENT_RE: Final[re.Pattern[str]] = re.compile(r"\A0\.\d{1,6}\Z")
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
    #: The venue taker coefficient this family's break-even was computed
    #: against, REGISTERED on this artifact. Required, no default: a default
    #: is exactly where a silent, unregistered cost basis would reappear.
    #: See the module docstring.
    taker_fee_coefficient: Decimal
    exit_rule: str | None = None
    #: The family's LAST climate day, inclusive, or ``None`` for "still
    #: open". Set when a family is superseded -- see the module docstring
    #: and ``settlement/family_barrier.assert_family_only``.
    terminal_climate_day: str | None = None
    #: FU-1d: declares this family's armed ``exit_rule`` also covers a
    #: NO-leg position. See the module docstring's ``no_leg_exit`` section.
    no_leg_exit: bool = False


def load_family_manifest(path: Path, *, allow_draft: bool = False) -> FamilyManifest:
    """Load and strictly validate one family manifest JSON file.

    Every key in `_REQUIRED_KEYS` is required; `_OPTIONAL_KEYS`
    (`exit_rule`, `terminal_climate_day`) may be present; any key outside
    that combined set is refused. `status="DRAFT_NOT_REGISTERED"` and an unpinned (all-zero)
    `boundary_inputs_sha256` are each refused unless `allow_draft=True`.
    """
    if path.parent.exists():
        assert_prereg_directory_eligible(path.parent)
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
        raise FamilyManifestValidationError(f"{path}: missing required key(s): {sorted(missing)}")
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
            f"{path}: composition_kind {composition_kind!r} not one of {sorted(_COMPOSITION_KINDS)}"
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
        raise FamilyManifestValidationError(f"{path}: stations must be a non-empty list of strings")

    raw_theta = payload["taker_fee_coefficient"]
    if not _TAKER_FEE_COEFFICIENT_RE.match(raw_theta):
        raise FamilyManifestValidationError(
            f"{path}: taker_fee_coefficient {raw_theta!r} must be a plain decimal "
            f'fraction matching {_TAKER_FEE_COEFFICIENT_RE.pattern!r} (e.g. "0.0695")'
        )
    taker_fee_coefficient = Decimal(raw_theta)
    if not (Decimal(0) < taker_fee_coefficient < Decimal(1)):
        raise FamilyManifestValidationError(
            f"{path}: taker_fee_coefficient {raw_theta!r} must be strictly between 0 and 1"
        )

    terminal_climate_day = payload.get("terminal_climate_day")
    if terminal_climate_day is not None:
        if not isinstance(terminal_climate_day, str):
            raise FamilyManifestValidationError(
                f"{path}: terminal_climate_day must be a string when present"
            )
        try:
            date.fromisoformat(terminal_climate_day)
        except ValueError as exc:
            raise FamilyManifestValidationError(
                f"{path}: terminal_climate_day {terminal_climate_day!r} is not a real ISO-8601 date"
            ) from exc
        if terminal_climate_day < d0_climate_day:
            raise FamilyManifestValidationError(
                f"{path}: terminal_climate_day {terminal_climate_day!r} precedes "
                f"d0_climate_day {d0_climate_day!r}, which would make the family's "
                "scope empty"
            )

    exit_rule = payload.get("exit_rule")
    if exit_rule is not None and (not isinstance(exit_rule, str) or not exit_rule):
        raise FamilyManifestValidationError(
            f"{path}: exit_rule must be a non-empty string when present"
        )

    no_leg_exit = False
    if "no_leg_exit" in payload:
        no_leg_exit_raw = payload["no_leg_exit"]
        if no_leg_exit_raw is not True:  # identity check (never `==`): refuses `1`, `"true"`
            raise FamilyManifestValidationError(
                f"{path}: no_leg_exit must be the literal JSON `true` when present "
                f"(got {no_leg_exit_raw!r}); omit the key instead of writing `false`"
            )
        no_leg_exit = True
    if no_leg_exit and exit_rule is None:
        raise FamilyManifestValidationError(
            f"{path}: no_leg_exit is true but exit_rule is absent; a NO-leg exit "
            "declaration is incoherent without an armed exit_rule to extend"
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
        taker_fee_coefficient=taker_fee_coefficient,
        exit_rule=exit_rule,
        terminal_climate_day=terminal_climate_day,
        no_leg_exit=no_leg_exit,
    )


def _field_getters() -> dict[str, Callable[[FamilyManifest], object]]:
    """One getter per key the loader accepts. A key that appears in
    `_REQUIRED_KEYS | _OPTIONAL_KEYS` but not here fails `dump_family_manifest`
    loudly -- the serialiser is not a hand-maintained second key list.
    """

    def _path(value: Path) -> str:
        return value.as_posix()

    return {
        "family_id": lambda manifest: manifest.family_id,
        "venue": lambda manifest: manifest.venue,
        "trial_id_prefix": lambda manifest: manifest.trial_id_prefix,
        "d0_climate_day": lambda manifest: manifest.d0_climate_day,
        "boundary_artefact_path": lambda manifest: _path(manifest.boundary_artefact_path),
        "boundary_inputs_sha256": lambda manifest: manifest.boundary_inputs_sha256,
        "stations": lambda manifest: list(manifest.stations),
        "status": lambda manifest: manifest.status,
        "composition_kind": lambda manifest: manifest.composition_kind,
        "density_artefact_path": lambda manifest: _path(manifest.density_artefact_path),
        "density_artefact_sha256": lambda manifest: manifest.density_artefact_sha256,
        "taker_fee_coefficient": lambda manifest: str(manifest.taker_fee_coefficient),
        "exit_rule": lambda manifest: manifest.exit_rule,
        "terminal_climate_day": lambda manifest: manifest.terminal_climate_day,
        "no_leg_exit": lambda manifest: True if manifest.no_leg_exit else None,
    }


def dump_family_manifest(manifest: FamilyManifest) -> dict[str, object]:
    """JSON object for `manifest`, covering `_REQUIRED_KEYS | _OPTIONAL_KEYS`.

    `manifest_sha256` is not a JSON field -- it is the hash of the file
    bytes `write_family_manifest` emits. Optional keys whose value is
    ``None`` are omitted, matching `load_family_manifest`'s absence rule.
    """
    getters = _field_getters()
    keys = _REQUIRED_KEYS | _OPTIONAL_KEYS
    missing = sorted(keys - getters.keys())
    if missing:
        raise FamilyManifestValidationError(f"serialiser has no mapping for key(s): {missing}")
    payload: dict[str, object] = {}
    for key in sorted(keys):
        value = getters[key](manifest)
        if key in _OPTIONAL_KEYS and value is None:
            continue
        payload[key] = value
    return payload


def write_family_manifest(path: Path, manifest: FamilyManifest) -> Path:
    """Write `manifest` as canonical JSON. Returns `path`."""
    raw = (json.dumps(dump_family_manifest(manifest), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path
