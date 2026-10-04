"""AUT-1 WP5 stage 3, S2: the live-proof roll-up (design r3 D8; plan r12 sections 3.11.5 and 6).

Files are real, under ``tmp_path``: audit files written by the audit's own writer, heal and stall
records, AUT-6 notifier markers and delivery records. The roll-up reads them and answers PROVEN or
NOT_PROVEN for one family as of one date. The builders at the top are shared with the CLI tests.
"""

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.analysis.capture_audit import write_audit_file
from breezy.analysis.capture_audit_model import (
    AuditResult,
    DayStatus,
    FillAudit,
)
from breezy.analysis.capture_live_proof import (
    HEAL_ALERT_RETRY_DAYS,
    LIVE_PROOF_SCHEMA,
    LOOKBACK_DAYS,
    MIN_REAL_FILLS,
    QUALIFYING_DAYS,
    build_live_proof,
    newest_audit_by_day,
)
from breezy.persistence.autonomy.capture_alerts import heal_alert_event

FAMILY: Final = "pm_us_crh_fq_v1"
ASOF: Final = dt.date(2026, 10, 20)
UNIT: Final = "breezy-quote-tape.service"
SHA: Final = "ab" * 32
INV: Final = "0123456789abcdef0123456789abcdef"
NS: Final = 1_000_000_000


def day(back: int) -> dt.date:
    """``back`` days before ``ASOF`` (``day(1)`` is yesterday, the newest audited day)."""
    return ASOF - dt.timedelta(days=back)


# -- builders (shared with test_capture_live_proof_cli) ---------------------------------------


def fill(*, source: str = "live", drill: bool = False, n: int = 1) -> FillAudit:
    return FillAudit(
        client_order_id=f"O-{source}-{n}",
        trade_id=f"T{n}",
        family_id=FAMILY,
        source=source,
        drill=drill,
        attributed=True,
        legs=(),
    )


def audit_result(
    d: dt.date,
    status: DayStatus,
    *,
    real: int = 0,
    canary: int = 0,
    lost: int = 0,
    family: str = FAMILY,
) -> AuditResult:
    fills = tuple(fill(n=i) for i in range(real)) + tuple(
        fill(source="canary", n=100 + i) for i in range(canary)
    )
    metrics: dict[str, Any] = {"day_status": status.value, "fills_total": len(fills)}
    if lost:
        metrics["records_lost_in_flush_window"] = lost
    return AuditResult(d, family, status, "", legs=(), fills=fills, metrics=metrics)


def put_audit(
    root: Path, d: dt.date, status: DayStatus = DayStatus.PASS, *, ts_ns: int = 1, **kw: Any
) -> None:
    write_audit_file(root, audit_result(d, status, **kw), ts_ns=ts_ns)


def put_pass_days(root: Path, backs: range, *, real: int = 1) -> None:
    for back in backs:
        put_audit(root, day(back), real=real)


def _write(root: Path, rel: tuple[str, ...], name: str, body: Any) -> Path:
    directory = root.joinpath(*rel)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(body if isinstance(body, bytes) else json.dumps(body).encode())
    path.chmod(0o600)
    return path


def put_heal(
    root: Path,
    d: dt.date,
    *,
    kind: str = "watchdog",
    sha: str = SHA,
    inv: str = INV,
    unit_result: str = "watchdog",
    injected: bool = False,
    name: str | None = None,
) -> str:
    body: dict[str, Any] = {"observation_sha256": sha, "injected": injected}
    if kind == "watchdog":
        body |= {"decided_by": "systemd_watchdog", "invocation_id": inv, "unit_result": unit_result}
        file_name = name or f"{1_000_000 + len(sha)}_audit_breezy-quote-tape.json"
    else:
        body |= {"decided_by": "nbm_quantile_actor", "action": "poll_reset"}
        file_name = name or "1791100000000000000_nbm_quantile_actor.json"
    _write(root, ("evidence", "capture", "heal", d.isoformat()), file_name, body)
    return file_name


def put_stall(root: Path, d: dt.date, *, inv: str = INV, sha: str = SHA) -> None:
    body = {"unit": UNIT, "invocation_id": inv, "observation_sha256": sha, "detected_ns": 1}
    _write(
        root,
        ("evidence", "capture", "stall", d.isoformat()),
        f"1_{inv}_recorder_watchdog.json",
        body,
    )


