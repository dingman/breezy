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
   else is compared. Also FAIL if the unit's Environment names
   ``BREEZY_BUILD_REVISION`` (a declared value, not the tree HEAD).
2. Decode check: ``supervisor_admits_retirement_reason(store,
   "RESOLVER_NO_ID_NO_FILL")`` is True, the marker pid equals ``MainPID``, and a
   synthetic RETIRED intent with that member round-trips in memory.
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
from breezy.runtime.submit_intent import RetirementReason, SubmitIntent, SubmitIntentState
from breezy.runtime.supervisor_decode_marker import (
    read_supervisor_decode_marker,
    supervisor_admits_retirement_reason,
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


@dataclass(frozen=True)
class Probes:
    """Every read the checks make, injectable so the checks are unit-testable."""

    main_pid: Callable[[], int | None]
    unit_environment_names_revision_override: Callable[[], bool]
    supervisor_log_text: Callable[[], str]
    is_ancestor: Callable[[str, str], bool]
    lock_holder_pid: Callable[[], int | None]


def _systemctl_show(prop: str) -> str:
    result = subprocess.run(
        ["systemctl", "--user", "show", UNIT, "-p", prop],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    return result.stdout


def _main_pid() -> int | None:
    match = re.search(r"^MainPID=(\d+)$", _systemctl_show("MainPID"), re.MULTILINE)
    pid = int(match.group(1)) if match else 0
    return pid if pid > 0 else None


def _environment_names_revision_override() -> bool:
    # Presence of the KEY only; the value (and every other variable) is never kept.
    return re.search(rf"\b{BUILD_REVISION_ENV_NAME}=", _systemctl_show("Environment")) is not None


def _is_ancestor(phase_a_sha: str, revision: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "merge-base", "--is-ancestor", phase_a_sha, revision],
        capture_output=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    return result.returncode == 0


def _since_newest_started(log_text: str) -> tuple[str | None, list[str]]:
    """The newest ``supervisor_started`` line and every line after it."""
    lines = log_text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if _STARTED.search(lines[index]):
            return lines[index], lines[index + 1 :]
    return None, []


def check_running_supervisor_descends_from_phase_a(
    store_path: Path | None, phase_a_sha: str, probes: Probes
) -> bool:
    if store_path is None or not _HEX_SHA.match(phase_a_sha):
        return False
    main_pid = probes.main_pid()
    marker = read_supervisor_decode_marker(store_path)
    started, _after = _since_newest_started(probes.supervisor_log_text())
    if main_pid is None or marker is None or started is None:
        return False
    if marker.pid != main_pid:
        return False
    logged = _REVISION.search(started)
    if logged is None or logged.group(1) != marker.revision:
        return False
    if not _HEX_SHA.match(marker.revision):  # package-version / "unknown" fallbacks FAIL
        return False
    if probes.unit_environment_names_revision_override():
        return False
    return probes.is_ancestor(phase_a_sha, marker.revision)


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


def check_decode_marker(store_path: Path | None, probes: Probes) -> bool:
    if store_path is None:
        return False
    main_pid = probes.main_pid()
    marker = read_supervisor_decode_marker(store_path)
    if main_pid is None or marker is None or marker.pid != main_pid:
        return False
    if not supervisor_admits_retirement_reason(store_path, NEW_REASON):
        return False
    return _synthetic_retired_round_trips()


def check_same_pid_adoption(
    store_path: Path | None, pre_restart_node_pid: int | None, probes: Probes
) -> bool:
    started, after = _since_newest_started(probes.supervisor_log_text())
    if started is None or store_path is None:
        return False
    if pre_restart_node_pid is None:  # node was down at U1 (delta R12)
        return any(_NODE_DOWN_EVIDENCE.search(line) for line in after)
    adopted = [int(m.group(1)) for line in after if (m := _ADOPTED.search(line))]
    holder = probes.lock_holder_pid()
    return pre_restart_node_pid in adopted and holder == pre_restart_node_pid


def run_checks(
    *, store_path: Path | None, phase_a_sha: str, pre_restart_node_pid: int | None, probes: Probes
) -> tuple[bool, bool, bool]:
    return (
        check_running_supervisor_descends_from_phase_a(store_path, phase_a_sha, probes),
        check_decode_marker(store_path, probes),
        check_same_pid_adoption(store_path, pre_restart_node_pid, probes),
    )


def _parse_node_pid(raw: str) -> int | None:
    if raw.lower() in {"none", "0", "down"}:
        return None
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("pre-restart node pid must be >= 0 or 'none'")
    return value


def _build_probes(store_path: Path | None, log_dir: Path) -> Probes:
    def _log_text() -> str:
        try:
            return supervisor_log_path(log_dir).read_text(errors="replace")
        except OSError:
            return ""

    def _holder() -> int | None:
        return None if store_path is None else resolve_lock_holder_pid(intent_lock_path(store_path))

    return Probes(
        main_pid=_main_pid,
        unit_environment_names_revision_override=_environment_names_revision_override,
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
    for label, ok in zip(labels, results, strict=True):
        print(f"{label} {'PASS' if ok else 'FAIL'}")
    overall = all(results)
    print(f"RESULT {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
