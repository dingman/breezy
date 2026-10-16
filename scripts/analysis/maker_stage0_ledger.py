"""MAKER-S2 WP1: the verdict ledger, its atomic claim and the ``.void`` run-directory helper.

Plan r4 delta (c). ``verdict_ledger.jsonl`` is keyed by the amendment sha. WP6 calls
:func:`claim_verdict_run` once, after every preflight check passes and BEFORE the S-7 pre-pass
(so a launch refused for a trivial reason never burns the ledger). The claim checks and appends
under ONE ``flock`` on a ``.lock`` file beside the ledger, so two launches cannot both win.

A verdict run is refused while a start entry exists, unless a dated addendum (supplied by its
sha) names the latest entry's ``run_id`` AND that run was voided through :func:`void_run_dir`:
the ``kind=void`` ledger record holds the directory's ``tree_sha256``; the addendum is accepted
only while the directory still digests to it and holds none of :data:`FORBIDDEN_RESULT_GLOBS`
(wider than amendment s3 by design: a finished run renamed and stripped of results has no void
record and so can never be re-run). A run that dies is renamed ``<run_id>.void`` and pinned
WITHOUT ever opening ``episodes.jsonl``; symlinks are refused, never followed.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import fnmatch
import hashlib
import json
import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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
    "claim_verdict_run",
    "ledger_refuses",
    "load_addendum",
    "tree_digest",
    "void_run_dir",
]

LEDGER_FILENAME: Final[str] = "verdict_ledger.jsonl"
VOID_SUFFIX: Final[str] = ".void"
KIND_START: Final[str] = "verdict_run_start"
KIND_VOID: Final[str] = "void"
#: A voided run may hold none of these (an addendum is refused otherwise).
FORBIDDEN_RESULT_GLOBS: Final[tuple[str, ...]] = (
    "scored_episodes.csv",
    "s3_inputs.json",
    "verdict.*",
    "station_days.csv",
    "stress_*_station_days.csv",
    "overlay_station_days.csv",
    "*.md",
    "report*",
)
#: Hashed by name and size only: a voided run's fills are never read.
UNOPENED_FILES: Final[tuple[str, ...]] = ("episodes.jsonl",)
_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^voided_run_id:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
_START_KEYS: Final[frozenset[str]] = frozenset(
    {"amendment_sha", "run_id", "code_sha", "ts", "kind", "addendum_sha"}
)
#: Per kind, the exact accepted key sets. A start entry is the legacy six keys, or those six plus
#: ``block_first_day`` (never null: a claim without a block omits the key). All else is refused.
_KEYS_BY_KIND: Final[Mapping[str, frozenset[frozenset[str]]]] = {
    KIND_START: frozenset({_START_KEYS, _START_KEYS | {"block_first_day"}}),
    KIND_VOID: frozenset({frozenset({"run_id", "ts", "kind", "tree_sha256", "files"})}),
}

Entry = Mapping[str, object]


class LedgerRefused(ValueError):
    """The ledger, an addendum or a run directory forbids the requested action."""


@dataclass(frozen=True, slots=True)
class Addendum:
    path: Path
    sha256: str
    run_id: str


def load_addendum(path: Path, expected_sha: str) -> Addendum:
    """A dated addendum, sha-checked, naming the voided run via a ``voided_run_id:`` line."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LedgerRefused(f"addendum {path.name} unreadable ({type(exc).__name__})") from exc
    digest = sha256_bytes(data)
    if digest != expected_sha:
        raise LedgerRefused(f"addendum sha {digest} != supplied {expected_sha}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LedgerRefused(f"addendum {path.name} is not utf-8") from exc
    match = _RUN_ID_RE.search(text)
    if match is None:
        raise LedgerRefused("the addendum names no voided_run_id")
    return Addendum(path=path, sha256=digest, run_id=match.group(1))


# --- locked, durable append ---------------------------------------------------------------


@contextmanager
def _locked(ledger: Path) -> Iterator[None]:
    """Exclusive ``flock`` on ``<ledger>.lock`` (the ledger itself may not exist yet)."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    lock = ledger.with_name(ledger.name + ".lock")
    with lock.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append(ledger: Path, entry: Entry) -> None:
    """Append one keyed JSON line and fsync it (the ledger is the one-shot burn record)."""
    line = json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(ledger.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _stamp(now: dt.datetime) -> str:
    return now.astimezone(dt.UTC).isoformat()


def _check_block_first_day(value: object) -> None:
    """A recorded block day is an ISO date string; null or anything else is refused."""
    if not isinstance(value, str):
        raise TypeError("block_first_day")
    dt.date.fromisoformat(value)


def _read_entries(ledger: Path) -> list[Entry]:
    if not ledger.exists():
        return []
    entries: list[Entry] = []
    try:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            kind = entry.get("kind") if isinstance(entry, dict) else None
            expected = _KEYS_BY_KIND.get(kind) if isinstance(kind, str) else None
            if expected is None or frozenset(entry) not in expected:
                raise ValueError("entry keys")
            if "block_first_day" in entry:
                _check_block_first_day(entry["block_first_day"])
            entries.append(entry)
    except (OSError, ValueError, TypeError) as exc:
        raise LedgerRefused(
            f"ledger {ledger} is unreadable ({type(exc).__name__}): refusing"
        ) from exc
    return entries


# --- the policy ---------------------------------------------------------------------------


def _forbidden(names: list[str]) -> list[str]:
    return sorted(
        {
            name
            for name in names
            if any(fnmatch.fnmatch(Path(name).name, glob) for glob in FORBIDDEN_RESULT_GLOBS)
        }
    )


def _void_refusal(entries: list[Entry], void_dir: Path, run_id: str) -> str | None:
    records = [e for e in entries if e["kind"] == KIND_VOID and e["run_id"] == run_id]
    if not records:
        return f"run {run_id!r} has no void record in the ledger (not voided by void_run_dir)"
    record = records[-1]
    if tree_digest(void_dir) != record["tree_sha256"]:
        return f"run {run_id!r} changed since it was voided (digest mismatch)"
    recorded = record["files"]
    held = _forbidden([*(recorded if isinstance(recorded, list) else []), *_tree_names(void_dir)])
    if held:
        return f"run {run_id!r} holds result files {held}: its result stands"
    return None


def _addendum_refusal(
    entries: list[Entry], mine: list[Entry], runs_root: Path, addendum: Addendum
) -> str | None:
    if any(e["addendum_sha"] == addendum.sha256 for e in mine):
        return f"addendum {addendum.sha256[:12]} was already used by a later run"
    latest = mine[-1]["run_id"]
    if addendum.run_id != latest:
        return f"addendum names {addendum.run_id!r}, not the latest ledger run {latest!r}"
    void_dir = runs_root / f"{addendum.run_id}{VOID_SUFFIX}"
    if not void_dir.is_dir() or (runs_root / addendum.run_id).exists():
        return f"run {addendum.run_id!r} is not {VOID_SUFFIX}-renamed ({void_dir} missing)"
    return _void_refusal(entries, void_dir, addendum.run_id)


def _is_mine(entry: Entry, amendment_sha: str, block_first_day: str | None) -> bool:
    """A start entry for this amendment, or for this block (``None`` never matches ``None``)."""
    if entry["kind"] != KIND_START:
        return False
    if entry["amendment_sha"] == amendment_sha:
        return True
    return block_first_day is not None and entry.get("block_first_day") == block_first_day


def _refusal(
    entries: list[Entry],
    amendment_sha: str,
    runs_root: Path,
    addendum: Addendum | None,
    block_first_day: str | None = None,
) -> str | None:
    mine = [e for e in entries if _is_mine(e, amendment_sha, block_first_day)]
    if not mine:
        return None
    if addendum is None:
        return (
            f"ledger already holds {len(mine)} verdict run(s) for amendment {amendment_sha[:12]}"
            f" (latest {mine[-1]['run_id']!r}); a dated addendum naming a voided run is required"
        )
    return _addendum_refusal(entries, mine, runs_root, addendum)


def ledger_refuses(
    ledger: Path,
    amendment_sha: str,
    runs_root: Path,
    addendum: Addendum | None = None,
    block_first_day: str | None = None,
) -> str | None:
    """Advisory, unlocked read: ``None`` when a run may start, else the refusal reason.

    The driver must start a run only through :func:`claim_verdict_run`.
    """
    return _refusal(_read_entries(ledger), amendment_sha, runs_root, addendum, block_first_day)


def claim_verdict_run(
    ledger: Path,
    *,
    amendment_sha: str,
    run_id: str,
    code_sha: str,
    now: dt.datetime,
    runs_root: Path,
    addendum: Addendum | None = None,
    block_first_day: str | None = None,
) -> str | None:
    """Check the policy and append the start entry under one lock; ``None`` = claimed.

    ``block_first_day`` (ISO date) also guards the block: a second start for the same block is
    refused across amendment shas unless a dated addendum names its voided latest run.

    A returned string is the refusal reason and nothing was written.
    """
    with _locked(ledger):
        reason = _refusal(
            _read_entries(ledger), amendment_sha, runs_root, addendum, block_first_day
        )
        if reason is not None:
            return reason
        entry: dict[str, object] = {
            "amendment_sha": amendment_sha,
            "run_id": run_id,
            "code_sha": code_sha,
            "ts": _stamp(now),
            "kind": KIND_START,
            "addendum_sha": None if addendum is None else addendum.sha256,
        }
        if block_first_day is not None:
            entry["block_first_day"] = block_first_day
        _append(ledger, entry)
    return None


# --- void ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VoidedRun:
    path: Path
    tree_sha256: str
    unopened: tuple[str, ...]


def _tree_paths(root: Path) -> list[Path]:
    """Every file under ``root``, sorted; a symlink anywhere is refused, never followed."""
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise LedgerRefused(f"{path} is a symlink: refusing to hash through it")
        if path.is_file():
            found.append(path)
    return found


def _tree_names(root: Path) -> list[str]:
    return [p.relative_to(root).as_posix() for p in _tree_paths(root)]


def tree_digest(root: Path) -> str:
    """sha256 over sorted (relative path, size, content sha) rows; unopened files: name and size."""
    digest = hashlib.sha256()
    for path in _tree_paths(root):
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        content = "-" if path.name in UNOPENED_FILES else sha256_file(path)
        digest.update(f"{relative}\t{size}\t{content}\n".encode())
    return digest.hexdigest()


def void_run_dir(run_dir: Path, *, ledger: Path, now: dt.datetime) -> VoidedRun:
    """Rename ``<run_id>`` to ``<run_id>.void``, pin its tree and record it in the ledger."""
    if run_dir.name.endswith(VOID_SUFFIX):
        raise LedgerRefused(f"{run_dir} is already {VOID_SUFFIX}-renamed")
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise LedgerRefused(f"{run_dir} is not a directory (or is a symlink): cannot void")
    target = run_dir.with_name(run_dir.name + VOID_SUFFIX)
    if target.exists():
        raise LedgerRefused(f"{target} already exists")
    _tree_paths(run_dir)  # refuse symlinks before anything moves
    try:
        run_dir.rename(target)
        names = _tree_names(target)
        tree_sha = tree_digest(target)
        with _locked(ledger):
            _append(
                ledger,
                {
                    "kind": KIND_VOID,
                    "run_id": run_dir.name,
                    "tree_sha256": tree_sha,
                    "files": names,
                    "ts": _stamp(now),
                },
            )
    except OSError as exc:
        raise LedgerRefused(f"voiding {run_dir} failed ({type(exc).__name__}): {target}") from exc
    unopened = tuple(sorted(Path(n).name for n in names if Path(n).name in UNOPENED_FILES))
    return VoidedRun(path=target, tree_sha256=tree_sha, unopened=unopened)
