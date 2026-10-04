"""Replay: validate over the whole chain, causes resolved, bytes checked (ARCH-0 seam A 8b; AC 17).

``replay_full(chain, *, paths, repo_root)`` is step 6 of the resolver. Its input is a chain that
``chain.verify_venue_chain`` has already proven contiguous and hash-linked. It walks the rows in
chain order, one *batch* at a time (a dated →CHAMPION head with the SUPERSEDE or DISPLACED
partners that cite it is one batch, as the store appended it; every other row is its own), and for
each batch:

1. folds the rows before it at the batch's first ``ts_ns`` (``FoldInvalid`` is ``ReplayInvalid``);
2. resolves the ``cause_verdict_ids`` of every PROMOTE, DRILL_PROMOTE, ROLLBACK, RESUME and
   ROOT_ADMIT to a stored verdict (``ReplayCauseUnresolved``);
3. re-runs ``transitions.first_refusal`` with those verdicts. It is the rule-level form of
   ``validate(mode=None)``; the stage gate is the resolver's ``rows_admissible`` (step 5). A
   RESUME's cited verdicts are judged PASS-after-halt (A7c-R8) and a HWM_RESET's
   ``carried_counters`` against the fold immediately before the row (B9; ``ReplayInvalid``);
4. checks the content-addressed artefact bytes of every row that carries an ``artefact_sha256``
   against that sha (``ReplayArtefactMismatch``).

A last fold of the whole chain catches a ``FoldInvalid`` that only the last batch causes. The
module reads the registry root and the repo; it never writes either.

Choices ARCH leaves open, fixed here (each pinned by a test):

* ``ReplayOk`` carries no fold. The resolver folds again at its own clock: a fold here would be at
  the head's ``ts_ns``, which hides every pair that takes effect later.
* A verdict is looked up under ``derived/verdicts/<row.family_id>/<day>/<id>.json`` in every day
  directory (the id does not name the day) and must be ``read_verdict``-clean: parse, the id equal
  to the recomputed id, the address equal to its family and ``valid_until`` date.
* A cause verdict must be a PASS for every cited kind. A PROMOTE to CHALLENGER must cite an
  OFFLINE_CHALLENGER verdict, a PROMOTE to CHAMPION both an OFFLINE_CHALLENGER and a FORWARD_SHADOW
  verdict (ARCH C5 "Allowed transitions"); no other kind is constrained.
* A PROMOTE or RESUME cites at least one verdict. A DRILL_PROMOTE (a drill clause, not a verdict,
  authorises it) and the restorative RESUME (E-5) may cite none; whatever they cite resolves like
  any other.
* A ROLLBACK and a ROOT_ADMIT are judged by role (A8b-R1; E-22). Each cited verdict resolves in its
  subject's directory, searched in three places only: the row's family, its batch partner (the
  outgoing family F) and the prior fold's senders. The roles are the halting causes of F (FAIL
  verdicts whose subject is F and whose artefact is F's bound sha) and the AUT-6 DRIFT
  ``fee_schedule`` PASS for the champion. A ROLLBACK needs the fee PASS, and F's causes unless F's
  standing halt carries no verdict (an exec-store mirror, a ``rollback_failed`` HALT) or F is not
  halted (the drill's abort close); it may then cite nothing. A ROOT_ADMIT needs the fee PASS.
* ``subject_artefact_sha256`` equals the row's ``artefact_sha256`` (else the sha the family was
  bound to). A verdict kind that always names an artefact (OFFLINE_CHALLENGER, FORWARD_SHADOW) must
  carry it; a HEALTH, DRIFT or RECONCILIATION verdict may carry none.
* A root's manifest (the family a BOOTSTRAP or ROOT_ADMIT introduced) is read from the repo only,
  never from a registry copy (E-14 rule 3a; A6d-A2 M2). The artefact lives at
  ``derived/artefacts/<composition_kind>:<component>/<sha>/artefact.json``, the kind read from that
  manifest. The component is found by probing ``pins.MODEL_CLASS_COMPONENTS`` and requiring
  exactly one component with a readable file (zero or several: ``ARTEFACT_UNREADABLE``, A8b-R2).
  Reads are STRICT, capped by ``pins.ARTEFACT_MAX_BYTES`` and memoised by ``(model_class, sha)``.
* A ``FoldInvalid`` of the rows before a batch is reported at the first row of the previous batch,
  the batch whose rows first made the prefix unfoldable or the earliest that can be named (A8b-R5).
* Every caller must also run ``transitions.rows_admissible`` on the chain (resolver step 5): replay
  judges the rules, not the stage gate. A HWM_RESET's carried counters are floored here only by
  the prior fold; the resolver (8c) also checks them against the newest export (B9).
* ``verify_family_bytes`` is not needed here: the resolver's own byte binding (8c) still runs after
  replay, on the champion alone.

Refusals carry closed names and sequence numbers, never paths.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Final

from breezy.persistence.autonomy import transitions
from breezy.persistence.autonomy.byte_binding import probe_artefact, read_artefact
from breezy.persistence.autonomy.chain import VerifiedVenueChain
from breezy.persistence.autonomy.family_bytes import read_manifest_facts, roots_of
from breezy.persistence.autonomy.fold import FoldInvalid, FoldResult, fold
from breezy.persistence.autonomy.fold_pairs import PARTNER_KINDS, is_head
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths, family_component
from breezy.persistence.autonomy.schemas import (
    CauseCode,
    Kind,
    ManifestFacts,
    RefusalReason,
    State,
    TransitionRow,
)
from breezy.persistence.autonomy.single_read import (
    SingleReadRefused,
    open_root,
    walk_dirs,
)
from breezy.persistence.autonomy.validate_ii import carried_of
from breezy.persistence.autonomy.verdict import (
    Verdict,
    VerdictKind,
    VerdictOutcome,
    VerdictUnreadable,
    read_verdict,
)

__all__ = [
    "ArtefactFailure",
    "CauseFailure",
    "ReplayArtefactMismatch",
    "ReplayCauseUnresolved",
    "ReplayInvalid",
    "ReplayOk",
    "ReplayResult",
    "replay_full",
]

_ARTEFACT_NAME: Final = "artefact.json"
_VERDICT_PARTS: Final = ("derived", "verdicts")
_DAY_RE: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z", re.ASCII)
#: Kinds judged by role (E-22) rather than "a PASS of the row's family".
_ROLE_KINDS: Final = frozenset({Kind.ROLLBACK, Kind.ROOT_ADMIT})
_FEE_DETECTOR: Final = "fee_schedule"
#: Standing halts whose cause is no verdict: an exec-store mirror and a failed rollback (E-22 a).
_VERDICTLESS_HALTS: Final = frozenset({CauseCode.EXEC_STORE_HALT_MIRROR, CauseCode.ROLLBACK_FAILED})
#: The kinds whose ``cause_verdict_ids`` the replay resolves (AUT-5 r7 section 3.2).
_CITING_KINDS: Final = frozenset(
    {Kind.PROMOTE, Kind.DRILL_PROMOTE, Kind.ROLLBACK, Kind.RESUME, Kind.ROOT_ADMIT}
)
#: Verdict kinds that always name the artefact they judge.
_ARTEFACT_KINDS: Final = frozenset({VerdictKind.OFFLINE_CHALLENGER, VerdictKind.FORWARD_SHADOW})


class CauseFailure(StrEnum):
    NOT_CITED = "not_cited"
    NOT_FOUND = "not_found"
    KIND_MISMATCH = "kind_mismatch"
    NOT_PASS = "not_pass"
    ROLE_MISMATCH = "role_mismatch"
    SUBJECT_ARTEFACT_MISMATCH = "subject_artefact_mismatch"


class ArtefactFailure(StrEnum):
    MANIFEST_UNREADABLE = "manifest_unreadable"
    ARTEFACT_UNREADABLE = "artefact_unreadable"
    ARTEFACT_SHA_MISMATCH = "artefact_sha_mismatch"


@dataclass(frozen=True, slots=True)
class ReplayOk:
    """Every row validated, every cause resolved, every artefact byte-equal to its row."""

    head_venue_seq: int
    chain_head: str


@dataclass(frozen=True, slots=True)
class ReplayInvalid:
    """``validate`` refused a batch, or the fold could not be built.

    ``rule`` is the ``validate`` rule value or the ``FoldInvalidReason`` value; ``venue_seq`` is
    the refused row (for a fold, the last row folded before the batch that could not start).
    ``validate_reason`` is the closed reason ``validate`` gave (``None`` for a fold).
    """

    reason: ClassVar[RefusalReason] = RefusalReason.REPLAY_INVALID
    venue_seq: int
    rule: str
    validate_reason: RefusalReason | None = None


@dataclass(frozen=True, slots=True)
class ReplayCauseUnresolved:
    """A cited cause that is absent, mismatched or no PASS. ``verdict_id`` is ``None`` when the
    failure belongs to no single verdict (nothing cited, or a required kind missing)."""

    reason: ClassVar[RefusalReason] = RefusalReason.REPLAY_CAUSE_UNRESOLVED
    venue_seq: int
    why: CauseFailure
    verdict_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayArtefactMismatch:
    """A row whose artefact bytes (or the manifest that locates them) cannot be trusted."""

    reason: ClassVar[RefusalReason] = RefusalReason.REPLAY_ARTEFACT_MISMATCH
    venue_seq: int
    why: ArtefactFailure


ReplayResult = ReplayOk | ReplayInvalid | ReplayCauseUnresolved | ReplayArtefactMismatch
_Failure = ReplayInvalid | ReplayCauseUnresolved | ReplayArtefactMismatch


class _Facts:
    """The manifest-facts reader the replay binds: memoised, repo-only for a root."""

    def __init__(
        self, paths: AutonomyPaths | ShadowPaths, repo_root: Path, roots: frozenset[str]
    ) -> None:
        self._paths = paths
        self._repo_root = repo_root
        self._roots = roots
        self._memo: dict[tuple[str, str], ManifestFacts | None] = {}

    def __call__(self, family_id: str, manifest_sha256: str) -> ManifestFacts | None:
        key = (family_id, manifest_sha256)
        if key not in self._memo:
            self._memo[key] = read_manifest_facts(
                family_id,
                manifest_sha256,
                paths=self._paths,
                repo_root=self._repo_root,
                repo_only=family_id in self._roots,
            )
        return self._memo[key]


def _batch_end(rows: Sequence[TransitionRow], start: int) -> int:
    """The index after the batch that begins at ``start`` (a dated head and its partners)."""
    head = rows[start]
    end = start + 1
    if not is_head(head):
        return end
    while (
        end < len(rows)
        and rows[end].kind in PARTNER_KINDS
        and rows[end].paired_transition_id == head.transition_id
    ):
        end += 1
    return end


def _find_verdict(
    paths: AutonomyPaths | ShadowPaths, family_id: str, verdict_id: str
) -> Verdict | None:
    """The stored verdict of ``family_id`` with this id, or ``None`` (no day names it)."""
    try:
        rootfd = open_root(paths.root)
    except SingleReadRefused:
        return None
    try:
        dirfd = walk_dirs(rootfd, (*_VERDICT_PARTS, family_component(family_id)))
        try:
            days = sorted(name for name in os.listdir(dirfd) if _DAY_RE.match(name))
        finally:
            os.close(dirfd)
    except (SingleReadRefused, OSError):
        return None
    finally:
        os.close(rootfd)
    for day in days:
        try:
            return read_verdict(paths, family_id, day, verdict_id)
        except VerdictUnreadable:
            continue
    return None


def _required_kinds(row: TransitionRow) -> frozenset[VerdictKind]:
    if row.kind is not Kind.PROMOTE:
        return frozenset()
    if row.to_state is State.CHAMPION:
        return frozenset({VerdictKind.OFFLINE_CHALLENGER, VerdictKind.FORWARD_SHADOW})
    return frozenset({VerdictKind.OFFLINE_CHALLENGER})


def _may_cite_nothing(row: TransitionRow) -> bool:
    restore = row.kind is Kind.RESUME and row.cause_code is CauseCode.DRILL_CLOSE_RESTORE
    return row.kind is Kind.DRILL_PROMOTE or restore


def _fits(
    verdict: Verdict, row: TransitionRow, expected_artefact: str | None
) -> CauseFailure | None:
    if verdict.outcome is not VerdictOutcome.PASS:
        return CauseFailure.NOT_PASS
    named = verdict.subject_artefact_sha256
    if named is None and verdict.kind not in _ARTEFACT_KINDS:
        return None
    if named is None or named != expected_artefact:
        return CauseFailure.SUBJECT_ARTEFACT_MISMATCH
    return None


def _resolve_causes(
    row: TransitionRow,
    paths: AutonomyPaths | ShadowPaths,
    expected_artefact: str | None,
    cache: dict[str, Verdict],
) -> tuple[Mapping[str, Verdict], ReplayCauseUnresolved | None]:
    """The row's cited verdicts by id, or the first reason one does not resolve."""
    seq = row.venue_seq or 0
    if not row.cause_verdict_ids:
        if _may_cite_nothing(row):
            return {}, None
        return {}, ReplayCauseUnresolved(seq, CauseFailure.NOT_CITED)
    found: dict[str, Verdict] = {}
    for verdict_id in row.cause_verdict_ids:
        cached = cache.get(verdict_id)
        if cached is not None and cached.subject_family_id == row.family_id:
            verdict: Verdict | None = cached
        else:  # a verdict resolved for another family never serves this row
            verdict = _find_verdict(paths, row.family_id, verdict_id)
        if verdict is None:
            return {}, ReplayCauseUnresolved(seq, CauseFailure.NOT_FOUND, verdict_id)
        failure = _fits(verdict, row, expected_artefact)
        if failure is not None:
            return {}, ReplayCauseUnresolved(seq, failure, verdict_id)
        cache[verdict_id] = found[verdict_id] = verdict
    if not _required_kinds(row) <= {v.kind for v in found.values()}:
        return {}, ReplayCauseUnresolved(seq, CauseFailure.KIND_MISMATCH)
    return found, None


