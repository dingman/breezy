"""RED-first tests: C1 lag evidence producer (F13 Phase A PIN-R6 input).

Synthetic ledgers only; no network, no live archive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.multisource_blend_stats import C1_LAG_SOURCES
from scripts.analysis import c1_lag_evidence as c1
from scripts.analysis import multisource_blend_pin_guards as guards

_MIN = 60 * 10**9
_DAY = 86_400 * 10**9
_T0 = 1_791_244_800 * 10**9  # 2026-10-06T00:00Z, a day boundary


def _seen(
    run: int, *, lag: int, late: bool = False, station: str = "ALL", **extra: Any
) -> dict[str, Any]:
    return {
        "kind": "seen",
        "station": station,
        "run_ts_ns": run,
        "available_ts_ns": run + lag,
        "first_seen_ns": run + lag + 5 * _MIN,
        "late": late,
        "clamped_to_miss": False,
        **extra,
    }


def _write(root: Path, key: str, events: list[dict[str, Any]]) -> None:
    d = root / key
    d.mkdir(parents=True)
    (d / "poll_ledger.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))


def test_lamp_uncensored_lag_is_available_minus_run(tmp_path: Path) -> None:
    _write(tmp_path, "us-lamp-live", [_seen(_T0, lag=7 * _MIN), _seen(_T0 + _DAY, lag=9 * _MIN)])
    ev = c1.build_evidence(tmp_path)
    assert sorted(ev["lag_samples_ns"]["lamp-mdl"]) == [7 * _MIN, 9 * _MIN]
    assert ev["uncensored"]["lamp-mdl"] == 2
    assert ev["measured_days"]["lamp-mdl"] == 2


def test_late_rows_are_censored_and_excluded(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "us-lamp-live",
        [_seen(_T0, lag=7 * _MIN), _seen(_T0 + _DAY, lag=99 * _MIN, late=True)],
    )
    ev = c1.build_evidence(tmp_path)
    assert ev["lag_samples_ns"]["lamp-mdl"] == [7 * _MIN]
    assert ev["censored"]["lamp-mdl"] == 1


def test_lamp_ext_and_repeat_revisions_are_not_double_counted(tmp_path: Path) -> None:
    rows = [
        _seen(_T0, lag=7 * _MIN),
        _seen(_T0, lag=7 * _MIN, station="ALLEXT"),
        _seen(_T0, lag=30 * _MIN),  # a later revision of the same run
    ]
    _write(tmp_path, "us-lamp-live", rows)
    assert c1.build_evidence(tmp_path)["lag_samples_ns"]["lamp-mdl"] == [7 * _MIN]


def test_pfm_lag_is_first_seen_minus_wmo_issuance(tmp_path: Path) -> None:
    # PFM available_ts IS the WMO header, so the lag must come from first_seen.
    _write(tmp_path, "us-pfm-afos", [_seen(_T0, lag=0, station="KNYC")])
    ev = c1.build_evidence(tmp_path)
    assert ev["lag_samples_ns"]["pfm"] == [5 * _MIN]


def test_source_without_ledger_is_reported_missing_not_invented(tmp_path: Path) -> None:
    _write(tmp_path, "us-lamp-live", [_seen(_T0, lag=_MIN)])
    ev = c1.build_evidence(tmp_path)
    for src in ("lav-iem", "mos-gfs", "obs"):
        assert src in ev["no_live_path"]
        assert src not in ev["lag_samples_ns"]
        assert ev["measured_days"][src] == 0


def test_measured_counts_use_pin_keys_not_level_aliases(tmp_path: Path) -> None:
    _write(tmp_path, "us-lamp-live", [_seen(_T0, lag=_MIN)])
    _write(tmp_path, "us-pfm-afos", [_seen(_T0, lag=0, station="KSFO")])
    ev = c1.build_evidence(tmp_path)
    assert ev["measured_days"]["lamp-mdl"] == 1
    assert ev["measured_days"]["pfm"] == 1
    assert ev["uncensored"]["lamp-mdl"] == 1
    assert ev["uncensored"]["pfm"] == 1
    assert ev["measured_days"]["mos-gfs"] == 0
    assert set(ev["measured_days"]) == set(C1_LAG_SOURCES)
    assert set(ev["uncensored"]) == set(C1_LAG_SOURCES)
    assert "lamp" not in ev["measured_days"]
    assert "lamp" not in ev["uncensored"]
    assert "mos" not in ev["measured_days"]
    assert "mos" not in ev["uncensored"]


def test_malformed_lines_are_counted_not_fatal(tmp_path: Path) -> None:
    _write(tmp_path, "us-lamp-live", [_seen(_T0, lag=_MIN)])
    with (tmp_path / "us-lamp-live" / "poll_ledger.jsonl").open("a") as fh:
        fh.write("{not json\n")
    ev = c1.build_evidence(tmp_path)
    assert ev["malformed_lines"] == 1
    assert ev["lag_samples_ns"]["lamp-mdl"] == [_MIN]


def test_output_satisfies_runner_pin_guard(tmp_path: Path) -> None:
    rows = [_seen(_T0 + i * _DAY, lag=(i + 1) * _MIN) for i in range(5)]
    _write(tmp_path, "us-lamp-live", rows)
    ev = c1.build_evidence(tmp_path)
    guards.check_pinned_lags_cover_c1({"lamp-mdl": 10 * _MIN}, ev["lag_samples_ns"])
    with pytest.raises(Exception, match="PIN-R6"):
        guards.check_pinned_lags_cover_c1({"lamp-mdl": 1 * _MIN}, ev["lag_samples_ns"])


def test_main_writes_report_atomically_even_when_insufficient(tmp_path: Path) -> None:
    _write(tmp_path, "us-lamp-live", [_seen(_T0, lag=_MIN)])
    out = tmp_path / "out" / "c1.json"
    rc = c1.main(["--archive-root", str(tmp_path), "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["ready"] is False
    assert data["lag_samples_ns"]["lamp-mdl"] == [_MIN]
    assert not list(out.parent.glob("*.tmp"))


def test_main_refuses_missing_archive_root(tmp_path: Path) -> None:
    out = tmp_path / "c1.json"
    assert c1.main(["--archive-root", str(tmp_path / "nope"), "--out", str(out)]) == 2
    assert not out.exists()


@pytest.mark.parametrize(
    ("source", "key"),
    [("lav-iem", "us-lav-iem-avail"), ("mos-gfs", "us-mos-gfs-avail"), ("obs", "us-obs-avail")],
)
def test_availability_only_legs_are_read_with_late_rows_censored(
    tmp_path: Path, source: str, key: str
) -> None:
    rows = [
        _seen(_T0, lag=40 * _MIN, station="KSFO"),
        _seen(_T0, lag=45 * _MIN, station="KMIA"),
        _seen(_T0 + _DAY, lag=50 * _MIN, station="KSFO"),
        _seen(_T0 + 2 * _DAY, lag=500 * _MIN, station="KSFO", late=True),
    ]
    _write(tmp_path, key, rows)
    ev = c1.build_evidence(tmp_path)
    assert sorted(ev["lag_samples_ns"][source]) == [40 * _MIN, 45 * _MIN, 50 * _MIN]
    assert ev["measured_days"][source] == 2
    assert ev["censored"][source] == 1
    assert source not in ev["no_live_path"]


def test_obs_non_routine_rows_are_excluded(tmp_path: Path) -> None:
    rows = [
        _seen(_T0, lag=7 * _MIN, station="KSFO", routine=True),
        _seen(_T0 + _DAY, lag=1 * _MIN, station="KSFO", routine=False),
    ]
    _write(tmp_path, "us-obs-avail", rows)
    assert c1.build_evidence(tmp_path)["lag_samples_ns"]["obs"] == [7 * _MIN]


def test_left_truncation_offsets_are_recorded_per_source(tmp_path: Path) -> None:
    trunc = c1.build_evidence(tmp_path)["left_truncation_ns"]
    assert trunc["lav-iem"] == 10 * _MIN
    assert trunc["mos-gfs"] == 120 * _MIN
    assert trunc["lamp-mdl"] == trunc["pfm"] == trunc["obs"] == 0


def test_live_and_left_truncation_keys_match_c1_lag_sources() -> None:
    assert set(c1._LIVE) == set(C1_LAG_SOURCES)
    assert set(c1._LEFT_TRUNCATION_NS) == set(C1_LAG_SOURCES)


def _stamped(
    run: int,
    *,
    fetched_at_ns: int,
    first_seen_ns: int,
    station: str = "KNYC",
    late: bool = False,
    kind: str = "seen",
) -> dict[str, Any]:
    """A ledger row carrying ``fetched_at_ns``, the poll time every real row has."""
    return {
        "kind": kind,
        "station": station,
        "run_ts_ns": run,
        "available_ts_ns": run,
        "first_seen_ns": first_seen_ns,
        "fetched_at_ns": fetched_at_ns,
        "late": late,
    }


def test_poll_gap_censors_seen_row_three_hours_after_previous_ledger_row(tmp_path: Path) -> None:
    """3 h after the previous ledger row, lag 2.5 h: censored_poll_gap, out of samples and p99."""
    previous_at = _T0
    kept = _stamped(_T0, fetched_at_ns=previous_at, first_seen_ns=previous_at + 10 * _MIN)
    recovery_at = previous_at + 3 * 60 * _MIN
    lag = int(2.5 * 60 * _MIN)
    recovery = _stamped(
        recovery_at - lag,
        fetched_at_ns=recovery_at,
        first_seen_ns=recovery_at,
        station="KSFO",
    )
    _write(tmp_path, "us-pfm-afos", [kept, recovery])
    ev = c1.build_evidence(tmp_path)
    assert ev["censored_poll_gap"]["pfm"] == 1
    assert ev["censored"]["pfm"] == 0
    assert set(ev["censored_poll_gap"]) == set(C1_LAG_SOURCES)
    assert ev["lag_samples_ns"]["pfm"] == [10 * _MIN]
    assert lag not in ev["lag_samples_ns"]["pfm"]
    assert ev["stats"]["pfm"]["p99_min"] == 10
    assert ev["schema"] == "c1_lag_evidence/v1"


def test_seen_row_fifty_five_minutes_after_previous_ledger_row_is_kept(tmp_path: Path) -> None:
    previous_at = _T0
    first = _stamped(_T0, fetched_at_ns=previous_at, first_seen_ns=previous_at + 10 * _MIN)
    seen_at = previous_at + 55 * _MIN
    lag = 12 * _MIN
    second = _stamped(seen_at - lag, fetched_at_ns=seen_at, first_seen_ns=seen_at, station="KSFO")
    _write(tmp_path, "us-pfm-afos", [first, second])
    ev = c1.build_evidence(tmp_path)
    assert ev["censored_poll_gap"]["pfm"] == 0
    assert ev["censored"]["pfm"] == 0
    assert sorted(ev["lag_samples_ns"]["pfm"]) == [10 * _MIN, lag]


def test_poll_gap_uses_the_previous_ledger_row_not_the_previous_seen_sample(
    tmp_path: Path,
) -> None:
    """A miss 20 min earlier keeps the sample, even if the previous ``seen`` was 3 h ago."""
    previous_at = _T0
    first = _stamped(_T0, fetched_at_ns=previous_at, first_seen_ns=previous_at + 10 * _MIN)
    miss_at = previous_at + 160 * _MIN
    miss = _stamped(_T0, fetched_at_ns=miss_at, first_seen_ns=miss_at, station="KNYC", kind="miss")
    seen_at = miss_at + 20 * _MIN
    lag = int(2.5 * 60 * _MIN)
    second = _stamped(seen_at - lag, fetched_at_ns=seen_at, first_seen_ns=seen_at, station="KSFO")
    _write(tmp_path, "us-pfm-afos", [first, miss, second])
    ev = c1.build_evidence(tmp_path)
    assert ev["censored_poll_gap"]["pfm"] == 0
    assert sorted(ev["lag_samples_ns"]["pfm"]) == [10 * _MIN, lag]


def test_poll_gap_censors_every_station_written_in_the_recovery_firing(tmp_path: Path) -> None:
    """Sibling stations 4 s apart share the firing's predecessor, not each other."""
    previous_at = _T0
    previous = _stamped(
        _T0, fetched_at_ns=previous_at, first_seen_ns=previous_at + 10 * _MIN, station="KNYC"
    )
    recovery_at = previous_at + 3 * 60 * _MIN
    lag = int(2.5 * 60 * _MIN)
    first = _stamped(
        recovery_at - lag, fetched_at_ns=recovery_at, first_seen_ns=recovery_at, station="KLAX"
    )
    second_at = recovery_at + 4 * 10**9
    second = _stamped(
        second_at - lag, fetched_at_ns=second_at, first_seen_ns=second_at, station="KSFO"
    )
    _write(tmp_path, "us-pfm-afos", [previous, first, second])
    ev = c1.build_evidence(tmp_path)
    assert ev["censored_poll_gap"]["pfm"] == 2
    assert ev["censored"]["pfm"] == 0
    assert ev["lag_samples_ns"]["pfm"] == [10 * _MIN]
    assert lag not in ev["lag_samples_ns"]["pfm"]


