"""``breezy-autonomy-health``: the AUT-6 unit health pass entry (plan r15 sections 3.9 and 3.11).

``main`` routes three things:

* ``--mark-buildside-restart <unit> --reason <text> --commit <sha>``: the write-once marker the
  build-side implementer writes immediately before a daemon restart (``run_mark_buildside``);
* ``--seed-cursor-now`` (X-14): the activation baseline of the journal cursor (reason
  ``activation_baseline``); it drops journal history only and refuses when a cursor exists;
* otherwise the pass: the bus snapshot, the journal cursor, the classification records, the
  meta-detectors, the C4 ``aut6.health`` verdicts, the heartbeat and the daily rollup. It prints
  one ``AUTONOMY_HEALTH`` summary line and exits 0 for every completed pass, including an UNKNOWN
  one (UNKNOWN is a result the heartbeat, the streak and the dead-man already carry; a non-zero exit
  would only add a second, redundant failure). It exits 3 when the producer's code is not pinned
  (``PRODUCER_SOURCE_SHA256["aut6.health"]``), 2 on bad arguments.

``--dry-run`` reads everything the real pass reads and writes nothing to the live data root: the
pass runs against a scratch copy of ``evidence/unit_health`` with scratch outbox and verdict
roots, prints the summary and the findings it would have recorded, and removes the scratch. It is
how the pass wall time is measured (F6) and how a new unit set is previewed before enabling.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, TextIO

from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.closure import ClosureUnavailable, closure_sha256
from breezy.persistence.autonomy.paths import AutonomyPaths
from breezy.runtime.monitor_watch import production_watch
from breezy.runtime.unit_health import production_env, run_health_pass
from breezy.runtime.unit_health_dryrun import scratch_root
from breezy.runtime.unit_health_fold import FoldSubject
from breezy.runtime.unit_health_store import day_of_ns, default_data_root
from breezy.runtime.unit_health_types import PassEnv, PassResult
from breezy.runtime.unit_health_verdict import HEALTH_PRODUCER_ID, HealthVerdictWriter

__all__ = [
    "EXIT_UNPINNED",
    "EXIT_USAGE",
    "committed_dropins",
    "main",
    "producer_pin_state",
    "run_mark_buildside",
    "run_pass",
]

EXIT_USAGE: Final = 2
EXIT_UNPINNED: Final = 3
ENTRY_MODULE: Final = "breezy.runtime.autonomy_health_cli"
_MARK_FLAG: Final = "--mark-buildside-restart"
_DRY_FLAG: Final = "--dry-run"
_SEED_FLAG: Final = "--seed-cursor-now"
_DEPLOY_DIR: Final = Path(__file__).resolve().parents[3] / "deploy" / "systemd"
_UNPINNED_PLACEHOLDER: Final = "0" * 64


def run_mark_buildside(argv: Sequence[str]) -> int:
    """``--mark-buildside-restart <unit> --reason <text> --commit <sha>`` (plan section 3.9,
    LOW-2): the write-once marker, run by the build-side implementer before a daemon restart.

    The writer lives in ``unit_health_daemons`` (imported lazily: a pass never needs it here).
    """
    from breezy.runtime.unit_health_daemons import run_mark_buildside_restart

    return run_mark_buildside_restart(argv)


def committed_dropins(deploy_dir: Path = _DEPLOY_DIR) -> Mapping[str, frozenset[str]] | None:
    """Unit name -> the drop-in file names committed under ``deploy/systemd/<unit>.d/``.

    ``None`` when the directory cannot be listed or holds none: the drift check is then
    inconclusive and skipped, never a pass over "no drop-ins are committed".
    """
    try:
        found = {
            entry.name.removesuffix(".d"): frozenset(p.name for p in entry.glob("*.conf"))
            for entry in sorted(deploy_dir.glob("*.d"))
            if entry.is_dir()
        }
    except OSError:
        return None
    return found or None


def producer_pin_state() -> tuple[bool, str]:
    """``(pinned, code_sha)``: the closure hash of this entry and whether the pin names it."""
    try:
        code_sha = closure_sha256(ENTRY_MODULE)
    except ClosureUnavailable:
        return False, _UNPINNED_PLACEHOLDER
    return pins.PRODUCER_SOURCE_SHA256.get(HEALTH_PRODUCER_ID) == code_sha, code_sha


def _wire(env: PassEnv, root: Path, read_root: Path, code_sha: str) -> PassEnv:
    """The production seams the S3 core leaves open: fold, verdicts, committed drop-ins."""
    subject = FoldSubject(AutonomyPaths(read_root), store=env.store)
    env.fold_probe = subject.probe
    env.host_verdict = HealthVerdictWriter(
        AutonomyPaths(root), env.store, code_sha=code_sha, subject=subject.subject
    )
    env.committed_dropins = committed_dropins()
    return env


def _summary(result: PassResult, *, wall_s: float, dry_run: bool) -> str:
    reasons = ",".join(dict.fromkeys(result.unknown_reasons)) or "none"
    failed = "unknown" if result.failed_units is None else str(result.failed_units)
    return (
        f"AUTONOMY_HEALTH pass_result={result.pass_result} failed_units={failed} "
        f"new_failures={len(result.new_failures)} foreign_failed={len(result.foreign_failed)} "
        f"journal_blind={len(result.journal_blind)} drift={len(result.drift)} "
        f"allowlisted={len(result.allowlisted)} "
        f"cursor_reset={int(result.cursor_reset)} unknown_reasons={reasons} "
        f"dry_run={int(dry_run)} wall_s={wall_s:.2f}"
    )


def _dry_run_report(env: PassEnv, result: PassResult, out: TextIO) -> None:
    """What the pass would have recorded: one line per failure, foreign unit, drift and finding."""
    for failure in result.new_failures:
        print(
            "AUTONOMY_HEALTH_DRYRUN_FAILURE "
            f"unit={failure.unit} class={failure.unit_class} severity={failure.severity}",
            file=out,
        )
    for unit in result.foreign_failed:
        print(f"AUTONOMY_HEALTH_DRYRUN_FOREIGN unit={unit}", file=out)
    rollup = env.store.read_rollup(day_of_ns(env.now_ns())) or {}
    for name in rollup.get("not_deployed", []):
        print(f"AUTONOMY_HEALTH_DRYRUN_NOT_DEPLOYED name={name}", file=out)
    for listed in result.allowlisted:
        print(f"AUTONOMY_HEALTH_DRYRUN_ALLOWLISTED_DROPIN {listed}", file=out)
    for drift in result.drift:
        print(f"AUTONOMY_HEALTH_DRYRUN_DRIFT {drift.detail} severity={drift.severity}", file=out)
    for record in env.store.finding_records_on(day_of_ns(env.now_ns())):
        print(
            "AUTONOMY_HEALTH_DRYRUN_FINDING "
            f"finding={record.get('finding')} unit={record.get('unit')} "
            f"severity={record.get('severity')}",
            file=out,
        )


def run_pass(
    *,
    dry_run: bool = False,
    environ: Mapping[str, str] | None = None,
    data_root: Path | None = None,
    out: TextIO | None = None,
) -> int:
    """One health pass. ``dry_run`` runs it against a scratch copy and writes nothing live."""
    stream = out if out is not None else sys.stdout
    env_map: Mapping[str, str] = os.environ if environ is None else environ
    root = data_root if data_root is not None else default_data_root()
    pinned, code_sha = producer_pin_state()
    if not pinned and not dry_run:
        print("AUTONOMY_HEALTH pass_result=REFUSED reason=producer_unpinned", file=stream)
        return EXIT_UNPINNED
    started = time.monotonic()
    if dry_run:
        with scratch_root(root) as scratch:
            return _run(scratch, root, env_map, code_sha, started, stream, dry_run=True)
    return _run(root, root, env_map, code_sha, started, stream, dry_run=False)


def _run(
    work: Path,
    read_root: Path,
    environ: Mapping[str, str],
    code_sha: str,
    started: float,
    out: TextIO,
    *,
    dry_run: bool,
) -> int:
    env = _wire(production_env(environ=environ, data_root=work), work, read_root, code_sha)
    if dry_run:
        env.watch = production_watch(read_root)  # reads the live root, writes none
    result = run_health_pass(env)
    print(_summary(result, wall_s=time.monotonic() - started, dry_run=dry_run), file=out)
    if dry_run:
        _dry_run_report(env, result, out)
    return 0


def run_seed_cursor_default() -> int:
    """``--seed-cursor-now`` on the live health tree (X-14); imported lazily like the marker."""
    from breezy.runtime.unit_health_seed import run_seed_cursor

    return run_seed_cursor()


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if _MARK_FLAG in args:
        return run_mark_buildside(args)
    if _SEED_FLAG in args:
        if args != [_SEED_FLAG]:
            sys.stderr.write(f"usage: autonomy_health_cli {_SEED_FLAG} (no other arguments)\n")
            return EXIT_USAGE
        return run_seed_cursor_default()
    unknown = [a for a in args if a != _DRY_FLAG]
    if unknown:
        sys.stderr.write(f"usage: autonomy_health_cli [{_DRY_FLAG}] | {_MARK_FLAG} <unit> ...\n")
        return EXIT_USAGE
    return run_pass(dry_run=_DRY_FLAG in args)


if __name__ == "__main__":
    raise SystemExit(main())
