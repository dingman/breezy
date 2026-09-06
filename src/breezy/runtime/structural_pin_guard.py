"""Pure structural-pin gate for the PREREG v2 family-tally wrapper.

READY iff the node-env pre-flight token is exactly ``MATCH`` and UTC wall
time is at or after :data:`LAUNCH_UTC`. Pre-launch MATCH is PRE_LAUNCH, not
READY. Kalshi is NOT_APPLICABLE. No I/O and no default HOME path (L-27).

``Persistent=true`` boot catch-up before launch exits 1 with no report --
accepted. AC #1 is MATCH at 17:15Z; the wrapper already requires the 14:15
marker (and, after this gate, the same-day counter JSON) before it can
write a binding report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Final, Literal

from breezy.runtime.trade_supervisor_core import LAUNCH_UTC

__all__ = [
    "PM_FAMILY_ID",
    "REQUIRED_TOKEN",
    "evaluate_pin_gate",
    "main",
]

REQUIRED_TOKEN: Final[str] = "MATCH"
PM_FAMILY_ID: Final[str] = "pm_us_crh_v2"

PinGateResult = Literal["READY", "PRE_LAUNCH", "UNAVAILABLE", "NOT_APPLICABLE"]

EXIT_OK: Final[int] = 0
EXIT_NOT_READY: Final[int] = 1
EXIT_USAGE: Final[int] = 2


def evaluate_pin_gate(family_id: str, check_token: str, now: dt.time) -> PinGateResult:
    """Return the pin-gate label for ``family_id`` / ``check_token`` / ``now``.

    ``now`` is a UTC wall ``dt.time``, never a datetime (A2/A10). MATCH is
    compared with ``==``, never a set (L-12 / F2).
    """
    if family_id != PM_FAMILY_ID:
        return "NOT_APPLICABLE"
    if now < LAUNCH_UTC:
        return "PRE_LAUNCH"
    if check_token == REQUIRED_TOKEN:
        return "READY"
    return "UNAVAILABLE"


def _parse_now(raw: str) -> dt.time:
    parts = raw.split(":")
    if len(parts) == 2:
        parts.append("0")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"invalid --now {raw!r}; expected HH:MM or HH:MM:SS")
    try:
        hour, minute, second = (int(part) for part in parts)
        return dt.time(hour, minute, second)
    except ValueError as exc:
        raise ValueError(f"invalid --now {raw!r}; expected HH:MM or HH:MM:SS") from exc


def main(argv: list[str] | None = None) -> int:
    """``python -m breezy.runtime.structural_pin_guard`` entrypoint.

    Exit 0 READY/NOT_APPLICABLE; 1 PRE_LAUNCH/UNAVAILABLE (stderr names the
    label and the token); 2 usage. ``--now HH:MM[:SS]`` is a test hook;
    omitted, reads ``datetime.now(UTC).time()``.
    """
    parser = argparse.ArgumentParser(prog="structural-pin-guard", exit_on_error=False)
    parser.add_argument("--family", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--now", default=None, help="UTC wall time HH:MM[:SS] (test hook)")
    args_list = sys.argv[1:] if argv is None else argv
    try:
        parsed = parser.parse_args(args_list)
    except argparse.ArgumentError as exc:
        print(
            "structural-pin-guard: usage: --family ID --token TOKEN "
            f"[--now HH:MM[:SS]] ({exc})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    except SystemExit as exc:
        code = exc.code
        if code in (None, 0):
            return EXIT_OK
        return EXIT_USAGE

    if parsed.now is None:
        now = dt.datetime.now(dt.UTC).time()
    else:
        try:
            now = _parse_now(parsed.now)
        except ValueError as exc:
            print(f"structural-pin-guard: usage: {exc}", file=sys.stderr)
            return EXIT_USAGE

    result = evaluate_pin_gate(parsed.family, parsed.token, now)
    if result in ("READY", "NOT_APPLICABLE"):
        print(result)
        return EXIT_OK
    print(
        f"structural-pin-guard: {result} token={parsed.token!r} "
        f"(required {REQUIRED_TOKEN})",
        file=sys.stderr,
    )
    return EXIT_NOT_READY


if __name__ == "__main__":
    raise SystemExit(main())
