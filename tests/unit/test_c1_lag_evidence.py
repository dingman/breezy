"""RED-first tests: C1 lag evidence producer (F13 Phase A PIN-R6 input).

Synthetic ledgers only; no network, no live archive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

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


def test_runner_level_source_keys_are_present(tmp_path: Path) -> None:
    _write(tmp_path, "us-lamp-live", [_seen(_T0, lag=_MIN)])
    _write(tmp_path, "us-pfm-afos", [_seen(_T0, lag=0, station="KSFO")])
    ev = c1.build_evidence(tmp_path)
    assert ev["measured_days"]["lamp"] == 1
    assert ev["measured_days"]["pfm"] == 1
    assert ev["uncensored"]["lamp"] == 1
    assert ev["measured_days"]["mos"] == 0


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
