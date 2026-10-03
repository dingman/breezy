"""C4 ``verdict/v1``: the record, its content id, and the write-once verdict store (AC 24).

``verdict_id`` is the sha256 of the canonical body without ``verdict_id`` and ``produced_at_ns``,
so a recompute of the same slot from the same inputs dedupes. ``valid_until_ns`` is slot-anchored
and stays in the body. A second write under an existing id is a no-op when the stored body differs
only in ``produced_at_ns`` and ``VerdictIdCollision`` otherwise. Every write is
``single_read.write_once`` (0600); the date directories are made by ``single_read.walk_dirs``.

Every non-integer number is a canonical decimal string (``canonical.decimal_str``). Refusals carry
enums, never paths.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Final, Self

from breezy.persistence.autonomy.canonical import canonical_json, sha256_hex
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths, family_component
from breezy.persistence.autonomy.pins import MAX_VERDICT_VALIDITY_H
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    WriteOutcome,
    open_root,
    read_once_at,
    walk_dirs,
    write_once,
)
from breezy.persistence.autonomy.wire import (
    WireRefusalReason,
    WireRefused,
    as_object,
    check_decimal,
    check_int,
    check_match,
    check_sha256,
    decimal_wire,
    optional_decimal_str,
    optional_int,
    optional_sha256,
    optional_str,
    parse_json_exact,
    require_decimal_str,
    require_enum,
    require_exact_keys,
    require_list,
    require_ns,
    require_object,
    require_sha256,
    require_str,
)

__all__ = [
    "MAX_VERDICT_BYTES",
    "ActionClass",
    "Assumption",
    "Verdict",
    "VerdictIdCollision",
    "VerdictInput",
    "VerdictKind",
    "VerdictOutcome",
    "VerdictRefusalReason",
    "VerdictRefused",
    "VerdictUnreadable",
    "read_verdict",
    "write_verdict",
]

VERDICT_SCHEMA: Final = "verdict/v1"
MAX_VERDICT_BYTES: Final = 65_536
VERDICT_FILE_MODE: Final = 0o600
_NS_PER_S: Final = 10**9
_NS_PER_H: Final = 3_600 * _NS_PER_S
_SECONDS_PER_DAY: Final = 86_400
_EPOCH: Final = date(1970, 1, 1)
_DETECTOR_RE: Final = re.compile(r"\A[a-z0-9_]+(?:[.:][a-z0-9_]+)*\Z", re.ASCII)
_NAME_RE: Final = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z", re.ASCII)
_ROLE_RE: Final = re.compile(r"\A[a-z0-9_]{1,64}\Z", re.ASCII)


class VerdictKind(StrEnum):
    OFFLINE_CHALLENGER = "OFFLINE_CHALLENGER"
    FORWARD_SHADOW = "FORWARD_SHADOW"
    LIVE_SEQUENTIAL = "LIVE_SEQUENTIAL"
    DRIFT = "DRIFT"
    HEALTH = "HEALTH"
    RECONCILIATION = "RECONCILIATION"


class VerdictOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNDERPOWERED = "UNDERPOWERED"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"


class ActionClass(StrEnum):
    NONE = "NONE"
    ALERT = "ALERT"
    SELF_HEAL = "SELF_HEAL"
    DEMOTE = "DEMOTE"
    HALT = "HALT"


class Assumption(StrEnum):
    SLIPPAGE_CHAMPION_PROXY = "slippage_champion_proxy"
    SLIPPAGE_FLOOR_AUD12A = "slippage_floor_aud12a"
    FILL_SURVIVORSHIP_UNMODELLED = "fill_survivorship_unmodelled"
    NO_POLICY_RULING = "no_policy_ruling"
    DRILL = "drill"


class VerdictRefusalReason(StrEnum):
    VALIDITY_ABOVE_CEILING = "validity_above_ceiling"


class VerdictRefused(Exception):
    """The writer refused a verdict that violates a store rule."""

    def __init__(self, reason: VerdictRefusalReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class VerdictIdCollision(Exception):
    """A different body (or unreadable bytes) already sits under this verdict id."""


class VerdictUnreadable(Exception):
    """A stored verdict cannot be read, parsed or trusted; ``reason`` is a closed code string."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VerdictInput:
    """One provenance input: a role name and the sha256 of the bytes read. Never a path."""

    path_role: str
    sha256: str

    def __post_init__(self) -> None:
        check_match(self.path_role, _ROLE_RE, "path_role")
        check_sha256(self.sha256, "sha256")

    def to_wire(self) -> dict[str, object]:
        return {"path_role": self.path_role, "sha256": self.sha256}

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=("path_role", "sha256"))
        return cls(path_role=require_str(obj, "path_role"), sha256=require_sha256(obj, "sha256"))