def put_marker(
    root: Path, d: dt.date, *, inv: str = INV, unit: str = UNIT, ok: bool = True
) -> None:
    _write(
        root,
        ("evidence", "alerts", "notify", d.isoformat()),
        f"{unit}__{inv}.delivered.json",
        {"delivered": ok},
    )


def put_delivery(
    root: Path, d: dt.date, event: str, *, ts: int = 1, delivered: bool = True
) -> None:
    body = {"schema": "alert_delivery/v1", "event": event, "delivered": delivered, "ts_ns": ts}
    _write(root, ("evidence", "alerts", d.isoformat()), f"{ts}_daily_d.json", body)


def put_paired_watchdog_heal(root: Path, d: dt.date, *, deliver_on: dt.date | None = None) -> None:
    put_heal(root, d)
    put_stall(root, d)
    put_marker(root, d)
    put_delivery(root, deliver_on or d, heal_alert_event(SHA))


def proof(root: Path, asof: dt.date = ASOF) -> Any:
    return build_live_proof(root, FAMILY, asof)


def proven_world(root: Path) -> None:
    """The smallest PROVEN world: seven PASS days, five real fills, one paired delivered heal."""
    put_pass_days(root, range(1, 8), real=1)
    put_audit(root, day(3), real=2, ts_ns=2)  # a re-audit: 8 real fills over the window
    put_paired_watchdog_heal(root, day(5))


# -- the proof -------------------------------------------------------------------------------------


def test_seven_pass_days_and_five_fills_is_proven(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 8), real=1)  # 7 days, 7 fills
    put_paired_watchdog_heal(tmp_path, day(5))
    doc = proof(tmp_path)
    assert doc["status"] == "PROVEN"
    assert doc["schema"] == LIVE_PROOF_SCHEMA and doc["family_id"] == FAMILY
    assert doc["asof"] == ASOF.isoformat()
    assert doc["qualifying_day_count"] == 7 and doc["real_fills"] == 7
    assert doc["qualifying_days"] == [day(b).isoformat() for b in range(7, 0, -1)]
    assert doc["criteria"] == {"qualifying_days": True, "real_fills": True, "heal": True}
    assert json.loads(json.dumps(doc)) == doc  # a plain JSON document


def test_the_thresholds_are_the_plan_values() -> None:
    assert (QUALIFYING_DAYS, MIN_REAL_FILLS, HEAL_ALERT_RETRY_DAYS) == (7, 5, 8)
    assert LOOKBACK_DAYS >= 8


def test_six_pass_days_are_not_proven(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 7), real=2)
    put_paired_watchdog_heal(tmp_path, day(5))
    doc = proof(tmp_path)
    assert doc["status"] == "NOT_PROVEN" and doc["qualifying_day_count"] == 6
    assert doc["criteria"]["qualifying_days"] is False


def test_four_real_fills_are_not_proven(tmp_path: Path) -> None:
    put_audit(tmp_path, day(1), real=2)
    put_audit(tmp_path, day(2), real=1)
    put_audit(tmp_path, day(3), real=1)
    for back in range(4, 8):
        put_audit(tmp_path, day(back), canary=1)
    put_paired_watchdog_heal(tmp_path, day(5))
    doc = proof(tmp_path)
    assert doc["qualifying_day_count"] == 7 and doc["real_fills"] == 4
    assert doc["status"] == "NOT_PROVEN" and doc["criteria"]["real_fills"] is False
    put_audit(tmp_path, day(3), real=2, ts_ns=2)  # the fifth real fill
    assert proof(tmp_path)["status"] == "PROVEN"


def test_no_heal_is_not_proven(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 8), real=1)
    doc = proof(tmp_path)
    assert doc["status"] == "NOT_PROVEN" and doc["heal"] is None
    assert doc["criteria"] == {"qualifying_days": True, "real_fills": True, "heal": False}


def test_an_empty_data_root_is_not_proven(tmp_path: Path) -> None:
    doc = proof(tmp_path)
    assert doc["status"] == "NOT_PROVEN" and doc["qualifying_day_count"] == 0


