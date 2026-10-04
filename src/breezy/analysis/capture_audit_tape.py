"""AUT-1 WP5 stage 2b, W3: the recorder catalog as the audit's ``TapeIndex`` (design S2-R7).

The recorder's catalog (``<tape root>/data/<class>/<instrument_id>/<start>_<end>.parquet``, written
by Nautilus ``ParquetDataCatalog``) holds one directory per instrument. The instrument id is the
DIRECTORY NAME and the file's schema metadata, not a column (verified on a live catalog, so S2-R7's
``instrument_id.isin`` filter is expressed as a directory choice). The columns read are only those
the legs need: ``ts_event`` for the index, and ``bid_price``/``ask_price`` (quote) or
``bid_price_<k>``/``ask_price_<k>``/``*_size_<k>`` (Depth10) for a row body. Prices and sizes are
fixed-point ``fixed_size_binary(16)`` little-endian signed integers scaled by ``10**16``; they are
rendered at the file's own ``price_precision`` / ``size_precision`` so a row equals the capture
``FrameCopy.frame_body`` string for string.

Loaded EAGERLY at construction: the sorted ``ts_event`` array of every instrument and kind inside
``[day - FLUSH_WINDOW_S, day + 1 day + FLUSH_WINDOW_S]`` is read there, so an unreadable file is
``AuditInputError("tape_unreadable")`` inside ``gather_inputs`` and never a surprise in a leg
(B7). Row BODIES are read lazily, but a failure then is the same error. Scans use
``pyarrow.dataset`` with ``batch_size=65536``, one fragment and one batch read-ahead, no threads,
and ``to_batches()`` only, never ``to_table()``.

Files are pruned by the ``<start>_<end>`` ISO stamps in their names, which are ``ts_init`` stamps: a
row's ``ts_event`` never exceeds its ``ts_init`` (so a file ending before the window holds no row of
it), and a file may start up to ``_LAG_MARGIN_S`` after the window and still hold a late-delivered
row of it. Read-only; no write site.
"""

import datetime as dt
import re
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from breezy.analysis.capture_audit_model import FLUSH_WINDOW_S, AuditInputError

__all__ = ["RecorderCatalogTape", "catalog_instruments"]

QUOTE_DIR: Final[str] = "quote_tick"
DEPTH_DIR: Final[str] = "order_book_depths"
_DATA_DIR: Final[str] = "data"
_NS: Final[int] = 1_000_000_000
_DAY_NS: Final[int] = 86_400 * _NS
_LAG_MARGIN_S: Final[int] = 6 * 3600
_FIXED_SCALE: Final[int] = 16
_BATCH_ROWS: Final[int] = 65_536
_LEVELS: Final[int] = 10
_FILE_RE: Final[re.Pattern[str]] = re.compile(
    r"\A(?P<a>\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-\d{9})Z_(?P<b>\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-\d{9})Z"
    r"\.parquet\Z"
)
_QUOTE_COLUMNS: Final[tuple[str, ...]] = ("ts_event", "bid_price", "ask_price")
_DEPTH_COLUMNS: Final[tuple[str, ...]] = (
    "ts_event",
    *(
        f"{side}_{kind}_{k}"
        for k in range(_LEVELS)
        for side in ("bid", "ask")
        for kind in ("price", "size")
    ),
)


def _unreadable(detail: str) -> AuditInputError:
    return AuditInputError("tape_unreadable", detail)


def _stamp_ns(text: str) -> int:
    whole, _, nanos = text.rpartition("-")
    moment = dt.datetime.strptime(whole, "%Y-%m-%dT%H-%M-%S").replace(tzinfo=dt.UTC)
    return int(moment.timestamp()) * _NS + int(nanos)


def _span(path: Path) -> tuple[int, int] | None:
    match = _FILE_RE.fullmatch(path.name)
    if match is None:
        return None
    try:
        return _stamp_ns(match["a"]), _stamp_ns(match["b"])
    except ValueError:
        return None


def _day_window(day: dt.date) -> tuple[int, int]:
    start = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS
    return start - FLUSH_WINDOW_S * _NS, start + _DAY_NS + FLUSH_WINDOW_S * _NS


