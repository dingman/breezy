"""The label-run entrypoint (AUT-2 r7 WP6 and WP8).

Modes (all production writes refuse outside ``breezy-label-outcomes.service``, plan Q1):

* default: ``run_unit`` takes the studies flock, applies the memory gate, runs ``run_labels`` and,
  after a marker, the proof-window hook. Its production deps (planner, settlement catalog) are wired
  by the coordinator at promotion; until then the default mode refuses (``reason=not_wired``).
* ``--record-skip``: the lock-skip journal (L1).
* ``--canary`` and ``--proof-window``: WP8.
* ``--measure-peak --output-root <dir>``: a measurement that writes only under ``<dir>``.

``run_canary`` is the canary path of section 3.8: on a UTC day with zero real fills it writes the
deterministic synthetic canary fills and labels them with the real FQ Scorer into
``derived/labels_canary/``. It reads no venue positions and never opens ``labels/``, the exec
store's ledger for anything but the day's fill count, or any reconciliation input. Its only writes
are ``derived/canary/`` and ``derived/labels_canary/`` (the studies flock is the wrapper's).

``run_proof_window`` evaluates the window rules over per-day evidence and writes the write-once
artefact; the store-backed evidence reader is ``proof_source``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import os
import sqlite3
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.attribution import Attribution
from breezy.analysis.labeling.constants import (
    LABEL_FLOCK_WAIT_S,
    MEASURE_MEMAVAILABLE_FLOOR_GIB,
)
from breezy.analysis.labeling.fill_source import (
    FillStoreCorruption,
    net_by_base_slug,
    read_durable_fills,
)
from breezy.analysis.labeling.fq_scorer import ForecastQuantileLadderScorer, FqFillInput
from breezy.analysis.labeling.label_core import AlertBatch, LabelRunDeps, RunResult, run_labels
from breezy.analysis.labeling.memory_gate import (
    Aut6Reading,
    HoldJournalWriteFailed,
    label_slot_held,
    record_hold,
)
from breezy.analysis.labeling.proof_window import (
    DayEvidence,
    evaluate_window,
)
from breezy.analysis.labeling.skip_journal import (
    SkipJournalWriteFailed,
    record_skip,
    run_record_skip,
    skip_is_critical,
    utc_day,
    write_json_once,
)
from breezy.domain.instrument_leg import base_symbol_of, leg_of_symbol, symbol_of_instrument_id
from breezy.persistence.autonomy.canary_store import (
    CANARY_ID_PREFIX,
    LABELS_CANARY_DIR,
    CanaryFill,
    read_canary_fills,
    write_canary_fills,
)
from breezy.persistence.autonomy.capture_reader import DecisionView, OrderLinkView
from breezy.persistence.autonomy.label_store import (
    LabelRow,
    LabelStoreError,
    MarkerCorrupt,
    read_newest_marker,
    write_labels,
)
from breezy.persistence.autonomy.paths import date_component
from breezy.persistence.autonomy.single_read import SingleReadRefused
from breezy.persistence.autonomy.wire import WireRefused
from breezy.runtime.autonomy_sandbox.wal_snapshot import SnapshotReadFailure, exec_snapshot

__all__ = [
    "LABEL_UNIT",
    "PROOF_DIR",
    "WP7_ACTIVE",
    "CanaryRefused",
    "CanaryRun",
    "ExecSnapshotUnavailable",
    "MeasureSeams",
    "Paths",
    "StudiesFlock",
    "UnitContext",
    "UnitWiring",
    "canary_reconciles",
    "default_paths",
    "main",
    "measure_peak",
    "read_cgroup_memory_peak",
    "run_canary",
    "run_proof_window",
    "run_unit",
    "snapshot_exec_db",
    "synthesize_canary_fills",
]

LABEL_UNIT: Final = "breezy-label-outcomes"
#: Flipped by a reviewed change when the AUT-2 WP7 C1 switch-over activates; until then the
#: proof window refuses to start (plan section 6, Q4).
WP7_ACTIVE: Final = False
_RC_REFUSED: Final = 2
_RC_DELIVERY: Final = 4
_GIB: Final = 1024**3

PROOF_DIR: Final[tuple[str, ...]] = ("evidence", "aut2_live_proof")
_PROOF_SCHEMA: Final = "aut2_live_proof/v1"
_NS_PER_H: Final = 3_600_000_000_000
_NS_PER_S: Final = 1_000_000_000
_RC_USAGE: Final = 2
_RC_FAILED: Final = 1
_SYNTHETIC_SHA: Final = "c" * 64
_CANARY_STATION: Final = "LAX"
_BUCKET_SLUG: Final = "tc-temp-laxhigh-{day}-gte89lt90f"
_VENUE_SUFFIX: Final = ".POLYMARKET_US"


class CanaryRefused(Exception):
    """The canary path refuses to run (a real fill exists that day)."""


@dataclass(frozen=True)
class CanaryRun:
    """The canary path's result. ``real_fills`` is always 0 and ``live_fill_check`` vacuous."""

    canary_fills: int
    rows: tuple[LabelRow, ...]
    labelled_with_p: bool
    reconciliation_passes: bool
    real_fills: int = 0
    live_fill_check: str = "vacuous"


