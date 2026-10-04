"""The sending resolver (ARCH-0 seam A 8c; AC 17, AC 19).

``resolve_sending_family(*, venue, paths, repo_root, now_ns, hwm)`` answers one question: which
family may send for ``venue`` now, and on what bytes. It returns a ``ResolvedFamily`` or a
``ResolverRefusal``; it never raises for a bad registry, export, manifest or artefact, and a
refusal names a closed reason (and at most a closed detail), never a path.

Step 1 (a shadow ``paths`` is refused as ``paths_role_mismatch``) is coded here, in the public
entry, and is not part of ``_resolve``. ``_resolve`` runs steps 0 and 2 to 12 of AC 17:

0. the stage is ``stage_policy.STAGE`` (a fixture may pass another) and the hwm mode agrees with
   the paths role;
2. the clock is an int > 0, the chain verifies from genesis, is not empty and ``now_ns`` is not
   before its head by more than the skew;
3. the newest export (a corrupt one blocks, E-18b; none is ``not_yet_due`` only within
   ``EXPORT_FIRST_DUE_H`` of genesis) is a verified prefix of the chain (rows and trailer);
4. ``hwm_check`` (enforced for a sending resolve only);
5. ``transitions.rows_admissible`` over the whole chain;
6. ``replay_full``, then every HWM_RESET after the newest export carries counters that cover that
   export's (B9; E-21), and the fold at ``now_ns``;
7. at most one family is CHAMPION or HALTED (``senders`` is data only: A7a-R5);
8. root or child is the fold's ``origin``;
9. a root: committed bytes, the E-14 record and its own live-orders triple
   (``permit_present=False``; only ``permit_absent`` passes);
10. a child: ``registry/families`` bytes, the committed-root equality, the lineage-policy gate and
    the d0 and prefix rule of its first ->CHAMPION row;
11. both: the manifest names the venue, the kind is routed, the authorising row's engine code is
    pinned and not revoked, the artefact is the row's;
12. ``ResolvedFamily``.

It yields no permit semantics (invariant I-3): there is no ``enabled`` field and the gate is asked
with ``permit_present=False``. Nothing here reads the exec store; the HWM is an argument. Until
AUT-5a no live process imports this module.

Choices ARCH leaves open, fixed here (each pinned by a test):

* The authorising row is the family's latest row of a →CHAMPION kind (BOOTSTRAP, ROOT_ADMIT,
  PROMOTE, DRILL_PROMOTE, ROLLBACK, RESUME) whose effective instant is the start of the family's
  current champion epoch in the fold. The bound manifest sha is the fold's latest for the family
  and the artefact sha the introducing row's (``FamilyView``).
* The B9 export check covers the HWM_RESET rows written after the newest export. Folding the export
  at its own head instant makes it a floor no honest reset can be under.
* A child whose manifest declares no ruling is ``ruling_not_policy``; a root the gate does not know
  is ``root_not_lineage_allowlisted`` (the gate cannot say whether the ruling or the root is the
  unknown part, so both read as the latter).
* ``registry_seq`` is the head ``venue_seq`` the resolve verified.
* The shadow step set belongs to seam 8d; ``_resolve`` in ``SKIP_SHADOW`` mode raises
  ``NotImplementedError`` after the role check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from breezy.persistence.autonomy import pins, stage_policy, transitions
from breezy.persistence.autonomy.chain import (
    ChainBroken,
    VerifiedVenueChain,
    canonical_row,
    verify_against_export,
    verify_venue_chain,
)
from breezy.persistence.autonomy.family_bytes import (
    ByteBindingFailure,
    FamilyBytes,
    manifest_equal_modulo_allowlist,
    verify_bound_bytes,
)
from breezy.persistence.autonomy.fold import FamilyView, FoldInvalid, FoldResult, Origin, fold
from breezy.persistence.autonomy.fold_tallies import parse_carried
from breezy.persistence.autonomy.hwm import Hwm, HwmReading, hwm_check, next_hwm
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.registry_export import (
    ExportAbsent,
    ExportRead,
    ExportUnreadable,
    RegistryReader,
    RegistryUnreadable,
    newest_export,
)
from breezy.persistence.autonomy.replay import ReplayOk, replay_full
from breezy.persistence.autonomy.schemas import (
    Kind,
    LiveOrdersRefusal,
    RefusalReason,
    StageView,
    State,
    TransitionRow,
    UnreadableReason,
    check_venue,
)
from breezy.persistence.autonomy.validate_ii import carried_of, effective_ns, hwm_floor_problem
from breezy.persistence.family_manifest import FamilyManifest
from breezy.persistence.live_orders_gate import (
    LineagePolicyDecision,
    LiveOrdersGateRefusedError,
    lineage_policy_authorized,
    live_orders_authorized,
)

__all__ = [
    "FamilySource",
    "HwmMode",
    "ResolvedFamily",
    "ResolverRefusal",
    "SendingState",
    "manifest_equal_modulo_allowlist",
    "read_family_source",
    "resolve_sending_family",
]

FAMILY_SOURCE_ENV: Final = "BREEZY_FAMILY_SOURCE"
_NS_PER_S: Final = 10**9
_NS_PER_H: Final = 3600 * _NS_PER_S
#: The kinds that can make a family CHAMPION: the rows an authorising row is chosen among.
_AUTHORISING_KINDS: Final = frozenset(
    {
        Kind.BOOTSTRAP,
        Kind.ROOT_ADMIT,
        Kind.PROMOTE,
        Kind.DRILL_PROMOTE,
        Kind.ROLLBACK,
        Kind.RESUME,
    }
)
_HEAD_KINDS: Final = frozenset({Kind.PROMOTE, Kind.DRILL_PROMOTE})

LineageGate = Callable[[FamilyManifest, str, Path], LineagePolicyDecision]
ExportCheck = Literal["verified", "not_yet_due"]
SendingState = Literal[State.CHAMPION, State.HALTED]


class HwmMode(StrEnum):
    """Whether the resolve enforces the node high-water mark (sending) or ignores it (shadow)."""

    ENFORCE = "enforce"
    SKIP_SHADOW = "skip_shadow"


class FamilySource(StrEnum):
    """The values ``BREEZY_FAMILY_SOURCE`` may take; only ``REGISTRY`` binds (U14)."""

    UNSET = "unset"
    REGISTRY_SHADOW = "registry_shadow"
    REGISTRY = "registry"


def read_family_source(env: Mapping[str, str]) -> FamilySource:
    """The family source named by ``env``; a value outside the closed set raises ``ValueError``."""
    raw = env.get(FAMILY_SOURCE_ENV)
    return FamilySource.UNSET if raw in (None, "") else FamilySource(raw)


@dataclass(frozen=True, slots=True)
class ResolverRefusal:
    """No champion: a closed ``reason`` and, for two reasons, a closed ``detail``."""

    reason: RefusalReason
    detail: UnreadableReason | LiveOrdersRefusal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedFamily:
    """The one family that may send, with the bytes it stands on (ARCH C5 pickup fields).

    There is no ``enabled`` or permit field: the order-submission permit is none of the
    registry's business. ``entries_allowed`` is ``False`` for a HALTED family (exits stay live).
    """

    family_id: str
    state: SendingState
    entries_allowed: bool
    origin: Origin
    registry_seq: int
    chain_head: str
    authorising_seq: int
    family_bytes: FamilyBytes
    export_check: ExportCheck
    verified_export_seq: int
    hwm: Hwm


@dataclass(frozen=True, slots=True)
class _Verified:
    """What steps 0 to 8 established, for steps 9 to 12."""

    chain: VerifiedVenueChain
    view: FoldResult
    family: FamilyView
    export_check: ExportCheck
    export_seq: int


def _refuse(
    reason: RefusalReason, detail: UnreadableReason | LiveOrdersRefusal | None = None
) -> ResolverRefusal:
    return ResolverRefusal(reason, detail)


# --- steps 2 and 3 --------------------------------------------------------------------------------


def _read_chain(
    venue: str, paths: AutonomyPaths | ShadowPaths, now_ns: object
) -> VerifiedVenueChain | ResolverRefusal:
    """Step 2: the venue's chain verified from genesis, and a usable clock against its head."""
    if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns <= 0:
        return _refuse(RefusalReason.CLOCK_INVALID)
    try:
        rows = RegistryReader(paths, busy_timeout_ms=pins.WATCH_BUSY_TIMEOUT_MS).read_venue_rows(
            venue
        )
    except RegistryUnreadable as exc:
        return _refuse(RefusalReason.REGISTRY_UNREADABLE, exc.reason)
    try:
        chain = verify_venue_chain(rows, venue)
    except ChainBroken:
        return _refuse(RefusalReason.CHAIN_BROKEN)
    if not chain.rows:
        return _refuse(RefusalReason.EMPTY_CHAIN)
    if now_ns < chain.rows[-1].ts_ns - pins.ROW_TS_MAX_SKEW_S * _NS_PER_S:
        return _refuse(RefusalReason.CLOCK_BEFORE_HEAD)
    return chain


