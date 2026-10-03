"""C3 artefact-lineage records: ``lineage/v1``, ``root/v1`` and ``refit_run/v1`` (ARCH-0 AC 24).

Each record is a frozen dataclass with an explicit ``to_wire`` and ``from_wire`` (never
``dataclasses.asdict``). Construction validates, so a record that exists is well-formed, and
``from_wire`` parses through the exact-parse validators in ``wire`` (no float, no unknown or missing
key). Decimals are canonical strings. A refusal raises ``WireRefused`` naming the field only.

Instants (``*_utc``) are ``YYYY-MM-DDTHH:MM:SSZ``; this fixed format makes lexical order equal
chronological order.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Self

from breezy.persistence.autonomy.canonical import CanonicalTypeError, canonical_json
from breezy.persistence.autonomy.paths import (
    family_component,
    model_class_component,
)
from breezy.persistence.autonomy.pins import ROOT_ARTEFACT_COMPONENT
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
    require_bool,
    require_decimal_str,
    require_enum,
    require_exact_keys,
    require_int,
    require_list,
    require_ns,
    require_object,
    require_sha256,
    require_str,
)

__all__ = [
    "REQUIRED_LEAKAGE_ASSERTIONS",
    "DataWindow",
    "LeakageAssertion",
    "Lineage",
    "RefitOutcome",
    "RefitRun",
    "RootRecord",
    "model_class_of",
    "root_model_class",
]

LINEAGE_SCHEMA: Final = "lineage/v1"
ROOT_SCHEMA: Final = "root/v1"
REFIT_RUN_SCHEMA: Final = "refit_run/v1"
FIT_STATUS_OK: Final = "OK"
NO_CHANGE_REASONS: Final = frozenset({"below_delta", "existing_sha"})
#: ARCH C3 ``leakage_assertions``: these three are always present and always passed.
REQUIRED_LEAKAGE_ASSERTIONS: Final = (
    "no_sealed_holdout_rows_in_train",
    "ref_ts_lt_take_ts",
    "train_end_lt_forward_eval_start",
)

_UTC_RE: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z", re.ASCII)
_GIT_SHA_RE: Final = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z", re.ASCII)
_NAME_RE: Final = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z", re.ASCII)
_REASON_RE: Final = re.compile(r"\A[a-z0-9_]{1,64}(?::[0-9a-f]{64})?\Z", re.ASCII)
_RUN_ID_RE: Final = re.compile(r"\A[A-Za-z0-9_.:-]{1,128}\Z", re.ASCII)
_SOURCE_RE: Final = re.compile(r"\A[a-z0-9_.:-]{1,64}\Z", re.ASCII)
_NS_PER_S: Final = 10**9


def _bad(field: str) -> WireRefused:
    return WireRefused(WireRefusalReason.BAD_VALUE, field)


def _utc(value: object, field: str) -> str:
    text = check_match(value, _UTC_RE, field)
    try:
        datetime.fromisoformat(text)
    except ValueError:
        raise _bad(field) from None
    return text


def _instant_to_ns(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp()) * _NS_PER_S


def _optional_sha(value: object, field: str) -> str | None:
    return None if value is None else check_sha256(value, field)


def model_class_of(composition_kind: str, component: str) -> str:
    """``"<composition_kind>:<component>"``, validated as a model class (path-safe)."""
    return model_class_component(f"{composition_kind}:{component}")


def root_model_class(composition_kind: str) -> str:
    """A root copy's model class (E-14 rule 2): ``"<kind>:density_table"``."""
    return model_class_of(composition_kind, ROOT_ARTEFACT_COMPONENT)