def _day_start_ns(day: str) -> int:
    date = dt.date.fromisoformat(date_component(day))
    return int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.UTC).timestamp()) * _NS_PER_S


def synthesize_canary_fills(*, venue: str, family_id: str, day: str) -> tuple[CanaryFill, ...]:
    """The deterministic synthetic set: one YES and one NO entry on a synthetic bucket."""
    slug = _BUCKET_SLUG.format(day=date_component(day))
    ts = _day_start_ns(day) + 6 * _NS_PER_H
    legs = (
        ("yes", f"{slug}{_VENUE_SUFFIX}", Decimal("0.40")),
        ("no", f"{slug}^no{_VENUE_SUFFIX}", Decimal("0.55")),
    )
    return tuple(
        CanaryFill(
            venue_order_id=f"{CANARY_ID_PREFIX}vo-{venue}-{day}-{side}",
            client_order_id=f"{CANARY_ID_PREFIX}O-{day}-{side}",
            instrument_id=instrument,
            order_side="BUY",
            qty=Decimal(1),
            cost=cost,
            fee=Decimal("0.03"),
            ts_event=ts + index,
            trade_id=f"{CANARY_ID_PREFIX}T-{day}-{side}",
            decision_id=f"{CANARY_ID_PREFIX}dec-{day}-{side}",
            family_id=family_id,
            station=_CANARY_STATION,
            climate_day=day,
            rung_id="89_90",
            side=side,
            p_hat="0.62",
            p_hat_raw="0.62",
        )
        for index, (side, instrument, cost) in enumerate(legs)
    )


def _durable(fill: CanaryFill) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=fill.venue_order_id,
        client_order_id=fill.client_order_id,
        instrument_id=fill.instrument_id,
        order_side=fill.order_side,
        cumulative_qty=fill.qty,
        cumulative_cost=fill.cost,
        cumulative_fee=fill.fee,
        fee_reconciled=True,
        ts_event=fill.ts_event,
        trade_id=fill.trade_id,
    )


