"""AUT-1 WP5 stage 2b W3: the ``breezy-capture-audit`` entry point (S2-R8).

Split out of ``test_capture_audit.py`` (S2-R43); the helpers are in
``tests/support/capture_audit_run_support.py``.
"""

import datetime as dt
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit as audit
from breezy.analysis import capture_audit_cli as cli
from breezy.analysis import capture_audit_host as host
from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis import capture_heal_io as heal_io
from breezy.analysis.capture_audit_model import (
    AuditInputError,
    DayStatus,
)
from breezy.analysis.capture_node_log import scan_node_log
from breezy.persistence.autonomy.capture_epoch import write_epoch_once
from breezy.runtime.autonomy_sandbox.studies_lock import StudiesLockTimeout, acquire_studies_lock
from tests.support import capture_audit_fixtures as fx
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_audit_run_support import (
    Offers,
)
from tests.support.capture_audit_run_support import (
    fake_gather as _fake_gather,
)
from tests.support.capture_audit_run_support import (
    quiet_duties as _quiet_duties,
)
from tests.support.capture_audit_w3_fixtures import leg_result, stub_legs

DAY = fx.DAY
NS = w3.NS
TODAY = DAY + dt.timedelta(days=1)


@pytest.fixture(autouse=True)
def heal_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The heal duty reads the real recorder journal, so every test here stubs it (a no-op that
    records its call). The 3c tests replace it, or restore the real duty over a fake journal."""
    calls: list[dict[str, Any]] = []

    def quiet(data_root: Path, **kw: Any) -> int:
        calls.append({"data_root": data_root, **kw})
        return 0

    monkeypatch.setattr(cli, "run_heal_duty", quiet)
    return calls


# -- the entry point (S2-R8) -------------------------------------------------------------------


def _argv(root: Path, *extra: str) -> list[str]:
    return ["--data-root", str(root), *extra]


def _clock(hour: int, minute: int = 0) -> Any:
    return lambda: w3.day_ns(TODAY, hour, minute)


class FakeLock:
    """The injected studies lock (S3-R13): a unit test never takes the real host lock.

    Calling it records ``"lock"`` in ``events``, may advance the fake clocks (a long wait) and
    either returns a real close-on-exec fd (on ``/dev/null``) or raises ``error``.
    """

    def __init__(
        self,
        *,
        events: list[str] | None = None,
        error: Exception | None = None,
        on_acquire: Callable[[], None] | None = None,
    ) -> None:
        self.events = events if events is not None else []
        self.error, self.on_acquire = error, on_acquire
        self.fds: list[int] = []

    def __call__(self) -> int:
        self.events.append("lock")
        if self.error is not None:
            raise self.error
        if self.on_acquire is not None:
            self.on_acquire()
        fd = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
        self.fds.append(fd)
        return fd

    @property
    def calls(self) -> int:
        return self.events.count("lock")

    def fd_closed(self) -> bool:
        try:
            os.fstat(self.fds[0])
        except OSError:
            return True
        return False


class Mono:
    """A fake monotonic clock (``inputs.MONOTONIC``)."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _main(
    argv: list[str],
    *,
    offer: Any,
    clock: Callable[[], int],
    lock: Callable[[], int] | None = None,
) -> int:
    return cli._main(argv, offer=offer, clock=clock, lock=lock if lock is not None else FakeLock())


