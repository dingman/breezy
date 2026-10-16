"""MAKER S2 second-look census guard, read-ledger and counts-only writer (unit C1b).

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md section 3 "C1b" and
the coordinator delta items 2.4 / 2.7. The guard applies only when a planned station-day
cleared through a registry row >= 1; a first-block (row 0) invocation never reaches it.

Ledger lines carry exactly ``sha, mode, from, to, rows_chain_sha256, ts``:

* the PRE-read line (mode ``counts_only`` / ``full``) is appended after firewall clearance
  and before any instance is touched; its chain is the chain over the rows committed so far;
* the POST-read line (mode ``..._post``) commits the invocation's rows into the chain.

An invocation that fails after its pre-read line counts over its whole [from, to] (disclosed).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.analysis.maker_search_declarations import (
    SEARCH_DECLARATIONS,
    declaration_row,
    is_trigger_check_token,
)

_DERIVED: Final[Path] = Path.home() / ".local/share/breezy/derived/maker_stage0"
DEFAULT_READ_LEDGER: Final[Path] = _DERIVED / "search_read_ledger.jsonl"
DEFAULT_TRIGGER_CLOSE: Final[Path] = _DERIVED / "trigger_close.json"
GENESIS_CHAIN: Final[str] = hashlib.sha256(b"").hexdigest()
LEDGER_FIELDS: Final[tuple[str, ...]] = ("sha", "mode", "from", "to", "rows_chain_sha256", "ts")
COUNT_FIELDS: Final[tuple[str, ...]] = ("station", "climate_day", "reason", "first_seen_ns")
MODE_COUNTS_ONLY: Final[str] = "counts_only"
MODE_FULL: Final[str] = "full"
_POST: Final[str] = "_post"
_LAG_DAYS: Final[int] = 2  # a day is readable once its instance has rotated: today - 2


@dataclass(frozen=True, slots=True)
class SecondLookRead:
    """An open (pre-read line written) second-look invocation."""

    sha: str
    mode: str
    day_from: dt.date
    day_to: dt.date
    ledger: Path
    chain: str


def utc_today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def count_fields(row: Any) -> dict[str, object]:
    """The four counts-only fields of a census row (the whole of what counts-only emits)."""
    return {
        "station": row.station,
        "climate_day": row.climate_day.isoformat(),
        "reason": row.reason,
        "first_seen_ns": row.first_seen_ns,
    }


def rows_chain(prev: str, rows: Iterable[Mapping[str, object]]) -> str:
    """Chain hash: sha256(prev || sha256 of the canonical, ordered counts rows)."""
    body = "".join(
        json.dumps({k: row[k] for k in COUNT_FIELDS}, sort_keys=True, separators=(",", ":")) + "\n"
        for row in sorted(rows, key=lambda r: (str(r["station"]), str(r["climate_day"])))
    )
    return hashlib.sha256((prev + hashlib.sha256(body.encode()).hexdigest()).encode()).hexdigest()


def read_ledger_lines(path: Path) -> list[dict[str, Any]]:
    """Every ledger line; a missing file is empty, a malformed line fails closed."""
    if not path.exists():
        return []
    lines: list[dict[str, Any]] = []
    for text in path.read_text(encoding="utf-8").splitlines():
        if not text.strip():
            continue
        entry = json.loads(text)
        if not isinstance(entry, dict) or set(entry) != set(LEDGER_FIELDS):
            raise ValueError(f"read-ledger line has unexpected fields: {text[:80]!r}")
        lines.append(entry)
    return lines


def holdout_start_floor(read_ledger: Path) -> dt.date:
    """Earliest legal S5 holdout start: the latest census-invoked day plus two."""
    lines = read_ledger_lines(read_ledger)
    if not lines:
        raise ValueError(f"read-ledger {read_ledger} is empty; no invoked day to floor on")
    return max(dt.date.fromisoformat(x["to"]) for x in lines) + dt.timedelta(days=2)


def _close_end(trigger_close: Path | None) -> dt.date | None:
    if trigger_close is None or not trigger_close.exists():
        return None
    try:
        return dt.date.fromisoformat(json.loads(trigger_close.read_text(encoding="utf-8"))["E"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"trigger_close {trigger_close} is unreadable: {exc}") from exc


def _refuse_full(
    *, row: int, day_from: dt.date, day_to: dt.date, end: dt.date | None, lines: Sequence[Any]
) -> None:
    if end is None:
        raise ValueError("a full census is refused before trigger close (no trigger_close file)")
    if day_from != SEARCH_DECLARATIONS[row].first_day:
        raise ValueError("a full census must start at S: from must equal S")
    if day_to != end:
        raise ValueError(f"a full census must end at the closed E: to must equal E ({end})")
    sha = SEARCH_DECLARATIONS[row].sha256
    if any(x["sha"] == sha and x["mode"] == MODE_FULL for x in lines):
        raise ValueError("a second full census under this sha needs a dated addendum")


def _append(path: Path, entry: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(entry), sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _entry(sha: str, mode: str, a: dt.date, b: dt.date, chain: str) -> dict[str, str]:
    ts = dt.datetime.now(dt.UTC).isoformat()
    return {
        "sha": sha, "mode": mode, "from": a.isoformat(), "to": b.isoformat(),
        "rows_chain_sha256": chain, "ts": ts,
    }  # fmt: skip


def begin_second_look(
    *,
    keys: Iterable[tuple[str, dt.date]],
    counts_only: bool,
    day_from: dt.date,
    day_to: dt.date,
    read_ledger: Path | None,
    today: dt.date | None,
    trigger_close: Path | None,
    trigger_check_token: str | None,
) -> SecondLookRead | None:
    """Refuse or ledger a second-look invocation; ``None`` when no row >= 1 day is planned."""
    rows = {r for r in (declaration_row(s, d) for s, d in keys) if r is not None and r >= 1}
    if not rows:
        return None
    row = max(rows)
    limit = (today or utc_today()) - dt.timedelta(days=_LAG_DAYS)
    if day_to > limit:
        raise ValueError(f"range end {day_to} is after today - 2 ({limit}); instance not rotated")
    if read_ledger is None:
        raise ValueError("a second-look census needs a read-ledger path")
    end = _close_end(trigger_close)
    if end is not None and day_to > end:
        raise ValueError(f"range end {day_to} is after E ({end}) from trigger_close")
    lines = read_ledger_lines(read_ledger)
    if counts_only:
        if end is None and not is_trigger_check_token(trigger_check_token):
            raise ValueError("counts-only before close is permitted only inside a trigger check")
    else:
        _refuse_full(row=row, day_from=day_from, day_to=day_to, end=end, lines=lines)
    sha = SEARCH_DECLARATIONS[row].sha256
    chain = next((x["rows_chain_sha256"] for x in reversed(lines) if x["sha"] == sha), None)
    mode = MODE_COUNTS_ONLY if counts_only else MODE_FULL
    session = SecondLookRead(sha, mode, day_from, day_to, read_ledger, chain or GENESIS_CHAIN)
    _append(read_ledger, _entry(sha, mode, day_from, day_to, session.chain))
    return session


def commit_rows(session: SecondLookRead | None, rows: Iterable[Mapping[str, object]]) -> None:
    """Post-read line: commit this invocation's rows into the chain (no-op for row 0)."""
    if session is None:
        return
    chain = rows_chain(session.chain, rows)
    _append(
        session.ledger,
        _entry(session.sha, session.mode + _POST, session.day_from, session.day_to, chain),
    )


def write_counts_only(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    """Counts-only output: four fields per line, nothing else, sealed 0400."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        json.dumps({k: row[k] for k in COUNT_FIELDS}, sort_keys=True, separators=(",", ":")) + "\n"
        for row in sorted(rows, key=lambda r: (str(r["station"]), str(r["climate_day"])))
    )
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    tmp.write_text(body, encoding="utf-8")
    tmp.chmod(0o400)
    tmp.replace(path)
