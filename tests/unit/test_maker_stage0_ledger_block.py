"""MAKER-S2 C5: the verdict ledger's per-block claim guard (a second licence for one block)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from scripts.analysis.maker_stage0_ledger import (
    Addendum,
    LedgerRefused,
    claim_verdict_run,
    ledger_refuses,
    load_addendum,
    void_run_dir,
)

NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)
SHA_A, SHA_B, SHA_C = "ab" * 32, "cd" * 32, "ef" * 32
BLOCK = "2026-10-10"
LEGACY_KEYS = {"amendment_sha", "run_id", "code_sha", "ts", "kind", "addendum_sha"}


def _claim(
    ledger: Path,
    runs: Path,
    run_id: str,
    *,
    sha: str = SHA_A,
    block: str | None = None,
    addendum: Addendum | None = None,
) -> str | None:
    return claim_verdict_run(
        ledger,
        amendment_sha=sha,
        run_id=run_id,
        code_sha="c" * 40,
        now=NOW,
        runs_root=runs,
        addendum=addendum,
        block_first_day=block,
    )


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "verdict_ledger.jsonl", tmp_path / "runs"


def _void(ledger: Path, runs: Path, run_id: str) -> None:
    (runs / run_id).mkdir(parents=True)
    (runs / run_id / "progress.jsonl").write_text("x")
    void_run_dir(runs / run_id, ledger=ledger, now=NOW)


def _addendum(tmp_path: Path, name: str, run_id: str) -> Addendum:
    path = tmp_path / name
    path.write_text(f"# Addendum {name}\nvoided_run_id: {run_id}\n")
    return load_addendum(path, hashlib.sha256(path.read_bytes()).hexdigest())


def _lines(ledger: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in ledger.read_text().splitlines()]


def _start_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "amendment_sha": SHA_A,
        "run_id": "r0",
        "code_sha": "c" * 40,
        "ts": "2026-10-15T12:00:00+00:00",
        "kind": "verdict_run_start",
        "addendum_sha": None,
    }
    return {**entry, **overrides}


def test_v1_claim_writes_exactly_six_keys(tmp_path: Path) -> None:
    ledger, runs = _paths(tmp_path)
    assert _claim(ledger, runs, "r1") is None
    assert set(_lines(ledger)[0]) == LEGACY_KEYS


def test_v1_claim_never_matches_on_block_first_day(tmp_path: Path) -> None:
    ledger, runs = _paths(tmp_path)
    assert _claim(ledger, runs, "r1", sha=SHA_A) is None
    assert _claim(ledger, runs, "r2", sha=SHA_B) is None  # None never matches None
    assert _claim(ledger, runs, "r3", sha=SHA_C, block=BLOCK) is None  # r1, r2 carry no block


def test_start_entry_key_sets_are_exactly_six_or_seven(tmp_path: Path) -> None:
    ledger, runs = _paths(tmp_path)
    assert _claim(ledger, runs, "r1", sha=SHA_A) is None
    assert _claim(ledger, runs, "r2", sha=SHA_B, block=BLOCK) is None
    first, second = _lines(ledger)
    assert set(first) == LEGACY_KEYS
    assert set(second) == LEGACY_KEYS | {"block_first_day"}
    assert second["block_first_day"] == BLOCK
    ledger.write_text(json.dumps({**second, "surprise": 1}) + "\n")
    with pytest.raises(LedgerRefused):
        ledger_refuses(ledger, SHA_A, runs)


def test_legacy_six_key_entries_still_read(tmp_path: Path) -> None:
    ledger, runs = _paths(tmp_path)
    ledger.write_text(json.dumps(_start_entry()) + "\n")
    reason = ledger_refuses(ledger, SHA_A, runs)
    assert reason is not None and "already holds 1" in reason
    assert ledger_refuses(ledger, SHA_B, runs, block_first_day=BLOCK) is None


def test_second_v2_licence_same_block_refused_without_addendum(tmp_path: Path) -> None:
    ledger, runs = _paths(tmp_path)
    assert _claim(ledger, runs, "r1", sha=SHA_A, block=BLOCK) is None
    reason = _claim(ledger, runs, "r2", sha=SHA_B, block=BLOCK)
    assert reason is not None and "already holds" in reason
    assert len(_lines(ledger)) == 1
    assert _claim(ledger, runs, "r3", sha=SHA_B, block="2026-10-17") is None  # another block


def test_v2_claim_after_void_with_addendum_naming_that_run_is_accepted(tmp_path: Path) -> None:
    ledger, runs = _paths(tmp_path)
    assert _claim(ledger, runs, "r1", sha=SHA_A, block=BLOCK) is None
    _void(ledger, runs, "r1")
    addendum = _addendum(tmp_path, "add1.md", "r1")
    assert _claim(ledger, runs, "r2", sha=SHA_B, block=BLOCK, addendum=addendum) is None
    assert _lines(ledger)[-1]["addendum_sha"] == addendum.sha256


def test_addendum_refusal_uses_latest_run_of_the_block_across_shas(tmp_path: Path) -> None:
    ledger, runs = _paths(tmp_path)
    assert _claim(ledger, runs, "r1", sha=SHA_A, block=BLOCK) is None
    _void(ledger, runs, "r1")
    first = _addendum(tmp_path, "add1.md", "r1")
    assert _claim(ledger, runs, "r2", sha=SHA_B, block=BLOCK, addendum=first) is None
    _void(ledger, runs, "r2")
    stale = _addendum(tmp_path, "add2.md", "r1")
    reason = _claim(ledger, runs, "r3", sha=SHA_A, block=BLOCK, addendum=stale)
    assert reason is not None and "latest" in reason and "'r2'" in reason
    fresh = _addendum(tmp_path, "add3.md", "r2")
    assert _claim(ledger, runs, "r3", sha=SHA_A, block=BLOCK, addendum=fresh) is None


def test_null_block_first_day_entry_is_refused_on_read(tmp_path: Path) -> None:
    ledger, runs = _paths(tmp_path)
    ledger.write_text(json.dumps(_start_entry(block_first_day=None)) + "\n")
    with pytest.raises(LedgerRefused):
        ledger_refuses(ledger, SHA_A, runs)
