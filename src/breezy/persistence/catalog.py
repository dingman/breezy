"""Per-station `ParquetDataCatalog` plumbing for NWS settlement records.

Why one catalog root per station
--------------------------------
There is no in-catalog filter that separates two stations' records on
NautilusTrader 1.231.0, because neither :class:`~breezy.domain.nws_climate_day.NwsClimateDay`
nor :class:`~breezy.domain.nws_raw_product.NwsRawProduct` carries an
``instrument_id``:

* ``_write_chunk`` partitions on ``Instrument`` -> ``bar_type`` -> ``instrument_id``
  and otherwise writes **flat** to ``data/custom_<snake_name>/`` (``parquet.py:320-336``),
  so every station's rows land in one directory;
* ``write_data(..., identifier=...)`` is only consulted for the empty-data
  file-name-extension case, and is otherwise derived from the objects themselves --
  a custom type without ``instrument_id`` yields ``None``;
* ``query(..., identifiers=[...])`` therefore matches nothing and returns ``[]``;
* ``DataType`` metadata does not filter the catalog at all -- it only tags the
  returned wrapper, so two ``BacktestDataConfig`` s differing only by metadata
  replay every row twice.

The partition key that remains is the **directory**. This module owns that
decision so the ingest and replay paths cannot disagree about it.

Path safety
-----------
Roots derive from registry identifiers (``venue``, ``city``) and nothing else.
Interpolating a value parsed out of product text into a filesystem path is a
path-traversal write primitive: a station code lifted from a malformed product
could escape the data directory. :func:`station_catalog_path` validates both
components against a strict allowlist and re-checks containment under the base.

It also refuses a derived component that *already exists as a symlink*.
Containment alone does not close that case: a link from one station root to
another stays inside the base, passes the check, and silently merges two
stations' records into one directory. Only components derived here
(``<base>/<venue>`` and ``<base>/<venue>/<city>``) are checked -- never ``base``
itself or anything above it, because pointing a data root at a symlinked volume
is ordinary deployment practice and rejecting it would be a false positive.

That check alone is not sufficient, because it is not atomic with the
directory creation that follows it. :meth:`pathlib.Path.mkdir` with
``exist_ok=True`` catches ``FileExistsError`` and falls back to ``is_dir()``,
which **follows symlinks**: a link planted in the window between the check and
the ``mkdir`` is accepted as "already exists and is a directory", and every
subsequent write goes to a directory of someone else's choosing with no
exception and no log. The writer lock closes its own version of this window in
the kernel with ``O_NOFOLLOW``; the directory has no such flag, so
:func:`_require_real_directory` re-verifies with ``os.lstat`` (which does not
follow) **after** the ``mkdir`` -- and again inside the writer lock's critical
section on every :func:`write_records` call, which narrows the exposure from
"once per process lifetime" to "immediately before each write, under the lock".
The consequence of missing it is worse than the lock case: a subverted lock lets
two writers race, which read-back verification catches, while an aliased root
durably merges two stations' settlement records and no read-back can tell.

Corrections
-----------
A correction is a **new record with a strictly later** ``ts_init``, never a
rewrite (proposal SS4.3). Nothing here deletes or overwrites: ``delete_data_range``
no-ops for identifier-less custom types (``parquet.py:1386-1406`` substring-matches
``"/data/<name>/"``, which a flat directory never contains), and a same-range
rewrite is **silently discarded** (``parquet.py:378-380`` prints and returns
normally). :func:`write_records` detects that second case by read-back and
reports it; it never constructs a filename or path inside the catalog directory,
which Nautilus owns.

Concurrency -- one writer per station root
-----------------------------------------
:func:`write_records` verifies its own write by reading the catalog back, and
that ``before`` -> ``write_data`` -> ``after`` sequence is not atomic. Two writers
racing on one station root would be reasoning about a window the other is
mutating. Every interleaving traced so far resolves to either the correct
``skipped`` verdict or a loud :class:`CatalogWriteError` -- never a silent false
"written" -- but that is not proven for all of them, and a settlement write path
should not depend on an unproven property.

So the invariant is stated AND enforced: **at most one writer process per station
root**, held for the duration of each :func:`write_records` call by a non-blocking
``flock`` advisory lock on ``<root>/.breezy-writer.lock``. A second writer fails
immediately with :class:`ConcurrentWriterError` instead of relying on the skip
detector to notice downstream.

The lock is deliberately **write-only**. Readers -- :func:`read_climate_days`,
:func:`read_raw_products`, both climate-day accessors, and Nautilus's own
``BacktestNode`` replay, which opens the root itself and never calls this module --
take no lock at all, so any number of processes may read one station root
concurrently. Locking reads would serialise multi-process replay for no
correctness gain: nothing here ever mutates or deletes an existing file.

``flock`` is advisory and POSIX-only. It binds every writer that goes through this
module (the only sanctioned write path) and is released by the kernel if the
holder dies, so a crashed ingest process cannot wedge a station.

The lock file is opened with ``O_NOFOLLOW``. Without it, a symlink pre-planted at
``<root>/.breezy-writer.lock`` redirects the ``flock`` onto an inode of someone
else's choosing: two writers on one station root then hold locks on two different
inodes, and the single-writer guarantee is gone with no exception and no log. The
precondition for planting one is local write access to the data root -- roughly
what tampering with the parquet files directly would need -- so this is
defence in depth, not a standalone exploit. It is still closed, because the whole
point of this module is to be the component that does not silently degrade.

``flock`` also assumes a **single host on a local filesystem**
---------------------------------------------------------------
``flock`` is unreliable over NFS (pre-v4 outright; v4 depending on lock-manager
configuration) and over CIFS/SMB, sshfs and other network-backed mounts. If a
station root is ever moved to shared storage -- a plausible step toward HA -- the
"at most one writer" invariant degrades **silently**: no exception, no log, just
weaker mutual exclusion between hosts. That is an unenforceable deployment
precondition, so it is asserted rather than merely documented:
:func:`probe_filesystem` reads the mount table and
:func:`assert_writer_lock_filesystem_supported` refuses a network-backed root.

**The assertion is deployment-invoked, never an import-time or per-write side
effect** -- nothing in :func:`open_station_catalog` or :func:`write_records`
touches the mount table. Call it once at startup, per station root.

**Detection is Linux-only.** The filesystem type of a path is not exposed by any
stdlib call (``os.statvfs`` carries no type field and CPython ships no
``os.statfs``), so it is read from ``/proc/self/mountinfo``. Where that file is
absent or unreadable -- non-Linux, or a container without ``/proc`` -- the probe
reports :attr:`FilesystemLocality.UNDETERMINED` and the assertion **fails
closed**. It never reports "cannot verify" as "verified local", because a check
that can be wrong in the unsafe direction is worse than an honest docstring.
Conversely it does not blanket-reject everything that is not a plain local disk:
overlayfs, tmpfs and friends are where containers ordinarily run and ``flock`` is
correct on them, so only genuinely network-shared types are refused (see
:data:`NETWORK_FILESYSTEM_TYPES`).

Selection is not reimplemented here -- :mod:`breezy.domain.selection` owns the
supersession rule, keyed on ``(is_final, ts_init, revision_seq)``, and the
``as_of_ts_init`` bound.

Two questions, two accessors
----------------------------
"What should the venue have settled on at 08:00 ET?" and "what do we believe
now?" are different questions with different answers, and the difference is
money: ``is_final`` leads the ordering and ``is_superseded`` is deliberately
never consulted, so an **unbounded** query always prefers a corrected final --
same ``is_final``, strictly later ``ts_init``. Venue P&L is immutable, so a
settlement, reconciliation or retry path that reads the corrected value is
reading a number the venue never paid out on.

A single function with an optional bound makes the safe call depend on every
future caller remembering an argument. So there are two, and the wrong one does
not type-check:

* :func:`read_climate_day_as_of_settlement` -- settlement-facing.
  ``as_of_ts_init`` is a **required keyword with no default**.
* :func:`read_climate_day_including_corrections` -- audit/truth-facing.
  Unbounded, and named for what it may return.

This mirrors the structural remedy already used for the two-clocks problem
(:class:`~breezy.registry.sites.ClimateDayWindow` vs
:class:`~breezy.registry.sites.SettlementDeadline`) and the enrichment barrier:
distinct names and distinct shapes, so the wrong one is not reachable by
autocomplete. There is deliberately no unbounded-by-default accessor.
"""

