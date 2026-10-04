"""AUT-1 WP5 stage 3 S1: the recorder heal planner and the heal duty (design r3 D6, section 4 S1).

A watchdog kill is healed only by the FIRST later invocation (matched by the ``TradingNode:
instance_id:`` journal line, never by a time window) that has a ``live/<id>/config.json``, after
30 minutes, with 15 minutes of non-dot growth and no second kill within 30 minutes of the restart.
"""

import ast
import datetime as dt
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis import capture_heal_io as heal_io
from breezy.analysis.capture_audit_input_types import RecorderJournalEntry
from breezy.analysis.capture_audit_model import AuditInputError
from breezy.analysis.capture_heal import (
    HEAL_JOURNAL_DAYS,
    HealPlan,
    InstanceEvidence,
    InstanceLine,
    heal_body,
    instance_lines,
    plan_heals,
)

NS = 1_000_000_000
NOW = int(dt.datetime(2026, 10, 4, 14, 0, tzinfo=dt.UTC).timestamp()) * NS
KILL_NS = NOW - 3 * 3600 * NS
RESTART_NS = KILL_NS + 120 * NS
INV_KILLED = "a" * 32
INV_NEXT = "b" * 32
INV_LATER = "c" * 32
SHA = "9" * 64
IID = "11111111-aaaa-bbbb-cccc-000000000001"
IID2 = "22222222-aaaa-bbbb-cccc-000000000002"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "capture_heal"
_DATE = "2026-10-04"


