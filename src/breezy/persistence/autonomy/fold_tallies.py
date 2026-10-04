"""The counters of the registry fold (ARCH-0 seam A 7b; ARCH C5 ``lineage_counters``, Z3, Z10).

``fold`` charges a ``TallyBook`` as each row takes effect and freezes it into one
``LineageTallies`` per lineage root and one ``VenueTallies``. This module is split out of ``fold``
so that the fold stays under its size cap; it holds no chain logic of its own: which row charges
which counter is ``fold``'s (see its docstring).

``holdout_opens`` has no row source: it belongs to the AUT-5 WP4 cache and is not a field here.

Windowed counters are sorted tuples of effective instants in ns (A7b-R1, erratum E-21): a budget is
the length of its in-window slice, which ``validate`` (7c, 7d) evaluates. Lifetime quantities stay
scalars: ``nominations``, ``infeasible_nominations``, ``alpha_spent`` and ``terminal_frozen``.

``carried_counters`` (the ``HWM_RESET`` column; ARCH leaves its shape to the fold) is canonical
JSON of exactly ``{"lineages": {<root>: <the LineageTallies fields>}, "venue": {<the VenueTallies
fields>}}``: ints as non-negative ints, ``alpha_spent`` as a non-negative canonical decimal string,
``terminal_frozen`` as a bool and every tuple field as a sorted list of ``ts_ns``.
``TallyBook.apply_carried`` merges it so that no budget is refunded (A7b-R2): ints by max, bools by
OR, lists by sorted multiset union (each instant at its higher multiplicity), so a carry never
drops an instant the fold already holds.

Pure: no I/O, no wall clock.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Context, Decimal
from typing import Any, Final

from breezy.persistence.autonomy.schemas import FAMILY_RE
from breezy.persistence.autonomy.wire import (
    WireRefusalReason,
    WireRefused,
    as_object,
    check_int,
    check_match,
    parse_json_exact,
    require_bool,
    require_decimal_str,
    require_exact_keys,
    require_list,
    require_ns,
    require_object,
)

__all__ = [
    "Carried",
    "CarriedLineage",
    "LineageTallies",
    "TallyBook",
    "VenueTallies",
    "parse_carried",
]

#: The lifetime integer counters of a lineage.
INT_COUNTERS: Final = ("nominations", "infeasible_nominations")
#: The windowed counters of a lineage: sorted instants (E-21).
TUPLE_COUNTERS: Final = (
    "nomination_instants", "mints", "promotions", "rollbacks", "model_resumes", "drill_admits",
    "drill_promotes", "drill_demotes", "drill_resumes", "drill_halts", "drill_rollbacks",
)  # fmt: skip
VENUE_COUNTERS: Final = ("infra_resumes", "drill_close_restores", "sender_changes")
_LINEAGE_KEYS: Final = (*INT_COUNTERS, *TUPLE_COUNTERS, "alpha_spent", "terminal_frozen")
#: Wide enough that summing ``alpha_k`` values of at most 38 digits each never rounds.
_EXACT: Final = Context(prec=100)


@dataclass(frozen=True, slots=True, kw_only=True)
class LineageTallies:
    """The ARCH C5 ``lineage_counters`` the fold derives (V24, V31), without ``holdout_opens``.

    The field set is frozen (``test_lineage_tallies_fields_equal_arch_counters_...``). Every
    windowed counter is a sorted tuple of effective instants (E-21); ``nominations`` is the largest
    ``k_life`` of a feasible nomination, not a row count, and ``nomination_instants`` holds every
    nomination (an infeasible one still uses the forward-window slot). ``model_resumes`` are the
    RECOVERABLE_MODEL resumes, a ROLLBACK_FAILED halt with that trigger class included.
    """

    nominations: int = 0
    infeasible_nominations: int = 0
    nomination_instants: tuple[int, ...] = ()
    alpha_spent: Decimal = Decimal(0)
    mints: tuple[int, ...] = ()
    promotions: tuple[int, ...] = ()
    rollbacks: tuple[int, ...] = ()
    model_resumes: tuple[int, ...] = ()
    terminal_frozen: bool = False
    drill_admits: tuple[int, ...] = ()
    drill_promotes: tuple[int, ...] = ()
    drill_demotes: tuple[int, ...] = ()
    drill_resumes: tuple[int, ...] = ()
    drill_halts: tuple[int, ...] = ()
    drill_rollbacks: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class VenueTallies:
    """The venue-level counters, as sorted tuples of effective instants (E-21).

    ``sender_changes`` holds every Z3 logical change: a non-drill →CHAMPION head taking effect
    (PROMOTE, ROLLBACK), a ROOT_ADMIT and a non-drill RESUME.
    """

    infra_resumes: tuple[int, ...] = ()
    drill_close_restores: tuple[int, ...] = ()
    sender_changes: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CarriedLineage:
    """One lineage's entry of a parsed ``carried_counters`` object."""

    ints: Mapping[str, int]
    alpha_spent: Decimal
    instants: Mapping[str, tuple[int, ...]]
    terminal_frozen: bool


@dataclass(frozen=True, slots=True)
class Carried:
    """A parsed ``carried_counters`` object."""

    lineages: Mapping[str, CarriedLineage]
    venue: Mapping[str, tuple[int, ...]]