def _is_fee(verdict: Verdict) -> bool:
    return verdict.kind is VerdictKind.DRIFT and verdict.detector == _FEE_DETECTOR


def _lookup(walk: _Walk, places: Sequence[str], verdict_id: str) -> Verdict | None:
    """The verdict with this id in the first of ``places`` that holds it (E-22 c)."""
    cached = walk.verdicts.get(verdict_id)
    if cached is not None and cached.subject_family_id in places:
        return cached
    for family in places:
        found = _find_verdict(walk.paths, family, verdict_id)
        if found is not None:
            walk.verdicts[verdict_id] = found
            return found
    return None


def _resolve_roles(
    walk: _Walk,
    prior: FoldResult,
    batch: Sequence[TransitionRow],
    row: TransitionRow,
    expected: str | None,
) -> tuple[Mapping[str, Verdict], ReplayCauseUnresolved | None]:
    """A ROLLBACK's or ROOT_ADMIT's citations, judged by role (A8b-R1; E-22 a, b, c)."""
    seq = row.venue_seq or 0
    partners = [
        r.family_id
        for r in batch
        if r.kind in PARTNER_KINDS and r.paired_transition_id == row.transition_id
    ]
    outgoing = partners[0] if partners else (prior.senders[0] if prior.senders else None)
    places = tuple(dict.fromkeys([row.family_id, *partners, *prior.senders]))
    view = None if outgoing is None else prior.families.get(outgoing)
    needs_cause = (
        row.kind is Kind.ROLLBACK
        and view is not None
        and view.state is State.HALTED
        and view.standing_cause_code not in _VERDICTLESS_HALTS
    )
    if not row.cause_verdict_ids:
        if row.kind is Kind.ROLLBACK and not needs_cause:
            return {}, None
        return {}, ReplayCauseUnresolved(seq, CauseFailure.NOT_CITED)
    found: dict[str, Verdict] = {}
    fees = causes = 0
    for verdict_id in row.cause_verdict_ids:
        verdict = _lookup(walk, places, verdict_id)
        if verdict is None:
            return {}, ReplayCauseUnresolved(seq, CauseFailure.NOT_FOUND, verdict_id)
        failure: CauseFailure | None
        if _is_fee(verdict):
            fees += 1
            failure = None if verdict.outcome is VerdictOutcome.PASS else CauseFailure.NOT_PASS
        elif row.kind is Kind.ROLLBACK:
            causes += 1
            is_cause = (
                verdict.outcome is VerdictOutcome.FAIL
                and verdict.subject_family_id == outgoing
                and view is not None
                and verdict.subject_artefact_sha256 == view.artefact_sha256
            )
            failure = None if is_cause else CauseFailure.ROLE_MISMATCH
        else:  # a root-admission verdict AUT-5 names: PASS, subject the row's family
            failure = _fits(verdict, row, expected)
            if verdict.subject_family_id != row.family_id:
                failure = CauseFailure.ROLE_MISMATCH
        if failure is not None:
            return {}, ReplayCauseUnresolved(seq, failure, verdict_id)
        found[verdict_id] = verdict
    if fees == 0 or (needs_cause and causes == 0):
        return {}, ReplayCauseUnresolved(seq, CauseFailure.KIND_MISMATCH)
    return found, None


