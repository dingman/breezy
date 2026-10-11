"""TE-2 loss taxonomy: log readers, take attribution and the S0-A count gate (I/O)."""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.analysis.labeling.decision_link import (
    BridgeEvent,
    BridgeMatch,
    BridgeReport,
    BridgeUnmatched,
    bridge_decision,
    bridge_report,
    parse_log_line,
    read_log_events,
)
from breezy.analysis.labeling.epoch import C1Epoch, EpochReader, fill_epoch_class
from breezy.analysis.labeling.fill_source import FillRead, read_durable_fills
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.domain.instrument_leg import leg_of_symbol, symbol_of_instrument_id
from scripts.analysis.fq_loss_taxonomy_classify import k1b_flags
from scripts.analysis.fq_loss_taxonomy_stats import cluster_station_days

CHUNK_BYTES: Final = 1 << 20
VENUE: Final = "polymarket_us"
_TAKE_MARK: Final = b"'kind': 'Take'"
_DECISION_MARK: Final = b"SHADOW_DECISION"
_ANSI: Final = re.compile(r"\x1b\[[0-9;]*m")
_STATION: Final = re.compile(r"'station': '([^']+)'")
_CLIMATE_DAY: Final = re.compile(r"'climate_day': datetime\.date\((\d+), (\d+), (\d+)\)")
_RUNG: Final = re.compile(r"'rung_id': '([^']+)'")
_KIND: Final = re.compile(r"'kind': '(\w+)'")
#: The verified P6 counts (plan section 1): fills, instruments, no-legs, open-ended bands,
#: station-days, clusters, clusters without K1b, K1b fills, K1b station-days.
EXPECTED_S0A: Final = (25, 25, 0, 6, 14, 7, 6, 5, 3)


class UnclassifiedFillsStop(Exception):
    """A fill did not attribute to exactly one Take: the plan STOPs (S0-C)."""


class S0AStop(Exception):
    """An S0-A count differs from the verified P6 counts."""


class UnparseableInstrumentStop(S0AStop):
    """A durable fill's instrument id does not parse as a weather slug."""


@dataclass(frozen=True)
class S0ACounts:
    n_fills: int
    n_instruments: int
    n_no_leg: int
    n_open_ended: int
    n_station_days: int
    n_clusters: int
    n_clusters_excluding_k1b: int
    n_k1b_fills: int
    n_k1b_station_days: int


def s0a_counts(
    db_path: Path,
    terminal_climate_day: dt.date,
    fq_window_start: dt.date = dt.date(2026, 10, 1),
) -> S0ACounts:
    """Outcome-free counts from the durable fills: only instrument ids are read."""
    reads = read_durable_fills(db_path).require_clean()
    seen: list[tuple[str, str, dt.date, bool, bool]] = []
    instruments: set[str] = set()
    for fill in reads.fills:
        facts = bucket_facts_from_instrument_id(fill.instrument_id)
        if facts is None:
            raise UnparseableInstrumentStop(f"unparseable instrument id: {fill.instrument_id}")
        if facts.climate_day < fq_window_start:
            continue
        instruments.add(fill.instrument_id)
        is_no = leg_of_symbol(symbol_of_instrument_id(fill.instrument_id)) == "no"
        open_ended = facts.lower_f is None or facts.upper_f is None
        seen.append(
            (fill.venue_order_id, facts.settlement_station, facts.climate_day, is_no, open_ended)
        )
    keys = [(fid, station, day) for fid, station, day, _n, _o in seen]
    k1b = k1b_flags(keys, terminal_climate_day)
    days = {(station, day) for _f, station, day in keys}
    return S0ACounts(
        n_fills=len(seen),
        n_instruments=len(instruments),
        n_no_leg=sum(1 for *_r, is_no, _o in seen if is_no),
        n_open_ended=sum(1 for *_r, _n, open_ended in seen if open_ended),
        n_station_days=len(days),
        n_clusters=len(cluster_station_days(sorted(days))),
        n_clusters_excluding_k1b=len(cluster_station_days(k1b.in_scope_station_days)),
        n_k1b_fills=len(k1b.flagged_fill_ids),
        n_k1b_station_days=len(k1b.flagged_station_days),
    )