def test_bus_snapshot_read_before_any_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MUTATION: bus snapshot read after the scan. The wrapper's snapshot goes stale, so ``main``
    reads it before anything else, including the first log scan."""
    root = w3.full_world(tmp_path, monkeypatch)
    events: list[str] = []
    real_consume = host._consume_snapshot
    real_scan = scan_node_log

    def consume(data_root: Path, now_ns: int) -> Any:
        events.append("bus")
        return real_consume(data_root, now_ns)

    def scan(path: Path, **kw: Any) -> Any:
        events.append("scan")
        return real_scan(path, **kw)

    monkeypatch.setattr(host, "_consume_snapshot", consume)
    monkeypatch.setattr(inputs, "scan_node_log", scan)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    w3.FakeMarkers.planted = {}
    code = _main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS)
    assert events[0] == "bus" and events.count("bus") == 1  # read once, cached for every day
    assert "scan" in events and events.index("bus") < events.index("scan")
    assert code in (0, 1)


def test_a_stale_bus_snapshot_is_each_days_error_and_masked_before_the_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root, snapshot=False)
    w3.plant_snapshot(root, ts_ns=w3.NOW_NS - 3600 * NS)  # an hour old: aged out
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    w3.write_epoch(root, epoch_ns=w3.day_ns(DAY - dt.timedelta(days=3)))  # three days before D
    code = _main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS)
    statuses = audit._audited_statuses(root, w3.FAMILY)
    assert code == 1
    assert statuses[DAY] is DayStatus.ERROR
    assert {s for d, s in statuses.items() if d < DAY - dt.timedelta(days=3)} <= {
        DayStatus.PRE_CAPTURE
    }


def test_the_cli_defers_inside_the_launch_window_but_still_reads_the_snapshot_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    ran: list[int] = []
    monkeypatch.setattr(cli, "run_audit", w3.recording(ran))
    lock = FakeLock()
    code = _main(
        _argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=_clock(16, 40), lock=lock
    )
    assert code == 0 and ran == [] and lock.calls == 0  # a deferral never takes the lock
    assert not (
        root / w3.SNAP_BIND / ".bus_snapshot" / f"{w3.INVOCATION}.json"
    ).exists()  # consumed


@pytest.mark.parametrize(
    ("hour", "minute", "runs"), [(13, 50, 1), (16, 29, 0), (17, 10, 1), (16, 30, 0)]
)
def test_cli_defers_inside_launch_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hour: int, minute: int, runs: int
) -> None:
    """The worst case is ``flock -w 600`` plus ``TimeoutStartSec=1500`` from the start instant."""
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    calls: list[int] = []
    monkeypatch.setattr(cli, "run_audit", w3.recording(calls))
    _main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=_clock(hour, minute))
    assert len(calls) == runs


def test_the_cli_window_constants_are_the_plan_unit_numbers() -> None:
    assert (cli.FLOCK_WAIT_S, cli.TIMEOUT_START_S) == (600, 1500)


def test_the_default_offer_returns_false_so_an_alert_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    stub_legs(monkeypatch, R1=leg_result("R1", "FAIL", "capture_missing"))
    _quiet_duties(monkeypatch)
    _fake_gather(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["x"])
    monkeypatch.setattr(time, "time_ns", lambda: w3.NOW_NS)
    monkeypatch.setattr(cli, "_default_lock", FakeLock())  # never the real host lock
    assert cli._undeliverable_offer("CAPTURE_JOIN_GAP", "CRITICAL", "day=x") is False
    code = cli.main(_argv(root, "--family-id", w3.FAMILY))
    assert code == 1
    assert "CAPTURE_JOIN_GAP" in capsys.readouterr().err


def test_families_are_enumerated_by_construction_from_epoch_files_and_explicit_ids(
    tmp_path: Path,
) -> None:
    root = w3.make_root(tmp_path)
    for family in ("pm_us_a", "pm_us_b"):
        write_epoch_once(root, family_id=family, node_boot_id="b", build_sha="0" * 40, now_ns=1)
    assert cli.families_by_construction(root, ["pm_us_c", "pm_us_a"]) == (
        "pm_us_a",
        "pm_us_b",
        "pm_us_c",
    )
    assert cli.families_by_construction(w3.make_root(tmp_path / "empty"), []) == ()


def test_unknown_family_fill_is_enumerated_by_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A family that only has an epoch file is audited without being named."""
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    write_epoch_once(root, family_id="orphan_fam", node_boot_id="b", build_sha="0" * 40, now_ns=1)
    seen: list[str] = []

    def run_for(root_: Path, family: str, *a: Any, **k: Any) -> int:
        seen.append(family)
        return 0

    monkeypatch.setattr(cli, "run_audit", run_for)
    _main(_argv(root), offer=Offers(), clock=lambda: w3.NOW_NS)
    assert seen == ["orphan_fam"]


def test_a_malformed_family_id_is_refused_by_the_parser(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _main(_argv(tmp_path, "--family-id", "../x"), offer=Offers(), clock=lambda: w3.NOW_NS)


def test_no_family_means_nothing_to_audit_and_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    assert _main(_argv(root), offer=Offers(), clock=lambda: w3.NOW_NS) == 0


# -- the in-process studies lock, the fresh clock and the single deadline (S3-R13..R14, S3-R26) ----


def _recording_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[tuple[str, int, float | None]]]:
    """A root with one family; ``run_audit`` is a recorder of (family, now_ns, DEADLINE)."""
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    seen: list[tuple[str, int, float | None]] = []

    def run_for(root_: Path, family: str, today: dt.date, *, now_ns: int, **k: Any) -> int:
        seen.append((family, now_ns, inputs.DEADLINE.get()))
        return 0

    monkeypatch.setattr(cli, "run_audit", run_for)
    _quiet_duties(monkeypatch)
    return root, seen


