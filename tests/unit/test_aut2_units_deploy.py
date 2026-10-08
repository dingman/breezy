"""AUT-2 r7 WP6 / section 3.10: the label unit fixtures, its bwrap row and the tally timer move.

The label unit is a FIXTURE under ``tests/fixtures/aut2_units/`` (AUT-1 stage-3 precedent: it is
promoted into ``deploy/systemd/`` only once AUT-6's notifier row and ``deliver_with_proof`` exist).
Nothing here installs, enables or starts a unit.
"""

from __future__ import annotations

import datetime as dt
import re
import shlex
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from breezy.analysis.labeling import constants as c
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, BwrapRow
from breezy.runtime.autonomy_sandbox.unit_lint import (
    WRAPPER_PATH,
    lint_units,
    parse_unit,
    start_phase_bound_s,
)

_REPO = Path(__file__).resolve().parents[2]
FIXTURES = _REPO / "tests" / "fixtures" / "aut2_units"
DEPLOY = _REPO / "deploy" / "systemd"
#: The WP6 versions of the score-live-trials unit pair, staged until promotion: the deployed pair is
#: installed by symlink, so an edit to it goes live on the next daemon-reload.
PROMOTE = FIXTURES / "promote"
LABEL = "breezy-label-outcomes"
SCORE = "breezy-score-live-trials"
STAND_IN = BwrapRow(
    name="breezy-autonomy-failed",
    owner_plan="AUT-6 (stand-in)",
    units=frozenset({"breezy-autonomy-failed@"}),
    binds=("cache/autonomy_failed",),
    entry_modules=("x",),
    resolves_dns=True,
    network="egress",
)
WINDOW_START, WINDOW_END = dt.time(16, 30), dt.time(17, 10)
DAY = dt.date(2026, 10, 7)


def _table(*extra: BwrapRow) -> Mapping[str, BwrapRow]:
    return MappingProxyType({**AUTONOMY_BWRAP_TABLE, **{row.name: row for row in extra}})


def _text(directory: Path, name: str, kind: str) -> str:
    return (directory / f"{name}.{kind}").read_text()


def _values(text: str, section: str, key: str) -> list[str]:
    return parse_unit(text).values(section, key)


def _one(text: str, section: str, key: str) -> str:
    (value,) = _values(text, section, key)
    return value


def _calendar_times(timer_text: str) -> list[dt.time]:
    times: list[dt.time] = []
    for line in _values(timer_text, "Timer", "OnCalendar"):
        found = re.fullmatch(r"\*-\*-\* (\d\d):(\d\d):(\d\d) UTC", line)
        assert found, line
        times.append(dt.time(int(found[1]), int(found[2]), int(found[3])))
    return times


def _seconds(text: str) -> float:
    from breezy.analysis.labeling.slot_guard import parse_systemd_span_s

    return parse_systemd_span_s(text)


def _accuracy_s(timer_text: str) -> float:
    values = _values(timer_text, "Timer", "AccuracySec")
    return _seconds(values[0]) if values else 60.0  # systemd's default AccuracySec


def _stop_s(service_text: str) -> float:
    values = _values(service_text, "Service", "TimeoutStopSec")
    return _seconds(values[0]) if values else float(c.SYSTEMD_DEFAULT_TIMEOUT_STOP_S)


def _worst_end(start: dt.time, timer: str, service: str, *, flock_wait_s: float = 0) -> dt.datetime:
    """``start + AccuracySec + flock wait + TimeoutStartSec + TimeoutStopSec``, everything read from
    the unit texts (P7, V6)."""
    begin = dt.datetime.combine(DAY, start, tzinfo=dt.UTC)
    return begin + dt.timedelta(
        seconds=_accuracy_s(timer)
        + flock_wait_s
        + _seconds(_one(service, "Service", "TimeoutStartSec"))
        + _stop_s(service)
    )


def _meets_window(start: dt.datetime, end: dt.datetime) -> bool:
    lo = dt.datetime.combine(DAY, WINDOW_START, tzinfo=dt.UTC)
    hi = dt.datetime.combine(DAY, WINDOW_END, tzinfo=dt.UTC)
    return start < hi and end >= lo


# -- the fixture set and lint ----------------------------------------------------------------------