@pytest.mark.parametrize("breaker", [DayStatus.FAIL, DayStatus.ERROR])
def test_fail_or_error_breaks_the_window(tmp_path: Path, breaker: DayStatus) -> None:
    """Eight PASS days around a broken one: only the days after it count (4 < 7)."""
    put_pass_days(tmp_path, range(5, 9), real=2)
    put_audit(tmp_path, day(4), breaker)
    put_pass_days(tmp_path, range(1, 4), real=2)
    put_paired_watchdog_heal(tmp_path, day(2))
    doc = proof(tmp_path)
    assert doc["status"] == "NOT_PROVEN"
    assert doc["qualifying_day_count"] == 3
    assert doc["breaking_days"] == [{"day": day(4).isoformat(), "status": breaker.value}]


def test_a_broken_day_only_restarts_the_count(tmp_path: Path) -> None:
    """Seven PASS days after an old FAIL prove: the break resets the run, it is not permanent."""
    put_audit(tmp_path, day(12), DayStatus.FAIL)
    put_pass_days(tmp_path, range(1, 8), real=1)
    put_audit(tmp_path, day(3), real=3, ts_ns=2)
    put_paired_watchdog_heal(tmp_path, day(5))
    assert proof(tmp_path)["status"] == "PROVEN"


def test_stale_inconclusive_breaks_fresh_is_pending(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(11, 21), real=1)  # ten PASS days before the stale day
    put_audit(tmp_path, day(10), DayStatus.INCONCLUSIVE)  # age 10 > BACKFILL_DAYS: stale
    put_pass_days(tmp_path, range(7, 10), real=2)  # three PASS days after it
    put_paired_watchdog_heal(tmp_path, day(5))
    stale = proof(tmp_path)
    assert stale["status"] == "NOT_PROVEN" and stale["qualifying_day_count"] == 3
    assert stale["breaking_days"] == [{"day": day(10).isoformat(), "status": "INCONCLUSIVE"}]

    fresh_root = tmp_path / "fresh"
    fresh_root.mkdir(mode=0o700)
    put_pass_days(fresh_root, range(3, 10), real=1)  # seven PASS days
    put_audit(fresh_root, day(2), DayStatus.INCONCLUSIVE)  # age 2: still being backfilled
    put_audit(fresh_root, day(1), real=1)
    put_paired_watchdog_heal(fresh_root, day(5))
    fresh = proof(fresh_root)
    assert fresh["status"] == "PROVEN"
    assert fresh["pending_days"] == [day(2).isoformat()]
    assert fresh["breaking_days"] == []


def test_a_fresh_inconclusive_day_does_not_count_either(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(2, 8), real=1)  # six PASS days
    put_audit(tmp_path, day(1), DayStatus.INCONCLUSIVE)
    put_paired_watchdog_heal(tmp_path, day(5))
    doc = proof(tmp_path)
    assert doc["qualifying_day_count"] == 6 and doc["status"] == "NOT_PROVEN"


def test_a_fresh_missing_day_is_pending(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(2, 9), real=1)  # day(1) is not audited yet
    put_paired_watchdog_heal(tmp_path, day(5))
    doc = proof(tmp_path)
    assert doc["pending_days"] == [day(1).isoformat()]
    assert doc["qualifying_day_count"] == 7 and doc["breaking_days"] == []


def test_a_stale_missing_day_breaks_the_run(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(10, 19), real=1)  # nine PASS days, all older than day(9)
    put_pass_days(tmp_path, range(1, 4), real=2)  # day(4)..day(9) missing: day(9) is stale
    doc = proof(tmp_path)
    assert doc["qualifying_day_count"] == 3  # the nine old days were cut off by the stale gap
    assert doc["breaking_days"] == []  # a gap is not an audited break; it is listed as missing
    assert day(9).isoformat() in doc["missing_days"]


@pytest.mark.parametrize("status", [DayStatus.PRE_CAPTURE, DayStatus.PARTIAL_EPOCH])
def test_pre_capture_and_partial_epoch_never_count(tmp_path: Path, status: DayStatus) -> None:
    """Even with fills in the file (an inconsistent one), these days are never qualifying, and they
    do not break the run either."""
    put_pass_days(tmp_path, range(1, 6), real=2)  # five PASS days
    for back in (6, 7):
        put_audit(tmp_path, day(back), status, real=2)
    put_paired_watchdog_heal(tmp_path, day(3))
    doc = proof(tmp_path)
    assert doc["qualifying_day_count"] == 5 and doc["status"] == "NOT_PROVEN"
    assert doc["breaking_days"] == []