def _read_artefact(paths: AutonomyPaths | ShadowPaths, model_class: str, sha: str) -> bytes | None:
    """The artefact's bytes, or ``None`` for anything but a clean STRICT read."""
    return read_artefact(paths, model_class, sha)


def _probe_artefact(walk: _Walk, kind: str, sha: str) -> bytes | None:
    """The one artefact under ``<kind>:<component>/<sha>``; ``None`` for none or several.

    ``byte_binding.probe_artefact`` decides; the read it is given is memoised per replay (A8c-R6).
    """

    def read(model_class: str, digest: str) -> bytes | None:
        key = (model_class, digest)
        if key not in walk.reads:
            walk.reads[key] = _read_artefact(walk.paths, model_class, digest)
        return walk.reads[key]

    found = probe_artefact(kind, sha, read=read)
    return None if found is None else found[1]


def _artefact_failure(walk: _Walk, row: TransitionRow) -> ArtefactFailure | None:
    sha = row.artefact_sha256
    if sha is None:
        return None
    manifest = (
        None if row.manifest_sha256 is None else walk.facts(row.family_id, row.manifest_sha256)
    )
    if manifest is None:
        return ArtefactFailure.MANIFEST_UNREADABLE
    try:
        raw = _probe_artefact(walk, manifest.composition_kind, sha)
    except ValueError:  # a composition kind that is no path component: nothing to read
        return ArtefactFailure.MANIFEST_UNREADABLE
    if raw is None:
        return ArtefactFailure.ARTEFACT_UNREADABLE
    if sha256(raw).hexdigest() != sha:
        return ArtefactFailure.ARTEFACT_SHA_MISMATCH
    return None


