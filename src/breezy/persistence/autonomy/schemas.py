"""Pyarrow-free closed enums and records for the autonomy registry (ARCH-0 seam A 6a).

This module imports only ``wire``, ``canonical`` and ``rollback_journal`` (also under
``TYPE_CHECKING``), so everything that must stay light can import it. Types that reach pyarrow
live with the module that needs them (A4-R1) and are never named here.

``TransitionRow`` carries every C5 column. ``seq``, ``venue_seq``, ``prev_transition_hash`` and
``transition_hash`` are ``None`` on a row the store has not yet written. Non-integer quantities
are canonical decimal strings on the wire (ruling A5-R1), never floats. Construction validates and
raises ``WireRefused``; records serialise through ``to_wire`` and ``from_wire`` and never through
``dataclasses.asdict``.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final, Protocol, Self

from breezy.persistence.autonomy.canonical import CanonicalTypeError, canonical_json, sha256_hex
from breezy.persistence.autonomy.rollback_journal import JournalHead
from breezy.persistence.autonomy.wire import (
    SHA256_RE,
    WireRefusalReason,
    WireRefused,
    check_decimal,
    check_int,
    check_match,
    check_sha256,
    decimal_wire,
    optional_decimal_str,
    parse_json_exact,
    require_exact_keys,
    require_int,
    require_list,
    require_ns,
    require_object,
    require_str,
)

__all__ = [
    "AdmissibilityResult",
    "CauseClass",
    "CauseCode",
    "DecidedBy",
    "ExportTrailer",
    "FoldInvalidReason",
    "Kind",
    "LiveOrdersRefusal",
    "ManifestFacts",
    "ManifestFactsReader",
    "RefusalReason",
    "StagePolicy",
    "StageView",
    "State",
    "TransitionRow",
    "UnreadableReason",
    "WriterMode",
    "check_venue",
    "compute_transition_id",
]

#: Local copies of ``paths.VENUE_RE``, ``paths.FAMILY_RE`` and ``paths.JOURNAL_KIND_RE``. They exist
#: because the plan's import list for this module is wire, canonical and rollback_journal only, not
#: because a contract forbids ``paths`` (it is reachable transitively). A test asserts that pattern
#: and flags equal the originals.
VENUE_RE: Final[re.Pattern[str]] = re.compile(r"\A[a-z0-9_]{1,32}\Z", re.ASCII)
FAMILY_RE: Final[re.Pattern[str]] = re.compile(r"\A[a-z0-9_]{1,64}\Z", re.ASCII)
JOURNAL_KIND_RE: Final[re.Pattern[str]] = re.compile(r"\A[a-z0-9_]{1,48}\Z", re.ASCII)
_UUID_RE: Final[re.Pattern[str]] = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.ASCII
)
_RULING_ID_RE: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z0-9_.:-]{0,128}\Z", re.ASCII)
_COMPOSITION_RE: Final[re.Pattern[str]] = re.compile(r"\A[a-z_]{1,48}\Z", re.ASCII)
_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z0-9_/.:-]{1,200}\Z", re.ASCII)
EXPORT_SCHEMA: Final = "registry_export/v1"


class State(StrEnum):
    SHADOW = "SHADOW"
    CHALLENGER = "CHALLENGER"
    CHAMPION = "CHAMPION"
    HALTED = "HALTED"
    RETIRED = "RETIRED"


class Kind(StrEnum):
    BOOTSTRAP = "BOOTSTRAP"
    MINT = "MINT"
    PROMOTE = "PROMOTE"
    DRILL_ADMIT = "DRILL_ADMIT"
    DRILL_PROMOTE = "DRILL_PROMOTE"
    ROLLBACK = "ROLLBACK"
    ROOT_ADMIT = "ROOT_ADMIT"
    SUPERSEDE = "SUPERSEDE"
    DISPLACED = "DISPLACED"
    ACTIVATE = "ACTIVATE"
    SWAP_CANCEL = "SWAP_CANCEL"
    TARGET_INELIGIBLE = "TARGET_INELIGIBLE"
    ATTEST = "ATTEST"
    DEMOTE = "DEMOTE"
    HALT = "HALT"
    RESUME = "RESUME"
    RETIRE = "RETIRE"
    HWM_RESET = "HWM_RESET"


class CauseClass(StrEnum):
    RECOVERABLE_MODEL = "RECOVERABLE_MODEL"
    RECOVERABLE_INFRA = "RECOVERABLE_INFRA"
    DRILL = "DRILL"
    TERMINAL = "TERMINAL"
    INTEGRITY = "INTEGRITY"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"


class CauseCode(StrEnum):
    """Closed; equal to ``pins.CAUSE_CODES`` (test-asserted; ``pins`` is not imported here)."""

    VERDICT_FAIL = "verdict_fail"
    EXEC_STORE_HALT_MIRROR = "exec_store_halt_mirror"
    PAIR_CAUSE_INCOMING = "pair_cause_incoming"
    PAIR_CAUSE_OUTGOING = "pair_cause_outgoing"
    PRELAUNCH_PRECHECK_FAILED = "prelaunch_precheck_failed"
    ENGINE_INCONSISTENCY = "engine_inconsistency"
    INFRA_BUDGET_EXHAUSTED = "infra_budget_exhausted"
    MODEL_BUDGET_EXHAUSTED = "model_budget_exhausted"
    ROLLBACK_FAILED = "rollback_failed"
    TARGET_INTEGRITY = "target_integrity"
    DRILL_CLOSE_RESTORE = "drill_close_restore"


class WriterMode(StrEnum):
    DAILY = "DAILY"
    INTRADAY = "INTRADAY"
    PRELAUNCH = "PRELAUNCH"
    BOOTSTRAP = "BOOTSTRAP"
    OPERATOR_CLI = "OPERATOR_CLI"


class DecidedBy(StrEnum):
    ENGINE = "engine"
    OPERATOR_CLI = "operator_cli"


class RefusalReason(StrEnum):
    """The closed reasons a registry read, write or resolve is refused (AC 17 refusal set)."""

    REGISTRY_UNREADABLE = "registry_unreadable"
    EMPTY_CHAIN = "empty_chain"
    CHAIN_BROKEN = "chain_broken"
    CLOCK_INVALID = "clock_invalid"
    CLOCK_BEFORE_HEAD = "clock_before_head"
    HWM_UNREADABLE = "hwm_unreadable"
    HWM_ABSENT = "hwm_absent"
    HWM_REGRESSED = "hwm_regressed"
    EXPORT_UNREADABLE = "export_unreadable"
    EXPORT_PREFIX_MISMATCH = "export_prefix_mismatch"
    WIDENING_KIND_NOT_ENABLED = "widening_kind_not_enabled"
    ADMISSION_PENDING = "admission_pending"
    REPLAY_INVALID = "replay_invalid"
    REPLAY_CAUSE_UNRESOLVED = "replay_cause_unresolved"
    REPLAY_ARTEFACT_MISMATCH = "replay_artefact_mismatch"
    ENGINE_INCONSISTENCY = "engine_inconsistency"
    NO_SENDER = "no_sender"
    PATHS_ROLE_MISMATCH = "paths_role_mismatch"
    STAGE_NOT_CANONICAL = "stage_not_canonical"
    FAMILY_NOT_INTRODUCED = "family_not_introduced"
    ROOT_LINEAGE_MISMATCH = "root_lineage_mismatch"
    ENGINE_CODE_UNPINNED = "engine_code_unpinned"
    ENGINE_CODE_REVOKED = "engine_code_revoked"
    MANIFEST_UNREADABLE = "manifest_unreadable"
    MANIFEST_INVALID = "manifest_invalid"
    MANIFEST_DRAFT = "manifest_draft"
    MANIFEST_UNPINNED = "manifest_unpinned"
    PREREG_INELIGIBLE = "prereg_ineligible"
    MANIFEST_SHA_MISMATCH = "manifest_sha_mismatch"
    MANIFEST_IDENTITY_MISMATCH = "manifest_identity_mismatch"
    KIND_NOT_LIVE_GATE_ROUTED = "kind_not_live_gate_routed"
    ARTEFACT_UNREADABLE = "artefact_unreadable"
    ARTEFACT_SHA_MISMATCH = "artefact_sha_mismatch"
    ROOT_RECORD_MISMATCH = "root_record_mismatch"
    CHILD_ROOT_MISMATCH = "child_root_mismatch"
    CHILD_NOT_EQUAL_ROOT = "child_not_equal_root"
    ROOT_NOT_LINEAGE_ALLOWLISTED = "root_not_lineage_allowlisted"
    RULING_NOT_POLICY = "ruling_not_policy"
    RULING_REFUSED = "ruling_refused"
    NO_LIVE_ORDERS_RULING = "no_live_orders_ruling"
    D0_BREACH = "d0_breach"
    TRIAL_PREFIX_MISMATCH = "trial_prefix_mismatch"


class UnreadableReason(StrEnum):
    """Why the reader could not read the registry (AC 12)."""

    BUSY = "busy"
    HOT_JOURNAL = "hot_journal"
    SCHEMA_MISMATCH = "schema_mismatch"
    IO = "io"
    SQLITE_ERROR = "sqlite_error"
    VENUE_MALFORMED = "venue_malformed"  # the resolver was asked about no well-formed venue


class LiveOrdersRefusal(StrEnum):
    """Local mirror of ``live_orders_gate.LiveOrdersReason`` (test-asserted equal; A4-R1)."""

    NO_RULING = "no_ruling"
    NOT_ALLOWLISTED = "not_allowlisted"
    RULING_MISSING = "ruling_missing"
    RULING_OUTSIDE_EVIDENCE = "ruling_outside_evidence"
    RULING_SHA_MISMATCH = "ruling_sha_mismatch"
    PERMIT_ABSENT = "permit_absent"
    OK = "ok"


class FoldInvalidReason(StrEnum):
    FAMILY_INTRODUCED_BY_OTHER_KIND = "family_introduced_by_other_kind"
    ROOT_LINEAGE_MISMATCH = "root_lineage_mismatch"
    HEAD_MISSING_LAUNCH_DATE = "head_missing_launch_date"  # E-16 (c)
    CARRIED_COUNTERS_MALFORMED = "carried_counters_malformed"  # A7b-R1 (erratum E-20 requested)


def check_venue(value: object) -> str:
    """``value`` when it is a well-formed venue id (``WireRefused`` otherwise)."""
    return check_match(value, VENUE_RE, "venue")


def _bad(reason: WireRefusalReason, field: str) -> WireRefused:
    return WireRefused(reason, field)


def _is_enum[E: StrEnum](value: object, cls: type[E], field: str) -> E:
    if not isinstance(value, cls):
        raise _bad(WireRefusalReason.WRONG_TYPE, field)
    return value


def _opt_enum[E: StrEnum](value: object, cls: type[E], field: str) -> E | None:
    return None if value is None else _is_enum(value, cls, field)


def _opt_int(value: object, field: str) -> int | None:
    return None if value is None else check_int(value, field)


def _opt_sha(value: object, field: str) -> str | None:
    return None if value is None else check_sha256(value, field)


def _sha_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise _bad(WireRefusalReason.WRONG_TYPE, field)
    ids = tuple(check_sha256(v, field) for v in value)
    if len(set(ids)) != len(ids):
        raise _bad(WireRefusalReason.BAD_VALUE, field)
    return ids


def _iso_date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise _bad(WireRefusalReason.WRONG_TYPE, field)
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError(value)
    except ValueError as exc:
        raise _bad(WireRefusalReason.BAD_VALUE, field) from exc
    return value


def _check_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise _bad(WireRefusalReason.WRONG_TYPE, field)
    return value


def _check_counters(value: object) -> str | None:
    """Canonical-JSON text of a counters object, or ``None`` (shape is the fold's to define)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _bad(WireRefusalReason.WRONG_TYPE, "carried_counters")
    parsed = parse_json_exact(value)
    if canonical_json(parsed).decode("utf-8") != value:
        raise _bad(WireRefusalReason.BAD_VALUE, "carried_counters")
    return value


def _check_ruling_sha(value: object) -> str:
    """A 64-hex digest, or ``""`` (the C5 fallback with no policy ruling)."""
    if value == "":
        return ""
    return check_sha256(value, "policy_ruling_sha256")


def compute_transition_id(
    *,
    venue: str,
    family_id: str,
    family_prior_seq: int,
    from_state: State | None,
    to_state: State,
    kind: Kind,
    cause_verdict_ids: Sequence[str],
    paired_transition_id: str | None,
    policy_ruling_sha256: str,
) -> str:
    """The Y9 idempotency id: sha256 of the identity tuple, with no ``expected_prior_seq``.

    The venue-wide ``expected_prior_seq`` is excluded so a crash-and-retry reproduces the id, while
    a later repeat of the same transition for the same family has a new ``family_prior_seq``.
    """
    check_match(venue, VENUE_RE, "venue")
    check_match(family_id, FAMILY_RE, "family_id")
    check_int(family_prior_seq, "family_prior_seq")
    _opt_enum(from_state, State, "from_state")
    _is_enum(to_state, State, "to_state")
    _is_enum(kind, Kind, "kind")
    if isinstance(cause_verdict_ids, str):
        raise _bad(WireRefusalReason.WRONG_TYPE, "cause_verdict_ids")
    verdict_ids = _sha_tuple(tuple(cause_verdict_ids), "cause_verdict_ids")
    _opt_sha(paired_transition_id, "paired_transition_id")
    _check_ruling_sha(policy_ruling_sha256)
    preimage = {
        "venue": venue,
        "family_id": family_id,
        "family_prior_seq": family_prior_seq,
        "from_state": None if from_state is None else from_state.value,
        "to_state": to_state.value,
        "kind": kind.value,
        "cause_verdict_ids": sorted(verdict_ids),
        "paired_transition_id": paired_transition_id,
        "policy_ruling_sha256": policy_ruling_sha256,
    }
    return sha256_hex(canonical_json(preimage))


_ROW_KEYS: Final = (
    "seq", "venue", "venue_seq", "transition_id", "family_id", "family_prior_seq",
    "paired_transition_id", "from_state", "to_state", "kind", "cause_verdict_ids", "cause_code",
    "halt_cause_class", "trigger_cause_class", "voids_transition_ids", "manifest_sha256",
    "artefact_sha256", "lineage_root_family_id", "attest_valid_until_ns", "k_life", "alpha_k",
    "n_min_eff", "n_cap", "nomination_feasible", "hwm_from", "hwm_to", "carried_counters", "drill",
    "drill_clause_sha256", "policy_ruling_id", "policy_ruling_sha256", "decided_by",
    "invocation_id", "engine_code_sha", "expected_prior_seq", "effective_launch_date", "ts_ns",
    "prev_transition_hash", "transition_hash",
)  # fmt: skip


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionRow:
    """One C5 ``transitions`` row. The four chain columns are ``None`` until the store seals it."""

    venue: str
    family_id: str
    to_state: State
    kind: Kind
    transition_id: str
    decided_by: DecidedBy
    invocation_id: str
    engine_code_sha: str
    ts_ns: int
    family_prior_seq: int
    expected_prior_seq: int
    seq: int | None = None
    venue_seq: int | None = None
    paired_transition_id: str | None = None
    from_state: State | None = None
    cause_verdict_ids: tuple[str, ...] = ()
    cause_code: CauseCode | None = None
    halt_cause_class: CauseClass | None = None
    trigger_cause_class: CauseClass | None = None
    voids_transition_ids: tuple[str, ...] | None = None
    manifest_sha256: str | None = None
    artefact_sha256: str | None = None
    lineage_root_family_id: str | None = None
    attest_valid_until_ns: int | None = None
    k_life: int | None = None
    alpha_k: Decimal | None = None
    n_min_eff: int | None = None
    n_cap: int | None = None
    nomination_feasible: bool | None = None
    #: Hold ``export_seq`` values (before and after the reset). ARCH l.425/l.490 and AUT-5 r7
    #: l.480-487 name the columns but not the seq; ruling A6a-R5 fixes this reading.
    hwm_from: int | None = None
    hwm_to: int | None = None
    #: Canonical-JSON text (an immutable, byte-stable form); the object shape belongs to the fold.
    carried_counters: str | None = None
    drill: bool = False
    drill_clause_sha256: str | None = None
    policy_ruling_id: str = ""
    policy_ruling_sha256: str = ""
    effective_launch_date: str | None = None
    prev_transition_hash: str | None = None
    transition_hash: str | None = None

    def __post_init__(self) -> None:
        check_match(self.venue, VENUE_RE, "venue")
        check_match(self.family_id, FAMILY_RE, "family_id")
        check_sha256(self.transition_id, "transition_id")
        check_match(self.invocation_id, _UUID_RE, "invocation_id")
        check_sha256(self.engine_code_sha, "engine_code_sha")
        check_match(self.policy_ruling_id, _RULING_ID_RE, "policy_ruling_id")
        _check_ruling_sha(self.policy_ruling_sha256)
        if (self.policy_ruling_id == "") != (self.policy_ruling_sha256 == ""):
            raise _bad(WireRefusalReason.BAD_VALUE, "policy_ruling_id")
        _is_enum(self.to_state, State, "to_state")
        _is_enum(self.kind, Kind, "kind")
        _is_enum(self.decided_by, DecidedBy, "decided_by")
        _opt_enum(self.from_state, State, "from_state")
        _opt_enum(self.cause_code, CauseCode, "cause_code")
        _opt_enum(self.halt_cause_class, CauseClass, "halt_cause_class")
        _opt_enum(self.trigger_cause_class, CauseClass, "trigger_cause_class")
        for name in ("ts_ns", "family_prior_seq", "expected_prior_seq"):
            check_int(getattr(self, name), name)
        for name in (
            "attest_valid_until_ns", "k_life", "n_min_eff", "n_cap", "hwm_from", "hwm_to",
        ):  # fmt: skip
            _opt_int(getattr(self, name), name)
        if self.seq is not None:
            check_int(self.seq, "seq", minimum=1)
        if self.venue_seq is not None:
            check_int(self.venue_seq, "venue_seq", minimum=1)
        for name in (
            "paired_transition_id", "manifest_sha256", "artefact_sha256", "drill_clause_sha256",
            "prev_transition_hash", "transition_hash",
        ):  # fmt: skip
            _opt_sha(getattr(self, name), name)
        _sha_tuple(self.cause_verdict_ids, "cause_verdict_ids")
        if self.voids_transition_ids is not None:
            _sha_tuple(self.voids_transition_ids, "voids_transition_ids")
        if self.lineage_root_family_id is not None:
            check_match(self.lineage_root_family_id, FAMILY_RE, "lineage_root_family_id")
        if self.alpha_k is not None:
            check_decimal(self.alpha_k, "alpha_k")
        if self.nomination_feasible is not None:
            _check_bool(self.nomination_feasible, "nomination_feasible")
        _check_bool(self.drill, "drill")
        _check_counters(self.carried_counters)
        if self.effective_launch_date is not None:
            _iso_date(self.effective_launch_date, "effective_launch_date")

    def computed_transition_id(self) -> str:
        """The Y9 id these fields imply (``expected_prior_seq`` is not among them)."""
        return compute_transition_id(
            venue=self.venue,
            family_id=self.family_id,
            family_prior_seq=self.family_prior_seq,
            from_state=self.from_state,
            to_state=self.to_state,
            kind=self.kind,
            cause_verdict_ids=self.cause_verdict_ids,
            paired_transition_id=self.paired_transition_id,
            policy_ruling_sha256=self.policy_ruling_sha256,
        )

    def to_wire(self) -> dict[str, object]:
        """Every C5 column; ``None`` is a JSON null and enums are their values."""
        out: dict[str, object] = {}
        for name in _ROW_KEYS:
            value = getattr(self, name)
            if isinstance(value, StrEnum):
                value = value.value
            elif isinstance(value, tuple):
                value = list(value)
            elif isinstance(value, Decimal):
                value = decimal_wire(value)
            out[name] = value
        counters = self.carried_counters
        out["carried_counters"] = None if counters is None else parse_json_exact(counters)
        return out

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=_ROW_KEYS)
        values: dict[str, object] = {k: obj[k] for k in _ROW_KEYS}
        for name, enum_cls in _ENUM_FIELDS.items():
            values[name] = _wire_enum(obj, name, enum_cls)
        for name in ("cause_verdict_ids", "voids_transition_ids"):
            raw = obj[name]
            if raw is None and name == "voids_transition_ids":
                values[name] = None
            else:
                values[name] = tuple(require_list(obj, name))
        values["alpha_k"] = optional_decimal_str(obj, "alpha_k")
        raw_counters = obj["carried_counters"]
        if raw_counters is None:
            values["carried_counters"] = None
        else:
            try:
                values["carried_counters"] = canonical_json(
                    require_object(obj, "carried_counters")
                ).decode("utf-8")
            except CanonicalTypeError as exc:
                raise _bad(WireRefusalReason.BAD_VALUE, "carried_counters") from exc
        return cls(**values)  # type: ignore[arg-type]