def test_first_ledger_row_has_no_predecessor_and_is_kept(tmp_path: Path) -> None:
    lag = int(2.5 * 60 * _MIN)
    seen_at = _T0 + lag
    only = _stamped(_T0, fetched_at_ns=seen_at, first_seen_ns=seen_at, station="KNYC")
    _write(tmp_path, "us-pfm-afos", [only])
    ev = c1.build_evidence(tmp_path)
    assert ev["censored_poll_gap"]["pfm"] == 0
    assert ev["lag_samples_ns"]["pfm"] == [lag]


def test_max_poll_gap_keys_equal_c1_lag_sources() -> None:
    """Parity: the cadence table is keyed by the pin sources, pfm max gap is 95 min."""
    assert set(c1.MAX_POLL_GAP_NS) == set(C1_LAG_SOURCES)
    expected_min = {
        "lamp-mdl": 104,  # 15:31Z → 17:10Z = 99 min, plus 5
        "lav-iem": 55,  # 16:20Z → 17:10Z = 50 min, plus 5
        "pfm": 95,  # 15:40Z → 17:10Z = 90 min, plus 5
        "mos-gfs": 65,  # 16:15Z → 17:15Z = 60 min, plus 5
        "obs": 55,  # 16:20Z → 17:10Z = 50 min, plus 5
    }
    assert {key: value // _MIN for key, value in c1.MAX_POLL_GAP_NS.items()} == expected_min
