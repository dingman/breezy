"""The C5 registry store: DDL, append-only triggers, the writer connection and ``append``
(ARCH-0 seam A 6e; AC 8-10; AUT-5 r7 3.2).

This module is the ONLY writer of ``registry/registry.sqlite`` (one-writer table, L-50). The reader,
exports and ``newest_export`` are seam 6f.

The store has no wall clock: every instant is the caller's ``now_ns``. It does not take
``registry/engine.lock``; the engine holds that lock around a pass and ``BEGIN IMMEDIATE``
serialises the writers that reach SQLite.

Choices ARCH leaves open, fixed here:

* ``meta`` is the one-row table ``meta(schema)`` holding ``registry/v1``.
* Refusals carry a member of the closed ``RefusalReason``. A refusal with no member of its own
  (CAS mismatch, partial replay, mask, malformed batch or row) is ``engine_inconsistency``; a
  nomination or HWM_RESET not yet admitted is ``admission_pending``.
* Every row of a batch carries the batch's ``expected_prior_seq``: the column records the CAS value
  the writer asserted, and the Y9 id excludes it so a retry stays a replay.
* Column rules (``check_row_shape``): ``ALLOWED`` pair membership; ``lineage_root_family_id``
  required on BOOTSTRAP, MINT, PROMOTE, DRILL_PROMOTE, ROLLBACK, ROOT_ADMIT and ACTIVATE; the
  nomination columns all present on a SHADOW to CHALLENGER PROMOTE and all null elsewhere;
  ``paired_transition_id`` present exactly on SUPERSEDE, DISPLACED and ACTIVATE (E-16 a); the
  ATTEST, HWM_RESET and SWAP_CANCEL columns present only on their kind; ``cause_code`` only on
  DEMOTE, HALT, SWAP_CANCEL, TARGET_INELIGIBLE and ``drill_close_restore`` RESUME;
  ``trigger_cause_class`` only on a ``rollback_failed`` HALT.

Step 9 of AC 10: the verified hash chain (including each ``family_prior_seq`` and Y9 id) and the
fold of the extended chain, then ``transitions.validate`` over ``fold(prior)`` with the store's
bound manifest-facts reader (seam 7d; ruling A6e-R2). Restrictive rows never wait on anything that
can fail open: ``validate`` reads no manifest for them and no policy, journal or export read gates
them. An HWM_RESET is not yet admitted (``RuleSetPending``), so the export floor (B9) is not read
here.
"""

from __future__ import annotations

import functools
import logging
import os
import sqlite3
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from breezy.persistence.autonomy import chain, pins, single_read, stage_policy, transitions
from breezy.persistence.autonomy.chain import ChainBroken
from breezy.persistence.autonomy.family_bytes import read_manifest_facts, roots_of
from breezy.persistence.autonomy.fold import FoldInvalid, fold
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.registry_schema import (
    APPLICATION_ID,
    COLUMNS,
    DDL_OBJECTS,
    SCHEMA_ID,
    SELECT_MASTER,
    SELECT_ROWS,
    USER_VERSION,
    RowDecodeError,
    row_from_record,
)
from breezy.persistence.autonomy.registry_shape import is_nomination, shape_problem
from breezy.persistence.autonomy.schemas import (
    FoldInvalidReason,
    Kind,
    ManifestFactsReader,
    RefusalReason,
    StageView,
    TransitionRow,
    WriterMode,
    check_venue,
)
from breezy.persistence.autonomy.wire import WireRefused

__all__ = [
    "APPLICATION_ID",
    "COLUMNS",
    "DDL_OBJECTS",
    "SCHEMA_ID",
    "USER_VERSION",
    "AdmissionPending",
    "AppendResult",
    "CasMismatch",
    "ChainRefused",
    "ClockRefused",
    "KindRefused",
    "ModeNotConcrete",
    "NominationRequiresPolicy",
    "PartialReplay",
    "RegistryRefused",
    "RegistryStore",
    "ReplayMismatch",
    "RowRefused",
    "RuleSetPending",
    "StageNotCanonical",
    "StoreBusy",
    "StoreDrifted",
    "StoreUnavailable",
    "ValidateRefused",
    "WideningNotEnabled",
    "check_row_shape",
]

