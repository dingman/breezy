"""JUnit parsing, the execution proof, load-flake handling and reference recording.

Stdlib only; split from ``gate_shards.py`` (which owns the CLI). Nothing here
touches the process environment or the filesystem except ``assert_serial_junit_path``'s
name check.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NamedTuple

RC_PROOF_MISMATCH: Final[int] = 4
#: A load-flake rerun is allowed for at most this many distinct failing keys.
MAX_FLAKE_KEYS: Final[int] = 3
#: pytest's own "some tests failed" exit status; any other nonzero job rc is not a flake.
PYTEST_FAILED_RC: Final[int] = 1

Key = tuple[str, str]

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


def env_skip_matches(env_skips: Iterable[EnvSkip], key: Key, message: str) -> EnvSkip | None:
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


# --- JUnit -----------------------------------------------------------------------------------


class Case(NamedTuple):
    classname: str
    name: str
    outcome: str  # pass | skip | xfail | fail
    message: str
    time_s: float


_COLLECT_SKIP_MESSAGE: Final[str] = "collection skipped"


def key_label(key: Key) -> str:
    return f"{key[0]}::{key[1]}"


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


def _group(cases: Iterable[Case]) -> dict[Key, list[Case]]:
    grouped: dict[Key, list[Case]] = {}
    for case in cases:
        grouped.setdefault((case.classname, case.name), []).append(case)
    return grouped


# --- the execution proof ---------------------------------------------------------------------


class Verdict(NamedTuple):
    rc: int
    errors: list[str]
    advisories: list[str]
    notes: list[str]
    summary: str
    authoritative: bool = False
    flaked: tuple[str, ...] = ()


def _listed(reference: Mapping[str, Any], run_slow: str) -> dict[Key, dict[str, str]] | None:
    entries = reference.get("non_pass", {}).get(run_slow)
    if entries is None:
        return None
    return {(e["classname"], e["name"]): e for e in entries}


def _apply_flake_reruns(
    jobs: Mapping[str, Sequence[Case]],
    flake_rerun: Sequence[Case],
    load_flakes: Collection[Key],
    errors: list[str],
) -> tuple[dict[str, list[Case]], list[str]]:
    """Swap each committed load flake's failing case for its single passing rerun.

    All-or-nothing: one failing key off the list (or more than ``MAX_FLAKE_KEYS``)
    forgives nothing. A rerun that fails, repeats a key, or is missing is an error.
    """
    effective = {job: list(cases) for job, cases in jobs.items()}
    if not flake_rerun:
        return effective, []
    failing: dict[Key, list[str]] = {}
    for job, cases in jobs.items():
        for case in cases:
            if case.outcome == "fail":
                failing.setdefault((case.classname, case.name), []).append(job)
    if not failing:
        errors.append("flake-rerun junit is present but no test failed in any job")
        return effective, []
    reruns = _group(flake_rerun)
    for key, rerun_cases in sorted(reruns.items()):
        if any(c.outcome == "fail" for c in rerun_cases):
            errors.append(f"load-flake rerun failed for {key_label(key)}")
    off_list = sorted(k for k in failing if k not in load_flakes)
    if off_list or len(failing) > MAX_FLAKE_KEYS:
        errors.append(
            "load-flake rerun not applicable: failing keys "
            f"{[key_label(k) for k in sorted(failing)][:5]} include off-list or more than "
            f"{MAX_FLAKE_KEYS}"
        )
        return effective, []
    forgiven: list[str] = []
    for key, where in sorted(failing.items()):
        rerun_cases = reruns.get(key, [])
        if len(where) != 1 or len(rerun_cases) != 1 or rerun_cases[0].outcome != "pass":
            errors.append(f"{key_label(key)} has no single passing load-flake rerun")
            continue
        effective[where[0]] = [
            rerun_cases[0] if (c.classname, c.name) == key else c for c in effective[where[0]]
        ]
        forgiven.append(key_label(key))
    return effective, forgiven


def verify(
    *,
    expected_keys: set[Key],
    jobs: Mapping[str, Sequence[Case]],
    collect_cases: Sequence[Case],
    reference: Mapping[str, Any],
    env_skips: Iterable[EnvSkip],
    tail_jobs: set[str],
    run_slow: str,
    primary_tree: bool,
    forced_advisory: Sequence[str] = (),
    load_flakes: Collection[Key] = frozenset(),
    flake_rerun: Sequence[Case] = (),
) -> Verdict:
    """The execution proof. Hard errors exit 4; outcome divergence is hard only on
    the primary tree with a reference set for this ``run_slow`` value and no
    test-seam override (``forced_advisory``)."""
    errors: list[str] = []
    advisories: list[str] = []
    notes: list[str] = []
    skips = list(env_skips)
    listed = _listed(reference, run_slow)
    authoritative = primary_tree and listed is not None and not forced_advisory

    def diverge(message: str) -> None:
        (errors if authoritative else advisories).append(message)

    if listed is None:
        (errors if primary_tree else advisories).append(
            f"no reference non_pass set for run_slow={run_slow}"
        )
    effective, flaked = _apply_flake_reruns(jobs, flake_rerun, load_flakes, errors)
    seen: dict[Key, list[tuple[str, Case]]] = {}
    for job, cases in effective.items():
        for case in cases:
            seen.setdefault((case.classname, case.name), []).append((job, case))
    collect_skips: dict[Key, Case] = {}
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
    for label in flaked:
        notes.append(f"load-flake rerun: {label} failed under load and passed on its serial rerun")
    return Verdict(
        RC_PROOF_MISMATCH if errors else 0,
        errors,
        advisories,
        notes,
        _summary(errors, advisories, authoritative, forced_advisory),
        authoritative,
        tuple(flaked),
    )


def _summary(
    errors: Sequence[str],
    advisories: Sequence[str],
    authoritative: bool,
    forced_advisory: Sequence[str],
) -> str:
    text = f"execution proof: {'FAILED (' + str(len(errors)) + ' errors)' if errors else 'OK'}"
    if not authoritative:
        text += (
            f" -- OUTCOME CHECK ADVISORY ({len(advisories)} skip/xfail divergences not enforced: "
            "off the primary tree, no reference set for this run_slow, or a test seam is active"
        )
        if forced_advisory:
            text += f"; seams: {', '.join(forced_advisory)}"
        text += ")"
    return text


def _judge(
    key: Key,
    job: str,
    case: Case,
    listed: Mapping[Key, Mapping[str, str]] | None,
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


# --- load-flake rerun planning ---------------------------------------------------------------


class FlakePlan(NamedTuple):
    eligible: bool
    reason: str
    args: list[str]
    labels: list[str]


def _no(reason: str) -> FlakePlan:
    return FlakePlan(False, reason, [], [])


def plan_flake_rerun(
    jobs: Mapping[str, Sequence[Case]],
    job_rcs: Mapping[str, int],
    flakes: Mapping[Key, str],
    rerun_args: Mapping[Key, str],
) -> FlakePlan:
    """Decide whether the failures are ONLY committed load flakes.

    ``flakes`` maps a key to its rerun scope; ``rerun_args`` maps a key to the
    pytest argument that reruns it (node id or file). Every nonzero job rc must be
    pytest's plain "tests failed" (1) and be explained by a failing testcase.
    """
    failing: dict[Key, int] = {}
    failing_jobs: set[str] = set()
    for job, cases in jobs.items():
        for case in cases:
            if case.outcome == "fail":
                key = (case.classname, case.name)
                failing[key] = failing.get(key, 0) + 1
                failing_jobs.add(job)
    if not failing:
        return _no("no failing testcase in any job junit")
    off_list = sorted(k for k in failing if k not in flakes)
    if off_list:
        return _no(f"failing key not on the load_flakes list: {key_label(off_list[0])}")
    if len(failing) > MAX_FLAKE_KEYS:
        return _no(f"{len(failing)} failing keys exceed the limit of {MAX_FLAKE_KEYS}")
    repeated = sorted(k for k, n in failing.items() if n > 1)
    if repeated:
        return _no(f"failing key reported more than once: {key_label(repeated[0])}")
    for job, rc in sorted(job_rcs.items()):
        if rc != 0 and (rc != PYTEST_FAILED_RC or job not in failing_jobs):
            return _no(f"job {job} rc={rc} is not explained by a failing flake testcase")
    args: list[str] = []
    for key in sorted(failing):
        arg = rerun_args.get(key)
        if arg is None:
            return _no(f"no node id for {key_label(key)} in the collection")
        if arg not in args:
            args.append(arg)
    return FlakePlan(True, "", args, [key_label(k) for k in sorted(failing)])


# --- phase-2-once proof ----------------------------------------------------------------------

_DEFERRED_RE: Final[re.Pattern[str]] = re.compile(
    r"^\[breezy\] gate: phase1 rc=\d+ phase2 DEFERRED \(parallel shard; NOT a gate run\)$"
)
_TAIL_PHASE2_RE: Final[re.Pattern[str]] = re.compile(
    r"^\[breezy\] gate: phase1 rc=\d+ phase2 rc=0$"
)


def phase2_proof(shard_logs: Mapping[str, str | None], tail_log: str | None) -> list[str]:
    """Errors proving phase 2 ran exactly once, in the serial tail, and never in a shard.

    ``shard_logs`` maps each deferred job (shards and the load-flake rerun) to its wrapper
    log text (``None`` = unreadable or absent); ``tail_log`` is the tail's. Every deferred
    log needs exactly one ``DEFERRED`` line and no ``phase2 rc=`` line; the tail log needs
    exactly one ``phase1 rc=N phase2 rc=0`` line, no other ``phase2 rc=`` line and no
    ``DEFERRED`` line. Empty list = proven."""
    errors: list[str] = []
    for name, text in sorted(shard_logs.items()):
        if text is None:
            errors.append(f"phase 2: job {name} has no readable log")
            continue
        lines = text.splitlines()
        deferred = [x for x in lines if "DEFERRED" in x]
        if len(deferred) != 1 or not _DEFERRED_RE.match(deferred[0]):
            errors.append(
                f"phase 2: job {name} has {len(deferred)} DEFERRED line(s); expected exactly one"
            )
        if any("phase2 rc=" in x for x in lines):
            errors.append(f"phase 2: job {name} ran phase 2 (a 'phase2 rc=' line); it must defer")
    if tail_log is None:
        errors.append("phase 2 never ran: the tail has no readable log")
        return errors
    lines = tail_log.splitlines()
    ran = [x for x in lines if _TAIL_PHASE2_RE.match(x)]
    other = [x for x in lines if "phase2 rc=" in x and not _TAIL_PHASE2_RE.match(x)]
    if len(ran) != 1:
        errors.append(
            f"phase 2: the tail has {len(ran)} 'phase2 rc=0' line(s); expected exactly one"
        )
    for line in other:
        errors.append(f"phase 2: the tail reports a failing or odd phase 2: {line}")
    if any("DEFERRED" in x for x in lines):
        errors.append("phase 2: the tail deferred phase 2; it must run it")
    return errors


# --- reference recording ---------------------------------------------------------------------


class RecordResult(NamedTuple):
    reference: dict[str, Any]
    diff: list[str]


_SERIAL_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^serial[\w.-]*\.xml$")


def assert_serial_junit_path(path: Path) -> None:
    if not _SERIAL_NAME_RE.fullmatch(path.name):
        raise ValueError(
            f"record reads only SERIAL gate junit (serial*.xml), never shard output: {path.name}"
        )


def parse_reason_for(items: Iterable[str]) -> dict[str, str]:
    """``--reason-for KEY=TEXT`` arguments -> ``{KEY: TEXT}``; names the bad argument."""
    parsed: dict[str, str] = {}
    for item in items:
        label, sep, text = item.partition("=")
        if not sep or not label.strip() or not text.strip():
            raise ValueError(f"malformed --reason-for {item!r}: expected KEY=TEXT with both parts")
        if label in parsed:
            raise ValueError(f"--reason-for given twice for {label!r}")
        parsed[label] = text
    return parsed


def key_module(key: Key, modules: Collection[str]) -> str | None:
    """The dotted test module (from ``modules``) that owns ``key``, if any."""
    dotted = key[0] or key[1]
    parts = dotted.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in modules:
            return candidate
    return None


def _resolve_reruns(
    cases: Sequence[Case],
    reruns: Sequence[Case],
    reasons_for: Mapping[str, str],
    diff: list[str],
) -> list[Case]:
    """Swap serial failures for their single passing rerun; refuse anything looser."""
    failed = {(c.classname, c.name) for c in cases if c.outcome == "fail"}
    rerun_by_key = _group(reruns)
    for key, group in sorted(rerun_by_key.items()):
        label = key_label(key)
        if key not in failed:
            raise ValueError(f"rerun key {label} did not fail in the serial run")
        if len(group) != 1:
            raise ValueError(f"rerun holds {len(group)} testcases for {label}; need exactly one")
        if group[0].outcome == "pass" and label not in reasons_for:
            raise ValueError(
                f"{label} is substituted by a rerun: give it --reason-for {label}=TEXT"
            )
    resolved: list[Case] = []
    for case in cases:
        key = (case.classname, case.name)
        rerun = rerun_by_key.get(key, [None])[0]
        if case.outcome == "fail" and rerun is not None and rerun.outcome == "pass":
            resolved.append(rerun)
            diff.append(
                f"= {key_label(key)} failed in the serial run, passes in the serial rerun "
                f"-- {reasons_for[key_label(key)]}"
            )
        else:
            resolved.append(case)
    return resolved


def record_reference(
    cases: Sequence[Case],
    reference: Mapping[str, Any] | None,
    *,
    run_slow: str,
    reason: str,
    reasons_for: Mapping[str, str],
    expected_keys: Collection[Key],
    known_modules: Collection[str] = (),
    reruns: Sequence[Case] = (),
) -> RecordResult:
    """Fold a SERIAL run into the reference.

    * ``expected_keys`` (the collected ids) must be covered exactly by ``cases``
      (collection-time skips, with an empty classname, are the only extra keys), so
      a partial serial run cannot prune entries.
    * ``reruns`` are serial re-runs of keys that failed under load; each must be a
      single passing testcase of a key that failed, with its own ``reasons_for``.
    * Whenever a reference file exists (even an empty one), a new or changed non-pass key
      in a test module listed in ``known_modules`` (the modules of the collected run)
      needs its own ``reasons_for``; the blanket ``reason`` covers only keys outside
      those modules (collection-time skips) and the very first seed (no reference at all).
    * Every ``reasons_for`` key must name a key of the serial run or rerun.
    """
    if not reason.strip():
        raise ValueError("a --reason is required to refresh the reference")
    diff: list[str] = []
    seen_labels = {key_label((c.classname, c.name)) for c in [*cases, *reruns]}
    unmatched = sorted(set(reasons_for) - seen_labels)
    if unmatched:
        raise ValueError(f"--reason-for matches no key in the serial run or rerun: {unmatched}")
    cases = _resolve_reruns(cases, reruns, reasons_for, diff)
    keys = [(c.classname, c.name) for c in cases]
    bad = [c for c in cases if c.outcome == "fail"]
    if bad or len(set(keys)) != len(keys):
        raise ValueError(f"serial run is not green: {len(bad)} failing, duplicates possible")
    observed = set(keys)
    missing = sorted(set(expected_keys) - observed)
    extra = sorted(k for k in observed - set(expected_keys) if k[0] != "")
    if missing or extra:
        raise ValueError(
            f"serial junit does not match the collected ids: {len(missing)} missing "
            f"{[key_label(k) for k in missing[:2]]}, {len(extra)} extra "
            f"{[key_label(k) for k in extra[:2]]}"
        )
    old_sets: dict[str, list[dict[str, str]]] = dict((reference or {}).get("non_pass", {}))
    strict = reference is not None  # a reference file exists: no blanket reasons in it
    old = {(e["classname"], e["name"]): e for e in old_sets.get(run_slow, [])}
    entries: list[dict[str, str]] = []
    for case in sorted(
        (c for c in cases if c.outcome in {"skip", "xfail"}), key=lambda c: (c.classname, c.name)
    ):
        key = (case.classname, case.name)
        label = key_label(key)
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
        module = key_module(key, known_modules)
        if strict and module is not None and label not in reasons_for:
            raise ValueError(
                f"{label} is a new or changed {case.outcome} in existing module {module}: "
                f"give it its own --reason-for {label}=TEXT (the blanket --reason covers new "
                "modules only)"
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
        f"- {key_label(k)} {e['outcome']} {e['message']!r}"
        for k, e in sorted(old.items())
        if k not in kept
    )
    new_sets = {**old_sets, run_slow: entries}
    return RecordResult(
        {"version": 1, "non_pass": {k: new_sets[k] for k in sorted(new_sets)}}, diff
    )
