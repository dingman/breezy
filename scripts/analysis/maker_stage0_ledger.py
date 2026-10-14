"""MAKER-S2 WP1: the verdict ledger and the ``.void`` run-directory helper.

Plan r4 delta (c). ``verdict_ledger.jsonl`` is keyed by the amendment sha. WP6 appends an entry
after every preflight check passes and BEFORE the S-7 pre-pass (so a launch refused for a trivial
reason never burns the ledger). A verdict run then refuses while an entry exists, unless a dated
addendum (supplied by its sha) names the latest entry's ``run_id`` and that run's directory is
``.void``-renamed and holds none of the result files. A run that dies is void: its directory is
renamed ``<run_id>.void`` and sha-pinned WITHOUT ever opening ``episodes.jsonl``.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import fnmatch
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.analysis.maker_stage0_inputs import sha256_bytes, sha256_file

__all__ = [
    "FORBIDDEN_RESULT_GLOBS",
    "LEDGER_FILENAME",
    "UNOPENED_FILES",
    "Addendum",
    "LedgerRefused",
    "VoidedRun",
    "append_ledger_entry",
    "ledger_refuses",
    "load_addendum",
    "tree_digest",
    "void_run_dir",
]

LEDGER_FILENAME: Final[str] = "verdict_ledger.jsonl"
VOID_SUFFIX: Final[str] = ".void"
#: A voided run may hold none of these (an addendum is refused otherwise).
FORBIDDEN_RESULT_GLOBS: Final[tuple[str, ...]] = (
    "scored_episodes.csv",
    "s3_inputs.json",
    "verdict.*",
)
#: Hashed by name and size only: a voided run's fills are never read.
UNOPENED_FILES: Final[tuple[str, ...]] = ("episodes.jsonl",)
_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^voided_run_id:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
_ENTRY_KEYS: Final[frozenset[str]] = frozenset(
    {"amendment_sha", "run_id", "code_sha", "ts", "kind", "addendum_sha"}
)


class LedgerRefused(ValueError):
    """The ledger, an addendum or a run directory forbids the requested action."""


@dataclass(frozen=True, slots=True)
class Addendum:
    path: Path
    sha256: str
    run_id: str


def load_addendum(path: Path, expected_sha: str) -> Addendum:
    """A dated addendum, sha-checked, naming the voided run via a ``voided_run_id:`` line."""
    data = path.read_bytes()
    digest = sha256_bytes(data)
    if digest != expected_sha:
        raise LedgerRefused(f"addendum sha {digest} != supplied {expected_sha}")
    match = _RUN_ID_RE.search(data.decode("utf-8"))
    if match is None:
        raise LedgerRefused("the addendum names no voided_run_id")
    return Addendum(path=path, sha256=digest, run_id=match.group(1))


def append_ledger_entry(
    ledger: Path,
    *,
    amendment_sha: str,
    run_id: str,
    code_sha: str,
    now: dt.datetime,
    addendum_sha: str | None = None,
) -> None:
    """Append one keyed JSON line (exclusive lock; the file is append-only)."""
    entry = {
        "amendment_sha": amendment_sha,
        "run_id": run_id,
        "code_sha": code_sha,
        "ts": now.astimezone(dt.UTC).isoformat(),
        "kind": "verdict_run_start",
        "addendum_sha": addendum_sha,
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
    with ledger.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_entries(ledger: Path) -> list[Mapping[str, object]]:
    if not ledger.exists():
        return []
    entries: list[Mapping[str, object]] = []
    try:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
                raise ValueError("entry keys")
            entries.append(entry)
    except (OSError, ValueError) as exc:
        raise LedgerRefused(
            f"ledger {ledger} is unreadable ({type(exc).__name__}): refusing"
        ) from exc
    return entries


def _result_files(void_dir: Path) -> list[str]:
    names = [p.name for p in void_dir.rglob("*") if p.is_file()]
    return sorted(n for n in names if any(fnmatch.fnmatch(n, g) for g in FORBIDDEN_RESULT_GLOBS))


def _addendum_refusal(
    entries: list[Mapping[str, object]], runs_root: Path, addendum: Addendum
) -> str | None:
    if any(e["addendum_sha"] == addendum.sha256 for e in entries):
        return f"addendum {addendum.sha256[:12]} was already used by a later run"
    latest = entries[-1]["run_id"]
    if addendum.run_id != latest:
        return f"addendum names {addendum.run_id!r}, not the latest ledger run {latest!r}"
    void_dir = runs_root / f"{addendum.run_id}{VOID_SUFFIX}"
    if not void_dir.is_dir() or (runs_root / addendum.run_id).exists():
        return f"run {addendum.run_id!r} is not {VOID_SUFFIX}-renamed ({void_dir} missing)"
    found = _result_files(void_dir)
    if found:
        return f"run {addendum.run_id!r} holds result files {found}: its result stands"
    return None


def ledger_refuses(
    ledger: Path, amendment_sha: str, runs_root: Path, addendum: Addendum | None = None
) -> str | None:
    """``None`` when a verdict run may start, else the refusal reason."""
    mine = [e for e in _read_entries(ledger) if e["amendment_sha"] == amendment_sha]
    if not mine:
        return None
    if addendum is None:
        return (
            f"ledger already holds {len(mine)} verdict run(s) for amendment {amendment_sha[:12]}"
            f" (latest {mine[-1]['run_id']!r}); a dated addendum naming a voided run is required"
        )
    return _addendum_refusal(mine, runs_root, addendum)


@dataclass(frozen=True, slots=True)
class VoidedRun:
    path: Path
    tree_sha256: str
    unopened: tuple[str, ...]


def tree_digest(root: Path) -> str:
    """sha256 over sorted (relative path, size, content sha) rows; unopened files: name and size."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        content = "-" if path.name in UNOPENED_FILES else sha256_file(path)
        digest.update(f"{relative}\t{size}\t{content}\n".encode())
    return digest.hexdigest()


def void_run_dir(run_dir: Path) -> VoidedRun:
    """Rename ``<run_id>`` to ``<run_id>.void`` and pin its tree without opening the fills."""
    if run_dir.name.endswith(VOID_SUFFIX):
        raise LedgerRefused(f"{run_dir} is already {VOID_SUFFIX}-renamed")
    target = run_dir.with_name(run_dir.name + VOID_SUFFIX)
    if target.exists():
        raise LedgerRefused(f"{target} already exists")
    run_dir.rename(target)
    unopened = tuple(sorted(p.name for p in target.rglob("*") if p.name in UNOPENED_FILES))
    return VoidedRun(path=target, tree_sha256=tree_digest(target), unopened=unopened)
