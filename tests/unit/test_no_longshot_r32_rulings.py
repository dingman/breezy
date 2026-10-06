"""M1-v3 r3.2 build rulings (M1V3-R19..R27): fixed sample, read-once, no interim loss counts,
error mapping, freeze-introduction check. Synthetic fixtures only; reuses the base suite helpers."""

from __future__ import annotations

import csv
import datetime as dt
import inspect
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scipy import stats as scipy_stats

from scripts.analysis import no_longshot_pooled_test as tool
from scripts.analysis import prereg_precommit_check as prereg_check
from tests.unit import test_no_longshot_pooled_test as base

_FIRST = base._FIRST_FORWARD
_LAST = _FIRST + dt.timedelta(days=52)
_READ = _FIRST + dt.timedelta(days=61)
_DEADLINE = _FIRST + dt.timedelta(days=75)
_PROGRESS_KEYS = {
    "n_takes",
    "n_days",
    "n_station_days",
    "skipped_no_bid_side",
    "windows_without_depth",
    "excluded_station_days",
    "excluded_days",
    "no_final_truth",
}
_TODAY = dt.date(2026, 10, 6)


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    prereg, sha = base._freeze(tmp_path)
    return {"root": tmp_path, "prereg": prereg, "sha": sha}


def _run(
    world: dict[str, Any], catalog: Path, truth: Path, **kw: Any
) -> tuple[dict[str, Any], int]:
    return base._run(world, catalog, truth, **kw)


def _drop_truth(truth: Path, day: dt.date) -> None:
    with truth.open(newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if r["climate_day"] != day.isoformat()]
    with truth.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _two_days(world: dict[str, Any]) -> tuple[Path, Path]:
    days = {_FIRST: [base._lax()], _FIRST + dt.timedelta(days=1): [base._lax()]}
    return base._stage(world["root"], days)


# --------------------------------------------------------------------------- R19


def test_r19_prereg_pins_fixed_sample_and_check_pins_flags_drift() -> None:
    design = json.loads(base._PREREG_SRC.read_text())
    assert design["sample_days"] == 53
    assert design["last_forward_day_rule"] == "first_forward_day+52d"
    assert design["truth_deadline_rule"] == "first_forward_day+75d"
    assert tool.check_pins(design) == []
    for key, bad in (
        ("sample_days", 54),
        ("last_forward_day_rule", "first_forward_day+60d"),
        ("truth_deadline_rule", "first_forward_day+80d"),
    ):
        assert any(key in m for m in tool.check_pins({**design, key: bad})), key
        missing = {k: v for k, v in design.items() if k != key}
        assert any(key in m for m in tool.check_pins(missing)), key