def _attribution(fill: CanaryFill) -> Attribution:
    decision = DecisionView(
        schema="capture_decision/v2",
        decision_id=fill.decision_id,
        family_id=fill.family_id,
        node_boot_id=f"{CANARY_ID_PREFIX}boot",
        build_sha="0" * 40,
        registry_seq=0,
        drill=False,
        source="canary",
        kind="Take",
        reason="",
        eval_ns=fill.ts_event - 10,
        eval_seq=0,
        wall_ns=fill.ts_event - 10,
        ts_ns=fill.ts_event - 10,
        station=fill.station,
        climate_day=fill.climate_day,
        rung_id=fill.rung_id,
        side=fill.side,
        instrument_id=fill.instrument_id,
        ask_px=str(fill.cost),
        depth_ref="",
        quote_ref="",
        p_hat=fill.p_hat,
        p_hat_raw=fill.p_hat_raw,
        p_lower="0.5",
        p_upper="0.7",
        ev_net="0",
        margin="0",
        forecast_input_ref="",
        artefact_sha256=_SYNTHETIC_SHA,
        manifest_sha256=_SYNTHETIC_SHA,
    )
    link = OrderLinkView(
        decision_id=fill.decision_id,
        client_order_id=fill.client_order_id,
        venue_order_id_sha256=_SYNTHETIC_SHA,
        instrument_id=fill.instrument_id,
        side="BUY",
        qty=str(fill.qty),
        px=str(fill.cost),
        time_in_force="IOC",
        intent_fingerprint=_SYNTHETIC_SHA,
        ts_ns=fill.ts_event,
        source="canary",
    )
    return Attribution(
        family_id=fill.family_id,
        decision=decision,
        link=link,
        drill=False,
        voided_pair=False,
        alerts=(),
    )


class _NoSettlement:
    """A canary is never settled: the scorer sees no record and leaves the row pending."""

    def record(self, station: str, climate_day: dt.date) -> None:
        return None


def _signed(fill: CanaryFill) -> Decimal:
    """YES BUY +q, NO BUY -q (the venue nets a NO holding as short YES); SELLs reverse."""
    sign = Decimal(1) if fill.side == "yes" else Decimal(-1)
    return sign * fill.qty * (Decimal(1) if fill.order_side == "BUY" else Decimal(-1))


def canary_reconciles(fills: Sequence[CanaryFill]) -> bool:
    """The canary ledger net equals a synthetic snapshot computed independently, per base slug."""
    ledger = net_by_base_slug(_durable(f) for f in fills)
    snapshot: dict[str, Decimal] = {}
    for fill in fills:
        symbol = symbol_of_instrument_id(fill.instrument_id)
        leg_of_symbol(symbol)
        slug = base_symbol_of(symbol)
        snapshot[slug] = snapshot.get(slug, Decimal(0)) + _signed(fill)
    return ledger == snapshot


def run_canary(
    *,
    data_root: Path,
    venue: str,
    family_id: str,
    day: str,
    now_ns: int,
    real_fill_count: int,
) -> CanaryRun:
    """Write and label the day's canary; refuses when any real fill exists that UTC day."""
    if real_fill_count != 0:
        raise CanaryRefused("a canary is written only on a UTC day with zero real fills")
    synthetic = synthesize_canary_fills(venue=venue, family_id=family_id, day=day)
    write_canary_fills(data_root, venue, day, synthetic)
    fills = read_canary_fills(data_root, venue, day)
    inputs = [
        FqFillInput(
            fill=_durable(f),
            attribution=_attribution(f),
            scheduled_release_at_ns=f.ts_event + 10 * _NS_PER_H,
            canary=True,
        )
        for f in fills
    ]
    scorer = ForecastQuantileLadderScorer(now_ns=now_ns)
    rows = scorer.label(dt.date.fromisoformat(day), inputs, _NoSettlement())
    write_labels(data_root, family_id, rows, now_ns=now_ns, labels_dir=LABELS_CANARY_DIR)
    return CanaryRun(
        canary_fills=len(fills),
        rows=rows,
        labelled_with_p=len(rows) == len(fills) and all(r.p_at_decision is not None for r in rows),
        reconciliation_passes=canary_reconciles(fills),
    )


