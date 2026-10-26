#!/usr/bin/env python3
"""Sharding, serial-tail and execution-proof logic for the parallel full gate.

Stdlib only: ``scripts/ci/run_tests_parallel.sh`` runs it before any test
interpreter is involved. The parallel gate is an ACCELERATOR; the serial gate
(``scripts/ci/run_tests_no_egress.sh`` with no sharding) stays the reference
(``docs/core/PARALLEL_GATE.md``).

This file is the CLI plus partitioning and the JUnit key scheme. Its stdlib-only
siblings: ``gate_verify`` (JUnit, execution proof, load-flake plan, reference
recording), ``gate_fixtures`` (AST affinity and drift), ``gate_classify`` (reviewed
data, scans, ENV_SKIPS hygiene) and ``gate_host`` (shard sizing, CPU idle, primary
tree). Their public names are re-exported here.

What lives in the whole:

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
import json
import re
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NamedTuple

CI_DIR: Final[Path] = Path(__file__).resolve().parent
REPO_ROOT: Final[Path] = CI_DIR.parents[1]

# The sibling modules live beside this file; loading it by path (the tests do) must
# still find them.
if str(CI_DIR) not in sys.path:
    sys.path.insert(0, str(CI_DIR))

from gate_classify import (
    LoadFlake,
    classification_gaps,
    classname_to_file,
    env_skip_problems,
    env_skips,
    expand_load_flakes,
    load_flake_problems,
    load_flakes,
    path_scan_files,
    reviewed_data,
    reviewed_parallel_ok,
    serial_tail,
    split_lanes,
    tail_files,
    tier_lanes,
    timing_scan_files,
)
from gate_fixtures import affinity_consumers, drift_problems
from gate_host import (
    DEFAULT_SHARDS,
    MAX_SHARDS,
    MEM_RESERVE_GB,
    PER_SHARD_GB,
    TAIL_IDLE_WINDOW_S,
    choose_n,
    cpu_idle_percent,
    gate_root,
    is_primary_tree,
    remove_gate_root,
)
from gate_verify import (
    RC_PROOF_MISMATCH,
    Case,
    EnvSkip,
    RecordResult,
    Verdict,
    assert_serial_junit_path,
    env_skip_matches,
    parse_junit,
    parse_reason_for,
    phase2_proof,
    plan_flake_rerun,
    record_reference,
    verify,
)

#: ``partition`` takes a ``tail_files`` keyword that shadows the function, so it uses this alias.
default_tail = tail_files

#: The public surface the tests and the shell driver use, including names that live in
#: the sibling modules.
__all__ = [
    "DEFAULT_SHARDS",
    "MAX_SHARDS",
    "MEM_RESERVE_GB",
    "PER_SHARD_GB",
    "Case",
    "EnvSkip",
    "LoadFlake",
    "RecordResult",
    "Verdict",
    "affinity_consumers",
    "assert_serial_junit_path",
    "choose_n",
    "classification_gaps",
    "classname_to_file",
    "cpu_idle_percent",
    "drift_problems",
    "env_skip_matches",
    "env_skip_problems",
    "env_skips",
    "expand_load_flakes",
    "is_primary_tree",
    "load_flake_problems",
    "load_flakes",
    "parse_junit",
    "path_scan_files",
    "plan_flake_rerun",
    "record_reference",
    "reviewed_data",
    "reviewed_parallel_ok",
    "serial_tail",
    "tail_files",
    "timing_scan_files",
    "verify",
]

# --- sizing ----------------------------------------------------------------------------------

#: Fallback per-test cost when no duration data exists for a file.
DEFAULT_TEST_MS: Final[int] = 100
#: With no duration file at all, weigh by test count at this many ms per test.
COUNT_WEIGHT_MS: Final[int] = 1000
#: Run names are short so AF_UNIX paths (107 bytes) under the run dir fit.
RUN_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
SOCKET_PATH_LIMIT: Final[int] = 107
SOCKET_NAME_RESERVE: Final[int] = 48
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


def __getattr__(name: str) -> Any:
    """PEP 562: the data constants load on first use, so bad JSON fails at use."""
    if name == "SERIAL_TAIL":
        return serial_tail()
    if name == "REVIEWED_PARALLEL_OK":
        return reviewed_parallel_ok()
    if name == "ENV_SKIPS":
        return env_skips()
    if name == "LOAD_FLAKES":
        return load_flakes()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    tail_set = set(default_tail() if tail_files is None else tail_files)
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
    lanes, _ = split_lanes(sorted(by_key), n, lambda k: weights[k])
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


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return value


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


def _cmd_cpu_idle(args: argparse.Namespace) -> int:
    try:
        before = Path(args.proc_stat).read_text(encoding="utf-8")
        time.sleep(args.window)
        after = Path(args.proc_stat).read_text(encoding="utf-8")
        print(f"{cpu_idle_percent(before, after):.1f}")
    except (OSError, ValueError) as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    return 0


def _cmd_check_run_dir(args: argparse.Namespace) -> int:
    try:
        print(validate_run_dir(Path(args.repo_root), Path(args.run_dir)))
    except ValueError as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    return 0


def _cmd_gate_root(args: argparse.Namespace) -> int:
    try:
        print(gate_root(Path(args.repo_root), Path(args.home), args.run_name))
    except ValueError as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    return 0


def _cmd_rm_gate_root(args: argparse.Namespace) -> int:
    try:
        remove_gate_root(Path(args.home), Path(args.root))
    except (OSError, ValueError) as exc:
        _err(f"error: {exc}")
        return RC_USAGE
    return 0


def _cmd_partition(args: argparse.Namespace) -> int:
    try:
        ids = _read_ids(Path(args.ids))
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
    loads = [len(shard) for shard in part.shards]
    _err(f"[gate] partition: {len(ids)} ids, {sum(loads)} shard args, {len(part.tail)} tail files")
    return 0


def _seam_overrides(items: Sequence[str]) -> list[str]:
    for item in items:
        name, sep, _ = item.partition("=")
        if not sep or not name.startswith("BREEZY_GATE_"):
            raise ValueError(f"malformed --seam {item!r}: expected BREEZY_GATE_NAME=VALUE")
    return list(items)


def _load_reference(path: Path, explicit: bool) -> dict[str, Any]:
    """The reference file; an explicitly requested one that is absent or bad is an error."""
    if explicit and not path.is_file():
        raise ValueError(f"explicit reference file is missing or unreadable: {path}")
    data = _load_json(path)
    result: dict[str, Any] = data or {"non_pass": {}}
    return result


def _read_cases(paths: Iterable[str]) -> dict[str, list[Case]]:
    """Parsed JUnit by job name (file stem); a path that does not exist is skipped, so
    the proof reports its keys as missing."""
    return {
        Path(p).stem: parse_junit(Path(p).read_text(encoding="utf-8"))
        for p in paths
        if Path(p).exists()
    }


def _cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.repo_root)
    authoritative = False
    try:
        ids = _read_ids(Path(args.ids))
        collect_cases = parse_junit(Path(args.collect_xml).read_text(encoding="utf-8"))
        jobs = _read_cases([*args.junit, *args.tail_junit])
        flake_rerun = (
            parse_junit(Path(args.flake_junit).read_text(encoding="utf-8"))
            if args.flake_junit
            else []
        )
        reference = _load_reference(Path(args.reference), args.reference_explicit)
        verdict = verify(
            expected_keys=expected_keys(ids, []),
            jobs=jobs,
            collect_cases=collect_cases,
            reference=reference,
            env_skips=env_skips(),
            tail_jobs={Path(p).stem for p in args.tail_junit},
            run_slow=args.run_slow,
            primary_tree=is_primary_tree(root),
            forced_advisory=_seam_overrides(args.seam),
            load_flakes=set(expand_load_flakes(load_flakes(), expected_keys(ids, []))),
            flake_rerun=flake_rerun,
        )
        authoritative = verdict.authoritative
    except (OSError, ValueError, ET.ParseError) as exc:
        _err(f"error: {exc}")
        _write_status(args.status_out, False)
        return RC_PROOF_MISMATCH
    for line in verdict.errors:
        print(f"[proof] ERROR {line}")
    for line in verdict.advisories:
        print(f"[proof] ADVISORY {line}")
    for line in verdict.notes:
        print(f"[proof] note {line}")
    print(f"[proof] {verdict.summary}")
    _write_status(args.status_out, authoritative)
    return verdict.rc


def _write_status(path: str | None, authoritative: bool) -> None:
    if path:
        Path(path).write_text(
            "authoritative\n" if authoritative else "advisory\n", encoding="utf-8"
        )


def _cmd_flake_plan(args: argparse.Namespace) -> int:
    """Exit 0 and print the keys when every failure is a committed load flake (the rerun
    arguments go to ``--out``); exit 1 when not eligible; exit 4 on bad input."""
    try:
        ids = _read_ids(Path(args.ids))
        jobs: dict[str, list[Case]] = {}
        rcs: dict[str, int] = {}
        for name, rc, junit in args.job:
            rcs[name] = int(rc)
            path = Path(junit)
            jobs[name] = parse_junit(path.read_text(encoding="utf-8")) if path.exists() else []
        by_key = {nodeid_to_key(i): i for i in ids}
        flakes = expand_load_flakes(load_flakes(), by_key)
        rerun_args = {
            key: (by_key[key] if spec.rerun == "node" else by_key[key].split("::")[0])
            for key, spec in flakes.items()
            if key in by_key
        }
        plan = plan_flake_rerun(jobs, rcs, {k: v.rerun for k, v in flakes.items()}, rerun_args)
    except (OSError, ValueError, ET.ParseError) as exc:
        _err(f"error: {exc}")
        return RC_PROOF_MISMATCH
    if not plan.eligible:
        _err(f"[gate] no load-flake rerun: {plan.reason}")
        return 1
    Path(args.out).write_text("".join(f"{a}\n" for a in plan.args), encoding="utf-8")
    print(", ".join(plan.labels))
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    path = Path(args.from_junit)
    try:
        assert_serial_junit_path(path)
        reruns: list[Case] = []
        for rerun in args.rerun_junit:
            assert_serial_junit_path(Path(rerun))
            reruns.extend(parse_junit(Path(rerun).read_text(encoding="utf-8")))
        reasons_for = parse_reason_for(args.reason_for)
        reference = _load_json(Path(args.reference))
        ids = _read_ids(Path(args.ids))
        # "Existing" modules are the ones in the collected run, not a durations snapshot.
        modules = {_dotted_module(i.split("::", 1)[0]) for i in ids}
        result = record_reference(
            parse_junit(path.read_text(encoding="utf-8")),
            reference,
            run_slow=args.run_slow,
            reason=args.reason,
            reasons_for=reasons_for,
            expected_keys=expected_keys(ids, []),
            known_modules=modules,
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
        known = tier_lanes().discover_test_files(REPO_ROOT, ["tests"])
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


def _read_log(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _cmd_phase2_proof(args: argparse.Namespace) -> int:
    shard_logs = {Path(p).stem: _read_log(p) for p in args.shard_log}
    errors = phase2_proof(shard_logs, _read_log(args.tail_log) if args.tail_log else None)
    for line in errors:
        print(f"[phase2] ERROR {line}")
    if errors:
        return RC_PROOF_MISMATCH
    print(f"[phase2] phase 2 ran once, in the tail ({len(shard_logs)} deferred job(s))")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan-n")
    plan.add_argument("--shards", type=_positive_int, default=None)
    plan.add_argument("--meminfo", default="/proc/meminfo")
    plan.set_defaults(func=_cmd_plan_n)
    idle = sub.add_parser("cpu-idle")
    idle.add_argument("--window", type=float, default=TAIL_IDLE_WINDOW_S)
    idle.add_argument("--proc-stat", default="/proc/stat")
    idle.set_defaults(func=_cmd_cpu_idle)
    check = sub.add_parser("check-run-dir")
    check.add_argument("--repo-root", default=str(REPO_ROOT))
    check.add_argument("run_dir")
    check.set_defaults(func=_cmd_check_run_dir)
    groot = sub.add_parser("gate-root")
    groot.add_argument("--repo-root", default=str(REPO_ROOT))
    groot.add_argument("--home", required=True)
    groot.add_argument("run_name")
    groot.set_defaults(func=_cmd_gate_root)
    rmroot = sub.add_parser("rm-gate-root")
    rmroot.add_argument("--home", required=True)
    rmroot.add_argument("root")
    rmroot.set_defaults(func=_cmd_rm_gate_root)
    part = sub.add_parser("partition")
    part.add_argument("--ids", required=True)
    part.add_argument("--shards", type=_positive_int, required=True)
    part.add_argument("--durations", default=str(CI_DIR / "gate_durations.json"))
    part.add_argument("--out-dir", required=True)
    part.set_defaults(func=_cmd_partition)
    ver = sub.add_parser("verify")
    ver.add_argument("--ids", required=True)
    ver.add_argument("--collect-xml", required=True)
    ver.add_argument("--junit", nargs="*", default=[])
    ver.add_argument("--tail-junit", nargs="*", default=[])
    ver.add_argument("--flake-junit", default=None)
    ver.add_argument("--reference", default=str(CI_DIR / "gate_reference.json"))
    ver.add_argument("--reference-explicit", action="store_true")
    ver.add_argument("--seam", action="append", default=[])
    ver.add_argument("--status-out", default=None)
    ver.add_argument("--run-slow", default="0")
    ver.add_argument("--repo-root", default=str(REPO_ROOT))
    ver.set_defaults(func=_cmd_verify)
    flake = sub.add_parser("flake-plan")
    flake.add_argument("--ids", required=True)
    flake.add_argument(
        "--job", nargs=3, action="append", default=[], metavar=("NAME", "RC", "JUNIT")
    )
    flake.add_argument("--out", required=True)
    flake.set_defaults(func=_cmd_flake_plan)
    rec = sub.add_parser("record")
    rec.add_argument("--from-junit", required=True)
    rec.add_argument("--ids", required=True)
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
    p2 = sub.add_parser("phase2-proof")
    p2.add_argument("--shard-log", action="append", default=[])
    p2.add_argument("--tail-log", default=None)
    p2.set_defaults(func=_cmd_phase2_proof)
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