_ENUM_FIELDS: Final[Mapping[str, type[StrEnum]]] = {
    "from_state": State,
    "to_state": State,
    "kind": Kind,
    "cause_code": CauseCode,
    "halt_cause_class": CauseClass,
    "trigger_cause_class": CauseClass,
    "decided_by": DecidedBy,
}


def _wire_enum[E: StrEnum](obj: Mapping[str, object], key: str, cls: type[E]) -> E | None:
    raw = obj[key]
    if raw is None:
        return None
    try:
        return cls(require_str(obj, key))
    except ValueError as exc:
        raise _bad(WireRefusalReason.BAD_VALUE, key) from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportTrailer:
    """The last line of ``registry_<venue>_<date>.jsonl`` (``registry_export/v1``)."""

    venue: str
    venue_seq: int
    chain_head: str
    export_seq: int
    #: ``(journal kind, newest entry)`` pairs, kinds unique.
    evidence_journal_heads: tuple[tuple[str, JournalHead], ...] = ()

    def __post_init__(self) -> None:
        check_match(self.venue, VENUE_RE, "venue")
        check_int(self.venue_seq, "venue_seq")
        check_sha256(self.chain_head, "chain_head")
        check_int(self.export_seq, "export_seq")
        kinds: set[str] = set()
        heads = self.evidence_journal_heads
        if not isinstance(heads, tuple):
            raise _bad(WireRefusalReason.WRONG_TYPE, "evidence_journal_heads")
        for pair in heads:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise _bad(WireRefusalReason.WRONG_TYPE, "evidence_journal_heads")
            kind, head = pair
            check_match(kind, JOURNAL_KIND_RE, "evidence_journal_heads")
            if kind in kinds or not isinstance(head, JournalHead):
                raise _bad(WireRefusalReason.BAD_VALUE, "evidence_journal_heads")
            check_int(head.seq, "evidence_journal_heads", minimum=1)
            check_sha256(head.sha256, "evidence_journal_heads")
            kinds.add(kind)

    def to_wire(self) -> dict[str, object]:
        heads = {
            kind: {"seq": head.seq, "sha256": head.sha256}
            for kind, head in sorted(self.evidence_journal_heads)
        }
        return {
            "schema": EXPORT_SCHEMA,
            "venue": self.venue,
            "venue_seq": self.venue_seq,
            "chain_head": self.chain_head,
            "export_seq": self.export_seq,
            "evidence_journal_heads": heads,
        }

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(
            obj,
            required=(
                "schema",
                "venue",
                "venue_seq",
                "chain_head",
                "export_seq",
                "evidence_journal_heads",
            ),
        )
        if require_str(obj, "schema") != EXPORT_SCHEMA:
            raise _bad(WireRefusalReason.UNKNOWN_SCHEMA, "schema")
        heads: list[tuple[str, JournalHead]] = []
        for kind, raw in require_object(obj, "evidence_journal_heads").items():
            check_match(kind, JOURNAL_KIND_RE, "evidence_journal_heads")
            if not isinstance(raw, dict):
                raise _bad(WireRefusalReason.WRONG_TYPE, "evidence_journal_heads")
            require_exact_keys(raw, required=("seq", "sha256"))
            seq = require_int(raw, "seq")
            if seq < 1:
                raise _bad(WireRefusalReason.BAD_VALUE, "evidence_journal_heads")
            digest = require_str(raw, "sha256")
            if SHA256_RE.fullmatch(digest) is None:
                raise _bad(WireRefusalReason.BAD_VALUE, "evidence_journal_heads")
            heads.append((kind, JournalHead(seq=seq, sha256=digest)))
        return cls(
            venue=require_str(obj, "venue"),
            venue_seq=require_ns(obj, "venue_seq"),
            chain_head=require_str(obj, "chain_head"),
            export_seq=require_ns(obj, "export_seq"),
            evidence_journal_heads=tuple(sorted(heads)),
        )


