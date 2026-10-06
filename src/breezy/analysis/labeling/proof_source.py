"""The store-backed live-proof evidence (AUT-2 r7 WP6, section 6; plan ruling WP8-2).

``collect_day_evidence`` assembles one UTC day's :class:`DayEvidence` from the stores the label run
wrote: the day's newest marker, the C2 labels, the verdict journal, the hold journal and the canary
store. Anything unreadable raises :class:`ProofSourceError`: a day is never guessed or defaulted to
a pass. ``store_proof_window`` runs the window rules over every closed day from the start day.

A day's real fills are every durable fill whose ``ts_event`` falls on that UTC day (drill included:
conservative). The window start is gated by ``wp7_active`` (a reviewed constant flipped when the
C1 switch-over activates) and the written ``capture_epoch_start``; a refusal prints one line and
writes nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.completeness import is_final_row
from breezy.analysis.labeling.fill_source import FillStoreCorruption, read_durable_fills
from breezy.analysis.labeling.memory_gate import HOLD_DIR
from breezy.analysis.labeling.proof_window import (
    DayEvidence,
    ProofWindowRefused,
    evaluate_window,
)
from breezy.analysis.labeling.skip_journal import utc_day
from breezy.persistence.autonomy.canary_store import (
    LABELS_CANARY_DIR,
    CanaryFill,
    InvalidCanaryFill,
    read_canary_fills,
)
from breezy.persistence.autonomy.label_schema import LabelRole, PSource
from breezy.persistence.autonomy.label_store import (
    LabelRow,
    LabelStoreError,
    MarkerCorrupt,
    read_labels,
    read_newest_marker,
)
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    open_root,
    read_once_at,
    walk_dirs,
)
from breezy.persistence.autonomy.verdict import VerdictOutcome

__all__ = [
    "ProofSourceError",
    "check_proof_start",
    "collect_day_evidence",
    "hold_days",
    "store_proof_window",
]

_NS_PER_H: Final = 3_600_000_000_000
_NS_PER_DAY: Final = 24 * _NS_PER_H
_VERDICT_ROOT: Final[tuple[str, ...]] = ("derived", "verdicts")
_MAX_VERDICT_BYTES: Final = 1024 * 1024
_RECON_DETECTOR: Final = "aut2.reconciliation"
_LAG_DETECTOR: Final = "aut2.label_lag"
_ONE_DAY: Final = dt.timedelta(days=1)


class ProofSourceError(Exception):
    """A store the proof window needs could not be read: the day is not evaluated."""


def _list(rootfd: int, parts: Sequence[str]) -> list[str]:
    try:
        dirfd = walk_dirs(rootfd, parts)
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.NOT_FOUND:
            return []
        raise
    try:
        return sorted(os.listdir(dirfd))
    finally:
        os.close(dirfd)


def hold_days(data_root: Path) -> tuple[str, ...]:
    """Every UTC day with a label-hold journal file, ascending."""
    try:
        rootfd = open_root(data_root)
    except (SingleReadRefused, OSError) as exc:
        raise ProofSourceError("the data root cannot be opened") from exc
    try:
        days = [d for d in _list(rootfd, HOLD_DIR) if _list(rootfd, (*HOLD_DIR, d))]
    except (SingleReadRefused, OSError) as exc:
        raise ProofSourceError("the hold journal cannot be read") from exc
    finally:
        os.close(rootfd)
    return tuple(days)


def _verdict_wires(data_root: Path, family_id: str) -> list[dict[str, Any]]:
    wires: list[dict[str, Any]] = []
    try:
        rootfd = open_root(data_root)
    except (SingleReadRefused, OSError) as exc:
        raise ProofSourceError("the data root cannot be opened") from exc
    try:
        base = (*_VERDICT_ROOT, family_id)
        for day in _list(rootfd, base):
            for name in _list(rootfd, (*base, day)):
                dirfd = walk_dirs(rootfd, (*base, day))
                try:
                    raw = read_once_at(
                        dirfd, name, max_bytes=_MAX_VERDICT_BYTES, policy=ReadPolicy.STRICT
                    )
                finally:
                    os.close(dirfd)
                wire = json.loads(raw)
                if not isinstance(wire, dict):
                    raise TypeError("a verdict file is not an object")
                wires.append(wire)
    except (SingleReadRefused, OSError, ValueError, TypeError) as exc:
        raise ProofSourceError("the verdict journal cannot be read") from exc
    finally:
        os.close(rootfd)
    return wires


def _metric_int(wire: dict[str, Any], name: str) -> int:
    metrics = wire.get("metrics", {})
    value = metrics.get(name) if isinstance(metrics, dict) else None
    if isinstance(value, str):
        return int(Decimal(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _day_of(ns: int) -> str:
    return utc_day(ns)


def _verdict_pick(
    wires: Sequence[dict[str, Any]], day: str, mode: str, detector: str = _RECON_DETECTOR
) -> tuple[VerdictOutcome | None, str | None, dict[str, Any] | None]:
    """The newest ``detector`` verdict of ``mode`` produced on ``day``: outcome, id, wire."""
    mine = [
        w
        for w in wires
        if w.get("detector") == detector
        and _day_of(int(w["produced_at_ns"])) == day
        and _mode_of(w) == mode
    ]
    if not mine:
        return None, None, None
    newest = max(mine, key=lambda w: int(w["produced_at_ns"]))
    return VerdictOutcome(newest["outcome"]), str(newest["verdict_id"]), newest


def _mode_of(wire: dict[str, Any]) -> str:
    metrics = wire.get("metrics", {})
    mode = metrics.get("mode") if isinstance(metrics, dict) else None
    return str(mode)


def _canary_reconciles(fills: Sequence[CanaryFill]) -> bool:
    from breezy.analysis.labeling.label_run import canary_reconciles

    return canary_reconciles(fills)


def collect_day_evidence(
    data_root: Path,
    *,
    exec_db: Path,
    venue: str,
    family_id: str,
    day: str,
    lag_start_ns: Callable[[DurableFillRecord], int],
    now_ns: int,
) -> DayEvidence:
    """One UTC day's evidence, read from the stores; unreadable input raises."""
    try:
        read = read_durable_fills(exec_db).require_clean()
    except (OSError, sqlite3.Error, FillStoreCorruption) as exc:
        raise ProofSourceError("the exec store cannot be read") from exc
    day_fills = [f for f in read.fills if _day_of(f.ts_event) == day]
    coids = {f.client_order_id for f in day_fills}
    try:
        labels = read_labels(data_root)
        canary_labels = read_labels(data_root, labels_dir=LABELS_CANARY_DIR)
        canary_fills = read_canary_fills(data_root, venue, day)
        after = (dt.date.fromisoformat(day) + _ONE_DAY).isoformat()
        marker = read_newest_marker(data_root, day=after)
    except (
        LabelStoreError,
        MarkerCorrupt,
        SingleReadRefused,
        InvalidCanaryFill,
        OSError,
        ValueError,
    ) as exc:
        raise ProofSourceError("a label, canary or marker store cannot be read") from exc
    mine = [r for r in labels if r.client_order_id in coids]
    entries = [r for r in mine if r.role is LabelRole.ENTRY]
    final = {
        r.client_order_id: r for r in entries if is_final_row(r, now_ns=now_ns, deadline_ns=now_ns)
    }
    wires = _verdict_wires(data_root, family_id)
    # the daily run that labels day D's fills is the run after D closes (D+1); the post-STOP and
    # intraday verdicts of D are produced on D itself
    after = (dt.date.fromisoformat(day) + _ONE_DAY).isoformat()
    daily, daily_id, daily_wire = _verdict_pick(wires, after, "daily")
    post_stop, post_stop_id, _ = _verdict_pick(wires, day, "post_stop")
    intraday_bad = tuple(
        str(w["verdict_id"])
        for w in wires
        if w.get("detector") == _RECON_DETECTOR
        and _mode_of(w) == "intraday"
        and _day_of(int(w["produced_at_ns"])) == day
        and w["outcome"] != VerdictOutcome.PASS.value
    )
    lag_h = _max_lag_hours(day_fills, final, lag_start_ns, now_ns)
    return DayEvidence(
        utc_day=day,
        real_fills=len(day_fills),
        final_labelled=sum(1 for f in day_fills if f.client_order_id in final),
        unresolved=0 if marker is None else marker.unresolved,
        missing_label=0 if marker is None else marker.missing_label,
        non_c1_post_epoch_count=0 if marker is None else marker.non_c1_post_epoch_count,
        non_c1_entry_rows=sum(1 for r in entries if r.p_source is not PSource.C1_DECISION),
        p_null_count=0 if marker is None else marker.p_null_count,
        daily_recon=daily,
        post_stop=post_stop,
        intraday_non_pass_ids=intraday_bad,
        position_mismatches_transient=(
            0 if daily_wire is None else _metric_int(daily_wire, "position_mismatches_transient")
        ),
        max_label_lag_h=lag_h,
        fills_never_position_compared=(
            len(day_fills)
            if daily_wire is None
            else _metric_int(daily_wire, "fills_never_position_compared")
        ),
        canary_fills=len(canary_fills),
        canary_labelled_with_p=bool(canary_fills)
        and len([r for r in canary_labels if r.climate_day == day]) >= len(canary_fills)
        and all(r.p_at_decision is not None for r in canary_labels if r.climate_day == day),
        canary_recon_passes=bool(canary_fills) and _canary_reconciles(canary_fills),
        label_slot_held=day in hold_days(data_root),
        no_leg_fills=sum(1 for r in entries if r.leg == "no"),
        exit_fills=sum(1 for r in mine if r.role is LabelRole.EXIT),
        marker_file=None if marker is None else f"marker_{marker.written_at_ns}.json",
        daily_recon_verdict_id=daily_id,
        post_stop_verdict_id=post_stop_id,
    )


