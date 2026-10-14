"""MAKER-S2 Stage 0 replay CLI (plan r3 WP6 + r4 delta (c)).

Usage (verdict run; one scoring pass per amendment, a clean committed tree):

    python -m scripts.analysis.maker_stage0_replay --census-days PATH --trade-unit PATH \\
        --truth PATH --node-log-dir PATH --out-dir DIR/<run_id> --amendment PATH \\
        --amendment-sha SHA [--catalog-root DIR] [--nbp-root DIR] [--truth-cross-check PATH] \\
        [--ledger PATH]

Report-only modes (mutually exclusive, none claims the ledger): ``--bench N`` (the only mode that
takes ``--stations/--days``), ``--tail-only --parity STATION:0|1,...`` and ``--verify-first``.
Exit codes: 0 done, 2 refused before any ledger claim, 3 the run was voided (``<run_id>.void``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis.maker_stage0_fill_events import DeltaBoundExceeded
from scripts.analysis.maker_stage0_frozen import FrozenSetRefused
from scripts.analysis.maker_stage0_inputs import InputRefused
from scripts.analysis.maker_stage0_ledger import LedgerRefused
from scripts.analysis.maker_stage0_model import ModelRefused
from scripts.analysis.maker_stage0_pins import DirtyTree, PinRefused
from scripts.analysis.maker_stage0_probe_core import CensusViolation, StopS2

PROG: Final[str] = "maker_stage0_replay"
HOME: Final[Path] = Path.home()
DEFAULT_CATALOG: Final[Path] = HOME / ".local/share/breezy/catalog/quote_tape/polymarket_us"
DEFAULT_NBP: Final[Path] = HOME / ".local/share/breezy/derived/nbp"
DEFAULT_CROSS_CHECK: Final[Path] = (
    HOME / ".local/share/breezy/derived/settlement-truth/settlement_truth.parquet"
)
DEFAULT_LEDGER: Final[Path] = HOME / ".local/share/breezy/derived/maker_stage0/verdict_ledger.jsonl"
DEFAULT_WORK: Final[Path] = HOME / ".cache/breezy/maker_stage0_work"
DEFAULT_SPEC: Final[str] = "docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md"
EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 2
EXIT_VOID: Final[int] = 3
REFUSALS: Final[tuple[type[BaseException], ...]] = (
    drv.SubsetRefused,
    drv.RunDirExists,
    drv.DiskLow,
    InputRefused,
    FrozenSetRefused,
    LedgerRefused,
    DirtyTree,
    PinRefused,
    ModelRefused,
)
VOIDS: Final[tuple[type[BaseException], ...]] = (
    drv.MemoryAbort,
    DeltaBoundExceeded,
    StopS2,
    CensusViolation,
)


def _csv(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _days(text: str) -> tuple[dt.date, ...]:
    try:
        return tuple(dt.date.fromisoformat(part) for part in _csv(text))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO date list: {text!r}") from exc


def _parity(text: str) -> tuple[tuple[str, int], ...]:
    pairs: list[tuple[str, int]] = []
    for part in _csv(text):
        station, _, value = part.partition(":")
        if not station or value not in {"0", "1"}:
            raise argparse.ArgumentTypeError(f"parity must be STATION:0|1, got {part!r}")
        pairs.append((station, int(value)))
    return tuple(pairs)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description=__doc__.split("\n\n")[0])
    for flag in ("census-days", "trade-unit", "truth", "node-log-dir", "out-dir", "amendment"):
        p.add_argument(f"--{flag}", type=Path)
    p.add_argument("--amendment-sha")
    p.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG)
    p.add_argument("--nbp-root", type=Path, default=DEFAULT_NBP)
    p.add_argument("--truth-cross-check", type=Path, default=DEFAULT_CROSS_CHECK)
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument(
        "--work-root", type=Path, help="scratch for converted instances (default per run)"
    )
    p.add_argument("--repo-root", type=Path, default=Path.cwd())
    p.add_argument("--spec", type=Path, help=f"default <repo-root>/{DEFAULT_SPEC}")
    p.add_argument("--addendum", type=Path)
    p.add_argument("--addendum-sha")
    p.add_argument("--stations", type=_csv, help="bench only")
    p.add_argument("--days", type=_days, help="bench only")
    p.add_argument("--bench", type=int, metavar="N", help="time N heaviest station-days")
    p.add_argument("--tail-only", action="store_true")
    p.add_argument("--verify-first", action="store_true")
    p.add_argument("--parity", type=_parity, help="tail-only: STATION:0|1,...")
    p.add_argument("--tail-csv", type=Path, help="verdict run: a prior --tail-only table to embed")
    p.add_argument("--as-of", type=dt.date.fromisoformat, help="date for the D+14 UNRESOLVED rule")
    return p


def _require(parser: argparse.ArgumentParser, ns: argparse.Namespace) -> None:
    names = ["out_dir", "amendment", "amendment_sha"]
    if not ns.verify_first:
        names += ["census_days", "trade_unit", "truth", "node_log_dir"]
    missing = [f"--{n.replace('_', '-')}" for n in names if getattr(ns, n) is None]
    if missing:
        parser.error(f"required: {', '.join(missing)}")


def parse_args(argv: Sequence[str] | None = None) -> drv.RunConfig:
    parser = build_parser()
    ns = parser.parse_args(argv)
    _require(parser, ns)
    shown = tuple(sys.argv if argv is None else (PROG, *argv))
    out_dir: Path = ns.out_dir
    return drv.RunConfig(
        census_days=ns.census_days or Path(),
        trade_unit=ns.trade_unit or Path(),
        catalog_root=ns.catalog_root,
        nbp_root=ns.nbp_root,
        truth=ns.truth or Path(),
        truth_cross_check=ns.truth_cross_check,
        node_log_dir=ns.node_log_dir or Path(),
        out_dir=out_dir,
        repo_root=ns.repo_root,
        amendment=ns.amendment,
        amendment_sha=ns.amendment_sha,
        spec=ns.spec or ns.repo_root / DEFAULT_SPEC,
        ledger=ns.ledger,
        work_root=ns.work_root or DEFAULT_WORK / out_dir.name,
        addendum=ns.addendum,
        addendum_sha=ns.addendum_sha,
        stations=ns.stations,
        days=ns.days,
        bench=ns.bench,
        tail_only=ns.tail_only,
        verify_first=ns.verify_first,
        parity=ns.parity,
        tail_csv=ns.tail_csv,
        as_of=ns.as_of,
        argv=shown,
    )


def main(argv: Sequence[str] | None = None) -> int:
    cfg = parse_args(argv)
    try:
        summary = drv.run(cfg)
    except REFUSALS as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except VOIDS as exc:
        print(f"VOID: {type(exc).__name__}: {exc} (run renamed <run_id>.void)", file=sys.stderr)
        return EXIT_VOID
    label = "" if summary.label is None else f" label={summary.label}"
    print(f"{summary.mode} run done{label} code_sha={summary.code_sha} -> {summary.run_dir}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