def _files(kind_dir: Path, lo_ns: int, hi_ns: int) -> list[Path]:
    """The instrument directory's parquet files that can hold a row with ``ts_event`` in
    ``[lo_ns, hi_ns]``, oldest first."""
    try:
        names = sorted(kind_dir.iterdir())
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise _unreadable(type(exc).__name__) from None
    keep: list[Path] = []
    for path in names:
        span = _span(path)
        if span is not None and span[1] >= lo_ns and span[0] <= hi_ns + _LAG_MARGIN_S * _NS:
            keep.append(path)
    return keep


def catalog_instruments(catalog_root: Path, day: dt.date) -> frozenset[str]:
    """Every instrument with a quote or Depth10 file that can hold a row of ``day``."""
    lo, hi = _day_window(day)
    found: set[str] = set()
    for kind in (QUOTE_DIR, DEPTH_DIR):
        base = catalog_root / _DATA_DIR / kind
        try:
            members = [p for p in base.iterdir() if p.is_dir()]
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _unreadable(type(exc).__name__) from None
        found.update(p.name for p in members if _files(p, lo, hi))
    return frozenset(found)


def _timestamps(files: list[Path], lo_ns: int, hi_ns: int) -> array[int]:
    out: array[int] = array("Q")
    for path in files:
        try:
            with pq.ParquetFile(path) as handle:
                column = handle.read(columns=["ts_event"]).column("ts_event")
        except (OSError, pa.ArrowException, KeyError) as exc:
            raise _unreadable(type(exc).__name__) from None
        out.extend(t for t in column.to_pylist() if lo_ns <= t <= hi_ns)
    return array("Q", sorted(out))


def _precisions(path: Path) -> tuple[int, int]:
    try:
        meta = pq.read_schema(path).metadata or {}
        return int(meta[b"price_precision"]), int(meta[b"size_precision"])
    except (OSError, pa.ArrowException, KeyError, ValueError) as exc:
        raise _unreadable(type(exc).__name__) from None


def _fixed(raw: bytes, precision: int) -> str:
    value = Decimal(int.from_bytes(raw, "little", signed=True)).scaleb(-_FIXED_SCALE)
    return f"{value:.{precision}f}"


def _quote_body(row: Mapping[str, Any], prec: tuple[int, int]) -> dict[str, Any]:
    return {
        "ask": _fixed(row["ask_price"], prec[0]),
        "bid": _fixed(row["bid_price"], prec[0]),
        "ts_event": int(row["ts_event"]),
    }


def _levels(row: Mapping[str, Any], side: str, prec: tuple[int, int]) -> list[list[str]]:
    levels: list[list[str]] = []
    for k in range(_LEVELS):
        size = int.from_bytes(row[f"{side}_size_{k}"], "little", signed=True)
        if size > 0:
            levels.append(
                [
                    _fixed(row[f"{side}_price_{k}"], prec[0]),
                    _fixed(row[f"{side}_size_{k}"], prec[1]),
                ]
            )
    return levels


def _depth_body(row: Mapping[str, Any], prec: tuple[int, int]) -> dict[str, Any]:
    return {
        "ts_event": int(row["ts_event"]),
        "bids": _levels(row, "bid", prec),
        "asks": _levels(row, "ask", prec),
    }


class _Series:
    """One instrument and kind: its files and its sorted ``ts_event`` array (the eager index)."""

    __slots__ = ("files", "hi", "lo", "precision", "ts")

    def __init__(self, files: list[Path], lo_ns: int, hi_ns: int) -> None:
        self.files, self.lo, self.hi = files, lo_ns, hi_ns
        self.ts = _timestamps(files, lo_ns, hi_ns) if files else array("Q")
        self.precision = _precisions(files[0]) if files else (2, 2)

    def rows(self, columns: tuple[str, ...], lo_ns: int, hi_ns: int) -> Iterator[Mapping[str, Any]]:
        """Raw rows with ``ts_event`` in ``[lo, hi)``, file order."""
        if not self.files:
            return
        lo_ns, hi_ns = max(lo_ns, self.lo), min(hi_ns, self.hi + 1)
        field = ds.field("ts_event")
        try:
            scanner = ds.dataset([str(p) for p in self.files], format="parquet").scanner(
                columns=list(columns),
                filter=(field >= lo_ns) & (field < hi_ns),
                batch_size=_BATCH_ROWS,
                batch_readahead=1,
                fragment_readahead=1,
                use_threads=False,
            )
            for batch in scanner.to_batches():
                yield from batch.to_pylist()
        except (OSError, pa.ArrowException, KeyError) as exc:
            raise _unreadable(type(exc).__name__) from None