from __future__ import annotations

import datetime as dt
import errno
import fcntl
import os
import re
import stat
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any, Final

from nautilus_trader.core.data import Data
from nautilus_trader.model.data import CustomData
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.domain.selection import select_climate_day

__all__ = [
    "NETWORK_FILESYSTEM_TYPES",
    "WRITER_LOCK_FILENAME",
    "CatalogPathError",
    "CatalogWriteError",
    "ConcurrentWriterError",
    "FilesystemLocality",
    "FilesystemProbe",
    "NonMonotonicWriteError",
    "WriteOutcome",
    "WriterLockError",
    "WriterLockFilesystemError",
    "assert_writer_lock_filesystem_supported",
    "open_station_catalog",
    "probe_filesystem",
    "read_climate_day_as_of_settlement",
    "read_climate_day_including_corrections",
    "read_climate_days",
    "read_raw_products",
    "station_catalog_path",
    "write_records",
]

_COMPONENT_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_COMPONENT_MAX_LEN: Final[int] = 64

WRITER_LOCK_FILENAME: Final[str] = ".breezy-writer.lock"

# `open(..., O_NOFOLLOW)` on a symlink is ELOOP on Linux and EMLINK on the BSDs.
# Both are treated as a path-safety failure rather than an environment failure;
# either way the write is refused, so the only cost of the (vanishingly unlikely)
# EMLINK-from-`mkdir` overlap is a less precise message on an already-loud abort.
_SYMLINKED_LOCK_ERRNOS: Final[frozenset[int]] = frozenset({errno.ELOOP, errno.EMLINK})

_Fingerprint = tuple[tuple[str, Any], ...]


class CatalogPathError(ValueError):
    """Raised when a catalog path is not safe to write through.

    Covers both a component that is not a safe registry identifier and a
    component (or the writer-lock file) that already exists as a **symlink**,
    which would silently redirect a write or a lock somewhere else.

    A `ValueError` subclass so that callers which validate configuration
    generically still catch it, and a distinct type so that a path-safety
    failure is never confused with a data-quality failure.
    """


class NonMonotonicWriteError(ValueError):
    """Raised when a batch is not non-decreasing in `ts_init` for its record type.

    `ParquetDataCatalog._objects_to_table` performs the same check, but only
    after `_write_chunk` has already created the target directory, and with a
    message that names neither the record type nor the offending pair. Failing
    first keeps the filesystem untouched by a rejected batch.
    """