def _max_lag_hours(
    day_fills: Sequence[DurableFillRecord],
    final: dict[str, LabelRow],
    lag_start_ns: Callable[[DurableFillRecord], int],
    now_ns: int,
) -> float:
    lags = [
        (
            (final[f.client_order_id].labelled_at_ns if f.client_order_id in final else now_ns)
            - lag_start_ns(f)
        )
        / _NS_PER_H
        for f in day_fills
    ]
    return max(lags, default=0.0)


def _closed_days(start_day: str, now_ns: int) -> list[str]:
    today = dt.date.fromisoformat(utc_day(now_ns))
    day = dt.date.fromisoformat(start_day)
    days: list[str] = []
    while day < today:
        days.append(day.isoformat())
        day += _ONE_DAY
    return days


def check_proof_start(
    data_root: Path, start_day: str, wp7_active: bool, capture_epoch_start_ns: int | None
) -> str | None:
    """The refusal reason for starting the window at ``start_day``, or ``None`` when it may."""
    try:
        evaluate_window(
            start_day=start_day,
            days=(),
            capture_epoch_start_ns=capture_epoch_start_ns,
            wp7_active=wp7_active,
            hold_days=hold_days(data_root),
        )
    except ProofWindowRefused as exc:
        return exc.reason
    return None


