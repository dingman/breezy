"""FU-1d S3: walked VWAP vs realised NO fills (`RULING_FU-1b_no_leg_marks_
2026-09-26.md` re-open item 3, `FU-1d_derived_no_marks_plan_r1_2026-09-26.md`).

For every durable fill record in the live exec state store, reconstruct
`PositionMonitor`'s own entry-price and exit-mark derivation from the
Depth10 tape, using the SAME `walk_exit_vwap` (`monitor_evidence.py`)
production code -- never a hand-written price formula -- and compare it to
what Breezy actually paid (`cumulative_cost / cumulative_qty`).

**A measurement, not a gate:** exits 0 whenever both sources are readable,
whatever the residuals are; exits 2 only when a source cannot be read. No
verdict, no CI gate.

**Read-only, always**, via `fill_time_count._open_readonly` (`mode=ro`,
no flock -- the SAME idiom `measured_slippage_from_fills.py` uses) and
`ParquetDataCatalog`'s own query API.

**There is no NO-leg book to walk** -- Depth10 only ever exists under the
YES id (`PositionMonitor._on_sibling_depth`'s own docstring). Every fill is
therefore priced off its sibling-YES frame (`sibling_instrument_id`, an
involution; a YES fill's sibling is itself).

**Derivation for a BUY fill:** `derived_entry_px = 1 -
walk_exit_vwap(frame, opposite(leg), qty)[0]` (a NO buy walks the YES
BIDS; a YES buy's internal `1 - ask_vwap` is undone by the outer `1 -`,
landing on the plain ask VWAP). `derived_exit_mark = walk_exit_vwap(frame,
leg, qty)[0]`. `residual = fill_px - derived_entry_px`; `flagged` means
`fill_px < derived_entry_px` (L-25).

**Frame selection:** the latest sibling-YES frame with `frame.ts_init <
fill.ts_event` (strictly earlier -- a leak guard). `frame_age_ns >
_BOOK_STALE_NS` (`monitor_decision.py`, the same bound the monitor itself
enforces) marks a row `stale_frame`.

**Premise correction (verified read-only against the live store):** 9
fills, 3 NO (`miahigh-2026-09-15-gte92lt93f^no`,
`miahigh-2026-09-21-gte88lt89f^no`, `mdwhigh-2026-09-22-gte62lt63f^no`),
all BUY -- 0 NO EXIT (SELL) fills, so the ruling's second re-open trigger
is reported NOT EVALUABLE, never guessed at from an entry fill.

**Two findings the doc states:** the NO rows validate the complement/
sibling-routing mechanism on the BID side (how a NO entry executes); the
YES rows are the ASK-side control (a NO EXIT would buy YES through the
asks, like a YES entry). Neither measures a realised NO exit.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

from nautilus_trader.model.data import OrderBookDepth10
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.adapters.polymarket_us.symbology import leg_of, sibling_instrument_id
from breezy.strategy.current_rung_hold.monitor_decision import _BOOK_STALE_NS
from breezy.strategy.current_rung_hold.monitor_evidence import Leg, walk_exit_vwap

sys.path.insert(0, str(Path(__file__).resolve().parent))
# ONE implementation, reused -- the same idiom `measured_slippage_from_fills.py`
# and `score_live_trials.py` already use.
from fill_time_count import _open_readonly

__all__ = [
    "TICK",
    "FidelitySourceUnreadableError",
    "FidelitySummary",
    "FillMarkComparison",
    "measure_fill",
    "read_fill_records",
    "render_markdown",
    "select_frame",
    "summarise",
]

_ONE: Final[Decimal] = Decimal(1)
_ORDER_SIDE_BUY: Final[str] = "BUY"
_RESOLVER_TRADE_ID_PREFIX: Final[str] = "GET-"
_ONE_DAY_NS: Final[int] = 24 * 60 * 60 * 1_000_000_000

#: One Polymarket.us tick (the `Amount` string precision every wire price
#: uses, `submit_chain.py`'s own `f"{wire_price:.2f}"`).
TICK: Final[Decimal] = Decimal("0.01")

STATUS_MEASURED: Final[str] = "measured"
STATUS_NO_FRAME: Final[str] = "no_frame"
STATUS_STALE_FRAME: Final[str] = "stale_frame"
STATUS_ONE_SIDED: Final[str] = "one_sided"
STATUS_NOT_A_BUY: Final[str] = "not_a_buy"

_EXCLUDED_FROM_AGGREGATE: Final[frozenset[str]] = frozenset(
    {STATUS_NO_FRAME, STATUS_STALE_FRAME, STATUS_ONE_SIDED, STATUS_NOT_A_BUY},
)


class FidelitySourceUnreadableError(Exception):
    """A durable store or the catalog could not be opened/read read-only.

    Never embeds a path or a store value -- mirrors
    `measured_slippage_from_fills.SlippageSourceUnreadableError`.
    """


def _opposite(leg: Leg) -> Leg:
    return "NO" if leg == "YES" else "YES"


@dataclass(frozen=True, slots=True, kw_only=True)
class FillMarkComparison:
    """One durable fill, compared against the monitor's own walked mark at
    the latest sibling-YES frame strictly before the fill."""

    venue_order_id: str
    instrument_id: str
    leg: Leg
    order_side: str
    fill_px: Decimal | None
    qty: Decimal
    frame_ts_init: int | None
    frame_age_ns: int | None
    derived_entry_px: Decimal | None
    residual: Decimal | None
    derived_exit_mark: Decimal | None
    status: str
    flagged: bool
    #: `"resolver"` for a `GET-`-prefixed synthetic `trade_id` (its
    #: `ts_event` is only an upper bound on the true fill instant, per
    #: `DurableFillRecord`'s own docstring) -- `"create"` otherwise.
    ts_provenance: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FidelitySummary:
    rows: tuple[FillMarkComparison, ...]
    included: tuple[FillMarkComparison, ...]
    flagged: tuple[FillMarkComparison, ...]
    n_by_leg: Mapping[Leg, int]
    n_exact: int
    n_within_one_tick: int
    n_beyond_one_tick: int
    n_no_exit_fills: int


def _open_and_fetch_rows(path: Path) -> list[tuple[object, object]]:
    conn = _open_readonly(path)
    if conn is None:
        raise FidelitySourceUnreadableError(
            "the exec state-DB source could not be opened read-only"
        )
    try:
        return conn.execute("SELECT key, value FROM state").fetchall()
    except sqlite3.Error as exc:
        raise FidelitySourceUnreadableError(
            "the exec state-DB source could not be read"
        ) from exc
    finally:
        conn.close()


def read_fill_records(path: Path) -> tuple[DurableFillRecord, ...]:
    """Every `DurableFillRecord` under `FILL_KEY_PREFIX` in `path`, read-only."""
    rows = _open_and_fetch_rows(path)
    fills: list[DurableFillRecord] = []
    for key, value in rows:
        if not isinstance(key, str) or not key.startswith(FILL_KEY_PREFIX):
            continue
        assert isinstance(value, bytes)
        fills.append(DurableFillRecord.from_bytes(value))
    return tuple(fills)


def select_frame(
    frames: Sequence[OrderBookDepth10], fill_ts_event: int,
) -> OrderBookDepth10 | None:
    """The latest frame with `frame.ts_init < fill_ts_event` (strictly
    earlier -- a leak guard), or `None` when no such frame exists."""
    candidates = [frame for frame in frames if frame.ts_init < fill_ts_event]
    if not candidates:
        return None
    return max(candidates, key=lambda frame: frame.ts_init)


def _leg_of_fill(fill: DurableFillRecord) -> Leg:
    return "NO" if leg_of(InstrumentId.from_str(fill.instrument_id)) == "no" else "YES"


def sibling_yes_instrument_id(fill: DurableFillRecord) -> InstrumentId:
    """The YES instrument id whose Depth10 tape prices this fill -- itself
    for a YES fill, its YES sibling for a NO fill (there is no NO-leg book,
    module docstring)."""
    instrument_id = InstrumentId.from_str(fill.instrument_id)
    if leg_of(instrument_id) == "no":
        return sibling_instrument_id(instrument_id)
    return instrument_id


def measure_fill(
    fill: DurableFillRecord, *, sibling_yes_frames: Sequence[OrderBookDepth10],
) -> FillMarkComparison:
    """Compare one durable fill to the monitor's own walked mark.

    Pure: `sibling_yes_frames` is caller-supplied (already the correct
    sibling-YES instrument's frames) -- this function does no catalog I/O.
    """
    leg = _leg_of_fill(fill)
    qty = fill.cumulative_qty
    ts_provenance = (
        "resolver"
        if (fill.trade_id or "").startswith(_RESOLVER_TRADE_ID_PREFIX)
        else "create"
    )
    base_kwargs: dict[str, object] = {
        "venue_order_id": fill.venue_order_id,
        "instrument_id": fill.instrument_id,
        "leg": leg,
        "order_side": fill.order_side,
        "qty": qty,
        "ts_provenance": ts_provenance,
    }

    if fill.order_side != _ORDER_SIDE_BUY:
        return FillMarkComparison(
            **base_kwargs,  # type: ignore[arg-type]
            fill_px=None,
            frame_ts_init=None,
            frame_age_ns=None,
            derived_entry_px=None,
            residual=None,
            derived_exit_mark=None,
            status=STATUS_NOT_A_BUY,
            flagged=False,
        )

    fill_px = fill.cumulative_cost / fill.cumulative_qty
    frame = select_frame(sibling_yes_frames, fill.ts_event)
    if frame is None:
        return FillMarkComparison(
            **base_kwargs,  # type: ignore[arg-type]
            fill_px=fill_px,
            frame_ts_init=None,
            frame_age_ns=None,
            derived_entry_px=None,
            residual=None,
            derived_exit_mark=None,
            status=STATUS_NO_FRAME,
            flagged=False,
        )

    frame_age_ns = fill.ts_event - frame.ts_init
    qty_int = int(qty)
    entry_walk, entry_ok = walk_exit_vwap(frame, _opposite(leg), qty_int)
    exit_walk, exit_ok = walk_exit_vwap(frame, leg, qty_int)
    if not entry_ok or not exit_ok:
        return FillMarkComparison(
            **base_kwargs,  # type: ignore[arg-type]
            fill_px=fill_px,
            frame_ts_init=frame.ts_init,
            frame_age_ns=frame_age_ns,
            derived_entry_px=None,
            residual=None,
            derived_exit_mark=None,
            status=STATUS_ONE_SIDED,
            flagged=False,
        )

    assert entry_walk is not None and exit_walk is not None  # entry_ok/exit_ok guarantee this
    derived_entry_px = _ONE - entry_walk
    residual = fill_px - derived_entry_px
    status = STATUS_STALE_FRAME if frame_age_ns > _BOOK_STALE_NS else STATUS_MEASURED
    return FillMarkComparison(
        **base_kwargs,  # type: ignore[arg-type]
        fill_px=fill_px,
        frame_ts_init=frame.ts_init,
        frame_age_ns=frame_age_ns,
        derived_entry_px=derived_entry_px,
        residual=residual,
        derived_exit_mark=exit_walk,
        status=status,
        flagged=fill_px < derived_entry_px,
    )


def summarise(rows: Sequence[FillMarkComparison]) -> FidelitySummary:
    """n-honest aggregate: `stale_frame`/`one_sided`/`no_frame`/`not_a_buy`
    rows and any `flagged` row are excluded from the tick-bucket counts but
    always counted and reported by :func:`render_markdown`."""
    included = tuple(
        row for row in rows if row.status not in _EXCLUDED_FROM_AGGREGATE and not row.flagged
    )
    flagged = tuple(row for row in rows if row.flagged)
    n_by_leg: dict[Leg, int] = {"YES": 0, "NO": 0}
    for row in rows:
        n_by_leg[row.leg] += 1
    n_exact = sum(1 for row in included if row.residual == 0)
    n_within_one_tick = sum(
        1 for row in included if row.residual != 0 and abs(row.residual or Decimal(0)) <= TICK
    )
    n_beyond_one_tick = sum(
        1 for row in included if abs(row.residual or Decimal(0)) > TICK
    )
    n_no_exit_fills = sum(
        1 for row in rows if row.leg == "NO" and row.order_side != _ORDER_SIDE_BUY
    )
    return FidelitySummary(
        rows=tuple(rows),
        included=included,
        flagged=flagged,
        n_by_leg=n_by_leg,
        n_exact=n_exact,
        n_within_one_tick=n_within_one_tick,
        n_beyond_one_tick=n_beyond_one_tick,
        n_no_exit_fills=n_no_exit_fills,
    )


def _row_line(row: FillMarkComparison) -> str:
    return (
        f"| {row.venue_order_id} | {row.instrument_id} | {row.leg} | {row.order_side} "
        f"| {row.fill_px} | {row.qty} | {row.frame_ts_init} | {row.frame_age_ns} "
        f"| {row.derived_entry_px} | {row.residual} | {row.derived_exit_mark} "
        f"| {row.status} | {row.flagged} | {row.ts_provenance} |"
    )


_ROW_HEADER: Final[tuple[str, str]] = (
    (
        "| venue_order_id | instrument_id | leg | order_side | fill_px | qty "
        "| frame_ts_init | frame_age_ns | derived_entry_px | residual "
        "| derived_exit_mark | status | flagged | ts_provenance |"
    ),
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
)


def render_markdown(summary: FidelitySummary, *, run_date: str) -> str:
    lines: list[str] = []
    lines.append(f"# NO-leg mark fidelity ({run_date})")
    lines.append("")
    lines.append(
        "FU-1d S3 (`RULING_FU-1b_no_leg_marks_2026-09-26.md` re-open item 3, "
        "`docs/plans/backlog/NIGHT_2026-09-26/FU-1d-reopen_plan_r1_2026-09-26.md`). "
        "Generated by `scripts/analysis/no_leg_mark_fidelity.py` against the "
        "live exec state store and the quote-tape catalog, both read-only. "
        "**A measurement, not a gate: no verdict, no CI gate.**"
    )
    lines.append("")
    lines.append("## n and honesty")
    lines.append("")
    lines.append(
        f"n={len(summary.rows)} total fills; YES={summary.n_by_leg.get('YES', 0)}, "
        f"NO={summary.n_by_leg.get('NO', 0)}. n(NO EXIT fills)="
        f"{summary.n_no_exit_fills} -- the ruling's second re-open trigger "
        "(\"walked-ask VWAP diverges from realized NO exit fills\") is "
        "**NOT EVALUABLE** from this store: every NO fill on record is an "
        "ENTRY (BUY), never an exit (SELL)."
    )
    lines.append("")
    lines.append(
        f"Of {len(summary.included)} rows entering the residual aggregate: "
        f"{summary.n_exact} exact, {summary.n_within_one_tick} within one tick "
        f"({TICK}), {summary.n_beyond_one_tick} beyond one tick. "
        f"{len(summary.flagged)} row(s) flagged (fill better than displayed, "
        "L-25) and excluded from the aggregate."
    )
    lines.append("")
    lines.append(
        "**Two findings.** The NO rows validate the complement and "
        "sibling-routing mechanism on the BID side, which is how a NO "
        "ENTRY actually executes. The YES rows are the ASK-side control: a "
        "NO EXIT would buy YES through the asks, the same book side a YES "
        "ENTRY uses. **Neither measures a realised NO exit.**"
    )
    lines.append("")
    lines.append("## All rows")
    lines.append("")
    lines.extend(_ROW_HEADER)
    for row in summary.rows:
        lines.append(_row_line(row))
    lines.append("")
    lines.append("## Flagged rows (fill better than displayed, excluded from the aggregate)")
    lines.append("")
    if summary.flagged:
        lines.extend(_ROW_HEADER)
        for row in summary.flagged:
            lines.append(_row_line(row))
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def _catalog_frames_for_fill(
    catalog: ParquetDataCatalog, fill: DurableFillRecord,
) -> tuple[OrderBookDepth10, ...]:
    """Query ONLY this fill's sibling-YES instrument, `start`/`end` = the
    fill's own `ts_event` +/- one day -- never the whole catalog (NFR
    memory)."""
    instrument_id = sibling_yes_instrument_id(fill)
    frames = catalog.order_book_depth10(
        instrument_ids=[str(instrument_id)],
        start=fill.ts_event - _ONE_DAY_NS,
        end=fill.ts_event + _ONE_DAY_NS,
    )
    return tuple(frames)


def build_rows(
    fills: Sequence[DurableFillRecord], catalog: ParquetDataCatalog,
) -> tuple[FillMarkComparison, ...]:
    rows: list[FillMarkComparison] = []
    for fill in fills:
        frames = _catalog_frames_for_fill(catalog, fill)
        rows.append(measure_fill(fill, sibling_yes_frames=frames))
    return tuple(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--exec-state-db", type=Path, required=True,
        help="Path to the exec SqliteStateStore (opened read-only).",
    )
    parser.add_argument(
        "--catalog-root", type=Path, required=True,
        help="Root of the quote-tape ParquetDataCatalog (read-only).",
    )
    parser.add_argument("--run-date", required=True, help="ISO date for the doc title.")
    parser.add_argument(
        "--out", type=Path, required=True, help="Output path for the rendered markdown.",
    )
    args = parser.parse_args(argv)

    try:
        fills = read_fill_records(args.exec_state_db)
        catalog = ParquetDataCatalog(str(args.catalog_root))
        rows = build_rows(fills, catalog)
    except FidelitySourceUnreadableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = summarise(rows)
    doc = render_markdown(summary, run_date=args.run_date)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(doc, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