def test_r19_days_after_last_forward_day_are_outside_every_collect(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    days = {d: [base._lax()] for d in (_FIRST, _LAST, _LAST + dt.timedelta(days=1))}
    catalog, truth = base._stage(world["root"], days)
    scanned: set[dt.date] = set()
    real = tool.m1.collect

    def spy(root: Path, rows: Any, last: Any, windows: Any = None, **kw: Any) -> Any:
        scanned.update(day for _s, day in rows)
        return real(root, rows, last, windows, **kw)

    monkeypatch.setattr(tool.m1, "collect", spy)
    report, _ = _run(world, catalog, truth)
    assert scanned == {_FIRST, _LAST}  # last day inclusive, last + 1 excluded, every window
    assert report["counts"]["n_days"] == 2
    assert report["last_forward_day"] == _LAST.isoformat()


def test_r19_pending_truth_until_deadline_then_missing_excluded_and_counted(
    world: dict[str, Any],
) -> None:
    catalog, truth = _two_days(world)
    _drop_truth(truth, _FIRST + dt.timedelta(days=1))  # tape exists, FINAL truth does not
    pending, code = _run(world, catalog, truth, as_of=_READ)
    assert code == 0 and pending["status"] == "PENDING_TRUTH"
    assert "verdict" not in pending and "stats" not in pending
    assert set(pending["progress"]) == _PROGRESS_KEYS
    assert pending["progress"]["no_final_truth"] == 1
    final, code = _run(world, catalog, truth, as_of=_DEADLINE)
    assert code == 0 and final["status"] == "READ" and "verdict" in final
    assert final["population"]["no_final_truth"] == 1
    assert final["counts"]["n_days"] == 1


def test_r19_no_verdict_before_read_date_even_with_complete_truth(world: dict[str, Any]) -> None:
    catalog, truth = _two_days(world)
    early, _ = _run(world, catalog, truth, as_of=_READ - dt.timedelta(days=1))
    assert early["status"] == "PROGRESS" and "verdict" not in early


# --------------------------------------------------------------------------- R20


def _argv(world: dict[str, Any], catalog: Path, truth: Path, out: Path, as_of: str) -> list[str]:
    return [
        "--prereg", str(world["prereg"]),
        "--catalog", str(catalog),
        "--truth", str(truth),
        "--out", str(out),
        "--as-of", as_of,
    ]  # fmt: skip


def test_r20_future_as_of_is_refused_unless_not_after_the_clock(
    world: dict[str, Any], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    catalog, truth = _two_days(world)
    out = tmp_path / "o"
    clock = lambda: _TODAY
    assert tool.main(_argv(world, catalog, truth, out, "2026-10-07"), clock=clock) == 3
    assert "--as-of" in capsys.readouterr().err
    assert not out.exists()
    assert tool.main(_argv(world, catalog, truth, out, "2026-10-06"), clock=clock) == 0


def test_r20_default_as_of_is_the_clock_today(world: dict[str, Any], tmp_path: Path) -> None:
    catalog, truth = _two_days(world)
    argv = _argv(world, catalog, truth, tmp_path / "o", "2026-10-06")[:-2]
    assert tool.main(argv, clock=lambda: _TODAY) == 0
    written = json.loads((tmp_path / "o" / tool.REPORT_NAME).read_text())
    assert written["as_of"] == "2026-10-06"


# --------------------------------------------------------------------------- R21


def test_r21_progress_report_carries_counts_only(world: dict[str, Any]) -> None:
    catalog, truth = _two_days(world)  # each ladder has one losing NO rung
    early, code = _run(world, catalog, truth, as_of=_FIRST + dt.timedelta(days=5))
    assert code == 0 and early["status"] == "PROGRESS"
    assert set(early["progress"]) == _PROGRESS_KEYS
    assert early["progress"]["n_takes"] == 6 and early["progress"]["n_station_days"] == 2
    forbidden = {"counts", "population", "depth", "stats", "verdict", "sensitivities", "ask_bins"}
    assert forbidden.isdisjoint(early)
    text = json.dumps(early)
    for needle in ("n_losses", "loss_days", "loss_rate", "lb_", "per_day", "net_ev", "mean"):
        assert needle not in text, needle


# --------------------------------------------------------------------------- R22


def test_r22_design_loading_failures_are_refusals(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalog, truth = _two_days(world)
    missing = dict(world, prereg=tmp_path / "nope" / "PREREG.json")
    with pytest.raises(tool.Refusal):
        _run(missing, catalog, truth)
    world["prereg"].write_text("{not json")
    with pytest.raises(tool.Refusal):
        _run(world, catalog, truth)
    prereg, _ = base._freeze(tmp_path / "other")
    world2 = dict(world, prereg=prereg)

    def timeout(*_a: Any, **_k: Any) -> Any:
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(tool, "_git", timeout)
    with pytest.raises(tool.Refusal):
        _run(world2, catalog, truth)


def test_r22_run_time_data_errors_are_invalid_not_tracebacks(
    world: dict[str, Any], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    catalog, _truth = _two_days(world)
    report, code = _run(world, catalog, tmp_path / "missing_truth.csv")
    assert code == 2 and report["status"] == "INVALID" and report["verdict"] == "INVALID"
    assert report["invalid_reasons"]
    bad = tmp_path / "bad_truth.csv"
    bad.write_text("station,climate_day\nLAX,2026-10-11\n")  # no is_final column
    assert _run(world, catalog, bad)[1] == 2
    out = tmp_path / "o"
    argv = _argv(world, catalog, tmp_path / "missing_truth.csv", out, "2026-10-06")
    assert tool.main(argv, clock=lambda: _TODAY) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_r22_main_maps_missing_prereg_to_exit_3(
    world: dict[str, Any], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    catalog, truth = _two_days(world)
    bad = dict(world, prereg=tmp_path / "nope.json")
    argv = _argv(bad, catalog, truth, tmp_path / "o", "2026-10-06")
    assert tool.main(argv, clock=lambda: _TODAY) == 3
    assert "Traceback" not in capsys.readouterr().err


# --------------------------------------------------------------------------- R23


def test_r23_read_and_invalid_reports_are_never_overwritten(
    world: dict[str, Any], tmp_path: Path
) -> None:
    catalog, truth = _two_days(world)
    out = tmp_path / "o"
    _run(world, catalog, truth, out_dir=out, as_of=_READ)
    path = out / tool.REPORT_NAME
    first = path.read_text()
    assert json.loads(first)["status"] == "READ"
    with pytest.raises(tool.Refusal, match="READ"):
        _run(world, catalog, truth, out_dir=out, as_of=_READ)
    assert path.read_text() == first
    out2 = tmp_path / "o2"
    out2.mkdir()
    (out2 / tool.REPORT_NAME).write_text(json.dumps({"status": "INVALID"}))
    with pytest.raises(tool.Refusal, match="INVALID"):
        _run(world, catalog, truth, out_dir=out2)


def test_r23_progress_and_pending_reports_may_be_overwritten(
    world: dict[str, Any], tmp_path: Path
) -> None:
    catalog, truth = _two_days(world)
    out = tmp_path / "o"
    for _ in range(2):
        report, _code = _run(world, catalog, truth, out_dir=out, as_of=_FIRST)
        assert report["status"] == "PROGRESS"
    _drop_truth(truth, _FIRST + dt.timedelta(days=1))
    pending, _ = _run(world, catalog, truth, out_dir=out, as_of=_READ)
    assert pending["status"] == "PENDING_TRUTH"
    assert json.loads((out / tool.REPORT_NAME).read_text())["status"] == "PENDING_TRUTH"


# --------------------------------------------------------------------------- R24 / R25


def test_r24_station_day_without_final_truth_is_counted_not_dropped(
    world: dict[str, Any],
) -> None:
    days = {_FIRST: [base._lax(), base._Ladder("SFO", 75, [base._Rung("lt70", "0.05")])]}
    catalog, truth = base._stage(world["root"], days)
    with truth.open(newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if r["station"] != "SFO"]
    with truth.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report, _ = _run(world, catalog, truth, as_of=_DEADLINE)
    assert report["population"]["no_final_truth"] == 1
    assert report["counts"]["n_takes"] == 3  # LAX only


def test_r25_junk_directory_and_yes_side_degenerate_ask_do_not_void_the_look(
    world: dict[str, Any],
) -> None:
    yes_junk = base._Ladder(
        "LAX", 75, [base._Rung("lt70", "0.05", ask="1.00"), base._Rung("gte72", "0.08")]
    )
    catalog, truth = base._stage(world["root"], {_FIRST: [yes_junk]})
    (catalog / "data" / "order_book_depths" / "unrelated_junk").mkdir(parents=True)
    report, code = _run(world, catalog, truth)
    assert code == 0 and report["status"] == "READ", report.get("invalid_reasons")
    assert report["invalid_reasons"] == []


def test_r25_no_side_degenerate_ask_in_window_still_voids_the_look(world: dict[str, Any]) -> None:
    catalog, truth = base._stage(world["root"], {_FIRST: [base._lax(lt70="1.00")]})
    report, code = _run(world, catalog, truth)
    assert code == 2 and any("degenerate" in r for r in report["invalid_reasons"])


# --------------------------------------------------------------------------- R26


def test_r26_older_ancestor_with_identical_blob_cannot_backdate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    path = repo / "docs" / "evidence" / "m1v3" / "PREREG.json"
    path.parent.mkdir(parents=True)
    base._git(repo, "init", "-q", "-b", "main")
    design = json.loads(base._PREREG_SRC.read_text())
    path.write_text(json.dumps(design, indent=2, sort_keys=True))
    base._git(repo, "add", "docs")
    base._git(repo, "commit", "-q", "-m", "introduce", when=base._COMMIT_ISO)
    (repo / "other.txt").write_text("x")
    base._git(repo, "add", "other.txt")
    base._git(repo, "commit", "-q", "-m", "unrelated", when="2026-11-20T00:00:00+00:00")
    later = base._git(repo, "rev-parse", "HEAD")  # same blob as its parent: not the introducer
    path.write_text(json.dumps({**design, "frozen_sha": later}, indent=2, sort_keys=True))
    world = {"root": tmp_path, "prereg": path}
    catalog, truth = _two_days(world)
    with pytest.raises(tool.Refusal, match="introduc"):
        _run(world, catalog, truth)
    first = base._git(repo, "rev-parse", "HEAD~1")
    path.write_text(json.dumps({**design, "frozen_sha": first}, indent=2, sort_keys=True))
    report, _ = _run(world, catalog, truth)  # the real introducer passes
    assert report["frozen_sha"] == first


def test_r26_docstring_records_trusted_committer_dates() -> None:
    doc = inspect.getdoc(tool.check_freeze_introduction) or ""
    assert "committer date" in doc and "trusted" in doc


# --------------------------------------------------------------------------- R27


def test_r27_last_ask_bin_is_inclusive_so_bins_sum_to_takes() -> None:
    takes = [base._take(_FIRST, ask=a) for a in ("0.90", "0.95", "0.99", "1.00")]
    table = tool.ask_bin_table(takes)
    assert sum(row["n"] for row in table) == len(takes)
    assert table[-1]["n"] == 2


def test_r27_bca_failure_is_reported_and_blocks_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise ValueError("bca failed")

    monkeypatch.setattr(scipy_stats, "bootstrap", boom)
    pooled = tool.pool(base._edge_takes(), base._days(60), resamples=300)
    assert pooled.bca_failed is True and pooled.lb_bca is None
    assert tool.decide(pooled) != "WINNER"
    assert tool.decide(base._pooled(bca_failed=True)) != "WINNER"
    assert tool._pooled_dict(pooled)["bca_failed"] is True


def test_r27_bca_success_is_not_flagged() -> None:
    assert tool.pool(base._edge_takes(), base._days(60), resamples=300).bca_failed is False


def test_r27_report_stats_carry_bca_failed(world: dict[str, Any]) -> None:
    catalog, truth = _two_days(world)
    report, _ = _run(world, catalog, truth)
    assert report["stats"]["bca_failed"] in (True, False)


def test_r27_imported_private_helpers_exist_with_expected_signatures() -> None:
    def params(fn: Any) -> list[str]:
        return list(inspect.signature(fn).parameters)

    m1 = tool.m1
    assert params(m1._bootstrap_stats) == ["s_mat", "n_mat", "resamples", "seed"]
    assert params(m1._index_directories) == ["base", "tally"]
    assert params(m1._first_row) == ["tape", "instrument", "lo_ns", "hi_ns"]
    assert params(m1._levels) == ["body", "key"]
    assert params(m1._refuse_live_root) == ["out_dir"]
    assert params(m1.collect)[:3] == ["catalog_root", "truth", "truth_last_day"]
    assert params(m1.no_ask) == ["body"]
    assert params(m1.window_bounds_ns) == ["climate_day", "window"]
    assert isinstance(m1._VENUE_SUFFIX, str) and m1._NS == 1_000_000_000
    assert callable(m1._Tally) and hasattr(m1._Tally(), "invalid")
    assert params(prereg_check._git) == ["cwd", "args"]
    assert params(prereg_check._canonical) == ["design"]


def test_r27_git_test_helper_ignores_ambient_git_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "bogus"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "bogus"))
    prereg, sha = base._freeze(tmp_path)
    assert len(sha) == 40 and prereg.exists()


def test_r27_prereg_discloses_mnar_exclusion_and_module_documents_cost() -> None:
    design = json.loads(base._PREREG_SRC.read_text())
    assert "MNAR" in design["caveats"] and "dead tail rung" in design["caveats"]
    assert "O(days" in (tool.__doc__ or "")
