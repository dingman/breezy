"""The pass loop shared by the AUT-6 WP3 S4 daemon and intraday tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from breezy.runtime.unit_health import PassResult
from breezy.runtime.unit_health_daemon_support import DaemonWiring
from breezy.runtime.unit_health_store import HealthStore
from tests.support.unit_health_daemon_fixtures import (
    QUOTE_TAPE,
    ROTATE,
    FakeDaemonJournal,
    systemd_ts,
)
from tests.support.unit_health_fixtures import (
    inv,
    make_snapshot,
    show_block,
)
from tests.unit.test_unit_health import Harness, harness

DAY_S = 86_400
NODE = "breezy-trade-supervisor.service"


# --------------------------------------------------------------------------- the world


class World:
    """One health pass loop over a mutable set of unit blocks and a fake journal."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.units: list[str] = []
        self.journal = FakeDaemonJournal()
        self.alerts_root = tmp_path / "alerts"
        self.h: Harness = harness(
            tmp_path,
            snapshot=self._snapshot,
            daemons=DaemonWiring(self.journal, alerts_root=self.alerts_root),
        )

    def _snapshot(self) -> Any:
        return make_snapshot(now_ns=self.h.clock.now_ns, units=self.units)

    @property
    def store(self) -> HealthStore:
        return self.h.store

    @property
    def events(self) -> list[str]:
        return self.h.alerts.events

    def run(self, advance_s: float = 600) -> PassResult:
        self.h.clock.advance(advance_s)
        return self.h.run()

    def deliver_all(self) -> None:
        for payload in self.h.alerts.payloads:
            self.h.delivered.add((payload.event, payload.site))

    def payloads(self, event: str) -> list[Any]:
        return [p for p in self.h.alerts.payloads if p.event == event]

    def records(self, event: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for path in sorted(self.store.root.glob("*/*__class.json")):
            body = json.loads(path.read_text())
            if body.get("kind") == "finding" and body.get("finding") == event:
                found.append(body)
        return found


def qt_block(
    n: int, *, restarts: int = 0, aet: float = -3600, unit: str = QUOTE_TAPE, **props: str
) -> str:
    return show_block(
        unit,
        Restart="always",
        Type="notify",
        ActiveState="active",
        SubState="running",
        InvocationID=inv(n),
        NRestarts=str(restarts),
        ActiveEnterTimestamp=systemd_ts(aet),
        **props,
    )


def rotate_block(start: float, result: str = "success") -> str:
    return show_block(ROTATE, ExecMainStartTimestamp=systemd_ts(start), Result=result)


def baseline(w: World, n: int = 1, *, restarts: int = 0, unit: str = QUOTE_TAPE) -> None:
    w.units = [qt_block(n, restarts=restarts, unit=unit)]
    result = w.run(0)
    assert result.pass_result in {"OK", "FINDINGS"}, result
    assert w.events == []
