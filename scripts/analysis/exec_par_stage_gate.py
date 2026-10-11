"""EXEC-PAR BG-7: the read-only cross-check and stage report (D-PREREG 1a, 10, 14 step 12, K8, O5).

An out-of-process second opinion on the in-node stage evaluator. It opens the node state store
with sqlite ``mode=ro`` (``Path.as_uri()``; ``PRAGMA query_only=ON``), builds the SAME
``StageSnapshot`` the node builds (``build_stage_snapshot`` over the same latch read methods,
through a store that has no ``set``/``delete``) and runs the SAME pure ``evaluate_stage``. It
never writes the store, ``BREAKER_KEY`` included; the only files it writes are its two outputs,
each by tmp file plus ``os.replace``.

Outputs (default ``docs/evidence/exec_par/``):

* ``stage_gate_report.json``: the verdict comparison, the stage report (rebuilt days, excluded
  days, pre-reset-armed settlements, the per-day AMBIGUOUS counts BG-10(f) consumes, look status,
  holds, the spend-audit deferral status) and the in-node report's ``report_json`` figures.
  Counts, labels and day labels only: no currency amount is written.
* ``k_epochs.jsonl``: one line per BG-2 epoch row (spec 10: "BG-7 exports the rows"). ``src``
  never reads it.

Comparison (``AGREE`` / ``DISAGREE``). The in-node verdict is the ``stage_eval/report`` row
(``stage_eval/stamp`` for health). It disagrees when the verdict kind or reason differs, when a
K>1 stage has no (or a stale, or an unreadable) in-node report or no stamp, or when a CLOSED day's
posted / AMBIGUOUS / fill counts differ between the two. With no epoch rows, or at K=1, the node
runs no K>1 pass and writes no report: the in-node verdict is then taken as ``PASS`` (K8: a
PASS/PASS agreement on empty data).

What this run cannot reproduce, stated rather than hidden:

* It does not reconcile (reconcile writes). It reads the counters as the node's last reconcile
  left them; the reconcile phase row maps to ``PassStatus`` (a pass older than the reconcile
  bound with no ``reconcile_ok_ns`` is ``RECONCILE_STUCK``).
* The Nautilus cache spend audit (``spend_unaudited`` / ``spend_audit_mismatch``) exists only in
  the node process and is persisted nowhere, so the report states ``cache_audit_available:
  false`` and lists only the days the node already excluded with an audit cause.
* The serial baseline and the BG-11 denial classifier are not wired in the node either (integration
  notes 16); both are passed as ``None``.
* The ``DailySpendLedger`` predicate reads the operator daily budget from the environment exactly
  as the node does. The unit loads no ``operator.env``: with no budget in the environment a P&L
  predicate raises, the evaluator FAILs ``predicate:*`` and the comparison reports it.

Exit status: 0 AGREE, 1 DISAGREE (alert ``EXEC_PAR_STAGE_CROSSCHECK_DISAGREE``), 2 the run itself
failed (alert ``EXEC_PAR_STAGE_CROSSCHECK_ERROR``).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from breezy.adapters.polymarket_us.operator_controls import DailySpendLedger
from breezy.registry.sites import default_registry
from breezy.runtime.exec_par_constants import EXEC_PAR_MAX_CONCURRENT_INTENTS
from breezy.runtime.exec_par_counter_store import LatchCounterStore
from breezy.runtime.exec_par_days_port import DayConvention
from breezy.runtime.exec_par_governed_days import governed_days_for
from breezy.runtime.exec_par_latch_stage import ExecParStageRowsMixin
from breezy.runtime.exec_par_reconcile import RECONCILE_BOUND_NS, PassStatus
from breezy.runtime.exec_par_records import (
    AMENDMENT_KEY_PREFIX,
    EXEC_PAR_PREFIX,
    Amendment,
    EpochRow,
    ExecParRecordError,
    RebuildRow,
    StageReportDoc,
    decode_record,
)
from breezy.runtime.exec_par_stage_eval import evaluate_stage
from breezy.runtime.exec_par_stage_report import report_json
from breezy.runtime.exec_par_stage_snapshot import SnapshotInputs, build_stage_snapshot
from breezy.runtime.exec_par_stage_types import (
    PnlPredicatePort,
    StageSnapshot,
    Verdict,
    VerdictKind,
)
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert, resolve_alert_sink
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS

__all__ = [
    "EPOCHS_NAME",
    "EVENT_DISAGREE",
    "EVENT_ERROR",
    "REPORT_NAME",
    "CrossCheckResult",
    "ReadOnlyState",
    "atomic_write_text",
    "main",
    "run_cross_check",
]

logger = logging.getLogger(__name__)

EVENT_DISAGREE: Final[str] = "EXEC_PAR_STAGE_CROSSCHECK_DISAGREE"
EVENT_ERROR: Final[str] = "EXEC_PAR_STAGE_CROSSCHECK_ERROR"
ALERT_SITE: Final[str] = "exec_par"
REPORT_NAME: Final[str] = "stage_gate_report.json"
EPOCHS_NAME: Final[str] = "k_epochs.jsonl"
DEFAULT_OUT_DIR: Final[Path] = Path("docs/evidence/exec_par")
DB_ENV_VAR: Final[str] = "POLYMARKET_US_EXEC_STATE_DB"
VENUE: Final[str] = "polymarket_us"

_NS_PER_HOUR: Final[int] = 3_600 * 1_000_000_000
#: The stamp is "stale after 26 h" (integration notes): a daily pass plus two hours of slack.
DEFAULT_MAX_REPORT_AGE_HOURS: Final[int] = 26
_BUSY_TIMEOUT_S: Final[float] = 5.0
_REBUILD_PENDING: Final[str] = EXEC_PAR_PREFIX + "rebuild/"
_REBUILD_LOG: Final[str] = EXEC_PAR_PREFIX + "rebuild_log/"
_AUDIT_CAUSES: Final[frozenset[str]] = frozenset({"spend_unaudited", "spend_audit_mismatch"})
_K_FORCED_NOTE_PREFIX: Final[str] = "k_forced_to_1:"
_HEALTHY_KINDS: Final[frozenset[str]] = frozenset({"pass", "hold", "promotion_eligible"})
_EXIT_AGREE: Final[int] = 0
_EXIT_DISAGREE: Final[int] = 1
_EXIT_ERROR: Final[int] = 2


class StoreCorrupt(Exception):
    """A stored EXEC-PAR row did not decode (the latch's own ``CorruptError``)."""


# -- the read-only store ------------------------------------------------------------------------


class ReadOnlyState:
    """``get`` and ``keys_with_prefix`` over a ``mode=ro`` connection; no write method exists.

    A database with no ``state`` table (nothing ever written) reads as empty. The connection is
    closed by the context manager.
    """

    def __init__(self, path: Path) -> None:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, timeout=_BUSY_TIMEOUT_S)
        try:
            self._conn.execute("PRAGMA query_only=ON")
        except sqlite3.Error:
            self._conn.close()
            raise

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def get(self, key: str) -> bytes | None:
        rows = self._fetch("SELECT value FROM state WHERE key = ?", (key,))
        if not rows:
            return None
        value = rows[0][0]
        if not isinstance(value, bytes | memoryview):
            raise StoreCorrupt(key)
        return bytes(value)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        rows = self._fetch(
            "SELECT key FROM state WHERE substr(key, 1, ?) = ? ORDER BY key",
            (len(prefix), prefix),
        )
        return [str(row[0]) for row in rows]

    def _fetch(self, sql: str, params: tuple[object, ...]) -> list[tuple[object, ...]]:
        try:
            return list(self._conn.execute(sql, params).fetchall())
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return []
            raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class _ReadOnlyLatch(ExecParStageRowsMixin):
    """The node's own record readers over a store that cannot write.

    The mixin's writers are inherited but unreachable: they call ``self._store.set`` /
    ``delete``, which :class:`ReadOnlyState` does not have.
    """

    CorruptError = StoreCorrupt

    def __init__(self, store: ReadOnlyState) -> None:
        self._store = store  # type: ignore[assignment]  # read-only: no set()
        self._mutex = threading.Lock()

    def _require_held(self) -> None:
        """No process lock is needed (or taken) to read."""