def test_snapshot_consumed_before_studies_lock_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTATION M-ORDER: the lock before the snapshot ages the wrapper's snapshot by the wait."""
    root, _ = _recording_world(tmp_path, monkeypatch)
    events: list[str] = []
    real_consume = host._consume_snapshot

    def consume(data_root: Path, now_ns: int) -> Any:
        events.append("snapshot")
        return real_consume(data_root, now_ns)

    monkeypatch.setattr(host, "_consume_snapshot", consume)
    lock = FakeLock(events=events)
    _main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS, lock=lock)
    assert events[:2] == ["snapshot", "lock"]
    assert events.count("snapshot") == 1 and lock.calls == 1


def test_lock_wait_600s_does_not_stale_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshot window is ``budget + 60`` s; a full 600 s lock wait would age it out."""
    root, _ = _recording_world(tmp_path, monkeypatch)
    wall = {"now": w3.NOW_NS}
    lock = FakeLock(on_acquire=lambda: wall.update(now=wall["now"] + 600 * NS))
    code = _main(
        _argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: wall["now"], lock=lock
    )
    outcome = host._BUS_OUTCOMES[root]
    assert not isinstance(outcome, Exception), outcome
    assert code == 0 and lock.calls == 1


def test_lock_timeout_exits_one_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """MUTATION M-EXIT0: a timeout that exits 0 would never page (``OnFailure=``)."""
    root, seen = _recording_world(tmp_path, monkeypatch)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    lock = FakeLock(error=StudiesLockTimeout())
    code = _main(
        _argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS, lock=lock
    )
    assert code == 1 and seen == [] and lock.fds == []
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert [n for n in after if n not in before] == []  # no write of any kind
    assert StudiesLockTimeout.code in capsys.readouterr().err


def test_missing_lock_exits_one_never_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, seen = _recording_world(tmp_path, monkeypatch)
    absent = tmp_path / "run-user" / "breezy-studies.lock"
    absent.parent.mkdir()

    def real_helper() -> int:
        return acquire_studies_lock(absent, wait_s=0, poll_s=0.1)

    code = _main(
        _argv(root, "--family-id", w3.FAMILY),
        offer=Offers(),
        clock=lambda: w3.NOW_NS,
        lock=real_helper,
    )
    assert code == 1 and seen == []
    assert not absent.exists() and list(absent.parent.iterdir()) == []


def test_clock_reread_after_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MUTATION M-STALECLOCK: keeping the pre-lock clock hands heal, the audit file and ``today``
    an instant up to 600 s old. Here the wait crosses midnight."""
    root, seen = _recording_world(tmp_path, monkeypatch)
    before, after = w3.day_ns(TODAY, 23, 55), w3.day_ns(TODAY + dt.timedelta(days=1), 0, 5)
    taken = {"yes": False}
    days: list[dt.date] = []

    def run_for(root_: Path, family: str, today: dt.date, *, now_ns: int, **k: Any) -> int:
        seen.append((family, now_ns, None))
        days.append(today)
        return 0

    monkeypatch.setattr(cli, "run_audit", run_for)
    lock = FakeLock(on_acquire=lambda: taken.update(yes=True))
    _main(
        _argv(root, "--family-id", w3.FAMILY),
        offer=Offers(),
        clock=lambda: after if taken["yes"] else before,
        lock=lock,
    )
    assert [now for _, now, _ in seen] == [after]
    assert days == [TODAY + dt.timedelta(days=1)]


def _advance(mono: Mono, seconds: float) -> Callable[[], None]:
    def advance() -> None:
        mono.now += seconds

    return advance


