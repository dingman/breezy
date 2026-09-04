"""The recorder must be throttled by its own cgroup before the host OOM

killer chooses it arbitrarily among every process on the box.

Measured incident (2026-09-03 22:31 UTC, `tests/unit/
test_polymarket_us_connect_fail_fast.py:3-4`): the recorder was OOM-killed.
Before this change `breezy-quote-tape.service` set no `MemoryHigh=`/
`MemoryMax=` at all, so its cgroup had no memory accounting ceiling of its
own and the process competed on equal footing with everything else on a
31 GB host for the kernel's global OOM decision. Measured post-incident:
MemoryCurrent ~= 1.10 GB, MemoryPeak ~= 1.14 GB after 28 minutes uptime.

Deliberately text-only parsing, matching `test_deploy_timer_hours.py`'s
approach (no `systemd-analyze` shelling; that stays a manual step per
`deploy/systemd/README.md`).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UNIT_PATH = _REPO_ROOT / "deploy" / "systemd" / "breezy-quote-tape.service"

_MEMORY_DIRECTIVE_RE = re.compile(r"^(MemoryHigh|MemoryMax)=(\d+)([KMGT])$")


def _memory_directives() -> dict[str, int]:
    """Return each `MemoryHigh=`/`MemoryMax=` directive's value, in bytes."""
    unit = 1024
    scale = {"K": unit, "M": unit**2, "G": unit**3, "T": unit**4}
    values: dict[str, int] = {}
    for line in _UNIT_PATH.read_text().splitlines():
        match = _MEMORY_DIRECTIVE_RE.match(line.strip())
        if match is None:
            continue
        name, digits, suffix = match.groups()
        values[name] = int(digits) * scale[suffix]
    return values


def test_the_unit_declares_both_a_memory_high_and_a_memory_max() -> None:
    values = _memory_directives()
    assert "MemoryHigh" in values, (
        "MemoryHigh= is missing: the kernel gets no throttling signal "
        "before a hard kill, exactly the incident this test pins"
    )
    assert "MemoryMax" in values, "MemoryMax= is missing: no per-cgroup ceiling exists"


def test_memory_max_is_at_or_above_memory_high() -> None:
    values = _memory_directives()
    assert values["MemoryMax"] >= values["MemoryHigh"], (
        "MemoryMax must be >= MemoryHigh -- otherwise the hard ceiling fires "
        "before the soft throttle ever gets a chance to act"
    )


def test_memory_high_clears_measured_peak_with_headroom() -> None:
    # Measured MemoryPeak ~= 1.14 GB (28 min uptime). MemoryHigh must clear
    # that comfortably or ordinary operation will be throttled every day.
    measured_peak_bytes = int(1.14 * 1024**3)
    values = _memory_directives()
    assert values["MemoryHigh"] > measured_peak_bytes


def test_memory_max_stays_well_under_the_host_total_so_this_unit_is_never_the_hosts_choice() -> None:
    # Host has 31 GB total. MemoryMax must be small enough that this cgroup's
    # own kill (not the global OOM killer picking among every process) is
    # what fires -- and small enough that a leak here cannot starve the rest
    # of the host.
    host_total_bytes = 31 * 1024**3
    values = _memory_directives()
    assert values["MemoryMax"] < host_total_bytes // 4
