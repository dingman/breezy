"""The sealed FQ evidence loader (FQ-R37, FQ-R54 M2; F7b-core).

``load_evidence_rows(store_kind)`` is the only constructor of :class:`EvidenceRow` and
:class:`LoadedEvidence`. It takes ONLY the store kind: the closed ``_READERS`` mapping resolves the
reader for that kind, and each reader finds its own data root when its owner WP wires it
(F7B-R8). In F7b-core every reader refuses with a named reason because no backing store has an
owner WP merged. The loader reads ``_READERS`` by module-global name at call time, so a test patch
is seen (F7B-R28).

The store kind fixes the evidence class (``live``, ``shadow`` or ``backtest``); a row carrying a
different or missing tag is refused. ``ref_ts < take_ts`` is enforced at load. Numeric fields are
``Decimal`` at the seal; the float conversion happens once, later, when a take becomes a
``TakeInput``.

HONESTY (F7B-R9, FQ-R54 M2): the module-private ``_TOKEN`` and the AST bans (no
``object.__new__`` of these types, no ``object.__setattr__`` on a foreign object, no
``pickle.load``/``loads``/``Unpickler`` and no non-refusing ``__setstate__`` under
``analysis/autonomy``) are an ACCIDENT GUARD, not a security boundary. ``_TOKEN`` is importable and
in-process code that wants to forge a row can (``gc``, ``ctypes``, module globals). The guard makes
forgery impossible to do by accident and visible in review. Real provenance comes from the
store-kind-derived reader, ``ref_ts < take_ts`` at load and the reviewed consumer table.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import InitVar, dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, NoReturn, final

__all__ = [
    "STORE_CLASS",
    "EvidenceClass",
    "EvidenceRefused",
    "EvidenceRow",
    "EvidenceUnavailable",
    "LoadedEvidence",
    "RawEvidence",
    "StoreKind",
    "is_sealed_row",
    "load_evidence_rows",
    "require_loaded_evidence",
]


class StoreKind(StrEnum):
    C2_LABEL_STORE = "c2_label_store"
    NODE_C1_SHADOW_TAKES = "node_c1_shadow_takes"
    HARNESS = "harness"
    FS_REPLAY = "fs_replay"


class EvidenceClass(StrEnum):
    LIVE = "live"
    SHADOW = "shadow"
    BACKTEST = "backtest"


#: The closed store-kind -> evidence-class mapping (the path is derived from the kind, never given).
STORE_CLASS: Final[Mapping[StoreKind, EvidenceClass]] = MappingProxyType(
    {
        StoreKind.C2_LABEL_STORE: EvidenceClass.LIVE,
        StoreKind.NODE_C1_SHADOW_TAKES: EvidenceClass.SHADOW,
        StoreKind.HARNESS: EvidenceClass.BACKTEST,
        StoreKind.FS_REPLAY: EvidenceClass.BACKTEST,
    }
)


class EvidenceRefused(ValueError):
    """A row or a reader output failed validation; ``reason`` is the named cause."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class EvidenceUnavailable(RuntimeError):
    """No reader is wired for the store kind yet; ``reason`` names the missing owner."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RawEvidence:
    """What a reader returns: plain rows (mappings) and the settled-coverage marker days."""

    rows: tuple[Mapping[str, object], ...]
    covered_days: tuple[str, ...]


_TOKEN: Final = object()


def _forbid(what: str) -> NoReturn:
    raise TypeError(f"{what} is refused: evidence is built only by load_evidence_rows")


@final
@dataclass(frozen=True)
class EvidenceRow:
    """One sealed take. Built only by the loader; every copy and pickle route refuses."""

    evidence_class: EvidenceClass
    climate_day: dt.date
    decision_ts_ns: int
    ref_ts_ns: int
    station: str
    rung_id: str
    side: str
    be: Decimal
    raw_ask: Decimal
    p_model: Decimal
    h: int | None
    void: bool
    token: InitVar[object]
    _seal: object = field(init=False, repr=False, compare=False, default_factory=lambda: _TOKEN)

    def __post_init__(self, token: object) -> None:
        if token is not _TOKEN:
            raise TypeError("EvidenceRow is built only by load_evidence_rows")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("EvidenceRow is final")

    def __copy__(self) -> NoReturn:
        _forbid("copy")

    def __deepcopy__(self, memo: object) -> NoReturn:
        _forbid("deepcopy")

    def __reduce__(self) -> NoReturn:
        _forbid("pickle")

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        _forbid("pickle")

    def __setstate__(self, state: object) -> NoReturn:
        raise TypeError("EvidenceRow state is never restored")


@final
@dataclass(frozen=True)
class LoadedEvidence:
    """The sealed container consumers accept: rows, the store kind and the covered days."""

    store_kind: StoreKind
    rows: tuple[EvidenceRow, ...]
    covered_days: frozenset[dt.date]
    token: InitVar[object]
    _seal: object = field(init=False, repr=False, compare=False, default_factory=lambda: _TOKEN)

    def __post_init__(self, token: object) -> None:
        if token is not _TOKEN:
            raise TypeError("LoadedEvidence is built only by load_evidence_rows")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("LoadedEvidence is final")

    @property
    def evidence_class(self) -> EvidenceClass:
        return STORE_CLASS[self.store_kind]

    def __copy__(self) -> NoReturn:
        _forbid("copy")

    def __deepcopy__(self, memo: object) -> NoReturn:
        _forbid("deepcopy")

    def __reduce__(self) -> NoReturn:
        _forbid("pickle")

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        _forbid("pickle")

    def __setstate__(self, state: object) -> NoReturn:
        raise TypeError("LoadedEvidence state is never restored")


def is_sealed_row(row: object) -> bool:
    """Exact type AND the seal an ``object.__new__`` forgery lacks (never ``isinstance``)."""
    return type(row) is EvidenceRow and row.__dict__.get("_seal") is _TOKEN


def require_loaded_evidence(candidate: object) -> LoadedEvidence:
    """Every consumer's entry check: exact ``LoadedEvidence``, sealed, of sealed rows."""
    if (
        type(candidate) is not LoadedEvidence
        or candidate.__dict__.get("_seal") is not _TOKEN
        or type(candidate.__dict__.get("rows")) is not tuple
        or not all(is_sealed_row(r) for r in candidate.rows)
    ):
        raise EvidenceRefused("evidence_not_loaded")
    return candidate