@dataclass(slots=True)
class _Walk:
    """The state one replay carries from batch to batch."""

    venue: str
    paths: AutonomyPaths | ShadowPaths
    facts: _Facts
    verdicts: dict[str, Verdict]
    bound: dict[str, str]
    reads: dict[tuple[str, str], bytes | None]


def _validate_batch(
    walk: _Walk, prior: FoldResult, batch: Sequence[TransitionRow]
) -> _Failure | None:
    resolved: dict[str, Verdict] = {}
    for row in batch:
        if row.kind not in _CITING_KINDS:
            continue
        expected = row.artefact_sha256 or walk.bound.get(row.family_id)
        if row.kind in _ROLE_KINDS:
            found, failure = _resolve_roles(walk, prior, batch, row, expected)
        else:
            found, failure = _resolve_causes(row, walk.paths, expected, walk.verdicts)
        if failure is not None:
            return failure
        resolved.update(found)
    export = carried_of(prior) if any(r.kind is Kind.HWM_RESET for r in batch) else None
    refusal = transitions.first_refusal(
        prior, batch, manifests=walk.facts, export_counters=export, verdicts=resolved
    )
    if refusal is None:
        return None
    if refusal.rule is transitions.Rule.MANIFEST_DENSITY_NOT_BOUND:
        # The density rule reads the manifest that locates the artefact: when that manifest or the
        # artefact is untrustworthy, that is the (more specific) artefact failure (E-24).
        problem = _artefact_problem(walk, batch)
        if problem is not None:
            return problem
    return ReplayInvalid(
        batch[refusal.row_index].venue_seq or 0, refusal.rule.value, refusal.reason
    )