_KEYS: Final = (
    "schema", "verdict_id", "kind", "subject_family_id", "subject_artefact_sha256",
    "comparator_family_id", "outcome", "detector", "declared_action_class", "metrics", "n",
    "n_min", "power", "mde", "eta_to_verdict_days", "alpha_spent", "k_life", "alpha_k",
    "n_min_eff", "n_cap", "inputs", "policy_ruling_sha256", "family_prereg_sha256",
    "produced_at_ns", "valid_until_ns", "producer_code_sha", "assumptions",
)  # fmt: skip
_BODY_EXCLUDED: Final = frozenset({"verdict_id", "produced_at_ns"})
_DECIMAL_COLUMNS: Final = ("power", "mde", "eta_to_verdict_days", "alpha_spent", "alpha_k")
_INT_COLUMNS: Final = ("n", "n_min", "k_life", "n_min_eff", "n_cap")
#: Null on every kind but FORWARD_SHADOW (ARCH C4, ALPHA).
_FORWARD_SHADOW_ONLY: Final = ("k_life", "alpha_k", "n_min_eff", "n_cap")


def _bad(field: str) -> WireRefused:
    return WireRefused(WireRefusalReason.BAD_VALUE, field)


def _strictly_increasing(values: list[object], field: str) -> None:
    if any(a >= b for a, b in pairwise(values)):  # type: ignore[operator]
        raise _bad(field)  # unsorted or duplicated


