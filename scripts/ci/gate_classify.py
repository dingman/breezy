"""Classification data for the parallel gate: the serial tail, reviewed parallel-OK
files, host-dependent skips and committed load flakes (``gate_reviewed.json``).

Stdlib only; split from ``gate_shards.py``. The JSON loads lazily so bad data
raises a clear ``ValueError`` at use, never an import crash.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final, NamedTuple

from gate_verify import EnvSkip

CI_DIR: Final[Path] = Path(__file__).resolve().parent
REVIEWED_JSON: Final[Path] = CI_DIR / "gate_reviewed.json"

# --- tier_lanes reuse ------------------------------------------------------------------------

_TIER_LANES: ModuleType | None = None


def tier_lanes() -> ModuleType:
    global _TIER_LANES
    if _TIER_LANES is None:
        spec = importlib.util.spec_from_file_location("tier_lanes", CI_DIR / "tier_lanes.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load tier_lanes.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["tier_lanes"] = module  # dataclasses and pickling resolve by name
        spec.loader.exec_module(module)
        _TIER_LANES = module
    return _TIER_LANES


def split_lanes(
    files: Sequence[str], lanes: int, weight: Callable[[str], int]
) -> tuple[list[list[str]], list[str]]:
    result: tuple[list[list[str]], list[str]] = tier_lanes().split_lanes(
        files, lanes, weight, serial_files=()
    )
    return result


# --- tail and classification -----------------------------------------------------------------


class LoadFlake(NamedTuple):
    """A committed load flake: ``key`` may fail under parallel load and is rerun once.

    ``rerun`` is ``node`` (rerun that node id) or ``file`` (rerun its whole file, for
    a check that only fires when the file's tests run together)."""

    classname: str
    name: str
    rerun: str
    why: str


def _shape_problem(data: Any) -> str | None:
    if not isinstance(data, dict):
        return "top level must be an object"
    for field in ("serial_tail", "groups", "env_skips", "load_flakes"):
        if not isinstance(data.get(field), list):
            return f"{field!r} must be a list"
    for group in data["groups"]:
        if not (isinstance(group, dict) and "reason" in group and "paths" in group):
            return "each group needs 'reason' and 'paths'"
    return None


@functools.cache
def reviewed_data() -> dict[str, Any]:
    """``gate_reviewed.json``; a clear error (not an import crash) when it is bad."""
    try:
        data = json.loads(REVIEWED_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot load {REVIEWED_JSON.name}: {exc}") from exc
    problem = _shape_problem(data)
    if problem is not None:
        raise ValueError(f"bad {REVIEWED_JSON.name}: {problem}")
    result: dict[str, Any] = data
    return result


def serial_tail() -> tuple[str, ...]:
    """Whole files run serially after every shard, beyond ``tier_lanes.SERIAL_FILES``.

    Real-clock budgets, shared fixed paths or host-wide state; see the Phase 0
    classification in docs/core/PARALLEL_GATE.md. A file that flakes in a parallel
    run moves here. (Data lives in gate_reviewed.json.)"""
    return tuple(sorted(reviewed_data()["serial_tail"]))


def reviewed_parallel_ok() -> dict[str, str]:
    """path -> reason this timing/fixed-path file is safe to run beside other shards."""
    return {p: g["reason"] for g in reviewed_data()["groups"] for p in g["paths"]}


def env_skips() -> tuple[EnvSkip, ...]:
    """Host-dependent skips (data in gate_reviewed.json): a matched test may pass or skip."""
    return tuple(EnvSkip(*row) for row in reviewed_data()["env_skips"])


def load_flakes() -> list[LoadFlake]:
    """Committed load flakes. A name without ``[`` covers every parametrisation of that
    function (pytest attaches a module-scoped fixture's teardown error to whichever
    parametrisation runs last, so the failing key moves from run to run)."""
    return [LoadFlake(*row) for row in reviewed_data()["load_flakes"]]


def expand_load_flakes(
    entries: Iterable[LoadFlake], keys: Iterable[tuple[str, str]]
) -> dict[tuple[str, str], LoadFlake]:
    """Exact ``(classname, name)`` keys among the collected ``keys`` that an entry covers."""
    expanded: dict[tuple[str, str], LoadFlake] = {}
    for entry in entries:
        exact = "[" in entry.name
        for classname, name in keys:
            if classname != entry.classname:
                continue
            if (name == entry.name) if exact else (name.partition("[")[0] == entry.name):
                expanded[(classname, name)] = entry
    return expanded


def load_flake_problems(entries: Iterable[LoadFlake], root: Path) -> list[str]:
    problems: list[str] = []
    for entry in entries:
        label = f"{entry.classname}::{entry.name}"
        if entry.rerun not in {"node", "file"}:
            problems.append(f"{label}: rerun must be node or file, got {entry.rerun!r}")
        if not entry.why.strip():
            problems.append(f"{label}: empty justification")
        path = classname_to_file(entry.classname, root)
        if path is None:
            problems.append(f"{label}: no test file for classname {entry.classname!r}")
            continue
        function = entry.name.partition("[")[0]
        if not re.search(rf"\bdef {re.escape(function)}\b", (root / path).read_text("utf-8")):
            problems.append(f"{label}: function {function!r} not found in {path}")
    return problems


def tail_files() -> list[str]:
    """Whole files for the serial tail, sorted."""
    return sorted(set(tier_lanes().SERIAL_FILES) | set(serial_tail()))


_TIMING_RE: Final[re.Pattern[str]] = re.compile(
    r"perf_counter|monotonic|time\.time\(\)|deadline|wait_for|timeout_s"
)
_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"/tmp/|/dev/shm|AF_UNIX|~/\.cache|\$HOME|Path\.home\(\)|expanduser"
)


def _scan(root: Path, pattern: re.Pattern[str]) -> set[str]:
    hits: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root / "tests"):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".venv"}]
        for name in filenames:
            if name.startswith("test_") and name.endswith(".py"):
                path = Path(dirpath) / name
                if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                    hits.add(path.relative_to(root).as_posix())
    return hits


