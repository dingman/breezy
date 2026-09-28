"""The durable forecast archive -- WP-12 Seam C (catalog / backtest source).

What this is
------------
A thin writer and reader for :class:`~breezy.domain.forecast_point.ForecastPoint`
over **one** :class:`~nautilus_trader.persistence.catalog.parquet.ParquetDataCatalog`
root **per station**. It is the archive a backtest replays and a calibration fit
reads; the live hot path keeps its own in-memory view
(:mod:`breezy.strategy.ladder_ev.forecast_state`) and never comes here.

No transport: this module names no host, opens no socket and performs catalog
I/O only.

L-1 verdict (null hypothesis: Nautilus already provides this)
-------------------------------------------------------------
Installed source: ``nautilus_trader`` 1.231.0, under ``.venv``. Nothing in the
framework is modified, patched, subclassed-to-override, or reimplemented here.

* **NATIVE AND SUFFICIENT -- storage, serialization and query.**
  ``ParquetDataCatalog.write_data`` / ``.query(data_cls=...)`` round-trip the
  registered custom type end to end (the registration itself lives at module
  scope in ``breezy.domain.forecast_point``). There is deliberately **no second
  parquet writer** in Breezy: every byte this module persists is written by the
  platform, and it never constructs a filename or a path inside the catalog
  directory, which Nautilus owns.
* **NATIVE AND SUFFICIENT -- path safety, single-writer locking and write
  verification.** Already solved in-tree by
  :mod:`breezy.persistence.catalog` for the settlement island
  (``station_catalog_path`` / ``open_station_catalog`` / ``write_records``), and
  reused verbatim rather than re-derived. The two path components it validates
  are this seam's namespace segment and the station.
* **NATIVE BUT INSUFFICIENT -- per-station partitioning.**
  ``identifier_function`` (``persistence/catalog/parquet.py:320-336``) keys
  ``Instrument`` -> ``bar_type`` -> ``instrument_id`` -> **else flat**, so an
  identifier-less custom type writes flat to ``<root>/data/custom_forecast_point``
  and two stations in ONE root cannot be separated. The recorded decision
  (``breezy.domain.forecast_point``) is **per-station catalog roots, not a
  synthetic** ``instrument_id``: a model output is not a traded instrument, and
  minting an id for one would bind the archive to per-rung, per-day venue
  symbology and make a forecast look tradeable to any standard Nautilus
  consumer. Climate day stays a query filter on the validity window, never a
  partition key.
* **NOT NATIVE -- point-in-time (as-of) selection over reissued records.**
  Nautilus replays by ``ts_init`` and has no notion of a corrected bulletin
  superseding an earlier one. That rule is
  :func:`breezy.domain.forecast_point.select_as_of` / ``latest_as_of``, pure
  functions over already-read records, and this module composes them rather
  than restating them.

Trap 1 -- a correction is NEVER a rewrite
-----------------------------------------
``_write_chunk`` (``persistence/catalog/parquet.py:370-380``) computes the
target filename from the batch's ``ts_init`` range and, if that file already
exists, ``print``\\ s ``"... already exists, skipping write"`` and **returns
normally**. No exception, no logger, no return value: a caller that treats "did
not raise" as "was written" has silently lost data.

A correction therefore MUST be a new record carrying its own later vintage --
a new ``issuance_seq`` with a strictly greater ``available_at_ns``, which lands
in a different file and is what makes the as-of rule expressible at all. A
write whose range collides with one already on disk is not a correction; it is
either a rewrite attempt or an ingest defect, and :func:`write_forecast_points`
raises :class:`SilentRewriteRefusedError` rather than letting it pass as a
success. Detection is by read-back, through
:func:`breezy.persistence.catalog.write_records`.

Trap 2 -- ``delete_data_range`` is a documented NO-OP here
----------------------------------------------------------
With ``identifier=None`` (``persistence/catalog/parquet.py:1386-1406``) the
platform enumerates leaf data directories and matches the substring
``"/data/<class_name>/"``. An identifier-less custom type's directory is
``<root>/data/custom_forecast_point`` -- there is no separator after the type
name -- so the match fails, the loop body never runs, and the call returns
having deleted nothing.

That no-op is a **feature** and this archive depends on it: it is what makes
the forecast record set append-only by construction. This module consequently
exposes no delete entry point and calls no deletion API, and a
"delete then rewrite" repair path is **forbidden** -- it would be indeterminate
(the delete silently does nothing, then the rewrite is silently skipped by trap
1, and the operator is told the repair succeeded). Repair a bad record the only
way the type supports: publish a further issuance with a later vintage. Both
behaviours are pinned by ``tests/strategy/ladder_ev/test_forecast_catalog.py``;
widen those tests if the platform changes, never delete them.

Path safety
-----------
Roots are ``<base>/forecast_point/<STATION>``. The station is normalised the
same way :class:`~breezy.domain.forecast_point.ForecastPoint` normalises its
own field (stripped, upper-cased) so one station cannot acquire two roots, then
validated as a single safe path segment with the same allowlist, symlink and
containment checks the settlement island uses. The namespace segment makes the
forecast island disjoint from the quote-tape and settlement roots even when an
operator points them at one base; :func:`require_disjoint_catalog_roots` lets a
composition root assert that rather than assume it.

Composite identifiers in this module use ``^`` (the repo's reserved separator,
:data:`breezy.domain.instrument_leg.INSTRUMENT_SEPARATOR`) and ``:``. The tilde
is never used in an identifier or a path: a tilde-composite id makes the
catalog's own query layer fail with a parser error, and a literal tilde in a
path is not expanded by :class:`pathlib.Path`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Final

from nautilus_trader.model.data import CustomData
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.forecast_point import ForecastPoint, ForecastPointKey, latest_as_of
from breezy.domain.instrument_leg import INSTRUMENT_SEPARATOR
from breezy.persistence.catalog import (
    WriteOutcome,
    open_station_catalog,
    station_catalog_path,
    write_records,
)

__all__ = [
    "FORECAST_CATALOG_NAMESPACE",
    "FORECAST_ISSUANCE_SEPARATOR",
    "ForecastCatalogRootError",
    "ForeignStationRowError",
    "SilentRewriteRefusedError",
    "forecast_catalog_root",
    "forecast_point_identity",
    "normalise_station",
    "open_forecast_catalog",
    "read_forecast_points",
    "read_forecast_points_as_of",
    "require_disjoint_catalog_roots",
    "write_forecast_points",
]

#: The directory segment that makes the forecast island its own island. Present
#: in every forecast root, so a forecast root can never coincide with a
#: quote-tape root or a settlement station root under a shared base.
FORECAST_CATALOG_NAMESPACE: Final[str] = "forecast_point"

#: Separates the forecast's identity from WHICH ISSUANCE of it. Distinct from
#: the field separator so an identity string remains splittable both ways.
FORECAST_ISSUANCE_SEPARATOR: Final[str] = ":"


class ForecastCatalogRootError(ValueError):
    """Raised when a catalog root is not a usable, isolated forecast root.

    Covers a root that does not carry this seam's namespace segment, and a root
    that overlaps another data island's root. A ``ValueError`` subclass so that
    generic configuration validation still catches it, and a distinct type so a
    layout failure is never mistaken for a data-quality failure.
    """


class ForeignStationRowError(RuntimeError):
    """Raised when a record's station contradicts the root it is stored in.

    The partition key IS the directory, so a row for another station in this
    root would be returned by every query against it and silently widen one
    station's calibration sample with another's forecasts. Refused on the write
    side (a caller mistake) and again on the read side (a foreign or
    hand-copied fragment), because only the second case survives a restart.
    """


class SilentRewriteRefusedError(RuntimeError):
    """Raised when a write collided with a range already on disk -- see trap 1.

    Never downgrade this to a warning and never "resolve" it by deleting the
    existing file: the archive is append-only by construction, and a correction
    is a new issuance with a later vintage. The offending records are named in
    the message so the ingest seam can report exactly which forecast it tried
    to restate.
    """


def normalise_station(station: str) -> str:
    """Return `station` in the one form this archive keys on.

    Identical to :class:`~breezy.domain.forecast_point.ForecastPoint`'s own
    normalisation of the field, so a record and its root cannot disagree about
    which station they describe.
    """
    if not isinstance(station, str):
        raise ForecastCatalogRootError(
            f"`station` must be a `str` ICAO station id, was {type(station).__name__}",
        )
    return station.strip().upper()


def forecast_catalog_root(base: Path, station: str) -> Path:
    """Return the catalog root for one station's forecast archive.

    ``<base>/forecast_point/<STATION>``. Both derived components are validated
    as single safe path segments, neither may already exist as a symlink, and
    the result is re-checked for containment under `base` -- all by
    :func:`breezy.persistence.catalog.station_catalog_path`, which owns those
    checks for the whole repo.

    Raises
    ------
    ValueError
        (:class:`~breezy.persistence.catalog.CatalogPathError`) if the station
        is not a single safe path segment, or a derived component is a symlink.

    """
    return station_catalog_path(
        base,
        FORECAST_CATALOG_NAMESPACE,
        normalise_station(station),
    )


def open_forecast_catalog(base: Path, station: str) -> ParquetDataCatalog:
    """Open (creating if needed) one station's forecast catalog.

    The root is created eagerly so a station with no forecasts yet is still a
    directory on disk: a missing root and an empty root are otherwise
    indistinguishable to an operator.
    """
    return open_station_catalog(
        base,
        FORECAST_CATALOG_NAMESPACE,
        normalise_station(station),
    )


def require_disjoint_catalog_roots(root: Path, *other_roots: Path) -> None:
    """Refuse a forecast `root` that overlaps another data island's root.

    Overlap means equal, or either path containing the other. Quote-tape,
    settlement and forecast data have different retention, different writers
    and different failure modes; a shared directory couples all three and the
    coupling is invisible until something is deleted.

    Raises
    ------
    ForecastCatalogRootError
        On the first overlapping root, naming both paths.

    """
    resolved = Path(root).resolve()

    for other in other_roots:
        resolved_other = Path(other).resolve()
        if (
            resolved == resolved_other
            or resolved.is_relative_to(
                resolved_other,
            )
            or resolved_other.is_relative_to(resolved)
        ):
            raise ForecastCatalogRootError(
                f"the forecast catalog root {resolved} overlaps {resolved_other}; "
                f"the forecast archive must occupy a directory no other data "
                f"island writes to or deletes from",
            )


def forecast_point_identity(point: ForecastPoint) -> str:
    """Return a stable, human-readable identity string for one record.

    Shape: ``station^model^model_version^variable^cycle^start^end:issuance``.
    The reserved ``^`` separator and the ``:`` issuance suffix are used because
    the tilde is banned repo-wide as an identifier separator. For log lines and
    error messages only -- the archive keys on
    :attr:`~breezy.domain.forecast_point.ForecastPoint.record_key`, never on
    this string.
    """
    sep = INSTRUMENT_SEPARATOR
    return (
        f"{point.station}{sep}{point.model}{sep}{point.model_version}{sep}"
        f"{point.variable}{sep}{point.cycle_runtime_ns}{sep}"
        f"{point.valid_start_ns}{sep}{point.valid_end_ns}"
        f"{FORECAST_ISSUANCE_SEPARATOR}{point.issuance_seq}"
    )


def write_forecast_points(
    catalog: ParquetDataCatalog,
    points: Sequence[ForecastPoint],
) -> WriteOutcome:
    """Append `points` to one station's archive, verifying they landed.

    Three guards, in order, before the platform is asked to write anything:

    1. every record's station must match the root's (`ForeignStationRowError`);
    2. the batch must be internally coherent as issuances --
       :func:`breezy.domain.forecast_point.latest_as_of` refuses a correction
       written under an original's sequence number, or a reissue claiming an
       earlier vintage, which is hindsight;
    3. :func:`breezy.persistence.catalog.write_records` takes the station
       root's single-writer lock, re-checks path safety under it, refuses a
       batch that is not non-decreasing in ``ts_init``, and verifies the write
       by read-back.

    Returns
    -------
    WriteOutcome
        Always complete: a skip is raised, never returned. The type is returned
        unchanged so callers can log ``written`` and the root path.

    Raises
    ------
    ForeignStationRowError
        If any record belongs to another station.
    SilentRewriteRefusedError
        If the platform silently skipped the write because the batch's
        ``ts_init`` range already exists on disk -- trap 1.
    ValueError
        From the coherence check, from the non-decreasing guard, or from the
        platform when a range *partially* overlaps an existing file (that case
        is already loud upstream).
    RuntimeError
        From the writer lock (another writer holds the station root) or from
        read-back verification.

    """
    if not points:
        return WriteOutcome(written=(), skipped=(), path=str(catalog.path))

    station = _root_station(catalog)
    _require_station(points, station=station, path=str(catalog.path))

    # Coherence of the batch as issuances. Cheap, and it fails before anything
    # touches the filesystem.
    latest_as_of(points, as_of_ns=max(point.available_at_ns for point in points))

    outcome = write_records(catalog, list(points))

    if outcome.skipped:
        identities = ", ".join(
            forecast_point_identity(record)
            for record in outcome.skipped
            if isinstance(record, ForecastPoint)
        )
        raise SilentRewriteRefusedError(
            f"the catalog at {outcome.path} silently skipped {len(outcome.skipped)} "
            f"record(s) because their `ts_init` range already exists on disk: "
            f"{identities}. This archive is append-only: a correction is a NEW "
            f"record with the next `issuance_seq` and a strictly later "
            f"`available_at_ns`, never a rewrite of an existing one. Nothing was "
            f"deleted and the stored records are unchanged.",
        )

    return outcome


def read_forecast_points(
    catalog: ParquetDataCatalog,
    *,
    start: int | None = None,
    end: int | None = None,
) -> list[ForecastPoint]:
    """Return every `ForecastPoint` in one station's archive, unwrapped.

    Parameters
    ----------
    catalog : ParquetDataCatalog
        One station's catalog, from :func:`open_forecast_catalog`.
    start, end : int, optional
        Inclusive ``ts_init`` (vintage) bounds in UNIX nanoseconds. A coarse
        retrieval bound only -- NOT the as-of rule, which is
        :func:`read_forecast_points_as_of`.

    Returns
    -------
    list[ForecastPoint]
        Raw records rather than ``CustomData`` wrappers: the shape a handler
        actually sees, and the shape the selection functions take.

    Raises
    ------
    ForeignStationRowError
        If the root holds a row for another station.

    """
    station = _root_station(catalog)
    rows: list[ForecastPoint] = []

    for item in catalog.query(data_cls=ForecastPoint, start=start, end=end):
        if isinstance(item, ForecastPoint):
            rows.append(item)
        elif isinstance(item, CustomData) and isinstance(item.data, ForecastPoint):
            rows.append(item.data)
        else:  # pragma: no cover - defensive against Nautilus API drift
            raise TypeError(
                "expected ForecastPoint rows from the Nautilus catalog query, "
                f"got {type(item).__name__}",
            )

    _require_station(rows, station=station, path=str(catalog.path))
    return rows


def read_forecast_points_as_of(
    catalog: ParquetDataCatalog,
    *,
    as_of_ns: int,
) -> dict[ForecastPointKey, ForecastPoint]:
    """Return what this station's archive could tell us at `as_of_ns`.

    Per join key, the issuance with the greatest ``available_at_ns <=
    as_of_ns`` (ties by the greater ``issuance_seq``); a key with nothing
    published by then is OMITTED rather than mapped to ``None``. A correction
    is therefore invisible to any read taken before its own vintage -- the
    leakage guard every forecast-edge measurement rests on.

    The bound is deliberately **not** pushed down into the query as an ``end``
    bound. The two are equivalent today (``ts_init`` is the vintage, and
    ``_query_pyarrow`` filters ``ts_init <= end``), but the as-of rule is
    measurement-critical and must have exactly one implementation --
    :func:`breezy.domain.forecast_point.select_as_of`. A pushdown would quietly
    become a second one, and the two would drift.
    """
    return latest_as_of(read_forecast_points(catalog), as_of_ns=as_of_ns)


def _root_station(catalog: ParquetDataCatalog) -> str:
    """Return the station a catalog root is for, refusing a non-forecast root.

    The root's own layout is the authority: ``<base>/forecast_point/<STATION>``.
    Deriving the station from the path rather than taking it as an argument is
    what lets both the writer and the reader check rows against the directory
    they are actually in, with no second source of truth to keep in step.
    """
    path = PurePosixPath(str(catalog.path))

    if path.parent.name != FORECAST_CATALOG_NAMESPACE:
        raise ForecastCatalogRootError(
            f"{path} is not a forecast catalog root: expected a "
            f"<base>/{FORECAST_CATALOG_NAMESPACE}/<STATION> layout, so that a "
            f"forecast archive can never share a directory with the quote-tape "
            f"or settlement islands. Open it with `open_forecast_catalog`.",
        )

    return path.name


def _require_station(
    points: Iterable[ForecastPoint],
    *,
    station: str,
    path: str,
) -> None:
    foreign = sorted({point.station for point in points if point.station != station})

    if foreign:
        raise ForeignStationRowError(
            f"the forecast catalog root {path} is for station {station!r} but the "
            f"records name {foreign!r}. The partition key IS the directory: a "
            f"foreign row here is returned by every query against this station "
            f"and would widen its calibration sample with another station's "
            f"forecasts.",
        )