def _ns_list(obj: Mapping[str, object], key: str) -> tuple[int, ...]:
    values = tuple(check_int(v, key) for v in require_list(obj, key))
    if list(values) != sorted(values):
        raise WireRefused(WireRefusalReason.BAD_VALUE, key)
    return values


def _carried_lineage(raw: object, root: str) -> CarriedLineage:
    obj = as_object(raw, root)
    require_exact_keys(obj, required=_LINEAGE_KEYS)
    alpha = require_decimal_str(obj, "alpha_spent")
    if alpha < 0:
        raise WireRefused(WireRefusalReason.BAD_VALUE, "alpha_spent")
    return CarriedLineage(
        ints={name: require_ns(obj, name) for name in INT_COUNTERS},
        alpha_spent=alpha,
        instants={name: _ns_list(obj, name) for name in TUPLE_COUNTERS},
        terminal_frozen=require_bool(obj, "terminal_frozen"),
    )


def parse_carried(text: str) -> Carried | None:
    """The parsed ``carried_counters`` text, or ``None`` when it is not of the exact shape."""
    try:
        obj = parse_json_exact(text)
        require_exact_keys(obj, required=("lineages", "venue"))
        lineages = {
            check_match(root, FAMILY_RE, "lineage"): _carried_lineage(raw, root)
            for root, raw in require_object(obj, "lineages").items()
        }
        venue = require_object(obj, "venue")
        require_exact_keys(venue, required=VENUE_COUNTERS)
        return Carried(lineages, {name: _ns_list(venue, name) for name in VENUE_COUNTERS})
    except WireRefused:
        return None


class _Counts:
    """Private working counters of one lineage."""

    def __init__(self) -> None:
        self.ints = dict.fromkeys(INT_COUNTERS, 0)
        self.alpha = Decimal(0)
        self.instants: dict[str, list[int]] = {name: [] for name in TUPLE_COUNTERS}


def _union(current: list[int], carried: tuple[int, ...]) -> list[int]:
    """Sorted multiset union: each instant at its higher multiplicity (A7b-R2)."""
    return sorted((Counter(current) | Counter(carried)).elements())


class TallyBook:
    """The mutable counters of one ``fold`` call, by lineage root; never escapes it."""

    def __init__(self, lineage_of: Mapping[str, str]) -> None:
        self._lineage_of = lineage_of
        self._counts: dict[str, _Counts] = {}
        self._venue: dict[str, list[int]] = {name: [] for name in VENUE_COUNTERS}

    def _of(self, family: str) -> _Counts:
        return self._at(self._lineage_of.get(family, family))

    def _at(self, root: str) -> _Counts:
        return self._counts.setdefault(root, _Counts())

    def charge(self, family: str, counter: str, instant: int) -> None:
        """Record ``instant`` in the windowed ``counter`` of the family's lineage."""
        self._of(family).instants[counter].append(instant)

    def charge_venue(self, counter: str, instant: int) -> None:
        self._venue[counter].append(instant)

    def nomination(
        self,
        family: str,
        instant: int,
        *,
        feasible: bool | None,
        k_life: int | None,
        alpha_k: Decimal | None,
    ) -> None:
        """Charge a SHADOW to CHALLENGER PROMOTE: the slot and α always, the index if feasible."""
        counts = self._of(family)
        if feasible is not None:  # a row without nomination columns is no nomination (7c/7d)
            counts.instants["nomination_instants"].append(instant)
        if alpha_k is not None:
            counts.alpha = _EXACT.add(counts.alpha, alpha_k)
        if feasible is False:
            counts.ints["infeasible_nominations"] += 1
        elif feasible and k_life is not None:
            counts.ints["nominations"] = max(counts.ints["nominations"], k_life)

    def apply_carried(self, carried: Carried) -> frozenset[str]:
        """Merge the carried counters (never a refund); the roots the carry freezes are returned."""
        frozen: set[str] = set()
        for root, entry in carried.lineages.items():
            counts = self._at(root)
            for name in INT_COUNTERS:
                counts.ints[name] = max(counts.ints[name], entry.ints[name])
            counts.alpha = max(counts.alpha, entry.alpha_spent)
            for name in TUPLE_COUNTERS:
                counts.instants[name] = _union(counts.instants[name], entry.instants[name])
            if entry.terminal_frozen:
                frozen.add(root)
        for name, instants in carried.venue.items():
            self._venue[name] = _union(self._venue[name], instants)
        return frozenset(frozen)

    def roots(self) -> frozenset[str]:
        """The lineage roots that have been charged or carried."""
        return frozenset(self._counts)

    def lineage(self, root: str, *, terminal_frozen: bool) -> LineageTallies:
        counts = self._counts.get(root) or _Counts()
        values: dict[str, Any] = {
            **counts.ints,
            **{name: tuple(sorted(v)) for name, v in counts.instants.items()},
        }
        return LineageTallies(alpha_spent=counts.alpha, terminal_frozen=terminal_frozen, **values)

    def venue(self) -> VenueTallies:
        return VenueTallies(**{name: tuple(sorted(v)) for name, v in self._venue.items()})
