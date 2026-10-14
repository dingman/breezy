"""MAKER-S2 WP6: run-directory I/O helpers (streaming sinks, manifests, small pure utilities).

Plan r4 delta (c) ``progress.jsonl`` carries no fill / rate / label field, (i)8 episodes stream to
``episodes.jsonl`` and are never accumulated, (i)9 the bench weight, (g) the fixed pin names. No
simulator, truth or Nautilus import here.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import json
import os
import resource
import sys
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final, TextIO

from breezy.adapters.polymarket_us.fees import taker_fee_coefficient_as_of
from scripts.analysis.maker_stage0_fill_events import CENTS, Episode
from scripts.analysis.maker_stage0_inputs import InputRefused, write_text_atomic

__all__ = [
    "PROGRESS_FIELDS",
    "EpisodeSink",
    "PositionFold",
    "PositionSeed",
    "ProgressLog",
    "heaviest",
    "import_closure",
    "jsonable",
    "peak_rss_bytes",
    "read_rss_bytes",
    "theta_for_day",
    "write_json",
]

#: The only keys a progress event may carry: no fill, rate, label or episode field (delta (c)).
PROGRESS_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "index",
        "of",
        "station",
        "climate_day",
        "status",
        "elapsed_s",
        "rss_bytes",
        "n_events",
        "rss_peak_delta_bytes",
        "peak_rss_bytes",
        "repeat_of_first",
    }
)
_NS: Final[int] = 10**9


def write_json(path: Path, payload: object) -> Path:
    return write_text_atomic(path, json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n")


def jsonable(obj: object) -> Any:
    """Plain-JSON view of dataclasses (via ``fields``), dates, mappings and sequences."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, Mapping):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in obj]
    return obj


def read_rss_bytes() -> int:
    """Current resident set size (``/proc/self/statm``); peak RSS where /proc is unavailable."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return peak_rss_bytes()


def peak_rss_bytes() -> int:
    unit = 1 if sys.platform == "darwin" else 1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit


def theta_for_day(day: dt.date) -> float:
    """The market's taker theta at D 00:00Z (mid-window), read from the venue fee schedule.

    D-1 16:50Z would fall inside the schedule's AMBIGUOUS window for the first replayable day
    (2026-09-17 00:00Z..17:00Z); no bid is placed before the 20:17Z vector, long after the drift.
    """
    midnight = dt.datetime.combine(day, dt.time(0, 0), tzinfo=dt.UTC)
    coefficient = taker_fee_coefficient_as_of(int(midnight.timestamp()) * _NS)
    if coefficient is None:
        raise InputRefused(f"no pinned taker fee coefficient for {day} (unpinned or ambiguous)")
    return float(coefficient)


def heaviest[K](weights: Mapping[K, int], n: int) -> list[K]:
    """The ``n`` heaviest keys by catalog bytes (outcome-blind); ties break by key order."""
    ranked = sorted(weights, key=lambda k: (-weights[k], str(k)))
    return ranked[: max(0, n)]


def import_closure(module: str, *, prefix: str, root: Path | None = None) -> set[str]:
    """Transitive ``prefix``-scoped import closure of ``module`` by AST (catches shared helpers)."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    seen: set[str] = set()
    todo = [module]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = base.joinpath(*name.split(".")).with_suffix(".py")
        if not path.is_file():
            continue
        for imported in _imports(ast.parse(path.read_text(encoding="utf-8")), name):
            if imported.startswith(prefix):
                todo.append(imported)
    return seen


def _is_type_checking(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _walk_runtime(node: ast.AST) -> Iterable[ast.AST]:
    """Every node that can execute: ``if TYPE_CHECKING:`` bodies never run, so they are skipped."""
    yield node
    for child in ast.iter_child_nodes(node):
        if _is_type_checking(child):
            continue
        yield from _walk_runtime(child)


def _imports(tree: ast.AST, here: str) -> Iterable[str]:
    for node in _walk_runtime(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


class ProgressLog:
    """One JSON line per station-day: input size, timing and memory only."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: TextIO = path.open("a", encoding="utf-8")
        self._start = time.monotonic()

    def write(self, event: Mapping[str, Any]) -> None:
        extra = set(event) - PROGRESS_FIELDS
        if extra:
            raise ValueError(f"progress events may not carry {sorted(extra)}")
        self._handle.write(json.dumps(dict(event), sort_keys=True) + "\n")
        self._handle.flush()

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def close(self) -> None:
        self._handle.close()


class EpisodeSink:
    """Append-only ``episodes.jsonl``; each episode is flushed before the next is pulled."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: TextIO = path.open("a", encoding="utf-8")
        self.count = 0

    def write(self, episode: Episode) -> None:
        self._handle.write(json.dumps(episode.to_dict(), sort_keys=True) + "\n")
        self._handle.flush()
        self.count += 1

    def close(self) -> None:
        self._handle.close()


@dataclasses.dataclass(frozen=True, slots=True)
class PositionSeed:
    """One posted position (station-day x rung) before truth: the row WP5 scores."""

    station: str
    climate_day: str
    unit_hypothesis: str
    rung_id: str
    bid: float
    filled_base: bool
    filled_stress: bool
    p_yes_point_live: float | None


@dataclasses.dataclass
class _RungState:
    bid: float
    p_yes: float | None
    t0_ns: int
    filled_base: bool = False
    filled_stress: bool = False


class PositionFold:
    """Folds streamed episodes into per-rung position seeds (constant memory per rung).

    The row of a filled position is its base-filled episode; an unfilled position is represented
    by its last placed episode (spec 6.9). Refused attempts never rested and carry no row.
    """

    def __init__(self, station: str, day: dt.date, unit: str) -> None:
        self._key = (station, day.isoformat(), unit)
        self._state: dict[str, _RungState] = {}

    def add(self, ep: Episode) -> None:
        if ep.refused_reason is not None:
            return
        base_fill, stress_fill = ep.filled_ns_base is not None, ep.filled_ns_stress is not None
        current = self._state.get(ep.rung_id)
        fresh = _RungState(ep.bid_cents / CENTS, ep.p_yes_point_live, ep.t0_ns)
        if current is None:
            current = self._state[ep.rung_id] = fresh
        elif (
            base_fill
            and not current.filled_base
            or (not current.filled_base and ep.t0_ns >= current.t0_ns)
        ):
            fresh.filled_base, fresh.filled_stress = current.filled_base, current.filled_stress
            current = self._state[ep.rung_id] = fresh
        current.filled_base = current.filled_base or base_fill
        current.filled_stress = current.filled_stress or stress_fill

    def seeds(self) -> list[PositionSeed]:
        station, day, unit = self._key
        return [
            PositionSeed(station, day, unit, rung, s.bid, s.filled_base, s.filled_stress, s.p_yes)
            for rung, s in sorted(self._state.items())
        ]