def store_proof_window(
    data_root: Path,
    *,
    exec_db: Path,
    venue: str,
    family_id: str,
    start_day: str,
    lag_start_ns: Callable[[DurableFillRecord], int],
    now_ns: int,
    wp7_active: bool,
    capture_epoch_start_ns: int | None,
) -> Path | None:
    """Evaluate every closed day from ``start_day`` and write the artefact; ``None`` when there is
    nothing to evaluate or the window cannot start (one refusal line, nothing written)."""
    from breezy.analysis.labeling.label_run import run_proof_window

    refusal = check_proof_start(data_root, start_day, wp7_active, capture_epoch_start_ns)
    if refusal is not None:
        print(f"AUT2 PROOF_WINDOW_REFUSED reason={refusal}")
        return None
    holds = hold_days(data_root)
    days = _closed_days(start_day, now_ns)
    if not days:
        return None
    evidence = [
        collect_day_evidence(
            data_root,
            exec_db=exec_db,
            venue=venue,
            family_id=family_id,
            day=day,
            lag_start_ns=lag_start_ns,
            now_ns=now_ns,
        )
        for day in days
    ]
    return run_proof_window(
        data_root,
        start_day=start_day,
        days=evidence,
        capture_epoch_start_ns=capture_epoch_start_ns,
        wp7_active=wp7_active,
        hold_days=holds,
    )
