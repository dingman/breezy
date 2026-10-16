"""MAKER S1 WP2: resolve ``TRADE_QUANTITY_UNIT`` from our own fills (the run is a later step).

Plan r3 WP2 (``docs/plans/backlog/MAKER_2026-10-12/S1_preconditions_plan_r3.md``). Reads the durable
create-path fills (``exec/polymarket_us/fill/<venueOrderId>``) from the exec-state store, opened
``mode=ro`` only (``fill_source.read_durable_fills``), keeps the fills the pure core allows
(``trade_quantity_unit.keep_decision``), asserts the kept set equals the 28 trade ids pinned in the
SEARCH declaration (a mismatch prints the diff to stderr and exits non-zero before any verdict),
then matches each kept fill to the recorded prints and emits ONE JSON result on stdout.

``--prints`` is a JSONL of ``trade_quantity_unit.Print`` rows (shape documented in that module).
Station and climate day come ONLY from ``bucket_facts_from_instrument_id`` (L-56; PM.us band edges
are inclusive). The post-freeze firewall is ``maker_tape_census.require_firewall_clearance`` (WP1),
called with the declaration's sha256; it is imported lazily so this script and its tests do not
depend on WP1 being merged.

Exit codes: 0 verdict emitted, 2 bad input, 3 pinned-set mismatch, 4 a STOP (S-2 or S-3) fired
(the JSON is still printed), 5 the firewall module is unavailable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from breezy.analysis.labeling.fill_source import FillStoreCorruption, read_durable_fills
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.trade_quantity_unit import (
    MATCH_BASIS,
    Clearance,
    ClearanceRefused,
    Fill,
    Print,
    candidates_of,
    classify_trade_quantity_unit,
    consistent_hypotheses,
    counted_matches,
    inversion_verdict,
    is_counted,
    keep_decision,
    match_fill,
    parse_print,
)

EXIT_OK = 0
EXIT_BAD_INPUT = 2
EXIT_PIN_MISMATCH = 3
EXIT_STOP = 4
EXIT_NO_FIREWALL = 5

_REPO = Path(__file__).resolve().parents[2]
DEFAULT_DB = Path.home() / ".local/share/breezy/state/exec_polymarket_us.sqlite"
DEFAULT_DECLARATION = _REPO / "docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md"
_UNRESOLVED_STATION = "UNRESOLVED"
_TRADE_ID_CELL = re.compile(r"^[A-Z0-9]+$")


def read_pinned_trade_ids(declaration: Path) -> frozenset[str]:
    """Trade ids of the declaration's ``Kept (N)`` table (the Excluded table is not read)."""
    ids: set[str] = set()
    in_kept = False
    for line in declaration.read_text(encoding="utf-8").splitlines():
        if line.startswith("Kept ("):
            in_kept = True
        elif line.startswith("Excluded ("):
            break
        elif in_kept and line.startswith("|"):
            first = line.split("|")[1].strip()
            if _TRADE_ID_CELL.match(first):
                ids.add(first)
    return frozenset(ids)


def load_fills(db: Path) -> list[Fill]:
    """Every durable fill, resolved to station/day via ``bucket_facts_from_instrument_id`` only."""
    fills = []
    for record in read_durable_fills(db).require_clean().fills:
        facts = bucket_facts_from_instrument_id(record.instrument_id)
        fills.append(
            Fill(
                venue_order_id=record.venue_order_id,
                instrument_id=record.instrument_id,
                order_side=record.order_side,
                qty=record.cumulative_qty,
                cost=record.cumulative_cost,
                ts_event_ns=record.ts_event,
                trade_id=record.trade_id,
                fee_reconciled=record.fee_reconciled,
                station=_UNRESOLVED_STATION if facts is None else facts.settlement_station,
                climate_day=dt.date.min if facts is None else facts.climate_day,
            )
        )
    return sorted(fills, key=lambda f: (f.ts_event_ns, f.venue_order_id))


def load_prints(path: Path) -> tuple[list[Print], int]:
    """Parsed prints, deduplicated on ``trade_id`` (first wins), and the duplicate count."""
    seen: dict[str, Print] = {}
    duplicates = 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = parse_print(json.loads(line))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path}:{lineno}: {exc}") from exc
        if row.trade_id in seen:
            duplicates += 1
        else:
            seen[row.trade_id] = row
    return list(seen.values()), duplicates


