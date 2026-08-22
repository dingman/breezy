"""Supersession selection for `NwsClimateDay` records.

The single revision rule (proposal §4.3): **a correction is a new record with a
strictly later ``ts_init``, never a rewrite.** Both alternatives are broken rather
than merely inelegant on NautilusTrader 1.231.0 --
``ParquetDataCatalog._write_chunk`` silently skips a write whose computed filename
already exists (``parquet.py:378-380``: a bare ``print`` and a normal return), and
``delete_data_range`` no-ops for an identifier-less custom type
(``parquet.py:1386-1406``).

So the catalog accumulates every revision and the reader picks the current one:
**max ``ts_init`` per ``(station, climate_day)``**.

``is_superseded`` is deliberately *not* consulted. Since prior records are never
rewritten, the flag can only record what was known when a record was written; it
can never be set retroactively on the record it supersedes. Selecting on it would
silently disagree with the write path.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from breezy.domain.nws_climate_day import NwsClimateDay

ClimateDayKey = tuple[str, dt.date]


def climate_day_key(record: NwsClimateDay) -> ClimateDayKey:
    """Return the `(station, climate_day)` identity a revision series shares."""
    return (record.station, record.climate_day)


def _ordering(record: NwsClimateDay) -> tuple[int, int]:
    """Order by arrival, then by revision.

    ``revision_seq`` breaks the tie when two records share a ``ts_init``, which
    happens whenever a poll returns an original and its correction together.
    """
    return (record.ts_init, record.revision_seq)


def _require_unwrapped(record: object) -> NwsClimateDay:
    if isinstance(record, NwsClimateDay):
        return record

    raise TypeError(
        f"expected `NwsClimateDay`, was {type(record).__name__}. "
        f"`ParquetDataCatalog.query`/`custom_data` return `CustomData` wrappers -- "
        f"unwrap with `[r.data for r in results]` before selecting.",
    )


def latest_by_climate_day(
    records: Iterable[object],
    as_of_ts_init: int | None = None,
) -> dict[ClimateDayKey, NwsClimateDay]:
    """Return the current record for each `(station, climate_day)`.

    Parameters
    ----------
    records : Iterable[NwsClimateDay]
        Unwrapped records, in any order.
    as_of_ts_init : int, optional
        Inclusive upper bound on ``ts_init``. Records that arrived after this
        instant are ignored, reproducing the answer the resolver would have given
        then. Replay gets point-in-time correctness implicitly; post-hoc audit
        needs it as a first-class query.

    Returns
    -------
    dict[tuple[str, datetime.date], NwsClimateDay]

    """
    selected: dict[ClimateDayKey, NwsClimateDay] = {}

    for candidate in records:
        record = _require_unwrapped(candidate)

        if as_of_ts_init is not None and record.ts_init > as_of_ts_init:
            continue

        key = climate_day_key(record)
        incumbent = selected.get(key)

        if incumbent is None or _ordering(record) > _ordering(incumbent):
            selected[key] = record

    return selected


def select_climate_day(
    records: Iterable[object],
    station: str,
    climate_day: dt.date,
    as_of_ts_init: int | None = None,
) -> NwsClimateDay | None:
    """Return the current record for one `(station, climate_day)`, or `None`.

    See :func:`latest_by_climate_day` for the selection rule and the
    ``as_of_ts_init`` bound.
    """
    return latest_by_climate_day(records, as_of_ts_init=as_of_ts_init).get(
        (station, climate_day),
    )