# ------------------------------------------------------------------ readers


def _unwired(reason: str) -> Callable[[], RawEvidence]:
    def reader() -> RawEvidence:
        raise EvidenceUnavailable(reason)

    return reader


#: Each reader is wired by its owner WP (the label store reader, the node C1 shadow-take reader,
#: the harness and the FS replay). F7b-core wires none: every path refuses with a named reason.
_READERS: Final[Mapping[StoreKind, Callable[[], RawEvidence]]] = MappingProxyType(
    {
        StoreKind.C2_LABEL_STORE: _unwired("c2_label_reader_not_wired"),
        StoreKind.NODE_C1_SHADOW_TAKES: _unwired("shadow_take_reader_not_wired"),
        StoreKind.HARNESS: _unwired("harness_reader_not_wired"),
        StoreKind.FS_REPLAY: _unwired("fs_replay_reader_not_wired"),
    }
)

_ROW_KEYS: Final = frozenset(
    {
        "evidence_tag",
        "climate_day",
        "decision_ts_ns",
        "ref_ts_ns",
        "station",
        "rung_id",
        "side",
        "be",
        "raw_ask",
        "p_model",
        "h",
        "void",
    }
)
_ONE: Final = Decimal(1)


def _int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceRefused("wrong_type", name)
    return value


