"""Builders for the AUT-6 unit health pass tests (WP3 S3): bus snapshots, journal lines, fakes.

The journal lines are shaped like the four results measured since 09-28 (exit-code from
``breezy-portfolio-roi``, signal from ``breezy-exit-window-study``, oom-kill from
``breezy-parity-fq``, timeout from ``breezy-discovery-pull``) with every id replaced. The deadman
fixture set is the one AUT-5's dead-man test consumes (plan section 3.11 item 1).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from breezy.runtime.autonomy_sandbox.bus_handoff import BusReadResult, BusSnapshot
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE

ROW: Final = AUTONOMY_BWRAP_TABLE["breezy-autonomy-health"]
NS: Final = 1_000_000_000
# 2026-10-08T12:00:00Z
NOW_NS: Final = 1_791_460_800 * NS
DAY: Final = "2026-10-08"
DAY_START_S: Final = 1_791_417_600
MESSAGE_ID_FAILED: Final = "d9b373ed55a64feb8242e02dbe79a49c"
REPO: Final = "/home/jon/breezy"


def inv(n: int) -> str:
    return f"{n:032x}"


def failure_line(
    unit: str, invocation: str, result: str, *, ts_us: int | None = None, seq: int = 1
) -> str:
    ts = ts_us if ts_us is not None else (NOW_NS // 1000) - 60_000_000 + seq
    return json.dumps(
        {
            "MESSAGE_ID": MESSAGE_ID_FAILED,
            "USER_UNIT": unit,
            "USER_INVOCATION_ID": invocation,
            "UNIT_RESULT": result,
            "__REALTIME_TIMESTAMP": str(ts),
            "__CURSOR": f"s=aa;i={seq:x};b=bb;m=1;t=2;x=3",
        }
    )


def show_block(unit: str, **props: str) -> str:
    base: dict[str, str] = {
        "Id": unit,
        "ActiveState": "inactive",
        "SubState": "dead",
        "Result": "success",
        "InvocationID": inv(0xAAA),
        "ExecMainStatus": "0",
        "MemoryPeak": "[not set]",
        "MemorySwapPeak": "[not set]",
        "MemoryHigh": "infinity",
        "Type": "oneshot",
        "Restart": "no",
        "LoadState": "loaded",
        "TimeoutStartUSec": "15min",
    }
    base.update(props)
    return "\n".join(f"{k}={v}" for k, v in base.items()) + "\n"


def show_text(*blocks: str) -> str:
    return "\n".join(blocks)


def failed_list(*units: str) -> str:
    return "".join(f"{u:<40} loaded failed failed Description of {u}\n" for u in units)


def make_snapshot(
    *,
    now_ns: int = NOW_NS,
    age_s: float = 5,
    units: Sequence[str] = (),
    failed: Sequence[str] = (),
    run_transient: Sequence[str] = (),
    bad: Mapping[str, Mapping[str, Any]] | None = None,
    inventory: str = "",
) -> BusSnapshot:
    texts = {
        "units_show": show_text(*units),
        "failed_list": failed_list(*failed),
        "units_inventory": inventory,
        "unit_files_inventory": "",
        "timers_list": "",
        "run_transient": show_text(*run_transient),
    }
    reads = []
    for read in ROW.bus_reads:
        flags: dict[str, Any] = {
            "rc": 0,
            "timed_out": False,
            "skipped": False,
            "oversize": False,
            "stdout": texts[read.name],
        }
        flags.update((bad or {}).get(read.name, {}))
        reads.append(BusReadResult(read.name, read.argv, **flags))
    return BusSnapshot(
        inv(0xFEED), "breezy-autonomy-health.service", now_ns - int(age_s * NS), 15, tuple(reads)
    )


@dataclass
class Trace:
    """One ordered event log shared by every fake of a test."""

    events: list[str] = field(default_factory=list)

    def add(self, event: str) -> None:
        self.events.append(event)


@dataclass
class FakeClock:
    now_ns: int = NOW_NS
    mono: float = 1000.0

    def wall(self) -> int:
        return self.now_ns

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.now_ns += int(seconds * NS)


class AlertRecorder:
    """The alert seam: records payloads; ``ok=False`` refuses (outbox overflow)."""

    def __init__(self, trace: Trace | None = None, *, ok: bool = True) -> None:
        self.payloads: list[Any] = []
        self.trace = trace
        self.ok = ok

    def __call__(self, payload: Any) -> bool:
        if self.trace is not None:
            self.trace.add("alert")
        self.payloads.append(payload)
        return self.ok

    @property
    def events(self) -> list[str]:
        return [p.event for p in self.payloads]


def heartbeat_fixtures(now_ns: int) -> dict[str, dict[str, Any]]:
    """Fresh, aged, and "fresh last_attempt_ns, aged ts_ns, streak 3" (plan section 3.11)."""
    base = {"schema": "health_heartbeat/v1", "invocation_id": inv(1), "passes_unknown_streak": 0}
    return {
        "fresh": {
            **base,
            "ts_ns": now_ns - 60 * NS,
            "last_attempt_ns": now_ns - 60 * NS,
            "pass_result": "OK",
        },
        "aged": {
            **base,
            "ts_ns": now_ns - 1900 * NS,
            "last_attempt_ns": now_ns - 1900 * NS,
            "pass_result": "OK",
        },
        "unknown_streak": {
            **base,
            "ts_ns": now_ns - 1900 * NS,
            "last_attempt_ns": now_ns - 60 * NS,
            "pass_result": "UNKNOWN",
            "passes_unknown_streak": 3,
        },
    }


Reader = Callable[[], BusSnapshot]