class WriterLockError(RuntimeError):
    """Raised when a station root's writer lock could not be acquired.

    The *environmental* failures -- read-only filesystem, disk full, permission
    denied, something other than a regular file already at the lock path. These
    used to escape as a raw `OSError`, outside :func:`write_records`'s documented
    taxonomy, so a caller catching :class:`ConcurrentWriterError` to back off
    crashed unhandled instead.

    Behaviour is unchanged and still **fail-closed**: the lock is acquired before
    anything is read or written, so a failure here means ``write_data`` was never
    reached and the catalog is untouched.

    :class:`ConcurrentWriterError` is a subclass, so ``except WriterLockError`` is
    the complete guard for "could not take the lock" while the narrower type stays
    available for the one case that is worth retrying. Do NOT catch this type to
    back off and retry -- none of these conditions clears on its own.
    """


class ConcurrentWriterError(WriterLockError):
    """Raised when another process already holds a station root's writer lock.

    Failing here is the point: the alternative is two writers interleaving inside
    the read-back verification window, where the skip detector's guarantees have
    not been established. Blocking is deliberately not offered -- an ingest path
    that quietly waits on a lock is an ingest path that has silently stopped
    polling.
    """


class CatalogWriteError(RuntimeError):
    """Raised when a write leaves the catalog in a state that is neither outcome.

    `write_data` groups by ``(class name, identifier)`` and our identifier-less
    custom types produce exactly one chunk per class, so a class's records are
    either all written or all skipped. Anything else means the platform's write
    grouping changed and the skip detector can no longer be trusted.
    """


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """What a :func:`write_records` call actually persisted.

    A successful return from ``write_data`` does not mean data was written: when
    the computed filename already exists, ``_write_chunk`` prints
    ``"... already exists, skipping write"`` to stdout and returns normally, with
    no exception and no logger. This type carries the read-back verdict so the
    caller -- not this module -- decides what a skip means. Ingest should treat a
    non-empty ``skipped`` as an integrity event: the record's ``ts_init`` range
    collided with data already on disk.

    Attributes
    ----------
    written : tuple[Data, ...]
        Records observed in the catalog after the write that were not there
        before, in submission order.
    skipped : tuple[Data, ...]
        Records whose class was silently skipped, in submission order.
    path : str
        The catalog root the write targeted, for logging.

    """

    written: tuple[Data, ...]
    skipped: tuple[Data, ...]
    path: str

    @property
    def is_complete(self) -> bool:
        """Whether every submitted record reached the catalog."""
        return not self.skipped


def station_catalog_path(base: Path, venue: str, city: str) -> Path:
    """Return the catalog root for one `(venue, city)` settlement site.

    Parameters
    ----------
    base : Path
        Root of the NWS data island (e.g. ``data/nws``). Enrichment data lives
        under a disjoint base and never shares a root with settlement data.
    venue : str
        Registry venue key, e.g. ``"polymarket_us"``.
    city : str
        Registry city key, e.g. ``"NYC"``.

    Returns
    -------
    Path
        ``base / venue / city``. Case is preserved verbatim so the directory is
        auditable against ``sites.toml``.

    Raises
    ------
    CatalogPathError
        If either component is not a single safe path segment, or if a derived
        component already exists as a symlink. ``base`` itself is deliberately
        not checked -- see the module docstring's "Path safety".

    Notes
    -----
    Both components MUST come from
    :meth:`breezy.registry.sites.SiteRegistry.settlement_site` (or
    :meth:`~breezy.registry.sites.SiteRegistry.pairs`), never from parsed product
    text. Validation here is a backstop, not a licence to pass untrusted input.

    """
    validated_venue = _require_path_component(venue, "venue")
    validated_city = _require_path_component(city, "city")

    root = Path(base) / validated_venue / validated_city

    _require_no_symlinked_components(Path(base), (validated_venue, validated_city))

    # Belt and braces: the allowlist already excludes separators and `..`.
    if not root.resolve().is_relative_to(Path(base).resolve()):
        raise CatalogPathError(
            f"derived catalog root {root} escapes base {base}",
        )

    return root


def open_station_catalog(base: Path, venue: str, city: str) -> ParquetDataCatalog:
    """Open (creating if needed) the catalog for one `(venue, city)` site.

    The root is created eagerly so that a station with no data yet is still a
    directory on disk -- a missing root and an empty root are otherwise
    indistinguishable to an operator inspecting the data island.

    Raises
    ------
    CatalogPathError
        If the path is unsafe, or if what is on disk after the ``mkdir`` is not
        a real directory. The path check and the ``mkdir`` are separate
        syscalls, and ``mkdir(exist_ok=True)`` reports success for a **symlink**
        to a directory, so the result is re-verified here rather than trusted.
        This is not the last word: :func:`write_records` re-checks under the
        writer lock, because a root opened once is written through for the whole
        life of the process.

    """
    root = station_catalog_path(base, venue, city)
    root.mkdir(parents=True, exist_ok=True)

    # Post-`mkdir`, with calls that do NOT follow symlinks: the component walk
    # covers `<base>/<venue>` (which `root` alone cannot speak for), and the
    # `lstat` covers `root` itself.
    _require_no_symlinked_components(Path(base), (venue, city))
    _require_real_directory(root)

    return ParquetDataCatalog(path=root)