@dataclass(frozen=True, kw_only=True)
class Verdict:
    """``verdict/v1`` (ARCH C4). ``inputs``, ``assumptions`` and ``metrics`` are held sorted."""

    kind: VerdictKind
    subject_family_id: str
    outcome: VerdictOutcome
    detector: str
    declared_action_class: ActionClass
    produced_at_ns: int
    valid_until_ns: int
    producer_code_sha: str
    metrics: tuple[tuple[str, Decimal], ...] = ()
    inputs: tuple[VerdictInput, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    subject_artefact_sha256: str | None = None
    comparator_family_id: str | None = None
    n: int | None = None
    n_min: int | None = None
    power: Decimal | None = None
    mde: Decimal | None = None
    eta_to_verdict_days: Decimal | None = None
    alpha_spent: Decimal | None = None
    k_life: int | None = None
    alpha_k: Decimal | None = None
    n_min_eff: int | None = None
    n_cap: int | None = None
    policy_ruling_sha256: str | None = None
    family_prereg_sha256: str | None = None

    def __post_init__(self) -> None:
        for field, enum in (
            ("kind", VerdictKind),
            ("outcome", VerdictOutcome),
            ("declared_action_class", ActionClass),
        ):
            if not isinstance(getattr(self, field), enum):
                raise WireRefused(WireRefusalReason.WRONG_TYPE, field)
        family_component(self.subject_family_id)
        if self.comparator_family_id is not None:
            family_component(self.comparator_family_id)
        check_match(self.detector, _DETECTOR_RE, "detector")
        check_sha256(self.producer_code_sha, "producer_code_sha")
        for field in ("subject_artefact_sha256", "policy_ruling_sha256", "family_prereg_sha256"):
            if getattr(self, field) is not None:
                check_sha256(getattr(self, field), field)
        for field in ("produced_at_ns", "valid_until_ns"):
            check_int(getattr(self, field), field)
        self._check_numbers()
        self._check_kind_rules()
        self._check_collections()

    def _check_numbers(self) -> None:
        for field in _INT_COLUMNS:
            if getattr(self, field) is not None:
                check_int(getattr(self, field), field)
        for field in _DECIMAL_COLUMNS:
            if getattr(self, field) is not None:
                check_decimal(getattr(self, field), field)

    def _check_kind_rules(self) -> None:
        if self.kind is not VerdictKind.FORWARD_SHADOW:
            for field in _FORWARD_SHADOW_ONLY:
                if getattr(self, field) is not None:
                    raise _bad(field)
        if self.kind is not VerdictKind.LIVE_SEQUENTIAL and self.family_prereg_sha256 is not None:
            raise _bad("family_prereg_sha256")
        if (
            self.policy_ruling_sha256 is None
            and Assumption.NO_POLICY_RULING not in self.assumptions
        ):
            raise _bad("policy_ruling_sha256")

    def _check_collections(self) -> None:
        for name, value in self.metrics:
            check_match(name, _NAME_RE, "metrics")
            check_decimal(value, "metrics")
        _strictly_increasing([name for name, _ in self.metrics], "metrics")
        for item in self.inputs:
            if not isinstance(item, VerdictInput):
                raise WireRefused(WireRefusalReason.WRONG_TYPE, "inputs")
        _strictly_increasing([item.path_role for item in self.inputs], "inputs")
        for assumption in self.assumptions:
            if not isinstance(assumption, Assumption):
                raise WireRefused(WireRefusalReason.WRONG_TYPE, "assumptions")
        _strictly_increasing([a.value for a in self.assumptions], "assumptions")

    def to_wire(self) -> dict[str, object]:
        """The full wire object, ``verdict_id`` included."""
        return {**self._body(), "verdict_id": self.verdict_id}

    def _body(self) -> dict[str, object]:
        return {
            "schema": VERDICT_SCHEMA,
            "kind": self.kind.value,
            "subject_family_id": self.subject_family_id,
            "subject_artefact_sha256": self.subject_artefact_sha256,
            "comparator_family_id": self.comparator_family_id,
            "outcome": self.outcome.value,
            "detector": self.detector,
            "declared_action_class": self.declared_action_class.value,
            "metrics": {name: decimal_wire(value) for name, value in self.metrics},
            "n": self.n,
            "n_min": self.n_min,
            "power": decimal_wire(self.power),
            "mde": decimal_wire(self.mde),
            "eta_to_verdict_days": decimal_wire(self.eta_to_verdict_days),
            "alpha_spent": decimal_wire(self.alpha_spent),
            "k_life": self.k_life,
            "alpha_k": decimal_wire(self.alpha_k),
            "n_min_eff": self.n_min_eff,
            "n_cap": self.n_cap,
            "inputs": [item.to_wire() for item in self.inputs],
            "policy_ruling_sha256": self.policy_ruling_sha256,
            "family_prereg_sha256": self.family_prereg_sha256,
            "produced_at_ns": self.produced_at_ns,
            "valid_until_ns": self.valid_until_ns,
            "producer_code_sha": self.producer_code_sha,
            "assumptions": [a.value for a in self.assumptions],
        }

    def body_wire(self) -> dict[str, object]:
        """The wire object without ``verdict_id`` and ``produced_at_ns`` (the hashed body)."""
        return {k: v for k, v in self._body().items() if k not in _BODY_EXCLUDED}

    @property
    def verdict_id(self) -> str:
        return sha256_hex(canonical_json(self.body_wire()))

    def valid_until_date(self) -> str:
        """The UTC calendar date of ``valid_until_ns`` (the store's directory)."""
        days = self.valid_until_ns // _NS_PER_S // _SECONDS_PER_DAY
        return (_EPOCH + timedelta(days=days)).isoformat()

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=_KEYS)
        require_enum(obj, "schema", allowed=(VERDICT_SCHEMA,))
        metrics_obj = require_object(obj, "metrics")
        verdict = cls(
            kind=VerdictKind(require_enum(obj, "kind", allowed=[k.value for k in VerdictKind])),
            subject_family_id=require_str(obj, "subject_family_id"),
            subject_artefact_sha256=optional_sha256(obj, "subject_artefact_sha256"),
            comparator_family_id=optional_str(obj, "comparator_family_id"),
            outcome=VerdictOutcome(
                require_enum(obj, "outcome", allowed=[o.value for o in VerdictOutcome])
            ),
            detector=require_str(obj, "detector"),
            declared_action_class=ActionClass(
                require_enum(obj, "declared_action_class", allowed=[a.value for a in ActionClass])
            ),
            metrics=tuple(
                sorted((name, require_decimal_str(metrics_obj, name)) for name in metrics_obj)
            ),
            n=optional_int(obj, "n"),
            n_min=optional_int(obj, "n_min"),
            power=optional_decimal_str(obj, "power"),
            mde=optional_decimal_str(obj, "mde"),
            eta_to_verdict_days=optional_decimal_str(obj, "eta_to_verdict_days"),
            alpha_spent=optional_decimal_str(obj, "alpha_spent"),
            k_life=optional_int(obj, "k_life"),
            alpha_k=optional_decimal_str(obj, "alpha_k"),
            n_min_eff=optional_int(obj, "n_min_eff"),
            n_cap=optional_int(obj, "n_cap"),
            inputs=tuple(
                VerdictInput.from_wire(as_object(item, "inputs"))
                for item in require_list(obj, "inputs")
            ),
            policy_ruling_sha256=optional_sha256(obj, "policy_ruling_sha256"),
            family_prereg_sha256=optional_sha256(obj, "family_prereg_sha256"),
            produced_at_ns=require_ns(obj, "produced_at_ns"),
            valid_until_ns=require_ns(obj, "valid_until_ns"),
            producer_code_sha=require_sha256(obj, "producer_code_sha"),
            assumptions=_assumptions_from_wire(obj),
        )
        if require_sha256(obj, "verdict_id") != verdict.verdict_id:
            raise _bad("verdict_id")
        return verdict