def run_proof_window(
    data_root: Path,
    *,
    start_day: str,
    days: Sequence[DayEvidence],
    capture_epoch_start_ns: int | None,
    wp7_active: bool,
    hold_days: Sequence[str],
) -> Path:
    """Evaluate the window and write ``window_<start>_<end>.json`` once; refusal writes nothing."""
    result = evaluate_window(
        start_day=start_day,
        days=days,
        capture_epoch_start_ns=capture_epoch_start_ns,
        wp7_active=wp7_active,
        hold_days=hold_days,
    )
    end = result.end_day or start_day
    body = {
        "schema": _PROOF_SCHEMA,
        "start_day": start_day,
        "window_start_day": result.start_day,
        "end_day": end,
        "complete": result.complete,
        "qualifying_days": result.qualifying_days,
        "real_fills": result.real_fills,
        "no_leg_fills": result.no_leg_fills,
        "exit_fills": result.exit_fills,
        "canary_fills": result.canary_fills,
        "restarted_on": list(result.restarted_on),
        "days": [
            {
                "utc_day": d.utc_day,
                "status": d.status.value,
                "reasons": list(d.reasons),
                "real_fills": d.real_fills,
                "canary_fills": d.canary_fills,
                "live_fill_check": d.live_fill_check,
                **_evidence_fields(d.evidence),
            }
            for d in result.days
        ],
        "marker_files": [d.evidence.marker_file for d in result.days],
        "invocation_ids": [d.evidence.invocation_id for d in result.days],
    }
    return write_json_once(data_root, (*PROOF_DIR, f"window_{start_day}_{end}.json"), body)


def _evidence_fields(ev: DayEvidence) -> dict[str, object]:
    """Every section 6 per-day field the evidence carries. The file is write-once, so none may be
    dropped; a verdict that is absent is recorded as null."""
    return {
        "final_labelled": ev.final_labelled,
        "unresolved": ev.unresolved,
        "missing_label": ev.missing_label,
        "non_c1_post_epoch_count": ev.non_c1_post_epoch_count,
        "non_c1_entry_rows": ev.non_c1_entry_rows,
        "p_null_count": ev.p_null_count,
        "daily_recon": None if ev.daily_recon is None else ev.daily_recon.value,
        "daily_recon_verdict_id": ev.daily_recon_verdict_id,
        "post_stop": None if ev.post_stop is None else ev.post_stop.value,
        "post_stop_verdict_id": ev.post_stop_verdict_id,
        "intraday_non_pass_ids": list(ev.intraday_non_pass_ids),
        "position_mismatches_transient": ev.position_mismatches_transient,
        "max_label_lag_h": format(ev.max_label_lag_h, ".3f"),  # canonical JSON has no floats
        "fills_never_position_compared": ev.fills_never_position_compared,
        "canary_labelled_with_p": ev.canary_labelled_with_p,
        "canary_recon_passes": ev.canary_recon_passes,
        "no_leg_fills": ev.no_leg_fills,
        "exit_fills": ev.exit_fills,
    }


# -- unit context, paths and the snapshot read -----------------------------------------------------


@dataclass(frozen=True)
class UnitContext:
    """Whether this process runs inside ``breezy-label-outcomes.service`` (plan Q1)."""

    invocation_id: str | None
    cgroup_path: str

    @staticmethod
    def from_environment(env: Mapping[str, str], proc_cgroup_text: str) -> UnitContext:
        path = ""
        for line in proc_cgroup_text.splitlines():
            if line.startswith("0::"):
                path = line[3:].strip()
        return UnitContext(env.get("INVOCATION_ID") or None, path)

    @staticmethod
    def current() -> UnitContext:
        try:
            text = Path("/proc/self/cgroup").read_text(encoding="utf-8")
        except OSError:
            text = ""
        return UnitContext.from_environment(os.environ, text)

    def is_label_unit(self) -> bool:
        return bool(self.invocation_id) and (
            PurePosixPath(self.cgroup_path).name == f"{LABEL_UNIT}.service"
        )


@dataclass(frozen=True)
class Paths:
    data_root: Path
    exec_db: Path
    snapshot_cache: Path
    studies_lock_name: str = "breezy-studies.lock"


def default_paths(home: Path) -> Paths:
    root = home / ".local" / "share" / "breezy"
    return Paths(
        root, root / "state" / "exec_polymarket_us.sqlite", root / "cache" / "label_run_snapshot"
    )


class ExecSnapshotUnavailable(Exception):
    """The exec store could not be snapshotted; the run fails (exit 1), it never guesses."""


