"""MAKER-S2 WP6: the ``maker_stage0_replay`` CLI (argument surface, exit codes, size ceiling)."""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis import maker_stage0_replay as cli
from tests.unit import test_maker_stage0_driver as drv_fx

REQUIRED = [
    "--census-days", "c.jsonl", "--trade-unit", "u.json", "--catalog-root", "cap",
    "--nbp-root", "nbp", "--truth", "t.csv", "--truth-cross-check", "x.parquet",
    "--node-log-dir", "logs", "--out-dir", "runs/r1", "--amendment", "a.md",
    "--amendment-sha", "ab" * 32, "--work-root", "w", "--spec", "s.md",
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
        raise drv.RunVoided(drv.MemoryAbort("S-5: rss 5 GiB"))

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


@pytest.mark.parametrize("exc", drv_fx.ERRORS, ids=lambda e: type(e).__name__)
def test_every_pre_claim_failure_type_maps_to_exit_two(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    def fail(_cfg: drv.RunConfig) -> drv.RunSummary:
        raise exc

    monkeypatch.setattr(drv, "run", fail)
    assert cli.main(REQUIRED) == 2
    assert "REFUSED" in capsys.readouterr().err


@pytest.mark.parametrize("exc", drv_fx.ERRORS, ids=lambda e: type(e).__name__)
def test_every_post_claim_failure_type_maps_to_exit_three(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    def fail(_cfg: drv.RunConfig) -> drv.RunSummary:
        raise drv.RunVoided(exc)

    monkeypatch.setattr(drv, "run", fail)
    assert cli.main(REQUIRED) == 3
    err = capsys.readouterr().err
    assert "VOID" in err and type(exc).__name__ in err and "boom-original-cause" in err


def test_a_failed_void_still_exits_three_with_the_original_cause(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_cfg: drv.RunConfig) -> drv.RunSummary:
        raise drv.RunVoided(RuntimeError("original"), void_failure=OSError("rename failed"))

    monkeypatch.setattr(drv, "run", fail)
    assert cli.main(REQUIRED) == 3
    err = capsys.readouterr().err
    assert "original" in err and "rename failed" in err


@pytest.mark.parametrize("flag", ["--ledger", "--repo-root"])
def test_a_caller_cannot_redirect_the_ledger_or_the_repo_root(flag: str) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.parse_args([*REQUIRED, flag, "elsewhere"])
    assert exc.value.code == 2
    assert flag not in cli.build_parser().format_help()


def test_ledger_is_derived_and_repo_root_is_the_imported_packages_git_root() -> None:
    argv = [a for i, a in enumerate(REQUIRED) if a not in ("--spec", "s.md")]
    cfg = cli.parse_args(argv)
    derived = Path.home() / ".local/share/breezy/derived/maker_stage0/verdict_ledger.jsonl"
    assert cfg.ledger == cli.DEFAULT_LEDGER == derived
    package = Path(drv.__file__).resolve()  # scripts.analysis is a namespace package
    assert package.is_relative_to(cfg.repo_root)
    top = subprocess.run(
        ["git", "-C", str(package.parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    assert cfg.repo_root == Path(top).resolve()
    assert cfg.spec == cfg.repo_root / cli.DEFAULT_SPEC


def test_modes_are_a_mutually_exclusive_argparse_group() -> None:
    for pair in (["--bench", "4", "--tail-only"], ["--tail-only", "--verify-first"],
                 ["--bench", "4", "--verify-first"]):  # fmt: skip
        with pytest.raises(SystemExit) as exc:
            cli.parse_args([*REQUIRED, *pair])
        assert exc.value.code == 2


def test_verify_first_needs_no_replay_inputs_and_absent_ones_are_not_sentinels() -> None:
    argv = ["--out-dir", "o", "--amendment", "a.md", "--amendment-sha", "ab" * 32, "--verify-first"]
    cfg = cli.parse_args(argv)
    assert cfg.census_days is None and cfg.truth is None and cfg.node_log_dir is None
    assert cfg.trade_unit is None


# --- C2b: the v1 amendment sha pin at the command-line layer ---------------------------------


def _amendment_argv(path: Path, sha: str, *extra: str) -> list[str]:
    argv = list(REQUIRED)
    argv[argv.index("a.md")] = str(path)
    argv[argv.index("ab" * 32)] = sha
    return [*argv, *extra]


def _recording_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[drv.RunConfig]:
    seen: list[drv.RunConfig] = []

    def run(cfg: drv.RunConfig) -> drv.RunSummary:
        seen.append(cfg)
        return drv.RunSummary(run_dir=tmp_path, label=None, code_sha="c0ffee", mode="verdict")

    monkeypatch.setattr(drv, "run", run)
    return seen


def test_cli_refuses_v1_block_for_any_other_sha(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests.unit.test_maker_stage0_frozen_v2 import V1_BLOCK

    seen = _recording_run(monkeypatch, tmp_path)
    amendment = tmp_path / "v1.md"
    amendment.write_text("# v1\nStatus: FINAL\n\n" + V1_BLOCK)
    assert cli.main(_amendment_argv(amendment, "ab" * 32)) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and cli.V1_AMENDMENT_SHA256 in err and not seen
    assert cli.main(_amendment_argv(amendment, cli.V1_AMENDMENT_SHA256)) == 0
    assert len(seen) == 1


def test_cli_refuses_v2_block_with_the_v1_sha(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests.fixtures.maker_stage0.frozen_v2 import v2_fields, v2_text

    seen = _recording_run(monkeypatch, tmp_path)
    amendment = tmp_path / "v2.md"
    amendment.write_text(v2_text(v2_fields()))
    assert cli.main(_amendment_argv(amendment, cli.V1_AMENDMENT_SHA256)) == 2
    assert "REFUSED" in capsys.readouterr().err and not seen
    assert cli.main(_amendment_argv(amendment, "ab" * 32)) == 0
    assert len(seen) == 1


@pytest.mark.parametrize("mode", [["--bench", "4"], ["--tail-only"], ["--verify-first"]])
def test_cli_bench_and_verify_first_unaffected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: list[str]
) -> None:
    from tests.unit.test_maker_stage0_frozen_v2 import V1_BLOCK

    seen = _recording_run(monkeypatch, tmp_path)
    amendment = tmp_path / "v1.md"
    amendment.write_text("# v1\nStatus: FINAL\n\n" + V1_BLOCK)
    assert cli.main(_amendment_argv(amendment, "ab" * 32, *mode)) == 0
    assert len(seen) == 1


@pytest.mark.parametrize(
    "body", [None, b"\xff\xfe not utf-8", b"no block here", b"```FROZEN_DATE_SET\n```"]
)
def test_cli_unreadable_amendment_defers_to_driver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: bytes | None
) -> None:
    seen = _recording_run(monkeypatch, tmp_path)
    amendment = tmp_path / "x.md"
    if body is not None:
        amendment.write_bytes(body)
    assert cli.main(_amendment_argv(amendment, "ab" * 32)) == 0
    assert len(seen) == 1  # the driver, not the CLI pin, owns every unreadable-amendment refusal


def test_cli_pin_check_is_an_injectable_seam(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _recording_run(monkeypatch, tmp_path)
    assert cli.main(REQUIRED, pin_check=lambda _cfg: "seam says no") == 2
    assert "seam says no" in capsys.readouterr().err and not seen
