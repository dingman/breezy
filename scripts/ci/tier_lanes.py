#!/usr/bin/env python3
"""Deterministic file-lane splitting for ``scripts/ci/run_tier.sh T1 --lanes N``.

Stdlib only: the tier script runs it before any test interpreter is involved.
The split is a pure function of the sorted file list and file sizes, so two
runs over the same tree produce the same lanes. Exactness is NOT trusted to
this module: ``run_tier.sh`` proves the lanes against a whole-tier
``--collect-only`` before it runs anything.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

#: pytest's default ``python_files`` patterns (pyproject sets none).
TEST_FILE_PATTERNS: tuple[str, ...] = ("test_*.py", "*_test.py")

#: Always run serially, after the lanes: the first rewrites ``catalog.py``,
#: the second uses a fixed basetemp and spawns collect-only children.
SERIAL_FILES: tuple[str, ...] = (
    "tests/unit/test_archive_import_contract.py",
    "tests/unit/test_tier_infra.py",
)


def discover_test_files(repo_root: Path, roots: Iterable[str]) -> list[str]:
    """Sorted repo-relative posix paths of pytest-collectable files under ``roots``."""
    found: set[str] = set()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(repo_root / root):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".venv"}]
            for name in filenames:
                if any(fnmatch.fnmatch(name, pat) for pat in TEST_FILE_PATTERNS):
                    found.add((Path(dirpath) / name).relative_to(repo_root).as_posix())
    return sorted(found)


def split_lanes(
    files: Sequence[str],
    lanes: int,
    weight: Callable[[str], int],
    serial_files: Iterable[str] = SERIAL_FILES,
) -> tuple[list[list[str]], list[str]]:
    """Return ``(lanes, serial)``: disjoint, complete, deterministic.

    Longest-processing-time greedy over ``weight``: heaviest file first (ties
    by path) onto the currently lightest lane (ties by lane index). Serial
    files are excluded from every lane and returned in sorted order.
    """
    if lanes < 1:
        raise ValueError(f"lanes must be >= 1, got {lanes}")
    serial_set = set(serial_files)
    serial = sorted(f for f in set(files) if f in serial_set)
    parallel = sorted(f for f in set(files) if f not in serial_set)
    ordered = sorted(parallel, key=lambda f: (-weight(f), f))
    buckets: list[list[str]] = [[] for _ in range(lanes)]
    loads = [0] * lanes
    for path in ordered:
        idx = min(range(lanes), key=lambda i: (loads[i], i))
        buckets[idx].append(path)
        loads[idx] += weight(path)
    return [sorted(bucket) for bucket in buckets], serial


def _write_lanes(out_dir: Path, lanes: list[list[str]], serial: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx, bucket in enumerate(lanes, start=1):
        (out_dir / f"lane{idx}.txt").write_text("\n".join(bucket) + "\n", encoding="utf-8")
    (out_dir / "serial.txt").write_text("\n".join(serial) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lanes", type=int, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("roots", nargs="+")
    args = parser.parse_args(argv)
    files = discover_test_files(args.repo_root, args.roots)
    if not files:
        print("error: no test files discovered", file=sys.stderr)
        return 2
    lanes, serial = split_lanes(
        files, args.lanes, lambda f: (args.repo_root / f).stat().st_size
    )
    _write_lanes(args.out_dir, lanes, serial)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
