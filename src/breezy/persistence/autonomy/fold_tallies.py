"""The counters of the registry fold (ARCH-0 seam A 7b; ARCH C5 ``lineage_counters``, Z3, Z10).

``fold`` charges a ``TallyBook`` as each row takes effect and freezes it into one
``LineageTallies`` per lineage root and one ``VenueTallies``. This module is split out of ``fold``
so that the fold stays under its size cap; it holds no chain logic of its own: which row charges
which counter is ``fold``'s (see its docstring).

``holdout_opens`` has no row source: it belongs to the AUT-5 WP4 cache and is not a field here.

``carried_counters`` (the ``HWM_RESET`` column; ARCH leaves its shape to the fold) is canonical
JSON of exactly ``{"lineages": {<root>: <the 13 LineageTallies fields>}, "venue":
{"infra_resumes": n, "drill_close_restores": n}}``: counts as non-negative ints, ``alpha_spent`` as
a non-negative canonical decimal string, ``mints`` and ``promotions`` as sorted ``ts_ns`` lists and
``terminal_frozen`` as a bool. ``TallyBook.apply_carried`` applies it as floors, so no budget is
refunded: a counter becomes the larger of its value so far and the carried one; a timestamp list
becomes the longer of the two.

Pure: no I/O, no wall clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Context, Decimal
from typing import Final

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

#: The plain integer counters of a lineage, in ``LineageTallies`` field order.
INT_COUNTERS: Final = (
    "nominations", "infeasible_nominations", "rollbacks", "drill_admits", "drill_promotes",
    "drill_demotes", "drill_resumes", "drill_halts", "drill_rollbacks",
)  # fmt: skip
VENUE_COUNTERS: Final = ("infra_resumes", "drill_close_restores")
_LINEAGE_KEYS: Final = (*INT_COUNTERS, "alpha_spent", "mints", "promotions", "terminal_frozen")
#: Wide enough that summing ``alpha_k`` values of at most 38 digits each never rounds.
_EXACT: Final = Context(prec=100)


@dataclass(frozen=True, slots=True, kw_only=True)
class LineageTallies:
    """The ARCH C5 ``lineage_counters`` the fold derives (V24, V31), without ``holdout_opens``.

    The field set is frozen (``test_lineage_tallies_fields_equal_arch_counters_...``);
    ``nominations`` is the largest ``k_life`` of a feasible nomination, not a row count.
    """

    nominations: int = 0
    infeasible_nominations: int = 0
    alpha_spent: Decimal = Decimal(0)
    mints: tuple[int, ...] = ()
    promotions: tuple[int, ...] = ()
    rollbacks: int = 0
    terminal_frozen: bool = False
    drill_admits: int = 0
    drill_promotes: int = 0
    drill_demotes: int = 0
    drill_resumes: int = 0
    drill_halts: int = 0
    drill_rollbacks: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class VenueTallies:
    """The venue-level counters: production infra RESUMEs (Z10) and E-5 drill-close restores."""

    infra_resumes: int = 0
    drill_close_restores: int = 0


@dataclass(frozen=True, slots=True)
class CarriedLineage:
    """One lineage's entry of a parsed ``carried_counters`` object."""

    ints: Mapping[str, int]
    alpha_spent: Decimal
    mints: tuple[int, ...]
    promotions: tuple[int, ...]
    terminal_frozen: bool


@dataclass(frozen=True, slots=True)
class Carried:
    """A parsed ``carried_counters`` object."""

    lineages: Mapping[str, CarriedLineage]
    venue: Mapping[str, int]


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
        mints=_ns_list(obj, "mints"),
        promotions=_ns_list(obj, "promotions"),
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
        return Carried(lineages, {name: require_ns(venue, name) for name in VENUE_COUNTERS})
    except WireRefused:
        return None


class _Counts:
    """Private working counters of one lineage."""

    def __init__(self) -> None:
        self.ints = dict.fromkeys(INT_COUNTERS, 0)
        self.alpha = Decimal(0)
        self.mints: list[int] = []
        self.promotions: list[int] = []


def _longer(current: list[int], carried: tuple[int, ...]) -> list[int]:
    return list(carried) if len(carried) > len(current) else current


class TallyBook:
    """The mutable counters of one ``fold`` call, by lineage root; never escapes it."""

    def __init__(self, lineage_of: Mapping[str, str]) -> None:
        self._lineage_of = lineage_of
        self._counts: dict[str, _Counts] = {}
        self._venue = dict.fromkeys(VENUE_COUNTERS, 0)

    def _of(self, family: str) -> _Counts:
        return self._at(self._lineage_of.get(family, family))

    def _at(self, root: str) -> _Counts:
        return self._counts.setdefault(root, _Counts())

    def bump(self, family: str, counter: str) -> None:
        """One more of the integer ``counter`` on the family's lineage."""
        self._of(family).ints[counter] += 1

    def bump_venue(self, counter: str) -> None:
        self._venue[counter] += 1

    def mint(self, family: str, instant: int) -> None:
        self._of(family).mints.append(instant)

    def promotion(self, family: str, instant: int) -> None:
        self._of(family).promotions.append(instant)

    def nomination(
        self, family: str, *, feasible: bool | None, k_life: int | None, alpha_k: Decimal | None
    ) -> None:
        """Charge a SHADOW to CHALLENGER PROMOTE: α always, the index only when feasible."""
        counts = self._of(family)
        if alpha_k is not None:
            counts.alpha = _EXACT.add(counts.alpha, alpha_k)
        if feasible is False:
            counts.ints["infeasible_nominations"] += 1
        elif feasible and k_life is not None:
            counts.ints["nominations"] = max(counts.ints["nominations"], k_life)

    def apply_carried(self, carried: Carried) -> frozenset[str]:
        """Raise every counter to its carried floor; the roots the carry freezes are returned."""
        frozen: set[str] = set()
        for root, entry in carried.lineages.items():
            counts = self._at(root)
            for name in INT_COUNTERS:
                counts.ints[name] = max(counts.ints[name], entry.ints[name])
            counts.alpha = max(counts.alpha, entry.alpha_spent)
            counts.mints = _longer(counts.mints, entry.mints)
            counts.promotions = _longer(counts.promotions, entry.promotions)
            if entry.terminal_frozen:
                frozen.add(root)
        for name, value in carried.venue.items():
            self._venue[name] = max(self._venue[name], value)
        return frozenset(frozen)

    def roots(self) -> frozenset[str]:
        """The lineage roots that have been charged or carried."""
        return frozenset(self._counts)

    def lineage(self, root: str, *, terminal_frozen: bool) -> LineageTallies:
        counts = self._counts.get(root) or _Counts()
        return LineageTallies(
            alpha_spent=counts.alpha,
            mints=tuple(counts.mints),
            promotions=tuple(counts.promotions),
            terminal_frozen=terminal_frozen,
            **counts.ints,
        )

    def venue(self) -> VenueTallies:
        return VenueTallies(**self._venue)