def _key(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise EvidenceRefused("wrong_type", name)
    if not value or not value.isascii():
        raise EvidenceRefused("bad_key", name)
    return value


def _date(value: object, name: str) -> dt.date:
    if isinstance(value, dt.datetime) or not isinstance(value, str | dt.date):
        raise EvidenceRefused("wrong_type", name)
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceRefused("bad_date", name) from exc


def _decimal(value: object, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal | str | int):
        raise EvidenceRefused("wrong_type", name)  # a float is refused: Decimal at the seal
    try:
        number = value if isinstance(value, Decimal) else Decimal(value)
    except InvalidOperation as exc:
        raise EvidenceRefused("bad_number", name) from exc
    if not number.is_finite():
        raise EvidenceRefused("bad_number", name)
    if (number <= 0) if positive else not (0 <= number <= _ONE):
        raise EvidenceRefused("bad_number", name)
    return number


def _seal_row(raw: object, cls: EvidenceClass) -> EvidenceRow:
    if not isinstance(raw, Mapping):
        raise EvidenceRefused("wrong_type", "row")
    keys = set(raw)
    if "evidence_tag" not in keys or raw["evidence_tag"] is None:
        raise EvidenceRefused("untagged_row")
    if extra := keys - _ROW_KEYS:
        raise EvidenceRefused("unexpected_key", ",".join(sorted(map(str, extra))))
    if missing := _ROW_KEYS - keys:
        raise EvidenceRefused("missing_key", ",".join(sorted(missing)))
    try:
        tag = EvidenceClass(raw["evidence_tag"])
    except ValueError as exc:
        raise EvidenceRefused("unknown_tag", repr(raw["evidence_tag"])) from exc
    if tag is not cls:
        raise EvidenceRefused("tag_mismatch", f"{tag.value} in a {cls.value} store")
    h = raw["h"]
    if h is not None and not (type(h) is int and h in (0, 1)):  # exact int: no bool/float/Decimal
        raise EvidenceRefused("bad_outcome", repr(h))
    void = raw["void"]
    if not isinstance(void, bool):
        raise EvidenceRefused("wrong_type", "void")
    if void and h is not None:
        raise EvidenceRefused("void_with_outcome")
    decision_ts, ref_ts = (
        _int(raw["decision_ts_ns"], "decision_ts_ns"),
        _int(raw["ref_ts_ns"], "ref_ts_ns"),
    )
    if not ref_ts < decision_ts:
        raise EvidenceRefused("ref_ts_not_before_take_ts", f"{ref_ts} >= {decision_ts}")
    return EvidenceRow(
        evidence_class=tag,
        climate_day=_date(raw["climate_day"], "climate_day"),
        decision_ts_ns=decision_ts,
        ref_ts_ns=ref_ts,
        station=_key(raw["station"], "station"),
        rung_id=_key(raw["rung_id"], "rung_id"),
        side=_key(raw["side"], "side"),
        be=_decimal(raw["be"], "be", positive=True),
        raw_ask=_decimal(raw["raw_ask"], "raw_ask"),
        p_model=_decimal(raw["p_model"], "p_model"),
        h=h,
        void=void,
        token=_TOKEN,
    )


def _covered(days: Iterable[object]) -> frozenset[dt.date]:
    return frozenset(_date(d, "covered_day") for d in days)


def load_evidence_rows(store_kind: StoreKind | str) -> LoadedEvidence:
    """The only constructor: resolve the reader for ``store_kind``, validate, seal."""
    try:
        kind = StoreKind(store_kind)
    except ValueError as exc:
        raise EvidenceRefused("unknown_store_kind", repr(store_kind)) from exc
    reader = _READERS.get(kind)
    if reader is None:
        raise EvidenceUnavailable("no_reader_for_store_kind")
    raw = reader()
    if not isinstance(raw, RawEvidence):
        raise EvidenceRefused("reader_output", type(raw).__name__)
    cls = STORE_CLASS[kind]
    rows = tuple(_seal_row(r, cls) for r in raw.rows)
    return LoadedEvidence(
        store_kind=kind, rows=rows, covered_days=_covered(raw.covered_days), token=_TOKEN
    )