def test_fixture_set_is_exactly_the_label_pair_and_the_staged_promote_directory() -> None:
    assert sorted(p.name for p in FIXTURES.iterdir()) == [
        f"{LABEL}.service",
        f"{LABEL}.timer",
        "promote",
    ]
    assert sorted(p.name for p in PROMOTE.iterdir()) == [
        "README.md",
        f"{SCORE}.service",
        f"{SCORE}.timer",
    ]


def test_label_unit_lints_clean_against_a_standin_notifier_row() -> None:
    assert lint_units(FIXTURES, _table(STAND_IN)) == ()


def test_label_unit_fails_lint_only_on_aut6_onfailure_scope() -> None:
    errors = lint_units(FIXTURES, AUTONOMY_BWRAP_TABLE)

    # AUT-6 WP1 (X-3) lists ``breezy-autonomy-failed@`` in the redeliver row, so the OnFailure
    # target is in lint scope and the scope error is gone. Promotion still waits for the notifier
    # unit itself (AUT-6 WP4/WP7), which the lint cannot see.
    assert [(e.unit, e.rule) for e in errors] == []
    assert (
        "breezy-autonomy-failed@" in AUTONOMY_BWRAP_TABLE["breezy-autonomy-alert-redeliver"].units
    )


def test_the_unit_text_already_carries_the_autonomy_failed_onfailure() -> None:
    assert _values(_text(FIXTURES, LABEL, "service"), "Unit", "OnFailure") == [
        "breezy-autonomy-failed@%n.service"
    ]


def test_execstart_runs_through_the_bwrap_wrapper_with_the_label_run_module() -> None:
    line = _one(_text(FIXTURES, LABEL, "service"), "Service", "ExecStart")
    tokens = shlex.split(line)

    assert tokens[:2] == ["/usr/bin/timeout", "-k"] and WRAPPER_PATH in tokens
    assert tokens[tokens.index(WRAPPER_PATH) + 1] == LABEL
    assert tokens[tokens.index(WRAPPER_PATH) + 2 :][:3] == [
        "/home/jon/breezy/.venv/bin/python3",
        "-I",
        "-m",
    ]
    assert tokens[-1] == "breezy.analysis.labeling.label_run"
    assert "flock" not in line  # the studies lock is taken in process (E7_STUDIES_LOCK)


def test_label_unit_has_no_wrapper_script_in_front_of_the_sandbox() -> None:
    assert not any(p.suffix == ".sh" for p in FIXTURES.iterdir())


# -- the bwrap row (E-15) --------------------------------------------------------------------------


def test_label_row_is_owned_by_aut2_with_declared_egress_and_the_studies_lock() -> None:
    row = AUTONOMY_BWRAP_TABLE[LABEL]

    assert row.owner_plan == "AUT-2"
    assert row.units == frozenset({f"{LABEL}.service"})
    assert row.resolves_dns is True and row.network == "egress"
    assert row.studies_lock is True and row.exceptions == frozenset({"E7_STUDIES_LOCK"})
    assert row.entry_modules == ("breezy.analysis.labeling.label_run",)
    assert row.bus_reads == () and row.host_proc is False and row.credential_names == ()


def test_label_row_binds_exactly_the_label_writers_and_the_snapshot_cache() -> None:
    row = AUTONOMY_BWRAP_TABLE[LABEL]

    assert set(row.binds) == {
        "derived/labels",
        "derived/labels_canary",
        "derived/label_outcomes",
        "derived/canary",
        "derived/verdicts",
        "evidence/aut2",
        "evidence/aut2_live_proof",
        "cache/label_run_snapshot",
    }
    assert not any("alerts" in b or b.startswith("state") for b in row.binds)


def test_the_pre_install_line_creates_exactly_the_row_binds() -> None:
    text = _text(FIXTURES, LABEL, "service")
    install = next(p for p in _values(text, "Service", "ExecStartPre") if "/usr/bin/install" in p)
    made = {
        t.removeprefix("%h/.local/share/breezy/")
        for t in shlex.split(install)
        if t.startswith("%h/")
    }

    assert made == set(AUTONOMY_BWRAP_TABLE[LABEL].binds)


# -- Q1 / V6 / P7 deploy tests ---------------------------------------------------------------------


def test_no_aut2_oneshot_sets_runtime_max_sec() -> None:
    for kind in ("service", "timer"):
        assert "RuntimeMaxSec" not in _text(FIXTURES, LABEL, kind)


def test_the_runtime_max_sec_scan_has_a_positive_control() -> None:
    planted = _text(FIXTURES, LABEL, "service") + "\nRuntimeMaxSec=600\n"

    assert _values(planted, "Service", "RuntimeMaxSec") == ["600"]
    assert _values(_text(FIXTURES, LABEL, "service"), "Service", "RuntimeMaxSec") == []