@contextmanager
def snapshot_exec_db(data_root: Path, cache_dir: Path) -> Iterator[Path]:
    """A read-only copy of the exec store taken WITHOUT the intent flock (``take_flock=False``)."""
    # the snapshot reader requires the cache directory AND its parent to be exactly 0700
    cache_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache_dir.mkdir(mode=0o700, exist_ok=True)
    with exec_snapshot(cache_dir=cache_dir, take_flock=False, data_root=data_root) as outcome:
        if isinstance(outcome, SnapshotReadFailure):
            raise ExecSnapshotUnavailable(outcome.reason.value)
        yield outcome.path


class StudiesFlock:
    """The studies flock taken in process (E7_STUDIES_LOCK): a bounded, polled ``LOCK_EX``."""

    def __init__(self, path: Path, *, poll_s: float = 1.0) -> None:
        self._path = path
        self._poll_s = poll_s
        self._fd: int | None = None

    def acquire(self, wait_s: float) -> bool:
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        deadline = time.monotonic() + wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    return False
                time.sleep(self._poll_s)
                continue
            self._fd = fd
            return True

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


class Lock(Protocol):
    def acquire(self, wait_s: float) -> bool: ...

    def release(self) -> None: ...


# -- the unit run ---------------------------------------------------------------------------------

ProofHook = Callable[[Path, int], None]


def _since_ns(data_root: Path) -> int:
    marker = read_newest_marker(data_root)
    return 0 if marker is None else marker.written_at_ns


def _skip(deps: LabelRunDeps, slot_ns: int) -> RunResult:
    try:
        record = record_skip(
            deps.data_root,
            LABEL_UNIT,
            "lock",
            deps.now_ns,
            slot_ns=slot_ns,
            since_ns=_since_ns(deps.data_root),
        )
    except SkipJournalWriteFailed:
        return RunResult(1, lines=(f"AUT2 SKIP_JOURNAL_WRITE_FAILED unit={LABEL_UNIT}",))
    except (MarkerCorrupt, SingleReadRefused, OSError):
        return RunResult(1, lines=("AUT2 INPUT_UNREADABLE input=marker",))
    lines = ["LABEL_OUTCOMES SKIPPED reason=lock"]
    alerts = AlertBatch(deps)
    if skip_is_critical(record.consecutive):
        alerts.raise_critical("aut2.lock_skips_consecutive", LABEL_UNIT)
        alerts.deliver_all()
    return RunResult(_RC_DELIVERY if alerts.failed else 0, lines=(*lines, *alerts.lines))


def run_unit(
    deps: LabelRunDeps,
    *,
    lock: Lock,
    unit_max_bytes: int,
    aut6: Aut6Reading,
    measured_peak_bytes: int | None,
    proof_window: ProofHook | None,
    slot_ns: int,
) -> RunResult:
    """One slot of ``breezy-label-outcomes``: flock, memory gate, the run, then the proof window.

    A flock timeout is a journalled skip (exit 0); a held slot writes the hold journal, delivers the
    health CRITICAL and never starts the scorer (exit 0, no marker); a run that wrote a marker is
    followed by the proof-window hook (a hook failure exits 1)."""
    if not lock.acquire(LABEL_FLOCK_WAIT_S):
        return _skip(deps, slot_ns)
    try:
        hold = label_slot_held(
            unit_max_bytes=unit_max_bytes, aut6=aut6, measured_peak_bytes=measured_peak_bytes
        )
        if hold is not None:
            try:
                record_hold(deps.data_root, hold, now_ns=deps.now_ns, slot_ns=slot_ns)
            except HoldJournalWriteFailed:
                return RunResult(1, lines=(f"AUT2 SKIP_JOURNAL_WRITE_FAILED unit={LABEL_UNIT}",))
            alerts = AlertBatch(deps)
            event = (
                "aut2.label_memory_sizing_exceeds_cap"
                if hold.cause == "memory_sizing_exceeds_cap"
                else "aut2.label_timer_held"
            )
            alerts.raise_critical(event, LABEL_UNIT)
            alerts.deliver_all()
            line = f"AUT2 HEALTH label_timer_held cause={hold.cause} unit={LABEL_UNIT}"
            return RunResult(_RC_DELIVERY if alerts.failed else 0, lines=(line, *alerts.lines))
        result = run_labels(deps)
        if result.marker_path is None or proof_window is None:
            return result
        try:
            proof_window(deps.data_root, deps.now_ns)
        except (OSError, SingleReadRefused, LabelStoreError, ValueError) as exc:
            failed = f"AUT2 PROOF_WINDOW_FAILED cause={type(exc).__name__}"
            return replace(result, exit_code=1, lines=(*result.lines, failed))
        return result
    finally:
        lock.release()