def _same_prefix(chain: VerifiedVenueChain, export: ExportRead) -> bool:
    """The export's rows are the chain's first rows, column for column."""
    head = export.trailer.venue_seq
    return len(export.rows) == head and all(
        canonical_row(a) == canonical_row(b) and a.transition_hash == b.transition_hash
        for a, b in zip(export.rows, chain.rows[:head], strict=False)
    )


def _read_exports(
    venue: str, paths: AutonomyPaths | ShadowPaths, chain: VerifiedVenueChain, now_ns: int
) -> tuple[ExportCheck, int, ExportRead | None] | ResolverRefusal:
    """Step 3: ``(export_check, newest_export_seq, export)`` or the refusal."""
    found = newest_export(paths, venue)
    if isinstance(found, ExportUnreadable):
        return _refuse(RefusalReason.EXPORT_UNREADABLE)
    if isinstance(found, ExportAbsent):
        due_ns = pins.EXPORT_FIRST_DUE_H * _NS_PER_H
        if now_ns - chain.rows[0].ts_ns < due_ns:
            return "not_yet_due", 0, None
        return _refuse(RefusalReason.EXPORT_UNREADABLE)
    if verify_against_export(chain, found.trailer) is not None or not _same_prefix(chain, found):
        return _refuse(RefusalReason.EXPORT_PREFIX_MISMATCH)
    return "verified", found.trailer.export_seq, found


