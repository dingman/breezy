"""The label-run entrypoint (AUT-2 r7 WP8 part: ``--canary`` and ``--proof-window``).

``run_canary`` is the canary path of section 3.8: on a UTC day with zero real fills it writes the
deterministic synthetic canary fills and labels them with the real FQ Scorer into
``derived/labels_canary/``. It reads no venue positions and never opens ``labels/``, the exec
store's ledger for anything but the day's fill count, or any reconciliation input. Its only writes
are ``derived/canary/`` and ``derived/labels_canary/`` (the studies flock is the wrapper's).

``run_proof_window`` evaluates the window rules over per-day evidence and writes the write-once
artefact. Assembling that evidence from the stores needs the run-marker reader WP6 adds, so the
command line has no source yet and fails closed (exit 2) rather than guessing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.attribution import Attribution
from breezy.analysis.labeling.fill_source import (
    FillStoreCorruption,
    net_by_base_slug,
    read_durable_fills,
)
from breezy.analysis.labeling.fq_scorer import ForecastQuantileLadderScorer, FqFillInput
from breezy.analysis.labeling.proof_window import (
    DayEvidence,
    evaluate_window,
)
from breezy.analysis.labeling.skip_journal import utc_day, write_json_once
from breezy.domain.instrument_leg import base_symbol_of, leg_of_symbol, symbol_of_instrument_id
from breezy.persistence.autonomy.canary_store import (
    CANARY_ID_PREFIX,
    LABELS_CANARY_DIR,
    CanaryFill,
    read_canary_fills,
    write_canary_fills,
)
from breezy.persistence.autonomy.capture_reader import DecisionView, OrderLinkView
from breezy.persistence.autonomy.label_store import LabelRow, write_labels
from breezy.persistence.autonomy.paths import date_component
from breezy.persistence.autonomy.wire import WireRefused

__all__ = [
    "PROOF_DIR",
    "CanaryRefused",
    "CanaryRun",
    "main",
    "run_canary",
    "run_proof_window",
    "synthesize_canary_fills",
]

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


def _canary_reconciles(fills: Sequence[CanaryFill]) -> bool:
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
        reconciliation_passes=_canary_reconciles(fills),
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="label_run", exit_on_error=False)
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--proof-window", action="store_true")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--exec-db", type=Path)
    parser.add_argument("--venue", default="polymarket_us")
    parser.add_argument("--family", default="pm_us_crh_fq_v1")
    parser.add_argument("--day")
    parser.add_argument("--start-day")
    parser.add_argument("--now-ns", type=int)
    return parser


def _real_fill_count(exec_db: Path, day: str) -> int:
    """Every durable fill dated ``day``. Drill fills count as real here, deliberately: a canary
    is refused on any day with any durable fill, which is the conservative direction."""
    read = read_durable_fills(exec_db).require_clean()
    return sum(1 for f in read.fills if utc_day(f.ts_event) == day)


def _canary_main(args: argparse.Namespace) -> int:
    if args.data_root is None or args.exec_db is None or args.day is None:
        print("AUT2 USAGE --canary needs --data-root, --exec-db and --day")
        return _RC_USAGE
    now_ns = args.now_ns if args.now_ns is not None else time.time_ns()
    try:
        date_component(args.day)
    except WireRefused:
        print("AUT2 USAGE --day must be an ISO YYYY-MM-DD date")
        return _RC_USAGE
    if not args.day < utc_day(now_ns):  # ISO dates order as strings; only closed days run
        print(f"AUT2 CANARY_REFUSED day={args.day} reason=day_not_closed")
        return _RC_FAILED
    try:
        count = _real_fill_count(args.exec_db, args.day)
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
        return _RC_FAILED
    except (OSError, sqlite3.Error, FillStoreCorruption):
        print("AUT2 CANARY_FAILED the exec store or a canary write failed")
        return _RC_FAILED
    print(f"AUT2 CANARY day={args.day} canary_fills={run.canary_fills} live_fill_check=vacuous")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    except (argparse.ArgumentError, SystemExit):
        return _RC_USAGE
    if args.canary == args.proof_window:
        print("AUT2 USAGE choose exactly one of --canary and --proof-window")
        return _RC_USAGE
    if args.canary:
        return _canary_main(args)
    # The store-backed day evidence needs the run-marker reader (WP6): fail closed until it lands.
    print("AUT2 PROOF_WINDOW_SOURCE_UNAVAILABLE no store reader is wired yet")
    return _RC_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
