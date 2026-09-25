"""AUD-12a: measured slippage from the live fills' fills-derived sub-question.

`docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md`
sub-item (a) ONLY -- (b) (fee-drift probe) is a separate item.

`breezy.strategy.weather_common.costs`'s `slippage_prob` has been a hardcoded
``0.01`` placeholder, documented as UNMEASURED. This script answers the
narrower "slippage derived from realised fills" sub-question the module's own
docstring names, joining each live fill's price
(`DurableFillRecord.cumulative_cost / cumulative_qty`, the durable per-order
record `exec/polymarket_us/fill/{venue_order_id}`) to the decision-time ask
that fill's own trial recorded (`TrialDayRecord.ask`, the durable
`continuous_rung_hold/trial/{station}/{climate_day}/{instrument_id}` record --
"the DECISION-time ask `_hunt_tick` captured for this station-day, never the
fill price", `continuous_strategy.py`'s own `_consume_or_flag_duplicate`
docstring), via the SAME `venue_order_id` Slice 4 item A wrote onto the latch.

Both stores are opened READ-ONLY (`mode=ro` URI, no flock, no write lock) via
`fill_time_count._open_readonly` -- reused, never reimplemented -- so this
script cannot contend with the live node's own writer. `CurrentRungHoldConfig
.order_quantity` is pinned to 1 contract, so `level0_ask`/`decision_ask` and
s8.5's `vwap_ask_at_intended_size` coincide for every fill measured here (a
future reader sizing above 1 contract would need to re-establish that
equivalence).

FLAGGED-FILL DISPOSITION (plan §6 item 1): a fill with `fill_px <
decision_ask` -- impossible for a BUY IOC at `limit=ask` under the same
model `paper_replay.ImpossibleFillPriceError` already enforces for the paper
path -- is the L-25 defect signature. It is EXCLUDED from the
mean/median/range aggregate but never silently dropped: it is still counted
and reported by value, separately.

UNRESOLVED FILLS: a fill with no matching TAKEN trial record (its
`venue_order_id` never appears in the trial store) has no known
decision-time ask at all. It is neither included nor flagged -- reported
separately, by `venue_order_id` only.

§7 STEP 0 PRE-CHECK: counts `decision="refuse"` records with a non-null
`ask` in each `offer_tape_<climate_day>.jsonl` sidecar
(`current_rung_hold/offer_tape.py`'s `OfferTapeRecord`) -- NOT
`TrialDayLatch`/`StateStore`, which never durably records a Refuse at all
(plan §2 round 3). Decoded via `OfferTapeRecord.from_dict`, the existing
reader half of `to_dict` -- reused, not reimplemented.

This script makes NO change to `DOCUMENTED_TAKER_FEE_COEFFICIENT` or the
`0.01` slippage placeholder; it only measures and reports.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.strategy.current_rung_hold.offer_tape import OfferTapeRecord
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TrialDayRecord,
    TrialDayRecordCorrupt,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
# ONE implementation, reused -- the same idiom score_live_trials.py uses.
from fill_time_count import _open_readonly

#: The live v3 ("continuous rung hold") family's own trial-latch key prefix
#: (confirmed against the live store this session -- every populated
#: `venue_order_id` in the durable store sits under this literal prefix, per
#: `deploy/systemd/score-live-trials-run.sh`'s own comment: "live
#: `pm_us_crh_cont` family, `continuous_rung_hold/trial/`"). Deliberately
#: NOT `trial_day_latch.DEFAULT_TRIAL_KEY_PREFIX` (`"current_rung_hold/
#: trial/"`), which is a DIFFERENT, older key namespace still present in the
#: same shared store from an earlier family.
DEFAULT_FAMILY_PREFIX: Final[str] = "continuous_rung_hold/trial/"

_TAKEN_REASON: Final[str] = "taken"


class SlippageSourceUnreadableError(Exception):
    """A durable store could not be opened read-only or read.

    Mirrors `score_live_trials.FillSourceUnreadableError`: the caller
    decides what a non-zero exit looks like; this exception never embeds a
    path or a store value.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class MeasuredSlippage:
    """One fill's measured slippage: `fill_px - decision_ask`."""

    venue_order_id: str
    instrument_id: str
    decision_ask: Decimal
    fill_px: Decimal
    slippage: Decimal
    #: `True` iff `slippage < 0` -- a fill better than its own decision-time
    #: ask, impossible under the BUY-IOC-at-limit-ask model (L-25 defect
    #: signature). Excluded from the aggregate, never from the report.
    flagged: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class SlippageSummary:
    """n-honest aggregate over `join_fills_to_decision_ask`'s output."""

    included: tuple[MeasuredSlippage, ...]
    flagged: tuple[MeasuredSlippage, ...]
    unresolved_venue_order_ids: tuple[str, ...]
    mean: Decimal | None
    median: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None


