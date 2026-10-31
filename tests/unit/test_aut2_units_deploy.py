"""AUT-2 r7 WP6 / section 3.10 and OPS-4 S1: the label unit, its bwrap row and the tally timer move.

The label unit pair and the 13:55 scorer pair live in ``deploy/systemd/`` (OPS-4 promoted them out
of the retired AUT-2 unit fixture directory). Nothing here installs, enables or starts a unit:
deployed units are symlinks, so activation is a separate host step.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shlex
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from breezy.analysis.labeling import constants as c
from breezy.analysis.labeling.memory_gate import MemorySizing, size_from_peak
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, BwrapRow
from breezy.runtime.autonomy_sandbox.unit_lint import (
    WRAPPER_PATH,
    lint_units,
    parse_unit,
    start_phase_bound_s,
)
from tests.support.systemd_size import parse_systemd_size

_REPO = Path(__file__).resolve().parents[2]
RETIRED_FIXTURES = _REPO / "tests" / "fixtures" / "aut2_units"  # retired by OPS-4 S1; stays absent
DEPLOY = _REPO / "deploy" / "systemd"
EVIDENCE = _REPO / "docs" / "evidence"
PEAK_ARTEFACT_GLOB = "OPS4_S1_label_run_peak_*.json"
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


def test_label_pair_is_deployed_and_the_fixture_directory_is_gone() -> None:
    assert (DEPLOY / f"{LABEL}.service").is_file() and (DEPLOY / f"{LABEL}.timer").is_file()
    assert not RETIRED_FIXTURES.exists()  # every reader points at deploy/systemd/ (OPS-4 section 3)


def test_label_unit_lints_clean_against_a_standin_notifier_row() -> None:
    errors = lint_units(DEPLOY, _table(STAND_IN))

    assert [e for e in errors if e.unit.startswith(LABEL)] == []


def test_label_unit_fails_real_tree_lint_only_on_aut6_onfailure_scope() -> None:
    errors = lint_units(DEPLOY, AUTONOMY_BWRAP_TABLE)

    assert [(e.unit, e.rule) for e in errors if e.unit.startswith(LABEL)] == [
        (f"{LABEL}.service", "onfailure_scope")
    ]


def test_the_unit_text_already_carries_the_autonomy_failed_onfailure() -> None:
    assert _values(_text(DEPLOY, LABEL, "service"), "Unit", "OnFailure") == [
        "breezy-autonomy-failed@%n.service"
    ]


def test_execstart_runs_through_the_bwrap_wrapper_with_the_label_run_module() -> None:
    line = _one(_text(DEPLOY, LABEL, "service"), "Service", "ExecStart")
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
    service = _text(DEPLOY, LABEL, "service")

    assert not any(".sh" in token for token in shlex.split(_one(service, "Service", "ExecStart")))


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
        "evidence/alerts",
        "cache/label_run_snapshot",
    }
    assert not any(b.startswith("state") for b in row.binds)


def test_the_pre_install_line_creates_exactly_the_row_binds() -> None:
    text = _text(DEPLOY, LABEL, "service")
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
        assert "RuntimeMaxSec" not in _text(DEPLOY, LABEL, kind)


def test_the_runtime_max_sec_scan_has_a_positive_control() -> None:
    planted = _text(DEPLOY, LABEL, "service") + "\nRuntimeMaxSec=600\n"

    assert _values(planted, "Service", "RuntimeMaxSec") == ["600"]
    assert _values(_text(DEPLOY, LABEL, "service"), "Service", "RuntimeMaxSec") == []


def test_aut2_oneshots_set_timeout_start_sec_equal_to_constants() -> None:
    service = _text(DEPLOY, LABEL, "service")

    assert _seconds(_one(service, "Service", "TimeoutStartSec")) == c.LABEL_TIMEOUT_START_S == 1800
    pre = start_phase_bound_s(DEPLOY / f"{LABEL}.service")
    k_plus_t = sum(int(t) for t in shlex.split(_one(service, "Service", "ExecStart"))[2:4])
    assert pre + k_plus_t == c.LABEL_TIMEOUT_START_S  # E-9: P + X <= S, exactly on the bound


def test_aut2_oneshots_set_timeout_stop_sec_5() -> None:
    service = _text(DEPLOY, LABEL, "service")

    assert _one(service, "Service", "TimeoutStopSec") == "5" and c.TIMEOUT_STOP_S == 5
    planted = service.replace("TimeoutStopSec=5\n", "")
    assert _values(planted, "Service", "TimeoutStopSec") == []  # the scan would fail on this


def test_aut2_timers_accuracy_1s_no_random_delay_not_persistent() -> None:
    timer = _text(DEPLOY, LABEL, "timer")

    assert _values(timer, "Timer", "AccuracySec") == ["1s"]
    assert _values(timer, "Timer", "RandomizedDelaySec") == ["0"]
    assert _values(timer, "Timer", "Persistent") == ["false"]
    planted = timer.replace("Persistent=false", "Persistent=true")
    assert _values(planted, "Timer", "Persistent") == ["true"]  # positive control


def test_label_timer_fires_at_1415_and_0500_utc() -> None:
    assert _calendar_times(_text(DEPLOY, LABEL, "timer")) == [dt.time(14, 15), dt.time(5, 0)]


def test_label_slots_clear_launch_window() -> None:
    timer, service = _text(DEPLOY, LABEL, "timer"), _text(DEPLOY, LABEL, "service")

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
    timer, service = _text(DEPLOY, LABEL, "timer"), _text(DEPLOY, LABEL, "service")
    slower = timer.replace("AccuracySec=1s", "AccuracySec=2h")

    assert _worst_end(dt.time(14, 15), slower, service) > _worst_end(
        dt.time(14, 15), timer, service
    )
    begin = dt.datetime.combine(DAY, dt.time(14, 15), tzinfo=dt.UTC)
    # a drifted AccuracySec in the file moves the worst end into the launch window and is caught
    assert _meets_window(begin, _worst_end(dt.time(14, 15), slower, service, flock_wait_s=600))
    assert _accuracy_s(slower) == 7200.0


def test_window_arithmetic_includes_timeout_stop_sec() -> None:
    timer, service = _text(DEPLOY, LABEL, "timer"), _text(DEPLOY, LABEL, "service")
    no_stop = service.replace("TimeoutStopSec=5\n", "")

    assert (
        _worst_end(dt.time(14, 15), timer, no_stop) - _worst_end(dt.time(14, 15), timer, service)
    ).total_seconds() == c.SYSTEMD_DEFAULT_TIMEOUT_STOP_S - 5


def test_score_live_trials_tally_releases_before_label_flock_wait_expires() -> None:
    timer, service = _text(DEPLOY, SCORE, "timer"), _text(DEPLOY, SCORE, "service")
    (tally,) = _calendar_times(timer)

    end = _worst_end(tally, timer, service)

    assert tally == dt.time(13, 55)
    assert end.strftime("%H:%M:%S") == "14:17:30"
    label_expiry = dt.datetime.combine(DAY, dt.time(14, 15), tzinfo=dt.UTC) + dt.timedelta(
        seconds=c.LABEL_FLOCK_WAIT_S
    )
    assert end <= label_expiry  # 14:17:30 <= 14:25:00


def test_score_live_trials_slot_clears_launch_window() -> None:
    timer, service = _text(DEPLOY, SCORE, "timer"), _text(DEPLOY, SCORE, "service")
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


def test_the_label_and_tally_timers_share_no_tick_with_any_other_deployed_timer() -> None:
    """The label timer (14:15, 05:00) and the tally timer (13:55) own their ticks outright."""
    ticks = _ticks_of(DEPLOY)
    mine = {f"{LABEL}.timer", f"{SCORE}.timer"}
    owned = ticks[f"{LABEL}.timer"] | ticks[f"{SCORE}.timer"]

    assert [name for name, t in ticks.items() if name not in mine and t & owned] == []


def test_the_deployed_tally_timer_owns_1355_and_the_label_timer_owns_1415() -> None:
    ticks = _ticks_of(DEPLOY)

    assert ticks[f"{SCORE}.timer"] == {dt.time(13, 55)}
    assert ticks[f"{LABEL}.timer"] == {dt.time(14, 15), dt.time(5, 0)}


# -- the promoted tally pair ----------------------------------------------------------------------


def test_deployed_score_live_trials_pair_is_the_promoted_wp6_version() -> None:
    service = _text(DEPLOY, SCORE, "service")
    timer = _text(DEPLOY, SCORE, "timer")

    assert _values(service, "Service", "ExecCondition") == [
        "/home/jon/breezy/deploy/systemd/slot-guard-run.sh --unit breezy-score-live-trials"
    ]
    assert _values(service, "Unit", "OnFailure") == ["breezy-study-failed@%n.service"]
    assert _values(service, "Service", "MemoryHigh") == ["4G"]
    assert _values(service, "Service", "MemoryMax") == ["5G"]
    assert _values(timer, "Timer", "OnCalendar") == ["*-*-* 13:55:00 UTC"]
    assert _values(timer, "Timer", "Persistent") == ["true"]
    assert "14:15" not in "\n".join(
        ln for ln in service.splitlines() + timer.splitlines() if not ln.startswith("#")
    )


def test_the_scorer_service_is_the_only_referrer_of_slot_guard_run() -> None:
    offenders = [
        path.name
        for path in sorted(DEPLOY.rglob("*"))
        if path.is_file()
        and path.name != "slot-guard-run.sh"
        and "slot-guard-run" in _safe_text(path)
    ]
    assert offenders == [f"{SCORE}.service"]


def test_the_scorer_service_names_slot_guard_run_in_exactly_one_line() -> None:
    lines = [ln for ln in _text(DEPLOY, SCORE, "service").splitlines() if "slot-guard-run" in ln]

    assert len(lines) == 1 and lines[0].startswith("ExecCondition=")


def _safe_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


# -- the measured label sizing (OPS-4 S0 artefact; plan D1, D12, D16, D17) -------------------------


def _sole_peak_artefact(directory: Path) -> Path:
    """The ONE committed S0 artefact: zero or several matches both fail (a re-run replaces it)."""
    matches = sorted(directory.glob(PEAK_ARTEFACT_GLOB))
    assert len(matches) == 1, f"expected exactly one {PEAK_ARTEFACT_GLOB}, found {matches}"
    return matches[0]


def _artefact() -> dict[str, object]:
    artefact: dict[str, object] = json.loads(
        _sole_peak_artefact(EVIDENCE).read_text(encoding="utf-8")
    )
    return artefact


def _peak_bytes() -> int:
    peak = _artefact()["memory_peak_bytes"]
    assert isinstance(peak, int) and not isinstance(peak, bool) and peak > 0
    return peak


def _declared_limits(service: str) -> tuple[int, int]:
    high = int(parse_systemd_size(_one(service, "Service", "MemoryHigh")))
    return high, int(parse_systemd_size(_one(service, "Service", "MemoryMax")))


def _memory_max_satisfies_measured_ceiling(declared_bytes: int, peak_bytes: int) -> bool:
    """D1/D12: MemoryMax is exactly ``size_from_peak(peak)`` and inside the 4 GiB label gate."""
    sizing = size_from_peak(peak_bytes)
    return (
        isinstance(sizing, MemorySizing)
        and declared_bytes == sizing.memory_max_bytes
        and declared_bytes <= c.LABEL_MEMORY_TARGET_GIB * 1024**3
    )


def test_exactly_one_peak_artefact_is_committed_and_zero_or_two_fail(tmp_path: Path) -> None:
    assert _sole_peak_artefact(EVIDENCE).name.startswith("OPS4_S1_label_run_peak_")
    with pytest.raises(AssertionError):  # positive control: none
        _sole_peak_artefact(tmp_path)
    (tmp_path / "OPS4_S1_label_run_peak_1.json").write_text("{}")
    assert _sole_peak_artefact(tmp_path).name == "OPS4_S1_label_run_peak_1.json"
    (tmp_path / "OPS4_S1_label_run_peak_2.json").write_text("{}")
    with pytest.raises(AssertionError):  # positive control: two
        _sole_peak_artefact(tmp_path)


def test_the_committed_peak_artefact_is_a_measured_label_run_with_a_wall_time() -> None:
    body = _artefact()
    peak = body["memory_peak_bytes"]

    assert body["schema"] == "aut2_memory_peak/v1"
    assert isinstance(peak, int) and not isinstance(peak, bool) and peak > 0
    assert isinstance(body["git_sha"], str) and body["git_sha"] not in ("", "unknown")
    wall_ns = body["wall_time_ns"]
    assert isinstance(wall_ns, int) and not isinstance(wall_ns, bool) and wall_ns > 0
    wall = wall_ns / 1e9
    # D16: the first-measurement bound (RuntimeMaxSec=1800) is the unit's TimeoutStartSec
    timeout = _seconds(_one(_text(DEPLOY, LABEL, "service"), "Service", "TimeoutStartSec"))
    assert timeout >= 1.75 * wall


def test_label_unit_memory_max_from_measured_label_peak() -> None:
    sizing = size_from_peak(_peak_bytes())
    service = _text(DEPLOY, LABEL, "service")
    declared_high, declared_max = _declared_limits(service)

    assert isinstance(sizing, MemorySizing)  # D1: not SizingExceedsCap
    assert _memory_max_satisfies_measured_ceiling(declared_max, _peak_bytes())
    assert declared_high == sizing.memory_high_bytes
    assert declared_max == 1024**3 and declared_high == 966367641


def test_a_planted_too_low_memory_max_fails_the_measured_ceiling_check() -> None:
    service = _text(DEPLOY, LABEL, "service")
    planted = re.sub(r"(?m)^MemoryMax=.*$", "MemoryMax=256M", service)
    _high, planted_max = _declared_limits(planted)

    assert planted_max == 256 * 1024**2
    assert _memory_max_satisfies_measured_ceiling(_declared_limits(service)[1], _peak_bytes())
    assert not _memory_max_satisfies_measured_ceiling(planted_max, _peak_bytes())  # the real check


def test_label_unit_keeps_the_studies_slice_and_carries_no_stale_markers() -> None:
    service = _text(DEPLOY, LABEL, "service")

    assert _values(service, "Service", "Slice") == ["breezy-studies.slice"]
    assert "WP6-SIZE" not in service
    assert "slot-guard-run" not in service  # D18