def _kind_set(value: object, field: str) -> frozenset[Kind]:
    if not isinstance(value, frozenset):
        raise _bad(WireRefusalReason.WRONG_TYPE, field)
    for member in value:
        _is_enum(member, Kind, field)
    return value


class StageView(Protocol):
    """What ``rows_admissible`` reads of a stage (read-only)."""

    @property
    def enabled_widening_kinds(self) -> Collection[Kind]: ...

    @property
    def admission_implemented(self) -> Collection[Kind]: ...


@dataclass(frozen=True, slots=True)
class StagePolicy:
    """The widening kinds a stage enables and the kinds whose admission is implemented.

    Built once, by ``stage_policy``; never constructed, replaced or copied elsewhere in ``src/``.
    """

    enabled_widening_kinds: frozenset[Kind]
    admission_implemented: frozenset[Kind]

    def __post_init__(self) -> None:
        _kind_set(self.enabled_widening_kinds, "enabled_widening_kinds")
        _kind_set(self.admission_implemented, "admission_implemented")


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestFacts:
    """The manifest facts ``transitions.validate`` needs for the d0 and identity rule (U1)."""

    family_id: str
    manifest_sha256: str
    d0_climate_day: str
    trial_id_prefix: str
    composition_kind: str
    #: The manifest's density pin; E-24: it equals the family's bound artefact, for every kind.
    density_artefact_sha256: str

    def __post_init__(self) -> None:
        check_match(self.family_id, FAMILY_RE, "family_id")
        check_sha256(self.manifest_sha256, "manifest_sha256")
        check_sha256(self.density_artefact_sha256, "density_artefact_sha256")
        _iso_date(self.d0_climate_day, "d0_climate_day")
        check_match(self.trial_id_prefix, _PREFIX_RE, "trial_id_prefix")
        check_match(self.composition_kind, _COMPOSITION_RE, "composition_kind")


class ManifestFactsReader(Protocol):
    """Reads one family's facts at a manifest sha; ``None`` when they cannot be read."""

    def __call__(self, family_id: str, manifest_sha256: str) -> ManifestFacts | None: ...


_ADMISSION_REASONS: Final = frozenset(
    {RefusalReason.WIDENING_KIND_NOT_ENABLED, RefusalReason.ADMISSION_PENDING}
)


@dataclass(frozen=True, slots=True)
class AdmissibilityResult:
    """``rows[:admitted]`` is admissible; ``reason is None`` means every row is."""

    admitted: int
    reason: RefusalReason | None

    def __post_init__(self) -> None:
        check_int(self.admitted, "admitted")
        if _opt_enum(self.reason, RefusalReason, "reason") not in {None, *_ADMISSION_REASONS}:
            raise _bad(WireRefusalReason.BAD_VALUE, "reason")
