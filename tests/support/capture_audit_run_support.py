"""Shared helpers of the audit orchestration tests (split by S2-R43): the alert offer recorder, the
fake ``gather_inputs`` and the run and duty stubs. Test-only; imports no exec package module."""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit as audit
from tests.support import capture_audit_fixtures as fx
from tests.support import capture_audit_w3_fixtures as w3

DAY = fx.DAY
TODAY = DAY + dt.timedelta(days=1)


class Offers:
    def __init__(self, *, accept: bool = True, raises: bool = False) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.accept, self.raises = accept, raises

    def __call__(self, event: str, severity: str, detail: str) -> bool:
        self.calls.append((event, severity, detail))
        if self.raises:
            raise RuntimeError("outbox down")
        return self.accept

    @property
    def events(self) -> list[str]:
        return [c[0] for c in self.calls]


def fake_gather(monkeypatch: pytest.MonkeyPatch, **per_day: Any) -> list[dt.date]:
    """``gather_inputs`` is replaced by one that returns fixture inputs (or raises the given
    exception for a day). Returns the list of days it was asked for."""
    asked: list[dt.date] = []

    def gather(root: Path, family: str, day: dt.date, *, now_ns: int) -> Any:
        asked.append(day)
        planted = per_day.get(day.isoformat())
        if isinstance(planted, Exception):
            raise planted
        return fx.make_inputs(day=day, **(planted or {}))

    monkeypatch.setattr(audit, "gather_inputs", gather)
    monkeypatch.setattr(audit, "_pre_capture", lambda root, family, day: False)
    return asked


def run(root: Path, offer: Offers, *, today: dt.date = TODAY) -> int:
    return audit.run_audit(root, fx.FAMILY_ID, today, now_ns=w3.NOW_NS, offer=offer)


def quiet_duties(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("_check_settlements", "_check_stuck", "_check_live_proof"):
        monkeypatch.setattr(audit, name, lambda *a, **k: None)
