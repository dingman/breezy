"""Fixture tests for Card E. No network: dry-run reads scratch files only."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import socket
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts" / "analysis").as_posix())

import card_e_cli_vs_twc as card_e  # type: ignore[import-not-found]

MIA_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cli_equivalence" / "MIA_20260824_archive.txt"
DAY = dt.date(2026, 8, 24)
P0 = 0.01
ALPHA = 0.025


def _market(
    event: str,
    expiration: object,
    *,
    status: str = "finalized",
    result: str = "no",
    strike_type: str = "less",
    floor_strike: float | None = None,
    cap_strike: float | None = 99,
    close_time: str = "2026-08-25T04:59:00Z",
) -> dict[str, object]:
    return {
        "station": "MIA",
        "side": "high",
        "event_ticker": event,
        "expiration_value": expiration,
        "status": status,
        "result": result,
        "strike_type": strike_type,
        "floor_strike": floor_strike,
        "cap_strike": cap_strike,
        "close_time": close_time,
        "ticker": event + "-T",
    }


def test_parse_kalshi_integer_void_and_close_time() -> None:
    rows = [
        _market("KXHIGHMIA-26AUG24", "100.00"),
        _market("KXHIGHMIA-26AUG24", "100.00", result="void", strike_type="between"),
        _market("KXHIGHMIA-26AUG25", "100.50"),
        _market("NOT-A-TICKER", "91", close_time="2026-01-01T00:00:00Z"),
        _market("KXHIGHMIA-26AUG26", "91", status="settled"),
    ]
    parsed = card_e.parse_kalshi_settled(rows)
    day = parsed.days[("MIA", "high", DAY)]
    assert day.expiration_f == 100
    assert day.exclusion is None
    bad = parsed.days[("MIA", "high", dt.date(2026, 8, 25))]
    assert bad.exclusion == "non_integer_expiration_value"
    settled = parsed.days[("MIA", "high", dt.date(2026, 8, 26))]
    assert settled.exclusion == "not_finalized"
    counts = parsed.exclusion_counts[("MIA", "high")]
    assert counts["void"] == 1
    assert counts["unparsed_event_ticker"] == 1
    assert dt.date(2026, 1, 1) not in {key[2] for key in parsed.days}


def test_parse_kalshi_conflict_cancel_and_null() -> None:
    conflict = card_e.parse_kalshi_settled(
        [_market("KXHIGHMIA-26AUG24", "91"), _market("KXHIGHMIA-26AUG24", "92")]
    )
    assert conflict.days[("MIA", "high", DAY)].exclusion == "conflicting_expiration_value"
    cancelled = card_e.parse_kalshi_settled(
        [_market("KXHIGHMIA-26AUG24", "91", status="cancelled")]
    )
    assert cancelled.days[("MIA", "high", DAY)].exclusion == "cancelled"
    empty = card_e.parse_kalshi_settled([_market("KXHIGHMIA-26AUG24", None)])
    assert empty.days[("MIA", "high", DAY)].exclusion == "null_expiration_value"
    text = card_e.parse_kalshi_settled([_market("KXHIGHMIA-26AUG24", "n/a")])
    assert text.days[("MIA", "high", DAY)].exclusion == "non_numeric_expiration_value"


def test_parse_cli_label_tmax_tmin_and_exclusions() -> None:
    raw = MIA_FIXTURE.read_text(encoding="utf-8")
    high = card_e.parse_cli_label(raw, "high")
    low = card_e.parse_cli_label(raw, "low")
    assert (high.value_f, high.climate_date) == (91, DAY)
    assert (low.value_f, low.climate_date) == (77, DAY)
    amended = card_e.parse_cli_label(raw + "\nCORRECTED\n", "high")
    assert amended.exclusion == "amendment"
    preliminary = card_e.parse_cli_label(raw + "\nVALID TODAY AS OF 0400 PM LOCAL TIME.\n", "low")
    assert preliminary.exclusion == "not_final"
    missing = card_e.parse_cli_label(
        raw.replace("MAXIMUM         91", "MAXIMUM          M", 1), "high"
    )
    assert missing.exclusion == "missing_temperature"
    record = card_e.parse_cli_label(
        raw.replace("MAXIMUM         91", "MAXIMUM        91R", 1), "high"
    )
    assert record.value_f == 91
    unread = card_e.parse_cli_label(
        raw.replace("MAXIMUM         91", "MAXIMUM         ??", 1), "high"
    )
    assert unread.exclusion == "unreadable_temperature"


def test_later_amendment_excludes_and_later_final_wins() -> None:
    raw = MIA_FIXTURE.read_text(encoding="utf-8")
    amendment = "...THE MIAMI CLIMATE SUMMARY FOR AUGUST 24 2026...\nCORRECTED\n"
    excluded = card_e.cli_days_from_text(raw + "\x03" + amendment, "high")
    assert excluded.days[DAY].exclusion == "amendment"
    restored = card_e.cli_days_from_text(amendment + "\x03" + raw, "high")
    assert restored.days[DAY].value_f == 91


def test_classify_mismatch_and_buckets() -> None:
    match = card_e.classify_mismatch(91, 91)
    assert (match.kind, match.delta) == ("match", 0)
    hotter = card_e.classify_mismatch(92, 91)
    assert (hotter.kind, hotter.delta) == ("mismatch", 1)
    colder = card_e.classify_mismatch(90, 91)
    assert colder.delta == -1
    assert card_e.bucket_check("no", 100, None, 99, "less") == "agree"
    assert card_e.bucket_check("no", 100, 106, None, "greater") == "agree"
    assert card_e.bucket_check("yes", 100, 99, 100, "between") == "agree"
    assert card_e.bucket_check("no", 100, 99, 100, "between") == "disagree"
    assert card_e.bucket_check("yes", 100, None, None, "custom") == "disagree"


def test_t1_planning_threshold_and_empty() -> None:
    at_55 = card_e.t1_pooled(55, card_e.PLANNING_N, P0, ALPHA)
    at_54 = card_e.t1_pooled(54, card_e.PLANNING_N, P0, ALPHA)
    assert at_55.threshold == 55
    assert at_55.reject is True
    assert at_54.reject is False
    empty = card_e.t1_pooled(0, 0, P0, ALPHA)
    assert empty.p_value == 1.0
    assert empty.reject is False


def test_bonferroni_first_step_exact() -> None:
    found = [
        card_e.bonferroni_threshold(n, P0, ALPHA, card_e.REFERENCE_FAMILY)
        for n in card_e.REFERENCE_NS
    ]
    assert found == [6, 6, 5, 5]


def test_holm_continuation_stop_and_family_48() -> None:
    both = card_e.t2_holm({"A": (11, 30), "B": (10, 30)}, 0.2, 0.10)
    assert both == ("A", "B")
    stopped = card_e.t2_holm({"A": (10, 30), "B": (15, 50)}, 0.2, 0.10)
    assert stopped == ()
    counts = {f"S{index}:high": (0, 90) for index in range(46)}
    counts["HIT:high"] = (6, 90)
    counts["NEAR:high"] = (5, 90)
    assert card_e.t2_holm(counts, P0, ALPHA) == ("HIT:high",)
    near = {f"S{index}:high": (0, 90) for index in range(47)}
    near["NEAR:high"] = (5, 90)
    assert card_e.t2_holm(near, P0, ALPHA) == ()
    assert card_e.t2_holm({"MIA:low": (0, 0)}, P0, ALPHA) == ()


def test_same_sign_kill_and_verdict() -> None:
    assert card_e.same_sign_rule((1, 1, 1, 1, -1, 0, 0), 0.80) is True
    assert card_e.same_sign_rule((1, 1, 1, -1), 0.80) is False
    assert card_e.same_sign_rule((), 0.80) is False
    assert card_e.clopper_pearson_upper(0, 90, 0.95) == 0.03273803383353457
    assert card_e.clopper_pearson_upper(0, 200, 0.95) == 0.014867039231272054
    assert card_e.kill_rule(0, 90, 0.95, 0.02) is False
    assert card_e.kill_rule(0, 200, 0.95, 0.02) is True
    assert card_e.kill_rule(5, 5, 0.95, 0.02) is False
    assert card_e.kill_rule(0, 0, 0.95, 0.02) is False
    assert card_e.verdict(True, (), False, True)[0] == "PASS"
    assert card_e.verdict(False, ("MIA:high",), True, False)[0] == "PASS"
    assert card_e.verdict(False, (), False, True)[0] == "KILL"
    flagged = card_e.verdict(False, ("MIA:high",), False, False)
    assert flagged[0] == "INCONCLUSIVE"
    quiet = card_e.verdict(False, (), False, False)
    assert quiet[0] == "INCONCLUSIVE"


def test_half_bounds_keep_the_middle_day() -> None:
    first, second = card_e.half_bounds(dt.date(2026, 7, 5), dt.date(2026, 10, 30))
    assert first == (dt.date(2026, 7, 5), dt.date(2026, 9, 1))
    assert second == (dt.date(2026, 9, 2), dt.date(2026, 10, 30))


def test_side_pass_is_not_implied_by_pooled_t1() -> None:
    rows = tuple(
        card_e.DayRow("MIA", "high", DAY, 92, 91, 1, "mismatch", None, 1) for _ in range(10)
    )
    stats, flags = card_e.side_statistics(rows, P0, 1e-30, 0.80, 0.02)
    card = card_e.evaluate_card(stats, flags, P0, ALPHA, 1e-30, 0.02)
    assert flags == ()
    assert stats[0].outcome == "INCONCLUSIVE"
    assert card.name == "PASS"


def test_load_stations_accepts_frozen_key_names(tmp_path: Path) -> None:
    path = tmp_path / "stations.json"
    path.write_text(
        json.dumps(
            [
                {
                    "city": "ATL",
                    "icao": "KATL",
                    "cli_afos_id": "ATL",
                    "kalshi_high_series": "KXHIGHTATL",
                    "kalshi_low_series": "KXLOWTATL",
                    "tz": "America/New_York",
                }
            ]
        ),
        encoding="utf-8",
    )
    loaded = card_e.load_stations(path)
    assert loaded[0].high_series == "KXHIGHTATL"
    assert loaded[0].low_series == "KXLOWTATL"
    assert loaded[0].timezone == "America/New_York"
    assert loaded[0].cli_id == "ATL"
    assert card_e.file_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def _argv(scratch: Path, out: Path, stations: Path, *, force: str | None = None) -> list[str]:
    argv = [
        "--stations-file",
        str(stations),
        "--start",
        "2026-08-24",
        "--end",
        "2026-08-24",
        "--sides",
        "high,low",
        "--cli-pull-ts",
        "2026-10-31T12:00:00Z",
        "--scratch-dir",
        str(scratch),
        "--out-dir",
        str(out),
        "--dry-run",
    ]
    if force is not None:
        argv.extend(["--force-new-look", force])
    return argv


def _write_scratch(scratch: Path) -> None:
    (scratch / "iem").mkdir(parents=True)
    mia = MIA_FIXTURE.read_text(encoding="utf-8")
    (scratch / "iem" / "MIA.txt").write_text(mia, encoding="utf-8")
    (scratch / "kalshi").mkdir()
    high = {
        "markets": [
            _market("KXHIGHMIA-26AUG24", "91.00", cap_strike=90),
            _market(
                "KXHIGHMIA-26AUG24",
                "91.00",
                result="void",
                strike_type="between",
                floor_strike=91,
                cap_strike=92,
            ),
            _market("KXHIGHMIA-26AUG23", "70.00"),
        ]
    }
    low = {
        "markets": [
            {
                "event_ticker": "KXLOWMIA-26AUG24",
                "expiration_value": "80.00",
                "status": "finalized",
                "result": "yes",
                "strike_type": "greater",
                "floor_strike": 79,
                "cap_strike": None,
                "close_time": "2026-08-25T04:59:00Z",
                "ticker": "KXLOWMIA-26AUG24-T79",
            }
        ]
    }
    (scratch / "kalshi" / "KXHIGHMIA.json").write_text(json.dumps(high), encoding="utf-8")
    (scratch / "kalshi" / "KXLOWMIA.json").write_text(json.dumps(low), encoding="utf-8")


def test_dry_run_writes_one_look_and_does_not_open_a_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    scratch = tmp_path / "scratch"
    out = tmp_path / "out"
    stations = tmp_path / "stations.json"
    stations.write_text(
        json.dumps(
            [
                {
                    "city": "MIA",
                    "icao": "KMIA",
                    "timezone": "America/New_York",
                    "high_series": "KXHIGHMIA",
                    "low_series": "KXLOWMIA",
                }
            ]
        ),
        encoding="utf-8",
    )
    _write_scratch(scratch)
    before = sorted(path.name for path in scratch.rglob("*") if path.is_file())
    assert card_e.main(_argv(scratch, out, stations)) == 0
    after = sorted(path.name for path in scratch.rglob("*") if path.is_file())
    assert before == after
    written = sorted(path.name for path in out.iterdir())
    assert written == ["card_e_cli_vs_twc.md", "card_e_cli_vs_twc.parquet"]
    markdown = (out / "card_e_cli_vs_twc.md").read_text(encoding="utf-8")
    digest = hashlib.sha256(stations.read_bytes()).hexdigest()
    assert digest in markdown
    assert "2026-10-31T12:00:00Z" in markdown
    assert "k=55" in markdown
    assert "n=90 k=6" in markdown
    assert "n=65 k=5" in markdown
    assert "**PASS**" in markdown
    assert "mode: dry-run" in markdown
    assert "| MIA:high | void | 1 |" in markdown
    assert "| 1 | 1 | 1 |" in markdown
    table = pq.read_table(out / "card_e_cli_vs_twc.parquet")
    assert table.num_rows == 2
    by_side = {table.column("side")[i].as_py(): table.column("delta")[i].as_py() for i in range(2)}
    assert by_side == {"high": 0, "low": 3}
    try:
        card_e.main(_argv(scratch, out, stations))
    except SystemExit as exc:
        assert "refusing to overwrite" in str(exc)
    else:
        raise AssertionError("second look was allowed")
    unchanged = (out / "card_e_cli_vs_twc.md").read_text(encoding="utf-8")
    assert card_e.main(_argv(scratch, out, stations, force="second look")) == 0
    forced = (out / "card_e_cli_vs_twc.md").read_text(encoding="utf-8")
    assert "second look" in forced
    assert "second look" not in unchanged
    assert sorted(path.name for path in out.iterdir()) == written