def _assumptions_from_wire(obj: Mapping[str, object]) -> tuple[Assumption, ...]:
    out: list[Assumption] = []
    for item in require_list(obj, "assumptions"):
        if not isinstance(item, str):
            raise WireRefused(WireRefusalReason.WRONG_TYPE, "assumptions")
        try:
            out.append(Assumption(item))
        except ValueError:
            raise _bad("assumptions") from None
    return tuple(out)


def _same_body_modulo_produced_at(existing: Verdict, incoming: Verdict) -> bool:
    return existing.body_wire() == incoming.body_wire()


def _read_stored(paths: AutonomyPaths | ShadowPaths, family_id: str, day: str, vid: str) -> bytes:
    path = paths.verdict_file(family_id, day, vid)
    rootfd = open_root(paths.root)
    try:
        dirfd = walk_dirs(rootfd, path.parent.relative_to(paths.root).parts, create=False)
        try:
            return read_once_at(
                dirfd, path.name, max_bytes=MAX_VERDICT_BYTES, policy=ReadPolicy.STRICT
            )
        finally:
            os.close(dirfd)
    finally:
        os.close(rootfd)


def _ensure_dirs(paths: AutonomyPaths | ShadowPaths, parent_rel: tuple[str, ...]) -> None:
    rootfd = open_root(paths.root)
    try:
        os.close(walk_dirs(rootfd, parent_rel, create=True))
    finally:
        os.close(rootfd)


def write_verdict(paths: AutonomyPaths | ShadowPaths, verdict: Verdict) -> WriteOutcome:
    """Write ``verdict`` once under ``derived/verdicts/<family>/<UTC valid_until date>/<id>.json``.

    ``WRITTEN`` for a new file; ``EXISTS_EQUAL`` when the stored body equals this one except for
    ``produced_at_ns`` (the first writer's bytes stay). ``VerdictRefused`` above the validity
    ceiling; ``VerdictIdCollision`` for any other occupant of the id.
    """
    if verdict.valid_until_ns - verdict.produced_at_ns > MAX_VERDICT_VALIDITY_H * _NS_PER_H:
        raise VerdictRefused(VerdictRefusalReason.VALIDITY_ABOVE_CEILING)
    day = verdict.valid_until_date()
    path = paths.verdict_file(verdict.subject_family_id, day, verdict.verdict_id)
    _ensure_dirs(paths, path.parent.relative_to(paths.root).parts)
    try:
        return write_once(
            path, canonical_json(verdict.to_wire()), root=paths.root, mode=VERDICT_FILE_MODE
        )
    except SingleReadRefused as exc:
        if exc.reason is not SingleReadReason.EXISTS_DIFFERENT:
            raise
    try:
        existing = _parse(_read_stored(paths, verdict.subject_family_id, day, verdict.verdict_id))
    except (SingleReadRefused, WireRefused) as exc:
        raise VerdictIdCollision("unreadable occupant") from exc
    if not _same_body_modulo_produced_at(existing, verdict):
        raise VerdictIdCollision("different body under this id")
    return WriteOutcome.EXISTS_EQUAL


def _parse(raw: bytes) -> Verdict:
    return Verdict.from_wire(parse_json_exact(raw))


def read_verdict(
    paths: AutonomyPaths | ShadowPaths, family_id: str, day: str, verdict_id: str
) -> Verdict:
    """Read one stored verdict; ``VerdictUnreadable`` unless it parses and matches its address."""
    try:
        verdict = _parse(_read_stored(paths, family_id, day, verdict_id))
    except SingleReadRefused as exc:
        raise VerdictUnreadable(exc.reason.value) from exc
    except WireRefused as exc:
        raise VerdictUnreadable(exc.reason.value) from exc
    if verdict.verdict_id != verdict_id or verdict.subject_family_id != family_id:
        raise VerdictUnreadable("address_mismatch")
    if verdict.valid_until_date() != day:
        raise VerdictUnreadable("address_mismatch")
    return verdict
