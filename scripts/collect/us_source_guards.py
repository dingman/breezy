"""F13-C1 S4: the collector's guards (deadline, disk, clock, alerts.env).

Everything here is small and stdlib-plus-``breezy.persistence.autonomy.capture_schedule``.
Nothing is imported from ``breezy.runtime``: ``alerts.env`` is read as a FILE by the local
reader below, because ``--clearenv`` strips ``EnvironmentFile`` (R31, R34).
"""

from __future__ import annotations

import enum
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy.capture_schedule import (
    launch_window_guard,
    seconds_outside_launch_window,
)

__all__ = [
    "ALERT_SINK_KEY",
    "ATTEMPT_BUDGET_S",
    "CHRONYC_PATH",
    "MAX_WORK_SECONDS",
    "STALE_AFTER_NS",
    "DiskGuardRefusedError",
    "FiringDecision",
    "NtpOffsetExceededError",
    "alerts_env_key_names",
    "attempt_allowed",
    "check_disk",
    "check_ntp_offset",
    "disk_free_bytes",
    "firing_decision",
    "measure_ntp_offset_ns",
    "parse_chronyc_tracking",
    "read_alerts_env",
    "resolve_webhook_url",
    "worked_seconds_outside_window",
]

_NS: Final[int] = 1_000_000_000
_HOUR_NS: Final[int] = 3600 * _NS

#: The one key ``alerts.env`` may hold (verified by test; values are never printed).
ALERT_SINK_KEY: Final[str] = "BREEZY_ALERT_WEBHOOK_URL"

#: Worst-case seconds one poll attempt can take (connect 5 + read 60 + a retry margin).
ATTEMPT_BUDGET_S: Final[int] = 90

#: In-process work budget per source, in seconds. ``RuntimeMaxSec`` is a backstop and must
#: exceed these (checked by test) while never reaching 16:30Z.
MAX_WORK_SECONDS: Final[Mapping[str, int]] = {
    "lamp": 20 * 60,
    "pfm": 10 * 60,
    "nbp": 115 * 60,
    "lav": 8 * 60,
    "mos": 8 * 60,
    "obs": 4 * 60,
}

#: A source is stale when its newest observed run is older than this. Provisional until the
#: OPEN-5 numerics are frozen after B0/A0.
STALE_AFTER_NS: Final[Mapping[str, int]] = {
    "lamp": 3 * _HOUR_NS,
    "pfm": 36 * _HOUR_NS,
    "nbp": 8 * _HOUR_NS,
    "lav": 4 * _HOUR_NS,
    "mos": 14 * _HOUR_NS,
    "obs": 6 * _HOUR_NS,
}

CHRONYC_PATH: Final[str] = "/usr/bin/chronyc"
_CHRONY_TIMEOUT_S: Final[float] = 5.0
_CHRONY_SYSTEM_TIME = re.compile(
    r"^System time\s*:\s*(?P<seconds>\d+\.\d+) seconds (?P<direction>fast|slow) of NTP time\s*$",
    re.MULTILINE,
)


class FiringDecision(enum.StrEnum):
    RUN = "run"
    SKIP_WINDOW = "skip_window"


class DiskGuardRefusedError(RuntimeError):
    """Free space is below the hard floor; nothing may be written."""


class NtpOffsetExceededError(RuntimeError):
    """The system clock is off by more than the pre-registered bound."""


# -- the in-process 16:30Z deadline (R11) ------------------------------------------------


def firing_decision(now_ns: int) -> FiringDecision:
    """A firing STARTING inside [16:30Z, 17:10Z) is skipped (the 17:10Z firing reruns it).

    A zero-span run: 16:29:59 runs, 16:30:00 and 17:09:59 skip, 17:10:00 runs.
    """
    return FiringDecision.RUN if launch_window_guard(now_ns, 0, 0) else FiringDecision.SKIP_WINDOW


def attempt_allowed(now_ns: int, budget_s: int = ATTEMPT_BUDGET_S) -> bool:
    """May ONE poll attempt start now? Its worst case must not meet the launch window."""
    return launch_window_guard(now_ns, 0, budget_s)


def worked_seconds_outside_window(start_ns: int, now_ns: int) -> int:
    """Whole seconds worked since ``start_ns`` that fall outside the launch window."""
    return seconds_outside_launch_window(start_ns, now_ns)


# -- disk guard ---------------------------------------------------------------------------


def disk_free_bytes(root: Path) -> int:
    return shutil.disk_usage(root).free


def check_disk(
    root: Path,
    *,
    min_free_bytes: int,
    free_bytes: Callable[[Path], int] = disk_free_bytes,
) -> int:
    """Hard refusal below ``min_free_bytes``; returns the free bytes otherwise."""
    free = free_bytes(root)
    if free < min_free_bytes:
        raise DiskGuardRefusedError(f"{free} bytes free is below the {min_free_bytes} byte floor")
    return free


# -- clock offset -------------------------------------------------------------------------


def parse_chronyc_tracking(text: str) -> int:
    """Signed offset in ns from ``chronyc tracking``; positive means the clock is FAST."""
    match = _CHRONY_SYSTEM_TIME.search(text)
    if match is None:
        raise ValueError("no `System time` line in the chronyc tracking output")
    whole, _, fraction = match["seconds"].partition(".")
    nanoseconds = int(whole) * _NS + int(fraction.ljust(9, "0")[:9])
    return nanoseconds if match["direction"] == "fast" else -nanoseconds


def measure_ntp_offset_ns(
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int | None:
    """The clock offset, or None when it cannot be measured (recorded as null, never guessed)."""
    try:
        done = run(
            [CHRONYC_PATH, "tracking"],
            capture_output=True,
            text=True,
            timeout=_CHRONY_TIMEOUT_S,
            check=False,
        )
        if done.returncode != 0:
            return None
        return parse_chronyc_tracking(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def check_ntp_offset(offset_ns: int | None, *, bound_ns: int) -> None:
    """Refuse an offset beyond ``bound_ns`` in either direction; None is not a refusal."""
    if offset_ns is not None and abs(offset_ns) > bound_ns:
        raise NtpOffsetExceededError(f"clock offset {offset_ns} ns exceeds the {bound_ns} ns bound")


# -- alerts.env, read as a FILE ------------------------------------------------------------

_ENV_LINE = re.compile(
    r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?)\s*$"
)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_alerts_env(path: Path) -> dict[str, str]:
    """``KEY=VALUE`` lines of ``path``; a missing file is an empty mapping."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if match is not None:
            values[match["key"]] = _unquote(match["value"])
    return values


def alerts_env_key_names(path: Path) -> tuple[str, ...]:
    """The key NAMES in file order: the only thing a verifier may print."""
    return tuple(read_alerts_env(path))


def resolve_webhook_url(path: Path) -> str | None:
    """The alert sink URL from the file, or None. No network call is made here."""
    return read_alerts_env(path).get(ALERT_SINK_KEY) or None
