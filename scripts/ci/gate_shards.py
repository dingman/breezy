#!/usr/bin/env python3
"""Sharding, serial-tail and execution-proof logic for the parallel full gate.

Stdlib only: ``scripts/ci/run_tests_parallel.sh`` runs it before any test
interpreter is involved. The parallel gate is an ACCELERATOR; the serial gate
(``scripts/ci/run_tests_no_egress.sh`` with no sharding) stays the reference
(``docs/core/PARALLEL_GATE.md``).

What lives here:

* ``partition`` -- split the whole collection into weighted shards plus a
  serial tail (LPT greedy via ``tier_lanes.split_lanes``). Split files are cut
  at function granularity; consumers of a module-scoped ``AFFINITY`` fixture
  stay together so the expensive fixture is built once.
* ``verify`` -- the execution proof: every collected test must appear exactly
  once in the JUnit output, none may fail, and skips/xfails must be explained
  by ``gate_reference.json`` or ``ENV_SKIPS``.
* ``record_reference`` -- refresh that reference, from SERIAL gate output only.
* guards: fixture drift in split files, the timing/fixed-path classification,
  and ``ENV_SKIPS`` hygiene (enforced by ``tests/unit/test_gate_shards.py``).

It never writes the process environment; the shell driver passes per-command
assignments.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import math
import os
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final, NamedTuple

CI_DIR: Final[Path] = Path(__file__).resolve().parent
REPO_ROOT: Final[Path] = CI_DIR.parents[1]
REVIEWED_JSON: Final[Path] = CI_DIR / "gate_reviewed.json"

# --- sizing ----------------------------------------------------------------------------------

#: Peak resident set of one shard (shell + bwrap + pytest + spawned children),
#: measured in Phase 0 (docs/core/PARALLEL_GATE.md). A shard is budgeted at this.
PER_SHARD_GB: Final[float] = 1.5
#: Memory kept free for the host (live node, nightly studies) before sharding.
MEM_RESERVE_GB: Final[float] = 4.0
MAX_SHARDS: Final[int] = 10
DEFAULT_SHARDS: Final[int] = 10
#: Fallback per-test cost when no duration data exists for a file.
DEFAULT_TEST_MS: Final[int] = 100
#: With no duration file at all, weigh by test count at this many ms per test.
COUNT_WEIGHT_MS: Final[int] = 1000
#: Run names are short so AF_UNIX paths (107 bytes) under the run dir fit.
RUN_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
SOCKET_PATH_LIMIT: Final[int] = 107
SOCKET_NAME_RESERVE: Final[int] = 48
RC_PROOF_MISMATCH: Final[int] = 4
RC_USAGE: Final[int] = 2

# --- split files -----------------------------------------------------------------------------

#: Files cut at function granularity -> module-scoped fixtures whose consumers
#: must share one process. ``world`` is cheap and used everywhere, so it is not
#: an affinity fixture.
SPLIT_FILES: Final[dict[str, tuple[str, ...]]] = {
    "tests/unit/test_maker_stage0_driver.py": ("e2e",),
    "tests/unit/test_aud07_m1c_census.py": ("canonical_cal_b_dir",),
    "tests/unit/test_maker_stage0_isolate.py": (),
    "tests/unit/test_maker_stage0_isolate_followups.py": (),
}


# --- JUnit key scheme ------------------------------------------------------------------------

_ILLEGAL_XML_RE: Final[str] = (
    r"[^\t\n\r\u0020-\u007e\u0080-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)


def _bin_xml_escape(value: str) -> str:
    """Byte-for-byte copy of ``_pytest.junitxml.bin_xml_escape`` (pytest 9.1)."""

    def repl(match: re.Match[str]) -> str:
        code = ord(match.group())
        return f"#x{code:02X}" if code <= 0xFF else f"#x{code:04X}"

    return re.sub(_ILLEGAL_XML_RE, repl, value)


def nodeid_to_key(nodeid: str) -> tuple[str, str]:
    """``(classname, name)`` pytest writes to JUnit for ``nodeid``.

    Copy of ``mangle_test_address``: split at ``[`` first, then ``::``; only
    ``name`` is escaped. Parity with pytest is pinned by a test.
    """
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]), _bin_xml_escape(names[-1])


def file_key(path: str) -> tuple[str, str]:
    """The key of a module-level (collection) skip: ``("", dotted.module)``."""
    return nodeid_to_key(path)


def check_injective(nodeids: Iterable[str]) -> None:
    ids = list(nodeids)
    keys = {nodeid_to_key(i) for i in ids}
    if len(keys) != len(ids):
        seen: dict[tuple[str, str], str] = {}
        for nodeid in ids:
            key = nodeid_to_key(nodeid)
            if key in seen:
                raise ValueError(f"junit keys collide: {seen[key]!r} and {nodeid!r} -> {key!r}")
            seen[key] = nodeid


def expected_keys(
    nodeids: Iterable[str], collect_skips: Iterable[tuple[str, str]]
) -> set[tuple[str, str]]:
    ids = list(nodeids)
    check_injective(ids)
    return {nodeid_to_key(i) for i in ids} | set(collect_skips)


def function_unit(nodeid: str) -> str:
    """``path[::Class]::function`` -- the node id without its parametrisation."""
    return nodeid.partition("[")[0]


# --- fixture analysis (affinity and drift) ---------------------------------------------------

_WIDE_SCOPES: Final[frozenset[str]] = frozenset({"class", "module", "package", "session"})
_MUTATORS: Final[frozenset[str]] = frozenset(
    {
        "append",
        "extend",
        "add",
        "update",
        "setdefault",
        "pop",
        "clear",
        "insert",
        "remove",
        "discard",
        "popitem",
    }
)
_CONTAINER_CALLS: Final[frozenset[str]] = frozenset(
    {"list", "dict", "set", "defaultdict", "deque", "Counter", "OrderedDict"}
)


def _fixture_options(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any] | None:
    """Keyword options of a ``@pytest.fixture`` decorator, or ``None`` if not a fixture."""
    for deco in node.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name != "fixture":
            continue
        options: dict[str, Any] = {}
        if isinstance(deco, ast.Call):
            for kw in deco.keywords:
                if kw.arg and isinstance(kw.value, ast.Constant):
                    options[kw.arg] = kw.value.value
        return options
    return None


def _fixture_scope(options: Mapping[str, Any]) -> str:
    return str(options.get("scope", "function"))


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _arg_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = node.args
    return {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}


def affinity_consumers(source: str, fixtures: Iterable[str]) -> set[str]:
    """Test names (``test_f`` / ``Class::test_m``) using ``fixtures``, directly or
    through another fixture defined in the same file."""
    tree = ast.parse(source)
    fixture_defs = {
        f.name: _arg_names(f) for f in _functions(tree) if _fixture_options(f) is not None
    }
    affected = set(fixtures)
    changed = True
    while changed:
        changed = False
        for name, args in fixture_defs.items():
            if name not in affected and args & affected:
                affected.add(name)
                changed = True
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test") and _arg_names(node) & affected:
                found.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name.startswith("test")
                    and _arg_names(item) & affected
                ):
                    found.add(f"{node.name}::{item.name}")
    return found


def _has_teardown_after_yield(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    yields = [n for n in ast.walk(node) if isinstance(n, (ast.Yield, ast.YieldFrom))]
    if not yields:
        return False
    last = node.body[-1]
    final_plain_yield = (
        len(yields) == 1 and isinstance(last, ast.Expr) and isinstance(last.value, ast.Yield)
    )
    return not final_plain_yield


def _module_accumulators(tree: ast.Module) -> dict[str, int]:
    """Module-level container names that some function mutates (name -> line)."""
    containers: set[str] = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        value = stmt.value
        is_container = isinstance(value, (ast.List, ast.Dict, ast.Set)) or (
            isinstance(value, ast.Call)
            and getattr(value.func, "id", getattr(value.func, "attr", "")) in _CONTAINER_CALLS
        )
        if is_container:
            containers |= {t.id for t in stmt.targets if isinstance(t, ast.Name)}
    mutated: dict[str, int] = {}
    for func in _functions(tree):
        for node in ast.walk(func):
            target: ast.AST | None = None
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in _MUTATORS:
                    target = node.func.value
            elif isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
                targets = (
                    node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
                )
                for t in targets:
                    if isinstance(t, ast.Subscript):
                        target = t.value
            if isinstance(target, ast.Name) and target.id in containers:
                mutated.setdefault(target.id, getattr(node, "lineno", 0))
    return mutated


def _wide_conftest_fixtures(conftest_sources: Iterable[str]) -> dict[str, str]:
    wide: dict[str, str] = {}
    for source in conftest_sources:
        for func in _functions(ast.parse(source)):
            options = _fixture_options(func)
            if options is not None and _fixture_scope(options) in _WIDE_SCOPES:
                wide[func.name] = _fixture_scope(options)
    return wide


def drift_problems(
    source: str, fixtures: Sequence[str], conftest_sources: Iterable[str] = ()
) -> list[str]:
    """Reasons ``source`` is no longer safe to cut at function granularity."""
    tree = ast.parse(source)
    problems: list[str] = []
    defs = {f.name: f for f in _functions(tree) if _fixture_options(f) is not None}
    for name in fixtures:
        func = defs.get(name)
        options = _fixture_options(func) if func is not None else None
        if func is None or options is None:
            problems.append(f"affinity fixture {name!r} is missing")
        elif _fixture_scope(options) != "module":
            problems.append(f"affinity fixture {name!r} is not scope='module'")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"usefixtures", "getfixturevalue"}:
            problems.append(f"{node.attr} at line {node.lineno} hides fixture use from the sharder")
    for name, func in defs.items():
        options = _fixture_options(func) or {}
        scope = _fixture_scope(options)
        if options.get("autouse") and scope in _WIDE_SCOPES:
            problems.append(f"autouse fixture {name!r} has scope {scope!r}")
        if scope in _WIDE_SCOPES and _has_teardown_after_yield(func):
            problems.append(f"{scope}-scoped fixture {name!r} has code after yield")
    for name, line in sorted(_module_accumulators(tree).items()):
        problems.append(f"module-level accumulator {name} is mutated (line {line})")
    wide = _wide_conftest_fixtures(conftest_sources)
    used = {a for f in _functions(tree) for a in _arg_names(f)}
    for name in sorted(set(wide) & used):
        problems.append(f"uses conftest fixture {name!r} (scope {wide[name]!r})")
    return problems


# --- tier_lanes reuse ------------------------------------------------------------------------

_TIER_LANES: ModuleType | None = None


def _tier_lanes() -> ModuleType:
    global _TIER_LANES
    if _TIER_LANES is None:
        spec = importlib.util.spec_from_file_location("tier_lanes", CI_DIR / "tier_lanes.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load tier_lanes.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _TIER_LANES = module
    return _TIER_LANES


def _split_lanes(
    files: Sequence[str], lanes: int, weight: Callable[[str], int]
) -> tuple[list[list[str]], list[str]]:
    result: tuple[list[list[str]], list[str]] = _tier_lanes().split_lanes(
        files, lanes, weight, serial_files=()
    )
    return result


# --- tail and classification -----------------------------------------------------------------


def _reviewed_data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(REVIEWED_JSON.read_text(encoding="utf-8"))
    return data


def _flatten_reviewed(data: Mapping[str, Any]) -> dict[str, str]:
    return {path: g["reason"] for g in data["groups"] for path in g["paths"]}


_REVIEWED: Final[dict[str, Any]] = _reviewed_data()

#: Whole files run serially after every shard, beyond ``tier_lanes.SERIAL_FILES``.
#: Real-clock budgets, shared fixed paths or host-wide state; see the Phase 0
#: classification in docs/core/PARALLEL_GATE.md. A file that flakes in a
#: parallel run moves here. (Data lives in gate_reviewed.json.)
SERIAL_TAIL: Final[tuple[str, ...]] = tuple(sorted(_REVIEWED["serial_tail"]))
#: path -> reason this timing/fixed-path file is safe to run beside other shards.
REVIEWED_PARALLEL_OK: Final[dict[str, str]] = _flatten_reviewed(_REVIEWED)


def tail_files() -> list[str]:
    """Whole files for the serial tail, sorted."""
    return sorted(set(_tier_lanes().SERIAL_FILES) | set(SERIAL_TAIL))


def _default_tail() -> list[str]:
    return tail_files()


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


# --- ENV_SKIPS -------------------------------------------------------------------------------


class EnvSkip(NamedTuple):
    """A skip explained by the host, keyed by an exact ``(classname, name)`` or a
    function prefix (``name`` without ``[``). ``message_re`` is anchored and
    matched against the JUnit ``message`` attribute. ``tag`` is ``static`` (host
    configuration) or ``resource`` (load or capacity; forces the file into the
    serial tail and fails when seen inside a shard)."""

    classname: str
    name: str
    message_re: str
    tag: str
    why: str


#: Host-dependent skips (data in gate_reviewed.json): a matched test may pass or skip.
ENV_SKIPS: Final[tuple[EnvSkip, ...]] = tuple(EnvSkip(*row) for row in _REVIEWED["env_skips"])


def env_skip_matches(
    env_skips: Iterable[EnvSkip], key: tuple[str, str], message: str
) -> EnvSkip | None:
    classname, name = key
    for entry in env_skips:
        if entry.classname != classname:
            continue
        exact = "[" in entry.name
        if (name != entry.name) if exact else (name.partition("[")[0] != entry.name):
            continue
        if re.fullmatch(entry.message_re, message):
            return entry
    return None


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


# --- partition -------------------------------------------------------------------------------


class Partition(NamedTuple):
    shards: list[list[str]]
    tail: list[str]
    weights_ms: dict[str, int]
    warnings: list[str]


class _Unit(NamedTuple):
    key: str
    args: tuple[str, ...]
    weight_ms: int


def refuse_duplicates(ids: Sequence[str]) -> None:
    if len(set(ids)) != len(ids):
        counts: dict[str, int] = {}
        for nodeid in ids:
            counts[nodeid] = counts.get(nodeid, 0) + 1
        dupes = sorted(i for i, c in counts.items() if c > 1)
        raise ValueError(f"duplicate node ids in the collection: {dupes[:3]}")


def _int_ms(value: float) -> int:
    return max(0, round(value))


def _function_weight(
    unit: str,
    count: int,
    file_path: str,
    durations: Mapping[str, Any],
    file_median: dict[str, int],
) -> int:
    classname, name = nodeid_to_key(unit)
    known: Mapping[str, float] = durations.get("functions", {})
    key = f"{classname}::{name}"
    if key in known:
        return _int_ms(known[key])
    if file_path not in file_median:
        dotted = nodeid_to_key(file_path)[1]
        values = [
            v for k, v in known.items() if k.split("::")[0] == dotted or k.startswith(dotted + ".")
        ]
        file_median[file_path] = _int_ms(statistics.median(values)) if values else -1
    if file_median[file_path] >= 0:
        return file_median[file_path]
    return _int_ms(durations.get("median_test_ms", DEFAULT_TEST_MS)) * count


def partition(
    ids: Sequence[str],
    n: int,
    durations: Mapping[str, Any] | None,
    *,
    sources: Mapping[str, str] | None = None,
    split_files: Mapping[str, Sequence[str]] | None = None,
    tail_files: Sequence[str] | None = None,
) -> Partition:
    """Cut ``ids`` into ``n`` weighted shards plus a serial tail of whole files."""
    refuse_duplicates(ids)
    splits = SPLIT_FILES if split_files is None else split_files
    tail_set = set(_default_tail() if tail_files is None else tail_files)
    by_file: dict[str, list[str]] = {}
    for nodeid in ids:
        by_file.setdefault(nodeid.split("::")[0], []).append(nodeid)
    warnings: list[str] = []
    if durations is None:
        warnings.append("no durations file: weighting by test count")
    dur: Mapping[str, Any] = durations or {}
    files_ms: Mapping[str, float] = dur.get("files", {})
    median_ms = _int_ms(dur.get("median_test_ms", DEFAULT_TEST_MS))
    units: list[_Unit] = []
    tail: list[str] = []
    for path in sorted(by_file):
        members = by_file[path]
        if path in tail_set:
            tail.append(path)
        elif path not in splits:
            if durations is None:
                weight = COUNT_WEIGHT_MS * len(members)
            elif path in files_ms:
                weight = _int_ms(files_ms[path])
            else:
                weight = median_ms * len(members)
            units.append(_Unit(path, (path,), weight))
        else:
            units.extend(_split_units(path, members, splits[path], sources, dur, durations is None))
    weights = {u.key: u.weight_ms for u in units}
    by_key = {u.key: u for u in units}
    lanes, _ = _split_lanes(sorted(by_key), n, lambda k: weights[k])
    shards = [sorted(a for k in lane for a in by_key[k].args) for lane in lanes]
    return Partition(shards, sorted(tail), weights, warnings)


def _split_units(
    path: str,
    members: Sequence[str],
    fixtures: Sequence[str],
    sources: Mapping[str, str] | None,
    durations: Mapping[str, Any],
    count_only: bool,
) -> list[_Unit]:
    text = sources[path] if sources and path in sources else (REPO_ROOT / path).read_text("utf-8")
    consumers = affinity_consumers(text, fixtures) if fixtures else set()
    counts: dict[str, int] = {}
    for nodeid in members:
        counts[function_unit(nodeid)] = counts.get(function_unit(nodeid), 0) + 1
    file_median: dict[str, int] = {}
    weight_of: dict[str, int] = {}
    for unit, count in counts.items():
        weight_of[unit] = (
            COUNT_WEIGHT_MS * count
            if count_only
            else _function_weight(unit, count, path, durations, file_median)
        )
    group = sorted(u for u in counts if u.partition("::")[2] in consumers)
    units = [_Unit(u, (u,), weight_of[u]) for u in sorted(counts) if u not in group]
    if group:
        units.append(_Unit("|".join(group), tuple(group), sum(weight_of[u] for u in group)))
    return units


# --- shard count -----------------------------------------------------------------------------


def choose_n(meminfo_text: str, requested: int | None, per_shard_gb: float) -> tuple[int, str]:
    match = re.search(r"^MemAvailable:\s+(\d+)\s*kB", meminfo_text, flags=re.MULTILINE)
    if match is None:
        raise ValueError("MemAvailable not found in meminfo")
    available_gb = int(match.group(1)) / 1048576
    memory_cap = math.floor((available_gb - MEM_RESERVE_GB) / per_shard_gb)
    wanted = min(requested if requested else DEFAULT_SHARDS, MAX_SHARDS)
    n = max(1, min(wanted, memory_cap))
    if memory_cap < wanted:
        reason = (
            f"memory-limited: {available_gb:.1f} GB available, {MEM_RESERVE_GB:g} GB reserved, "
            f"{per_shard_gb:g} GB per shard"
        )
    elif requested:
        reason = f"requested {requested}"
    else:
        reason = f"default {DEFAULT_SHARDS} ({available_gb:.1f} GB available)"
    return n, reason


def aggregate(rcs: Sequence[int]) -> int:
    """First nonzero return code, in the order given; refuses an empty list."""
    if not rcs:
        raise ValueError("empty return-code list")
    return next((rc for rc in rcs if rc != 0), 0)


def validate_run_dir(repo_root: Path, run_dir: Path) -> Path:
    if ".." in run_dir.parts:
        raise ValueError(f"run dir may not contain '..': {run_dir}")
    if run_dir.parent != repo_root / ".pytest-tmp":
        raise ValueError(f"run dir must be directly under {repo_root}/.pytest-tmp/: {run_dir}")
    if not RUN_NAME_RE.fullmatch(run_dir.name):
        raise ValueError(f"run name must match {RUN_NAME_RE.pattern}: {run_dir.name!r}")
    if len(str(run_dir / "bt" / "s00")) + SOCKET_NAME_RESERVE > SOCKET_PATH_LIMIT:
        raise ValueError(f"run dir too long for AF_UNIX socket paths under it: {run_dir}")
    return run_dir


# --- JUnit -----------------------------------------------------------------------------------


class Case(NamedTuple):
    classname: str
    name: str
    outcome: str  # pass | skip | xfail | fail
    message: str
    time_s: float


_COLLECT_SKIP_MESSAGE: Final[str] = "collection skipped"


def _case_outcome(element: ET.Element) -> tuple[str, str]:
    if element.find("failure") is not None or element.find("error") is not None:
        return "fail", ""
    skipped = element.findall("skipped")
    if not skipped:
        return "pass", ""
    outcomes: list[tuple[str, str]] = []
    for node in skipped:
        message = node.get("message", "")
        kind = node.get("type")
        if kind == "pytest.skip":
            outcomes.append(("skip", message))
        elif kind == "pytest.xfail":
            outcomes.append(("xfail", message))
        elif kind is None and message == _COLLECT_SKIP_MESSAGE:
            outcomes.append(("skip", message))
        else:  # strict xpass (no type) or anything unrecognised
            outcomes.append(("fail", message))
    return outcomes[0] if len(outcomes) == 1 else ("fail", "")


def parse_junit(text: str) -> list[Case]:
    cases: list[Case] = []
    for element in ET.fromstring(text).iter("testcase"):
        outcome, message = _case_outcome(element)
        cases.append(
            Case(
                element.get("classname", ""),
                element.get("name", ""),
                outcome,
                message,
                float(element.get("time") or 0.0),
            )
        )
    return cases


class Verdict(NamedTuple):
    rc: int
    errors: list[str]
    advisories: list[str]
    notes: list[str]
    summary: str


def _listed(
    reference: Mapping[str, Any], run_slow: str
) -> dict[tuple[str, str], dict[str, str]] | None:
    entries = reference.get("non_pass", {}).get(run_slow)
    if entries is None:
        return None
    return {(e["classname"], e["name"]): e for e in entries}


def verify(
    *,
    expected_keys: set[tuple[str, str]],
    jobs: Mapping[str, Sequence[Case]],
    collect_cases: Sequence[Case],
    reference: Mapping[str, Any],
    env_skips: Iterable[EnvSkip],
    tail_jobs: set[str],
    run_slow: str,
    primary_tree: bool,
) -> Verdict:
    """The execution proof. Hard errors exit 4; outcome divergence is hard only on
    the primary tree with a reference set for this ``run_slow`` value."""
    errors: list[str] = []
    advisories: list[str] = []
    notes: list[str] = []
    skips = list(env_skips)
    listed = _listed(reference, run_slow)
    authoritative = primary_tree and listed is not None

    def diverge(message: str) -> None:
        (errors if authoritative else advisories).append(message)

    if listed is None:
        (errors if primary_tree else advisories).append(
            f"no reference non_pass set for run_slow={run_slow}"
        )
    seen: dict[tuple[str, str], list[tuple[str, Case]]] = {}
    for job, cases in jobs.items():
        for case in cases:
            seen.setdefault((case.classname, case.name), []).append((job, case))
    collect_skips: dict[tuple[str, str], Case] = {}
    for case in collect_cases:
        key = (case.classname, case.name)
        if case.outcome == "skip" and case.classname == "":
            collect_skips[key] = case
        else:
            errors.append(f"collect job reported {case.outcome} for {key}")
    expected = expected_keys | set(collect_skips)
    observed = set(seen) | set(collect_skips)
    for key in sorted(expected - observed):
        errors.append(f"missing key {key}: collected but never reported")
    for key in sorted(observed - expected):
        errors.append(f"extra key {key}: reported but not collected")
    for key, runs in sorted(seen.items()):
        if len(runs) > 1:
            where = ", ".join(job for job, _ in runs)
            errors.append(
                f"key {key} reported more than one testcase element (twice or more): {where}"
            )
            continue
        job, case = runs[0]
        _judge(key, job, case, listed, skips, tail_jobs, errors, notes, diverge)
    for key, case in sorted(collect_skips.items()):
        _judge(key, "collect", case, listed, skips, tail_jobs, errors, notes, diverge)
    for key, entry in sorted((listed or {}).items()):
        if key[0] == "" and key not in collect_skips:
            notes.append(f"STALE reference entry {key}: the module no longer skips at collection")
    return Verdict(
        RC_PROOF_MISMATCH if errors else 0,
        errors,
        advisories,
        notes,
        _summary(errors, advisories, authoritative),
    )


def _summary(errors: Sequence[str], advisories: Sequence[str], authoritative: bool) -> str:
    text = f"execution proof: {'FAILED (' + str(len(errors)) + ' errors)' if errors else 'OK'}"
    if not authoritative:
        text += (
            f" -- OUTCOME CHECK ADVISORY ({len(advisories)} skip/xfail divergences not enforced: "
            "off the primary tree or no reference set for this run_slow)"
        )
    return text


def _judge(
    key: tuple[str, str],
    job: str,
    case: Case,
    listed: Mapping[tuple[str, str], Mapping[str, str]] | None,
    env_skips: Sequence[EnvSkip],
    tail_jobs: set[str],
    errors: list[str],
    notes: list[str],
    diverge: Callable[[str], None],
) -> None:
    entry = (listed or {}).get(key)
    matched = env_skip_matches(env_skips, key, case.message) if case.outcome == "skip" else None
    if case.outcome == "fail":
        errors.append(f"{key} failed or errored in job {job}")
    elif case.outcome == "skip":
        if matched is not None:
            if matched.tag == "resource" and job not in tail_jobs:
                errors.append(f"{key} hit a resource skip inside shard {job}: {case.message!r}")
        elif entry is None or entry["outcome"] != "skip" or entry["message"] != case.message:
            diverge(f"unlisted skip {key} in {job}: {case.message!r}")
    elif case.outcome == "xfail":
        if entry is None or entry["outcome"] != "xfail":
            diverge(f"unlisted xfail {key} in {job}: {case.message!r}")
    elif entry is not None:
        if entry["outcome"] == "xfail":
            notes.append(f"XPASS {key}: reference lists an xfail but it now passes")
        elif env_skip_matches(env_skips, key, entry["message"]) is None:
            notes.append(f"STALE {key}: reference lists a skip but it now passes")


# --- reference and durations -----------------------------------------------------------------


class RecordResult(NamedTuple):
    reference: dict[str, Any]
    diff: list[str]


_SERIAL_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^serial[\w.-]*\.xml$")


def assert_serial_junit_path(path: Path) -> None:
    if not _SERIAL_NAME_RE.fullmatch(path.name):
        raise ValueError(
            f"record reads only SERIAL gate junit (serial*.xml), never shard output: {path.name}"
        )


def _key_label(key: tuple[str, str]) -> str:
    return f"{key[0]}::{key[1]}"


def record_reference(
    cases: Sequence[Case],
    reference: Mapping[str, Any] | None,
    *,
    run_slow: str,
    reason: str,
    reasons_for: Mapping[str, str],
    reruns: Sequence[Case] = (),
) -> RecordResult:
    """Fold a SERIAL run into the reference. ``reruns`` are serial re-runs of keys
    that failed under load (e.g. the 60 s import budget); each failing key must
    pass in a rerun, and every substitution is printed in the diff."""
    if not reason.strip():
        raise ValueError("a --reason is required to refresh the reference")
    rerun_by_key = {(c.classname, c.name): c for c in reruns if c.outcome != "fail"}
    diff: list[str] = []
    resolved: list[Case] = []
    for case in cases:
        key = (case.classname, case.name)
        if case.outcome == "fail" and key in rerun_by_key:
            resolved.append(rerun_by_key[key])
            diff.append(f"= {_key_label(key)} failed in the serial run, passes in the serial rerun")
        else:
            resolved.append(case)
    cases = resolved
    keys = [(c.classname, c.name) for c in cases]
    bad = [c for c in cases if c.outcome == "fail"]
    if bad or len(set(keys)) != len(keys):
        raise ValueError(f"serial run is not green: {len(bad)} failing, duplicates possible")
    old_sets: dict[str, list[dict[str, str]]] = dict((reference or {}).get("non_pass", {}))
    old = {(e["classname"], e["name"]): e for e in old_sets.get(run_slow, [])}
    entries: list[dict[str, str]] = []
    for case in sorted(
        (c for c in cases if c.outcome in {"skip", "xfail"}), key=lambda c: (c.classname, c.name)
    ):
        key = (case.classname, case.name)
        label = _key_label(key)
        previous = old.get(key)
        if previous is not None and (previous["outcome"], previous["message"]) == (
            case.outcome,
            case.message,
        ):
            entries.append(previous)
            continue
        if previous is not None and label not in reasons_for:
            raise ValueError(
                f"{label} changed from {previous['outcome']} {previous['message']!r}: "
                f"give it its own --reason-for {label}=TEXT"
            )
        why = reasons_for.get(label, reason)
        entries.append(
            {
                "classname": case.classname,
                "name": case.name,
                "outcome": case.outcome,
                "message": case.message,
                "why": why,
            }
        )
        sign = "~" if previous is not None else "+"
        diff.append(f"{sign} {label} {case.outcome} {case.message!r} -- {why}")
    kept = {(e["classname"], e["name"]) for e in entries}
    diff.extend(
        f"- {_key_label(k)} {e['outcome']} {e['message']!r}"
        for k, e in sorted(old.items())
        if k not in kept
    )
    new_sets = {**old_sets, run_slow: entries}
    return RecordResult(
        {"version": 1, "non_pass": {k: new_sets[k] for k in sorted(new_sets)}}, diff
    )


def _dotted_module(path: str) -> str:
    return nodeid_to_key(path)[1]


def build_durations(
    cases: Sequence[Case], known_files: Sequence[str], split_files: Iterable[str]
) -> dict[str, Any]:
    modules = {_dotted_module(f): f for f in known_files}
    splits = set(split_files)
    files_s: dict[str, float] = {}
    functions_s: dict[str, float] = {}
    per_test_ms: list[int] = []
    for case in cases:
        if not case.classname:
            continue
        parts = case.classname.split(".")
        owner = next(
            (
                modules[".".join(parts[:i])]
                for i in range(len(parts), 0, -1)
                if ".".join(parts[:i]) in modules
            ),
            None,
        )
        if owner is None:
            continue
        files_s[owner] = files_s.get(owner, 0.0) + case.time_s
        per_test_ms.append(_int_ms(case.time_s * 1000))
        if owner in splits:
            key = f"{case.classname}::{case.name.partition('[')[0]}"
            functions_s[key] = functions_s.get(key, 0.0) + case.time_s
    return {
        "version": 1,
        "median_test_ms": max(1, _int_ms(statistics.median(per_test_ms))) if per_test_ms else 1,
        "files": {k: _int_ms(v * 1000) for k, v in sorted(files_s.items())},
        "functions": {k: _int_ms(v * 1000) for k, v in sorted(functions_s.items())},
    }


# --- CLI -------------------------------------------------------------------------------------


def _read_ids(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _err(text: str) -> None:
    print(text, file=sys.stderr)


def _cmd_plan_n(args: argparse.Namespace) -> int:
    try:
        n, reason = choose_n(
            Path(args.meminfo).read_text(encoding="utf-8"), args.shards, PER_SHARD_GB
        )
    except (OSError, ValueError) as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    print(n)
    _err(f"[gate] shards={n} ({reason})")
    return 0


def _cmd_check_run_dir(args: argparse.Namespace) -> int:
    try:
        print(validate_run_dir(Path(args.repo_root), Path(args.run_dir)))
    except ValueError as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    return 0


def _cmd_partition(args: argparse.Namespace) -> int:
    ids = _read_ids(Path(args.ids))
    try:
        part = partition(ids, args.shards, _load_json(Path(args.durations)))
    except (ValueError, OSError) as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for index, shard in enumerate(part.shards):
        (out / f"s{index}.args").write_text("".join(f"{a}\n" for a in shard), encoding="utf-8")
    (out / "tail.args").write_text("".join(f"{a}\n" for a in part.tail), encoding="utf-8")
    for warning in part.warnings:
        _err(f"[gate] warning: {warning}")
    loads = [sum(1 for _ in shard) for shard in part.shards]
    _err(f"[gate] partition: {len(ids)} ids, {sum(loads)} shard args, {len(part.tail)} tail files")
    return 0


def _is_primary_tree(repo_root: Path) -> bool:
    return (repo_root / ".git").is_dir()


def _cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.repo_root)
    try:
        ids = _read_ids(Path(args.ids))
        collect_cases = parse_junit(Path(args.collect_xml).read_text(encoding="utf-8"))
        jobs = {
            Path(p).stem: parse_junit(Path(p).read_text(encoding="utf-8"))
            for p in [*args.junit, *args.tail_junit]
            if Path(p).exists()
        }
        reference = _load_json(Path(args.reference)) or {"non_pass": {}}
        verdict = verify(
            expected_keys=expected_keys(ids, []),
            jobs=jobs,
            collect_cases=collect_cases,
            reference=reference,
            env_skips=ENV_SKIPS,
            tail_jobs={Path(p).stem for p in args.tail_junit},
            run_slow=args.run_slow,
            primary_tree=_is_primary_tree(root),
        )
    except (OSError, ValueError, ET.ParseError) as exc:
        _err(f"error: {exc}")
        return RC_PROOF_MISMATCH
    for line in verdict.errors:
        print(f"[proof] ERROR {line}")
    for line in verdict.advisories:
        print(f"[proof] ADVISORY {line}")
    for line in verdict.notes:
        print(f"[proof] note {line}")
    print(f"[proof] {verdict.summary}")
    return verdict.rc


def _cmd_record(args: argparse.Namespace) -> int:
    path = Path(args.from_junit)
    try:
        assert_serial_junit_path(path)
        reruns: list[Case] = []
        for rerun in args.rerun_junit:
            assert_serial_junit_path(Path(rerun))
            reruns.extend(parse_junit(Path(rerun).read_text(encoding="utf-8")))
        reasons_for = dict(item.split("=", 1) for item in args.reason_for)
        result = record_reference(
            parse_junit(path.read_text(encoding="utf-8")),
            _load_json(Path(args.reference)),
            run_slow=args.run_slow,
            reason=args.reason,
            reasons_for=reasons_for,
            reruns=reruns,
        )
    except (OSError, ValueError, ET.ParseError) as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    for line in result.diff:
        print(line)
    if args.dry_run:
        return 0
    _write_json(Path(args.reference), result.reference)
    print(f"wrote {args.reference} (not committed; review the diff)")
    return 0


def _cmd_durations(args: argparse.Namespace) -> int:
    try:
        cases = [
            c for p in args.from_junit for c in parse_junit(Path(p).read_text(encoding="utf-8"))
        ]
        known = _tier_lanes().discover_test_files(REPO_ROOT, ["tests"])
        data = build_durations(cases, known, SPLIT_FILES)
    except (OSError, ValueError, ET.ParseError) as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    _write_json(Path(args.out), data)
    print(f"wrote {args.out}: {len(data['files'])} files, {len(data['functions'])} functions")
    return 0


def _cmd_aggregate(args: argparse.Namespace) -> int:
    try:
        rc = aggregate(args.rcs)
    except ValueError as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    print(rc)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan-n")
    plan.add_argument("--shards", type=int, default=None)
    plan.add_argument("--meminfo", default="/proc/meminfo")
    plan.set_defaults(func=_cmd_plan_n)
    check = sub.add_parser("check-run-dir")
    check.add_argument("--repo-root", default=str(REPO_ROOT))
    check.add_argument("run_dir")
    check.set_defaults(func=_cmd_check_run_dir)
    part = sub.add_parser("partition")
    part.add_argument("--ids", required=True)
    part.add_argument("--shards", type=int, required=True)
    part.add_argument("--durations", default=str(CI_DIR / "gate_durations.json"))
    part.add_argument("--out-dir", required=True)
    part.set_defaults(func=_cmd_partition)
    ver = sub.add_parser("verify")
    ver.add_argument("--ids", required=True)
    ver.add_argument("--collect-xml", required=True)
    ver.add_argument("--junit", nargs="*", default=[])
    ver.add_argument("--tail-junit", nargs="*", default=[])
    ver.add_argument("--reference", default=str(CI_DIR / "gate_reference.json"))
    ver.add_argument("--run-slow", default="0")
    ver.add_argument("--repo-root", default=str(REPO_ROOT))
    ver.set_defaults(func=_cmd_verify)
    rec = sub.add_parser("record")
    rec.add_argument("--from-junit", required=True)
    rec.add_argument("--reference", default=str(CI_DIR / "gate_reference.json"))
    rec.add_argument("--run-slow", default="0")
    rec.add_argument("--reason", required=True)
    rec.add_argument("--reason-for", action="append", default=[])
    rec.add_argument("--rerun-junit", action="append", default=[])
    rec.add_argument("--dry-run", action="store_true")
    rec.set_defaults(func=_cmd_record)
    dur = sub.add_parser("durations")
    dur.add_argument("--from-junit", nargs="+", required=True)
    dur.add_argument("--out", required=True)
    dur.set_defaults(func=_cmd_durations)
    agg = sub.add_parser("aggregate")
    agg.add_argument("rcs", nargs="*", type=int)
    agg.set_defaults(func=_cmd_aggregate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    rc: int = args.func(args)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