# --- steps 5 to 8 ---------------------------------------------------------------------------------


def _reset_floor_problem(
    chain: VerifiedVenueChain, export: ExportRead | None, venue: str
) -> ResolverRefusal | None:
    """B9 / E-21: each HWM_RESET after the newest export covers that export's counters."""
    if export is None:
        return None
    resets = [
        r
        for r in chain.rows
        if r.kind is Kind.HWM_RESET and (r.venue_seq or 0) > export.trailer.venue_seq
    ]
    if not resets:
        return None
    at_export = fold(export.rows, venue, export.rows[-1].ts_ns)
    if isinstance(at_export, FoldInvalid):
        return _refuse(RefusalReason.REPLAY_INVALID)
    floor = carried_of(at_export)
    for row in resets:
        carried = None if row.carried_counters is None else parse_carried(row.carried_counters)
        if carried is None or hwm_floor_problem(floor, carried) is not None:
            return _refuse(RefusalReason.REPLAY_INVALID)
    return None


def _verify_registry(
    *,
    venue: str,
    paths: AutonomyPaths | ShadowPaths,
    repo_root: Path,
    now_ns: int,
    hwm: HwmReading,
    stage: StageView,
    hwm_mode: HwmMode,
) -> _Verified | ResolverRefusal:
    """Steps 2 to 8: the verified chain, its fold and the one family that sends."""
    chain = _read_chain(venue, paths, now_ns)
    if isinstance(chain, ResolverRefusal):
        return chain
    exports = _read_exports(venue, paths, chain, now_ns)
    if isinstance(exports, ResolverRefusal):
        return exports
    export_check, export_seq, export = exports
    if hwm_mode is HwmMode.ENFORCE:
        problem = hwm_check(chain, hwm, newest_export_seq=export_seq)
        if problem is not None:
            return _refuse(problem)
    admissible = transitions.rows_admissible(chain.rows, stage=stage)
    if admissible.reason is not None:
        return _refuse(admissible.reason)
    replayed = replay_full(chain, paths=paths, repo_root=repo_root)
    if not isinstance(replayed, ReplayOk):
        return _refuse(replayed.reason)
    floors = _reset_floor_problem(chain, export, venue)
    if floors is not None:
        return floors
    view = fold(chain.rows, venue, now_ns)
    if isinstance(view, FoldInvalid):
        return _refuse(RefusalReason.REPLAY_INVALID)
    senders = view.senders
    if len(senders) > 1:
        return _refuse(RefusalReason.ENGINE_INCONSISTENCY)
    if not senders:
        return _refuse(RefusalReason.NO_SENDER)
    return _Verified(chain, view, view.families[senders[0]], export_check, export_seq)