@dataclass(frozen=True)
class DataWindow:
    """One refit input window: source, [start, end), row count and content hash."""

    source: str
    start_utc: str
    end_exclusive_utc: str
    rows: int
    content_sha256: str

    def __post_init__(self) -> None:
        check_match(self.source, _SOURCE_RE, "source")
        if _utc(self.start_utc, "start_utc") >= _utc(self.end_exclusive_utc, "end_exclusive_utc"):
            raise _bad("end_exclusive_utc")
        check_int(self.rows, "rows")
        check_sha256(self.content_sha256, "content_sha256")

    def to_wire(self) -> dict[str, object]:
        return {
            "source": self.source,
            "start_utc": self.start_utc,
            "end_exclusive_utc": self.end_exclusive_utc,
            "rows": self.rows,
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(
            obj,
            required=("source", "start_utc", "end_exclusive_utc", "rows", "content_sha256"),
        )
        return cls(
            source=require_str(obj, "source"),
            start_utc=require_str(obj, "start_utc"),
            end_exclusive_utc=require_str(obj, "end_exclusive_utc"),
            rows=require_int(obj, "rows"),
            content_sha256=require_sha256(obj, "content_sha256"),
        )


def _windows_from_wire(obj: Mapping[str, object]) -> tuple[DataWindow, ...]:
    return tuple(
        DataWindow.from_wire(as_object(item, "data_windows"))
        for item in require_list(obj, "data_windows")
    )


def _check_windows(windows: object) -> tuple[DataWindow, ...]:
    if not isinstance(windows, tuple) or not all(isinstance(w, DataWindow) for w in windows):
        raise WireRefused(WireRefusalReason.WRONG_TYPE, "data_windows")
    return windows


@dataclass(frozen=True)
class LeakageAssertion:
    """One named leakage check and whether it held."""

    name: str
    passed: bool

    def __post_init__(self) -> None:
        check_match(self.name, _NAME_RE, "leakage_assertions")
        if not isinstance(self.passed, bool):
            raise WireRefused(WireRefusalReason.WRONG_TYPE, "passed")

    def to_wire(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed}

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=("name", "passed"))
        return cls(name=require_str(obj, "name"), passed=require_bool(obj, "passed"))


def _check_leakage(assertions: object) -> tuple[LeakageAssertion, ...]:
    if not isinstance(assertions, tuple) or not all(
        isinstance(a, LeakageAssertion) for a in assertions
    ):
        raise WireRefused(WireRefusalReason.WRONG_TYPE, "leakage_assertions")
    names = [a.name for a in assertions]
    if len(set(names)) != len(names) or not set(REQUIRED_LEAKAGE_ASSERTIONS) <= set(names):
        raise _bad("leakage_assertions")
    if not all(a.passed for a in assertions):
        raise _bad("leakage_assertions")  # a lineage with a failed assertion is never built
    return assertions