class RecorderCatalogTape:
    """The recorder catalog as a ``TapeIndex``, scoped to one day's instruments.

    Only ``[day 00:00 - 61 s, day + 1 00:00 + 61 s]`` is indexed: a query outside it finds nothing.
    Every returned row has the ``FrameCopy.frame_body`` shape: ``{"ask", "bid", "ts_event"}`` for a
    quote and ``{"ts_event", "bids", "asks"}`` (populated levels, ``[price, size]`` strings) for a
    Depth10."""

    def __init__(self, catalog_root: Path, day: dt.date, instruments: frozenset[str]) -> None:
        lo, hi = _day_window(day)
        self._lo, self._hi = lo, hi
        self._quotes: dict[str, _Series] = {}
        self._depths: dict[str, _Series] = {}
        for instrument in sorted(instruments):
            for kind, store in ((QUOTE_DIR, self._quotes), (DEPTH_DIR, self._depths)):
                files = _files(catalog_root / _DATA_DIR / kind / instrument, lo, hi)
                if files:
                    store[instrument] = _Series(files, lo, hi)

    @property
    def instruments(self) -> frozenset[str]:
        return frozenset(self._quotes) | frozenset(self._depths)

    def active_instruments(self, start_ns: int, end_ns: int) -> frozenset[str]:
        """The instruments with a quote or Depth10 row whose ``ts_event`` is in ``[start, end)``."""
        active: set[str] = set()
        for store in (self._quotes, self._depths):
            for instrument, series in store.items():
                at = bisect_left(series.ts, start_ns)
                if at < len(series.ts) and series.ts[at] < end_ns:
                    active.add(instrument)
        return frozenset(active)

    def lookup(
        self, frame_kind: str, instrument_id: str, ts_event: int
    ) -> Mapping[str, Any] | None:
        store = {"quote": self._quotes, "depth10": self._depths}.get(frame_kind)
        series = None if store is None else store.get(instrument_id)
        if series is None:
            return None
        at = bisect_left(series.ts, ts_event)
        if at >= len(series.ts) or series.ts[at] != ts_event:
            return None
        rows = list(self._rows(frame_kind, series, ts_event, ts_event + 1))
        return rows[-1] if rows else None

    def quote_rows(
        self, instrument_id: str, start_ns: int, end_ns: int
    ) -> Iterable[Mapping[str, Any]]:
        series = self._quotes.get(instrument_id)
        return () if series is None else self._rows("quote", series, start_ns, end_ns)

    def depth_rows(
        self, instrument_id: str, start_ns: int, end_ns: int
    ) -> Iterable[Mapping[str, Any]]:
        series = self._depths.get(instrument_id)
        return () if series is None else self._rows("depth10", series, start_ns, end_ns)

    def best_ask_at(self, instrument_id: str, ts_ns: int) -> float | None:
        """The lowest populated Depth10 ask of the latest row at or before ``ts_ns``, or None."""
        series = self._depths.get(instrument_id)
        if series is None:
            return None
        at = bisect_right(series.ts, ts_ns)
        if at == 0:
            return None
        latest = series.ts[at - 1]
        rows = list(self._rows("depth10", series, latest, latest + 1))
        asks = rows[-1]["asks"] if rows else []
        return min(float(price) for price, _size in asks) if asks else None

    @staticmethod
    def _rows(kind: str, series: _Series, lo_ns: int, hi_ns: int) -> Iterator[Mapping[str, Any]]:
        columns = _QUOTE_COLUMNS if kind == "quote" else _DEPTH_COLUMNS
        build = _quote_body if kind == "quote" else _depth_body
        for row in series.rows(columns, lo_ns, hi_ns):
            yield build(row, series.precision)