# -- inputs derived from the store -----------------------------------------


@dataclass(frozen=True, slots=True)
class _KView:
    configured: int
    effective: int
    source: str


def _forced_amendment_ts(store: ReadOnlyState) -> tuple[int, ...]:
    found: list[int] = []
    for key in store.keys_with_prefix(AMENDMENT_KEY_PREFIX):
        raw = store.get(key)
        if raw is None:
            continue
        try:
            row = decode_record(Amendment, raw)
        except ExecParRecordError:
            raise StoreCorrupt(key) from None
        if row.note.startswith(_K_FORCED_NOTE_PREFIX):
            found.append(row.ts_ns)
    return tuple(sorted(found))


def _derive_k(
    epochs: tuple[EpochRow, ...], forced_ts: tuple[int, ...], override: int | None
) -> _KView:
    """Configured and effective K from the epoch ledger (or ``--configured-k``).

    No epoch rows: the node never booted a K>1 epoch, so K=1. The configured K is the last
    UNFORCED epoch's K (a forced row only records the K it was forced to); the effective K is the
    last row's, or 1 when a K-forced amendment landed since that boot."""
    if not epochs:
        return _KView(1 if override is None else override, 1, "no_epochs")
    last = epochs[-1]
    effective = 1 if any(ts >= last.boot_ts for ts in forced_ts) else last.effective_k
    if override is not None:
        return _KView(override, effective, "cli")
    unforced = [row.effective_k for row in epochs if row.force_reason is None]
    configured = unforced[-1] if unforced else EXEC_PAR_MAX_CONCURRENT_INTENTS
    return _KView(configured, effective, "epoch_ledger")