def write_records(catalog: ParquetDataCatalog, records: Sequence[Data]) -> WriteOutcome:
    """Write `records` to `catalog`, verifying by read-back that they landed.

    Parameters
    ----------
    catalog : ParquetDataCatalog
        A single station's catalog, from :func:`open_station_catalog`.
    records : Sequence[Data]
        Records of any registered custom type, non-decreasing in ``ts_init``
        within each type. Mixed types in one batch are fine: ``write_data``
        groups by class before writing.

    Returns
    -------
    WriteOutcome

    Raises
    ------
    NonMonotonicWriteError
        If any record type's records are not non-decreasing in ``ts_init``.
        Raised before any filesystem access.
    ConcurrentWriterError
        If another writer already holds this station root's lock. The one
        lock-acquisition failure worth backing off and retrying.
    WriterLockError
        If the lock could not be acquired for any other reason -- read-only
        filesystem, disk full, permission denied, or something other than a
        regular file at the lock path. Fail-closed: nothing was written.
        :class:`ConcurrentWriterError` is a subclass, so catch this type to
        handle every "could not take the lock" outcome at once.
    CatalogPathError
        If the writer-lock path is a symlink, or if the station root itself is
        no longer a real directory. Refusing to follow either is what keeps both
        the lock and the records bound to this station root rather than to an
        inode of someone else's choosing. The root is re-checked on **every**
        call, under the lock: it was validated when the catalog was opened, but
        a root is opened once and written through for the life of the process.
    CatalogWriteError
        If read-back shows a partial write, which the platform's per-class
        chunking should make impossible.
    ValueError
        Propagated from the catalog when a batch's ``ts_init`` range *partially*
        overlaps an existing file. That case is loud upstream; only the exact
        same-range rewrite is silent, and that one is reported in the outcome.
        (:class:`CatalogPathError` is also a ``ValueError``.)

    """
    if not records:
        return WriteOutcome(written=(), skipped=(), path=str(catalog.path))

    grouped = _group_by_type(records)

    for data_cls, group in grouped.items():
        _require_non_decreasing(data_cls, group)

    skipped_classes: set[type[Data]] = set()

    with _writer_lock(catalog):
        before = {
            data_cls: _fingerprint_counts(catalog, data_cls, group)
            for data_cls, group in grouped.items()
        }

        catalog.write_data(list(records))

        for data_cls, group in grouped.items():
            after = _fingerprint_counts(catalog, data_cls, group)
            expected = before[data_cls] + Counter(_fingerprint(record) for record in group)

            if after == expected:
                continue

            if after == before[data_cls]:
                skipped_classes.add(data_cls)
                continue

            raise CatalogWriteError(
                f"read-back after writing {len(group)} {data_cls.__name__} record(s) to "
                f"{catalog.path} matched neither a complete write nor a complete skip; "
                f"the catalog's per-class write grouping may have changed",
            )

    return WriteOutcome(
        written=tuple(r for r in records if type(r) not in skipped_classes),
        skipped=tuple(r for r in records if type(r) in skipped_classes),
        path=str(catalog.path),
    )


def read_climate_days(
    catalog: ParquetDataCatalog,
    *,
    start: int | None = None,
    end: int | None = None,
) -> list[NwsClimateDay]:
    """Return every `NwsClimateDay` in `catalog`, unwrapped.

    Parameters
    ----------
    catalog : ParquetDataCatalog
    start, end : int, optional
        Inclusive ``ts_init`` bounds in UNIX nanoseconds.

    Returns
    -------
    list[NwsClimateDay]
        Raw records, not ``CustomData`` wrappers. ``catalog.custom_data`` (whose
        parameter is ``cls``, not ``data_cls``) returns wrappers because ``query``
        already wraps non-Nautilus classes; ``on_data`` delivers the unwrapped
        object, so this returns the shape handlers actually see.

    """
    return _read(catalog, NwsClimateDay, start=start, end=end)


def read_raw_products(
    catalog: ParquetDataCatalog,
    *,
    start: int | None = None,
    end: int | None = None,
) -> list[NwsRawProduct]:
    """Return every `NwsRawProduct` in `catalog`, unwrapped.

    See :func:`read_climate_days`. Callers MUST still call
    :meth:`~breezy.domain.nws_raw_product.NwsRawProduct.verify_digest` before any
    settlement use of the stored text -- reading it back does not re-verify it.
    """
    return _read(catalog, NwsRawProduct, start=start, end=end)


