"""LAT-1 NBP revision-latency scorer: ``--stage {tau,0,1}`` (stage 2 is a refusing stub).

Plan r3 as amended by r3.1. Offline analysis only: no network, no orders, no operator caps.
Every stage refuses while ``PREREG_SHA256`` is UNFROZEN or does not match the prereg file, and every
pre-stage-2 stage refuses any climate day D >= 2026-10-28 (the confirm period).

The scorer core (``score_station_day`` and the stage runners) takes an injected station-day loader,
so it is exercised end to end on synthetic books. The real loader lives in
``nbp_revision_latency_io`` and is never run by the tests.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import resource
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from breezy.analysis.revision_latency import (
    CONFIRM_START,
    TAU_ALT_FLOOR,
    TAU_PRIMARY_FLOOR,
    LeakGuardError,
    assert_guard_5,
)
from breezy.strategy.no_ladder_maker.pno_store import STATIONS
from breezy.strategy.weather_common.revision_gate import NS
from scripts.analysis.nbp_revision_latency_core import (
    TauValues,
    json_default,
    run_stage_0,
    run_stage_1,
    run_stage_tau,
)

#: Frozen by the prereg commit. UNFROZEN makes every stage refuse (plan Phase P step 5).
PREREG_SHA256: Final[str] = "UNFROZEN"
#: Pinned by the commit that follows the Stage 1 selection artefact (Stage 2 only).
SELECTION_SHA256: Final[str] = "UNSET"
UNFROZEN: Final[str] = "UNFROZEN"
UNSET: Final[str] = "UNSET"

STAGES: Final[tuple[str, ...]] = ("tau", "0", "1", "2")
ADDRESS_SPACE_CAP_BYTES: Final[int] = 8 * 1024**3


class RefusalError(RuntimeError):
    """A policy refusal (exit code 2). Anything else is a bug and propagates."""


class UsageRefused(RefusalError):
    """A missing or invalid argument (naive freeze, tau below its floor, no artefact)."""


class PinRefused(RefusalError):
    """A sha pin is UNFROZEN/UNSET, or the file does not match it."""


class ConfirmDayRefused(RefusalError):
    """A pre-stage-2 stage was asked for a confirm-period climate day."""


class StageRefused(RefusalError):
    """The requested stage cannot run (stage 2 is not built)."""


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_prereg(path: Path | None, *, pin: str | None = None) -> str:
    """Return the prereg text after proving it matches ``PREREG_SHA256`` (never UNFROZEN)."""
    pinned = PREREG_SHA256 if pin is None else pin
    if pinned == UNFROZEN:
        raise PinRefused("PREREG_SHA256 is UNFROZEN; the prereg has not been committed")
    if path is None or not path.is_file():
        raise PinRefused("a prereg file is required")
    if _file_sha256(path) != pinned:
        raise PinRefused("prereg sha256 does not match PREREG_SHA256")
    return path.read_text(encoding="utf-8")


def require_selection(path: Path | None, *, pin: str | None = None) -> None:
    """Stage 2 starts only with a selection artefact whose sha matches ``SELECTION_SHA256``."""
    pinned = SELECTION_SHA256 if pin is None else pin
    if pinned == UNSET:
        raise PinRefused("SELECTION_SHA256 is UNSET; there is no committed selection artefact")
    if path is None or not path.is_file():
        raise PinRefused("a selection artefact file is required for stage 2")
    if _file_sha256(path) != pinned:
        raise PinRefused("selection artefact sha256 does not match SELECTION_SHA256")


def refuse_confirm_days(days: Sequence[dt.date]) -> None:
    late = [day for day in days if day >= CONFIRM_START]
    if late:
        raise ConfirmDayRefused(
            f"pre-stage-2 stages never read D >= {CONFIRM_START}; got {late[0]}"
        )


def date_range(start: dt.date, end: dt.date) -> tuple[dt.date, ...]:
    return tuple(start + dt.timedelta(days=i) for i in range((end - start).days + 1))


# ------------------------------------------------------------------------------ CLI


def _parse_date(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LAT-1 NBP revision-latency scorer")
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--start", type=_parse_date, required=True)
    parser.add_argument("--end", type=_parse_date, required=True)
    parser.add_argument("--prereg", type=Path, default=None)
    parser.add_argument("--selection", type=Path, default=None)
    parser.add_argument("--artefact", type=Path, default=None)
    parser.add_argument("--derived-root", type=Path, default=None)
    parser.add_argument("--tape-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--freeze-utc", default=None, help="ISO instant for the tau freeze")
    parser.add_argument("--tau-primary", type=float, default=None)
    parser.add_argument("--tau-alt", type=float, default=None)
    return parser


def _freeze_ns(text: str | None) -> int:
    if text is None:
        raise UsageRefused("--freeze-utc is required for stage tau")
    stamp = dt.datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        raise UsageRefused("--freeze-utc must be tz-aware (e.g. 2026-10-26T00:00:00+00:00)")
    return int(stamp.timestamp()) * NS


_TAU_LINE = re.compile(r"^TAU_PRIMARY=(\S+)\s+TAU_ALT=(\S+)\s*$", re.MULTILINE)


def prereg_tau(text: str) -> tuple[float, float]:
    """The tau pair recorded in the prereg, from a line ``TAU_PRIMARY=0.13 TAU_ALT=0.18``."""
    match = _TAU_LINE.search(text)
    if match is None:
        raise UsageRefused("the prereg has no 'TAU_PRIMARY=<x> TAU_ALT=<y>' line")
    try:
        return float(match.group(1)), float(match.group(2))
    except ValueError as exc:
        raise UsageRefused(f"unparseable TAU_PRIMARY/TAU_ALT in the prereg: {exc}") from exc


def _floor_checked_tau(args: argparse.Namespace) -> tuple[float, float]:
    primary, alt = args.tau_primary, args.tau_alt
    if primary is None or alt is None:
        raise UsageRefused("--tau-primary and --tau-alt (from the prereg tau report) are required")
    if primary < TAU_PRIMARY_FLOOR or alt < TAU_ALT_FLOOR:
        raise UsageRefused(
            f"tau below the pinned floors ({TAU_PRIMARY_FLOOR}, {TAU_ALT_FLOOR}): {primary}, {alt}"
        )
    return primary, alt


def _tau_values(args: argparse.Namespace, recorded: tuple[float, float]) -> TauValues:
    primary, alt = _floor_checked_tau(args)
    if (primary, alt) != recorded:
        raise UsageRefused(f"tau ({primary}, {alt}) differs from the prereg's TAU line {recorded}")
    return TauValues(primary, alt, "prereg_text")


def preflight(args: argparse.Namespace) -> str | None:
    """Every refusal that needs no tape, in order. Returns the prereg text (None for stage tau).

    Stage tau is outcome-free and runs BEFORE the prereg exists, so it is exempt from the prereg
    pin; it keeps the confirm-day refusal."""
    if args.stage == "2":
        require_selection(args.selection)
    text = None if args.stage == "tau" else require_prereg(args.prereg)
    if args.stage == "2":
        raise StageRefused("stage 2 (LD-OBF confirmation) is not built in this slice")
    refuse_confirm_days(date_range(args.start, args.end))
    if args.artefact is None:
        raise UsageRefused("--artefact is required")
    if args.stage == "tau":
        _freeze_ns(args.freeze_utc)
    else:
        assert text is not None
        _floor_checked_tau(args)
        _tau_values(args, prereg_tau(text))
    return text


def _run(args: argparse.Namespace, prereg_text: str | None) -> int:
    days = date_range(args.start, args.end)
    resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_CAP_BYTES, ADDRESS_SPACE_CAP_BYTES))
    assert_guard_5(days, artefact_sha256=_file_sha256(args.artefact), prereg_text=prereg_text)
    from scripts.analysis.nbp_revision_latency_io import make_loader  # real tape; never in tests

    loader = make_loader(
        args.artefact, args.derived_root, args.tape_root, with_books=args.stage != "tau"
    )
    if args.stage == "tau":
        report = run_stage_tau(loader, STATIONS, days, freeze_ns=_freeze_ns(args.freeze_utc))
    else:
        runner = run_stage_0 if args.stage == "0" else run_stage_1
        report = runner(loader, STATIONS, days, _tau_values(args, prereg_tau(prereg_text or "")))
    text = json.dumps(report, indent=2, sort_keys=True, default=json_default)
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return _run(args, preflight(args))
    except (RefusalError, LeakGuardError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