_LOG = logging.getLogger(__name__)

FILE_MODE: Final = 0o600
DIR_MODE: Final = 0o700
WRITER_BUSY_TIMEOUT_S: Final = 5.0
_REGISTRY_DIR: Final = ("registry",)
_NS_PER_S: Final = 10**9

_SET_APPLICATION_ID: Final = f"PRAGMA application_id = {APPLICATION_ID}"
_SET_USER_VERSION: Final = f"PRAGMA user_version = {USER_VERSION}"
_INSERT_META: Final = "INSERT INTO meta (schema) VALUES (?)"
_BEGIN: Final = "BEGIN IMMEDIATE"
_COMMIT: Final = "COMMIT"
_ROLLBACK: Final = "ROLLBACK"
#: ``(set, read back, expected)``: each writer pragma is read back, never assumed.
_WRITER_PRAGMAS: Final[tuple[tuple[str, str, object], ...]] = (
    ("PRAGMA journal_mode = DELETE", "PRAGMA journal_mode", "delete"),
    ("PRAGMA synchronous = EXTRA", "PRAGMA synchronous", 3),
    ("PRAGMA recursive_triggers = ON", "PRAGMA recursive_triggers", 1),
    ("PRAGMA trusted_schema = OFF", "PRAGMA trusted_schema", 0),
)
_INSERT_COLUMNS: Final = tuple(name for name in COLUMNS if name != "seq")
_INSERT_ROW: Final = (
    f"INSERT INTO transitions ({', '.join(_INSERT_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _INSERT_COLUMNS)})"
)
_SELECT_ROWS: Final = SELECT_ROWS
_SELECT_VENUE: Final = f"{_SELECT_ROWS} WHERE venue = ? ORDER BY venue_seq"
_SELECT_AFTER: Final = f"{_SELECT_ROWS} WHERE venue = ? AND venue_seq > ? ORDER BY venue_seq"
_SELECT_BY_ID: Final = f"{_SELECT_ROWS} WHERE transition_id = ?"
_SELECT_HEAD_SEQ: Final = "SELECT COALESCE(MAX(venue_seq), 0) FROM transitions WHERE venue = ?"
_SELECT_META: Final = "SELECT schema FROM meta"
_COUNT_MASTER: Final = "SELECT COUNT(*) FROM sqlite_master"
_PRAGMA_APPLICATION_ID: Final = "PRAGMA application_id"
_PRAGMA_USER_VERSION: Final = "PRAGMA user_version"


# --- refusals -------------------------------------------------------------------------------------


class RegistryRefused(Exception):
    """A write was refused; ``reason`` is a member of the closed ``RefusalReason``."""

    reason: RefusalReason = RefusalReason.ENGINE_INCONSISTENCY

    def __init__(self, detail: str = "", *, reason: RefusalReason | None = None) -> None:
        self.reason = reason or type(self).reason
        self.detail = detail
        super().__init__(f"{self.reason.value}: {detail}" if detail else self.reason.value)


class StageNotCanonical(RegistryRefused):
    reason = RefusalReason.STAGE_NOT_CANONICAL


class WideningNotEnabled(RegistryRefused):
    reason = RefusalReason.WIDENING_KIND_NOT_ENABLED


class AdmissionPending(RegistryRefused):
    reason = RefusalReason.ADMISSION_PENDING


class NominationRequiresPolicy(AdmissionPending):
    """A SHADOW to CHALLENGER PROMOTE: its k-checks belong to AUT-5a (WP1b)."""


class RuleSetPending(AdmissionPending):
    """An HWM_RESET: its store admission belongs to AUT-5a (WP1b c)."""


class PartialReplay(RegistryRefused):
    """Some, not all, of a batch's transition ids are already stored."""


class ReplayMismatch(RegistryRefused):
    """A stored row has the submitted ``transition_id`` but a different body (E-17 a)."""


