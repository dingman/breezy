"""TE-2 FQ v1 loss taxonomy: CLI (Phase A outcome-blind, Phase B after the freeze).

``phase-a`` reads fills, node logs and the committed reflog snapshot, and writes the outcome-blind
table (no wins, no P&L, no ``tmax_f``), including the S0-D p-hat reconstruction over a derived NBP
store that the coordinator fetched beforehand (``nbp_backfill.py``; never run here) and the S0-G
alternative-source discovery. ``phase-b`` first refuses unless the frozen pins, the family pin
coverage and the predeclaration hold, then reproduces the corrected FQ audit (STOP on a mismatch)
and writes the classified result (``fq_loss_taxonomy_phase_b``); it never reads a pre-October
climate day (the frozen holdout, plan P9). ``verify`` checks that the committed result artefact
follows the predeclaration commit.
Plan: docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-2_plan_r3_2.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.analysis.labeling.fill_source import FillRead, read_durable_fills
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.registry.sites import default_registry
from scripts.analysis.fq_loss_taxonomy_core import (
    lower_tail,
    t_win_testability,
)
from scripts.analysis.fq_loss_taxonomy_inputs import (
    Boot,
    BootPin,
    ClippingSettlementSource,
    FillSpec,
    PinConfig,
    Reconstructor,
    S0AStop,
    S0DStop,
    SubprocessGit,
    UnclassifiedFillsStop,
    UnparseableInstrumentStop,
    attribute_fills,
    boot_for,
    day_and_cluster_rows,
    discover_alt_sources,
    fill_rows,
    iter_partition_events,
    load_derived_cycles,
    partition_union,
    phase_a_truth,
    pin_label,
    published_cycles,
    reconstruct_all,
    resolve_pins,
    s0a_counts,
    s0a_gate,
    s0d_gate,
    truth_status,
    vector_table,
)
from scripts.analysis.fq_loss_taxonomy_inputs import (
    CatalogRouter as _CatalogRouter,
)
from scripts.analysis.fq_loss_taxonomy_phase_b import (
    EXIT_STOP,
    PhaseBInputs,
    PhaseBRefused,
    check_gates,
    execute,
    verify_artefact,
)
from scripts.analysis.fq_loss_taxonomy_reconstruct import SEMANTICS_NOTE
from scripts.analysis.fq_loss_taxonomy_report import fields_dict as _fields_dict
from scripts.analysis.fq_loss_taxonomy_report import write_json as _write_json

__all__ = ["EXIT_STOP", "P7_POLICY", "PinPolicy", "UnparseableInstrumentStop", "main"]

TERMINAL_CLIMATE_DAY: Final = dt.date(2026, 10, 5)
LAST_CLIMATE_DAY: Final = dt.date(2026, 10, 6)
FQ_WINDOW_START: Final = dt.date(2026, 10, 1)
EXPECTED_FQ_FILLS: Final = 25
EXPECTED_FQ_WINS: Final = 2
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
BOOT_HEADER_LINES: Final = 400
DEFAULT_ARCHIVE_ROOT: Final = Path.home() / ".local/share/breezy/us_source_archive"
VENUE: Final = "polymarket_us"
_BOOT_STAMP: Final = re.compile(r"(\d{8}T\d{6})Z")
_MANIFEST_SHA: Final = re.compile(r"manifest_sha256=([0-9a-f]{64})")
_ARTEFACT_SHA: Final = re.compile(r"calibration_sha256=([0-9a-f]{64})")


@dataclass(frozen=True)
class PinPolicy:
    """The expected per-boot pinned commits (plan P7 table) and the git-log range for the label."""

    expected_commits: tuple[str, ...]
    pin_range: tuple[str, str]


P7_POLICY: Final = PinPolicy(
    (
        "60290e9ddd29", "99067d4a9e7a", "99067d4a9e7a", "7dfd1af114c1", "6e99a7ae2dbe",
        "3eb4a1085dbf", "f45f5a6558cd", "c893e13e603e", "4ba7f10cd1f6",
    ),
    PIN_RANGE,
)  # fmt: skip


def _boots_from_logs(logs: Sequence[Path], expected_count: int) -> list[Boot]:
    """One Boot per node log: the boot time from the file name, the logged shas from its head.

    A log count other than ``expected_count`` or a log without both shas is an S0-A STOP.
    """
    if len(logs) != expected_count:
        raise S0AStop(f"expected {expected_count} boot logs (pin table), got {len(logs)}")
    boots = []
    for number, path in enumerate(sorted(logs), start=1):
        stamp = _BOOT_STAMP.search(path.name)
        if stamp is None:
            raise S0AStop(f"cannot read a boot time from {path.name}")
        when = dt.datetime.strptime(stamp.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=dt.UTC)
        manifest = artefact = None
        with path.open(encoding="utf-8", errors="replace") as handle:
            for _, line in zip(range(BOOT_HEADER_LINES), handle, strict=False):
                manifest = manifest or (m.group(1) if (m := _MANIFEST_SHA.search(line)) else None)
                artefact = artefact or (m.group(1) if (m := _ARTEFACT_SHA.search(line)) else None)
        if manifest is None or artefact is None:
            raise S0AStop(f"{path.name} carries no manifest_sha256 / calibration_sha256 (sha) line")
        boots.append(Boot(number, when, manifest, artefact))
    return boots


def _verify_pin_table(pins: Sequence[BootPin], expected: Sequence[str]) -> None:
    for pin, want in zip(pins, expected, strict=True):
        got = pin.commit or ""
        if not got or not (got.startswith(want) or want.startswith(got)):
            raise S0AStop(
                f"pin table mismatch: boot {pin.boot_number} is {pin.commit}, want {want}"
            )


def _is_fq_window(instrument_id: str) -> bool:
    facts = bucket_facts_from_instrument_id(instrument_id)
    return facts is not None and facts.climate_day >= FQ_WINDOW_START


def _fq_only(fills: FillRead) -> FillRead:
    october = tuple(f for f in fills.fills if _is_fq_window(f.instrument_id))
    return FillRead(fills=october, n_keys=len(october), n_undecodable=0)


def _predecessor_p_hats(
    reconstructor: Reconstructor,
    specs: Sequence[FillSpec],
    boots: Sequence[Boot],
    pins: Sequence[BootPin],
) -> dict[str, tuple[str, float | None]]:
    """p-hat under the reflog predecessor for fills of NEAR-BOUNDARY pinned boots (plan P7)."""
    by_boot = {p.boot_number: p for p in pins}
    shown: dict[str, tuple[str, float | None]] = {}
    for spec in specs:
        pin = by_boot.get(boot_for(boots, spec.decision_now_ns) or 0)
        if pin and pin.state == "PINNED" and pin.near_boundary and pin.predecessor:
            before = reconstructor.reconstruct(spec, pin.predecessor)
            shown[spec.fill_id] = (pin.predecessor, before.p_hat_reconstructed)
    return shown


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


def _s0g(args: argparse.Namespace, stations: Sequence[str]) -> dict[str, Any]:
    registry = default_registry()
    icaos = sorted({registry.settlement_site(VENUE, s).icao for s in stations})
    found = discover_alt_sources(
        args.archive_root, icaos, LAST_CLIMATE_DAY, venue_outcomes=args.venue_outcomes
    )
    return {
        "metar_last_valid": dict(found.metar_last_valid),
        "k3_status": "SOURCE_PRESENT" if found.metar_covers else "UNTESTABLE",
        "k4_status": "SOURCE_PRESENT" if found.venue_outcomes_present else "UNTESTABLE",
    }


def _phase_a(args: argparse.Namespace, policy: PinPolicy) -> int:
    counts = s0a_counts(args.fills_db, TERMINAL_CLIMATE_DAY)
    s0a_gate(counts)
    fills = _fq_only(read_durable_fills(args.fills_db).require_clean())
    attribution = attribute_fills(fills, args.logs, data_root=args.data_root)
    specs = [
        FillSpec(f.venue_order_id, f.instrument_id, m.p_at_decision, m.decision_now_ns,
                 float(f.cumulative_cost / f.cumulative_qty))
        for f, m in zip(fills.fills, attribution.matches, strict=True)
    ]  # fmt: skip
    git = SubprocessGit(args.repo_root)
    boots = _boots_from_logs(args.logs, len(policy.expected_commits))
    reconstructor = Reconstructor(
        git, manifest_path=MANIFEST_PATH, workdir=args.output_dir / "pinned",
        cycles=load_derived_cycles(args.derived_store), published=published_cycles(args.logs),
    )  # fmt: skip
    specs_by_boot: dict[int, list[FillSpec]] = {}
    for spec in specs:
        number = boot_for(boots, spec.decision_now_ns)
        if number is not None:
            specs_by_boot.setdefault(number, []).append(spec)
    pins = resolve_pins(
        args.reflog_snapshot, args.reflog_snapshot_sha256, boots, git,
        PinConfig(MANIFEST_PATH, ARTEFACT_PATH, WIDENED_PATHS),
        reproduces_under=reconstructor.reproduces_under(specs_by_boot),
    )  # fmt: skip
    _verify_pin_table(pins, policy.expected_commits)
    results = reconstruct_all(reconstructor, specs, boots, pins)
    gate = s0d_gate(results)
    label = pin_label(git, WIDENED_PATHS, *policy.pin_range)
    rows = fill_rows(
        fills, results, specs, {p.boot_number: p for p in pins}, label, TERMINAL_CLIMATE_DAY,
        _predecessor_p_hats(reconstructor, specs, boots, pins),
    )  # fmt: skip
    union = partition_union(
        itertools.chain.from_iterable(iter_partition_events(p) for p in args.logs)
    )
    days, clusters = day_and_cluster_rows(rows, results, union)
    p_c = [c["P_c"] for c in clusters]
    payload = {
        "phase": "A", "outcome_blind": True, "s0a": _fields_dict(counts),
        "s0c": _fields_dict(attribution.report),
        "s0d": {**_fields_dict(gate), "semantics": SEMANTICS_NOTE,
                "vectors": vector_table(results)},
        "s0g": _s0g(args, sorted({r["station"] for r in rows})),
        "per_fill": rows, "station_days": days, "clusters": clusters,
        "t_win_null": {
            "testability": t_win_testability(p_c),
            "min_attainable_p": lower_tail(p_c, 0),
        },
        "pins": [_fields_dict(p) for p in pins],
        "pin_table": [_fields_dict(p) for p in pins], "pin_label": label,
        "truth_projection": _truth_projection(
            args.catalog_root, [(d["station"], d["climate_day"]) for d in days]
        ),
    }  # fmt: skip
    _write_json(args.output_dir / "phase_a_table.json", payload)
    sys.stdout.write(f"phase A table written to {args.output_dir / 'phase_a_table.json'}\n")
    return 0


def _phase_b(args: argparse.Namespace) -> int:
    inputs = PhaseBInputs(
        args.output_dir, args.repo_root, args.pins_json, args.predeclaration, args.phase_a_table,
        args.now_ns, args.archive_root, args.venue_outcomes, args.te1_ledger,
    )  # fmt: skip
    try:
        gates = check_gates(inputs, SubprocessGit(args.repo_root))
    except PhaseBRefused as refused:
        sys.stderr.write(f"PHASE B REFUSED: {refused.reasons}\n")
        return EXIT_STOP
    fq_only = _fq_only(read_durable_fills(args.fills_db).require_clean())
    source = ClippingSettlementSource(_CatalogRouter(args.catalog_root), LAST_CLIMATE_DAY)
    return execute(inputs, gates, fq_only, source)


def _verify(args: argparse.Namespace) -> int:
    violations = verify_artefact(
        args.repo_root, args.pins_json, args.artefact, SubprocessGit(args.repo_root)
    )
    if violations:
        sys.stderr.write(f"VERIFY FAILED: {list(violations)}\n")
        return EXIT_STOP
    sys.stdout.write("verify ok: the artefact commit follows the predeclaration commit\n")
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
        p.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
        p.add_argument("--venue-outcomes", type=Path, default=None)
    a = sub.choices["phase-a"]
    a.add_argument("--logs", type=Path, nargs="+", required=True)
    a.add_argument("--data-root", type=Path, required=True)
    a.add_argument("--reflog-snapshot", type=Path, required=True)
    a.add_argument("--reflog-snapshot-sha256", required=True)
    a.add_argument("--derived-store", type=Path, required=True)
    b = sub.choices["phase-b"]
    b.add_argument("--pins-json", type=Path, required=True)
    b.add_argument("--now-ns", type=int, required=True)
    b.add_argument("--predeclaration", type=Path, required=True)
    b.add_argument("--phase-a-table", type=Path, required=True)
    b.add_argument("--te1-ledger", type=Path, default=None)
    v = sub.add_parser("verify")
    v.add_argument("--repo-root", type=Path, default=Path.cwd())
    v.add_argument("--pins-json", type=Path, required=True)
    v.add_argument("--artefact", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None, *, policy: PinPolicy = P7_POLICY) -> int:
    args = _parser().parse_args(argv)
    if args.phase == "verify":
        return _verify(args)
    if args.phase == "phase-b":
        if args.catalog_root is None:
            sys.stderr.write("phase-b needs --catalog-root\n")
            return EXIT_STOP
        return _phase_b(args)
    try:
        return _phase_a(args, policy)
    except (S0AStop, S0DStop, UnclassifiedFillsStop) as stop:
        sys.stderr.write(f"STOP: {stop}\n")
        return EXIT_STOP


if __name__ == "__main__":
    raise SystemExit(main())
