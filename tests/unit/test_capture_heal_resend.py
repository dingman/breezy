"""AUT-1 WP5 stage 3 S1: heal and gap alert re-send, abandon and age-out (design r3 D7).

Heal records of the last 8 dates are re-sent daily (``attempt_kind="retry"``); the ones dated
8 to 30 days ago are abandoned (the marker only after a delivered proof); the unmarked older ones
are logged loud. The same rules govern the leg-W gaps recorded in the audit files.
"""

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_heal_io as heal_io
from breezy.analysis.capture_audit_model import AuditResult, DayStatus, WatchdogGap
from breezy.analysis.capture_audit_wire import audit_to_wire
from breezy.analysis.capture_heal import RECORDER_UNIT, gap_key
from breezy.persistence.autonomy.single_read import SingleReadReason, SingleReadRefused
from tests.unit.test_capture_heal import NOW, NS, Sender, World, _date, _line

DAY_NS = 86_400 * NS
INV = "e" * 32
SHA_A = "1" * 64
SHA_B = "2" * 64


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    built = World(tmp_path, monkeypatch)
    for back in range(3):  # a quiet recorder journal: the heal phase finds no kill
        ts = NOW - back * DAY_NS - 3600 * NS
        built.entries.append((ts, _line(ts, "_SYSTEMD_INVOCATION_ID", "f" * 32, "hello")))
    return built


def heal(
    world: World, days_ago: int, sha: str = SHA_A, *, who: str = "audit", ts_ns: int = 0
) -> str:
    ts = ts_ns or NOW - days_ago * DAY_NS
    name = f"{ts}_{who}_breezy-quote-tape.json" if who == "audit" else f"{ts}_{who}_nbm.json"
    world.put(f"evidence/capture/heal/{_date(ts)}/{name}", {"observation_sha256": sha})
    return f"CAPTURE_HEALED_{sha}"


