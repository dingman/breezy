"""AUT-6 WP3 S5: timers #28, producer #26, daily verdict #27 and the not-deployed rule (X-8).

The logic tests run on a synthetic ``deploy/systemd`` so every case is exact; the coverage tests
read the real one. Nothing here runs systemctl or journalctl.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import monitor_watch
from breezy.runtime.monitor_watch import (
    NOT_DEPLOYED_ARTIFACTS,
    NOT_DEPLOYED_CRITICAL_FROM,
    NOT_YET_DEPLOYED,
    TIMER_INSTANCE_INTERVAL_S,
    TIMER_MAX_INTERVAL_S,
    TIMER_RETIRED_BY_RULING,
)
from breezy.runtime.monitor_watch_model import (
    deploy_unit_names,
    directive_values,
    firing_minutes,
    max_gap_s,
    parse_accuracy_s,
    timer_accuracy_s,
)
from breezy.runtime.monitor_watch_producer import (
    FileProducerSource,
    ReaderUnwired,
    evaluate_daily,
    evaluate_producer,
)
from breezy.runtime.monitor_watch_timers import TIMER_GRACE_S
from tests.support.monitor_watch_fixtures import (
    REPO_DEPLOY,
    TEMPLATE,
    TIMER_A,
    TIMER_M,
    TIMER_R,
    healthy_timer_blocks,
    installed,
    later,
    run_watch,
    snapshot,
    subjects,
    synth_deploy,
    timer_block,
    wiring,
)
from tests.support.unit_health_daemon_fixtures import systemd_ts
from tests.support.unit_health_fixtures import NOW_NS, NS

TIMERS = "aut6.timer_liveness"
PRODUCER = "aut6.producer_stale"
DAILY = "aut6.daily_verdict_absent"
REPO = Path(__file__).resolve().parents[2]
INSTANCE_ONE = "breezy-t@one.timer"
INSTANCE_TWO = "breezy-t@two.timer"


@pytest.fixture
def deploy(tmp_path: Path) -> Path:
    return synth_deploy(tmp_path / "deploy")


def healthy(deploy: Path, **timer_kw: Any) -> list[str]:
    return [
        timer_block(TIMER_A, **timer_kw),
        timer_block(TIMER_M, monotonic_next="45min", next_s=None, **timer_kw),
        timer_block(INSTANCE_ONE, **timer_kw),
    ]


def judge(tmp_path: Path, deploy: Path, blocks: list[str], **kw: Any) -> Any:
    files = installed(deploy, skip=[TIMER_R], instances=[INSTANCE_ONE])
    snap = snapshot(blocks=blocks, unit_files=kw.pop("unit_files", files))
    return run_watch(wiring(tmp_path, deploy, **kw.pop("wiring", {})), snap, **kw).by_detector(
        TIMERS
    )


# --------------------------------------------------------------------------- the tables


def test_timer_interval_table_covers_every_deployed_timer() -> None:
    files = {n for n in deploy_unit_names(REPO_DEPLOY) if n.endswith(".timer")}
    keys, retired = set(TIMER_MAX_INTERVAL_S), set(TIMER_RETIRED_BY_RULING)
    assert files == keys | retired
    assert keys.isdisjoint(retired)
    # both templates, and no literal count anywhere
    assert {"breezy-family-tally@.timer", "us-source-collector@.timer"} <= keys


def test_retired_timer_files_carry_a_retired_header_naming_an_existing_ruling() -> None:
    for timer, ruling in TIMER_RETIRED_BY_RULING.items():
        head = (REPO_DEPLOY / timer).read_text(encoding="utf-8").splitlines()[0]
        assert head.startswith("# RETIRED")
        assert ruling in (REPO_DEPLOY / timer).read_text(encoding="utf-8")
        assert (REPO / "docs" / "evidence" / f"{ruling}.md").is_file()


def test_timer_interval_table_states_assumed_accuracy_matching_unit_files() -> None:
    """Y7: each pair states the AccuracySec its grace assumes; a loosened timer fails here."""
    pairs = {**TIMER_MAX_INTERVAL_S, **TIMER_INSTANCE_INTERVAL_S}
    for name, (_interval, accuracy) in pairs.items():
        assert timer_accuracy_s(REPO_DEPLOY, name) == accuracy, name
    assert timer_accuracy_s(REPO_DEPLOY, "breezy-no-such.timer") == 60.0  # the manager default


def test_timer_interval_table_values_equal_the_longest_calendar_gap() -> None:
    for name, (interval, _accuracy) in {
        **TIMER_MAX_INTERVAL_S,
        **TIMER_INSTANCE_INTERVAL_S,
    }.items():
        assert max_gap_s(REPO_DEPLOY, name) == interval, name


def test_instance_interval_table_covers_every_instance_dropin_schedule() -> None:
    dropins = {p.name.removesuffix(".d") for p in REPO_DEPLOY.glob("*@*.timer.d")}
    assert dropins == set(TIMER_INSTANCE_INTERVAL_S)


def test_calendar_expander_forms_and_unsupported_specs() -> None:
    assert firing_minutes("*-*-* 04:30:00 UTC") == {4 * 60 + 30}
    assert firing_minutes("*:45:00 UTC") == {h * 60 + 45 for h in range(24)}
    assert firing_minutes("*:03/5") == {h * 60 + m for h in range(24) for m in range(3, 60, 5)}
    assert firing_minutes("*-*-* 16:00,15:00 UTC") == {16 * 60, 16 * 60 + 15}
    assert 17 * 60 + 31 in firing_minutes("*-*-* 0..15,17..23:31:00 UTC")
    assert 16 * 60 + 31 not in firing_minutes("*-*-* 0..15,17..23:31:00 UTC")
    for bad in ("Mon *-*-* 04:00:00", "daily", "*-*-* 25:00:00", "2026-10-09 04:00"):
        with pytest.raises(ValueError):
            firing_minutes(bad)


def test_parse_accuracy_forms() -> None:
    assert parse_accuracy_s("1min") == 60 and parse_accuracy_s("30sec") == 30
    assert parse_accuracy_s("1s") == 1 and parse_accuracy_s("nonsense") is None


def test_dropin_reset_clears_the_list() -> None:
    values = directive_values(REPO_DEPLOY, "us-source-collector@nbp.timer", "OnCalendar")
    assert values == ["*-*-* 02,08,14,20:05:00 UTC"]


# --------------------------------------------------------------------------- timer liveness


def test_healthy_timers_pass(tmp_path: Path, deploy: Path) -> None:
    result = judge(tmp_path, deploy, healthy(deploy))
    assert result.outcome == "PASS", result.findings
    assert result.metrics["timers_judged"] == "3"


def test_template_timer_expanded_to_enabled_instances(tmp_path: Path, deploy: Path) -> None:
    files = installed(deploy, skip=[TIMER_R], instances=[INSTANCE_ONE, INSTANCE_TWO])
    blocks = [*healthy(deploy), timer_block(INSTANCE_TWO, last_s=-3 * 86_400)]
    result = judge(tmp_path, deploy, blocks, unit_files=files)
    assert subjects(result, "timer_last_trigger_stale") == {INSTANCE_TWO}
    assert result.metrics["timers_judged"] == "4"


def test_disabled_template_instance_is_not_expanded(tmp_path: Path, deploy: Path) -> None:
    files = installed(deploy, skip=[TIMER_R], instances=[INSTANCE_ONE])
    files += f"{INSTANCE_TWO:<44} disabled  enabled\n"
    blocks = [*healthy(deploy), timer_block(INSTANCE_TWO, enabled="disabled", last_s=None)]
    result = judge(tmp_path, deploy, blocks, unit_files=files)
    assert result.outcome == "PASS", result.findings


def test_template_with_zero_enabled_instances_fails(tmp_path: Path, deploy: Path) -> None:
    files = installed(deploy, skip=[TIMER_R])
    result = judge(tmp_path, deploy, healthy(deploy)[:2], unit_files=files)
    assert subjects(result, "timer_template_no_instances") == {TEMPLATE}


def test_timer_not_enabled_is_fail(tmp_path: Path, deploy: Path) -> None:
    blocks = [timer_block(TIMER_A, enabled="disabled"), *healthy(deploy)[1:]]
    result = judge(tmp_path, deploy, blocks)
    assert subjects(result, "timer_not_enabled") == {TIMER_A}


def test_timer_not_active_is_fail(tmp_path: Path, deploy: Path) -> None:
    blocks = [timer_block(TIMER_A, active="inactive"), *healthy(deploy)[1:]]
    assert subjects(judge(tmp_path, deploy, blocks), "timer_not_active") == {TIMER_A}


def test_timer_without_a_future_elapse_is_fail(tmp_path: Path, deploy: Path) -> None:
    blocks = [timer_block(TIMER_A, next_s=-60), *healthy(deploy)[1:]]
    assert subjects(judge(tmp_path, deploy, blocks), "timer_no_next_elapse") == {TIMER_A}


def test_last_trigger_zero_after_grace_is_fail(tmp_path: Path, deploy: Path) -> None:
    old = timer_block(TIMER_A, last_s=None, entered_s=-(86_400 + TIMER_GRACE_S + 60))
    result = judge(tmp_path, deploy, [old, *healthy(deploy)[1:]])
    assert subjects(result, "timer_never_triggered") == {TIMER_A}


def test_last_trigger_zero_inside_grace_is_not_a_fail(tmp_path: Path, deploy: Path) -> None:
    fresh = timer_block(TIMER_A, last_s=None, entered_s=-3600)
    result = judge(tmp_path, deploy, [fresh, *healthy(deploy)[1:]])
    assert result.outcome == "PASS", result.findings


def test_timer_liveness_fails_on_stale_last_trigger(tmp_path: Path, deploy: Path) -> None:
    stale = timer_block(TIMER_A, last_s=-(86_400 + TIMER_GRACE_S + 60))
    ok = timer_block(TIMER_A, last_s=-(86_400 + TIMER_GRACE_S - 60))
    assert subjects(
        judge(tmp_path, deploy, [stale, *healthy(deploy)[1:]]), "timer_last_trigger_stale"
    )
    assert judge(tmp_path, deploy, [ok, *healthy(deploy)[1:]]).outcome == "PASS"


def test_monotonic_timer_uses_next_elapse_monotonic(tmp_path: Path, deploy: Path) -> None:
    bad = timer_block(TIMER_M, monotonic_next="0", next_s=7200)  # a realtime value must not count
    result = judge(tmp_path, deploy, [healthy(deploy)[0], bad, healthy(deploy)[2]])
    assert subjects(result, "timer_no_next_elapse") == {TIMER_M}
    good = timer_block(TIMER_M, monotonic_next="45min", next_s=None)
    assert judge(tmp_path, deploy, [healthy(deploy)[0], good, healthy(deploy)[2]]).outcome == "PASS"


def test_a_timers_monotonic_property_in_the_block_overrides_the_files(
    tmp_path: Path, deploy: Path
) -> None:
    """``TimersMonotonic`` in the block (when the read carries it) decides, not the unit file."""
    block = timer_block(TIMER_A, TimersMonotonic="{ OnUnitActiveSec=1h }", monotonic_next="5min")
    result = judge(tmp_path, deploy, [block, *healthy(deploy)[1:]])
    assert result.outcome == "PASS", result.findings


def test_retired_timer_enabled_is_fail(tmp_path: Path, deploy: Path) -> None:
    on = timer_block(TIMER_R)
    files = installed(deploy, instances=[INSTANCE_ONE])
    assert subjects(
        judge(tmp_path, deploy, [*healthy(deploy), on], unit_files=files), "retired_timer_enabled"
    ) == {TIMER_R}
    off = timer_block(TIMER_R, enabled="disabled")
    assert judge(tmp_path, deploy, [*healthy(deploy), off], unit_files=files).outcome == "PASS"


def test_unreadable_timer_properties_make_the_pass_unknown(tmp_path: Path, deploy: Path) -> None:
    missing = "Id=" + TIMER_A + "\nLoadState=loaded\nActiveState=active\n"
    result = judge(tmp_path, deploy, [missing, *healthy(deploy)[1:]])
    assert any(r.startswith("timer_property_missing:" + TIMER_A) for r in result.unknown_reasons)
    garbled = timer_block(TIMER_A, LastTriggerUSec="yesterday-ish")
    result = judge(tmp_path, deploy, [garbled, *healthy(deploy)[1:]])
    assert any("unparseable" in r for r in result.unknown_reasons)


def test_present_timer_without_a_show_block_is_unknown_not_a_pass(
    tmp_path: Path, deploy: Path
) -> None:
    result = judge(tmp_path, deploy, healthy(deploy)[1:])
    assert result.unknown_reasons == (f"timer_property_missing:{TIMER_A}:block",)


def real_blocks_and_files() -> tuple[list[str], str]:
    files = installed(REPO_DEPLOY, skip=TIMER_RETIRED_BY_RULING)
    instances = ["breezy-family-tally@pm_us_crh_v2.timer", "us-source-collector@obs.timer"]
    files += "".join(f"{name:<44} enabled   enabled\n" for name in instances)
    names = [n for n in TIMER_MAX_INTERVAL_S if "@." not in n] + instances
    return healthy_timer_blocks(names), files


def real_wiring(tmp_path: Path) -> Any:
    return wiring(
        tmp_path,
        REPO_DEPLOY,
        table=TIMER_MAX_INTERVAL_S,
        instance_intervals=TIMER_INSTANCE_INTERVAL_S,
        retired=TIMER_RETIRED_BY_RULING,
        rows=NOT_YET_DEPLOYED,
        artifacts=NOT_DEPLOYED_ARTIFACTS,
    )


def test_canary_timer_is_judged_normally_on_the_real_tables(tmp_path: Path) -> None:
    """The canary is live (10-08): no not-deployed exemption, so a stale trigger fails it."""
    blocks, files = real_blocks_and_files()
    canary = "breezy-autonomy-canary.timer"
    ok = run_watch(real_wiring(tmp_path), snapshot(blocks=blocks, unit_files=files))
    assert ok.by_detector(TIMERS).outcome == "PASS", ok.by_detector(TIMERS).findings
    assert canary not in {r.unit for r in NOT_YET_DEPLOYED.values()}
    stale = [timer_block(canary, last_s=-3 * 3600) if f"Id={canary}" in b else b for b in blocks]
    bad = run_watch(real_wiring(tmp_path), snapshot(blocks=stale, unit_files=files))
    assert subjects(bad.by_detector(TIMERS), "timer_last_trigger_stale") == {canary}


def test_template_instance_override_uses_its_own_interval(tmp_path: Path) -> None:
    """``us-source-collector@obs`` fires at least every 50 min, ``@nbp`` every 6 h: a trigger 3 h
    ago is stale for the first only."""
    blocks, files = real_blocks_and_files()
    files += f"{'us-source-collector@nbp.timer':<44} enabled   enabled\n"
    three_hours = -3 * 3600
    obs = timer_block("us-source-collector@obs.timer", last_s=three_hours, next_s=300)
    nbp = timer_block("us-source-collector@nbp.timer", last_s=three_hours, next_s=300)
    rest = [b for b in blocks if "Id=us-source-collector@obs.timer" not in b]
    result = run_watch(real_wiring(tmp_path), snapshot(blocks=[*rest, obs, nbp], unit_files=files))
    assert subjects(result.by_detector(TIMERS), "timer_last_trigger_stale") == {
        "us-source-collector@obs.timer"
    }


# --------------------------------------------------------------------------- X-8: not deployed


UNITS = ("breezy-autonomy-producer-intraday.service", "breezy-autonomy-producer-intraday.timer")
ROWS = NOT_YET_DEPLOYED
ARTIFACTS = NOT_DEPLOYED_ARTIFACTS
HEARTBEAT = "derived/verdicts/.aut6-intraday.heartbeat"


def watch_with_rows(tmp_path: Path, deploy: Path, **kw: Any) -> Any:
    return wiring(
        tmp_path,
        deploy,
        rows=ROWS,
        artifacts=ARTIFACTS,
        producer=kw.pop("producer", None),
        **kw,
    )


def x8(tmp_path: Path, deploy: Path, *, unit_files: str, now_ns: int = NOW_NS, **kw: Any) -> Any:
    snap = snapshot(blocks=healthy(deploy), unit_files=unit_files, now_ns=now_ns)
    return run_watch(watch_with_rows(tmp_path, deploy, **kw), snap, now_ns=now_ns)


def x8_files(deploy: Path, extra: str = "") -> str:
    return installed(deploy, skip=[TIMER_R], instances=[INSTANCE_ONE]) + extra


def test_never_deployed_listed_unit_reads_inconclusive_and_is_listed(
    tmp_path: Path, deploy: Path
) -> None:
    """The positive control: row present, before the deadline, no unit, no artifact."""
    result = x8(tmp_path, deploy, unit_files=x8_files(deploy))
    assert set(result.not_deployed) == set(NOT_YET_DEPLOYED)
    assert not any(f.subject in ROWS for f in result.by_detector(TIMERS).findings)
    assert result.by_detector(PRODUCER).outcome == "INCONCLUSIVE"
    assert result.by_detector(PRODUCER).metrics["unknown_reason"] == "not_deployed"
    assert result.unknown_reasons == ()  # never counts toward unknown_streak


def test_deleted_link_with_artifacts_is_deployed_then_vanished(
    tmp_path: Path, deploy: Path
) -> None:
    (tmp_path / "data" / HEARTBEAT).parent.mkdir(parents=True)
    (tmp_path / "data" / HEARTBEAT).write_text("{}")
    result = x8(tmp_path, deploy, unit_files=x8_files(deploy))
    assert subjects(result.by_detector(TIMERS), "deployed_then_vanished") == set(UNITS)
    assert set(result.not_deployed).isdisjoint(UNITS)


def test_artifact_present_while_unit_absent_fails_even_for_a_renamed_unit(
    tmp_path: Path, deploy: Path
) -> None:
    """A unit re-installed under another name leaves the listed name absent and its artifact."""
    (tmp_path / "data" / HEARTBEAT).parent.mkdir(parents=True)
    (tmp_path / "data" / HEARTBEAT).write_text("{}")
    renamed = "breezy-autonomy-producer-intraday-v2.timer"
    files = x8_files(deploy, f"{renamed:<44} enabled   enabled\n")
    result = x8(tmp_path, deploy, unit_files=files)
    assert subjects(result.by_detector(TIMERS), "deployed_then_vanished") == set(UNITS)


def test_broken_symlink_is_unit_link_broken(tmp_path: Path, deploy: Path) -> None:
    files = x8_files(deploy, f"{UNITS[1]:<44} bad       enabled\n")
    result = x8(tmp_path, deploy, unit_files=files)
    assert subjects(result.by_detector(TIMERS), "unit_link_broken") == {UNITS[1]}
    assert UNITS[1] not in result.not_deployed


def test_unlisted_absent_unit_is_critical_missing(tmp_path: Path, deploy: Path) -> None:
    files = installed(deploy, skip=[TIMER_R, "breezy-a.service"], instances=[INSTANCE_ONE])
    result = x8(tmp_path, deploy, unit_files=files)
    finding = next(
        f for f in result.by_detector(TIMERS).findings if f.subject == "breezy-a.service"
    )
    assert (finding.kind, finding.severity) == ("unit_missing", "CRITICAL")


def test_listed_unit_past_deadline_warns_then_goes_critical(tmp_path: Path, deploy: Path) -> None:
    def days_to(iso: str) -> int:
        return (dt.date.fromisoformat(iso) - dt.date(2026, 10, 8)).days

    just_past = later(days_to("2026-11-16") + 1)
    result = x8(tmp_path, deploy, unit_files=x8_files(deploy), now_ns=just_past)
    sev = {f.severity for f in result.by_detector(TIMERS).findings if f.subject in ROWS}
    assert sev == {"WARNING"}
    assert {f.kind for f in result.by_detector(TIMERS).findings if f.subject in ROWS} == {
        "unit_not_deployed_overdue"
    }
    critical = later(days_to(NOT_DEPLOYED_CRITICAL_FROM) + 1)
    result = x8(tmp_path, deploy, unit_files=x8_files(deploy), now_ns=critical)
    assert {f.severity for f in result.by_detector(TIMERS).findings if f.subject in ROWS} == {
        "CRITICAL"
    }
    assert result.not_deployed == ()


def test_installed_listed_unit_is_judged_normally(tmp_path: Path, deploy: Path) -> None:
    files = x8_files(deploy, "".join(f"{u:<44} enabled   enabled\n" for u in UNITS))
    result = x8(tmp_path, deploy, unit_files=files)
    assert set(result.not_deployed).isdisjoint(UNITS)
    assert result.by_detector(TIMERS).outcome == "PASS"


def test_every_deploy_systemd_unit_is_installed_or_listed() -> None:
    """The S2 list-unit-files read against ``deploy/systemd/*.service|*.timer`` names."""
    from breezy.runtime.monitor_watch_deploy import classify_unit
    from breezy.runtime.monitor_watch_model import parse_inventory
    from breezy.runtime.monitor_watch_timers import inventory_findings

    names = deploy_unit_names(REPO_DEPLOY)
    assert names and all(n.endswith((".service", ".timer")) for n in names)

    def findings(files: str) -> tuple[list[Any], list[str]]:
        inv = parse_inventory("", files, {})

        def classify(name: str) -> Any:
            return classify_unit(
                name,
                inventory=inv,
                rows=NOT_YET_DEPLOYED,
                has_artifacts=lambda _n: False,
                today="2026-10-08",
                critical_from=NOT_DEPLOYED_CRITICAL_FROM,
            )

        return inventory_findings(REPO_DEPLOY, classify, "2026-10-08", tuple(NOT_YET_DEPLOYED))

    everything = "".join(f"{n} enabled enabled\n" for n in names)
    found, listed = findings(everything)
    assert found == [] and set(listed) == set(NOT_YET_DEPLOYED)
    dropped = names[0]
    found, _ = findings("".join(f"{n} enabled enabled\n" for n in names if n != dropped))
    assert [f.subject for f in found] == [dropped]


def test_not_yet_deployed_rows_are_well_formed() -> None:
    import re

    assert NOT_YET_DEPLOYED
    for unit, row in NOT_YET_DEPLOYED.items():
        assert unit == row.unit and re.fullmatch(r"breezy-[a-z0-9-]+\.(service|timer)", unit)
        assert row.owner_wp.startswith("AUT-6.WP")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.not_expected_until)
        assert row.not_expected_until < NOT_DEPLOYED_CRITICAL_FROM  # a WARNING span exists
        assert unit not in deploy_unit_names(REPO_DEPLOY)  # a row is deleted when its file lands
        assert NOT_DEPLOYED_ARTIFACTS.get(unit)
    assert set(NOT_DEPLOYED_ARTIFACTS) <= set(NOT_YET_DEPLOYED)


# --------------------------------------------------------------------------- producer #26


class Source:
    def __init__(self, **kw: Any) -> None:
        self.beat = kw.get("beat")
        self.missing = kw.get("missing", [])
        self.daily = kw.get("daily", {})
        self.skips = kw.get("skips", [])
        self.calls: list[str] = []

    def heartbeat(self) -> Any:
        if isinstance(self.beat, Exception):
            raise self.beat
        return self.beat

    def missing_intraday(self, now_ns: int) -> Any:
        self.calls.append("missing")
        return self.missing

    def newest_daily_verdict_ns(self) -> Any:
        return self.daily

    def daily_skips(self) -> Any:
        return self.skips


def beat(
    age_s: float = 60, *, fold_ok: bool = True, reason: str = "", at: int = NOW_NS
) -> dict[str, Any]:
    return {
        "schema": "x",
        "ts_ns": at - int(age_s * NS),
        "fold_ok": fold_ok,
        "fold_reason": reason,
    }


def producer(source: Source, now_ns: int = NOW_NS) -> Any:
    return evaluate_producer(source, now_ns=now_ns, today="2026-10-08")


def test_producer_stale_on_old_heartbeat() -> None:
    assert producer(Source(beat=beat(901))).findings[0].kind == "producer_heartbeat_stale"
    assert producer(Source(beat=beat(899))).outcome == "PASS"


def test_producer_stale_fails_on_fold_not_ok() -> None:
    result = producer(Source(beat=beat(fold_ok=False, reason="unreadable")))
    assert [f.kind for f in result.findings] == ["producer_fold_not_ok"]
    assert result.findings[0].metrics["fold_reason"] == "unreadable"


def test_missing_intraday_verdict_in_window_alerts() -> None:
    in_window = NOW_NS + 6 * 3600 * NS  # 18:00Z
    source = Source(beat=beat(60, at=in_window), missing=["KNYC/aut6.fill_better_than_ask"])
    result = producer(source, in_window)
    assert result.findings[0].kind == "intraday_verdict_missing"
    assert result.findings[0].metrics["missing"] == "KNYC/aut6.fill_better_than_ask"


def test_missing_intraday_verdict_outside_the_window_is_not_read() -> None:
    source = Source(beat=beat(60), missing=["KNYC/x"])  # 12:00Z, outside [17:05Z, 01:00Z)
    assert producer(source).outcome == "PASS" and source.calls == []
    at_0059 = NOW_NS + (12 * 3600 + 59 * 60) * NS  # 00:59Z
    assert producer(Source(beat=beat(60, at=at_0059), missing=["x"]), at_0059).findings
    at_0100 = NOW_NS + 13 * 3600 * NS  # 01:00Z
    assert producer(Source(beat=beat(60, at=at_0100), missing=["x"]), at_0100).outcome == "PASS"


def test_producer_missing_heartbeat_fails_after_grace_and_waits_inside_it() -> None:
    result = evaluate_producer(
        Source(), now_ns=NOW_NS, today="d", enabled_since_ns=NOW_NS - 3600 * NS
    )
    assert result.findings[0].kind == "producer_heartbeat_missing"
    soon = evaluate_producer(Source(), now_ns=NOW_NS, today="d", enabled_since_ns=NOW_NS - 60 * NS)
    assert soon.outcome == "INCONCLUSIVE" and not soon.findings


def test_producer_unreadable_heartbeat_is_unknown_never_a_pass() -> None:
    for bad in (OSError("eio"), ValueError("json"), {"ts_ns": "x", "fold_ok": True}):
        result = producer(Source(beat=bad))
        assert result.unknown_reasons == ("producer_heartbeat_unreadable",) and not result.findings


def test_unwired_verdict_reader_is_unknown_when_the_unit_is_deployed(tmp_path: Path) -> None:
    src = FileProducerSource(tmp_path)
    with pytest.raises(ReaderUnwired):
        src.missing_intraday(NOW_NS)
    (tmp_path / "derived" / "verdicts").mkdir(parents=True)
    (tmp_path / "derived" / "verdicts" / ".aut6-intraday.heartbeat").write_text(
        json.dumps({"ts_ns": NOW_NS - NS, "fold_ok": True})
    )
    in_window = NOW_NS + 6 * 3600 * NS
    result = evaluate_producer(src, now_ns=in_window + NS, today="d")
    assert "producer_reader_unwired" in result.unknown_reasons


def test_file_producer_source_reads_heartbeat_and_skip_records(tmp_path: Path) -> None:
    src = FileProducerSource(tmp_path)
    assert src.heartbeat() is None and src.daily_skips() == []
    skips = tmp_path / "derived" / "verdicts" / "_aut6_daily_skips"
    skips.mkdir(parents=True)
    (skips / "2026-10-08_0530.json").write_text(
        '{"ts_ns": 1, "slot": "05:30", "reason": "lock_timeout"}'
    )
    assert src.daily_skips()[0]["reason"] == "lock_timeout"
    (skips / "2026-10-08_1300.json").write_text("[1]")
    with pytest.raises(TypeError):
        src.daily_skips()


# --------------------------------------------------------------------------- daily #27


def daily(source: Source, now_ns: int = NOW_NS) -> Any:
    return evaluate_daily(source, now_ns=now_ns, today="2026-10-08")


def test_daily_verdict_absent_after_30h() -> None:
    stale = {"KNYC": NOW_NS - int(30.1 * 3600 * NS), "KSFO": NOW_NS - 3600 * NS}
    result = daily(Source(daily=stale))
    assert result.findings[0].kind == "daily_verdict_absent"
    assert result.findings[0].metrics["subjects"] == "KNYC"
    fresh = {"KNYC": NOW_NS - int(29.9 * 3600 * NS)}
    assert daily(Source(daily=fresh)).outcome == "PASS"


def test_daily_verdict_absent_reports_lock_timeout_skips() -> None:
    newest = NOW_NS - int(31.5 * 3600 * NS)
    skips = [
        {"ts_ns": newest + 100 * NS, "slot": "05:30", "reason": "lock_timeout"},
        {"ts_ns": newest + 7 * 3600 * NS, "slot": "13:00", "reason": "lock_timeout"},
    ]
    result = daily(Source(daily={"KNYC": newest}, skips=skips))
    finding = result.findings[0]
    assert finding.severity == "CRITICAL"
    assert finding.metrics["last_skip_reason"] == "lock_timeout"
    assert finding.metrics["skips_since_last_verdict"] == "2"


def test_first_daily_skip_of_the_day_is_a_warning_not_a_fail() -> None:
    fresh = {"KNYC": NOW_NS - 6 * 3600 * NS}
    skips = [{"ts_ns": NOW_NS - 3600 * NS, "slot": "05:30", "reason": "lock_timeout"}]
    result = daily(Source(daily=fresh, skips=skips))
    assert [(f.kind, f.severity) for f in result.findings] == [
        ("daily_producer_skipped", "WARNING")
    ]


def test_daily_without_subjects_is_inconclusive_and_unreadable_is_unknown() -> None:
    assert daily(Source(daily={})).outcome == "INCONCLUSIVE"
    broken = Source()
    broken.newest_daily_verdict_ns = lambda: (_ for _ in ()).throw(OSError("eio"))  # type: ignore[method-assign]
    assert daily(broken).unknown_reasons == ("daily_verdicts_unreadable",)


# --------------------------------------------------------------------------- guards


def test_monitor_watch_never_names_or_assembles_a_state_changing_verb() -> None:
    from tests.unit.test_unit_health import verb_findings

    src = Path(monitor_watch.__file__).resolve().parent
    files = sorted(src.glob("monitor_watch*.py"))
    assert len(files) >= 7
    for path in files:
        bad, ok = verb_findings(path.read_text(encoding="utf-8"))
        assert bad == [] and ok == 0, f"{path.name}: {bad}"
        assert len(path.read_text(encoding="utf-8").splitlines()) < 800


def test_monitor_watch_modules_never_call_a_systemd_binary_or_the_permit() -> None:
    src = Path(monitor_watch.__file__).resolve().parent
    for path in sorted(src.glob("monitor_watch*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8")
        for word in ("systemctl", "permit", "orders_enabled", "ORDERS_ENABLED", "subprocess"):
            assert word not in text, f"{path.name} mentions {word}"
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not any(m.startswith(("subprocess", "nautilus_trader")) for m in imports)


def test_systemd_ts_helper_matches_the_parser() -> None:
    from breezy.runtime.monitor_watch_model import timestamp_or_zero

    assert timestamp_or_zero(systemd_ts(0)) == (True, NOW_NS)
    assert timestamp_or_zero("n/a") == (True, None)
    assert timestamp_or_zero("garbage") == (False, None)
