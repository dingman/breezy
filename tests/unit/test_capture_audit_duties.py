"""AUT-1 WP5 stage 2b W3: the duties moved from the retired watchdog (plan r12 section 3.11.5).

Split out of ``test_capture_audit.py`` (S2-R43); the helpers are in
``tests/support/capture_audit_run_support.py``.
"""

import dataclasses
import datetime as dt
import os
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit as audit
from breezy.analysis.capture_audit_input_types import (
    ExecFill,
    ExecView,
)
from breezy.analysis.capture_audit_model import (
    DayStatus,
)
from breezy.analysis.capture_settlement import SettlementRecord
from tests.support import capture_audit_fixtures as fx
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_audit_run_support import (
    Offers,
)
from tests.support.capture_audit_run_support import (
    fake_gather as _fake_gather,
)
from tests.support.capture_audit_run_support import (
    run as _run,
)
from tests.support.capture_audit_w3_fixtures import stub_legs

DAY = fx.DAY
NS = w3.NS
TODAY = DAY + dt.timedelta(days=1)


# -- the moved duties (section 3.11.5) ---------------------------------------------------------


def _decisions(root: Path) -> Path:
    path = root / "catalog" / "quote_tape" / "decisions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settle(root: Path, station: str, day: dt.date) -> None:
    record = SettlementRecord(station, day.isoformat(), 84, "NWS_CLI", "ab" * 32, 1)
    path = _decisions(root) / f"settlement_{day.isoformat()}.jsonl"
    path.write_text(record.to_line())
    path.chmod(0o600)  # the writer's own mode; a group- or world-writable file is refused


def _fill_for(station_day: dt.date, instrument_station: str = "lax") -> ExecFill:
    slug = f"tc-temp-{instrument_station}high-{station_day.isoformat()}-gte93lt94f.POLYMARKET_US"
    return dataclasses.replace(fx.make_exec_view().fills[0], instrument_id=slug)


def _delivery() -> audit._Delivery:
    return audit._Delivery(Offers())


def _duty_offers(offer: Offers) -> audit._Delivery:
    return audit._Delivery(offer)


def test_audit_alerts_settlement_missing_after_48h(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    old = TODAY - dt.timedelta(days=4)
    fresh = TODAY - dt.timedelta(days=1)
    monkeypatch.setattr(
        audit, "read_exec_view", lambda r: ExecView(fills=(_fill_for(old), _fill_for(fresh)))
    )
    offers = Offers()
    audit._check_settlements(root, TODAY, w3.NOW_NS, _duty_offers(offers))
    assert offers.calls == [
        ("CAPTURE_SETTLEMENT_MISSING", "CRITICAL", f"station=LAX climate_day={old}")
    ]


def test_a_settled_station_day_raises_no_settlement_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    old = TODAY - dt.timedelta(days=4)
    _settle(root, "LAX", old)
    monkeypatch.setattr(audit, "read_exec_view", lambda r: ExecView(fills=(_fill_for(old),)))
    offers = Offers()
    audit._check_settlements(root, TODAY, w3.NOW_NS, _duty_offers(offers))
    assert offers.calls == []


def test_settlement_alert_waits_exactly_48h_after_the_climate_day_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    day = TODAY - dt.timedelta(days=3)  # ends at TODAY-2 00:00; 48h later is TODAY 00:00
    monkeypatch.setattr(audit, "read_exec_view", lambda r: ExecView(fills=(_fill_for(day),)))
    boundary = w3.day_ns(TODAY)
    early, late = Offers(), Offers()
    audit._check_settlements(root, TODAY, boundary, _duty_offers(early))
    audit._check_settlements(root, TODAY, boundary + 1, _duty_offers(late))
    assert early.calls == [] and late.events == ["CAPTURE_SETTLEMENT_MISSING"]


def test_audit_alerts_stuck_inconclusive_after_8_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    for age, status in (
        (9, DayStatus.INCONCLUSIVE),
        (8, DayStatus.INCONCLUSIVE),
        (10, DayStatus.PASS),
    ):
        day = TODAY - dt.timedelta(days=age)
        result = dataclasses.replace(audit.audit_day(fx.make_inputs(day=day)), status=status)
        audit.write_audit_file(root, result, ts_ns=1)
    offers = Offers()
    audit._check_stuck(root, fx.FAMILY_ID, TODAY, _duty_offers(offers))
    assert offers.calls == [
        ("CAPTURE_AUDIT_STUCK_INCONCLUSIVE", "CRITICAL", f"day={TODAY - dt.timedelta(days=9)}")
    ]


def _proof(root: Path, family: str, asof: dt.date, *, age_h: float) -> None:
    directory = root / "evidence" / "capture" / "live_proof"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"live_proof_{family}_{asof.isoformat()}.json"
    path.write_text("{}")
    stamp = w3.NOW_NS - int(age_h * 3600 * NS)
    os.utime(path, ns=(stamp, stamp))


@pytest.mark.parametrize(("age_h", "alerts"), [(25.9, 0), (26.0, 0), (26.1, 1), (72.0, 1)])
def test_audit_alerts_live_proof_stale(tmp_path: Path, age_h: float, alerts: int) -> None:
    root = w3.make_root(tmp_path)
    _proof(root, fx.FAMILY_ID, DAY, age_h=age_h)
    _proof(root, "other_family", DAY, age_h=1.0)  # another family's roll-up never rescues this one
    offers = Offers()
    audit._check_live_proof(root, fx.FAMILY_ID, w3.NOW_NS, _duty_offers(offers))
    assert len(offers.calls) == alerts


def test_a_missing_live_proof_is_stale(tmp_path: Path) -> None:
    offers = Offers()
    audit._check_live_proof(w3.make_root(tmp_path), fx.FAMILY_ID, w3.NOW_NS, _duty_offers(offers))
    assert offers.events == ["CAPTURE_LIVE_PROOF_STALE"]


def test_each_moved_check_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MUTATION: a moved check that is not isolated. A raising check must not stop the others."""
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _fake_gather(monkeypatch)
    ran: list[str] = []

    def broken(*a: Any, **k: Any) -> None:
        ran.append("settlement")
        raise OSError("snapshot")

    monkeypatch.setattr(audit, "_check_settlements", broken)
    monkeypatch.setattr(audit, "_check_stuck", lambda *a, **k: ran.append("stuck"))
    monkeypatch.setattr(audit, "_check_live_proof", lambda *a, **k: ran.append("live_proof"))
    assert _run(root, Offers()) == 1  # a failed duty fails the run, loudly, after all of them ran
    assert ran == ["settlement", "stuck", "live_proof"]


@pytest.mark.parametrize("breaker", ["_check_settlements", "_check_stuck", "_check_live_proof"])
def test_each_duty_failure_leaves_the_other_two_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, breaker: str
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _fake_gather(monkeypatch)
    ran: set[str] = set()
    for name in ("_check_settlements", "_check_stuck", "_check_live_proof"):

        def duty(*a: Any, _n: str = name, **k: Any) -> None:
            ran.add(_n)
            if _n == breaker:
                raise RuntimeError("boom")

        monkeypatch.setattr(audit, name, duty)
    _run(root, Offers())
    assert ran == {"_check_settlements", "_check_stuck", "_check_live_proof"}
