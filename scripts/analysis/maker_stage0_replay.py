"""MAKER-S2 Stage 0 replay CLI (plan r3 WP6 + r4 delta (c)).

Usage (verdict run; one scoring pass per amendment, a clean committed tree):

    python -m scripts.analysis.maker_stage0_replay --census-days PATH --trade-unit PATH \\
        --truth PATH --node-log-dir PATH --out-dir DIR/<run_id> --amendment PATH \\
        --amendment-sha SHA [--catalog-root DIR] [--nbp-root DIR] [--truth-cross-check PATH]

Report-only modes (mutually exclusive, none claims the ledger): ``--bench N`` (N = 4 or 8; the only
mode that takes ``--stations/--days``), ``--tail-only --parity STATION:0|1,...`` (stations from
LAX/MDW/MIA/SFO) and ``--verify-first``.
The ledger (``<derived root>/maker_stage0/verdict_ledger.jsonl``) and the repo root (the git root of
the imported ``scripts.analysis`` package; clean tree and code sha are read from it) are derived,
never flags: a caller cannot point a second scoring pass at a fresh ledger.
Exit codes: 0 done, 2 refused before any ledger claim, 3 the run was voided (``<run_id>.void``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from breezy.analysis.maker_tape_census import FirewallRefused
from scripts.analysis import maker_stage0_driver as drv

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
GIT_TIMEOUT_S: Final[int] = 30
#: Every failure BEFORE the ledger claim is a refusal (exit 2): the named refusals are all
#: ValueError / RuntimeError subclasses, so the generic classes also cover EventError,
#: LeakageError, LocalDayViolation, PNoStoreReadError, VerdictRefused, CSV errors and OSError.
REFUSALS: Final[tuple[type[BaseException], ...]] = (
    OSError,
    ValueError,
    RuntimeError,
    FirewallRefused,
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


def package_repo_root() -> Path:
    """The git root of the imported ``scripts.analysis`` package (a namespace package: resolved
    from a member module's ``__file__``); never a caller choice."""
    package = Path(drv.__file__).resolve().parent
    try:
        done = subprocess.run(
            ["git", "-C", str(package), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise drv.InputRefused(f"cannot resolve the git root of {package}: {exc}") from exc
    if done.returncode != 0 or not done.stdout.strip():
        raise drv.InputRefused(f"{package} is not inside a git work tree: {done.stderr.strip()}")
    return Path(done.stdout.strip()).resolve()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description=__doc__.split("\n\n")[0])
    for flag in ("census-days", "trade-unit", "truth", "node-log-dir", "out-dir", "amendment"):
        p.add_argument(f"--{flag}", type=Path)
    p.add_argument("--amendment-sha")
    p.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG)
    p.add_argument("--nbp-root", type=Path, default=DEFAULT_NBP)
    p.add_argument("--truth-cross-check", type=Path, default=DEFAULT_CROSS_CHECK)
    p.add_argument(
        "--work-root", type=Path, help="scratch for converted instances (default per run)"
    )
    p.add_argument("--spec", type=Path, help=f"default <repo root>/{DEFAULT_SPEC}")
    p.add_argument("--addendum", type=Path)
    p.add_argument("--addendum-sha")
    p.add_argument(
        "--no-isolate", action="store_true", help="debug: simulate in-process (memory unbounded)"
    )
    p.add_argument("--stations", type=_csv, help="bench only")
    p.add_argument("--days", type=_days, help="bench only")
    modes = p.add_mutually_exclusive_group()
    modes.add_argument("--bench", type=int, metavar="N", help="time N heaviest (N = 4 or 8)")
    modes.add_argument("--tail-only", action="store_true")
    modes.add_argument("--verify-first", action="store_true")
    p.add_argument("--parity", type=_parity, help="tail-only: STATION:0|1,... (LAX/MDW/MIA/SFO)")
    p.add_argument("--tail-csv", type=Path, help="verdict run: a prior --tail-only table to embed")
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
    try:
        repo_root = package_repo_root()
    except drv.InputRefused as exc:
        parser.error(str(exc))
    return drv.RunConfig(
        census_days=ns.census_days,
        trade_unit=ns.trade_unit,
        catalog_root=ns.catalog_root,
        nbp_root=ns.nbp_root,
        truth=ns.truth,
        truth_cross_check=ns.truth_cross_check,
        node_log_dir=ns.node_log_dir,
        out_dir=out_dir,
        repo_root=repo_root,
        amendment=ns.amendment,
        amendment_sha=ns.amendment_sha,
        spec=ns.spec or repo_root / DEFAULT_SPEC,
        ledger=DEFAULT_LEDGER,
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
        isolate=not ns.no_isolate,
        argv=shown,
    )


def main(argv: Sequence[str] | None = None) -> int:
    cfg = parse_args(argv)
    try:
        summary = drv.run(cfg)
    except drv.RunVoided as exc:  # before REFUSALS: RunVoided is a RuntimeError
        print(f"VOID: {exc} (run renamed <run_id>.void)", file=sys.stderr)
        return EXIT_VOID
    except REFUSALS as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    label = "" if summary.label is None else f" label={summary.label}"
    print(f"{summary.mode} run done{label} code_sha={summary.code_sha} -> {summary.run_dir}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