# --- steps 9 to 11 --------------------------------------------------------------------------------


def _authorising_row(chain: VerifiedVenueChain, family: FamilyView) -> TransitionRow | None:
    """The row that opened the family's current champion epoch (the latest at that instant)."""
    start = family.champion_epoch_start_ns
    if start is None:
        return None
    for row in reversed(chain.rows):
        if (
            row.family_id == family.family_id
            and row.kind in _AUTHORISING_KINDS
            and row.to_state is State.CHAMPION
            and effective_ns(row) == start
        ):
            return row
    return None


def _root_gate(manifest: FamilyManifest, repo_root: Path) -> ResolverRefusal | None:
    """Step 9: the root's own live-orders triple verifies; the permit is none of our business."""
    try:
        decision = live_orders_authorized(manifest, repo_root, permit_present=False)
    except LiveOrdersGateRefusedError as exc:
        return _refuse(RefusalReason.RULING_REFUSED, LiveOrdersRefusal(exc.reason))
    if decision.reason == "permit_absent":
        return None
    if decision.reason == "no_ruling":
        return _refuse(RefusalReason.NO_LIVE_ORDERS_RULING)
    return _refuse(RefusalReason.RULING_REFUSED, LiveOrdersRefusal(decision.reason))


def _child_gate(
    manifest: FamilyManifest, root_id: str, repo_root: Path, lineage_gate: LineageGate
) -> ResolverRefusal | None:
    """Step 10: the root's lineage-policy ruling covers this child."""
    try:
        decision = lineage_gate(manifest, root_id, repo_root)
    except LiveOrdersGateRefusedError as exc:
        if exc.reason == "not_allowlisted":
            return _refuse(RefusalReason.ROOT_NOT_LINEAGE_ALLOWLISTED)
        return _refuse(RefusalReason.RULING_REFUSED, LiveOrdersRefusal(exc.reason))
    if not decision.authorized:
        return _refuse(RefusalReason.RULING_NOT_POLICY)
    return None


def _first_champion_problem(
    chain: VerifiedVenueChain, manifest: FamilyManifest
) -> RefusalReason | None:
    """d0 and the trial prefix bind a family's first →CHAMPION head only (U1).

    A family whose champion epoch a ROLLBACK or RESUME opened is judged by the head that made it
    CHAMPION the first time, so neither rule applies to the later rows.
    """
    for row in chain.rows:
        if (
            row.family_id == manifest.family_id
            and row.kind in _HEAD_KINDS
            and row.to_state is State.CHAMPION
        ):
            if manifest.trial_id_prefix != f"{manifest.composition_kind}/trial/{row.family_id}/":
                return RefusalReason.TRIAL_PREFIX_MISMATCH
            day = row.effective_launch_date
            return RefusalReason.D0_BREACH if day is None or manifest.d0_climate_day < day else None
    return None


def _is_routed(manifest: FamilyManifest) -> bool:
    """Only a kind in ``LIVE_GATE_ROUTED_KINDS`` can send, whatever else the registry says."""
    return manifest.composition_kind in pins.LIVE_GATE_ROUTED_KINDS


def _engine_problem(
    row: TransitionRow, engine_pins: frozenset[str], revoked: frozenset[str]
) -> RefusalReason | None:
    if row.engine_code_sha in revoked:
        return RefusalReason.ENGINE_CODE_REVOKED
    if row.engine_code_sha not in engine_pins:
        return RefusalReason.ENGINE_CODE_UNPINNED
    return None


def _sending_state(family: FamilyView) -> SendingState | None:
    if family.state is State.CHAMPION:
        return State.CHAMPION
    return State.HALTED if family.state is State.HALTED else None