# -- measure-peak ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MeasureSeams:
    meminfo_path: Path
    rss_bytes: Callable[[], int]
    proc_cgroup_text: str
    cgroup_root: Path


def read_cgroup_memory_peak(proc_cgroup_text: str, cgroup_root: Path) -> tuple[int, str]:
    """``(memory.peak bytes, cgroup path)`` of the cgroup named by ``/proc/self/cgroup``."""
    path = ""
    for line in proc_cgroup_text.splitlines():
        if line.startswith("0::"):
            path = line[3:].strip()
    if not path:
        raise ValueError("no cgroup v2 line in /proc/self/cgroup")
    peak_file = cgroup_root / path.lstrip("/") / "memory.peak"
    try:
        text = peak_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("memory.peak cannot be read") from exc
    if not text.isascii() or not text.isdigit():
        raise ValueError("memory.peak is not a byte count")
    return int(text), path


def _mem_available_bytes(meminfo_path: Path) -> int:
    for line in meminfo_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise ValueError("MemAvailable is absent from meminfo")


def measure_peak(
    deps: LabelRunDeps,
    *,
    output_root: Path,
    seams: MeasureSeams,
    invocation_id: str | None,
    git_sha: str,
) -> RunResult:
    """Run the whole label path into ``output_root`` with delivery as a dry run, then record the
    run's own cgroup ``memory.peak`` (plan Q1/V3). Aborts before any read below the MemAvailable
    floor; nothing is written outside ``output_root``."""
    floor = MEASURE_MEMAVAILABLE_FLOOR_GIB * _GIB + seams.rss_bytes()
    if _mem_available_bytes(seams.meminfo_path) < floor:
        print("LABEL_OUTCOMES MEASURE_ABORTED reason=memavailable")
        return RunResult(_RC_REFUSED, lines=("LABEL_OUTCOMES MEASURE_ABORTED reason=memavailable",))
    output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = run_labels(replace(deps, data_root=output_root, dry_run_root=output_root))
    peak, cgroup = read_cgroup_memory_peak(seams.proc_cgroup_text, seams.cgroup_root)
    write_json_once(
        output_root,
        ("evidence", "aut2", "memory", f"label_run_peak_{deps.now_ns}.json"),
        {
            "schema": "aut2_memory_peak/v1",
            "transient_unit": PurePosixPath(cgroup).name,
            "invocation_id": invocation_id,
            "memory_peak_bytes": peak,
            "cgroup_path": cgroup,
            "durable_fill_count": 0
            if result.coverage is None
            else result.coverage.durable_fill_count,
            "git_sha": git_sha,
            "memory_max_during_measure": _memory_max(seams, cgroup),
            "measured_at_ns": deps.now_ns,
        },
    )
    return result


def _memory_max(seams: MeasureSeams, cgroup: str) -> int | None:
    try:
        text = (
            (seams.cgroup_root / cgroup.lstrip("/") / "memory.max")
            .read_text(encoding="utf-8")
            .strip()
        )
    except OSError:
        return None
    return int(text) if text.isascii() and text.isdigit() else None


def _real_measure_seams() -> MeasureSeams:  # pragma: no cover - reads the live host
    try:
        proc = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        proc = ""
    return MeasureSeams(Path("/proc/meminfo"), lambda: 0, proc, Path("/sys/fs/cgroup"))


# -- the command line -----------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitWiring:
    """Everything the default mode needs that only the promoted unit can supply."""

    deps: LabelRunDeps
    lock: Lock
    unit_max_bytes: int
    aut6: Aut6Reading
    measured_peak_bytes: int | None
    proof_window: ProofHook | None
    slot_ns: int