def read_climate_day_as_of_settlement(
    catalog: ParquetDataCatalog,
    *,
    station: str,
    climate_day: dt.date,
    as_of_ts_init: int,
) -> NwsClimateDay | None:
    """Return the record as known at `as_of_ts_init` -- the SETTLEMENT answer.

    Use this wherever the question is "what should the venue have settled on",
    including reconciliation and any retry of a settlement decision. Venue P&L
    is immutable, so these paths must read the value that was current at the
    settlement instant, never a correction that landed afterwards.

    ``as_of_ts_init`` is a **required keyword with no default**, and ``None`` is
    rejected at runtime. That is the whole point of this function existing
    separately from :func:`read_climate_day_including_corrections`: an optional
    bound makes correctness depend on every future caller remembering to pass
    one, and the failure is silent -- an unbounded query returns a *later*
    corrected final in preference to the record the venue actually paid out on,
    because ``is_final`` leads the ordering and ``is_superseded`` is never
    consulted.

    Parameters
    ----------
    catalog : ParquetDataCatalog
        One station's catalog, from :func:`open_station_catalog`.
    station : str
        The registry **CLI location** code -- see
        :func:`read_climate_day_including_corrections`.
    climate_day : datetime.date
    as_of_ts_init : int
        Inclusive upper bound on ``ts_init`` in UNIX nanoseconds: the answer the
        resolver would have given at that instant. Source it from the venue's
        settlement deadline (:class:`~breezy.registry.sites.SettlementDeadline`),
        not from "now".

    Returns
    -------
    NwsClimateDay or None
        ``None`` when nothing for that key had arrived by ``as_of_ts_init``.
        A returned record is *current as of the bound*, not necessarily
        settlement-grade: callers must still check ``is_final``.

    Raises
    ------
    TypeError
        If ``as_of_ts_init`` is omitted (also a `mypy` error) or is not an
        ``int``. ``None`` in particular would silently un-bound the query.

    """
    if not isinstance(as_of_ts_init, int):
        raise TypeError(
            f"`as_of_ts_init` must be an `int` UNIX-nanosecond bound, was "
            f"{type(as_of_ts_init).__name__}. Un-bounding this query returns "
            f"corrections that landed after settlement, which is a different "
            f"question: call `read_climate_day_including_corrections` if that "
            f"is genuinely what you want.",
        )

    return _select_current_climate_day(
        catalog,
        station=station,
        climate_day=climate_day,
        as_of_ts_init=as_of_ts_init,
    )


def read_climate_day_including_corrections(
    catalog: ParquetDataCatalog,
    *,
    station: str,
    climate_day: dt.date,
) -> NwsClimateDay | None:
    """Return the latest record for `(station, climate_day)` -- the AUDIT answer.

    Unbounded on purpose, and named for what that means: if a correction has
    landed, this returns the *corrected* value, which is what Breezy believes
    now and NOT what the venue settled on. Use it for audit, monitoring, truth
    reconstruction and supersession review.

    **Never** call this from a settlement, reconciliation or retry path --
    :func:`read_climate_day_as_of_settlement` is the accessor for those, and it
    forces the bound to be stated.

    Parameters
    ----------
    catalog : ParquetDataCatalog
        One station's catalog. ``station`` is still matched on the record, so a
        catalog that somehow holds a second station's rows cannot leak one in.
    station : str
        The registry **CLI location** code -- ``NYC``, ``MDW``, ``LAX`` -- which is
        what the record's ``station`` field holds. This is NOT the registry
        ``city`` key, even where the two strings coincide. Source it as
        ``registry.settlement_site(venue, city).cli_location``; passing ``city``
        directly is a settlement bug waiting for the first site where they differ.
    climate_day : datetime.date

    Returns
    -------
    NwsClimateDay or None
        The *current* record, which is not necessarily settlement-grade: before
        the final arrives this is the preliminary. Callers must check
        ``is_final`` themselves -- selection guarantees a final is never
        shadowed, not that one exists.

    """
    return _select_current_climate_day(
        catalog,
        station=station,
        climate_day=climate_day,
        as_of_ts_init=None,
    )


def _select_current_climate_day(
    catalog: ParquetDataCatalog,
    *,
    station: str,
    climate_day: dt.date,
    as_of_ts_init: int | None,
) -> NwsClimateDay | None:
    """Shared body of the two accessors -- never called directly.

    Private so that the unbounded shape is not reachable as an entry point:
    the public surface is exactly the two named questions.

    Composes :func:`read_climate_days` with
    :func:`breezy.domain.selection.select_climate_day`, which owns the rule --
    max ``(is_final, ts_init, revision_seq)`` per ``(station, climate_day)``,
    ``is_final`` leading so that a backfilled preliminary can never shadow a
    final -- and the ``as_of_ts_init`` bound. Only the key's shape is named here;
    the rule itself is not restated.

    Notes
    -----
    The bound is deliberately NOT pushed down into the catalog query as an
    ``end`` bound. The two filters are equivalent today (``_query_pyarrow`` filters
    ``ts_init <= end``), but the selection rule is settlement-critical and must have
    exactly one implementation; a pushdown would silently become a second one.

    This therefore reads the station's whole catalog into memory per lookup, with
    no bound. Accepted, not overlooked: one station accumulates ~2 records per
    climate day, so a multi-year root is thousands of rows, and replay is one-shot
    (see `tests/contract/test_persistence_streaming_replay.py`) so the whole
    dataset is resident during a backtest anyway. Revisit if retention grows by
    orders of magnitude -- and if so, bound it at the CALL site by reading through
    :func:`read_climate_days` and passing the result to
    :func:`breezy.domain.selection.select_climate_day` directly, rather than by
    adding a bound here that could silently exclude the record an
    ``as_of_ts_init`` query needs.

    """
    records = read_climate_days(catalog)

    return select_climate_day(
        records,
        station=station,
        climate_day=climate_day,
        as_of_ts_init=as_of_ts_init,
    )


# -- internals ------------------------------------------------------------------------------


