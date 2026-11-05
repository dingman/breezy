"""MAKER-S2 second look (C4): the trigger tool: ``check`` (daily) and ``close`` (manual).

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md section 3 "C4".
``check`` catches up the unchecked days with ONE counts-only census (under the trigger lock
and its nonce token), appends the rows in date order and stops at the first crossing; days
after E in the batch are discarded unread (they still count toward forfeiture). ``close``
seals E, the rows hash and the chain into ``trigger_close.json`` once, and re-verifies the
forfeiture against the read-ledger.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import itertools
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from breezy.analysis.maker_search_declarations import TRIGGER_CHECK_ENV
from scripts.analysis import maker_stage0_trigger_io as tio
from scripts.analysis import maker_tape_census_guard as guard
from scripts.analysis.maker_stage0_inputs import InputRefused
from scripts.analysis.maker_stage0_trigger_io import ROW, TriggerRefused, run_counts_only
from scripts.analysis.maker_stage0_trigger_rule import (
    first_crossing,
    n_eff_proxy,
    read_trigger_rows,
)

_ONE_DAY = dt.timedelta(days=1)
_EXIT_REFUSED = 2


def _window(checked: dt.date | None, today: dt.date) -> tuple[dt.date, dt.date] | None:
    first = ROW.first_day if checked is None else max(checked + _ONE_DAY, ROW.first_day)
    last = min(today - 2 * _ONE_DAY, ROW.last_day)
    return (first, last) if first <= last else None


def _append_days(
    work: Path, new: Sequence[dict[str, object]], seen: list[dict[str, object]]
) -> dt.date | None:
    """Append day by day, evaluating the crossing after each; returns E when it crossed."""
    ordered = sorted(new, key=lambda r: (str(r["climate_day"]), str(r["station"])))
    done = {str(r["climate_day"]) for r in seen}  # idempotent: a re-run never duplicates a day
    for day, group in itertools.groupby(ordered, key=lambda r: str(r["climate_day"])):
        if day in done:
            continue
        batch = list(group)
        tio.append_lines(work / tio.ROWS_NAME, [tio.canonical(r) for r in batch])
        seen.extend(batch)
        tio.write_checked_through(work, dt.date.fromisoformat(day))
        crossing = first_crossing(tio.as_trigger_rows(seen))
        if crossing is not None:
            line = json.dumps({"CROSSED": True, "E": crossing.isoformat()}, sort_keys=True)
            tio.append_lines(work / tio.ROWS_NAME, [line])
            tio.write_checked_through(work, crossing)
            return crossing
    return None


def _check(args: argparse.Namespace) -> int:
    work: Path = args.work_root
    with tio.trigger_lock(work) as nonce:
        seen, crossed = tio.load_state(work / tio.ROWS_NAME)
        if crossed is not None:
            raise TriggerRefused(f"already crossed at E={crossed}; no further check is allowed")
        last_row = max((dt.date.fromisoformat(r["climate_day"]) for r in seen), default=None)
        stamped = [d for d in (tio.read_checked_through(work), last_row) if d is not None]
        window = _window(max(stamped, default=None), args.today or guard.utc_today())
        if window is None:
            print("trigger: nothing to check")
            return 0
        first, last = window
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")  # one file per attempt
        counts = work / "counts" / f"{first}_{last}_{stamp}.jsonl"
        env = {**os.environ, TRIGGER_CHECK_ENV: nonce}  # the child's env only; ours is untouched
        code = run_counts_only(
            day_from=first, day_to=last, out=counts, env=env, read_ledger=args.read_ledger,
            trigger_close=args.trigger_close, declaration=args.search_declaration,
        )  # fmt: skip
        if code != 0:
            raise TriggerRefused(f"census exited {code}; the invocation counts toward forfeiture")
        new = [tio.row_dict(r) for r in read_trigger_rows(counts)]
        if any(not first.isoformat() <= str(r["climate_day"]) <= last.isoformat() for r in new):
            raise TriggerRefused(f"census rows fall outside [{first}, {last}]")
        crossing = _append_days(work, new, seen)
        if crossing is None:
            tio.write_checked_through(work, last)
        score = n_eff_proxy(tio.as_trigger_rows(seen))
        print(f"trigger: checked {first}..{last} n_eff={score:.3f} crossed={crossing is not None}")
    return 0


def _close(args: argparse.Namespace) -> int:
    """Seal E once. ``rows_chain_sha256`` chains the rows <= E only (from GENESIS), so it is NOT
    comparable to the read-ledger's per-invocation chain; ``rows_sha256`` is the verification
    object.
    """
    if args.trigger_close.exists():
        raise TriggerRefused(f"{args.trigger_close} exists; close is once-only")
    rows, crossed = tio.load_state(args.work_root / tio.ROWS_NAME)
    checked = tio.read_checked_through(args.work_root)
    if crossed is None and (checked is None or checked < ROW.last_day):
        raise TriggerRefused("neither crossed nor checked through the cap; nothing to close")
    end = crossed if crossed is not None else ROW.last_day
    kept = [r for r in rows if str(r["climate_day"]) <= end.isoformat()]
    body = "".join(tio.canonical(r) + "\n" for r in kept)
    forfeiture = tio.forfeiture(args.read_ledger, end)
    payload = {
        "E": end.isoformat(), "crossed": crossed is not None,
        "rows_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "rows_chain_sha256": guard.rows_chain(guard.GENESIS_CHAIN, kept),
        "closed_at": dt.datetime.now(dt.UTC).isoformat(),
    }  # fmt: skip
    args.trigger_close.parent.mkdir(parents=True, exist_ok=True)
    with args.trigger_close.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    if args.repo_copy is not None:
        args.repo_copy.write_text(body, encoding="utf-8")
    print(f"trigger: closed E={payload['E']} crossed={payload['crossed']} rows={len(kept)} "
          f"forfeiture={forfeiture}")  # fmt: skip
    return 0


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--work-root", type=Path, default=tio.default_work_root())
    common.add_argument("--trigger-close", type=Path, default=guard.default_trigger_close())
    common.add_argument("--read-ledger", type=Path, default=guard.default_read_ledger())
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", parents=[common])
    check.add_argument("--today", type=dt.date.fromisoformat, default=None)
    check.add_argument("--search-declaration", type=Path, default=tio.DECLARATION)
    close = sub.add_parser("close", parents=[common])
    close.add_argument("--repo-copy", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        return _check(args) if args.command == "check" else _close(args)
    except (TriggerRefused, InputRefused, ValueError, KeyError, OSError) as exc:
        print(f"trigger: REFUSED {type(exc).__name__}: {exc}", file=sys.stderr)
        return _EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
