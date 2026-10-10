"""AMBIG-LATCH-RESUME Phase A check ("U2", plan r6 2.11 + delta D4/R12).

Run by the COORDINATOR (no operator step) after the Phase A merge and the
supervisor restart (U1)::

    /home/jon/breezy/.venv/bin/python scripts/ops/ambig_latch_phase_a_check.py \
        <PHASE_A_SHA> <PRE_RESTART_NODE_PID|none> [--store-path P] [--log-dir D]

Exit 0 iff all three checks pass; prints only ``PASS``/``FAIL`` per check and
a final ``RESULT``. READ-ONLY: it writes no store key, sends no signal, makes
no network call, and never prints a revision, pid, path or environment value.

1. The RUNNING supervisor's code descends from the Phase A merge: the revision
   in the decode marker (bound to ``MainPID`` by pid + /proc start ticks) equals
   the revision of the newest ``supervisor_started`` log line, is a hex sha, and
   ``git merge-base --is-ancestor <PHASE_A_SHA> <revision>`` exits 0 -- nothing
   else is compared. The marker must also match ``MainPID`` by pid AND /proc start
   ticks (a reused pid cannot pass). Also FAIL if ``/proc/<MainPID>/environ``
   (which covers ``EnvironmentFile=`` and ``set-environment``) names
   ``BREEZY_BUILD_REVISION`` (a declared value, not the tree HEAD). Any probe
   failure (systemctl, /proc, git, log read) is a FAIL with a one-line fixed
   cause token, never a traceback and never a pass. A node pid of ``0`` is
   invalid input (exit 2); use ``none`` when the node was down at U1.
2. Decode check: ``supervisor_admits_retirement_reason(store,
   "RESOLVER_NO_ID_NO_FILL")`` is True, the marker pid equals ``MainPID``, and a
   synthetic RETIRED intent with that member round-trips in memory, and
   ``supervisor_admits_slot_schema(store, 2)`` is True (EXEC-PAR WP5a).
3. Same-pid adoption: after that ``supervisor_started`` line, a
   ``permit_watch_adopted_live_node pid=<P>`` line has ``P`` equal to the
   pre-restart node pid AND to the intent-lock holder (``/proc/locks``). With
   ``none`` (node down at U1) the check passes only if ``launch_adopted_live_node``
   or a spawn (``launched pid=`` / ``boot_retry_launched pid=``) is logged
   after it.

Any supervisor restart after this check voids it: re-run against the new
``MainPID``.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.runtime.exec_state_db_path import ExecStateDbNotConfiguredError, resolve_store_path
from breezy.runtime.stop_intent_marker import process_start_ticks
from breezy.runtime.submit_intent import RetirementReason, SubmitIntent, SubmitIntentState
from breezy.runtime.supervisor_decode_marker import (
    read_supervisor_decode_marker,
    supervisor_admits_retirement_reason,
    supervisor_admits_slot_schema,
)
from breezy.runtime.trade_supervisor import (
    intent_lock_path,
    resolve_lock_holder_pid,
    supervisor_log_path,
)

NEW_REASON: Final[str] = "RESOLVER_NO_ID_NO_FILL"
UNIT: Final[str] = "breezy-trade-supervisor"
BUILD_REVISION_ENV_NAME: Final[str] = "BREEZY_BUILD_REVISION"
_HEX_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_STARTED = re.compile(r"\bsupervisor_started\b")
_REVISION = re.compile(r"\brevision=(\S+)")
_ADOPTED = re.compile(r"\bpermit_watch_adopted_live_node pid=(\d+)")
_NODE_DOWN_EVIDENCE = re.compile(
    r"\b(?:launch_adopted_live_node|launched|boot_retry_launched) pid=\d+"
)
_SUBPROCESS_TIMEOUT_S: Final[float] = 15.0
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


class ProbeFailed(Exception):
    """A read the checks depend on failed. ``cause`` is a fixed token, never data."""

    def __init__(self, cause: str) -> None:
        super().__init__(cause)
        self.cause = cause


CheckResult = tuple[bool, str]


@dataclass(frozen=True)
class Probes:
    """Every read the checks make, injectable so the checks are unit-testable.

    Each probe raises :class:`ProbeFailed` (a fixed cause token) on any failure;
    a probe failure is a FAIL, never a traceback and never a pass.
    """

    main_pid: Callable[[], int]
    main_environ_names_revision_override: Callable[[int], bool]
    process_start_ticks: Callable[[int], int | None]
    supervisor_log_text: Callable[[], str]
    is_ancestor: Callable[[str, str], bool]
    lock_holder_pid: Callable[[], int | None]


def _systemctl_main_pid() -> int:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", UNIT, "-p", "MainPID"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        raise ProbeFailed("systemctl_missing") from None
    except subprocess.TimeoutExpired:
        raise ProbeFailed("systemctl_timeout") from None
    except OSError:
        raise ProbeFailed("systemctl_failed") from None
    if result.returncode != 0:
        raise ProbeFailed("systemctl_failed")
    if not result.stdout.strip():
        raise ProbeFailed("systemctl_empty")
    match = re.search(r"^MainPID=(\d+)$", result.stdout, re.MULTILINE)
    pid = int(match.group(1)) if match else 0
    if pid <= 0:
        raise ProbeFailed("mainpid_absent")
    return pid


def _proc_environ_names_revision_override(main_pid: int) -> bool:
    """Presence of the KEY only, read from the running process's own environment
    (covers ``EnvironmentFile=`` and ``set-environment``); no value is retained."""
    try:
        raw = Path(f"/proc/{main_pid}/environ").read_bytes()
    except OSError:
        raise ProbeFailed("environ_unreadable") from None
    if not raw:
        raise ProbeFailed("environ_empty")
    needle = BUILD_REVISION_ENV_NAME.encode() + b"="
    return any(item.startswith(needle) for item in raw.split(b"\0"))


def _is_ancestor(phase_a_sha: str, revision: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "merge-base", "--is-ancestor", phase_a_sha, revision],
            capture_output=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        raise ProbeFailed("git_missing") from None
    except subprocess.TimeoutExpired:
        raise ProbeFailed("git_timeout") from None
    except OSError:
        raise ProbeFailed("git_failed") from None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise ProbeFailed("git_error")


def _since_newest_started(log_text: str) -> tuple[str | None, list[str]]:
    """The newest ``supervisor_started`` line and every line after it."""
    lines = log_text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if _STARTED.search(lines[index]):
            return lines[index], lines[index + 1 :]
    return None, []


def _guarded(check: Callable[[], CheckResult]) -> CheckResult:
    try:
        return check()
    except ProbeFailed as exc:
        return False, exc.cause
    except Exception as exc:  # noqa: BLE001 -- never a traceback; the TYPE name only.
        return False, f"probe_error_{type(exc).__name__}"


def check_running_supervisor_descends_from_phase_a(
    store_path: Path | None, phase_a_sha: str, probes: Probes
) -> CheckResult:
    return _guarded(lambda: _check_one(store_path, phase_a_sha, probes))


def _check_one(store_path: Path | None, phase_a_sha: str, probes: Probes) -> CheckResult:
    if store_path is None:
        return False, "store_path_unresolved"
    if not _HEX_SHA.match(phase_a_sha):
        return False, "phase_a_sha_invalid"
    main_pid = probes.main_pid()
    marker = read_supervisor_decode_marker(store_path)
    if marker is None:
        return False, "marker_absent_or_malformed"
    if marker.pid != main_pid:
        return False, "marker_pid_not_mainpid"
    ticks = probes.process_start_ticks(main_pid)
    if ticks is None or ticks != marker.start_ticks:
        return False, "marker_start_ticks_mismatch"
    started, _after = _since_newest_started(probes.supervisor_log_text())
    if started is None:
        return False, "no_supervisor_started_line"
    logged = _REVISION.search(started)
    if logged is None or logged.group(1) != marker.revision:
        return False, "log_revision_differs_from_marker"
    if not _HEX_SHA.match(marker.revision):  # package-version / "unknown" fallbacks FAIL
        return False, "revision_not_a_sha"
    if probes.main_environ_names_revision_override(main_pid):
        return False, "build_revision_override_set"
    if not probes.is_ancestor(phase_a_sha, marker.revision):
        return False, "not_a_descendant_of_phase_a"
    return True, ""


def _synthetic_retired_round_trips() -> bool:
    try:
        synthetic = SubmitIntent(
            intent_id="0" * 32,
            fingerprint="0" * 64,
            created_ns=1,
            state=SubmitIntentState.RETIRED,
            retired_ns=2,
            retirement_reason=RetirementReason(NEW_REASON),
        )
        decoded = SubmitIntent.from_bytes(synthetic.to_bytes())
    except Exception:  # noqa: BLE001 -- any failure is a FAIL, never printed.
        return False
    return decoded.retirement_reason is RetirementReason.RESOLVER_NO_ID_NO_FILL


def check_decode_marker(store_path: Path | None, probes: Probes) -> CheckResult:
    return _guarded(lambda: _check_two(store_path, probes))


def _check_two(store_path: Path | None, probes: Probes) -> CheckResult:
    if store_path is None:
        return False, "store_path_unresolved"
    main_pid = probes.main_pid()
    marker = read_supervisor_decode_marker(store_path)
    if marker is None:
        return False, "marker_absent_or_malformed"
    if marker.pid != main_pid:
        return False, "marker_pid_not_mainpid"
    if not supervisor_admits_retirement_reason(store_path, NEW_REASON):
        return False, "marker_does_not_admit_new_member"
    if not supervisor_admits_slot_schema(store_path, 2):
        return False, "marker_does_not_admit_slot_schema_2"
    if not _synthetic_retired_round_trips():
        return False, "synthetic_round_trip_failed"
    return True, ""


def check_same_pid_adoption(
    store_path: Path | None, pre_restart_node_pid: int | None, probes: Probes
) -> CheckResult:
    return _guarded(lambda: _check_three(store_path, pre_restart_node_pid, probes))


def _check_three(
    store_path: Path | None, pre_restart_node_pid: int | None, probes: Probes
) -> CheckResult:
    if store_path is None:
        return False, "store_path_unresolved"
    started, after = _since_newest_started(probes.supervisor_log_text())
    if started is None:
        return False, "no_supervisor_started_line"
    if pre_restart_node_pid is None:  # node was down at U1 (delta R12)
        if any(_NODE_DOWN_EVIDENCE.search(line) for line in after):
            return True, ""
        return False, "no_adoption_or_spawn_logged"
    adopted = [int(m.group(1)) for line in after if (m := _ADOPTED.search(line))]
    if pre_restart_node_pid not in adopted:
        return False, "no_adoption_of_pre_restart_pid"
    if probes.lock_holder_pid() != pre_restart_node_pid:
        return False, "lock_holder_differs"
    return True, ""


def run_checks(
    *, store_path: Path | None, phase_a_sha: str, pre_restart_node_pid: int | None, probes: Probes
) -> tuple[CheckResult, CheckResult, CheckResult]:
    return (
        check_running_supervisor_descends_from_phase_a(store_path, phase_a_sha, probes),
        check_decode_marker(store_path, probes),
        check_same_pid_adoption(store_path, pre_restart_node_pid, probes),
    )


def _parse_node_pid(raw: str) -> int | None:
    """``none``/``down`` = the node was down at U1. ``0`` and negatives are invalid
    input (argparse exits 2), never silently read as "node down"."""
    if raw.lower() in {"none", "down"}:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "pre-restart node pid must be a positive int or 'none'"
        ) from None
    if value <= 0:
        raise argparse.ArgumentTypeError("pre-restart node pid must be a positive int or 'none'")
    return value


def _build_probes(store_path: Path | None, log_dir: Path) -> Probes:
    def _log_text() -> str:
        try:
            return supervisor_log_path(log_dir).read_text(errors="replace")
        except OSError:
            raise ProbeFailed("log_unreadable") from None

    def _holder() -> int | None:
        return None if store_path is None else resolve_lock_holder_pid(intent_lock_path(store_path))

    return Probes(
        main_pid=_systemctl_main_pid,
        main_environ_names_revision_override=_proc_environ_names_revision_override,
        process_start_ticks=process_start_ticks,
        supervisor_log_text=_log_text,
        is_ancestor=_is_ancestor,
        lock_holder_pid=_holder,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AMBIG-LATCH-RESUME Phase A check (U2)")
    parser.add_argument("phase_a_sha")
    parser.add_argument("pre_restart_node_pid", type=_parse_node_pid)
    parser.add_argument("--store-path", type=Path, default=None)
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path.home() / ".local" / "share" / "breezy" / "logs",
    )
    args = parser.parse_args(argv)
    store_path: Path | None = args.store_path
    if store_path is None:
        try:
            store_path = resolve_store_path(os.environ)
        except ExecStateDbNotConfiguredError:
            store_path = None  # every store-dependent check then FAILs
    probes = _build_probes(store_path, args.log_dir)
    results = run_checks(
        store_path=store_path,
        phase_a_sha=args.phase_a_sha,
        pre_restart_node_pid=args.pre_restart_node_pid,
        probes=probes,
    )
    labels = ("check1_descends_from_phase_a", "check2_decode_marker", "check3_same_pid_adoption")
    for label, (ok, cause) in zip(labels, results, strict=True):
        print(f"{label} PASS" if ok else f"{label} FAIL {cause}")
    overall = all(ok for ok, _cause in results)
    print(f"RESULT {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