def test_one_deadline_is_the_min_of_the_work_budget_and_the_exec_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTATION M-840: ignoring the unit's ``timeout -k 5 1470`` lets a long lock wait overrun it.

    ``DEADLINE = min(lock_acquired + 840, exec_start + 1470 - 60)`` (S3-R41, S3-R48)."""
    mono = Mono(100.0)
    monkeypatch.setattr(inputs, "MONOTONIC", mono)
    for wait, expected in ((0, 940.0), (500, 1440.0), (570, 1510.0), (600, 1510.0)):
        root, seen = _recording_world(tmp_path / f"w{wait}", monkeypatch)
        monkeypatch.setattr(inputs, "MONOTONIC", mono)
        mono.now = 100.0
        lock = FakeLock(on_acquire=_advance(mono, wait))
        _main(
            _argv(root, "--family-id", w3.FAMILY),
            offer=Offers(),
            clock=lambda: w3.NOW_NS,
            lock=lock,
        )
        assert [deadline for *_, deadline in seen] == [expected], wait
        assert expected <= 100.0 + 1410  # at most exec_start + 1410, 60 s inside the 1470 timeout


def test_the_deadline_is_reset_and_the_lock_released_after_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _recording_world(tmp_path, monkeypatch)
    lock = FakeLock()
    _main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS, lock=lock)
    assert inputs.DEADLINE.get() is None and lock.fd_closed()


def test_the_lock_is_released_when_the_run_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _recording_world(tmp_path, monkeypatch)

    def boom(*a: Any, **k: Any) -> int:
        raise RuntimeError("run failed")

    monkeypatch.setattr(cli, "run_audit", boom)
    lock = FakeLock()
    with pytest.raises(RuntimeError):
        _main(
            _argv(root, "--family-id", w3.FAMILY),
            offer=Offers(),
            clock=lambda: w3.NOW_NS,
            lock=lock,
        )
    assert lock.fd_closed() and inputs.DEADLINE.get() is None


def test_zero_families_still_take_the_lock_and_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    lock = FakeLock()
    assert _main(_argv(root), offer=Offers(), clock=lambda: w3.NOW_NS, lock=lock) == 0
    assert lock.calls == 1 and lock.fd_closed()


# -- heal wiring (S3-R18, S3-R25, S3-R41, S3-R46, S3-R47) -----------------------------------------

_QUIET_JOURNAL = (
    '{"MESSAGE":"x","__REALTIME_TIMESTAMP":"1"}\n'  # one entry, no UNIT_RESULT: no kill
)


def _real_heal(monkeypatch: pytest.MonkeyPatch, journal: Any = None) -> list[tuple[str, str]]:
    """Restore the real heal duty over a fake journal (never ``journalctl``). Returns the reads."""
    reads: list[tuple[str, str]] = []

    def fake_journal(_template: object, since: str, until: str, **_kw: object) -> str:
        reads.append((since, until))
        if journal is not None:
            raise journal
        return _QUIET_JOURNAL

    monkeypatch.setattr(cli, "run_heal_duty", heal_io.run_heal_duty)
    monkeypatch.setattr(heal_io, "run_journal", fake_journal)
    monkeypatch.setattr(heal_io, "delivered_events", lambda *_a: frozenset())
    return reads


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_heal_runs_before_family_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, heal_calls: list[dict[str, Any]]
) -> None:
    """MUTATION M-HEALLAST: heal after the family loop starves behind a long family run (K8)."""
    root, _ = _recording_world(tmp_path, monkeypatch)
    events: list[str] = []

    def heal(data_root: Path, **kw: Any) -> int:
        events.append("heal")
        heal_calls.append(kw)
        return 0

    def family(root_: Path, fam: str, today: dt.date, **kw: Any) -> int:
        events.append(f"family:{fam}")
        return 0

    monkeypatch.setattr(cli, "run_heal_duty", heal)
    monkeypatch.setattr(cli, "run_audit", family)
    argv = _argv(root, "--family-id", "fam_a", "--family-id", "fam_b")
    code = _main(argv, offer=Offers(), clock=lambda: w3.NOW_NS)
    assert code == 0 and events == ["heal", "family:fam_a", "family:fam_b"]
    assert [c["now_ns"] for c in heal_calls] == [w3.NOW_NS]


def test_heal_budget_is_the_min_of_its_own_budget_and_the_run_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, heal_calls: list[dict[str, Any]]
) -> None:
    """``heal_deadline = min(MONOTONIC() + HEAL_BUDGET_S, DEADLINE)`` (S3-R25, S3-R41)."""
    mono = Mono(100.0)
    for work_budget, expected in ((840, 280.0), (100, 200.0)):  # DEADLINE 940 / 200
        root, _ = _recording_world(tmp_path / f"b{work_budget}", monkeypatch)
        monkeypatch.setattr(inputs, "MONOTONIC", mono)
        monkeypatch.setattr(cli, "AUDIT_WORK_BUDGET_S", work_budget)
        heal_calls.clear()
        _main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS)
        assert [c["heal_deadline"] for c in heal_calls] == [expected], work_budget


def test_heal_runs_with_zero_families(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MUTATION M-ZEROFAM: with no family the run still heals, and writes nothing without a stall
    record. It exits 0 only because the lock and the journal were readable (S3-R46)."""
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    reads = _real_heal(monkeypatch)
    before = _files(root)
    lock = FakeLock()
    assert _main(_argv(root), offer=Offers(), clock=lambda: w3.NOW_NS, lock=lock) == 0
    assert len(reads) == 3 and lock.calls == 1  # HEAL_JOURNAL_DAYS reads
    assert [n for n in _files(root) if n not in before] == []  # no heal write, no other write