def _bind_sender(
    ok: _Verified,
    *,
    venue: str,
    paths: AutonomyPaths | ShadowPaths,
    repo_root: Path,
    lineage_gate: LineageGate,
    engine_pins: frozenset[str],
    revoked: frozenset[str],
) -> ResolvedFamily | ResolverRefusal:
    """Steps 8 to 12: the sender's bytes, gate, routing and engine pins."""
    family = ok.family
    authorising = _authorising_row(ok.chain, family)
    if authorising is None:
        return _refuse(RefusalReason.ENGINE_INCONSISTENCY)
    bound = verify_bound_bytes(
        venue=venue,
        family_id=family.family_id,
        manifest_sha256=family.manifest_sha256,
        artefact_sha256=family.artefact_sha256,
        paths=paths,
        repo_root=repo_root,
        origin=family.origin,
        expected_root=family.lineage_root_family_id,
    )
    if isinstance(bound, ByteBindingFailure):
        return _refuse(bound.reason)
    manifest = bound.manifest
    if family.origin is Origin.ROOT:
        refusal = _root_gate(manifest, repo_root)
    else:
        refusal = _child_gate(manifest, family.lineage_root_family_id, repo_root, lineage_gate)
        problem = _first_champion_problem(ok.chain, manifest)
        if refusal is None and problem is not None:
            refusal = _refuse(problem)
    if refusal is not None:
        return refusal
    if not _is_routed(manifest):
        return _refuse(RefusalReason.KIND_NOT_LIVE_GATE_ROUTED)
    engine = _engine_problem(authorising, engine_pins, revoked)
    if engine is not None:
        return _refuse(engine)
    state = _sending_state(family)
    if state is None:
        return _refuse(RefusalReason.ENGINE_INCONSISTENCY)
    return ResolvedFamily(
        family_id=family.family_id,
        state=state,
        entries_allowed=state is State.CHAMPION,
        origin=family.origin,
        registry_seq=ok.chain.head_venue_seq,
        chain_head=ok.chain.head_hash,
        authorising_seq=authorising.venue_seq or 0,
        family_bytes=bound,
        export_check=ok.export_check,
        verified_export_seq=ok.export_seq,
        hwm=next_hwm(ok.chain, export_seq=ok.export_seq),
    )


# --- the entries ----------------------------------------------------------------------------------


def _resolve(
    *,
    venue: str,
    paths: AutonomyPaths | ShadowPaths,
    repo_root: Path,
    now_ns: int,
    hwm: HwmReading,
    stage: StageView,
    lineage_gate: LineageGate,
    hwm_mode: HwmMode,
    _fixture_stage: bool = False,
    _engine_pins: frozenset[str] | None = None,
    _revoked_pins: frozenset[str] | None = None,
) -> ResolvedFamily | ResolverRefusal:
    """Steps 0 and 2 to 12 (step 1 is the public entry's). The ``_`` parameters are test seams."""
    if stage is not stage_policy.STAGE and not _fixture_stage:
        return _refuse(RefusalReason.STAGE_NOT_CANONICAL)
    if (hwm_mode is HwmMode.SKIP_SHADOW) != paths.is_shadow:
        return _refuse(RefusalReason.PATHS_ROLE_MISMATCH)
    if hwm_mode is HwmMode.SKIP_SHADOW:
        raise NotImplementedError("the shadow step set is seam 8d")
    venue = check_venue(venue)
    verified = _verify_registry(
        venue=venue,
        paths=paths,
        repo_root=repo_root,
        now_ns=now_ns,
        hwm=hwm,
        stage=stage,
        hwm_mode=hwm_mode,
    )
    if isinstance(verified, ResolverRefusal):
        return verified
    return _bind_sender(
        verified,
        venue=venue,
        paths=paths,
        repo_root=repo_root,
        lineage_gate=lineage_gate,
        engine_pins=pins.ENGINE_SOURCE_SHA256 if _engine_pins is None else _engine_pins,
        revoked=pins.REVOKED_SOURCE_SHA256 if _revoked_pins is None else _revoked_pins,
    )


def resolve_sending_family(
    *,
    venue: str,
    paths: AutonomyPaths | ShadowPaths,
    repo_root: Path,
    now_ns: int,
    hwm: HwmReading,
) -> ResolvedFamily | ResolverRefusal:
    """The family that may send for ``venue`` at ``now_ns``, or why none may (module docstring).

    Step 1: a shadow ``paths`` is refused. The attribute is read, never an ``isinstance``.
    """
    if paths.is_shadow:
        return _refuse(RefusalReason.PATHS_ROLE_MISMATCH)
    return _resolve(
        venue=venue,
        paths=paths,
        repo_root=repo_root,
        now_ns=now_ns,
        hwm=hwm,
        stage=stage_policy.STAGE,
        lineage_gate=lineage_policy_authorized,
        hwm_mode=HwmMode.ENFORCE,
    )