def test_no_input_and_zero_fill_pass_days_extend_the_window_not_break_it(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 4), real=2)
    put_audit(tmp_path, day(4), DayStatus.NO_INPUT)
    put_audit(tmp_path, day(5), DayStatus.PASS)  # PASS with no fill at all: zero-fill
    put_pass_days(tmp_path, range(6, 10), real=1)
    put_paired_watchdog_heal(tmp_path, day(2))
    doc = proof(tmp_path)
    assert doc["qualifying_day_count"] == 7 and doc["real_fills"] == 10
    assert doc["status"] == "PROVEN"


def test_canary_only_day_counts_zero_fills(tmp_path: Path) -> None:
    for back in range(1, 4):
        put_audit(tmp_path, day(back), canary=2)  # canary-only days qualify
    put_audit(tmp_path, day(4), real=1)
    put_audit(tmp_path, day(5), real=1)
    put_audit(tmp_path, day(6), real=1)
    put_audit(tmp_path, day(7), real=1)
    put_paired_watchdog_heal(tmp_path, day(2))
    doc = proof(tmp_path)
    assert doc["qualifying_day_count"] == 7 and doc["real_fills"] == 4
    assert doc["status"] == "NOT_PROVEN"
    put_audit(tmp_path, day(7), real=2, ts_ns=2)
    assert proof(tmp_path)["status"] == "PROVEN"


def test_drill_fills_are_not_real_fills(tmp_path: Path) -> None:
    for back in range(1, 8):
        write_audit_file(
            tmp_path,
            dataclasses.replace(audit_result(day(back), DayStatus.PASS), fills=(fill(drill=True),)),
            ts_ns=1,
        )
    put_paired_watchdog_heal(tmp_path, day(2))
    doc = proof(tmp_path)
    assert doc["qualifying_day_count"] == 7 and doc["real_fills"] == 0


def test_lost_in_flush_window_day_still_qualifies(tmp_path: Path) -> None:
    for back in range(1, 8):
        put_audit(tmp_path, day(back), real=1, lost=3)
    put_audit(tmp_path, day(2), real=3, lost=3, ts_ns=2)
    put_paired_watchdog_heal(tmp_path, day(4))
    doc = proof(tmp_path)
    assert doc["qualifying_day_count"] == 7 and doc["status"] == "PROVEN"


def test_the_newest_audit_file_of_a_day_wins(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 8), real=2)
    put_audit(tmp_path, day(3), DayStatus.FAIL, ts_ns=99)  # a later re-audit of the day
    put_paired_watchdog_heal(tmp_path, day(5))
    doc = proof(tmp_path)
    assert doc["status"] == "NOT_PROVEN"
    assert [b["day"] for b in doc["breaking_days"]] == [day(3).isoformat()]


def test_an_unreadable_audit_file_counts_as_no_audit(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 8), real=2)
    put_paired_watchdog_heal(tmp_path, day(5))
    audit_dir = tmp_path / "evidence" / "capture" / "audit" / FAMILY
    (audit_dir / f"{day(4).isoformat()}.json").chmod(0o600)
    (audit_dir / f"{day(4).isoformat()}.json").write_bytes(b"{not json")
    doc = proof(tmp_path)
    assert doc["qualifying_day_count"] == 6 and doc["status"] == "NOT_PROVEN"


def test_other_families_and_other_days_do_not_count(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 7), real=2)
    write_audit_file(
        tmp_path, audit_result(day(7), DayStatus.PASS, real=2, family="other_fam"), ts_ns=1
    )
    put_audit(tmp_path, ASOF, real=2)  # the day of asof itself is not audited yet
    put_audit(tmp_path, ASOF + dt.timedelta(days=1), real=2)
    put_paired_watchdog_heal(tmp_path, day(5))
    assert proof(tmp_path)["qualifying_day_count"] == 6