def _require_path_component(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise CatalogPathError(
            f"`{name}` must be a `str` registry identifier, was {type(value).__name__}",
        )

    if len(value) > _COMPONENT_MAX_LEN:
        raise CatalogPathError(
            f"`{name}` exceeds {_COMPONENT_MAX_LEN} characters: {value[:16]!r}...",
        )

    if _COMPONENT_PATTERN.fullmatch(value) is None:
        raise CatalogPathError(
            f"`{name}` must be a single path segment matching "
            f"{_COMPONENT_PATTERN.pattern} (registry identifiers only, never "
            f"a value parsed from product text), was {value!r}",
        )

    return value


def _require_no_symlinked_components(base: Path, components: Sequence[str]) -> None:
    """Refuse a DERIVED path component that already exists as a symlink.

    `base` and everything above it are deliberately not checked: an operator
    pointing a data root at a symlinked volume is ordinary practice, and
    rejecting it would be the false positive that gets a safety check ripped out.
    The components derived here have no such excuse -- nothing legitimate creates
    ``<base>/<venue>`` or ``<base>/<venue>/<city>`` as a link.

    A non-existent component is not a symlink and passes; the point is only to
    avoid *trusting* something already on disk.
    """
    current = base

    for component in components:
        current = current / component

        if current.is_symlink():
            raise CatalogPathError(
                f"catalog path component {current} is a symlink and was not "
                f"followed; a station root reached through a link is neither "
                f"isolated from the other stations nor covered by this root's "
                f"writer lock",
            )


def _require_real_directory(root: Path) -> None:
    """Refuse a station root that is not a real directory, WITHOUT following links.

    The check that matters is `os.lstat`, which -- unlike every path predicate
    used to derive the root -- does not follow a symlink. `Path.mkdir` with
    ``exist_ok=True`` catches `FileExistsError` and falls back to `self.is_dir()`,
    which DOES follow, so a link planted between a symlink check and the `mkdir`
    is reported as "already exists and is a directory" and every write from then
    on lands in the link's target.

    Raising `CatalogPathError` rather than a new type is deliberate:
    `breezy.ingest.routing` enumerates the catalog write-path taxonomy exactly,
    and this IS a path-safety failure -- the same class of event as a symlinked
    component or a symlinked lock file.
    """
    try:
        status = os.lstat(root)
    except OSError as exc:
        raise CatalogPathError(
            f"the station root {root} could not be verified as a real directory "
            f"({exc}); refusing to write through a path whose identity on disk "
            f"is unknown",
        ) from exc

    if not stat.S_ISDIR(status.st_mode):
        raise CatalogPathError(
            f"station root {root} is not a real directory: `lstat` (which does "
            f"not follow links) reports {stat.filemode(status.st_mode)}. A "
            f"symlink here silently merges two stations' settlement records "
            f"into one directory, and `mkdir(exist_ok=True)` cannot detect it "
            f"because its `is_dir()` fallback follows the link",
        )


@contextmanager
def _writer_lock(catalog: ParquetDataCatalog) -> Iterator[None]:
    """Hold this station root's advisory writer lock, or fail immediately.

    The lock file sits at the catalog ROOT, not inside `data/<name>/`, so it is
    invisible to every Nautilus path -- the catalog only ever globs beneath
    `data/`. It is created empty and never written to: its content would be a
    second source of truth about who holds it, and the kernel already knows.

    `O_NOFOLLOW` makes a pre-planted symlink at the lock path fail the open rather
    than silently move the lock to its target. It is checked by the kernel as part
    of the open, so there is no check-then-open window to race, and it covers the
    dangling-symlink case too -- `O_CREAT` on a dangling link would otherwise
    create and lock the attacker-chosen path.

    Acquisition failures are normalised here so that every exit from this function
    is a documented type: contention is `ConcurrentWriterError`, a symlinked lock
    path is `CatalogPathError`, and every other `OSError` (EROFS, ENOSPC, EACCES,
    EISDIR, ENOTDIR ...) is `WriterLockError`. All of them are raised before the
    lock is held and therefore before anything is read or written.

    The station root is re-verified INSIDE the critical section, immediately
    before the caller's read-modify-write span. Validating it when the catalog
    was opened is not enough: a root is opened once and written through for the
    life of the process, so that check leaves a window as wide as the process.
    Under the lock the check is cheap, no other sanctioned writer can be midway
    through a write, and a failure aborts before `write_data` is reached.
    """
    lock_path = Path(catalog.path) / WRITER_LOCK_FILENAME

    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
    except OSError as exc:
        if exc.errno in _SYMLINKED_LOCK_ERRNOS:
            # Raised by `O_NOFOLLOW` when the lock path itself is a link, and by
            # `mkdir` when one lies above it. Both are the same hazard, so the
            # message names the condition rather than a specific component.
            raise CatalogPathError(
                f"refusing to follow a symlink at or above the writer lock path "
                f"{lock_path}; a lock taken on a link's target does not exclude "
                f"another writer on station root {catalog.path}",
            ) from exc

        raise WriterLockError(
            f"could not acquire the writer lock for station root {catalog.path}: "
            f"{exc}; nothing was read or written",
        ) from exc

    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ConcurrentWriterError(
                f"another process holds the writer lock for station root "
                f"{catalog.path}; exactly one writer per station root is required "
                f"because the write-verification read-back is not atomic",
            ) from exc

        try:
            _require_real_directory(Path(catalog.path))
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _group_by_type(records: Sequence[Data]) -> dict[type[Data], list[Data]]:
    """Group in submission order, mirroring `write_data`'s per-class chunking."""
    grouped: dict[type[Data], list[Data]] = {}

    for record in records:
        if isinstance(record, CustomData):
            raise TypeError(
                "pass raw records, not `CustomData` wrappers: the catalog wraps on "
                "read and unwraps on write, so a pre-wrapped record obscures which "
                "class was submitted",
            )

        grouped.setdefault(type(record), []).append(record)

    return grouped


def _require_non_decreasing(data_cls: type[Data], group: Sequence[Data]) -> None:
    for previous, current in pairwise(group):
        if current.ts_init < previous.ts_init:
            raise NonMonotonicWriteError(
                f"{data_cls.__name__} records must be non-decreasing in `ts_init` "
                f"before writing: found {previous.ts_init} followed by {current.ts_init}",
            )


def _fingerprint(record: Data) -> _Fingerprint:
    """Return a hashable, order-independent identity for one record's values.

    `to_dict` is safe to require: a type reaches the catalog only via
    `register_arrow`, whose encoder is built from it, and an unregistered type
    fails in the serializer before any write occurs.
    """
    values: dict[str, Any] = record.to_dict()

    return tuple(sorted(values.items(), key=lambda item: item[0]))


def _fingerprint_counts(
    catalog: ParquetDataCatalog,
    data_cls: type[Data],
    group: Sequence[Data],
) -> Counter[_Fingerprint]:
    """Count records already present in the `ts_init` window `group` will occupy.

    Comparing counts over a fixed window before and after the write is what makes
    the silent skip observable: a skipped write leaves the window unchanged.
    """
    start = min(record.ts_init for record in group)
    end = max(record.ts_init for record in group)

    return Counter(_fingerprint(record) for record in _read(catalog, data_cls, start=start, end=end))


def _read[RecordT: Data](
    catalog: ParquetDataCatalog,
    data_cls: type[RecordT],
    *,
    start: int | None = None,
    end: int | None = None,
) -> list[RecordT]:
    results: list[Any] = catalog.custom_data(cls=data_cls, start=start, end=end)
    records: list[RecordT] = []

    for result in results:
        record = result.data if isinstance(result, CustomData) else result

        if not isinstance(record, data_cls):
            raise TypeError(
                f"catalog at {catalog.path} returned {type(record).__name__} when "
                f"queried for {data_cls.__name__}",
            )

        records.append(record)

    return records


# ---------------------------------------------------------------------------
# `flock` local-filesystem startup assertion
# ---------------------------------------------------------------------------
#
# `flock` is unreliable over NFS (pre-v4 outright; v4 depending on lock-manager
# configuration), CIFS/SMB, sshfs and other network-backed mounts. Moving a
# station root onto shared storage would weaken "at most one writer per station
# root" with NO exception and NO log -- exactly the silent degradation this
# module exists to prevent. The precondition is not enforceable by `flock`
# itself, so it is asserted at startup instead, mirroring
# `breezy.ingest.gate.assert_cache_persistence_configured`.


class FilesystemLocality(str, Enum):
    """Whether a path's filesystem is one `flock` can be trusted on."""

    LOCAL = "LOCAL"
    NETWORK = "NETWORK"
    UNDETERMINED = "UNDETERMINED"


#: Mount types where `flock` does NOT reliably exclude writers on other hosts.
#:
#: Deliberately a targeted list, not "everything that is not a local disk".
#: Containers routinely run on ``overlay`` and ``tmpfs``, where `flock` is
#: perfectly correct locally; rejecting those would be a false positive that
#: gets the check disabled in frustration, which is worse than not having it.
#:
#: FUSE mounts are matched on their ``fuse.<subtype>`` name, so a network-backed
#: FUSE filesystem is caught while a local one (``fuse.gocryptfs``,
#: ``fuse.ntfs-3g``) is not; a bare ``fuse`` with no subtype is not rejected,
#: because it carries no evidence either way.
#:
#: ``gfs2`` and ``ocfs2`` are excluded on purpose: they are shared-BLOCK cluster
#: filesystems that implement cluster-wide `flock` correctly, so listing them
#: would reject a configuration that is in fact safe.
NETWORK_FILESYSTEM_TYPES: Final[frozenset[str]] = frozenset(
    {
        "9p",
        "afs",
        "afpfs",
        "beegfs",
        "ceph",
        "cifs",
        "coda",
        "davfs",
        "fuse.cephfs",
        "fuse.curlftpfs",
        "fuse.davfs2",
        "fuse.gcsfuse",
        "fuse.glusterfs",
        "fuse.rclone",
        "fuse.s3fs",
        "fuse.sshfs",
        "fuse.blobfuse",
        "fuse.blobfuse2",
        "glusterfs",
        "lustre",
        "ncpfs",
        "nfs",
        "nfs4",
        "orangefs",
        "pvfs2",
        "smb2",
        "smb3",
        "smbfs",
        "sshfs",
    }
)

# Linux-only. There is no stdlib call that returns a filesystem TYPE:
# `os.statvfs` carries no type field and CPython ships no `os.statfs`.
_MOUNTINFO_PATH: Final[Path] = Path("/proc/self/mountinfo")

# `mountinfo` octal-escapes space, tab, newline and backslash in path fields.
_MOUNTINFO_ESCAPE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\\(\d{3})")

# id, parent, maj:min, root, mount point, options -- then optional fields, then
# the `-` separator. So the separator can never appear before index 6.
_MOUNTINFO_MOUNT_POINT_FIELD: Final[int] = 4
_MOUNTINFO_MIN_SEPARATOR_FIELD: Final[int] = 6


class WriterLockFilesystemError(Exception):
    """Raised when a station root's filesystem cannot be trusted for `flock`.

    Either it is a known network-shared type, or its type could not be
    determined at all -- both fail closed, because "cannot verify" reported as
    "verified local" is precisely the silent degradation being guarded against.
    """


@dataclass(frozen=True, slots=True)
class FilesystemProbe:
    """What :func:`probe_filesystem` could determine about one path.

    Attributes
    ----------
    path : str
        The resolved path that was probed.
    mount_point : str or None
        The mount covering it, or ``None`` when nothing could be determined.
    fs_type : str or None
        That mount's filesystem type, e.g. ``"ext4"``, ``"overlay"``, ``"nfs4"``.
    locality : FilesystemLocality
    detail : str
        Human-readable provenance for the verdict, for logs and error messages.

    """

    path: str
    mount_point: str | None
    fs_type: str | None
    locality: FilesystemLocality
    detail: str


def probe_filesystem(path: Path | str) -> FilesystemProbe:
    """Determine whether `path` sits on a filesystem `flock` can be trusted on.

    Reads ``/proc/self/mountinfo`` and takes the longest mount point covering the
    RESOLVED path (later entries win a tie, because an over-mount shadows the
    mount beneath it). `path` need not exist yet: a mount point always does, so
    longest-prefix matching gives the same answer for a path about to be created.

    Never raises and never has side effects -- it is a query. The refusal is
    :func:`assert_writer_lock_filesystem_supported`'s job, so a caller that only
    wants to log what it is running on does not need a ``try``.
    """
    resolved = Path(path).resolve()

    try:
        raw = _MOUNTINFO_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        return FilesystemProbe(
            path=str(resolved),
            mount_point=None,
            fs_type=None,
            locality=FilesystemLocality.UNDETERMINED,
            detail=(
                f"{_MOUNTINFO_PATH} could not be read ({exc}); filesystem type "
                f"detection is Linux-only"
            ),
        )

    matched = _match_mount(raw, resolved)

    if matched is None:
        return FilesystemProbe(
            path=str(resolved),
            mount_point=None,
            fs_type=None,
            locality=FilesystemLocality.UNDETERMINED,
            detail=f"no mount point in {_MOUNTINFO_PATH} covers {resolved}",
        )

    mount_point, fs_type = matched
    is_network = fs_type in NETWORK_FILESYSTEM_TYPES

    return FilesystemProbe(
        path=str(resolved),
        mount_point=mount_point,
        fs_type=fs_type,
        locality=FilesystemLocality.NETWORK if is_network else FilesystemLocality.LOCAL,
        detail=f"{mount_point} is {fs_type} (per {_MOUNTINFO_PATH})",
    )


def assert_writer_lock_filesystem_supported(probe: FilesystemProbe) -> None:
    """Raise unless `probe` shows a filesystem `flock` can be trusted on.

    Call this **once at startup, per station root** -- it is deliberately not
    invoked from :func:`open_station_catalog` or :func:`write_records`, because
    import-time or per-write filesystem probing is hostile to tests and tooling::

        assert_writer_lock_filesystem_supported(
            probe_filesystem(station_catalog_path(base, venue, city)),
        )

    Takes the probe rather than the path, for the same reason
    :func:`breezy.ingest.gate.assert_cache_persistence_configured` takes a config
    object: every verdict is then reachable in a test without a real mount.

    Raises
    ------
    WriterLockFilesystemError
        If the root is on a known network filesystem, or if its filesystem could
        not be determined.

    """
    if probe.locality is FilesystemLocality.LOCAL:
        return

    if probe.locality is FilesystemLocality.NETWORK:
        raise WriterLockFilesystemError(
            f"station root {probe.path} is on {probe.fs_type} mounted at "
            f"{probe.mount_point}, where `flock` does not reliably exclude "
            f"writers on other hosts. The single-writer-per-station-root "
            f"invariant would degrade silently, so this configuration is "
            f"refused. Put settlement data on local storage.",
        )

    raise WriterLockFilesystemError(
        f"the filesystem backing station root {probe.path} could not be "
        f"determined ({probe.detail}), so `flock`'s single-host precondition "
        f"cannot be verified. Failing closed: an unverified precondition is not "
        f"reported as a satisfied one.",
    )


def _unescape_mountinfo(field: str) -> str:
    return _MOUNTINFO_ESCAPE_PATTERN.sub(lambda m: chr(int(m.group(1), 8)), field)


def _iter_mount_entries(raw: str) -> Iterator[tuple[str, str]]:
    """Yield `(mount_point, fs_type)` for every well-formed `mountinfo` line.

    Malformed lines are skipped rather than raising: an unparseable mount table
    must degrade to ``UNDETERMINED`` (which fails closed at the assertion), never
    to an exception out of a query function.
    """
    for line in raw.splitlines():
        fields = line.split(" ")

        try:
            separator = fields.index("-")
        except ValueError:
            continue

        if separator < _MOUNTINFO_MIN_SEPARATOR_FIELD or separator + 1 >= len(fields):
            continue

        yield _unescape_mountinfo(fields[_MOUNTINFO_MOUNT_POINT_FIELD]), fields[separator + 1]


def _match_mount(raw: str, resolved: Path) -> tuple[str, str] | None:
    """Return the longest mount point covering `resolved`, latest entry winning."""
    target = PurePosixPath(resolved)
    best: tuple[str, str] | None = None
    best_depth = -1

    for mount_point, fs_type in _iter_mount_entries(raw):
        candidate = PurePosixPath(mount_point)

        if candidate != target and candidate not in target.parents:
            continue

        depth = len(candidate.parts)

        if depth >= best_depth:
            best = (mount_point, fs_type)
            best_depth = depth

    return best