class KindRefused(RegistryRefused):
    """The kind is outside ``KIND_MASK[mode]``."""


class ModeNotConcrete(RegistryRefused):
    """``mode`` is not a ``WriterMode`` member."""


class RowRefused(RegistryRefused):
    """The batch or a row is malformed (shape, pair, columns)."""


class CasMismatch(RegistryRefused):
    """``max(venue_seq)`` is not the ``expected_prior_seq`` the writer asserted.

    The engine's retry contract is ``isinstance(error, CasMismatch)``: re-read the head, rebuild the
    batch, append again (ARCH l.530). CAS runs before the clock check so a stale writer sees this.
    """


class ClockRefused(RegistryRefused):
    """``clock_invalid`` (outside ``[now - skew, now]``) or ``clock_before_head`` (E-17 c)."""

    reason = RefusalReason.CLOCK_INVALID


class FoldRefused(RegistryRefused):
    """The extended chain does not fold."""


class ValidateRefused(RegistryRefused):
    """``transitions.validate`` refused the batch (AC 10.9).

    ``reason`` is its closed reason, ``rule`` the precise rule and ``row_index`` the batch row: a
    deterministic refusal the engine must not retry (A7d-R2).
    """

    def __init__(self, detail: str, *, refusal: transitions.Refusal) -> None:
        self.rule = refusal.rule
        self.row_index = refusal.row_index
        super().__init__(detail, reason=refusal.reason)


class ChainRefused(RegistryRefused):
    """A stored or extended chain does not verify (the wrapped ``ChainBroken``)."""

    reason = RefusalReason.CHAIN_BROKEN


class StoreUnavailable(RegistryRefused):
    """Base of ``StoreBusy`` and ``StoreDrifted``: nothing was written."""

    reason = RefusalReason.REGISTRY_UNREADABLE


class StoreBusy(StoreUnavailable):
    """Another writer holds the database (SQLITE_BUSY or LOCKED); retryable (Y19, 60 s)."""


class StoreDrifted(StoreUnavailable):
    """Schema drift, a foreign or missing database, bad modes, an integrity or I/O error."""


_BUSY_CODES: Final = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})


def _unavailable(exc: sqlite3.Error, what: str) -> StoreUnavailable:
    code = getattr(exc, "sqlite_errorcode", None)
    detail = f"{what}: {type(exc).__name__}"
    if isinstance(code, int) and code & 0xFF in _BUSY_CODES:
        return StoreBusy(detail)
    return StoreDrifted(detail)


_FOLD_REFUSALS: Final[Mapping[FoldInvalidReason, RefusalReason]] = MappingProxyType(
    {
        FoldInvalidReason.FAMILY_INTRODUCED_BY_OTHER_KIND: RefusalReason.FAMILY_NOT_INTRODUCED,
        FoldInvalidReason.ROOT_LINEAGE_MISMATCH: RefusalReason.ROOT_LINEAGE_MISMATCH,
        FoldInvalidReason.HEAD_MISSING_LAUNCH_DATE: RefusalReason.ENGINE_INCONSISTENCY,
        FoldInvalidReason.CARRIED_COUNTERS_MALFORMED: RefusalReason.ENGINE_INCONSISTENCY,
    }
)


@dataclass(frozen=True, slots=True)
class AppendResult:
    """The stored rows (sealed, with ``seq``) and whether the call was a logged no-op."""

    rows: tuple[TransitionRow, ...]
    head_venue_seq: int
    replayed: bool


# --- column rules ---------------------------------------------------------------------------------


def check_row_shape(row: TransitionRow) -> None:
    """Raise ``RowRefused`` unless ``row`` obeys the AUT-5 r7 3.2 / E-16 column rules."""
    problem = shape_problem(row)
    if problem is not None:
        raise RowRefused(f"{row.kind.value}: {problem}")


# --- row <-> database -------------------------------------------------------------------------


def _encode_ids(ids: tuple[str, ...] | None) -> str | None:
    return None if ids is None else ",".join(ids)


