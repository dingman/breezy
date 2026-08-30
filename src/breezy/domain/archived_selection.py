"""Supersession selection for `ArchivedClimateDay` records.

This intentionally duplicates :mod:`breezy.domain.selection`'s ordering instead
of importing or generalising it. The live selector's runtime
``isinstance(record, NwsClimateDay)`` gate is a separation barrier: widening it
to a union or Protocol would legalise a merged live+archived stream. Duplication
keeps the archive stream orderable for research without weakening settlement.

The rule is max ``(is_final, ts_init, revision_seq)`` per
``(station, climate_day)``. ``is_final`` still leads because a backfilled
preliminary must never shadow a final; ``ts_init`` then orders within one
finality class, and ``revision_seq`` breaks ties.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from breezy.domain.archived_climate_day import ArchivedClimateDay

ArchivedClimateDayKey = tuple[str, dt.date]


def archived_climate_day_key(record: ArchivedClimateDay) -> ArchivedClimateDayKey:
    """Return the `(station, climate_day)` identity an archived revision series shares."""
    return (record.station, record.climate_day)


def _ordering(record: ArchivedClimateDay) -> tuple[bool, int, int]:
    """Order by finality, then archived publication instant, then revision."""
    return (record.is_final, record.ts_init, record.revision_seq)


def _require_unwrapped(record: object) -> ArchivedClimateDay:
    if isinstance(record, ArchivedClimateDay):
        return record

    raise TypeError(
        f"expected `ArchivedClimateDay`, was {type(record).__name__}. "
        f"`ParquetDataCatalog.query`/`custom_data` return `CustomData` wrappers -- "
        f"unwrap with `[r.data for r in results]` before selecting.",
    )


def latest_by_archived_climate_day(
    records: Iterable[object],
    as_of_ts_init: int | None = None,
) -> dict[ArchivedClimateDayKey, ArchivedClimateDay]:
    """Return the current archived record for each `(station, climate_day)`.

    The bound is applied before ordering so a later final cannot leak into an
    earlier walk-forward answer. Research callers own the discipline of choosing
    any lag offset or as-of bound; this module deliberately does not provide a
    settlement-shaped accessor.
    """
    selected: dict[ArchivedClimateDayKey, ArchivedClimateDay] = {}

    for candidate in records:
        record = _require_unwrapped(candidate)

        if as_of_ts_init is not None and record.ts_init > as_of_ts_init:
            continue

        key = archived_climate_day_key(record)
        incumbent = selected.get(key)

        if incumbent is None or _ordering(record) > _ordering(incumbent):
            selected[key] = record

    return selected


def select_archived_climate_day(
    records: Iterable[object],
    station: str,
    climate_day: dt.date,
    as_of_ts_init: int | None = None,
) -> ArchivedClimateDay | None:
    """Return the current archived record for one key, or `None`."""
    return latest_by_archived_climate_day(records, as_of_ts_init=as_of_ts_init).get(
        (station, climate_day),
    )