def test_aut2_oneshots_set_timeout_start_sec_equal_to_constants() -> None:
    service = _text(FIXTURES, LABEL, "service")

    assert _seconds(_one(service, "Service", "TimeoutStartSec")) == c.LABEL_TIMEOUT_START_S == 1800
    pre = start_phase_bound_s(FIXTURES / f"{LABEL}.service")
    k_plus_t = sum(int(t) for t in shlex.split(_one(service, "Service", "ExecStart"))[2:4])
    assert pre + k_plus_t == c.LABEL_TIMEOUT_START_S  # E-9: P + X <= S, exactly on the bound


def test_aut2_oneshots_set_timeout_stop_sec_5() -> None:
    service = _text(FIXTURES, LABEL, "service")

    assert _one(service, "Service", "TimeoutStopSec") == "5" and c.TIMEOUT_STOP_S == 5
    planted = service.replace("TimeoutStopSec=5\n", "")
    assert _values(planted, "Service", "TimeoutStopSec") == []  # the scan would fail on this


def test_aut2_timers_accuracy_1s_no_random_delay_not_persistent() -> None:
    timer = _text(FIXTURES, LABEL, "timer")

    assert _values(timer, "Timer", "AccuracySec") == ["1s"]
    assert _values(timer, "Timer", "RandomizedDelaySec") == ["0"]
    assert _values(timer, "Timer", "Persistent") == ["false"]
    planted = timer.replace("Persistent=false", "Persistent=true")
    assert _values(planted, "Timer", "Persistent") == ["true"]  # positive control


def test_label_timer_fires_at_1415_and_0500_utc() -> None:
    assert _calendar_times(_text(FIXTURES, LABEL, "timer")) == [dt.time(14, 15), dt.time(5, 0)]


def test_label_slots_clear_launch_window() -> None:
    timer, service = _text(FIXTURES, LABEL, "timer"), _text(FIXTURES, LABEL, "service")

    for start in _calendar_times(timer):
        begin = dt.datetime.combine(DAY, start, tzinfo=dt.UTC)
        end = _worst_end(start, timer, service, flock_wait_s=c.LABEL_FLOCK_WAIT_S)
        assert not _meets_window(begin, end), start
    assert (
        _worst_end(dt.time(14, 15), timer, service, flock_wait_s=600).strftime("%H:%M:%S")
        == "14:55:06"
    )
    assert (
        _worst_end(dt.time(5, 0), timer, service, flock_wait_s=600).strftime("%H:%M:%S")
        == "05:40:06"
    )


def test_window_arithmetic_reads_accuracy_from_timer_file() -> None:
    timer, service = _text(FIXTURES, LABEL, "timer"), _text(FIXTURES, LABEL, "service")
    slower = timer.replace("AccuracySec=1s", "AccuracySec=2h")

    assert _worst_end(dt.time(14, 15), slower, service) > _worst_end(
        dt.time(14, 15), timer, service
    )
    begin = dt.datetime.combine(DAY, dt.time(14, 15), tzinfo=dt.UTC)
    # a drifted AccuracySec in the file moves the worst end into the launch window and is caught
    assert _meets_window(begin, _worst_end(dt.time(14, 15), slower, service, flock_wait_s=600))
    assert _accuracy_s(slower) == 7200.0


def test_window_arithmetic_includes_timeout_stop_sec() -> None:
    timer, service = _text(FIXTURES, LABEL, "timer"), _text(FIXTURES, LABEL, "service")
    no_stop = service.replace("TimeoutStopSec=5\n", "")

    assert (
        _worst_end(dt.time(14, 15), timer, no_stop) - _worst_end(dt.time(14, 15), timer, service)
    ).total_seconds() == c.SYSTEMD_DEFAULT_TIMEOUT_STOP_S - 5


def test_score_live_trials_tally_releases_before_label_flock_wait_expires() -> None:
    timer, service = _text(PROMOTE, SCORE, "timer"), _text(PROMOTE, SCORE, "service")
    (tally,) = _calendar_times(timer)

    end = _worst_end(tally, timer, service)

    assert tally == dt.time(13, 55)
    assert end.strftime("%H:%M:%S") == "14:17:30"
    label_expiry = dt.datetime.combine(DAY, dt.time(14, 15), tzinfo=dt.UTC) + dt.timedelta(
        seconds=c.LABEL_FLOCK_WAIT_S
    )
    assert end <= label_expiry  # 14:17:30 <= 14:25:00