def _to_db(row: TransitionRow) -> tuple[object, ...]:
    wire = row.to_wire()
    wire["cause_verdict_ids"] = _encode_ids(row.cause_verdict_ids)
    wire["voids_transition_ids"] = _encode_ids(row.voids_transition_ids)
    wire["carried_counters"] = row.carried_counters
    return tuple(int(v) if isinstance(v, bool) else v for v in (wire[n] for n in _INSERT_COLUMNS))


def _from_db(record: Sequence[object]) -> TransitionRow:
    try:
        return row_from_record(record)
    except RowDecodeError as exc:
        raise StoreDrifted(f"stored row does not decode: {exc}") from exc


def _seal(
    batch: Sequence[TransitionRow], verified: chain.VerifiedVenueChain
) -> list[TransitionRow]:
    """``batch`` with ``venue_seq``, ``prev_transition_hash`` and ``transition_hash`` filled in."""
    sealed: list[TransitionRow] = []
    prev = verified.head_hash
    for offset, row in enumerate(batch, start=1):
        linked = TransitionRow.from_wire(
            {
                **row.to_wire(),
                "venue_seq": verified.head_venue_seq + offset,
                "prev_transition_hash": prev,
            }
        )
        current = chain.transition_hash(linked, prev)
        sealed.append(TransitionRow.from_wire({**linked.to_wire(), "transition_hash": current}))
        prev = current
    return sealed


