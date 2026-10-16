"""MAKER-S2 second look (C4): state files, the single-writer lock and the census subprocess.

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md section 3 "C4".
The trigger lock is the only writer of the read-ledger's counts-only lines: ``check`` holds
``trigger.lock`` (``flock``) and hands the census a fresh nonce as its trigger-check token.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from breezy.analysis.maker_search_declarations import SEARCH_DECLARATIONS
from scripts.analysis.maker_stage0_trigger_rule import TriggerRow
from scripts.analysis.maker_tape_census_guard import COUNT_FIELDS, read_ledger_lines

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
ROWS_NAME: Final[str] = "trigger_rows.jsonl"
CHECKED_NAME: Final[str] = "checked_through.txt"
LOCK_NAME: Final[str] = "trigger.lock"
DECLARATION: Final[Path] = (
    REPO_ROOT / "docs" / "evidence" / "RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16.md"
)


ROW: Final = SEARCH_DECLARATIONS[1]  # Doc A: the second-look registry row


class TriggerRefused(Exception):
    """A refusal the CLI reports with exit 2."""


def default_work_root() -> Path:
    return Path.home() / ".local/share/breezy/derived/maker_stage0/trigger"


@contextmanager
def trigger_lock(work_root: Path) -> Iterator[str]:
    """Hold ``trigger.lock`` exclusively and yield the nonce written into it."""
    work_root.mkdir(parents=True, exist_ok=True)
    path = work_root / LOCK_NAME
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TriggerRefused(f"trigger lock {path} is held by another process") from exc
        try:
            same = os.fstat(handle.fileno()).st_ino == path.stat().st_ino
        except OSError:
            same = False
        if not same:
            raise TriggerRefused(f"trigger lock file {path} is absent after acquisition")
        nonce = uuid.uuid4().hex
        handle.truncate(0)
        handle.write(nonce + "\n")
        handle.flush()
        yield nonce


def canonical(row: Mapping[str, object]) -> str:
    return json.dumps({k: row[k] for k in COUNT_FIELDS}, sort_keys=True, separators=(",", ":"))


def load_state(rows_path: Path) -> tuple[list[dict[str, Any]], dt.date | None]:
    """Data rows in file order, and E of the terminal CROSSED row (None before a crossing)."""
    rows: list[dict[str, Any]] = []
    crossed: dt.date | None = None
    if not rows_path.exists():
        return rows, crossed
    for text in rows_path.read_text(encoding="utf-8").splitlines():
        if not text.strip():
            continue
        record = json.loads(text)
        if "CROSSED" in record:
            crossed = dt.date.fromisoformat(record["E"])
        else:
            rows.append(record)
    return rows, crossed


def as_trigger_rows(records: Iterable[Mapping[str, Any]]) -> list[TriggerRow]:
    return [
        TriggerRow(
            r["station"], dt.date.fromisoformat(r["climate_day"]), r["reason"], r["first_seen_ns"]
        )
        for r in records
    ]


def row_dict(row: TriggerRow) -> dict[str, Any]:
    return {
        "station": row.station, "climate_day": row.climate_day.isoformat(),
        "reason": row.reason, "first_seen_ns": row.first_seen_ns,
    }  # fmt: skip


def append_lines(path: Path, lines: Iterable[str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(line + "\n" for line in lines))
        handle.flush()
        os.fsync(handle.fileno())


def read_checked_through(work_root: Path) -> dt.date | None:
    path = work_root / CHECKED_NAME
    return (
        dt.date.fromisoformat(path.read_text(encoding="utf-8").strip()) if path.exists() else None
    )


def write_checked_through(work_root: Path, day: dt.date) -> None:
    (work_root / CHECKED_NAME).write_text(day.isoformat() + "\n", encoding="utf-8")


def run_counts_only(  # pragma: no cover - the live census; tests replace it
    *,
    day_from: dt.date,
    day_to: dt.date,
    out: Path,
    env: dict[str, str],
    read_ledger: Path,
    trigger_close: Path,
    declaration: Path,
) -> int:
    """One counts-only census over [day_from, day_to]; ``env`` carries the lock nonce."""
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable, "-m", "scripts.analysis.maker_tape_census",
        "--from", day_from.isoformat(), "--to", day_to.isoformat(), "--counts-only",
        "--output", str(out), "--read-ledger", str(read_ledger),
        "--trigger-close", str(trigger_close), "--search-declaration", str(declaration),
    ]  # fmt: skip
    return subprocess.run(argv, env=env, cwd=REPO_ROOT, check=False).returncode


def forfeiture(ledger: Path, end: dt.date) -> int:
    invoked = [
        dt.date.fromisoformat(x["to"]) for x in read_ledger_lines(ledger) if x["sha"] == ROW.sha256
    ]
    if not invoked or max(invoked) < end:
        raise TriggerRefused(f"read-ledger {ledger} does not cover E={end} under the Doc A sha")
    return len(ROW.stations) * ((max(invoked) - ROW.first_day).days + 1)