def timing_scan_files(root: Path) -> set[str]:
    return _scan(root, _TIMING_RE)


def path_scan_files(root: Path) -> set[str]:
    return _scan(root, _PATH_RE)


def classification_gaps(
    hits: Iterable[str], tail: Iterable[str], reviewed: Mapping[str, str]
) -> list[str]:
    tail_set = set(tail)
    return sorted(h for h in set(hits) if h not in tail_set and h not in reviewed)


# --- ENV_SKIPS hygiene -----------------------------------------------------------------------


def classname_to_file(classname: str, root: Path) -> str | None:
    parts = classname.split(".")
    while parts:
        candidate = "/".join(parts) + ".py"
        if (root / candidate).is_file():
            return candidate
        parts.pop()
    return None


def env_skip_problems(env_skips: Iterable[EnvSkip], tail: Iterable[str], root: Path) -> list[str]:
    tail_set = set(tail)
    problems: list[str] = []
    for entry in env_skips:
        label = f"{entry.classname}::{entry.name}"
        if entry.tag not in {"static", "resource"}:
            problems.append(f"{label}: tag must be static or resource, got {entry.tag!r}")
        if not entry.why.strip():
            problems.append(f"{label}: empty justification")
        try:
            re.compile(entry.message_re)
        except re.error as exc:
            problems.append(f"{label}: message regex does not compile ({exc})")
        if not (entry.message_re.startswith("^") and entry.message_re.endswith("$")):
            problems.append(f"{label}: message regex must be anchored with ^ and $")
        path = classname_to_file(entry.classname, root)
        if path is None:
            problems.append(f"{label}: no test file for classname {entry.classname!r}")
            continue
        function = entry.name.partition("[")[0]
        text = (root / path).read_text(encoding="utf-8")
        if not re.search(rf"\bdef {re.escape(function)}\b", text):
            problems.append(f"{label}: function {function!r} not found in {path}")
        if entry.tag == "resource" and path not in tail_set:
            problems.append(f"{label}: resource entry requires {path} in the serial tail")
    return problems
