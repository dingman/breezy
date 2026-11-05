"""MAKER-S2 S-5: one station-day per fresh child process, so memory is bounded BY CONSTRUCTION.

Allocator retention across station-days (glibc keeps freed heap; bench 4 grew ~170 MB per day even
with ``malloc_trim``) cannot grow past one day when each day starts in a new interpreter. The parent
keeps the preamble (its scan memo is handed to each child), the
sink, the progress log and the manifest; the child (``spawn``, never fork:
pyarrow and Nautilus threads are live in the parent) receives the picklable ``LoopContext`` with a
fresh ``CatalogSession`` under its own scratch dir, runs the SAME ``run_station_day`` into a local
``LoopOutput``, and sends back that output, the primary episodes in write order, its capture-file
manifest entries, and its own ``rss_end`` / ``ru_maxrss``. The parent replays those into the shared
``LoopOutput`` / ``EpisodeSink`` in the original order, so every output byte is unchanged.
Any child failure (exception, kill, OOM, timeout, unpicklable result) raises ``IsolatedDayFailed``
and so voids the run; one child at a time.
"""

from __future__ import annotations

import dataclasses
import multiprocessing as mp
import pickle
import shutil
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from scripts.analysis.maker_stage0_fill_events import Episode
from scripts.analysis.maker_stage0_release import release_free_heap
from scripts.analysis.maker_stage0_runio import peak_rss_bytes, read_rss_bytes
from scripts.analysis.maker_stage0_scoped_convert import scans_install, scans_snapshot
from scripts.analysis.maker_stage0_station_loop import (
    Key,
    LoopContext,
    LoopOutput,
    run_station_day,
)

if TYPE_CHECKING:  # annotation only: the pins module stays out of the loop's import closure
    from scripts.analysis.maker_stage0_pins import CatalogSliceManifest

__all__ = ["DAY_TIMEOUT_S", "DayMeasure", "DayRunner", "IsolatedDayFailed", "isolated_runner"]

DAY_TIMEOUT_S: Final[float] = 3600.0  # a bench day is ~200 s; the whole run is capped at 6 h
_JOIN_S: Final[float] = 60.0


class IsolatedDayFailed(RuntimeError):
    """A station-day child did not deliver a result: the run is void (CLI exit 3)."""


@dataclass(frozen=True)
class DayMeasure:
    """What one station-day reports to ``simulate``: events and the process's own memory."""

    n_events: int
    rss_bytes: int
    peak_bytes: int
    peak_delta_bytes: int


DayRunner = Callable[[LoopContext, Key, LoopOutput], DayMeasure]


class _Collector:
    """Stands in for the ``EpisodeSink`` inside the child: keeps episodes in write order."""

    def __init__(self) -> None:
        self.episodes: list[Episode] = []

    def write(self, episode: Episode) -> None:
        self.episodes.append(episode)


@dataclass(frozen=True)
class _DayReport:
    measure: DayMeasure
    out: LoopOutput
    episodes: list[Episode]
    manifest: CatalogSliceManifest | None  # the child's capture-file hashes, if the run keeps them


def _run_in_child(
    ctx: LoopContext, key: Key, work_dir: Path, want_episodes: bool, scans: dict[Any, Any]
) -> _DayReport:
    from scripts.analysis.maker_stage0_modes import peak_watch  # lazy: modes imports this module

    scans_install(scans)  # the parent's preflight scans (~70 s per large instance) are not redone
    base_peak = peak_rss_bytes()
    collector = _Collector() if want_episodes else None
    local = LoopOutput()
    child_ctx = dataclasses.replace(ctx, sink=collector, watch=peak_watch(peak_rss_bytes))
    n_events = run_station_day(child_ctx, key, local)
    ctx.session.close()
    shutil.rmtree(work_dir, ignore_errors=True)
    release_free_heap()
    peak = peak_rss_bytes()
    measure = DayMeasure(n_events, read_rss_bytes(), peak, max(0, peak - base_peak))
    episodes = collector.episodes if collector is not None else []
    return _DayReport(measure, local, episodes, ctx.session.manifest)


def _portable(exc: Exception) -> Exception | None:
    """``exc`` itself when it survives a pickle round trip, so typed in-day errors cross intact."""
    try:
        return pickle.loads(pickle.dumps(exc))  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001 - fall back to the name and text
        return None


