"""AUT-6 WP3 S4: the unit-scoped journal reader and the module guards."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from breezy.runtime import unit_health
from breezy.runtime.unit_health_daemon_support import (
    MSG_EXIT,
    MSG_STARTED,
    MSG_STOPPING,
    SubprocessDaemonJournal,
    UnitEntry,
)
from breezy.runtime.unit_health_journal import JournalError, Run, RunResult
from tests.support.unit_health_daemon_fixtures import (
    INTRADAY,
    QUOTE_TAPE,
    at_us,
    exited,
)
from tests.support.unit_health_daemon_world import (
    World,
)
from tests.support.unit_health_fixtures import (
    inv,
)


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path)


# --------------------------------------------------------------------------- journal reader


class RecordingRun:
    def __init__(self, stdout: str = "", rc: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.result = RunResult(rc, stdout, False, False)

    def __call__(self, argv: Sequence[str], timeout_s: float) -> RunResult:
        self.calls.append(list(argv))
        return self.result


def _json_line(entry: UnitEntry) -> str:
    return json.dumps(
        {
            "MESSAGE_ID": entry.message_id,
            "USER_UNIT": entry.unit,
            "USER_INVOCATION_ID": entry.invocation_id,
            "__REALTIME_TIMESTAMP": str(entry.ts_us),
            "MESSAGE": entry.message,
            **entry.fields,
        }
    )


def test_daemon_journal_lifecycle_query_is_an_argv_list_with_the_three_message_ids() -> None:
    run = RecordingRun()
    SubprocessDaemonJournal(run).unit_entries(
        QUOTE_TAPE, since_us=1_000_000, until_us=9_000_000, lifecycle_only=True, timeout_s=5
    )
    argv = run.calls[0]
    assert argv[:2] == ["/usr/bin/journalctl", "--user"]
    assert f"USER_UNIT={QUOTE_TAPE}" in argv
    assert {f"MESSAGE_ID={m}" for m in (MSG_STARTED, MSG_EXIT, MSG_STOPPING)} <= set(argv)
    assert "--since=@1" in argv and "--until=@9" in argv
    assert "+" not in argv  # systemd's own entries only: no stdout lines of a chatty daemon


def test_daemon_journal_stage_query_joins_systemd_and_stdout_entries_with_or() -> None:
    run = RecordingRun()
    SubprocessDaemonJournal(run).invocation_entries(
        INTRADAY, inv(7), lifecycle_only=False, timeout_s=5
    )
    argv = run.calls[0]
    plus = argv.index("+")
    assert f"USER_INVOCATION_ID={inv(7)}" in argv[:plus]
    assert f"_SYSTEMD_INVOCATION_ID={inv(7)}" in argv[plus:]
    assert f"_SYSTEMD_USER_UNIT={INTRADAY}" in argv[plus:]


def test_daemon_journal_parses_entries_and_normalises_stdout_ids() -> None:
    systemd = _json_line(exited(QUOTE_TAPE, inv(1), 5, "3"))
    stdout = json.dumps(
        {
            "MESSAGE": "PRODUCER_INTRADAY START ts_ns=1",
            "_SYSTEMD_USER_UNIT": INTRADAY,
            "_SYSTEMD_INVOCATION_ID": inv(2),
            "__REALTIME_TIMESTAMP": str(at_us(1)),
        }
    )
    run = RecordingRun(systemd + "\n" + stdout + "\n")
    got = SubprocessDaemonJournal(run).invocation_entries(
        INTRADAY, inv(2), lifecycle_only=False, timeout_s=5
    )
    assert [(e.unit, e.invocation_id, e.message_id) for e in got] == [
        (QUOTE_TAPE, inv(1), MSG_EXIT),
        (INTRADAY, inv(2), ""),
    ]
    assert got[0].fields["EXIT_STATUS"] == "3" and got[1].message.startswith("PRODUCER_INTRADAY")


@pytest.mark.parametrize("bad", ["not json", "[1]", json.dumps({"MESSAGE": "x"})])
def test_daemon_journal_unparseable_line_is_a_journal_error(bad: str) -> None:
    run = RecordingRun(bad + "\n")
    with pytest.raises(JournalError):
        SubprocessDaemonJournal(run).unit_entries(
            QUOTE_TAPE, since_us=0, until_us=10**9, lifecycle_only=True, timeout_s=5
        )


def _fixed_run(result: RunResult) -> Run:
    def run(argv: Sequence[str], timeout_s: float) -> RunResult:
        return result

    return run


def test_daemon_journal_errors_are_never_empty_results() -> None:
    for result in (RunResult(1, "", False, False), RunResult(-9, "", True, False)):
        j = SubprocessDaemonJournal(_fixed_run(result))
        with pytest.raises(JournalError):
            j.unit_entries(QUOTE_TAPE, since_us=0, until_us=10**9, lifecycle_only=True, timeout_s=5)
    with pytest.raises(JournalError):
        SubprocessDaemonJournal(RecordingRun()).invocation_entries(
            QUOTE_TAPE, "not-an-id", lifecycle_only=True, timeout_s=5
        )


# --------------------------------------------------------------------------- misc guards


def test_daemons_module_does_not_read_the_permit_or_orders_switch() -> None:
    src = Path(unit_health.__file__).resolve().parent
    for name in ("unit_health_daemons.py", "unit_health_intraday.py"):
        text = (src / name).read_text(encoding="utf-8")
        for needle in ("BREEZY_ORDERS_ENABLED", "permit", "live_orders_gate"):
            assert needle not in text, (name, needle)