def s0a_gate(counts: S0ACounts) -> None:
    """Raise ``S0AStop`` unless the counts equal P6: 25/25/0/6 and 14 days, 7 clusters, 5 K1b."""
    got = tuple(getattr(counts, f.name) for f in dataclasses.fields(S0ACounts))
    if got != EXPECTED_S0A:
        raise S0AStop(f"S0-A counts {got} differ from the verified P6 counts {EXPECTED_S0A}")


@dataclass(frozen=True)
class AttributionResult:
    matches: tuple[BridgeMatch, ...]
    report: BridgeReport


def attribute_fills(
    fills: FillRead,
    log_files: Sequence[Path],
    *,
    data_root: Path,
    epoch_reader: EpochReader | None = None,
    family_id: str = "pm_us_crh_fq_v1",
    recalibration: str | None = None,
) -> AttributionResult:
    """S0-C: every fill must attribute to exactly one Take or the plan STOPs (unclassified).

    A POST_EPOCH fill makes ``bridge_decision`` raise ``BackfillRefused`` (not caught here).
    """
    reader = epoch_reader or C1Epoch(data_root, venue=VENUE, family_id=family_id)
    events = read_log_events(log_files)
    results: list[BridgeMatch | BridgeUnmatched] = []
    unclassified: list[str] = []
    for fill in fills.fills:
        outcome = fill_epoch_class(fill, reader)
        if outcome.epoch_class is None:
            unclassified.append(f"{fill.venue_order_id}: epoch {outcome.unresolved_cause}")
            continue
        result = bridge_decision(
            fill, events, epoch_class=outcome.epoch_class, recalibration=recalibration
        )
        if isinstance(result, BridgeUnmatched):
            unclassified.append(f"{fill.venue_order_id}: {result.reason}")
            continue
        results.append(result)
    if unclassified:
        raise UnclassifiedFillsStop(f"{len(unclassified)} UNCLASSIFIED: {unclassified}")
    return AttributionResult(
        tuple(m for m in results if isinstance(m, BridgeMatch)), bridge_report(results)
    )


def _marked_lines(path: Path, mark: bytes, chunk_size: int) -> Iterator[bytes]:
    """Lazily yield only the lines containing ``mark``; a line may span any number of chunks."""
    pending: list[bytes] = []
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            pieces = chunk.split(b"\n")
            last = pieces.pop()
            if pieces:
                pieces[0] = b"".join([*pending, pieces[0]])
                pending = []
                yield from (line for line in pieces if mark in line)
            pending.append(last)
    tail = b"".join(pending)
    if mark in tail:
        yield tail


def stream_take_events(path: Path, *, chunk_size: int = CHUNK_BYTES) -> Iterator[BridgeEvent]:
    """The ``Take`` bridge events of one node log, by a line-wise byte prefilter (lazy)."""
    for raw in _marked_lines(path, _TAKE_MARK, chunk_size):
        event = parse_log_line(raw.decode("utf-8", errors="replace"))
        if event is not None and event.kind == "take":
            yield event


@dataclass(frozen=True)
class PartitionEvent:
    station: str
    climate_day: dt.date
    rung_id: str
    kind: str


def iter_partition_events(path: Path) -> Iterator[PartitionEvent]:
    """Every decision line (Take AND Refuse) carrying a rung: the ladder-partition source."""
    for raw in _marked_lines(path, _DECISION_MARK, CHUNK_BYTES):
        text = _ANSI.sub("", raw.decode("utf-8", errors="replace"))
        station, day, rung, kind = (
            _STATION.search(text),
            _CLIMATE_DAY.search(text),
            _RUNG.search(text),
            _KIND.search(text),
        )
        if station and day and rung and kind:
            y, m, d = (int(g) for g in day.groups())
            yield PartitionEvent(station.group(1), dt.date(y, m, d), rung.group(1), kind.group(1))


def partition_union(
    events: Iterator[PartitionEvent],
) -> dict[tuple[str, dt.date], frozenset[str]]:
    """The union of rung ids per (station, climate day); the caller flags an incomplete union."""
    union: dict[tuple[str, dt.date], set[str]] = {}
    for event in events:
        union.setdefault((event.station, event.climate_day), set()).add(event.rung_id)
    return {key: frozenset(rungs) for key, rungs in union.items()}
