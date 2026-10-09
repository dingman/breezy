"""Builders for the AUT-6 meta-detector tests (WP3 S5): deploy dirs, show blocks, snapshots, wiring.

A synthetic ``deploy/systemd`` keeps the logic tests exact; the table-coverage tests read the real
one. The clock is the unit health fixtures' 2026-10-08T12:00:00Z.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from breezy.runtime.autonomy_sandbox.bus_handoff import BusSnapshot
from breezy.runtime.monitor_watch import WatchWiring, evaluate_watch
from breezy.runtime.monitor_watch_model import DetectorResult, WatchResult
from breezy.runtime.unit_health_obs import UnitObservation, parse_observation
from breezy.runtime.unit_health_store import MemAvailWindow
from tests.support.unit_health_daemon_fixtures import systemd_ts
from tests.support.unit_health_fixtures import NOW_NS, NS, make_snapshot, show_block

REPO_DEPLOY: Final = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
DAY_NS: Final = 86_400 * NS
TIMER_A: Final = "breezy-a.timer"
TIMER_M: Final = "breezy-m.timer"
TIMER_R: Final = "breezy-r.timer"
TEMPLATE: Final = "breezy-t@.timer"
RULING: Final = "RULING_X_test"
SYNTH_TABLE: Final[Mapping[str, tuple[int, int]]] = {
    TIMER_A: (86_400, 60),
    TIMER_M: (3_600, 1),
    TEMPLATE: (86_400, 60),
}
GOOD_WINDOW: Final = MemAvailWindow(40_000_000, 40_000_000, 144, None)
ALL_WINDOW: Final = GOOD_WINDOW


def write_deploy(root: Path, files: Mapping[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def synth_deploy(root: Path, extra: Mapping[str, str] | None = None) -> Path:
    """Timers a (daily, calendar), m (hourly, monotonic), r (retired) and a template t@."""
    files = {
        TIMER_A: "[Timer]\nOnCalendar=*-*-* 04:00:00 UTC\nAccuracySec=1min\n",
        "breezy-a.service": "[Service]\nExecStart=/bin/true\nMemoryMax=64M\n",
        TIMER_M: "[Timer]\nOnBootSec=5min\nOnUnitActiveSec=1h\nAccuracySec=1s\n",
        "breezy-m.service": "[Service]\nExecStart=/bin/true\nMemoryMax=64M\n",
        TIMER_R: (
            f"# RETIRED 2026-09-24 per docs/evidence/{RULING}.md\n"
            "[Timer]\nOnCalendar=*-*-* 03:00:00 UTC\n"
        ),
        "breezy-r.service": "[Service]\nExecStart=/bin/true\nMemoryMax=64M\n",
        TEMPLATE: "[Timer]\nOnCalendar=*-*-* 17:20:00 UTC\nAccuracySec=1min\n",
        "breezy-t@.service": "[Service]\nExecStart=/bin/true\nMemoryMax=64M\n",
    }
    files.update(extra or {})
    return write_deploy(root, files)


def timer_block(
    name: str,
    *,
    enabled: str = "enabled",
    active: str = "active",
    last_s: float | None = -3600,
    next_s: float | None = 3600,
    monotonic_next: str = "0",
    entered_s: float = -10 * 86_400,
    **extra: str,
) -> str:
    props: dict[str, str] = {
        "Id": name,
        "LoadState": "loaded",
        "ActiveState": active,
        "SubState": "waiting",
        "UnitFileState": enabled,
        "ActiveEnterTimestamp": systemd_ts(entered_s),
        "LastTriggerUSec": systemd_ts(last_s) if last_s is not None else "",
        "NextElapseUSecRealtime": systemd_ts(next_s) if next_s is not None else "",
        "NextElapseUSecMonotonic": monotonic_next,
    }
    props.update(extra)
    return "\n".join(f"{k}={v}" for k, v in props.items()) + "\n"


def unit_files_text(entries: Mapping[str, str]) -> str:
    return "".join(f"{name:<44} {state:<9} enabled\n" for name, state in entries.items())


def installed(deploy: Path, *, skip: Iterable[str] = (), instances: Iterable[str] = ()) -> str:
    """``list-unit-files`` for every deploy file (minus ``skip``) plus enabled ``instances``."""
    skipped = set(skip)
    entries = {
        p.name: ("enabled" if p.name.endswith(".timer") else "static")
        for p in sorted(deploy.iterdir())
        if p.is_file() and p.suffix in {".service", ".timer"} and p.name not in skipped
    }
    entries.update({name: "enabled" for name in instances})
    return unit_files_text(entries)


def snapshot(
    *,
    blocks: Sequence[str] = (),
    unit_files: str = "",
    loaded: str = "",
    now_ns: int = NOW_NS,
) -> BusSnapshot:
    base = make_snapshot(now_ns=now_ns, units=list(blocks), inventory=loaded)
    reads = tuple(
        dataclasses.replace(r, stdout=unit_files) if r.name == "unit_files_inventory" else r
        for r in base.reads
    )
    return dataclasses.replace(base, reads=reads)


def observe(snap: BusSnapshot, now_ns: int = NOW_NS) -> UnitObservation:
    return parse_observation(snap, now_ns)


def healthy_timer_blocks(names: Iterable[str]) -> list[str]:
    return [timer_block(n, last_s=-60, next_s=300) for n in names]


def wiring(tmp_path: Path, deploy: Path, **overrides: Any) -> WatchWiring:
    base: dict[str, Any] = {
        "data_root": tmp_path / "data",
        "deploy_dir": deploy,
        "table": SYNTH_TABLE,
        "instance_intervals": {},
        "retired": {TIMER_R: RULING},
        "rows": {},
        "artifacts": {},
        "producer": None,
        "summary": lambda since_ns, timeout_s: [],
        "node_log_tail": lambda: "",
        "rss_kib": lambda unit: 0,
    }
    base.update(overrides)
    return WatchWiring(**base)


def run_watch(
    w: WatchWiring,
    snap: BusSnapshot,
    *,
    now_ns: int = NOW_NS,
    window: MemAvailWindow = GOOD_WINDOW,
) -> WatchResult:
    return evaluate_watch(
        w,
        observe(snap, now_ns),
        now_ns=now_ns,
        window=window,
        summary_since_ns=now_ns - 600 * NS,
        summary_timeout_s=5.0,
    )


def kinds(result: DetectorResult) -> set[str]:
    return {f.kind for f in result.findings}


def subjects(result: DetectorResult, kind: str) -> set[str]:
    return {f.subject for f in result.findings if f.kind == kind}


def later(days: int) -> int:
    return NOW_NS + days * DAY_NS


def block_for(unit: str, **props: str) -> str:
    return show_block(unit, **props)


Reader = Callable[[], BusSnapshot]