UnitFactory = Callable[[argparse.Namespace], UnitWiring]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="label_run", exit_on_error=False)
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--proof-window", action="store_true")
    parser.add_argument("--record-skip", action="store_true")
    parser.add_argument("--measure-peak", action="store_true")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--exec-db", type=Path)
    parser.add_argument("--venue", default="polymarket_us")
    parser.add_argument("--family", default="pm_us_crh_fq_v1")
    parser.add_argument("--day")
    parser.add_argument("--start-day")
    parser.add_argument("--now-ns", type=int)
    parser.add_argument("--slot-ns", type=int)
    return parser


def _real_fill_count(exec_db: Path, day: str) -> int:
    """Every durable fill dated ``day``. Drill fills count as real here, deliberately: a canary
    is refused on any day with any durable fill, which is the conservative direction."""
    read = read_durable_fills(exec_db).require_clean()
    return sum(1 for f in read.fills if utc_day(f.ts_event) == day)


def _canary_main(args: argparse.Namespace) -> int:
    if args.data_root is None or args.day is None:
        print("AUT2 USAGE --canary needs --data-root and --day")
        return _RC_REFUSED
    now_ns = args.now_ns if args.now_ns is not None else time.time_ns()
    try:
        date_component(args.day)
    except WireRefused:
        print("AUT2 USAGE --day must be an ISO YYYY-MM-DD date")
        return _RC_REFUSED
    if not args.day < utc_day(now_ns):  # ISO dates order as strings; only closed days run
        print(f"AUT2 CANARY_REFUSED day={args.day} reason=day_not_closed")
        return 1
    count = -1
    try:
        if args.exec_db is not None:
            count = _real_fill_count(args.exec_db, args.day)
        else:
            cache = args.data_root / "cache" / "label_run_snapshot"
            with snapshot_exec_db(args.data_root, cache) as db:
                count = _real_fill_count(db, args.day)
        run = run_canary(
            data_root=args.data_root,
            venue=args.venue,
            family_id=args.family,
            day=args.day,
            now_ns=now_ns,
            real_fill_count=count,
        )
    except CanaryRefused:
        print(f"AUT2 CANARY_REFUSED day={args.day} real_fills={count}")
        return 1
    except (OSError, sqlite3.Error, FillStoreCorruption, ExecSnapshotUnavailable):
        print("AUT2 CANARY_FAILED the exec store or a canary write failed")
        return 1
    print(f"AUT2 CANARY day={args.day} canary_fills={run.canary_fills} live_fill_check=vacuous")
    return 0


def _proof_window_main(args: argparse.Namespace) -> int:
    from breezy.analysis.labeling.proof_source import check_proof_start, store_proof_window
    from breezy.persistence.autonomy.capture_epoch import read_epoch

    if args.data_root is None or args.start_day is None:
        print("AUT2 USAGE --proof-window needs --data-root and --start-day")
        return _RC_REFUSED
    now_ns = args.now_ns if args.now_ns is not None else time.time_ns()
    try:
        epoch = read_epoch(args.data_root, args.family)
    except (OSError, SingleReadRefused, ValueError):
        print("AUT2 PROOF_WINDOW_FAILED cause=capture_epoch_unreadable")
        return 1
    epoch_ns = None if epoch is None else epoch.epoch_start_ns
    refusal = check_proof_start(args.data_root, args.start_day, WP7_ACTIVE, epoch_ns)
    if refusal is not None:
        print(f"AUT2 PROOF_WINDOW_REFUSED reason={refusal}")
        return _RC_REFUSED
    try:
        with _exec_db(args) as db:
            path = store_proof_window(
                args.data_root,
                exec_db=db,
                venue=args.venue,
                family_id=args.family,
                start_day=args.start_day,
                lag_start_ns=lambda fill: fill.ts_event,  # conservative: the fill, not the deadline
                now_ns=now_ns,
                wp7_active=WP7_ACTIVE,
                capture_epoch_start_ns=epoch_ns,
            )
    except Exception as exc:  # noqa: BLE001 - any store failure is one nonzero exit
        print(f"AUT2 PROOF_WINDOW_FAILED cause={type(exc).__name__}")
        return 1
    print(
        "AUT2 PROOF_WINDOW written" if path is not None else "AUT2 PROOF_WINDOW nothing_to_evaluate"
    )
    return 0