def _pass_status(latch: _ReadOnlyLatch, now_ns: int) -> tuple[PassStatus, dict[str, object]]:
    phase = latch.read_reconcile_phase()
    if phase is None:
        return PassStatus.OK, {"present": False}
    in_flight = phase.reconcile_ok_ns is None
    stuck = in_flight and now_ns - phase.reconcile_start_ns > RECONCILE_BOUND_NS
    info: dict[str, object] = {
        "present": True,
        "start_ns": phase.reconcile_start_ns,
        "ok_ns": phase.reconcile_ok_ns,
        "in_flight": in_flight,
    }
    return (PassStatus.RECONCILE_STUCK if stuck else PassStatus.OK), info


# -- the rebuilt verdict ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Mine:
    verdict: Verdict
    snapshot: StageSnapshot | None
    k: _KView
    epochs: tuple[EpochRow, ...] | None
    reconcile: dict[str, object]


def _fail_verdict(reason: str) -> Verdict:
    return Verdict(VerdictKind.FAIL, reason=reason)


def _rebuild(
    latch: _ReadOnlyLatch,
    store: ReadOnlyState,
    *,
    governed: DayConvention,
    predicates: PnlPredicatePort,
    now_ns: int,
    configured_k: int | None,
) -> _Mine:
    """Build the node's snapshot and evaluate it; a stage-level read failure is a FAIL verdict
    (``stage_eval_fail:snapshot:<type>``, as in the node), never a crash."""
    k = _KView(1, 1, "unread")
    epochs: tuple[EpochRow, ...] | None = None
    reconcile: dict[str, object] = {"present": False}
    try:
        epochs = latch.read_epoch_rows()
        k = _derive_k(epochs, _forced_amendment_ts(store), configured_k)
        status, reconcile = _pass_status(latch, now_ns)
        snapshot = build_stage_snapshot(
            latch,
            LatchCounterStore(latch, wall_ns=lambda: now_ns),
            SnapshotInputs(
                now_ns=now_ns,
                today=governed.today(now_ns),
                configured_k=k.configured,
                effective_k=k.effective,
                pass_status=status,
                governed=governed,
                predicates=predicates,
                serial_baseline=None,
                counted_denial=None,
                read_stub_pnl=latch.read_floor_stub_pnl_day,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a FAIL verdict like the node's snapshot step
        logger.error("cross-check snapshot failed: %s", type(exc).__name__)
        return _Mine(
            _fail_verdict(f"stage_eval_fail:snapshot:{type(exc).__name__}"),
            None,
            k,
            epochs,
            reconcile,
        )
    return _Mine(evaluate_stage(snapshot), snapshot, k, epochs, reconcile)


# -- comparison ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Compared:
    in_node_verdict: str
    in_node_reason: str | None
    reasons: tuple[str, ...]


def _day_stat_rows(raw: object) -> dict[str, tuple[object, object, object]]:
    rows: dict[str, tuple[object, object, object]] = {}
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("day"), str):
            rows[item["day"]] = (item.get("posted"), item.get("ambiguous"), item.get("fills"))
    return rows


def _closed_day_mismatches(mine: Verdict, doc: StageReportDoc, today: str) -> list[str]:
    if mine.report is None or doc.report_json is None:
        return []
    try:
        theirs = _day_stat_rows(json.loads(doc.report_json).get("day_stats"))
    except (ValueError, AttributeError):
        return ["in_node_report_unreadable"]
    ours = {row.day: (row.posted, row.ambiguous, row.fills) for row in mine.report.day_stats}
    return [
        f"day_stats:{day}"
        for day in sorted(ours.keys() & theirs.keys())
        if day < today and ours[day] != theirs[day]
    ]


def _compare(
    mine: Verdict,
    *,
    today: str,
    k_gt1: bool,
    doc: StageReportDoc | None,
    doc_unreadable: bool,
    stamp_present: bool,
    now_ns: int,
    max_age_ns: int,
) -> _Compared:
    if doc_unreadable:
        return _Compared("UNREADABLE", None, ("in_node_report_unreadable",))
    mine_kind = mine.kind.value
    if doc is None:
        if k_gt1:
            return _Compared("MISSING", None, ("in_node_report_missing",))
        absent: tuple[str, ...] = () if mine_kind == "pass" else (f"verdict:pass!={mine_kind}",)
        return _Compared("PASS", None, absent)
    reasons: list[str] = []
    if doc.verdict != mine_kind:
        reasons.append(f"verdict:{doc.verdict}!={mine_kind}")
    elif (doc.reason or None) != (mine.reason or None):
        reasons.append(f"reason:{doc.reason}!={mine.reason}")
    if k_gt1 and now_ns - doc.ts_ns > max_age_ns:
        reasons.append("in_node_report_stale")
    if k_gt1 and doc.verdict in _HEALTHY_KINDS and not stamp_present:
        reasons.append("in_node_stamp_missing")
    reasons.extend(_closed_day_mismatches(mine, doc, today))
    return _Compared(doc.verdict.upper(), doc.reason, tuple(reasons))


# -- the report ------------------------------------------------------------


def _scan_rebuilds(store: ReadOnlyState) -> list[dict[str, object]]:
    rows: list[tuple[str, RebuildRow]] = []
    for prefix, status in ((_REBUILD_PENDING, "pending"), (_REBUILD_LOG, "retired")):
        for key in store.keys_with_prefix(prefix):
            raw = store.get(key)
            if raw is None:
                continue
            try:
                rows.append((status, decode_record(RebuildRow, raw)))
            except ExecParRecordError:
                raise StoreCorrupt(key) from None
    return [
        {
            "day": row.day,
            "status": status,
            "ts_ns": row.ts_ns,
            "mismatch_kinds": row.mismatch_kinds.split(","),
            "posted_entries": row.posted_entries,
            "ambiguous": row.ambiguous,
            "fills": row.fills,
        }
        for status, row in sorted(rows, key=lambda x: (x[1].day, x[1].ts_ns, x[0]))
    ]


def _pre_reset_rows(latch: _ReadOnlyLatch, governed: DayConvention) -> list[dict[str, object]]:
    """Entries armed before the reset, by arm-time day (counts only; the settlement instant is
    not stored). Days before the floor label are wholly pre-reset; a floor label is split by its
    post-floor stub row."""
    floor = latch.read_stage_reset()
    if floor is None:
        return []
    floor_labels = governed.open_days_at(floor.ts)
    first_floor = min(floor_labels)
    rows: list[dict[str, object]] = []
    for row in latch.read_settled_pnl_days():
        if row.day < first_floor:
            rows.append(_pnl_counts(row.day, row.total_entries, row))
        elif row.day in floor_labels:
            stub = latch.read_floor_stub_pnl_day(row.day)
            pre = None if stub is None else row.total_entries - stub.total_entries
            rows.append(_pnl_counts(row.day, pre, row))
    return rows


def _pnl_counts(day: str, pre_floor: int | None, row: object) -> dict[str, object]:
    return {
        "day": day,
        "pre_floor_entries": pre_floor,
        "settled_entries": getattr(row, "settled_entries", None),
        "ambiguous_entries": getattr(row, "ambiguous_entries", None),
        "unsettled_entries": getattr(row, "unsettled_entries", None),
        "overdue_entries": getattr(row, "overdue_entries", None),
    }


def _per_day(snapshot: StageSnapshot | None) -> list[dict[str, object]]:
    if snapshot is None:
        return []
    return [
        {
            "day": row.day,
            "posted": row.posted,
            "ambiguous": row.ambiguous,
            "fills": None if row.fills is None else len({f.client_order_id for f in row.fills}),
        }
        for row in sorted(snapshot.days, key=lambda r: r.day)
    ]


def _looks_section(latch: _ReadOnlyLatch, verdict: Verdict) -> dict[str, object]:
    return {
        "recorded": [{"day": x.day, "outcome": x.outcome} for x in latch.read_looks()],
        "look_number": verdict.look_number,
        "look_blockers": list(verdict.look_blockers),
        "eligible": verdict.kind is VerdictKind.PROMOTION_ELIGIBLE,
    }


def _holds_section(verdict: Verdict) -> dict[str, object]:
    held = verdict.kind is VerdictKind.HOLD
    return {
        "active": held,
        "reason": verdict.reason if held else None,
        "target_k": verdict.target_k if held else None,
        "held_days": None if verdict.report is None else verdict.report.held_days,
    }


def _deferral_section(excluded: list[dict[str, object]]) -> dict[str, object]:
    return {
        "cache_audit_available": False,
        "note": (
            "the Nautilus cache audit runs in the node only and is not persisted; "
            "only days the node already excluded with an audit cause are listed"
        ),
        "excluded_with_audit_cause": [
            str(row["day"]) for row in excluded if row["cause"] in _AUDIT_CAUSES
        ],
    }


def _stage_section(mine: _Mine, latch: _ReadOnlyLatch, today: str) -> dict[str, object]:
    stamp = latch.read_stage_eval_stamp()
    floor = latch.read_stage_reset()
    return {
        "today": today,
        "configured_k": mine.k.configured,
        "effective_k": mine.k.effective,
        "k_source": mine.k.source,
        "floor_ts": None if floor is None else floor.ts,
        "floor_cause": None if floor is None else floor.cause,
        "epoch_rows": None if mine.epochs is None else len(mine.epochs),
        "in_node_stamp_ts": None if stamp is None else stamp.ts_ns,
        "reconcile_phase": mine.reconcile,
        "stage_report": None if mine.verdict.report is None else report_json(mine.verdict.report),
    }


def _excluded_rows(latch: _ReadOnlyLatch) -> list[dict[str, object]]:
    return [{"day": x.day, "cause": x.cause, "ts": x.ts} for x in latch.read_excluded_days()]


_NOTES: Final[tuple[str, ...]] = (
    "read-only: no reconcile ran; counters are as the node's last reconcile left them",
    "serial baseline and the BG-11 denial classifier are not supplied (as in the node)",
    "pre-reset settlements are listed by arm-time day; settlement instants are not stored",
)


# -- outputs ---------------------------------------------------------------


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` whole or not at all: a tmp file in the same directory, flushed
    and synced, then ``os.replace``. A failure leaves the old file and no tmp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _epochs_jsonl(epochs: tuple[EpochRow, ...]) -> str:
    lines = [
        json.dumps(
            {
                "boot_ts": row.boot_ts,
                "commit_sha": row.commit_sha,
                "effective_k": row.effective_k,
                "force_reason": row.force_reason,
                "stop_ts": row.stop_ts,
            },
            sort_keys=True,
        )
        for row in sorted(epochs, key=lambda r: r.boot_ts)
    ]
    return "".join(line + "\n" for line in lines)


# -- the run ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CrossCheckResult:
    mine_verdict: str
    mine_reason: str | None
    in_node_verdict: str
    in_node_reason: str | None
    agreement: str
    reasons: tuple[str, ...]
    exit_code: int
    stage_report_json: str | None
    report_path: Path
    epochs_path: Path | None


def _alert(sink: AlertSink, severity: str, event: str, detail: str) -> None:
    emit_alert(sink, AlertPayload(severity=severity, event=event, site=ALERT_SITE, detail=detail))


def run_cross_check(
    *,
    db_path: Path,
    out_dir: Path,
    governed: DayConvention,
    predicates: PnlPredicatePort,
    now_ns: int,
    configured_k: int | None = None,
    max_report_age_hours: int = DEFAULT_MAX_REPORT_AGE_HOURS,
    sink: AlertSink,
) -> CrossCheckResult:
    """One read-only pass: rebuild the verdict, compare, write the report and the epoch export.

    Raises on a store that cannot be opened or read at the stage level of the REPORT sections
    (the caller maps that to exit 2); a failing snapshot is a FAIL verdict, not a raise."""
    with ReadOnlyState(db_path) as store:
        latch = _ReadOnlyLatch(store)
        mine = _rebuild(
            latch,
            store,
            governed=governed,
            predicates=predicates,
            now_ns=now_ns,
            configured_k=configured_k,
        )
        today = governed.today(now_ns)
        try:
            doc, report_unreadable = latch.read_stage_report(), False
        except StoreCorrupt:
            doc, report_unreadable = None, True
        compared = _compare(
            mine.verdict,
            today=today,
            k_gt1=mine.k.configured > 1,
            doc=doc,
            doc_unreadable=report_unreadable,
            stamp_present=_stamp_present(latch),
            now_ns=now_ns,
            max_age_ns=max_report_age_hours * _NS_PER_HOUR,
        )
        unreadable: list[str] = []
        excluded: list[dict[str, object]] = _section(
            "excluded_days", lambda: _excluded_rows(latch), _no_rows(), unreadable
        )
        sections: dict[str, object] = {
            "rebuilt_days": _section(
                "rebuilt_days", lambda: _scan_rebuilds(store), _no_rows(), unreadable
            ),
            "excluded_days": excluded,
            "pre_reset_armed_settlements": _section(
                "pre_reset_armed_settlements",
                lambda: _pre_reset_rows(latch, governed),
                _no_rows(),
                unreadable,
            ),
            "per_day_ambiguous": _per_day(mine.snapshot),
            "looks": _section(
                "looks", lambda: _looks_section(latch, mine.verdict), _no_doc(), unreadable
            ),
            "holds": _holds_section(mine.verdict),
            "spend_deferrals": _deferral_section(excluded),
            "stage": _section(
                "stage", lambda: _stage_section(mine, latch, today), _no_doc(), unreadable
            ),
            "unreadable_sections": unreadable,
        }
    agreement = "AGREE" if not compared.reasons else "DISAGREE"
    report: dict[str, object] = {
        "generated_ns": now_ns,
        "verdict_compare": {
            "agreement": agreement,
            "reasons": list(compared.reasons),
            "mine": {"verdict": mine.verdict.kind.value, "reason": mine.verdict.reason},
            "in_node": {"verdict": compared.in_node_verdict, "reason": compared.in_node_reason},
        },
        **sections,
        "notes": list(_NOTES),
    }
    report_path = out_dir / REPORT_NAME
    atomic_write_text(report_path, json.dumps(report, sort_keys=True, indent=2) + "\n")
    epochs_path: Path | None = None
    if mine.epochs is not None:
        epochs_path = out_dir / EPOCHS_NAME
        atomic_write_text(epochs_path, _epochs_jsonl(mine.epochs))
    if agreement == "DISAGREE":
        _alert(sink, "CRITICAL", EVENT_DISAGREE, "reasons=" + ",".join(compared.reasons))
    return CrossCheckResult(
        mine_verdict=mine.verdict.kind.value.upper(),
        mine_reason=mine.verdict.reason,
        in_node_verdict=compared.in_node_verdict,
        in_node_reason=compared.in_node_reason,
        agreement=agreement,
        reasons=compared.reasons,
        exit_code=_EXIT_AGREE if agreement == "AGREE" else _EXIT_DISAGREE,
        stage_report_json=None if mine.verdict.report is None else report_json(mine.verdict.report),
        report_path=report_path,
        epochs_path=epochs_path,
    )


def _section[T](name: str, build: Callable[[], T], default: T, unreadable: list[str]) -> T:
    """One report section: an unreadable row leaves the default and names the section (the
    verdict comparison already FAILs on the same row; the report must still be written)."""
    try:
        return build()
    except (StoreCorrupt, ExecParRecordError) as exc:
        logger.error("report section %s unreadable: %s", name, type(exc).__name__)
        unreadable.append(name)
        return default


def _no_rows() -> list[dict[str, object]]:
    return []


def _no_doc() -> dict[str, object]:
    return {}


def _stamp_present(latch: _ReadOnlyLatch) -> bool:
    try:
        return latch.read_stage_eval_stamp() is not None
    except StoreCorrupt:
        return False


# -- CLI -------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exec_par_stage_gate",
        description="EXEC-PAR BG-7: read-only stage cross-check, report and k_epochs export.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"node state store (default: ${DB_ENV_VAR}); opened mode=ro",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--stations",
        default=",".join(SUPPORTED_STATIONS),
        help="governed stations, comma separated (default: the supported four)",
    )
    parser.add_argument("--configured-k", type=int, default=None)
    parser.add_argument("--max-report-age-hours", type=int, default=DEFAULT_MAX_REPORT_AGE_HOURS)
    return parser


def _governed(stations: Sequence[str]) -> DayConvention:
    registry = default_registry()
    return governed_days_for(
        stations, lambda s: registry.climate_day_window(VENUE, s).std_utc_offset_hours
    )


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = _parser().parse_args(argv)
    db = args.db if args.db is not None else _db_from_env()
    sink = resolve_alert_sink(os.environ)
    try:
        if db is None:
            raise ValueError(f"no --db and ${DB_ENV_VAR} is unset")
        stations = tuple(s.strip() for s in str(args.stations).split(",") if s.strip())
        result = run_cross_check(
            db_path=db,
            out_dir=args.out_dir,
            governed=_governed(stations),
            predicates=DailySpendLedger(),
            now_ns=time.time_ns(),
            configured_k=args.configured_k,
            max_report_age_hours=args.max_report_age_hours,
            sink=sink,
        )
    except Exception as exc:  # noqa: BLE001 - any run failure is exit 2 plus an alert
        logger.error("cross-check failed: %s", type(exc).__name__)
        _alert(sink, "CRITICAL", EVENT_ERROR, f"run failed: {type(exc).__name__}")
        return _EXIT_ERROR
    logger.info(
        "cross-check %s mine=%s in_node=%s reasons=%s",
        result.agreement,
        result.mine_verdict,
        result.in_node_verdict,
        ",".join(result.reasons) or "-",
    )
    return result.exit_code


def _db_from_env() -> Path | None:
    value = os.environ.get(DB_ENV_VAR)
    return Path(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
