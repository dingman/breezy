"""The `breezy-quote-tape-preflight` console entrypoint (BL-23).

Run this against a finished capture BEFORE reading a single row of it. The
native read path is silent about truncation -- ``convert_stream_to_data``
delivers zero rows, raises nothing, logs nothing -- and a silently-truncated
tape reads as "quiet market", reads as "no edge". This process turns that into
a non-zero exit code.

A SEPARATE entrypoint from ``breezy-quote-tape``, for the same reason that one
is separate from ``breezy``: it must run on a host with no venue configuration
at all, it opens no socket, and it holds no credential. It reads bytes and
exits.

Exit contract
-------------
===========================  ====  =====================================
Outcome                      Code  Meaning
===========================  ====  =====================================
Intact, rows recovered          0  the tape is safe to interpret
Nothing captured                1  0 rows -- never "success", but not loss
Usage / configuration error     2  matches ``breezy-quote-tape``'s code 2
TRUNCATION DETECTED             3  bytes were written and then cut
===========================  ====  =====================================

Code 3 is distinct from code 1 because the two mean opposite things about the
market: "nothing happened" versus "something happened and we lost it".
Collapsing them is precisely the defect being closed. Code 3 dominates code 1
when both occur.

Read-only by construction: every file is opened ``"rb"``, nothing is written,
moved, or removed, and the catalog it inspects may be the only copy of a tape
that can never be re-recorded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    FeatherFileReport,
    PreflightError,
    PreflightReport,
    list_instance_ids,
    scan_instance,
)

EXIT_OK = 0
EXIT_NOTHING_CAPTURED = 1
EXIT_USAGE = 2
EXIT_TRUNCATED = 3

#: Same variable the recorder requires, so the two processes can never be
#: pointed at different roots by accident.
CATALOG_ENV_VAR = "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"

PROGRAM = "breezy-quote-tape-preflight"

#: A file touched this recently may be mid-write rather than cut. The verdict
#: is NOT softened -- a partial trailing message is a partial trailing message
#: -- but the operator is told to re-run once the recorder has exited.
WRITER_ACTIVITY_GRACE_NS = 60 * 1_000_000_000


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Verify that a streamed feather tape can actually be read back. "
            "Reports truncation loudly instead of returning an empty catalog."
        ),
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help=f"Catalog root. Defaults to ${CATALOG_ENV_VAR}.",
    )
    parser.add_argument(
        "--instance-id",
        action="append",
        dest="instance_ids",
        default=None,
        metavar="ID",
        help="Run instance to check. Repeatable. Default: every instance.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Check only the most recently written instance.",
    )
    parser.add_argument(
        "--subdirectory",
        default=DEFAULT_SUBDIRECTORY,
        help=f"Staging subdirectory (default: {DEFAULT_SUBDIRECTORY}).",
    )
    parser.add_argument("--list", action="store_true", help="List instance ids and exit.")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help=(
            "Print only problem files and the per-instance summary. A real "
            "capture stages hundreds of files; the healthy ones are the noise."
        ),
    )
    return parser


def _resolve_catalog(namespace: argparse.Namespace, env: Mapping[str, str]) -> Path:
    if namespace.catalog is not None:
        root = Path(namespace.catalog)
    else:
        raw = env.get(CATALOG_ENV_VAR, "").strip()
        if not raw:
            raise PreflightError(
                f"no catalog root: pass --catalog or set {CATALOG_ENV_VAR}"
            )
        root = Path(raw)
    if not root.is_dir():
        raise PreflightError(f"catalog root {root} is not a directory")
    return root


def _latest_instance(root: Path, subdirectory: str, instance_ids: Sequence[str]) -> str:
    def newest_write(instance_id: str) -> int:
        directory = root / subdirectory / instance_id
        return max(
            (path.stat().st_mtime_ns for path in directory.rglob("*.feather")),
            default=0,
        )

    return max(instance_ids, key=newest_write)


def _select_instances(
    namespace: argparse.Namespace, root: Path, subdirectory: str
) -> tuple[str, ...]:
    known = list_instance_ids(root, subdirectory)
    if not known:
        raise PreflightError(f"no run instances under {root / subdirectory}")

    if namespace.instance_ids:
        unknown = [name for name in namespace.instance_ids if name not in known]
        if unknown:
            raise PreflightError(
                f"unknown run instance(s) {', '.join(repr(name) for name in unknown)} "
                f"under {root / subdirectory}; known: {', '.join(known)}"
            )
        selected = tuple(namespace.instance_ids)
    else:
        selected = known

    if namespace.latest:
        return (_latest_instance(root, subdirectory, selected),)
    return selected


def _file_line(file: FeatherFileReport, now_ns: int) -> str:
    line = (
        f"  {file.status.value:<12} rows={file.rows:<8} batches={file.batches:<6} "
        f"bytes={file.size_bytes:<10} lost={file.lost_bytes:<8} {file.path.name}"
    )
    if file.failure is not None:
        line += f"\n      ended mid-message: {file.failure}"
    if file.is_truncated and _recently_written(file, now_ns):
        line += (
            "\n      NOTE: this file was still being written seconds ago; a live "
            "writer's tail looks identical to a cut one. Re-run once the recorder "
            "has exited before concluding the tape is lost."
        )
    return line


def _announce(text: str, out: TextIO, err: TextIO) -> None:
    """Say it on stdout, then on stderr -- in that order, visibly.

    ``out`` is flushed first on purpose: when stdout is a pipe it is block
    buffered while stderr is not, so without the flush the verdict reaches the
    operator's terminal BEFORE the per-file detail it summarises.
    """
    print(text, file=out)
    out.flush()
    print(f"{PROGRAM}: {text}", file=err)
    err.flush()


def _recently_written(file: FeatherFileReport, now_ns: int) -> bool:
    return now_ns - file.mtime_ns < WRITER_ACTIVITY_GRACE_NS


def _render(
    reports: Sequence[PreflightReport], stdout: TextIO, now_ns: int, *, quiet: bool
) -> None:
    for report in reports:
        print(f"instance {report.instance_id}:", file=stdout)
        shown = (
            report.truncated + report.unreadable if quiet else report.files
        )
        for file in shown:
            print(_file_line(file, now_ns), file=stdout)
        if quiet and len(shown) < len(report.files):
            print(
                f"  ({len(report.files) - len(shown)} healthy file(s) not shown; "
                "omit --quiet for the full list)",
                file=stdout,
            )
        summary = (
            f"  -> rows={report.total_rows} files={len(report.files)} "
            f"intact={len(report.intact)} empty={len(report.empty)} "
            f"truncated={len(report.truncated)} unreadable={len(report.unreadable)}"
        )
        print(summary, file=stdout)
        if report.captured_nothing:
            print(
                f"  CAPTURED NOTHING: instance {report.instance_id} holds 0 rows. "
                "This is not a pass -- either the recorder never received data, or "
                "it was pointed somewhere else.",
                file=stdout,
            )


def _as_json(reports: Sequence[PreflightReport], exit_code: int) -> dict[str, Any]:
    return {
        "exit_code": exit_code,
        "has_truncation": any(report.has_truncation for report in reports),
        "total_rows": sum(report.total_rows for report in reports),
        "instances": [
            {
                "instance_id": report.instance_id,
                "catalog_root": str(report.catalog_root),
                "subdirectory": report.subdirectory,
                "total_rows": report.total_rows,
                "has_truncation": report.has_truncation,
                "captured_nothing": report.captured_nothing,
                "files": [
                    {
                        "path": str(file.path),
                        "status": file.status.value,
                        "rows": file.rows,
                        "batches": file.batches,
                        "size_bytes": file.size_bytes,
                        "readable_bytes": file.readable_bytes,
                        "lost_bytes": file.lost_bytes,
                        "schema_readable": file.schema_readable,
                        "ended_mid_message": file.ended_mid_message,
                        "end_of_stream_marker": file.end_of_stream_marker,
                        "mtime_ns": file.mtime_ns,
                        "failure": file.failure,
                    }
                    for file in report.files
                ],
            }
            for report in reports
        ],
    }


def _exit_code(reports: Sequence[PreflightReport]) -> int:
    if any(report.has_truncation for report in reports):
        return EXIT_TRUNCATED
    if any(report.captured_nothing for report in reports):
        return EXIT_NOTHING_CAPTURED
    return EXIT_OK


def run(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    now_ns: int | None = None,
) -> int:
    """Scan, report, and return the process exit code. Never raises."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    active_env: Mapping[str, str] = env if env is not None else {}
    parser = _build_parser()

    try:
        namespace = parser.parse_args(list(argv) if argv is not None else [])
    except SystemExit:
        return EXIT_USAGE

    try:
        root = _resolve_catalog(namespace, active_env)
        subdirectory = namespace.subdirectory
        instance_ids = _select_instances(namespace, root, subdirectory)
        if namespace.list:
            for name in instance_ids:
                print(name, file=out)
            return EXIT_OK
        reports = [
            scan_instance(root, instance_id, subdirectory) for instance_id in instance_ids
        ]
    except PreflightError as exc:
        print(f"{PROGRAM}: {exc}", file=err)
        return EXIT_USAGE

    exit_code = _exit_code(reports)

    if namespace.json:
        print(json.dumps(_as_json(reports, exit_code), indent=2), file=out)
        return exit_code

    now = time.time_ns() if now_ns is None else now_ns
    print(f"{PROGRAM}: catalog={root} subdirectory={subdirectory}", file=out)
    _render(reports, out, now, quiet=namespace.quiet)

    if exit_code == EXIT_TRUNCATED:
        truncated = sum(len(report.truncated) for report in reports)
        unreadable = sum(len(report.unreadable) for report in reports)
        verdict = (
            f"TRUNCATION DETECTED: {truncated} truncated and {unreadable} unreadable "
            f"file(s). The native read path would report ZERO rows for these and "
            f"raise NOTHING. Do NOT read this tape as a quiet market."
        )
        _announce(verdict, out, err)
        active = sum(
            1
            for report in reports
            for file in report.truncated
            if _recently_written(file, now)
        )
        if active:
            # A live writer's tail is byte-identical to a cut one. Say so at
            # the verdict, not only per file: on a real capture the per-file
            # notes scroll past and the last line is what gets read.
            caveat = (
                f"{active} of {truncated} truncated file(s) were written within the "
                f"last {WRITER_ACTIVITY_GRACE_NS // 1_000_000_000}s -- the recorder "
                f"is probably STILL RUNNING and these are mid-flush, not lost. "
                f"Re-run after it exits before concluding anything."
            )
            _announce(caveat, out, err)
    elif exit_code == EXIT_NOTHING_CAPTURED:
        _announce("no truncation, but 0 rows captured.", out, err)

    return exit_code


def main() -> int:
    """Console-script entrypoint. Returns the process exit code."""
    return run(sys.argv[1:], env=os.environ)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests
    # `python -m breezy.runtime.quote_tape_preflight_cli` works on a checkout
    # that has not been reinstalled since this entrypoint was added. That
    # matters operationally: the console script only appears after a package
    # reinstall, and reinstalling while a capture is running is exactly the
    # kind of avoidable risk this tool exists to reduce.
    raise SystemExit(main())