def _open_and_fetch_rows(path: Path) -> list[tuple[object, object]]:
    conn = _open_readonly(path)
    if conn is None:
        raise SlippageSourceUnreadableError(
            "a durable state-DB source could not be opened read-only"
        )
    try:
        return conn.execute("SELECT key, value FROM state").fetchall()
    except sqlite3.Error as exc:
        raise SlippageSourceUnreadableError(
            "a durable state-DB source could not be read"
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
        fills.append(DurableFillRecord.from_bytes(value))
    return tuple(fills)


def read_taken_trial_records_by_venue_order_id(
    path: Path, *, family_prefix: str = DEFAULT_FAMILY_PREFIX,
) -> dict[str, TrialDayRecord]:
    """Every TAKEN `TrialDayRecord` under `family_prefix`, keyed by its own
    `venue_order_id` (Slice 4 item A). A record whose `reason != "taken"` or
    whose `venue_order_id` is `None` (a pre-Slice-4 record, or a genuine
    refusal) is skipped -- this join only ever needs a CONSUMED trial's own
    recorded venue order id.

    A second, short-lived read-only connection over the SAME store
    `read_fill_records` reads -- mirrors `score_live_trials.py`'s own
    two-separate-fetches idiom rather than widening either function's return
    shape to carry both.
    """
    rows = _open_and_fetch_rows(path)
    by_venue_order_id: dict[str, TrialDayRecord] = {}
    for key, value in rows:
        if not isinstance(key, str) or not key.startswith(family_prefix):
            continue
        try:
            record = TrialDayRecord.from_bytes(value)
        except TrialDayRecordCorrupt as exc:
            raise SlippageSourceUnreadableError(
                f"a record under the {family_prefix!r} key prefix could not be decoded"
            ) from exc
        if record.reason != _TAKEN_REASON or record.venue_order_id is None:
            continue
        by_venue_order_id[record.venue_order_id] = record
    return by_venue_order_id


def join_fills_to_decision_ask(
    fills: Sequence[DurableFillRecord],
    trial_records_by_venue_order_id: Mapping[str, TrialDayRecord],
) -> tuple[tuple[MeasuredSlippage, ...], tuple[str, ...]]:
    """Join each fill to its decision-time ask by `venue_order_id`.

    Returns `(measurements, unresolved_venue_order_ids)`. A fill with no
    matching TAKEN trial record has no known decision-time ask -- it is
    reported in the second tuple, never silently dropped nor coerced into a
    measurement with a fabricated ask.
    """
    measurements: list[MeasuredSlippage] = []
    unresolved: list[str] = []
    for fill in fills:
        record = trial_records_by_venue_order_id.get(fill.venue_order_id)
        if record is None:
            unresolved.append(fill.venue_order_id)
            continue
        fill_px = fill.cumulative_cost / fill.cumulative_qty
        slippage = fill_px - record.ask
        measurements.append(
            MeasuredSlippage(
                venue_order_id=fill.venue_order_id,
                instrument_id=fill.instrument_id,
                decision_ask=record.ask,
                fill_px=fill_px,
                slippage=slippage,
                flagged=slippage < 0,
            )
        )
    return tuple(measurements), tuple(unresolved)


def summarize_slippage(
    measurements: Sequence[MeasuredSlippage],
    *,
    unresolved_venue_order_ids: Sequence[str] = (),
) -> SlippageSummary:
    """n-honest summary: a flagged fill is excluded from the aggregate but
    always counted and reported (plan §6 item 1's disposition rule)."""
    flagged = tuple(m for m in measurements if m.flagged)
    included = tuple(m for m in measurements if not m.flagged)
    if not included:
        return SlippageSummary(
            included=included,
            flagged=flagged,
            unresolved_venue_order_ids=tuple(unresolved_venue_order_ids),
            mean=None,
            median=None,
            minimum=None,
            maximum=None,
        )
    values = sorted(m.slippage for m in included)
    n = len(values)
    mean = sum(values) / n
    median = values[n // 2] if n % 2 == 1 else (values[n // 2 - 1] + values[n // 2]) / 2
    return SlippageSummary(
        included=included,
        flagged=flagged,
        unresolved_venue_order_ids=tuple(unresolved_venue_order_ids),
        mean=mean,
        median=median,
        minimum=values[0],
        maximum=values[-1],
    )


def count_refused_priced_offer_tape_records(paths: Iterable[Path]) -> dict[str, int]:
    """§7 step 0: per-file count of `decision="refuse"` records with a
    non-null `ask` -- a triggered evaluation that priced the market but did
    not result in a Take. Decoded via `OfferTapeRecord.from_dict`."""
    counts: dict[str, int] = {}
    for path in paths:
        count = 0
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                record = OfferTapeRecord.from_dict(json.loads(stripped))
                if record.decision == "refuse" and record.ask is not None:
                    count += 1
        counts[path.name] = count
    return counts


#: §6 item 2 (round 4 corrected): the field-by-field comparison of
#: `OfferTapeRecord`'s existing schema against bl19 s8.5's specified 16-field
#: per-station-day column list, verbatim from the peer-reviewed plan.
_S8_5_FIELD_TABLE_ROWS: Final[tuple[str, ...]] = (
    "| s8.5 field | `OfferTapeRecord` equivalent | Status |",
    "|---|---|---|",
    "| `station` | `station` | present |",
    "| `climate_day` | `climate_day` | present |",
    (
        "| `cli_received_ts` | -- (`observed_at_ns`/`ts_event` are present "
        "but are NOT treated as equivalents: `ts_event` is the record's "
        "Nautilus event time and `observed_at_ns` is a market-data-arrival "
        "timestamp, neither measures the NWS-CLI-retrieval clock s8.5 "
        "specifies) | **missing** |"
    ),
    "| `printed_value` (tmax_f) | -- | **missing** |",
    "| `is_final` | -- | **missing** |",
    "| `correction_flag` | -- | **missing** |",
    "| `revision_seq` | -- | **missing** |",
    "| `mapped_instrument_id` | `instrument_id` | present |",
    (
        "| bucket bounds | -- (`width_code`/`m_code` encode cell geometry, "
        "not raw bounds) | **missing** (partial via width/m code, not the "
        "raw bounds) |"
    ),
    (
        "| `hours_to_settlement` | -- (`minutes_since_window_open` is a "
        "different clock) | **missing** |"
    ),
    "| `level0_ask` | `ask` | present |",
    "| `ask_size` | `size` | present |",
    (
        "| `vwap_ask_at_intended_size` | `ask` (coincides at "
        "`order_quantity=1`, per §2) | present-by-equivalence, not a "
        "distinct field |"
    ),
    "| `fee_coefficient` | `fee_coefficient` | present |",
    (
        "| computed edge at `slippage_prob` in {0.000, 0.010} | "
        "`p_bound`/`break_even` (edge proxies, not a dual-slippage "
        "computation) | **partial** -- not the exact dual-value edge s8.5 "
        "specifies |"
    ),
    "| first gate that stopped it | `reason` | present |",
)
_S8_5_FIELD_TABLE: Final[str] = "\n".join(_S8_5_FIELD_TABLE_ROWS) + "\n"

_S8_5_MISSING_FIELDS: Final[tuple[str, ...]] = (
    "cli_received_ts",
    "printed_value",
    "is_final",
    "correction_flag",
    "revision_seq",
    "hours_to_settlement",
    "raw bucket bounds",
)


def render_evidence_doc(
    summary: SlippageSummary,
    *,
    offer_tape_counts: Mapping[str, int],
    family_prefix: str,
    run_date: str,
) -> str:
    """Render `docs/evidence/MEASURED_SLIPPAGE_<run_date>.md`'s content."""
    n_included = len(summary.included)
    n_flagged = len(summary.flagged)
    n_unresolved = len(summary.unresolved_venue_order_ids)
    total_refused_priced = sum(offer_tape_counts.values())

    lines: list[str] = []
    lines.append(f"# Measured slippage from the live fills ({run_date})")
    lines.append("")
    lines.append(
        "AUD-12a (`docs/plans/backlog/AUDIT_2026-09-21/"
        "AUD-12-cost-model-slippage-and-fee-drift.md`, sub-item (a) ONLY -- "
        "(b), the fee-drift probe, is a separate item). Generated by "
        "`scripts/analysis/measured_slippage_from_fills.py` against the "
        "live exec state store, read-only."
    )
    lines.append("")
    lines.append("## Scope statement")
    lines.append("")
    lines.append(
        "This item answers ONLY the fills-derived sub-question "
        "`breezy.strategy.weather_common.costs`'s own docstring names -- "
        "`fill_px - decision_ask` per realised fill, joined by "
        "`venue_order_id` between the durable "
        f"`{family_prefix}` trial record and the durable "
        "`exec/polymarket_us/fill/*` record. It does NOT build BL-19 s8.5's "
        "full per-station-day record (every REFUSED station-day too, "
        "regardless of whether an order forms) -- that residual scope is "
        "characterised below, not assumed."
    )
    lines.append("")
    lines.append("## n and honesty")
    lines.append("")
    lines.append(
        f"n={n_included} included, {n_flagged} flagged (excluded from the "
        f"aggregate, reported separately), {n_unresolved} unresolved "
        "(a fill with no matching TAKEN trial record -- its decision-time "
        "ask is unknown, so it is neither included nor flagged)."
    )
    lines.append("")
    lines.append(
        f"n={n_included} cannot support a confidence interval that excludes "
        "the current 0.01 placeholder with confidence. This figure is "
        "reported for honesty and future accumulation, not as a "
        "replacement for the placeholder."
    )
    lines.append("")
    lines.append("## Included fills")
    lines.append("")
    lines.append("| venue_order_id | instrument_id | decision_ask | fill_px | slippage |")
    lines.append("|---|---|---|---|---|")
    for m in summary.included:
        lines.append(
            f"| {m.venue_order_id} | {m.instrument_id} | {m.decision_ask} "
            f"| {m.fill_px} | {m.slippage} |"
        )
    lines.append("")
    lines.append("## Aggregate over included fills")
    lines.append("")
    lines.append(f"mean={summary.mean}, median={summary.median}, "
                  f"range=[{summary.minimum}, {summary.maximum}]")
    lines.append("")
    lines.append("## Flagged fills (L-25 defect signature, excluded from the aggregate)")
    lines.append("")
    if summary.flagged:
        lines.append("| venue_order_id | instrument_id | decision_ask | fill_px | slippage |")
        lines.append("|---|---|---|---|---|")
        for m in summary.flagged:
            lines.append(
                f"| {m.venue_order_id} | {m.instrument_id} | {m.decision_ask} "
                f"| {m.fill_px} | {m.slippage} |"
            )
    else:
        lines.append("None.")
    lines.append("")
    lines.append("## Unresolved fills (no matching TAKEN trial record)")
    lines.append("")
    if summary.unresolved_venue_order_ids:
        for venue_order_id in summary.unresolved_venue_order_ids:
            lines.append(f"- {venue_order_id}")
    else:
        lines.append("None.")
    lines.append("")
    lines.append(
        "## §7 step 0 pre-check: refused-but-priced station-days "
        "(`offer_tape_<climate_day>.jsonl`)"
    )
    lines.append("")
    lines.append(
        "Counted from `OfferTapeRecord` (never `TrialDayLatch`/`StateStore`, "
        "which never durably records a Refuse at all):"
    )
    lines.append("")
    for filename, count in sorted(offer_tape_counts.items()):
        lines.append(f"- {filename}: {count}")
    lines.append(f"- **total: {total_refused_priced}**")
    lines.append("")
    lines.append("## §6 item 2: s8.5 field coverage in `OfferTapeRecord`")
    lines.append("")
    lines.append(_S8_5_FIELD_TABLE)
    lines.append("")
    lines.append(
        "**Conclusion:** `OfferTapeRecord` already carries 7 of 16 s8.5 "
        "fields verbatim (station, climate_day, instrument_id, ask, size, "
        "fee_coefficient, reason) plus one present-by-equivalence "
        "(`vwap_ask_at_intended_size`, only true at `order_quantity=1`) and "
        "one partial (edge proxies, not the exact dual-slippage "
        "computation). **Seven** fields remain genuinely absent: "
        + ", ".join(f"`{f}`" for f in _S8_5_MISSING_FIELDS)
        + ". The correct characterisation is neither \"unbuilt\" nor "
        "\"fulfilled\" -- it is **partially covered by an existing "
        "artefact**."
    )
    lines.append("")
    lines.append("## costs.py placeholder")
    lines.append("")
    lines.append(
        "`DOCUMENTED_TAKER_FEE_COEFFICIENT` and the `0.01` slippage "
        "placeholder constant in `src/breezy/strategy/weather_common/costs.py` "
        "are BYTE-UNCHANGED by this item."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--state-db-path",
        type=Path,
        default=Path.home() / ".local/share/breezy/state/exec_polymarket_us.sqlite",
        help="Path to the exec SqliteStateStore (opened read-only).",
    )
    parser.add_argument(
        "--decisions-dir",
        type=Path,
        default=Path.home() / ".local/share/breezy/catalog/quote_tape/decisions",
        help="Directory containing offer_tape_<date>.jsonl sidecars.",
    )
    parser.add_argument("--family-prefix", default=DEFAULT_FAMILY_PREFIX)
    parser.add_argument("--run-date", required=True, help="ISO date for the doc title/filename.")
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output path for the rendered evidence markdown.",
    )
    args = parser.parse_args(argv)

    fills = read_fill_records(args.state_db_path)
    trial_records = read_taken_trial_records_by_venue_order_id(
        args.state_db_path, family_prefix=args.family_prefix,
    )
    measurements, unresolved = join_fills_to_decision_ask(fills, trial_records)
    summary = summarize_slippage(measurements, unresolved_venue_order_ids=unresolved)

    offer_tape_paths = sorted(args.decisions_dir.glob("offer_tape_*.jsonl"))
    offer_tape_counts = count_refused_priced_offer_tape_records(offer_tape_paths)

    doc = render_evidence_doc(
        summary,
        offer_tape_counts=offer_tape_counts,
        family_prefix=args.family_prefix,
        run_date=args.run_date,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(doc, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
