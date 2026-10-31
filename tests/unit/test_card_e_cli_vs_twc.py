"""Fixture tests for Card E. No network: dry-run reads scratch files only."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import socket
import sys
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from breezy.ingest.http import ForbiddenError, RateLimitedError, ServerError

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
    # B2 dropped the per-side kill argument. B3 requires the Holm family to be 48,
    # so the ten MIA mismatches are padded with empty sides. alpha 1e-30 does not flag.
    rows: list[Any] = [
        card_e.DayRow("MIA", "high", DAY, 92, 91, 1, "mismatch", None, 1) for _ in range(10)
    ]
    for index in range(47):
        rows.append(
            card_e.DayRow(
                f"C{index:02d}",
                "high",
                DAY,
                None,
                None,
                None,
                "excluded",
                "missing_both",
                0,
            )
        )
    stats, flags = card_e.side_statistics(tuple(rows), P0, 1e-30, 0.80)
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


def _prereg(directory: Path, text: str = "frozen card e prereg\n") -> tuple[Path, str]:
    path = directory / "prereg.md"
    path.write_text(text, encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _argv(
    scratch: Path,
    out: Path,
    stations: Path,
    prereg: Path,
    digest: str,
    *,
    force: str | None = None,
    dry_run: bool = True,
) -> list[str]:
    # B3/B4/B5: no --sides, no --cli-pull-ts, no one-day window. Start/end default.
    argv = [
        "--stations-file",
        str(stations),
        "--prereg",
        str(prereg),
        "--prereg-sha",
        digest,
        "--scratch-dir",
        str(scratch),
        "--out-dir",
        str(out),
    ]
    if dry_run:
        argv.append("--dry-run")
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


def _write_family_stations(path: Path) -> None:
    """MIA plus 23 series-less cities so the dry-run Holm family is 48."""
    rows: list[dict[str, str]] = [
        {
            "city": "MIA",
            "icao": "KMIA",
            "timezone": "America/New_York",
            "high_series": "KXHIGHMIA",
            "low_series": "KXLOWMIA",
        }
    ]
    for index in range(23):
        city = f"C{index:02d}"
        rows.append({"city": city, "icao": f"K{city}", "timezone": "America/New_York"})
    path.write_text(json.dumps(rows), encoding="utf-8")


def _assert_dry_markdown(markdown: str, digest: str, prereg_sha: str, body_sha: str) -> None:
    assert digest in markdown
    assert prereg_sha in markdown
    assert body_sha in markdown
    assert "iem_pull_ts: `dry-run`" in markdown
    assert "kalshi_pull_ts: `dry-run`" in markdown
    assert "2026-10-31T12:00:00Z" not in markdown
    assert "k=55" in markdown
    assert "n=90 k=6" in markdown
    assert "n=65 k=5" in markdown
    assert "**PASS**" in markdown
    assert "Family m = 48" in markdown
    assert "mode: dry-run" in markdown
    assert "2026-07-04" in markdown
    assert "| MIA:high | void | 1 |" in markdown
    assert "| 1 | 1 | 2 |" in markdown
    assert "## Day-row kalshi_reason" in markdown
    assert "## Day-row cli_reason" in markdown
    assert "missing_kalshi" in markdown
    assert "missing_cli" in markdown


def _assert_dry_parquet(path: Path, digest: str, prereg_sha: str) -> None:
    table = pq.read_table(path)
    assert table.num_rows == 24 * 2 * 118
    assert "kalshi_reason" in table.column_names
    assert "cli_reason" in table.column_names
    meta = table.schema.metadata or {}
    assert meta[b"iem_pull_ts"] == b"dry-run"
    assert meta[b"kalshi_pull_ts"] == b"dry-run"
    assert meta[b"stations_sha256"] == digest.encode()
    assert meta[b"prereg_sha256"] == prereg_sha.encode()
    assert meta[b"verdict"] == b"PASS"
    paired = {
        table.column("side")[index].as_py(): table.column("delta")[index].as_py()
        for index in range(table.num_rows)
        if table.column("outcome")[index].as_py() != "excluded"
    }
    assert paired == {"high": 0, "low": 3}
    both = [
        index
        for index in range(table.num_rows)
        if table.column("exclusion")[index].as_py() == "missing_both"
    ]
    assert both
    assert table.column("kalshi_reason")[both[0]].as_py() == "missing_kalshi"
    assert table.column("cli_reason")[both[0]].as_py() == "missing_cli"


def test_dry_run_writes_one_look_and_does_not_open_a_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    scratch = tmp_path / "scratch"
    out = tmp_path / "out"
    stations = tmp_path / "stations.json"
    _write_family_stations(stations)
    prereg, prereg_sha = _prereg(tmp_path)
    _write_scratch(scratch)
    before = sorted(path.name for path in scratch.rglob("*") if path.is_file())
    argv = _argv(scratch, out, stations, prereg, prereg_sha)
    assert card_e.main(argv) == 0
    after = sorted(path.name for path in scratch.rglob("*") if path.is_file())
    assert before == after
    written = sorted(path.name for path in out.iterdir())
    assert written == ["card_e_cli_vs_twc.md", "card_e_cli_vs_twc.parquet"]
    digest = hashlib.sha256(stations.read_bytes()).hexdigest()
    body_sha = hashlib.sha256((scratch / "iem" / "MIA.txt").read_bytes()).hexdigest()
    markdown = (out / "card_e_cli_vs_twc.md").read_text(encoding="utf-8")
    _assert_dry_markdown(markdown, digest, prereg_sha, body_sha)
    _assert_dry_parquet(out / "card_e_cli_vs_twc.parquet", digest, prereg_sha)
    try:
        card_e.main(argv)
    except SystemExit as exc:
        assert "refusing to overwrite" in str(exc)
    else:
        raise AssertionError("second look was allowed")
    unchanged = (out / "card_e_cli_vs_twc.md").read_text(encoding="utf-8")
    forced_argv = _argv(scratch, out, stations, prereg, prereg_sha, force="second look")
    assert card_e.main(forced_argv) == 0
    forced = (out / "card_e_cli_vs_twc.md").read_text(encoding="utf-8")
    assert "second look" in forced
    assert "second look" not in unchanged
    assert sorted(path.name for path in out.iterdir()) == written


def test_prereg_mismatch_and_pending_refuse_before_one_look(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prereg, digest = _prereg(tmp_path, "still PENDING\n")
    out = tmp_path / "out"
    out.mkdir()
    (out / card_e.MARKDOWN_NAME).write_text("old look", encoding="utf-8")
    stations = tmp_path / "stations.json"
    _write_family_stations(stations)
    argv = _argv(tmp_path / "scratch", out, stations, prereg, "0" * 64)
    with pytest.raises(SystemExit) as exc:
        card_e.main(argv)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "prereg sha256 mismatch" in err
    assert "prereg still contains PENDING" in err
    assert "refusing to overwrite" not in err
    assert (out / card_e.MARKDOWN_NAME).read_text(encoding="utf-8") == "old look"
    with pytest.raises(SystemExit) as pending:
        card_e.assert_prereg(prereg, digest)
    assert pending.value.code == 2
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    clean, clean_sha = _prereg(clean_dir)
    assert card_e.assert_prereg(clean, clean_sha) == clean_sha
    named = clean_dir / "names-the-rule.md"
    named.write_text(
        "Frozen. The script refuses to run while the sha256 line says PENDING.\n",
        encoding="utf-8",
    )
    named_sha = hashlib.sha256(named.read_bytes()).hexdigest()
    assert card_e.assert_prereg(named, named_sha) == named_sha


def test_apply_side_outcomes_follows_the_card_kill() -> None:
    quiet = card_e.SideStat(
        "MIA:high", "MIA", "high", 10, 0, 1.0, False, 0, 0, False, 0.2, "INCONCLUSIVE", {}
    )
    flagged = card_e.SideStat(
        "MIA:low", "MIA", "low", 10, 10, 0.0, True, 10, 0, True, 1.0, "PASS", {}
    )
    killed = card_e.apply_side_outcomes((quiet, flagged), True)
    assert killed[0].outcome == "KILL"
    assert killed[1].outcome == "PASS"
    held = card_e.apply_side_outcomes((quiet,), False)
    assert held[0].outcome == "INCONCLUSIVE"


def test_side_statistics_requires_family_48() -> None:
    row = card_e.DayRow("MIA", "high", DAY, 91, 91, 0, "match", None, 1)
    with pytest.raises(ValueError, match="Holm family"):
        card_e.side_statistics((row,), P0, ALPHA, 0.80)


def test_removed_flags_and_frozen_window(tmp_path: Path) -> None:
    prereg, digest = _prereg(tmp_path)
    stations = tmp_path / "stations.json"
    stations.write_text("[]", encoding="utf-8")
    base = _argv(tmp_path / "scratch", tmp_path / "out", stations, prereg, digest)
    parser = card_e.build_parser()
    for extra in (["--sides", "high,low"], ["--p0", "0.01"], ["--cli-pull-ts", "now"]):
        with pytest.raises(SystemExit):
            parser.parse_args([*base, *extra])
    assert card_e.main([*base, "--start", "2026-08-24", "--end", "2026-08-24"]) == 2
    config = card_e._config_from_args(parser.parse_args(base))
    assert (config.start, config.end) == (card_e.FROZEN_START, card_e.FROZEN_END)
    assert config.sides == ("high", "low")
    assert card_e.P0 == 0.01
    assert card_e.ALPHA_T1 == card_e.ALPHA_T2 == 0.025
    assert card_e.SAME_SIGN_SHARE == 0.80
    assert card_e.KILL_UCB == 0.02
    assert card_e.station_cap("MIA") == 91
    assert card_e.station_cap("PHX") == 89
    assert card_e.station_cap("MSP") == 90
    assert card_e.station_cap("SAN") == 71
    assert card_e.station_cap("EWR") == card_e.station_cap("TTN") == 65
    assert card_e.station_cap("SDF") == 63
    assert card_e.paired_cap() == 4162


def test_stamps_land_before_the_first_request(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def _stamp() -> str:
        order.append("stamp")
        return "2026-10-31T00:00:00+00:00"

    class _Client:
        def __init__(self) -> None:
            self.calls = 0
            self.pages: list[tuple[str, object]] = []

        def list_series_markets(self, series: str) -> list[object]:
            order.append("kalshi")
            return []

    monkeypatch.setattr(card_e, "_stamp", _stamp)
    monkeypatch.setattr(card_e, "_counting_kalshi", lambda: _Client())
    pulled = card_e._pull_kalshi({"KX": ("MIA", "high")})
    assert pulled.pulled_at == "2026-10-31T00:00:00+00:00"
    assert order[:2] == ["stamp", "kalshi"]

    def _runtime(_count: int) -> tuple[object, object]:
        order.append("iem")
        raise OSError("stop before a request")

    monkeypatch.setattr(card_e, "_iem_runtime", _runtime)
    station = card_e.Station("MIA", "KMIA", "UTC", None, None, "MIA")
    iem = asyncio.run(
        card_e._pull_iem_async((station,), ("high", "low"), card_e.FROZEN_START, card_e.FROZEN_END)
    )
    assert iem.pulled_at == "2026-10-31T00:00:00+00:00"
    assert order[-2:] == ["stamp", "iem"]


def test_dry_run_refuses_the_evidence_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(card_e, "assert_prereg", lambda _path, _sha: "abc")
    monkeypatch.setattr(card_e, "assert_one_look", lambda *_args: seen.append("look"))
    config = card_e.RunConfig(
        stations_file=tmp_path / "stations.json",
        prereg=tmp_path / "prereg.md",
        prereg_sha="abc",
        start=card_e.FROZEN_START,
        end=card_e.FROZEN_END,
        sides=("high", "low"),
        scratch_dir=tmp_path / "scratch",
        out_dir=card_e.evidence_dir(),
        dry_run=True,
        force_reason=None,
    )
    with pytest.raises(SystemExit) as exc:
        card_e.execute(config)
    assert exc.value.code == 2
    assert seen == []
    card_e.assert_dry_run_not_evidence(tmp_path, True)


def test_partial_pull_aborts_before_any_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prereg, digest = _prereg(tmp_path)
    stations = tmp_path / "stations.json"
    stations.write_text(
        json.dumps(
            [{"city": "MIA", "icao": "KMIA", "timezone": "UTC", "high_series": "KXHIGHMIA"}]
        ),
        encoding="utf-8",
    )
    scratch = tmp_path / "scratch"
    out = tmp_path / "out"

    def _kalshi(_owners: object) -> Any:
        return card_e._KalshiPull(
            {("MIA", "high"): "kalshi_fetch_error"},
            (),
            1,
            1,
            card_e._empty_copies(),
            {},
            {"KXHIGHMIA": ({"ticker": "SHOULD_NOT_WRITE"},)},
            "ts",
        )

    def _iem(*_args: object) -> Any:
        return card_e._IemPull(
            {("MIA", "low"): "iem_fetch_error"},
            1,
            1,
            {"MIA": "BODY THAT MUST NOT BE WRITTEN"},
            {},
            {("MIA", "high"): "iem_fetch_error", ("MIA", "low"): "iem_short_body"},
            {},
            "ts",
        )

    monkeypatch.setattr(card_e, "_pull_kalshi", _kalshi)
    monkeypatch.setattr(card_e, "_pull_iem", _iem)
    argv = _argv(scratch, out, stations, prereg, digest, dry_run=False)
    with pytest.raises(SystemExit) as exc:
        card_e.main(argv)
    assert exc.value.code == 2
    assert not scratch.exists()
    assert not out.exists()
    err = capsys.readouterr().err
    assert "side\treason" in err
    assert "MIA:high\tkalshi_fetch_error+iem_fetch_error" in err
    assert "MIA:low\tiem_short_body" in err


class _BoomClient:
    def __init__(self, exc: BaseException | None) -> None:
        self.calls = 0
        self.pages: list[tuple[str, object]] = []
        self._exc = exc

    def list_series_markets(self, series: str) -> list[object]:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return []


@pytest.mark.parametrize(
    "exc",
    [KeyError("k"), RuntimeError("401"), TypeError("t"), AttributeError("a"), ValueError("v")],
)
def test_programming_errors_propagate(exc: BaseException) -> None:
    with pytest.raises(type(exc)):
        card_e._pull_one_series(_BoomClient(exc), "KXHIGHMIA", ("MIA", "high"))


def test_oserror_is_a_kalshi_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    pulled = card_e._pull_one_series(_BoomClient(OSError("down")), "KX", ("MIA", "high"))
    assert pulled.reason == "kalshi_fetch_error"
    monkeypatch.setattr(card_e, "_counting_kalshi", lambda: _BoomClient(OSError("down")))
    result = card_e._pull_kalshi({"KXHIGHMIA": ("MIA", "high")})
    assert result.errors == 1
    assert result.blocked[("MIA", "high")] == "kalshi_fetch_error"
    monkeypatch.setattr(card_e, "_counting_kalshi", lambda: _BoomClient(KeyError("k")))
    with pytest.raises(KeyError):
        card_e._pull_kalshi({"KXHIGHMIA": ("MIA", "high")})


class _RetryTransport:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def fetch_cli_text(self, url: str) -> object:
        self.calls += 1
        item = self.outcomes[self.calls - 1]
        if isinstance(item, BaseException):
            raise item
        return item


def _sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []

    async def _sleep(delay: float, result: object = None) -> object:
        delays.append(delay)
        return result

    monkeypatch.setattr(card_e.asyncio, "sleep", _sleep)
    return delays


def _retry(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[object]
) -> tuple[_RetryTransport, list[float], Any]:
    delays = _sleeps(monkeypatch)
    transport = _RetryTransport(outcomes)
    station = card_e.Station("MIA", "KMIA", "UTC", None, None, "MIA")
    fetched, reason = asyncio.run(
        card_e._fetch_with_retry(
            transport,
            lambda *_args: "https://example.invalid/cli",
            station,
            card_e.FROZEN_START,
            card_e.FROZEN_END,
        )
    )
    assert fetched is None
    return transport, delays, reason


@pytest.mark.parametrize(
    "failure",
    [
        RateLimitedError("https://user:secret@example.invalid/token", retry_after=None),
        ServerError("https://user:secret@example.invalid/token", status_code=503),
    ],
)
def test_iem_retries_429_and_5xx(
    failure: BaseException, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport, delays, reason = _retry(monkeypatch, [failure] * 5)
    assert transport.calls == 5
    assert delays == [1.0, 2.0, 4.0, 8.0]
    assert reason == "iem_fetch_error"
    err = capsys.readouterr().err
    assert "secret" not in err
    assert "http_429" in err or "http_503" in err


def test_iem_retries_non_200_then_stops(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    page = type("Fetched", (), {"status_code": 404, "text": "token=secret"})()
    transport, delays, reason = _retry(monkeypatch, [page] * 5)
    assert transport.calls == 5
    assert delays == [1.0, 2.0, 4.0, 8.0]
    assert reason == "iem_http_404"
    err = capsys.readouterr().err
    assert "http_404" in err
    assert "secret" not in err


def test_iem_does_not_retry_programming_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    delays = _sleeps(monkeypatch)
    transport = _RetryTransport([KeyError("parse")])
    station = card_e.Station("MIA", "KMIA", "UTC", None, None, "MIA")
    with pytest.raises(KeyError):
        asyncio.run(
            card_e._fetch_with_retry(
                transport, lambda *_a: "https://example.invalid", station, DAY, DAY
            )
        )
    assert transport.calls == 1
    assert delays == []
    forbidden = _RetryTransport([ForbiddenError("https://user:secret@example.invalid")])
    fetched, reason = asyncio.run(
        card_e._fetch_with_retry(
            forbidden, lambda *_a: "https://example.invalid", station, DAY, DAY
        )
    )
    assert fetched is None
    assert reason == "iem_fetch_error"
    assert forbidden.calls == 1


def test_short_body_is_a_fetch_failure(capsys: pytest.CaptureFixture[str]) -> None:
    start, end = card_e.FROZEN_START, card_e.FROZEN_END
    assert card_e.products_in_window("", "high", start, end) == 0
    raw = MIA_FIXTURE.read_text(encoding="utf-8")
    missing = raw.replace("MAXIMUM         91", "MAXIMUM          M", 1)
    assert card_e.products_in_window(missing, "high", start, end) >= 1
    kept = card_e._classify_body("MIA", ("high", "low"), start, end, missing)
    assert kept.reason is None
    short = card_e._classify_body("MIA", ("high", "low"), start, end, "")
    digest = hashlib.sha256(b"").hexdigest()
    assert short.reason == "iem_short_body"
    assert short.sha256 == digest
    err = capsys.readouterr().err
    assert digest in err
    assert "iem_short_body" in err
    assert "secret" not in err


def _one_row() -> Any:
    return card_e.DayRow("MIA", "high", DAY, 91, 91, 0, "match", None, 1)


def _meta() -> dict[str, str]:
    return {
        "iem_pull_ts": "2026-10-31T00:00:01+00:00",
        "kalshi_pull_ts": "2026-10-31T00:00:02+00:00",
        "stations_sha256": "abc",
        "prereg_sha256": "def",
        "verdict": "INCONCLUSIVE",
    }


def test_emit_outputs_publishes_both_and_records_metadata(tmp_path: Path) -> None:
    card_e.emit_outputs(tmp_path, (_one_row(),), "# card\n", _meta())
    assert list(tmp_path.glob(".*.tmp")) == []
    table = pq.read_table(tmp_path / card_e.PARQUET_NAME)
    meta = table.schema.metadata or {}
    assert meta[b"iem_pull_ts"] == b"2026-10-31T00:00:01+00:00"
    assert meta[b"kalshi_pull_ts"] == b"2026-10-31T00:00:02+00:00"
    assert meta[b"verdict"] == b"INCONCLUSIVE"
    assert (tmp_path / card_e.MARKDOWN_NAME).read_text(encoding="utf-8") == "# card\n"


def test_failed_temp_write_leaves_no_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("parquet write failed")

    monkeypatch.setattr(card_e, "write_parquet", _boom)
    with pytest.raises(OSError, match="parquet write failed"):
        card_e.emit_outputs(tmp_path, (_one_row(),), "# card\n", _meta())
    assert list(tmp_path.iterdir()) == []


def test_second_replace_rolls_back_the_parquet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    real = os.replace

    def _replace(src: str | Path, dst: str | Path) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("second replace failed")
        real(src, dst)

    monkeypatch.setattr(card_e.os, "replace", _replace)
    with pytest.raises(OSError, match="second replace failed"):
        card_e.emit_outputs(tmp_path, (_one_row(),), "# card\n", _meta())
    assert not (tmp_path / card_e.PARQUET_NAME).exists()
    assert not (tmp_path / card_e.MARKDOWN_NAME).exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_compare_kalshi_copies_sees_both_pages() -> None:
    historical = [
        {"ticker": "A", "expiration_value": "91", "status": "finalized"},
        {"ticker": "B", "expiration_value": "80", "status": "finalized"},
        {"ticker": "C", "expiration_value": "1", "status": "determined"},
    ]
    live = [
        {"ticker": "A", "expiration_value": "91", "status": "finalized"},
        {"ticker": "B", "expiration_value": "81", "status": "finalized"},
    ]

    class _Inner:
        def get_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, object]:
            if path.startswith("historical/"):
                return {"markets": historical}
            return {"markets": live}

        def list_series_markets(self, series: str) -> list[dict[str, object]]:
            collected: dict[str, dict[str, object]] = {}
            for path in ("historical/markets", "markets"):
                page = self.get_json(path, {"series_ticker": series})
                markets = page.get("markets")
                if not isinstance(markets, list):
                    continue
                for market in markets:
                    if isinstance(market, dict):
                        ticker = market.get("ticker")
                        if isinstance(ticker, str):
                            collected.setdefault(ticker, market)
            return list(collected.values())

    wrapper = card_e._CountedKalshi(_Inner())
    merged = wrapper.list_series_markets("KXHIGHMIA")
    by_ticker = {row["ticker"]: row for row in merged}
    assert by_ticker["B"]["expiration_value"] == "80"
    report = card_e.compare_kalshi_copies(*card_e._split_copies(wrapper.pages))
    assert report.overlap == 2
    assert report.conflicts == 1
    assert report.historical_rows == 3
    assert report.historical_not_finalized == 1
    assert report.cutoff == dt.date(2026, 7, 4)


def test_assign_matched_halves_uses_floor_n_over_2() -> None:
    days = [dt.date(2026, 7, day) for day in (6, 5, 8, 7, 9)]
    rows = [card_e.DayRow("MIA", "high", day, 91, 91, 0, "match", None, 9) for day in days]
    rows.append(
        card_e.DayRow("MIA", "high", dt.date(2026, 7, 10), None, None, None, "excluded", "x", 9)
    )
    assigned = card_e.assign_matched_halves(tuple(rows))
    by_day = {row.climate_date: row.half for row in assigned if row.outcome != "excluded"}
    assert by_day[dt.date(2026, 7, 5)] == 1
    assert by_day[dt.date(2026, 7, 6)] == 1
    assert by_day[dt.date(2026, 7, 7)] == 2
    assert by_day[dt.date(2026, 7, 9)] == 2
    assert assigned[-1].half == 0


def test_paired_fraction_aborts_below_half_the_cap(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        card_e.assert_paired_fraction(2080, {"finalized": 3, "settled": 1})
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "finalized=3" in err
    assert "settled=1" in err
    assert "2080" in err
    card_e.assert_paired_fraction(2081, {"finalized": 1})


def test_later_not_final_keeps_the_final_and_counts_overwrites() -> None:
    raw = MIA_FIXTURE.read_text(encoding="utf-8")
    later = (
        "...THE MIAMI CLIMATE SUMMARY FOR AUGUST 24 2026...\n"
        "VALID TODAY AS OF 0400 PM LOCAL TIME.\n"
    )
    kept = card_e.cli_days_from_text(raw + "\x03" + later, "low")
    assert kept.days[DAY].value_f == 77
    assert kept.overwrites == 0
    amendment = "...THE MIAMI CLIMATE SUMMARY FOR AUGUST 24 2026...\nCORRECTED\n"
    replaced = card_e.cli_days_from_text(raw + "\x03" + amendment, "high")
    assert replaced.days[DAY].exclusion == "amendment"
    assert replaced.overwrites == 1


def test_fetch_errors_log_http_code_not_message(capsys: pytest.CaptureFixture[str]) -> None:
    secret = "https://user:secret@example.invalid/token"
    limited = RateLimitedError(secret, retry_after="9")
    server = ServerError(secret, status_code=503)
    http = urllib.error.HTTPError(secret, 401, "denied", Message(), None)
    assert card_e._http_code(limited) == 429
    assert card_e._http_code(server) == 503
    assert card_e._http_code(http) == 401
    card_e._note_fetch_error("kalshi", "KXHIGHMIA", limited)
    card_e._note_fetch_error("iem", "MIA", server)
    card_e._note_fetch_error("kalshi", "KX", http)
    err = capsys.readouterr().err
    assert "RateLimitedError http_429" in err
    assert "ServerError http_503" in err
    assert "HTTPError http_401" in err
    assert "secret" not in err