# --- the store ------------------------------------------------------------------------------------


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class RegistryStore:
    """The one writer of one registry root's ``registry.sqlite``.

    ``repo_root`` is supplied by the caller and bound, with ``paths``, into the manifest-facts
    reader that ``transitions.validate`` takes (AC 10 step 9); it is never derived from the
    interpreter's location or the working directory.
    """

    def __init__(self, paths: AutonomyPaths | ShadowPaths, *, repo_root: Path) -> None:
        if not isinstance(paths, AutonomyPaths | ShadowPaths):
            raise TypeError("paths must be AutonomyPaths or ShadowPaths")
        if not isinstance(repo_root, Path) or not repo_root.is_absolute():
            raise ValueError("repo_root must be an absolute Path")
        self._paths = paths
        self._db = paths.registry_db()
        #: The families a BOOTSTRAP or ROOT_ADMIT introduced, refreshed per append: their
        #: manifests are read repo-only (E-14 rule 3a), as the replay reads them (A8b-R5 L4).
        self._roots: set[str] = set()
        self._manifests: ManifestFactsReader = functools.partial(
            read_manifest_facts, paths=paths, repo_root=repo_root, roots=self._roots
        )

    @classmethod
    def initialise(cls, paths: AutonomyPaths | ShadowPaths, *, repo_root: Path) -> RegistryStore:
        """Create the 0700 directory and 0600 file and the schema; verify them when present."""
        store = cls(paths, repo_root=repo_root)
        store._create_file()
        conn = store._open()
        try:
            conn.execute(_BEGIN)
            if conn.execute(_COUNT_MASTER).fetchone()[0] == 0:
                store._install_schema(conn)
            store._check_schema(conn)
            conn.execute(_COMMIT)
        except sqlite3.Error as exc:
            raise _unavailable(exc, "initialise failed") from exc
        finally:
            _release(conn, committed=False)
        return store

    def _create_file(self) -> None:
        try:
            rootfd = single_read.open_root(self._paths.root)
        except single_read.SingleReadRefused as exc:
            raise StoreDrifted(f"data root: {exc.reason.value}") from exc
        try:
            dirfd = single_read.ensure_dir(rootfd, _REGISTRY_DIR, mode=DIR_MODE)
        except single_read.SingleReadRefused as exc:
            raise StoreDrifted(f"registry directory: {exc.reason.value}") from exc
        finally:
            os.close(rootfd)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            try:
                fd = os.open(self._db.name, flags, FILE_MODE, dir_fd=dirfd)
            except FileExistsError:
                return
            try:
                os.fchmod(fd, FILE_MODE)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(dirfd)
        except OSError as exc:
            raise StoreDrifted(f"database file: {type(exc).__name__}") from exc
        finally:
            os.close(dirfd)

    def _open(self) -> sqlite3.Connection:
        """A writer connection to an existing file: pragmas set and read back, autocommit off."""
        try:
            info = os.lstat(self._db)
            directory = os.lstat(self._db.parent)
        except OSError as exc:
            raise StoreDrifted(f"database file: {type(exc).__name__}") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise StoreDrifted("database file is not a regular file owned by this user")
        if stat.S_IMODE(info.st_mode) != FILE_MODE or stat.S_IMODE(directory.st_mode) != DIR_MODE:
            raise StoreDrifted("database file or directory mode is not 0600/0700")
        uri = f"{self._db.as_uri()}?mode=rw"
        try:
            conn = sqlite3.connect(
                uri, uri=True, timeout=WRITER_BUSY_TIMEOUT_S, isolation_level=None
            )
        except sqlite3.Error as exc:
            raise _unavailable(exc, "open failed") from exc
        try:
            self._apply_pragmas(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        try:
            for setter, readback, expected in _WRITER_PRAGMAS:
                conn.execute(setter)
                got = conn.execute(readback).fetchone()[0]
                if got != expected:
                    raise StoreDrifted(f"pragma not applied: {readback}")
        except sqlite3.Error as exc:
            raise _unavailable(exc, "pragma failed") from exc

    @staticmethod
    def _install_schema(conn: sqlite3.Connection) -> None:
        for _kind, _name, ddl in DDL_OBJECTS:
            conn.execute(ddl)
        conn.execute(_INSERT_META, (SCHEMA_ID,))
        conn.execute(_SET_APPLICATION_ID)
        conn.execute(_SET_USER_VERSION)

    @staticmethod
    def _check_schema(conn: sqlite3.Connection) -> None:
        """Refuse a database whose identity or any owned object differs from the DDL constants."""
        app_id = conn.execute(_PRAGMA_APPLICATION_ID).fetchone()[0]
        version = conn.execute(_PRAGMA_USER_VERSION).fetchone()[0]
        meta = [row[0] for row in conn.execute(_SELECT_META)]
        objects = {tuple(row) for row in conn.execute(SELECT_MASTER)}
        if (
            app_id != APPLICATION_ID
            or version != USER_VERSION
            or meta != [SCHEMA_ID]
            or objects != set(DDL_OBJECTS)
        ):
            raise StoreDrifted("registry schema differs from the DDL constants")

    # --- append -----------------------------------------------------------------------------

    def append(
        self,
        rows: Sequence[TransitionRow],
        *,
        expected_prior_seq: int,
        mode: WriterMode,
        now_ns: int,
    ) -> AppendResult:
        """Append ``rows`` to their venue's chain under the canonical stage (AC 10)."""
        return self._append(
            rows,
            expected_prior_seq=expected_prior_seq,
            mode=mode,
            now_ns=now_ns,
            stage=stage_policy.STAGE,
            _fixture_stage=False,
        )

    def _append(
        self,
        rows: Sequence[TransitionRow],
        *,
        expected_prior_seq: int,
        mode: WriterMode,
        now_ns: int,
        stage: StageView,
        _fixture_stage: bool = False,
    ) -> AppendResult:
        if stage is not stage_policy.STAGE and not _fixture_stage:
            raise StageNotCanonical("the stage is not stage_policy.STAGE")
        try:
            batch = _check_batch(rows, expected_prior_seq, now_ns)
        except (WireRefused, ValueError, TypeError) as exc:
            raise RowRefused(f"malformed batch: {type(exc).__name__}") from exc
        conn = self._open()
        committed = False
        try:
            conn.execute(_BEGIN)
            result = self._append_in_transaction(
                conn, batch, expected_prior_seq, mode, now_ns, stage
            )
            conn.execute(_COMMIT)
            committed = True
            return result
        except sqlite3.Error as exc:
            raise _unavailable(exc, "write failed") from exc
        except ChainBroken as exc:
            raise ChainRefused(f"venue_seq {exc.venue_seq}: {exc.detail}") from exc
        except (WireRefused, ValueError, TypeError) as exc:
            raise RowRefused(f"row refused: {type(exc).__name__}") from exc
        finally:
            _release(conn, committed=committed)

    def _append_in_transaction(
        self,
        conn: sqlite3.Connection,
        batch: tuple[TransitionRow, ...],
        expected_prior_seq: int,
        mode: WriterMode,
        now_ns: int,
        stage: StageView,
    ) -> AppendResult:
        self._check_schema(conn)
        stored = [_read_by_id(conn, row.transition_id) for row in batch]
        for submitted, existing in zip(batch, stored, strict=True):
            if existing is not None and _replay_body(existing) != _replay_body(submitted):
                raise ReplayMismatch("a stored row has this transition_id and another body")
        if all(row is not None for row in stored):
            _LOG.info("registry append is a replay: %d rows already stored", len(batch))
            replayed = tuple(row for row in stored if row is not None)
            head = conn.execute(_SELECT_HEAD_SEQ, (batch[0].venue,)).fetchone()[0]
            return AppendResult(replayed, head, True)
        if any(row is not None for row in stored):
            raise PartialReplay("some, not all, transition ids are already stored")
        if not isinstance(mode, WriterMode):
            raise ModeNotConcrete("mode must be a WriterMode member")
        _check_mask_and_admission(batch, mode, stage)
        venue = batch[0].venue
        prior = [_from_db(r) for r in conn.execute(_SELECT_VENUE, (venue,))]
        head = conn.execute(_SELECT_HEAD_SEQ, (venue,)).fetchone()[0]
        if head != expected_prior_seq:  # before the clock: a stale writer retries (E-17 d)
            raise CasMismatch(f"head venue_seq {head} is not the expected prior seq")
        _check_clock(batch, prior, now_ns)
        extended = _verify_structure(prior, batch, venue, now_ns)
        self._validate(prior, batch, now_ns)
        for row in extended:
            conn.execute(_INSERT_ROW, _to_db(row))
        written = [_from_db(r) for r in conn.execute(_SELECT_AFTER, (venue, head))]
        return AppendResult(tuple(written), head + len(written), False)

    def _validate(
        self,
        prior: Sequence[TransitionRow],
        batch: Sequence[TransitionRow],
        now_ns: int,
    ) -> None:
        """AC 10 step 9: the semantic rules, against the fold of the rows already written.

        The prior rows fold at the batch's first ``ts_ns``, the stamp, not at ``now_ns``: a row
        stamped 16:49:59 and committed after LAUNCH is judged against a pair not yet in effect, so
        the store and ``replay_full`` give one answer (A8b-R3). ``now_ns`` still bounds the stamp.
        """
        self._roots.clear()
        self._roots.update(roots_of((*prior, *batch)))
        folded = fold(prior, batch[0].venue, batch[0].ts_ns)
        if isinstance(folded, FoldInvalid):
            raise FoldRefused(folded.reason.value, reason=_FOLD_REFUSALS[folded.reason])
        refusal = transitions.first_refusal(folded, batch, manifests=self._manifests)
        if refusal is not None:
            raise ValidateRefused(
                f"{refusal.rule.value} at row {refusal.row_index}", refusal=refusal
            )


#: Columns a replay may differ in: the position, the clock, the writer's identity and the hashes.
_REPLAY_IGNORED: Final = frozenset(
    {
        "seq", "venue_seq", "ts_ns", "invocation_id", "expected_prior_seq",
        "prev_transition_hash", "transition_hash",
    }
)  # fmt: skip


def _replay_body(row: TransitionRow) -> dict[str, object]:
    return {k: v for k, v in row.to_wire().items() if k not in _REPLAY_IGNORED}


def _release(conn: sqlite3.Connection, *, committed: bool) -> None:
    """Roll back an open transaction and close; a failing ROLLBACK must not mask the real error."""
    try:
        if not committed and conn.in_transaction:
            conn.execute(_ROLLBACK)
    except sqlite3.Error:
        _LOG.warning("registry rollback failed; closing the connection")
    finally:
        conn.close()


def _read_by_id(conn: sqlite3.Connection, transition_id: str) -> TransitionRow | None:
    record = conn.execute(_SELECT_BY_ID, (transition_id,)).fetchone()
    return None if record is None else _from_db(record)


def _check_batch(
    rows: Sequence[TransitionRow], expected_prior_seq: int, now_ns: int
) -> tuple[TransitionRow, ...]:
    """The pure, I/O-free refusals: batch structure, column rules, integers."""
    for name, value in (("expected_prior_seq", expected_prior_seq), ("now_ns", now_ns)):
        if not _is_count(value):
            raise RowRefused(f"{name} must be a non-negative int")
    batch = tuple(rows)
    if not batch:
        raise RowRefused("the batch is empty")
    if not all(isinstance(row, TransitionRow) for row in batch):
        raise RowRefused("the batch holds a non-TransitionRow")
    venue = check_venue(batch[0].venue)
    if any(row.venue != venue for row in batch):
        raise RowRefused("the batch spans more than one venue")
    if len({row.transition_id for row in batch}) != len(batch):
        raise RowRefused("the batch repeats a transition_id")
    for row in batch:
        chain_columns = (row.seq, row.venue_seq, row.prev_transition_hash, row.transition_hash)
        if any(value is not None for value in chain_columns):
            raise RowRefused("rows arrive unsealed: the store assigns the chain columns")
        if row.transition_id != row.computed_transition_id():
            raise RowRefused("transition_id is not the id computed from the row")
        if row.expected_prior_seq != expected_prior_seq:
            raise RowRefused("a row's expected_prior_seq is not the batch's")
        check_row_shape(row)
    return batch


def _check_mask_and_admission(
    batch: Sequence[TransitionRow], mode: WriterMode, stage: StageView
) -> None:
    """AC 10 steps 4-6. The admissibility predicate has one home, ``transitions``."""
    mask = transitions.KIND_MASK[mode]
    for row in batch:
        if row.kind not in mask:
            raise KindRefused(f"{row.kind.value} is outside the {mode.value} mask")
    admission = transitions.rows_admissible(batch, stage=stage)
    if admission.reason is RefusalReason.WIDENING_KIND_NOT_ENABLED:
        raise WideningNotEnabled(batch[admission.admitted].kind.value)
    if admission.reason is RefusalReason.ADMISSION_PENDING:
        raise AdmissionPending(batch[admission.admitted].kind.value)
    for row in batch:
        if is_nomination(row):
            raise NominationRequiresPolicy("nomination k-checks are not implemented")
        if row.kind is Kind.HWM_RESET:
            raise RuleSetPending("HWM_RESET admission is not implemented")


def _check_clock(
    batch: Sequence[TransitionRow], prior: Sequence[TransitionRow], now_ns: int
) -> None:
    """AC 10 step 7: ``now - skew <= ts <= now`` (E-17 c) and monotone over the head."""
    floor = now_ns - pins.ROW_TS_MAX_SKEW_S * _NS_PER_S
    previous = prior[-1].ts_ns if prior else 0
    for row in batch:
        if not floor <= row.ts_ns <= now_ns:
            raise ClockRefused("row ts_ns is after now_ns or older than the allowed skew")
        if row.ts_ns < previous:
            raise ClockRefused(
                "row ts_ns precedes the head", reason=RefusalReason.CLOCK_BEFORE_HEAD
            )
        previous = row.ts_ns


def _verify_structure(
    prior: Sequence[TransitionRow], batch: Sequence[TransitionRow], venue: str, now_ns: int
) -> list[TransitionRow]:
    """AC 10 step 9, structural part: the chain verifies and the extension folds."""
    verified = chain.verify_venue_chain(prior, venue)
    sealed = _seal(batch, verified)
    extended = chain.verify_extension(verified, sealed)
    folded = fold(extended.rows, venue, now_ns)
    if isinstance(folded, FoldInvalid):
        raise FoldRefused(folded.reason.value, reason=_FOLD_REFUSALS[folded.reason])
    return sealed