def test_zero_families_with_an_unreadable_journal_exit_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    _real_heal(monkeypatch, journal=AuditInputError("journal_failed", "TimeoutExpired"))
    assert _main(_argv(root), offer=Offers(), clock=lambda: w3.NOW_NS) == 1


def test_heal_overrun_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """MUTATION M-SILENT: a heal that runs past its deadline is a duty FAILURE, never a quiet 0.

    The work budget is zero, so ``DEADLINE`` has passed when heal starts; the families still run."""
    root, seen = _recording_world(tmp_path, monkeypatch)
    reads = _real_heal(monkeypatch)
    monkeypatch.setattr(cli, "AUDIT_WORK_BUDGET_S", 0)
    monkeypatch.setattr(cli, "run_once_duties", lambda *a, **k: 0)  # isolate the heal outcome
    code = _main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS)
    assert code == 1 and reads == [] and len(seen) == 1


def test_a_failing_heal_duty_is_folded_into_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, seen = _recording_world(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "run_heal_duty", lambda *a, **k: 1)
    code = _main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS)
    assert code == 1 and len(seen) == 1  # the family audit still ran


def test_a_heal_duty_that_raises_is_a_failure_and_the_families_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, seen = _recording_world(tmp_path, monkeypatch)

    def boom(*a: Any, **k: Any) -> int:
        raise RuntimeError("heal bug")

    monkeypatch.setattr(cli, "run_heal_duty", boom)
    code = _main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS)
    assert code == 1 and len(seen) == 1 and inputs.DEADLINE.get() is None


def test_heal_never_runs_when_the_lock_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, heal_calls: list[dict[str, Any]]
) -> None:
    root, _ = _recording_world(tmp_path, monkeypatch)
    lock = FakeLock(error=StudiesLockTimeout())
    assert _main(_argv(root), offer=Offers(), clock=lambda: w3.NOW_NS, lock=lock) == 1
    assert heal_calls == []


def test_the_heal_sender_puts_severity_and_attempt_kind_through_the_offer() -> None:
    """The stage-4 shim: ``attempt_kind`` rides in ``detail`` until AUT-6's outbox takes it."""
    offers = Offers()
    sender = cli.OfferHealSender(offers)
    assert sender.send("CAPTURE_HEALED_" + "ab" * 32, "heal=x", "retry") is True
    assert sender.send("CAPTURE_WATCHDOG_EVIDENCE_GAP", "gap=y", "alert") is True
    assert offers.calls == [
        ("CAPTURE_HEALED_" + "ab" * 32, "INFO", "heal=x attempt_kind=retry"),
        ("CAPTURE_WATCHDOG_EVIDENCE_GAP", "CRITICAL", "gap=y attempt_kind=alert"),
    ]
    assert cli.OfferHealSender(Offers(accept=False)).send("CAPTURE_JOIN_GAP", "d", "alert") is False


def test_the_cli_imports_no_venue_adapter_and_makes_no_network_call() -> None:
    code = (
        "import sys\n"
        "import breezy.analysis.capture_audit_cli\n"
        "bad = sorted(m for m in sys.modules if m.startswith('breezy.adapters')"
        " or m in ('httpx', 'requests', 'aiohttp', 'urllib3'))\n"
        "print(bad)\n"
        "raise SystemExit(1 if bad else 0)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(audit.__file__).parents[2])}
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_audit_modules_are_judged_non_vacuous_by_the_closure_lint() -> None:
    from tests.support.capture_closure_lint import AUT1_WRITE_AUTHORITY

    rows = {row.module: row for row in AUT1_WRITE_AUTHORITY}
    for name in (
        "capture_audit",
        "capture_audit_inputs",
        "capture_audit_cache",
        "capture_audit_host",
    ):
        assert rows[f"breezy.analysis.{name}"].min_calls >= 70
    assert len(rows["breezy.analysis.capture_audit_host"].argvs) == 3