def firewall_clearance(declaration_sha256: str) -> Clearance:
    """WP1's ``require_firewall_clearance`` bound to the declaration hash.

    The library path clears days only through registry row 0; any row >= 1 (the second-look
    declarations) is refused here, by sha at construction and by day at clearance time.
    """
    census = importlib.import_module("breezy.analysis.maker_tape_census")
    registry = importlib.import_module("breezy.analysis.maker_search_declarations")
    refused = census.FirewallRefused
    if declaration_sha256 in {row.sha256 for row in registry.SEARCH_DECLARATIONS[1:]}:
        raise ClearanceRefused("the second-look declaration is not clearable by this crosscheck")

    def clearance(station: str, day: dt.date) -> None:
        row = registry.declaration_row(station, day)
        if row is not None and row >= 1:
            raise ClearanceRefused(
                f"{station} {day.isoformat()} belongs to a second-look declaration row"
            )
        try:
            census.require_firewall_clearance(station, day, declaration_sha256)
        except refused as exc:
            raise ClearanceRefused(str(exc)) from exc

    return clearance


def _fill_row(fill: Fill, prints: Sequence[Print]) -> dict[str, Any]:
    match = match_fill(fill, prints)
    return {
        "venue_order_id": fill.venue_order_id,
        "trade_id": fill.trade_id,
        "station": fill.station,
        "climate_day": fill.climate_day.isoformat(),
        "leg": fill.leg,
        "qty": str(fill.qty),
        "cost": str(fill.cost),
        "ts_event_ns": fill.ts_event_ns,
        "candidate_count": match.candidate_count,
        "anti_candidate_count": match.anti_candidate_count,
        "summed": match.summed,
        "counted": is_counted(match),
        "match_basis": MATCH_BASIS if is_counted(match) else None,
        "consistent": sorted(consistent_hypotheses(match)),
        "inversion": inversion_verdict(match),
        "candidates": [
            {"trade_id": p.trade_id, "ts_ns": p.ts_ns, "price": str(p.price), "size": str(p.size)}
            for p in candidates_of(fill, prints)
        ],
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--prints", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, default=DEFAULT_DECLARATION)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, clearance: Clearance | None = None) -> int:
    args = _parse_args(argv)
    try:
        declaration_bytes = args.declaration.read_bytes()
        pinned = read_pinned_trade_ids(args.declaration)
        fills = load_fills(args.db)
        prints, duplicates = load_prints(args.prints)
    except (OSError, ValueError, FillStoreCorruption) as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    if clearance is None:
        try:
            clearance = firewall_clearance(hashlib.sha256(declaration_bytes).hexdigest())
        except (ImportError, AttributeError) as exc:
            print(f"firewall module unavailable: {exc}", file=sys.stderr)
            return EXIT_NO_FIREWALL

    decisions = [(fill, keep_decision(fill, clearance)) for fill in fills]
    kept = [fill for fill, decision in decisions if decision.kept]
    derived = frozenset(str(f.trade_id) for f in kept)
    if derived != pinned:
        print(
            "derived kept set differs from the pinned declaration list: "
            f"only derived={sorted(derived - pinned)} only pinned={sorted(pinned - derived)}",
            file=sys.stderr,
        )
        return EXIT_PIN_MISMATCH

    matches = [match_fill(fill, prints) for fill in kept]
    verdict, surviving, reason = classify_trade_quantity_unit(matches)
    rows = [_fill_row(fill, prints) for fill in kept]
    s3 = any(row["inversion"] == "CONTRADICTED" for row in rows)
    s2 = verdict == "UNRESOLVED"
    result: Mapping[str, Any] = {
        "verdict": verdict,
        "surviving": sorted(surviving),
        "reason": reason,
        "n_counted": len(counted_matches(matches)),
        "s2_stop": s2,
        "s3_stop": s3,
        "pinned_set_equal": True,
        "duplicate_prints": duplicates,
        "fills": rows,
        "refused": [
            {
                "venue_order_id": f.venue_order_id,
                "trade_id": f.trade_id,
                "ts_event_ns": f.ts_event_ns,
                "reason": d.reason,
            }
            for f, d in decisions
            if not d.kept
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return EXIT_STOP if (s2 or s3) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