def test_newest_audit_by_day_picks_the_highest_stamp() -> None:
    names = ["2026-10-01.json", "2026-10-01_5.json", "2026-10-01_30.json", "2026-10-02.json",
             "notes.json", "2026-13-40.json", "2026-10-03.json.tmp"]  # fmt: skip
    assert newest_audit_by_day(names) == {
        dt.date(2026, 10, 1): "2026-10-01_30.json",
        dt.date(2026, 10, 2): "2026-10-02.json",
    }


# -- the heal pairing ---------------------------------------------------------------------------


def test_watchdog_heal_pairs_stall_unit_result_and_marker(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 8), real=1)
    put_audit(tmp_path, day(2), real=4, ts_ns=2)
    put_paired_watchdog_heal(tmp_path, day(5))
    doc = proof(tmp_path)
    assert doc["status"] == "PROVEN"
    assert doc["heal"]["decided_by"] == "systemd_watchdog"
    assert doc["heal"]["observation_sha256"] == SHA and doc["heal"]["date"] == day(5).isoformat()


_SPOILS: Final = (
    "no_stall", "stall_other_sha", "stall_other_inv", "unit_result", "no_marker", "marker_false",
    "marker_other_inv", "marker_other_unit", "no_delivery", "delivery_other_event",
)  # fmt: skip


@pytest.mark.parametrize("spoil", _SPOILS)
def test_a_watchdog_heal_missing_any_leg_does_not_prove(tmp_path: Path, spoil: str) -> None:
    put_pass_days(tmp_path, range(1, 8), real=1)
    put_audit(tmp_path, day(2), real=4, ts_ns=2)
    put_heal(tmp_path, day(5), unit_result="timeout" if spoil == "unit_result" else "watchdog")
    if spoil != "no_stall":
        other_sha, other_inv = "cd" * 32, "f" * 32
        put_stall(
            tmp_path,
            day(5),
            sha=other_sha if spoil == "stall_other_sha" else SHA,
            inv=other_inv if spoil == "stall_other_inv" else INV,
        )
    if spoil != "no_marker":
        put_marker(
            tmp_path,
            day(5),
            ok=spoil != "marker_false",
            inv="e" * 32 if spoil == "marker_other_inv" else INV,
            unit="breezy-trade.service" if spoil == "marker_other_unit" else UNIT,
        )
    if spoil != "no_delivery":
        other_event = "CAPTURE_HEALED_" + "cd" * 32
        put_delivery(
            tmp_path,
            day(5),
            other_event if spoil == "delivery_other_event" else heal_alert_event(SHA),
        )
    assert proof(tmp_path)["status"] == "NOT_PROVEN", spoil


def test_the_unspoiled_world_proves(tmp_path: Path) -> None:
    """Control for the spoil cases above: the same world with nothing spoiled is PROVEN."""
    put_pass_days(tmp_path, range(1, 8), real=1)
    put_audit(tmp_path, day(2), real=4, ts_ns=2)
    put_paired_watchdog_heal(tmp_path, day(5))
    assert proof(tmp_path)["status"] == "PROVEN"


def test_a_heal_not_decided_by_the_watchdog_or_the_nbp_actor_does_not_count(tmp_path: Path) -> None:
    proven_world(tmp_path)
    for path in (tmp_path / "evidence" / "capture" / "heal").rglob("*.json"):
        body = json.loads(path.read_text())
        body["decided_by"] = "somebody_else"
        path.write_text(json.dumps(body))
    assert proof(tmp_path)["status"] == "NOT_PROVEN"


def test_an_injected_heal_counts(tmp_path: Path) -> None:
    """The plan accepts an injected stall when no natural one occurs (WP9 drill)."""
    put_pass_days(tmp_path, range(1, 8), real=1)
    put_audit(tmp_path, day(2), real=4, ts_ns=2)
    put_heal(tmp_path, day(5), injected=True)
    put_stall(tmp_path, day(5))
    put_marker(tmp_path, day(5))
    put_delivery(tmp_path, day(5), heal_alert_event(SHA))
    doc = proof(tmp_path)
    assert doc["status"] == "PROVEN" and doc["heal"]["injected"] is True