def _child_main(
    conn: Connection,
    ctx: LoopContext,
    key: Key,
    work_dir: Path,
    want_episodes: bool,
    scans: dict[Any, Any],
) -> None:
    try:
        conn.send(("ok", _run_in_child(ctx, key, work_dir, want_episodes, scans)))
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed: the parent voids the run
        conn.send(("err", _portable(exc), type(exc).__name__, str(exc), traceback.format_exc()))
    finally:
        conn.close()


def _absorb(out: LoopOutput, local: LoopOutput) -> None:
    for variant, rows in local.rows.items():
        out.rows.setdefault(variant, []).extend(rows)
    out.seeds += local.seeds
    out.consumed |= local.consumed
    out.add_abstentions(local.abstentions)
    for station, parity in local.parity.items():
        out.parity.setdefault(station, parity)
    out.listing_abstained += local.listing_abstained
    for unit, counts in local.rounding.items():
        mine = out.rounding.setdefault(unit, dict.fromkeys(counts, 0))
        for name, n in counts.items():
            mine[name] += n
    out.unknown_delta += local.unknown_delta


def _recv(conn: Connection, box: list[Any]) -> None:
    try:
        box.append(conn.recv())
    except (EOFError, OSError) as exc:
        box.append(exc)


def _receive(proc: BaseProcess, conn: Connection, key: Key, timeout_s: float) -> _DayReport:
    """The child's result; the whole receive (not just its first byte) is bounded by the timeout."""
    where = f"{key[0]} {key[1].isoformat()}"
    box: list[Any] = []
    reader = threading.Thread(target=_recv, args=(conn, box), daemon=True)
    reader.start()
    reader.join(timeout_s)
    if reader.is_alive():  # killing the child closes its pipe end, which ends the blocked read
        proc.kill()
        reader.join(_JOIN_S)
        proc.join(_JOIN_S)
        raise IsolatedDayFailed(f"{where}: child timed out after {timeout_s:.0f} s")
    proc.join(_JOIN_S)
    message = box[0]
    if isinstance(message, BaseException):
        raise IsolatedDayFailed(
            f"{where}: child died without a result (exit code {proc.exitcode})"
        ) from message
    if message[0] == "err":
        _, exc, name, text, trace = message
        if exc is not None:  # typed in-day errors (MemoryAbort, LocalDayViolation, ...) unchanged
            exc.add_note(f"raised in the {where} child:\n{trace}")
            raise exc
        raise IsolatedDayFailed(f"{where}: child raised {name}: {text}\n{trace}")
    if proc.exitcode != 0:
        raise IsolatedDayFailed(f"{where}: child exit code {proc.exitcode} after its result")
    report: _DayReport = message[1]
    return report


def isolated_runner(work_root: Path, timeout_s: float = DAY_TIMEOUT_S) -> DayRunner:
    """A ``DayRunner`` that replays each station-day in its own spawned child."""
    spawn = mp.get_context("spawn")

    def run(ctx: LoopContext, key: Key, out: LoopOutput) -> DayMeasure:
        work_dir = work_root / f"day_{key[0]}_{key[1].isoformat()}"
        parent = ctx.session
        manifest = None if parent.manifest is None else type(parent.manifest)()
        # ``skipped`` is a planning-pass record (unreadable instances); a replay never reads it
        session = type(parent)(parent.capture_root, work_dir, manifest, parent.keep)
        child_ctx = dataclasses.replace(ctx, session=session, sink=None, watch=None)
        receiver, sender = spawn.Pipe(duplex=False)
        proc = spawn.Process(
            target=_child_main,
            args=(sender, child_ctx, key, work_dir, ctx.sink is not None, scans_snapshot()),
        )
        proc.start()
        sender.close()
        try:
            report = _receive(proc, receiver, key, timeout_s)
        finally:
            receiver.close()
            if proc.is_alive():
                proc.kill()
                proc.join(_JOIN_S)
            proc.close()
            shutil.rmtree(work_dir, ignore_errors=True)
        _absorb(out, report.out)
        if ctx.sink is not None:
            for episode in report.episodes:
                ctx.sink.write(episode)
        if parent.manifest is not None and report.manifest is not None:
            parent.manifest.merge(report.manifest)
        return report.measure

    return run