def _freeze(value: object) -> object:
    """A detached, immutable copy: mappings become read-only proxies, lists become tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


def _frozen_params(params: object) -> Mapping[str, Any]:
    if not isinstance(params, Mapping):
        raise WireRefused(WireRefusalReason.WRONG_TYPE, "params")
    try:
        canonical_json(_thaw(params))
    except CanonicalTypeError:
        raise _bad("params") from None
    frozen = _freeze(params)
    assert isinstance(frozen, Mapping)
    return frozen


_LINEAGE_KEYS: Final = (
    "schema", "artefact_sha256", "model_class", "lineage_root_family_id", "parent_artefact_sha256",
    "code_git_sha", "build_sha", "producer_code_sha", "params", "seed", "fit_status",
    "data_windows", "own_outcome_label_set_sha256", "ablation_artefact_sha256",
    "own_outcome_max_abs_delta_p", "own_outcome_gate_decisions_changed",
    "train_end_exclusive_utc", "forward_eval_start_utc", "leakage_assertions", "recalibration",
    "correction_form", "created_at_ns", "runtime_s", "peak_rss_bytes",
)  # fmt: skip


@dataclass(frozen=True, kw_only=True)
class Lineage:
    """``lineage/v1`` (ARCH C3): how one content-addressed artefact was produced."""

    artefact_sha256: str
    model_class: str
    lineage_root_family_id: str
    parent_artefact_sha256: str | None
    code_git_sha: str
    build_sha: str
    producer_code_sha: str
    params: Mapping[str, Any]
    seed: int
    data_windows: tuple[DataWindow, ...]
    train_end_exclusive_utc: str
    forward_eval_start_utc: str
    leakage_assertions: tuple[LeakageAssertion, ...]
    created_at_ns: int
    runtime_s: Decimal
    peak_rss_bytes: int
    own_outcome_label_set_sha256: str | None = None
    ablation_artefact_sha256: str | None = None
    own_outcome_max_abs_delta_p: Decimal | None = None
    own_outcome_gate_decisions_changed: int | None = None
    recalibration: str | None = None
    correction_form: str | None = None

    def __post_init__(self) -> None:
        check_sha256(self.artefact_sha256, "artefact_sha256")
        model_class_component(self.model_class)
        family_component(self.lineage_root_family_id)
        _optional_sha(self.parent_artefact_sha256, "parent_artefact_sha256")
        check_match(self.code_git_sha, _GIT_SHA_RE, "code_git_sha")
        check_match(self.build_sha, _GIT_SHA_RE, "build_sha")
        check_sha256(self.producer_code_sha, "producer_code_sha")
        object.__setattr__(self, "params", _frozen_params(self.params))  # frozen on construction
        check_int(self.seed, "seed", minimum=-(2**63))
        if not _check_windows(self.data_windows):
            raise _bad("data_windows")
        self._check_own_outcome()
        _utc(self.train_end_exclusive_utc, "train_end_exclusive_utc")
        forward = _utc(self.forward_eval_start_utc, "forward_eval_start_utc")
        if self.train_end_exclusive_utc > forward:
            raise _bad("train_end_exclusive_utc")
        created = check_int(self.created_at_ns, "created_at_ns")
        if _instant_to_ns(forward) < created:
            raise _bad("forward_eval_start_utc")
        _check_leakage(self.leakage_assertions)
        for field in ("recalibration", "correction_form"):
            value = getattr(self, field)
            if value is not None:
                check_match(value, _NAME_RE, field)
        if check_decimal(self.runtime_s, "runtime_s") < 0:
            raise _bad("runtime_s")
        check_int(self.peak_rss_bytes, "peak_rss_bytes")

    def _check_own_outcome(self) -> None:
        ablation = _optional_sha(self.ablation_artefact_sha256, "ablation_artefact_sha256")
        label_set = _optional_sha(self.own_outcome_label_set_sha256, "own_outcome_label_set_sha256")
        if self.own_outcome_max_abs_delta_p is not None:
            check_decimal(self.own_outcome_max_abs_delta_p, "own_outcome_max_abs_delta_p")
        if self.own_outcome_gate_decisions_changed is not None:
            check_int(self.own_outcome_gate_decisions_changed, "own_outcome_gate_decisions_changed")
        if label_set is None:
            if (
                ablation is not None
                or self.own_outcome_max_abs_delta_p is not None
                or self.own_outcome_gate_decisions_changed is not None
            ):
                raise _bad("own_outcome_label_set_sha256")
        elif ablation is None or ablation == self.artefact_sha256:
            raise _bad("ablation_artefact_sha256")
        elif self.own_outcome_gate_decisions_changed is None:
            raise _bad("own_outcome_gate_decisions_changed")  # null exactly with the label set

    def to_wire(self) -> dict[str, object]:
        return {
            "schema": LINEAGE_SCHEMA,
            "artefact_sha256": self.artefact_sha256,
            "model_class": self.model_class,
            "lineage_root_family_id": self.lineage_root_family_id,
            "parent_artefact_sha256": self.parent_artefact_sha256,
            "code_git_sha": self.code_git_sha,
            "build_sha": self.build_sha,
            "producer_code_sha": self.producer_code_sha,
            "params": _thaw(self.params),
            "seed": self.seed,
            "fit_status": FIT_STATUS_OK,
            "data_windows": [w.to_wire() for w in self.data_windows],
            "own_outcome_label_set_sha256": self.own_outcome_label_set_sha256,
            "ablation_artefact_sha256": self.ablation_artefact_sha256,
            "own_outcome_max_abs_delta_p": decimal_wire(self.own_outcome_max_abs_delta_p),
            "own_outcome_gate_decisions_changed": self.own_outcome_gate_decisions_changed,
            "train_end_exclusive_utc": self.train_end_exclusive_utc,
            "forward_eval_start_utc": self.forward_eval_start_utc,
            "leakage_assertions": [a.to_wire() for a in self.leakage_assertions],
            "recalibration": self.recalibration,
            "correction_form": self.correction_form,
            "created_at_ns": self.created_at_ns,
            "runtime_s": decimal_wire(self.runtime_s),
            "peak_rss_bytes": self.peak_rss_bytes,
        }

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=_LINEAGE_KEYS)
        require_enum(obj, "schema", allowed=(LINEAGE_SCHEMA,))
        require_enum(obj, "fit_status", allowed=(FIT_STATUS_OK,))
        return cls(
            artefact_sha256=require_sha256(obj, "artefact_sha256"),
            model_class=require_str(obj, "model_class"),
            lineage_root_family_id=require_str(obj, "lineage_root_family_id"),
            parent_artefact_sha256=optional_sha256(obj, "parent_artefact_sha256"),
            code_git_sha=require_str(obj, "code_git_sha"),
            build_sha=require_str(obj, "build_sha"),
            producer_code_sha=require_sha256(obj, "producer_code_sha"),
            params=require_object(obj, "params"),
            seed=require_int(obj, "seed"),
            data_windows=_windows_from_wire(obj),
            own_outcome_label_set_sha256=optional_sha256(obj, "own_outcome_label_set_sha256"),
            ablation_artefact_sha256=optional_sha256(obj, "ablation_artefact_sha256"),
            own_outcome_max_abs_delta_p=optional_decimal_str(obj, "own_outcome_max_abs_delta_p"),
            own_outcome_gate_decisions_changed=optional_int(
                obj, "own_outcome_gate_decisions_changed"
            ),
            train_end_exclusive_utc=require_str(obj, "train_end_exclusive_utc"),
            forward_eval_start_utc=require_str(obj, "forward_eval_start_utc"),
            leakage_assertions=tuple(
                LeakageAssertion.from_wire(as_object(item, "leakage_assertions"))
                for item in require_list(obj, "leakage_assertions")
            ),
            recalibration=optional_str(obj, "recalibration"),
            correction_form=optional_str(obj, "correction_form"),
            created_at_ns=require_ns(obj, "created_at_ns"),
            runtime_s=require_decimal_str(obj, "runtime_s"),
            peak_rss_bytes=require_int(obj, "peak_rss_bytes"),
        )


@dataclass(frozen=True)
class RootRecord:
    """``root/v1`` (E-14): binds a committed root manifest to its content-addressed artefact."""

    family_id: str
    manifest_sha256: str
    artefact_sha256: str
    committed_path: str

    def __post_init__(self) -> None:
        family_component(self.family_id)
        check_sha256(self.manifest_sha256, "manifest_sha256")
        check_sha256(self.artefact_sha256, "artefact_sha256")
        if self.committed_path != f"deploy/families/{self.family_id}.json":
            raise _bad("committed_path")

    def to_wire(self) -> dict[str, object]:
        return {
            "schema": ROOT_SCHEMA,
            "family_id": self.family_id,
            "manifest_sha256": self.manifest_sha256,
            "artefact_sha256": self.artefact_sha256,
            "committed_path": self.committed_path,
        }

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(
            obj,
            required=(
                "schema",
                "family_id",
                "manifest_sha256",
                "artefact_sha256",
                "committed_path",
            ),
        )
        require_enum(obj, "schema", allowed=(ROOT_SCHEMA,))
        return cls(
            family_id=require_str(obj, "family_id"),
            manifest_sha256=require_sha256(obj, "manifest_sha256"),
            artefact_sha256=require_sha256(obj, "artefact_sha256"),
            committed_path=require_str(obj, "committed_path"),
        )


class RefitOutcome(StrEnum):
    """``refit_run/v1`` outcomes. ``NO_CHANGE`` and ``NOT_FITTABLE`` carry a separate reason."""

    MINTED = "MINTED"
    NO_CHANGE = "NO_CHANGE"
    NOT_FITTABLE = "NOT_FITTABLE"
    REFUSED = "REFUSED"
    MINT_REFUSED_CEILING = "MINT_REFUSED_CEILING"
    ERROR = "ERROR"


_REFIT_KEYS: Final = (
    "schema", "run_id", "lineage_root_family_id", "model_class", "outcome", "reason",
    "artefact_sha256", "own_outcome_gate_decisions_changed", "data_windows",
    "own_outcome_label_set_sha256", "runtime_s", "peak_rss_bytes", "producer_code_sha",
)  # fmt: skip


@dataclass(frozen=True, kw_only=True)
class RefitRun:
    """``refit_run/v1`` (ARCH C3, P3-6): one write-once record per refit run."""

    run_id: str
    lineage_root_family_id: str
    model_class: str
    outcome: RefitOutcome
    data_windows: tuple[DataWindow, ...]
    runtime_s: Decimal
    peak_rss_bytes: int
    producer_code_sha: str
    reason: str | None = None
    artefact_sha256: str | None = None
    own_outcome_gate_decisions_changed: int | None = None
    own_outcome_label_set_sha256: str | None = None

    def __post_init__(self) -> None:
        check_match(self.run_id, _RUN_ID_RE, "run_id")
        family_component(self.lineage_root_family_id)
        model_class_component(self.model_class)
        if not isinstance(self.outcome, RefitOutcome):
            raise WireRefused(WireRefusalReason.WRONG_TYPE, "outcome")
        self._check_outcome()
        _check_windows(self.data_windows)
        if check_decimal(self.runtime_s, "runtime_s") < 0:
            raise _bad("runtime_s")
        check_int(self.peak_rss_bytes, "peak_rss_bytes")
        check_sha256(self.producer_code_sha, "producer_code_sha")
        if self.own_outcome_gate_decisions_changed is not None:
            check_int(self.own_outcome_gate_decisions_changed, "own_outcome_gate_decisions_changed")
        _optional_sha(self.own_outcome_label_set_sha256, "own_outcome_label_set_sha256")

    def _check_outcome(self) -> None:
        minted = self.outcome is RefitOutcome.MINTED
        if minted != (self.artefact_sha256 is not None):
            raise _bad("artefact_sha256")  # non-null exactly when MINTED
        if self.artefact_sha256 is not None:
            check_sha256(self.artefact_sha256, "artefact_sha256")
        if self.reason is not None:
            check_match(self.reason, _REASON_RE, "reason")
        if self.outcome is RefitOutcome.NO_CHANGE and self.reason not in NO_CHANGE_REASONS:
            raise _bad("reason")  # there is no NO_CHANGE(k_max_reached)
        if self.outcome is RefitOutcome.NOT_FITTABLE and self.reason is None:
            raise _bad("reason")

    def to_wire(self) -> dict[str, object]:
        return {
            "schema": REFIT_RUN_SCHEMA,
            "run_id": self.run_id,
            "lineage_root_family_id": self.lineage_root_family_id,
            "model_class": self.model_class,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "artefact_sha256": self.artefact_sha256,
            "own_outcome_gate_decisions_changed": self.own_outcome_gate_decisions_changed,
            "data_windows": [w.to_wire() for w in self.data_windows],
            "own_outcome_label_set_sha256": self.own_outcome_label_set_sha256,
            "runtime_s": decimal_wire(self.runtime_s),
            "peak_rss_bytes": self.peak_rss_bytes,
            "producer_code_sha": self.producer_code_sha,
        }

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=_REFIT_KEYS)
        require_enum(obj, "schema", allowed=(REFIT_RUN_SCHEMA,))
        outcome = RefitOutcome(
            require_enum(obj, "outcome", allowed=[o.value for o in RefitOutcome])
        )
        return cls(
            run_id=require_str(obj, "run_id"),
            lineage_root_family_id=require_str(obj, "lineage_root_family_id"),
            model_class=require_str(obj, "model_class"),
            outcome=outcome,
            reason=optional_str(obj, "reason"),
            artefact_sha256=optional_sha256(obj, "artefact_sha256"),
            own_outcome_gate_decisions_changed=optional_int(
                obj, "own_outcome_gate_decisions_changed"
            ),
            data_windows=_windows_from_wire(obj),
            own_outcome_label_set_sha256=optional_sha256(obj, "own_outcome_label_set_sha256"),
            runtime_s=require_decimal_str(obj, "runtime_s"),
            peak_rss_bytes=require_int(obj, "peak_rss_bytes"),
            producer_code_sha=require_sha256(obj, "producer_code_sha"),
        )
