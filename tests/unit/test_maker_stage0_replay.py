"""MAKER-S2 WP6: the ``maker_stage0_replay`` CLI (argument surface, exit codes, size ceiling)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis import maker_stage0_replay as cli

REQUIRED = [
    "--census-days", "c.jsonl", "--trade-unit", "u.json", "--catalog-root", "cap",
    "--nbp-root", "nbp", "--truth", "t.csv", "--truth-cross-check", "x.parquet",
    "--node-log-dir", "logs", "--out-dir", "runs/r1", "--amendment", "a.md",
    "--amendment-sha", "ab" * 32, "--ledger", "l.jsonl", "--work-root", "w", "--spec", "s.md",
]  # fmt: skip
LINE_CEILING = 250


def test_cli_module_is_under_the_line_ceiling_and_importable_without_side_effects() -> None:
    lines = Path(cli.__file__).read_text().splitlines()
    assert len(lines) <= LINE_CEILING


def test_usage_line_names_every_plan_flag() -> None:
    usage = cli.build_parser().format_usage()
    for flag in (
        "--census-days", "--trade-unit", "--catalog-root", "--nbp-root", "--truth",
        "--node-log-dir", "--out-dir", "--stations", "--days", "--tail-only", "--bench",
        "--verify-first",
    ):  # fmt: skip
        assert flag in usage, flag


def test_parse_builds_a_verdict_config_by_default() -> None:
    cfg = cli.parse_args(REQUIRED)
    assert isinstance(cfg, drv.RunConfig)
    assert (cfg.bench, cfg.tail_only, cfg.verify_first) == (None, False, False)
    assert cfg.stations is None and cfg.days is None
    assert cfg.out_dir == Path("runs/r1") and cfg.addendum is None
    assert cfg.argv[0].endswith("maker_stage0_replay") or "maker_stage0_replay" in cfg.argv[0]


def test_parse_subset_and_mode_flags() -> None:
    cfg = cli.parse_args(
        [*REQUIRED, "--bench", "4", "--stations", "SFO,LAX", "--days", "2026-09-29,2026-09-30"]
    )
    assert cfg.bench == 4 and cfg.stations == ("SFO", "LAX")
    assert cfg.days == (dt.date(2026, 9, 29), dt.date(2026, 9, 30))
    tail = cli.parse_args([*REQUIRED, "--tail-only", "--parity", "SFO:0,LAX:1"])
    assert tail.tail_only and tail.parity == (("SFO", 0), ("LAX", 1))


def test_parse_rejects_a_bad_day_or_parity() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args([*REQUIRED, "--days", "not-a-date"])
    with pytest.raises(SystemExit):
        cli.parse_args([*REQUIRED, "--parity", "SFO:7"])


def test_main_maps_refusals_to_exit_two_and_prints_the_reason(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_cfg: drv.RunConfig) -> drv.RunSummary:
        raise drv.SubsetRefused("verdict run refuses --stations")

    monkeypatch.setattr(drv, "run", refuse)
    assert cli.main([*REQUIRED, "--stations", "SFO"]) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and "--stations" in err


def test_main_maps_a_void_abort_to_exit_three(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def abort(_cfg: drv.RunConfig) -> drv.RunSummary:
        raise drv.MemoryAbort("S-5: rss 5 GiB")

    monkeypatch.setattr(drv, "run", abort)
    assert cli.main(REQUIRED) == 3
    assert "VOID" in capsys.readouterr().err


def test_main_prints_the_summary_and_returns_zero(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    summary = drv.RunSummary(
        run_dir=tmp_path, label="UNDERPOWERED-WAIT", code_sha="c0ffee", mode="verdict"
    )
    monkeypatch.setattr(drv, "run", lambda _cfg: summary)
    assert cli.main(REQUIRED) == 0
    out = capsys.readouterr().out
    assert "UNDERPOWERED-WAIT" in out and str(tmp_path) in out


def test_main_returns_zero_for_a_reported_s4_stop(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stop = drv.RunSummary(
        run_dir=tmp_path, label="STOP-S4-NO-BID-BEARING-DAYS", code_sha="c0ffee", mode="verdict"
    )
    monkeypatch.setattr(drv, "run", lambda _cfg: stop)
    assert cli.main(REQUIRED) == 0  # a reported stop, not a refusal or a void
    assert "STOP-S4-NO-BID-BEARING-DAYS" in capsys.readouterr().out