def _date(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns // NS, dt.UTC).date().isoformat()


def _line(ts_ns: int, inv_key: str, inv: str, message: Any, **extra: Any) -> str:
    entry = {"__REALTIME_TIMESTAMP": str(ts_ns // 1000), inv_key: inv, "MESSAGE": message, **extra}
    return json.dumps(entry)


def kill_line(ts_ns: int, inv: str) -> str:
    return _line(
        ts_ns,
        "USER_INVOCATION_ID",
        inv,
        "x: Failed with result 'watchdog'.",
        UNIT_RESULT="watchdog",
    )


def instance_line(ts_ns: int, inv: str, iid: str, *, ansi: bool = True) -> str:
    text = f"2026-10-04T11:02:00.000000000Z [INFO] BREEZY-L001.TradingNode: instance_id: {iid}"
    if ansi:
        text = f"\x1b[1m{text[:30]}\x1b[0m \x1b[94m{text[31:]}\x1b[0m"
    return _line(ts_ns, "_SYSTEMD_INVOCATION_ID", inv, list(text.encode()))


class Sender:
    def __init__(self, accept: bool = True) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.accept = accept

    def send(self, event: str, detail: str, attempt_kind: str) -> bool:
        self.calls.append((event, detail, attempt_kind))
        return self.accept

    def events(self, kind: str | None = None) -> list[str]:
        return [e for e, _d, k in self.calls if kind is None or k == kind]


class World:
    """A data root, a fake recorder journal and the live directories, all under ``tmp_path``."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = tmp_path / "data"
        self.root.mkdir(mode=0o700)
        self.entries: list[tuple[int, str]] = []
        self.reads: list[tuple[str, str]] = []
        self.delivered: frozenset[str] = frozenset()
        monkeypatch.setattr(heal_io, "run_journal", self._journal)
        monkeypatch.setattr(heal_io, "delivered_events", lambda *_a: self.delivered)
        monkeypatch.setattr(inputs, "MONOTONIC", lambda: 1000.0)

    def _journal(self, _template: object, since: str, until: str, **_kw: object) -> str:
        self.reads.append((since, until))
        low, high = (
            int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=dt.UTC).timestamp())
            * NS
            for s in (since, until)
        )
        lines = [text for ts, text in sorted(self.entries) if low <= ts < high]
        if not lines:
            raise AuditInputError("journal_failed", "empty_output")
        return "\n".join(lines) + "\n"

    def put(self, rel: str, body: Any, *, mtime_ns: int | None = None) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body if isinstance(body, str) else json.dumps(body))
        path.chmod(0o600)
        if mtime_ns is not None:
            os.utime(path, ns=(mtime_ns, mtime_ns))
        return path

    def kill(self, inv: str = INV_KILLED, ts_ns: int = KILL_NS, *, stall: bool = True) -> None:
        self.entries.append((ts_ns, kill_line(ts_ns, inv)))
        if stall:
            name = f"{ts_ns}_{inv}_recorder_watchdog.json"
            body = {"invocation_id": inv, "detected_ns": ts_ns, "observation_sha256": SHA}
            self.put(f"evidence/capture/stall/{_date(ts_ns)}/{name}", body)

    def restart(
        self,
        inv: str = INV_NEXT,
        iid: str = IID,
        ts_ns: int = RESTART_NS,
        *,
        growth_s: int | None = 1200,
        journal: bool = True,
    ) -> Path:
        if journal:
            self.entries.append((ts_ns, instance_line(ts_ns, inv, iid)))
        live = self.root / "catalog/quote_tape/polymarket_us/live" / iid
        live.mkdir(parents=True, exist_ok=True)
        config = live / "config.json"
        config.write_text("{}")
        os.utime(config, ns=(ts_ns, ts_ns))
        if growth_s is not None:
            feather = live / "quote_tick_0.feather"
            feather.write_bytes(b"x" * 10)
            os.utime(feather, ns=(ts_ns + growth_s * NS,) * 2)
        return live

    def run(self, sender: Sender, *, now_ns: int = NOW, deadline: float = 1100.0) -> int:
        return heal_io.run_heal_duty(
            self.root, now_ns=now_ns, heal_deadline=deadline, sender=sender
        )

    def heal_files(self) -> list[Path]:
        return sorted((self.root / "evidence/capture/heal").glob("*/*.json"))


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


# -- matching and confirmation ---------------------------------------------------------------


def test_watchdog_kill_followed_by_streaming_instance_is_healed(world: World) -> None:
    world.kill()
    world.restart()
    sender = Sender()

    failures = world.run(sender)

    (path,) = world.heal_files()
    assert (failures, path.name) == (0, f"{KILL_NS}_audit_breezy-quote-tape.json")
    assert path.parent.name == _date(KILL_NS) and path.stat().st_mode & 0o777 == 0o444
    body = json.loads(path.read_text())
    assert body["observation_sha256"] == SHA and body["invocation_id"] == INV_KILLED
    assert (body["unit_result"], body["decided_by"], body["injected"]) == (
        "watchdog",
        "systemd_watchdog",
        False,
    )
    assert body["instance_id"] == IID
    assert [c[0::2] for c in sender.calls] == [(f"CAPTURE_HEALED_{SHA}", "alert")]


def test_recorder_heal_matches_restart_by_instance_id_not_time_window(world: World) -> None:
    """MUTATION M-TIMEWIN: a directory that merely grew in the window is not the restart."""
    world.kill()
    world.restart(iid=IID)
    world.restart(inv="d" * 32, iid=IID2, ts_ns=RESTART_NS + 5 * NS, growth_s=5000, journal=False)
    sender = Sender()

    world.run(sender)

    (path,) = world.heal_files()
    assert json.loads(path.read_text())["instance_id"] == IID


def test_first_later_invocation_with_config_is_the_restart(world: World) -> None:
    """MUTATION M-LASTINV: the FIRST later invocation decides, not the last."""
    world.kill()
    world.restart(inv=INV_NEXT, iid=IID, growth_s=100)  # first: too little growth, so unconfirmed
    world.restart(inv=INV_LATER, iid=IID2, ts_ns=RESTART_NS + 600 * NS, growth_s=5000)
    sender = Sender()

    world.run(sender)

    assert world.heal_files() == [] and sender.calls == []


def test_a_later_invocation_without_config_is_skipped(world: World) -> None:
    world.kill()
    world.restart(inv=INV_NEXT, iid=IID, growth_s=None)
    (world.root / "catalog/quote_tape/polymarket_us/live" / IID / "config.json").unlink()
    world.restart(inv=INV_LATER, iid=IID2, ts_ns=RESTART_NS + 60 * NS, growth_s=3000)

    world.run(Sender())

    (path,) = world.heal_files()
    assert json.loads(path.read_text())["instance_id"] == IID2


def test_use_instance_id_config_line_is_not_an_instance(world: World) -> None:
    """MUTATION M-DECOY: the ``config.use_instance_id=False`` line is not an instance."""
    decoy = json.loads((FIXTURES / "recorder_instance_lines.json").read_text())["lines"][1]
    line = _line(RESTART_NS, "_SYSTEMD_INVOCATION_ID", INV_NEXT, list(decoy.encode()))
    assert instance_lines(line) == ()
    world.kill()
    world.entries.append((RESTART_NS, line))
    world.restart(journal=False)

    world.run(Sender())

    assert world.heal_files() == []


def test_ansi_byte_array_message_is_decoded() -> None:
    """MUTATION M-ANSI: the real line is a byte array with ANSI codes and a timestamp prefix."""
    real = json.loads((FIXTURES / "recorder_instance_lines.json").read_text())["lines"][0]
    text = _line(RESTART_NS, "_SYSTEMD_INVOCATION_ID", INV_NEXT, list(real.encode()))

    (found,) = instance_lines(text)

    assert found == InstanceLine(RESTART_NS, INV_NEXT, "b3336cb3-3a2e-46f9-a528-ee8064ba1c5c")


def _plan(
    now_ns: int,
    *,
    growth_s: float = 1200,
    kills: tuple[RecorderJournalEntry, ...] | None = None,
) -> tuple[HealPlan, ...]:
    first = RecorderJournalEntry(KILL_NS, INV_KILLED, "watchdog")
    line = InstanceLine(RESTART_NS, INV_NEXT, IID)
    evidence = {IID: InstanceEvidence(True, int(growth_s * NS))}
    return plan_heals(kills or (first,), (line,), {INV_KILLED: SHA}, evidence, now_ns)


def test_growth_899s_unconfirmed_900s_confirmed() -> None:
    """MUTATION M-GROW: 900 s of growth is enough, 899 s is not."""
    assert _plan(NOW, growth_s=899) == ()
    assert len(_plan(NOW, growth_s=900)) == 1


def test_restart_1799s_old_unconfirmed_1800s_confirmed() -> None:
    """MUTATION M-AGE: the restart must be 1800 s old on the post-lock clock."""
    assert _plan(RESTART_NS + 1799 * NS) == ()
    assert len(_plan(RESTART_NS + 1800 * NS)) == 1


def test_restart_younger_than_30min_is_unconfirmed() -> None:
    assert _plan(RESTART_NS + 600 * NS, growth_s=5000) == ()


def test_second_kill_within_1800s_is_not_healed() -> None:
    first = RecorderJournalEntry(KILL_NS, INV_KILLED, "watchdog")
    inside = RecorderJournalEntry(RESTART_NS + 1800 * NS, INV_NEXT, "watchdog")
    outside = RecorderJournalEntry(RESTART_NS + 1801 * NS, INV_NEXT, "watchdog")
    assert _plan(NOW, kills=(first, inside)) == ()
    assert [p.kill for p in _plan(NOW, kills=(first, outside))] == [first]


def test_a_timeout_result_is_not_a_watchdog_kill() -> None:
    other = RecorderJournalEntry(KILL_NS, INV_KILLED, "timeout")
    assert _plan(NOW, kills=(other,)) == ()


def _grow_only(world: World, *, dot: str | None = None, empty_feather: bool = False) -> None:
    live = world.restart(growth_s=100)
    late = RESTART_NS + 5000 * NS
    if dot:
        extra = live / dot
        if dot.endswith("/"):
            extra = live / dot.rstrip("/")
            extra.mkdir()
        else:
            extra.write_text("x")
        os.utime(extra, ns=(late, late))
    if empty_feather:
        feather = live / "quote_tick_9.feather"
        feather.write_bytes(b"")
        os.utime(feather, ns=(late, late))


@pytest.mark.parametrize(
    "marker", [".converted-2026-10-04", ".preflight-memo-v1.json", ".salvaged-abc", ".any"]
)
@pytest.mark.parametrize("shape", ["{}", "{}/", "{}.feather"])
def test_dot_entries_are_not_growth(world: World, marker: str, shape: str) -> None:
    """MUTATION M-CONV / M-DOT: markers the ingest drops into the directory, as a file, a
    directory or a ``.feather``, are not growth."""
    world.kill()
    _grow_only(world, dot=shape.format(marker))

    world.run(Sender())

    assert world.heal_files() == []


def test_zero_size_feather_is_not_growth(world: World) -> None:
    world.kill()
    _grow_only(world, empty_feather=True)

    world.run(Sender())

    assert world.heal_files() == []


def test_a_data_subdirectory_counts_as_growth(world: World) -> None:
    world.kill()
    live = world.restart(growth_s=100)
    sub = live / "quote_tick"
    sub.mkdir()
    os.utime(sub, ns=(RESTART_NS + 2000 * NS,) * 2)

    world.run(Sender())

    assert len(world.heal_files()) == 1


# -- records ---------------------------------------------------------------------------------


def test_heal_record_rerun_is_noop(world: World) -> None:
    world.kill()
    world.restart()
    first = Sender()
    world.run(first)
    (path,) = world.heal_files()
    before = path.read_bytes()
    again = Sender()

    failures = world.run(again)

    assert failures == 0 and path.read_bytes() == before
    assert again.events("alert") == [] and first.events("alert") == [f"CAPTURE_HEALED_{SHA}"]


def test_late_drill_file_never_exists_different(world: World) -> None:
    world.kill()
    world.restart()
    world.run(Sender())
    (path,) = world.heal_files()
    before = path.read_bytes()
    world.put(f"evidence/capture/drill/{_date(KILL_NS)}.json", {"injected": True})

    failures = world.run(Sender())

    assert failures == 0 and path.read_bytes() == before
    assert json.loads(before)["injected"] is False


def test_drill_present_at_first_write_marks_injected(world: World) -> None:
    """MUTATION M-INJ: ``injected`` is read once, at the first write."""
    world.kill()
    world.restart()
    world.put(f"evidence/capture/drill/{_date(KILL_NS)}.json", {"injected": True})

    world.run(Sender())

    (path,) = world.heal_files()
    assert json.loads(path.read_text())["injected"] is True


def test_an_existing_record_that_disagrees_with_the_journal_is_a_failure(world: World) -> None:
    world.kill()
    world.restart()
    rel = f"evidence/capture/heal/{_date(KILL_NS)}/{KILL_NS}_audit_breezy-quote-tape.json"
    world.put(rel, {"observation_sha256": "8" * 64, "invocation_id": INV_KILLED})

    assert world.run(Sender()) == 1


def test_kill_without_stall_record_writes_no_heal(world: World) -> None:
    """MUTATION M-NOSTALL: no stall sha, no heal: leg W carries the kill."""
    world.kill(stall=False)
    world.restart()
    sender = Sender()

    failures = world.run(sender)

    assert (failures, world.heal_files(), sender.calls) == (0, [], [])


def test_a_malformed_stall_record_is_a_failure_not_a_heal(world: World) -> None:
    world.kill(stall=False)
    world.put(
        f"evidence/capture/stall/{_date(KILL_NS)}/{KILL_NS}_{INV_KILLED}_recorder_watchdog.json",
        "{",
    )
    world.restart()

    assert world.run(Sender()) == 1 and world.heal_files() == []


def test_an_undelivered_heal_alert_is_a_failure(world: World) -> None:
    world.kill()
    world.restart()

    assert world.run(Sender(accept=False)) == 1
    assert len(world.heal_files()) == 1


# -- the journal, the budget and the isolation ----------------------------------------------


def test_journal_read_per_day_over_three_days(world: World) -> None:
    """MUTATION M-9D: one read per UTC day, oldest first, never one wide read."""
    world.kill()
    world.restart()

    world.run(Sender())

    days = [(since[:10], until[:10]) for since, until in world.reads]
    assert HEAL_JOURNAL_DAYS == 3 and days == [
        ("2026-10-02", "2026-10-03"),
        ("2026-10-03", "2026-10-04"),
        ("2026-10-04", "2026-10-05"),
    ]
    assert all(s.endswith("00:00:00 UTC") and u.endswith("00:00:00 UTC") for s, u in world.reads)


def test_a_journal_with_no_output_on_any_day_is_a_failure(world: World) -> None:
    assert world.run(Sender()) == 1


def test_a_failed_journal_read_is_a_failure(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: object, **_k: object) -> str:
        raise AuditInputError("journal_failed", "timeout")

    monkeypatch.setattr(heal_io, "run_journal", broken)

    assert world.run(Sender()) == 1


def test_overrunning_the_heal_deadline_is_a_failure(world: World) -> None:
    world.kill()
    world.restart()
    sender = Sender()

    failures = world.run(sender, deadline=1000.0)

    assert failures >= 1 and sender.calls == [] and world.heal_files() == []


def test_the_run_deadline_is_a_failure_too(world: World) -> None:
    world.kill()
    world.restart()
    token = inputs.DEADLINE.set(999.0)
    try:
        failures = world.run(Sender())
    finally:
        inputs.DEADLINE.reset(token)

    assert failures >= 1 and world.heal_files() == []


def test_nbp_heal_fixture_2608599c_parses(world: World) -> None:
    body = json.loads((FIXTURES / "nbp_heal_wp4_2608599c.json").read_text())
    healed_ns = body["healed_ns"]
    world.put(f"evidence/capture/heal/{_date(healed_ns)}/{healed_ns}_node_nbm.json", body)
    world.entries.append((healed_ns, _line(healed_ns, "_SYSTEMD_INVOCATION_ID", INV_NEXT, "ok")))
    sender = Sender()

    failures = world.run(sender, now_ns=healed_ns + 700 * NS)

    assert failures == 0
    assert sender.calls[0][0] == f"CAPTURE_HEALED_{body['observation_sha256']}"


def test_heal_io_never_imports_delivery_class() -> None:
    tree = ast.parse(Path(heal_io.__file__ or "").read_text(encoding="utf-8"))
    imported = {
        a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names
    } | {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "_Delivery" not in imported and "breezy.analysis.capture_audit" not in imported
    assert not hasattr(heal_io, "_Delivery")


def test_capture_heal_io_sys_modules_closure(tmp_path: Path) -> None:
    """S3-R37: the heal I/O closure holds no adapter and no HTTP client."""
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    src = str(Path(heal_io.__file__ or "").resolve().parents[2])
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {src!r})
        from pathlib import Path
        from breezy.analysis import capture_heal_io as h
        from breezy.analysis.capture_audit_model import AuditInputError

        def broken(*a, **k):
            raise AuditInputError("journal_failed", "timeout")

        class S:
            def send(self, e, d, k):
                return True

        h.run_journal = broken
        h.delivered_events = lambda *a: frozenset()
        inf = float("inf")
        assert h.run_heal_duty(Path({str(root)!r}), now_ns=1, heal_deadline=inf, sender=S()) == 1
        banned = {{"httpx", "requests", "aiohttp", "urllib3"}}
        bad = sorted(m for m in sys.modules
                     if m.split(".")[0] in banned or m.startswith("breezy.adapters"))
        assert not bad, bad
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_heal_body_is_the_pinned_shape() -> None:
    plan = HealPlan(
        RecorderJournalEntry(KILL_NS, INV_KILLED, "watchdog"),
        InstanceLine(RESTART_NS, INV_NEXT, IID),
        SHA,
    )
    assert sorted(heal_body(plan, injected=False)) == [
        "cause",
        "decided_by",
        "detected_ns",
        "healed_ns",
        "injected",
        "instance_id",
        "invocation_id",
        "observation_sha256",
        "unit",
        "unit_result",
    ]
