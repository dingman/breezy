"""AUT-1 WP5 stage 3: the audit entry point ``_main`` (S3-R13, S3-R18, S3-R41, S3-R47).

Split from ``test_capture_audit.py`` (S3-R55) with its tests unchanged. The legs are stubbed; the
studies lock and the heal duty are injected or stubbed by ``capture_audit_main_support``.
"""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit as audit
from breezy.analysis import capture_audit_cli as cli
from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis.capture_audit_model import AUDIT_WORK_BUDGET_S
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_audit_main_support import (
    no_lock as _no_lock,
)
from tests.support.capture_audit_main_support import (
    no_real_heal as _no_real_heal,  # noqa: F401 - an autouse fixture, collected by name
)
from tests.support.capture_audit_run_support import (
    Offers,
)
from tests.support.capture_audit_run_support import (
    fake_gather as _fake_gather,
)
from tests.support.capture_audit_run_support import (
    quiet_duties as _quiet_duties,
)
from tests.support.capture_audit_w3_fixtures import stub_legs


def _cli_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    stub_legs(monkeypatch)
    _fake_gather(monkeypatch)
    return root


_THREE: tuple[str, ...] = ("--family-id", "fam_a", "--family-id", "fam_b", "--family-id", "fam_c")


def test_every_family_sees_one_absolute_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTATION M-REARM: ``DEADLINE.set(MONOTONIC() + 840)`` per family. The clock advances on
    every read, so a per-family re-arm would give each family a different instant."""
    root = _cli_world(tmp_path, monkeypatch)
    _quiet_duties(monkeypatch)
    ticks = iter(range(1000, 100_000))
    monkeypatch.setattr(inputs, "MONOTONIC", lambda: float(next(ticks)))
    seen: list[float | None] = []
    real: Any = vars(audit)["gather_inputs"]

    def spying(*a: Any, **k: Any) -> Any:
        seen.append(inputs.DEADLINE.get())
        return real(*a, **k)

    monkeypatch.setattr(audit, "gather_inputs", spying)
    argv = ["--data-root", str(root), *_THREE]
    cli._main(argv, offer=Offers(), clock=lambda: w3.NOW_NS, lock=_no_lock)
    assert len(seen) >= 3 and None not in seen
    assert len(set(seen)) == 1
    assert inputs.DEADLINE.get() is None  # the CLI releases it


def test_n_families_one_settlement_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MUTATION M-ONCE: the settlement duty once per family (N sends of one alert)."""
    root = _cli_world(tmp_path, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(audit, "_check_settlements", lambda *a, **k: calls.append("settle"))
    monkeypatch.setattr(audit, "_check_stuck", lambda *a, **k: calls.append("stuck"))
    monkeypatch.setattr(audit, "_check_live_proof", lambda *a, **k: calls.append("proof"))
    argv = ["--data-root", str(root), *_THREE]
    assert cli._main(argv, offer=Offers(), clock=lambda: w3.NOW_NS, lock=_no_lock) == 0
    assert calls.count("settle") == 1
    assert calls.count("stuck") == 3 and calls.count("proof") == 3  # per-family duties stay


def test_the_once_per_run_duty_failure_and_failed_delivery_fold_into_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _cli_world(tmp_path, monkeypatch)
    monkeypatch.setattr(audit, "_check_stuck", lambda *a, **k: None)
    monkeypatch.setattr(audit, "_check_live_proof", lambda *a, **k: None)
    argv = ["--data-root", str(root), "--family-id", "fam_a"]

    def raising(*a: Any, **k: Any) -> None:
        raise RuntimeError("settlement read failed")

    monkeypatch.setattr(audit, "_check_settlements", raising)
    assert cli._main(argv, offer=Offers(), clock=lambda: w3.NOW_NS, lock=_no_lock) == 1

    def sending(data_root: Path, today: dt.date, now_ns: int, delivery: Any) -> None:
        delivery.send("CAPTURE_SETTLEMENT_MISSING", "station=LAX climate_day=2026-10-01")

    monkeypatch.setattr(audit, "_check_settlements", sending)
    offers = Offers(accept=False)
    assert cli._main(argv, offer=offers, clock=lambda: w3.NOW_NS, lock=_no_lock) == 1
    assert offers.events.count("CAPTURE_SETTLEMENT_MISSING") == 1
    assert cli._main(argv, offer=Offers(), clock=lambda: w3.NOW_NS, lock=_no_lock) == 0


def test_a_once_per_run_duty_that_reaches_the_deadline_is_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _cli_world(tmp_path, monkeypatch)
    ran: list[str] = []
    monkeypatch.setattr(audit, "_check_stuck", lambda *a, **k: None)
    monkeypatch.setattr(audit, "_check_live_proof", lambda *a, **k: None)
    monkeypatch.setattr(audit, "_check_settlements", lambda *a, **k: ran.append("settle"))
    clock = iter([1000.0])  # arms DEADLINE at 1840; every later read is far past it
    monkeypatch.setattr(inputs, "MONOTONIC", lambda: next(clock, 10_000.0))
    monkeypatch.setattr(cli, "run_audit", lambda *a, **k: 0)
    argv = ["--data-root", str(root), "--family-id", "fam_a"]
    assert cli._main(argv, offer=Offers(), clock=lambda: w3.NOW_NS, lock=_no_lock) == 1
    assert ran == []


def test_the_budget_is_the_unit_timeout_less_the_lock_wait_and_a_margin() -> None:
    assert AUDIT_WORK_BUDGET_S == 1500 - 600 - 60 == 840