def test_score_live_trials_slot_clears_launch_window() -> None:
    timer, service = _text(PROMOTE, SCORE, "timer"), _text(PROMOTE, SCORE, "service")
    (tally,) = _calendar_times(timer)

    assert not _meets_window(
        dt.datetime.combine(DAY, tally, tzinfo=dt.UTC), _worst_end(tally, timer, service)
    )
    assert _accuracy_s(timer) == 60.0 and _values(timer, "Timer", "Persistent") == ["true"]


def _ticks_of(directory: Path, *, skip: set[str] | None = None) -> dict[str, set[dt.time]]:
    found: dict[str, set[dt.time]] = {}
    for path in sorted(directory.glob("*.timer")):
        if skip and path.name in skip:
            continue
        found[path.name] = set()
        for line in _values(path.read_text(), "Timer", "OnCalendar"):
            hit = re.fullmatch(r"\*-\*-\* (\d\d):(\d\d):(\d\d) UTC", line)
            if hit:
                found[path.name].add(dt.time(int(hit[1]), int(hit[2]), int(hit[3])))
    return found


def test_the_staged_set_shares_no_tick_with_any_deployed_timer_it_does_not_replace() -> None:
    """The label timer (14:15, 05:00) and the staged tally timer (13:55) must each be free in the
    deployed schedule once the deployed tally timer, which the staged one replaces, is set aside."""
    staged = {t for ticks in _ticks_of(FIXTURES).values() for t in ticks} | {dt.time(13, 55)}
    deployed = _ticks_of(DEPLOY, skip={f"{SCORE}.timer"})

    assert [name for name, ticks in deployed.items() if ticks & staged] == []


def test_the_staged_tally_timer_replaces_exactly_the_deployed_1415_tick() -> None:
    assert _ticks_of(DEPLOY)[f"{SCORE}.timer"] == {dt.time(14, 15)}
    assert _ticks_of(PROMOTE)[f"{SCORE}.timer"] == {dt.time(13, 55)}


# -- the installed units stay untouched until promotion ------------------------------------------


def test_deployed_score_live_trials_pair_is_the_pre_aut2_version() -> None:
    """Installed by symlink: an edit goes live at the next daemon-reload, before the label unit
    exists. The WP6 versions live only in the promote fixture directory."""
    service = _text(DEPLOY, SCORE, "service")
    timer = _text(DEPLOY, SCORE, "timer")

    assert _values(service, "Service", "ExecCondition") == []
    assert "slot-guard" not in service and "slot-guard" not in timer
    assert _values(timer, "Timer", "OnCalendar") == ["*-*-* 14:15:00 UTC"]


def test_the_promote_fixtures_are_the_wp6_versions() -> None:
    service = _text(PROMOTE, SCORE, "service")
    timer = _text(PROMOTE, SCORE, "timer")

    assert _values(service, "Service", "ExecCondition") == [
        "/home/jon/breezy/deploy/systemd/slot-guard-run.sh --unit breezy-score-live-trials"
    ]
    assert _values(service, "Unit", "OnFailure") == ["breezy-study-failed@%n.service"]
    assert _values(timer, "Timer", "OnCalendar") == ["*-*-* 13:55:00 UTC"]
    assert _values(timer, "Timer", "Persistent") == ["true"]


def test_no_deployed_file_references_slot_guard_run_until_promotion() -> None:
    offenders = [
        path.name
        for path in sorted(DEPLOY.rglob("*"))
        if path.is_file()
        and path.name != "slot-guard-run.sh"
        and "slot-guard-run" in _safe_text(path)
    ]
    assert offenders == []


def _safe_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


# -- WP6-size is deferred ---------------------------------------------------------------------


def test_label_unit_memory_lines_are_deferred_to_the_measured_sizing_commit() -> None:
    """The coordinator measures the label run's own cgroup peak and adds ``MemoryHigh``/
    ``MemoryMax`` with the evidence artefact in one reviewed commit (plan WP6, Q1/V9)."""
    service = _text(FIXTURES, LABEL, "service")

    assert "WP6-SIZE" in service
    assert _values(service, "Service", "MemoryMax") == []
    assert _values(service, "Service", "MemoryHigh") == []
    assert _values(service, "Service", "Slice") == ["breezy-studies.slice"]
