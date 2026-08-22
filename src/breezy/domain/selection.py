"""Supersession selection for `NwsClimateDay` records.

The single revision rule (proposal §4.3): **a correction is a new record with a
strictly later ``ts_init``, never a rewrite.** Both alternatives are broken rather
than merely inelegant on NautilusTrader 1.231.0 --
``ParquetDataCatalog._write_chunk`` silently skips a write whose computed filename
already exists (``parquet.py:378-380``: a bare ``print`` and a normal return), and
``delete_data_range`` no-ops for an identifier-less custom type
(``parquet.py:1386-1406``).

So the catalog accumulates every revision and the reader picks the current one:
**max ``(is_final, ts_init, revision_seq)`` per ``(station, climate_day)``**.

Why ``is_final`` leads
----------------------
NWS issues two CLI products per climate day: a **preliminary** carrying
``VALID TODAY AS OF 0400 PM LOCAL TIME.``, and a **final** the following ~02:27
local. Only the final is settlement-grade, so a final must outrank a preliminary
**however late the preliminary arrives**. Arrival alone is not a safe proxy for
finality: ``ts_init`` is ``retrieved_at_ns``, so a backfill that re-fetches a
week of products stamps every one of them ``now`` and a re-fetched preliminary
would then outrank the final already on disk. Max-``ts_init`` -- correct for
corrections -- silently inverts prelim/final precedence, and settling on a value
NWS never finalized is the highest-consequence error in the system.

Within one finality class arrival still decides, so the correction path is
untouched: a corrected final has a strictly later ``ts_init`` than the final it
supersedes, and before any final exists the preliminaries order among themselves
by arrival. ``revision_seq`` breaks a remaining tie.

Finality precedence and the ``as_of_ts_init`` bound
---------------------------------------------------
The bound is applied **first**, and the ordering chooses only among what had
arrived by that instant. "A final always wins" is therefore a claim about the
*filtered* candidate set, never about the whole record set: as of 17:00 on the
climate day the preliminary is genuinely all Breezy knew, so it is the correct
answer for that instant and replay must still see it.

This is why the rule is expressed as a total order on each candidate rather than
as "refuse a non-final when any final exists". The two agree on the filtered set,
but the existence phrasing invites evaluating "any final exists" over the
unfiltered records -- which would silently destroy point-in-time correctness. A
comparison key cannot see records the bound excluded.

``is_superseded`` is deliberately *not* consulted. Since prior records are never
rewritten, the flag can only record what was known when a record was written; it
can never be set retroactively on the record it supersedes. Selecting on it would
silently disagree with the write path. ``is_final`` is different in kind: it is a
property of the product NWS published, fixed at ingestion and never restated by a
later record.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from breezy.domain.nws_climate_day import NwsClimateDay

ClimateDayKey = tuple[str, dt.date]


def climate_day_key(record: NwsClimateDay) -> ClimateDayKey:
    """Return the `(station, climate_day)` identity a revision series shares."""
    return (record.station, record.climate_day)


def _ordering(record: NwsClimateDay) -> tuple[bool, int, int]:
    """Order by settlement grade, then by arrival, then by revision.

    ``is_final`` leads because only the final CLI is settlement-grade, and a
    preliminary must never outrank one no matter when it arrived (see the module
    docstring: backfill re-stamps ``ts_init`` on re-fetch). ``ts_init`` then
    orders *within* a finality class, which is what keeps the correction path
    working. ``revision_seq`` breaks the tie when two records share both, which
    happens whenever one poll returns an original and its correction together.

    The key is evaluated only on candidates that survived the ``as_of_ts_init``
    bound, so it cannot promote a record that had not arrived yet.
    """
    return (record.is_final, record.ts_init, record.revision_seq)


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

    The rule is max ``(is_final, ts_init, revision_seq)`` among the candidates
    that survived ``as_of_ts_init`` -- a final always outranks a preliminary, and
    arrival orders within a finality class. See the module docstring.

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

        # The bound is applied BEFORE `_ordering` is ever consulted: finality
        # precedence must decide among what was known at `as_of_ts_init`, not
        # promote a final that had not arrived yet.
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

    A returned record is *current*, not necessarily settlement-grade: before the
    final arrives this is the preliminary. Settlement callers must still check
    ``is_final`` -- selection guarantees a final is never shadowed, not that one
    exists.
    """
    return latest_by_climate_day(records, as_of_ts_init=as_of_ts_init).get(
        (station, climate_day),
    )