@contextmanager
def _exec_db(args: argparse.Namespace) -> Iterator[Path]:
    if args.exec_db is not None:
        yield args.exec_db
        return
    with snapshot_exec_db(args.data_root, args.data_root / "cache" / "label_run_snapshot") as db:
        yield db


def _record_skip_main(args: argparse.Namespace) -> int:
    if args.data_root is None or args.slot_ns is None:
        print("AUT2 USAGE --record-skip needs --data-root and --slot-ns")
        return _RC_REFUSED
    now_ns = args.now_ns if args.now_ns is not None else time.time_ns()
    try:
        since = _since_ns(args.data_root)
    except (MarkerCorrupt, SingleReadRefused, OSError):
        print("AUT2 INPUT_UNREADABLE input=marker")
        return 1
    rc, line = run_record_skip(
        args.data_root, LABEL_UNIT, now_ns, slot_ns=args.slot_ns, since_ns=since
    )
    print(line)
    return rc


def main(
    argv: Sequence[str] | None = None,
    *,
    unit_context: UnitContext | None = None,
    measure_seams: MeasureSeams | None = None,
    unit_factory: UnitFactory | None = None,
) -> int:
    try:
        args = _parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    except (argparse.ArgumentError, SystemExit):
        return _RC_REFUSED
    modes = [args.canary, args.proof_window, args.record_skip, args.measure_peak]
    if sum(modes) > 1:
        print("AUT2 USAGE choose at most one mode")
        return _RC_REFUSED
    if args.measure_peak:
        return _measure_main(args, measure_seams, unit_factory)
    context = unit_context if unit_context is not None else UnitContext.current()
    if not context.is_label_unit():
        print("LABEL_OUTCOMES REFUSED reason=not_under_unit")
        return _RC_REFUSED
    if args.canary:
        return _canary_main(args)
    if args.proof_window:
        return _proof_window_main(args)
    if args.record_skip:
        return _record_skip_main(args)
    if unit_factory is None:
        print("LABEL_OUTCOMES REFUSED reason=not_wired")
        return _RC_REFUSED
    wiring = unit_factory(args)
    result = run_unit(
        wiring.deps,
        lock=wiring.lock,
        unit_max_bytes=wiring.unit_max_bytes,
        aut6=wiring.aut6,
        measured_peak_bytes=wiring.measured_peak_bytes,
        proof_window=wiring.proof_window,
        slot_ns=wiring.slot_ns,
    )
    for line in result.lines:
        print(line)
    return result.exit_code


def _measure_main(
    args: argparse.Namespace, seams: MeasureSeams | None, unit_factory: UnitFactory | None
) -> int:
    if args.output_root is None:
        print("AUT2 USAGE --measure-peak needs --output-root")
        return _RC_REFUSED
    chosen = seams if seams is not None else _real_measure_seams()
    floor = MEASURE_MEMAVAILABLE_FLOOR_GIB * _GIB + chosen.rss_bytes()
    if _mem_available_bytes(chosen.meminfo_path) < floor:
        print("LABEL_OUTCOMES MEASURE_ABORTED reason=memavailable")
        return _RC_REFUSED
    if unit_factory is None:
        print("LABEL_OUTCOMES REFUSED reason=not_wired")
        return _RC_REFUSED
    wiring = unit_factory(args)
    result = measure_peak(
        wiring.deps,
        output_root=args.output_root,
        seams=chosen,
        invocation_id=os.environ.get("INVOCATION_ID"),
        git_sha=os.environ.get("BREEZY_GIT_SHA", "unknown"),
    )
    for line in result.lines:
        print(line)
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
