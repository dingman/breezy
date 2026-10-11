"""TE-2 FQ v1 loss taxonomy: CLI (Phase A outcome-blind, Phase B after the freeze).

``phase-a`` reads fills, node logs and the committed reflog snapshot, and writes the outcome-blind
table (no wins, no P&L, no ``tmax_f``). ``phase-b`` first refuses unless the frozen pins hold
(``phase_b_refusals``), then reproduces the corrected audit through the clipping wrapper. The S0-D
vector reconstruction needs a network fetch and is run by the coordinator, not here.
Plan: docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-2_plan_r3_2.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import re
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from breezy.analysis.labeling.fill_source import FillRead, read_durable_fills
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.labeling.settlement_source import NwsCliFinal
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.catalog import open_station_catalog
from scripts.analysis.fq_loss_taxonomy_core import (
    cluster_probability,
    cluster_station_days,
    lower_tail,
    station_day_probability,
    t_win_testability,
)
from scripts.analysis.fq_loss_taxonomy_inputs import (
    Boot,
    ClippingSettlementSource,
    PinConfig,
    SubprocessGit,
    attribute_fills,
    phase_a_truth,
    phase_b_refusals,
    pin_label,
    reproduce_audit,
    resolve_pins,
    s0a_counts,
    s0a_gate,
    truth_status,
)

__all__ = ["main"]

TERMINAL_CLIMATE_DAY: Final = dt.date(2026, 10, 5)
LAST_CLIMATE_DAY: Final = dt.date(2026, 10, 6)
FQ_WINDOW_START: Final = dt.date(2026, 10, 1)
MANIFEST_PATH: Final = "deploy/families/pm_us_crh_fq_v1.json"
ARTEFACT_PATH: Final = "deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
WIDENED_PATHS: Final = (
    "src/breezy/strategy/forecast_quantile_ladder/",
    "src/breezy/strategy/ladder_ev/",
    "src/breezy/normalize/climate_day.py",
    "src/breezy/ingest/nbm_quantile_actor.py",
    "deploy/families/",
)
PIN_RANGE: Final = ("1d7ea1016d7c", "4ba7f10cd1f6")
AUDIT_NET: Final = Decimal("-2.17")
AUDIT_TOLERANCE: Final = Decimal("0.005")
BOOT_HEADER_LINES: Final = 400
EXIT_STOP: Final = 2
_BOOT_STAMP: Final = re.compile(r"(\d{8}T\d{6})Z")
_MANIFEST_SHA: Final = re.compile(r"manifest_sha256=([0-9a-f]{64})")
_ARTEFACT_SHA: Final = re.compile(r"calibration_sha256=([0-9a-f]{64})")


class _CatalogRouter:
    """The production ``NwsCliFinal`` over one station catalog per station (read-only)."""

    def __init__(self, base: Path) -> None:
        self._base = base
        self._sources: dict[str, NwsCliFinal] = {}

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        if station not in self._sources:
            catalog = open_station_catalog(self._base, "polymarket_us", station)
            self._sources[station] = NwsCliFinal(catalog)
        return self._sources[station].record(station, climate_day)


def _boots_from_logs(logs: Sequence[Path]) -> list[Boot]:
    """One Boot per node log: the boot time from the file name, the logged shas from its head."""
    boots = []
    for number, path in enumerate(sorted(logs), start=1):
        stamp = _BOOT_STAMP.search(path.name)
        if stamp is None:
            raise ValueError(f"cannot read a boot time from {path.name}")
        when = dt.datetime.strptime(stamp.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=dt.UTC)
        manifest = artefact = None
        with path.open(encoding="utf-8", errors="replace") as handle:
            for _, line in zip(range(BOOT_HEADER_LINES), handle, strict=False):
                manifest = manifest or (m.group(1) if (m := _MANIFEST_SHA.search(line)) else None)
                artefact = artefact or (m.group(1) if (m := _ARTEFACT_SHA.search(line)) else None)
        boots.append(Boot(number, when, manifest or "", artefact or ""))
    return boots


def _is_fq_window(instrument_id: str) -> bool:
    facts = bucket_facts_from_instrument_id(instrument_id)
    return facts is not None and facts.climate_day >= FQ_WINDOW_START


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def _station_day_table(
    fills: FillRead, p_hats: Sequence[float]
) -> dict[tuple[str, dt.date], list[float]]:
    by_day: dict[tuple[str, dt.date], list[float]] = {}
    for fill, p_hat in zip(fills.fills, p_hats, strict=True):
        facts = bucket_facts_from_instrument_id(fill.instrument_id)
        assert facts is not None  # s0a_counts already refused an unparseable id
        by_day.setdefault((facts.settlement_station, facts.climate_day), []).append(p_hat)
    return by_day


def _cluster_table(by_day: dict[tuple[str, dt.date], list[float]]) -> list[dict[str, Any]]:
    p_d = {key: station_day_probability(p) for key, p in by_day.items()}
    rows = []
    for cluster in cluster_station_days(sorted(by_day)):
        days = [p_d[(cluster.station, day)] for day in cluster.climate_days]
        rows.append(
            {
                "station": cluster.station,
                "climate_days": [d.isoformat() for d in cluster.climate_days],
                "P_d": days,
                "P_c": cluster_probability(days),
            }
        )
    return rows


def _truth_projection(
    catalog_root: Path | None, days: Sequence[tuple[str, dt.date]]
) -> dict[str, int]:
    """Phase A truth: status counts through the clipping wrapper and the tmax-free projection."""
    if catalog_root is None:
        return {"NOT_CHECKED": len(days)}
    source = ClippingSettlementSource(_CatalogRouter(catalog_root), LAST_CLIMATE_DAY)
    counts: dict[str, int] = {}
    for station, day in days:
        status = truth_status(phase_a_truth(source, station, day, last_day=LAST_CLIMATE_DAY))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _phase_a(args: argparse.Namespace) -> int:
    counts = s0a_counts(args.fills_db, TERMINAL_CLIMATE_DAY)
    s0a_gate(counts)
    fills = read_durable_fills(args.fills_db).require_clean()
    attribution = attribute_fills(fills, args.logs, data_root=args.data_root)
    p_hats = [m.p_at_decision for m in attribution.matches]
    by_day = _station_day_table(fills, p_hats)
    clusters = _cluster_table(by_day)
    p_c = [c["P_c"] for c in clusters]
    git = SubprocessGit(args.repo_root)
    config = PinConfig(MANIFEST_PATH, ARTEFACT_PATH, WIDENED_PATHS)
    pins = resolve_pins(
        args.reflog_snapshot, args.reflog_snapshot_sha256, _boots_from_logs(args.logs), git, config
    )
    payload = {
        "phase": "A",
        "outcome_blind": True,
        "s0a": dataclasses.asdict(counts),
        "s0c": dataclasses.asdict(attribution.report),
        "p_hat_per_fill": [
            {
                "instrument_id": f.instrument_id,
                "p_hat": p,
                "ask_proxy": f.cumulative_cost / f.cumulative_qty,
            }
            for f, p in zip(fills.fills, p_hats, strict=True)
        ],
        "clusters": clusters,
        "t_win_null": {
            "testability": t_win_testability(p_c),
            "min_attainable_p": lower_tail(p_c, 0),
        },
        "pins": [dataclasses.asdict(p) for p in pins],
        "pin_label": pin_label(git, WIDENED_PATHS, *PIN_RANGE),
        "truth_projection": _truth_projection(args.catalog_root, sorted(by_day)),
        "pending_coordinator": ["S0-D reconstruction (fetch)", "S0-G alternative sources"],
    }
    _write_json(args.output_dir / "phase_a_table.json", payload)
    sys.stdout.write(f"phase A table written to {args.output_dir / 'phase_a_table.json'}\n")
    return 0


def _phase_b(args: argparse.Namespace) -> int:
    pins = json.loads(args.pins_json.read_text())
    refusals = phase_b_refusals(
        pins["head_blob_sha256"], pins["predeclaration_commit"], SubprocessGit(args.repo_root)
    )
    if refusals:
        sys.stderr.write(f"PHASE B REFUSED: {[r.value for r in refusals]}\n")
        return EXIT_STOP
    fills = read_durable_fills(args.fills_db).require_clean()
    source = ClippingSettlementSource(_CatalogRouter(args.catalog_root), LAST_CLIMATE_DAY)
    audit = reproduce_audit(fills, source, now_ns=args.now_ns)
    october = tuple(f for f in fills.fills if _is_fq_window(f.instrument_id))
    fq_only = FillRead(fills=october, n_keys=len(october), n_undecodable=0)
    oct_audit = reproduce_audit(fq_only, source, now_ns=args.now_ns)
    ok = (
        oct_audit.n_fills == 25
        and oct_audit.n_wins == 2
        and abs(oct_audit.net_pnl - AUDIT_NET) <= AUDIT_TOLERANCE
    )
    payload = {
        "phase": "B",
        "audit_all": dataclasses.asdict(audit),
        "audit_fq": dataclasses.asdict(oct_audit),
    }
    _write_json(args.output_dir / "phase_b_audit.json", payload)
    if not ok:
        sys.stderr.write("STOP: the corrected audit (25 fills, 2 wins, -2.17) did not reproduce\n")
        return EXIT_STOP
    sys.stdout.write("audit reproduced (classification and tests are WP3)\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    for name in ("phase-a", "phase-b"):
        p = sub.add_parser(name)
        p.add_argument("--fills-db", type=Path, required=True)
        p.add_argument("--output-dir", type=Path, required=True)
        p.add_argument("--repo-root", type=Path, default=Path.cwd())
        p.add_argument("--catalog-root", type=Path, default=None)
    a = sub.choices["phase-a"]
    a.add_argument("--logs", type=Path, nargs="+", required=True)
    a.add_argument("--data-root", type=Path, required=True)
    a.add_argument("--reflog-snapshot", type=Path, required=True)
    a.add_argument("--reflog-snapshot-sha256", required=True)
    b = sub.choices["phase-b"]
    b.add_argument("--pins-json", type=Path, required=True)
    b.add_argument("--now-ns", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.phase == "phase-b":
        if args.catalog_root is None:
            sys.stderr.write("phase-b needs --catalog-root\n")
            return EXIT_STOP
        return _phase_b(args)
    return _phase_a(args)


if __name__ == "__main__":
    raise SystemExit(main())
