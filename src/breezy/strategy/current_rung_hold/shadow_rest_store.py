"""Per-station-day shadow resting-bid summary persistence (plan §5/§6 shadow
stage).

Byte-for-byte the same shape as ``monitor_store.write_monitor_summaries``/
``read_monitor_summaries`` (``monitor_store.py:225-267``): one parquet file
per run, atomic tempfile + ``os.replace``, filename stamped from the
caller's own clock reading, never rewriting an existing file. This is a
SIBLING artifact, not a reuse of the monitor's own catalog root or schema
-- the shadow decider (``resting_decider.py``) is pure and never touches
``PositionMonitor``/``monitor_records.py``, so its own summary needs its
own schema.

A compact tally, not a row-per-tick log (the offer tape already carries
that, additively, per ``OfferTapeRecord``'s ``shadow_rest_*`` fields):
one row per ``(station, climate_day, leg)`` key ever seen this run,
counting rests/re-prices/fill-eligible events and CANCEL reasons.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import pyarrow as pa
import pyarrow.parquet as pq

from breezy.strategy.current_rung_hold.resting_decider import REASON_CODES

__all__ = [
    "SHADOW_REST_SUMMARY_SCHEMA",
    "ShadowRestSummary",
    "read_shadow_rest_summaries",
    "write_shadow_rest_summaries",
]

_SUMMARY_FILE_PREFIX: Final[str] = "shadow_rest_summaries_"
_SUMMARY_FILE_SUFFIX: Final[str] = ".parquet"

#: One column per registered CANCEL/WAIT reason code, plus the tallies every
#: key accumulates. `key` is `"station|climate_day|leg"` (pipe-joined,
#: mirroring `PositionMarkRecord.reason_codes`'s comma-join precedent for a
#: composite field with no natural single delimiter-free column) -- read
#: back by :func:`read_shadow_rest_summaries`, never re-parsed elsewhere.
SHADOW_REST_SUMMARY_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("key", pa.string(), nullable=False),
        pa.field("station", pa.string(), nullable=False),
        pa.field("climate_day", pa.string(), nullable=False),
        pa.field("leg", pa.string(), nullable=False),
        pa.field("ticks_evaluated", pa.int64(), nullable=False),
        pa.field("rests", pa.int64(), nullable=False),
        pa.field("reprices", pa.int64(), nullable=False),
        pa.field("fill_eligible_events", pa.int64(), nullable=False),
        *(
            pa.field(f"cancel_{reason}", pa.int64(), nullable=False)
            for reason in sorted(REASON_CODES)
        ),
        pa.field("still_resting_at_stop", pa.bool_(), nullable=False),
    ]
)


@dataclass(slots=True)
class ShadowRestSummary:
    """One ``(station, climate_day, leg)``'s tally for one run.

    Mutated in place by the strategy wiring as ticks arrive
    (``record_tick``), then serialized read-only at ``on_stop``. Never
    constructs an order and carries no reference to any order/latch type --
    a pure accumulator over :class:`resting_decider.ShadowRestTickResult`.
    """

    station: str
    climate_day: str
    leg: str
    ticks_evaluated: int = 0
    rests: int = 0
    reprices: int = 0
    fill_eligible_events: int = 0
    cancels: dict[str, int] = field(default_factory=dict)
    still_resting_at_stop: bool = False

    @property
    def key(self) -> str:
        return f"{self.station}|{self.climate_day}|{self.leg}"

    def record_reason(self, reason: str | None) -> None:
        """Tally one tick's ``ShadowRestTickResult.reason``.

        ``"rest"``/``"reprice"`` increment their own counters; any member of
        :data:`REASON_CODES` increments ``cancels[reason]``; ``None`` (an
        unchanged RESTING tick) and any other value are no-ops.
        """
        if reason == "rest":
            self.rests += 1
        elif reason == "reprice":
            self.reprices += 1
        elif reason in REASON_CODES:
            self.cancels[reason] = self.cancels.get(reason, 0) + 1

    def to_dict(self) -> dict[str, object]:
        row: dict[str, object] = {
            "key": self.key,
            "station": self.station,
            "climate_day": self.climate_day,
            "leg": self.leg,
            "ticks_evaluated": self.ticks_evaluated,
            "rests": self.rests,
            "reprices": self.reprices,
            "fill_eligible_events": self.fill_eligible_events,
            "still_resting_at_stop": self.still_resting_at_stop,
        }
        for reason in sorted(REASON_CODES):
            row[f"cancel_{reason}"] = self.cancels.get(reason, 0)
        return row

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ShadowRestSummary:
        cancels = {
            reason: _require_int(payload, f"cancel_{reason}") for reason in sorted(REASON_CODES)
        }
        return cls(
            station=str(payload["station"]),
            climate_day=str(payload["climate_day"]),
            leg=str(payload["leg"]),
            ticks_evaluated=_require_int(payload, "ticks_evaluated"),
            rests=_require_int(payload, "rests"),
            reprices=_require_int(payload, "reprices"),
            fill_eligible_events=_require_int(payload, "fill_eligible_events"),
            cancels=cancels,
            still_resting_at_stop=bool(payload["still_resting_at_stop"]),
        )


def _require_int(payload: dict[str, object], key: str) -> int:
    """Raise, not coerce, on a non-``int`` column value -- schema drift
    (a column read back as something else) must fail loudly, matching
    ``monitor_records.py``'s own ``from_dict`` discipline."""
    value = payload[key]
    if not isinstance(value, int):
        raise TypeError(f"`{key}` must be an `int`, was {type(value).__name__}")
    return value


def write_shadow_rest_summaries(
    directory: Path,
    summaries: Sequence[ShadowRestSummary],
    *,
    now_ns: int,
) -> Path | None:
    """Write one run's `summaries` as a new parquet file under `directory`.

    Mirrors `monitor_store.write_monitor_summaries` exactly: never rewrites
    an existing file, atomic tempfile + `os.replace`, filename stamped from
    the caller's own clock reading. Returns `None` (no file written) when
    `summaries` is empty -- an idle run leaves no artifact rather than an
    empty parquet file.
    """
    if not summaries:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    rows = [summary.to_dict() for summary in summaries]
    table = pa.Table.from_pylist(rows, schema=SHADOW_REST_SUMMARY_SCHEMA)
    target = directory / f"{_SUMMARY_FILE_PREFIX}{_stamp(now_ns)}{_SUMMARY_FILE_SUFFIX}"

    fd, tmp_name = tempfile.mkstemp(
        dir=directory,
        prefix=f".{_SUMMARY_FILE_PREFIX}",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        os.close(fd)
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def read_shadow_rest_summaries(directory: Path) -> tuple[ShadowRestSummary, ...]:
    """Read every summary run under `directory`.

    An empty or absent directory returns no rows, never an error.
    """
    if not directory.exists():
        return ()
    out: list[ShadowRestSummary] = []
    for path in sorted(directory.glob(f"{_SUMMARY_FILE_PREFIX}*{_SUMMARY_FILE_SUFFIX}")):
        table = pq.read_table(path, schema=SHADOW_REST_SUMMARY_SCHEMA)
        for row in table.to_pylist():
            out.append(ShadowRestSummary.from_dict(row))
    return tuple(out)


def _stamp(now_ns: int) -> str:
    seconds, nanos = divmod(now_ns, 1_000_000_000)
    stamp = dt.datetime.fromtimestamp(seconds, tz=dt.UTC).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}{nanos:09d}Z"