def test_nbp_heal_alternative_satisfies_stall_leg(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 8), real=1)
    put_audit(tmp_path, day(2), real=4, ts_ns=2)
    put_heal(tmp_path, day(5), kind="nbp")  # no stall record, no marker
    put_delivery(tmp_path, day(5), heal_alert_event(SHA))
    doc = proof(tmp_path)
    assert doc["status"] == "PROVEN" and doc["heal"]["decided_by"] == "nbm_quantile_actor"
    undelivered = tmp_path / "evidence" / "alerts" / day(5).isoformat()
    for path in undelivered.glob("*.json"):
        path.unlink()
    assert proof(tmp_path)["status"] == "NOT_PROVEN"  # the alternative still needs artefact 3


def test_healed_delivered_outside_plus8_window_does_not_count(tmp_path: Path) -> None:
    heal_date = day(10)
    for delivered_on, ok in [
        (heal_date, True),
        (heal_date + dt.timedelta(days=HEAL_ALERT_RETRY_DAYS), True),
        (heal_date + dt.timedelta(days=HEAL_ALERT_RETRY_DAYS + 1), False),
        (heal_date - dt.timedelta(days=1), False),
    ]:
        root = tmp_path / f"d{delivered_on.isoformat()}"
        root.mkdir(mode=0o700)
        put_pass_days(root, range(1, 8), real=1)
        put_audit(root, day(2), real=4, ts_ns=2)
        put_paired_watchdog_heal(root, heal_date, deliver_on=delivered_on)
        assert (proof(root)["status"] == "PROVEN") is ok, delivered_on


def test_a_failed_delivery_record_is_not_a_delivery(tmp_path: Path) -> None:
    put_pass_days(tmp_path, range(1, 8), real=1)
    put_audit(tmp_path, day(2), real=4, ts_ns=2)
    put_heal(tmp_path, day(5), kind="nbp")
    put_delivery(tmp_path, day(5), heal_alert_event(SHA), delivered=False)
    assert proof(tmp_path)["status"] == "NOT_PROVEN"


def test_rollup_reports_heal_alert_undelivered(tmp_path: Path) -> None:
    put_heal(tmp_path, day(5), kind="nbp", name="a.json")
    put_heal(tmp_path, day(6), kind="nbp", sha="cd" * 32, name="b.json")
    put_delivery(tmp_path, day(6), heal_alert_event("cd" * 32))
    doc = proof(tmp_path)
    assert doc["heal_alert_undelivered_count"] == 1
    assert doc["heal_alert_undelivered"] == [
        {
            "heal_record": f"{day(5).isoformat()}/a.json",
            "event": heal_alert_event(SHA),
            "age_days": 5,
        }
    ]


def test_a_malformed_heal_record_is_ignored_not_fatal(tmp_path: Path) -> None:
    proven_world(tmp_path)
    heal_dir = tmp_path / "evidence" / "capture" / "heal" / day(6).isoformat()
    heal_dir.mkdir(parents=True)
    (heal_dir / "x.json").write_bytes(b"\x00 garbage")
    (heal_dir / "y.json").write_text(json.dumps({"decided_by": "nbm_quantile_actor"}))
    (heal_dir / "z.json").write_text(json.dumps({"decided_by": "nbm_quantile_actor",
                                                  "observation_sha256": "short"}))  # fmt: skip
    (heal_dir / "w.txt").write_text("not a record")
    doc = proof(tmp_path)
    assert doc["status"] == "PROVEN"
    assert doc["heal_alert_undelivered"] == []


def test_the_delivery_ledger_is_read_once_per_call_however_many_heals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-R57: the roll-up reads the ledger once, not once per heal."""
    from breezy.analysis import capture_aut6_contract as contract

    put_heal(tmp_path, day(5), kind="nbp", name="a.json")
    put_heal(tmp_path, day(6), kind="nbp", sha="cd" * 32, name="b.json")
    put_heal(tmp_path, day(7), kind="nbp", sha="ef" * 32, name="c.json")
    reads: list[str] = []
    real: Any = vars(contract)["read_file"]

    def counting(root: Path, rel: tuple[str, ...], name: str, *a: Any) -> Any:
        if rel[:2] == ("evidence", "alerts") and "notify" not in rel:
            reads.append(name)
        return real(root, rel, name, *a)

    put_delivery(tmp_path, day(6), heal_alert_event("cd" * 32))
    monkeypatch.setattr(contract, "read_file", counting)

    doc = proof(tmp_path)

    assert doc["heal_alert_undelivered_count"] == 2
    assert len(reads) == 1