def _artefact_problem(walk: _Walk, batch: Sequence[TransitionRow]) -> ReplayArtefactMismatch | None:
    """The first row of ``batch`` whose artefact or the manifest locating it cannot be trusted."""
    for row in batch:
        if row.artefact_sha256 is None:
            continue
        failure = _artefact_failure(walk, row)
        if failure is not None:
            return ReplayArtefactMismatch(row.venue_seq or 0, failure)
    return None


def _bind_artefacts(walk: _Walk, batch: Sequence[TransitionRow]) -> None:
    """A family's artefact is its first row's: later rows of the chain are cited against it."""
    for row in batch:
        if row.artefact_sha256 is not None:
            walk.bound.setdefault(row.family_id, row.artefact_sha256)


def _replay_full(
    chain: VerifiedVenueChain,
    *,
    paths: AutonomyPaths | ShadowPaths,
    repo_root: Path,
) -> ReplayResult:
    rows = chain.rows
    walk = _Walk(
        venue=chain.venue,
        paths=paths,
        facts=_Facts(paths, repo_root, roots_of(rows)),
        verdicts={},
        bound={},
        reads={},
    )
    index = previous = 0
    while index < len(rows):
        end = _batch_end(rows, index)
        batch = rows[index:end]
        prior = fold(rows[:index], chain.venue, batch[0].ts_ns)
        if isinstance(prior, FoldInvalid):  # reported at the first row of the previous batch
            return ReplayInvalid(rows[previous].venue_seq or 0, prior.reason.value)
        failure = _validate_batch(walk, prior, batch) or _artefact_problem(walk, batch)
        if failure is not None:
            return failure
        _bind_artefacts(walk, batch)
        previous, index = index, end
    if rows and isinstance(whole := fold(rows, chain.venue, rows[-1].ts_ns), FoldInvalid):
        return ReplayInvalid(rows[-1].venue_seq or 0, whole.reason.value)
    return ReplayOk(chain.head_venue_seq, chain.head_hash)


def replay_full(
    chain: VerifiedVenueChain, *, paths: AutonomyPaths | ShadowPaths, repo_root: Path
) -> ReplayResult:
    """Replay ``chain`` from genesis; see the module docstring."""
    return _replay_full(chain, paths=paths, repo_root=repo_root)