def gap(world: World, days_ago: int, inv: str = INV, family: str = "fq") -> str:
    ts = NOW - days_ago * DAY_NS
    day = dt.datetime.fromtimestamp(ts // NS, dt.UTC).date()
    found = (WatchdogGap(RECORDER_UNIT, inv, ts, "no_stall_record"),)
    result = AuditResult(day, family, DayStatus.FAIL, "", (), (), watchdog_evidence_gaps=found)
    world.put(f"evidence/capture/audit/{family}/{day.isoformat()}.json", audit_to_wire(result))
    return gap_key(inv)


def marker_names(world: World) -> list[str]:
    return sorted(p.name for p in (world.root / "evidence/capture/heal_alert_abandoned").glob("*"))


# -- heal records ----------------------------------------------------------------------------


def test_heal_resend_daily_with_attempt_kind_retry(world: World) -> None:
    """MUTATION M-KIND: a re-send is ``retry``, never ``alert``."""
    event = heal(world, 2)
    sender = Sender()

    failures = world.run(sender)

    assert failures == 0 and sender.calls == [
        (event, f"heal={SHA_A} date={_date(NOW - 2 * DAY_NS)}", "retry")
    ]
    world.run(again := Sender())
    assert again.events("retry") == [event]  # daily, until delivered


def test_a_delivered_heal_is_not_resent(world: World) -> None:
    world.delivered = frozenset({heal(world, 2)})
    sender = Sender()

    world.run(sender)

    assert sender.calls == []


def test_node_record_younger_than_600s_not_resent(world: World) -> None:
    """MUTATION M-NODE600: the actor may still be delivering its own alert."""
    young = heal(world, 0, SHA_A, who="node", ts_ns=NOW - 599 * NS)
    old = heal(world, 0, SHA_B, who="node", ts_ns=NOW - 600 * NS)
    sender = Sender()

    world.run(sender)

    assert sender.events("retry") == [old] and young not in sender.events()


def test_an_audit_record_is_resent_at_once(world: World) -> None:
    event = heal(world, 0, ts_ns=NOW - 10 * NS)
    sender = Sender()

    world.run(sender)

    assert sender.events("retry") == [event]


def test_abandon_marker_only_after_delivered_true(world: World) -> None:
    """MUTATION M-EARLYMARK: the abandon alert is sent first; the marker waits for its proof."""
    heal(world, 10)
    abandon = f"CAPTURE_HEAL_ALERT_ABANDONED_{SHA_A}"
    sender = Sender()

    world.run(sender)

    assert sender.events() == [abandon] and marker_names(world) == []
    world.delivered = frozenset({abandon})
    world.run(proof := Sender())
    assert proof.calls == [] and marker_names(world) == [f"{SHA_A}.json"]
    world.delivered = frozenset()
    world.run(done := Sender())
    assert done.calls == []  # a marked heal is never sent again


def test_a_delivered_heal_in_the_abandon_window_is_marked_without_a_send(world: World) -> None:
    world.delivered = frozenset({heal(world, 12)})
    sender = Sender()

    world.run(sender)

    assert sender.calls == [] and marker_names(world) == [f"{SHA_A}.json"]


def test_a_failed_abandon_send_is_a_failure(world: World) -> None:
    heal(world, 10)

    assert world.run(Sender(accept=False)) == 1


def test_unmarked_heal_older_than_30d_counts_unabandoned(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    heal(world, 31)
    sender = Sender()

    with caplog.at_level("INFO"):
        failures = world.run(sender)

    assert failures == 0 and sender.calls == []
    assert f"CAPTURE_HEAL_UNABANDONED heal={SHA_A}" in caplog.text
    assert "heal_alert_unabandoned_count=1 gap_alert_unabandoned_count=0" in caplog.text


def test_ledger_missing_or_unreadable_is_not_delivered(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTATION M-LEDGER: an unreadable ledger fails closed toward a re-send."""
    event = heal(world, 2)

    def unreadable(*_a: Any) -> frozenset[str]:
        raise SingleReadRefused(SingleReadReason.IO, "evidence/alerts")

    monkeypatch.setattr(heal_io, "delivered_events", unreadable)
    sender = Sender()

    failures = world.run(sender)

    assert failures == 0 and sender.events("retry") == [event]


def test_a_heal_record_without_a_sha_is_a_failure(world: World) -> None:
    world.put(f"evidence/capture/heal/{_date(NOW)}/{NOW}_audit_breezy-quote-tape.json", {"x": 1})

    assert world.run(Sender()) == 1


# -- leg-W gaps ------------------------------------------------------------------------------


def test_gap_first_sent_on_run_after_recording_audit_and_resent_until_delivered(
    world: World,
) -> None:
    sender = Sender()
    assert world.run(sender) == 0 and sender.calls == []  # this run's audit has not written yet
    key = gap(world, 2)  # the audit that records the gap runs after the heal
    expected = (
        "CAPTURE_WATCHDOG_EVIDENCE_GAP",
        f"gap={key} invocation_id={INV} cause=no_stall_record",
    )

    for _run in range(2):
        sender = Sender()
        world.run(sender)
        assert sender.calls == [(*expected, "retry")]


def test_gap_with_late_evidence_not_resent(world: World) -> None:
    """MUTATION M-LATEGAP: a gap is closed only when BOTH the stall record and the delivered
    notifier marker have appeared."""
    gap(world, 2)
    day = _date(NOW - 2 * DAY_NS)
    stall = f"evidence/capture/stall/{day}/{NOW - 2 * DAY_NS}_{INV}_recorder_watchdog.json"
    world.put(stall, {"invocation_id": INV, "observation_sha256": SHA_A})
    sender = Sender()
    world.run(sender)
    assert len(sender.calls) == 1  # the notifier marker is still missing

    marker = f"evidence/alerts/notify/{day}/{RECORDER_UNIT}__{INV}.delivered.json"
    world.put(marker, {"delivered": True})
    world.run(later := Sender())

    assert later.calls == []


def test_an_undelivered_notifier_marker_does_not_close_a_gap(world: World) -> None:
    gap(world, 2)
    day = _date(NOW - 2 * DAY_NS)
    world.put(
        f"evidence/capture/stall/{day}/{NOW - 2 * DAY_NS}_{INV}_recorder_watchdog.json",
        {"invocation_id": INV, "observation_sha256": SHA_A},
    )
    world.put(
        f"evidence/alerts/notify/{day}/{RECORDER_UNIT}__{INV}.delivered.json", {"delivered": False}
    )
    sender = Sender()

    world.run(sender)

    assert len(sender.calls) == 1


def test_gap_abandon_key_is_sha_of_unit_nul_invocation(world: World) -> None:
    """MUTATION M-KEY: ``sha256("breezy-quote-tape.service" NUL InvocationID)``."""
    key = gap(world, 10)
    assert key == hashlib.sha256(f"breezy-quote-tape.service\0{INV}".encode()).hexdigest()
    assert key != hashlib.sha256(f"breezy-quote-tape.service{INV}".encode()).hexdigest()
    abandon = f"CAPTURE_HEAL_ALERT_ABANDONED_{key}"
    sender = Sender()

    world.run(sender)

    assert sender.events() == [abandon] and f"gap={key}" in sender.calls[0][1]
    world.delivered = frozenset({abandon})
    world.run(Sender())
    assert marker_names(world) == [f"gap_{key}.json"]
    world.run(last := Sender())
    assert last.calls == []


def test_gap_ages_out_at_30_days(world: World, caplog: pytest.LogCaptureFixture) -> None:
    """MUTATION M-GAPAGE: an unmarked gap older than 30 days is loud, and is never re-sent."""
    key = gap(world, 31)
    sender = Sender()

    with caplog.at_level("INFO"):
        failures = world.run(sender)

    assert failures == 0 and sender.calls == []
    assert f"CAPTURE_HEAL_UNABANDONED gap={key}" in caplog.text
    assert "heal_alert_unabandoned_count=0 gap_alert_unabandoned_count=1" in caplog.text


def test_one_gap_is_sent_once_however_many_families_record_it(world: World) -> None:
    gap(world, 2, family="fq")
    gap(world, 2, family="other")
    sender = Sender()

    world.run(sender)

    assert len(sender.calls) == 1


def test_only_the_newest_audit_file_of_a_day_counts(world: World) -> None:
    gap(world, 2)
    day = _date(NOW - 2 * DAY_NS)
    clean = AuditResult(dt.date.fromisoformat(day), "fq", DayStatus.PASS, "", (), ())
    world.put(f"evidence/capture/audit/fq/{day}_{NOW}.json", audit_to_wire(clean))
    sender = Sender()

    world.run(sender)

    assert sender.calls == []


def test_an_unreadable_audit_file_counts_as_no_audit(world: World) -> None:
    world.put(f"evidence/capture/audit/fq/{_date(NOW - 2 * DAY_NS)}.json", "{")
    sender = Sender()

    assert world.run(sender) == 0 and sender.calls == []


def test_the_dump_of_a_marker_is_json(world: World) -> None:
    heal(world, 10)
    world.delivered = frozenset({f"CAPTURE_HEALED_{SHA_A}"})

    world.run(Sender())

    body = json.loads(
        (world.root / f"evidence/capture/heal_alert_abandoned/{SHA_A}.json").read_text()
    )
    assert body["key"] == SHA_A and body["proof"] == "delivered"
