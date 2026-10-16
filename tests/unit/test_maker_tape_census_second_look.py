"""MAKER S2 second look, unit C1b -- census guard, read-ledger, counts-only and full modes.

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md section 3 "C1b" and
the coordinator delta items 2.4 / 2.7. Tests use ``tmp_path`` only: never the real
read-ledger, trigger-close file, catalog or derived tree.
"""

from __future__ import annotations

import datetime as dt
import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import maker_search_declarations as reg
from breezy.analysis.maker_tape_census import FirewallRefused

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import maker_tape_census as census_script  # type: ignore[import-not-found]
import maker_tape_census_guard as guard  # type: ignore[import-not-found]

_DOC_A = REPO_ROOT / "docs/evidence/RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16.md"
_REAL_HOME = Path.home()  # captured at import, before the autouse fixture patches it
_SHA1 = reg.SEARCH_DECLARATIONS[0].sha256
_SHA2 = reg.SEARCH_DECLARATIONS[1].sha256
_S = dt.date(2026, 10, 14)
_TODAY = dt.date(2026, 10, 20)
_LEDGER_FIELDS = {"sha", "mode", "from", "to", "rows_chain_sha256", "ts"}
_COUNT_FIELDS = {"station", "climate_day", "reason", "first_seen_ns"}


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Library callers passing None resolve to the defaults under HOME: keep them in tmp."""
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _capture(tmp_path: Path) -> Path:
    capture = tmp_path / "capture"
    (capture / "live").mkdir(parents=True, exist_ok=True)
    return capture


def _run(tmp_path: Path, **overrides: Any) -> Any:
    options: dict[str, Any] = {
        "catalog_root": _capture(tmp_path),
        "work_root": tmp_path / "work",
        "stations": ("LAX",),
        "day_from": _S,
        "day_to": _S,
        "declaration_sha256": _SHA2,
        "counts_only": True,
        "read_ledger": tmp_path / "ledger.jsonl",
        "today": _TODAY,
        "trigger_close": None,
        "trigger_check_token": "lock-token",
    }
    options.update(overrides)
    return census_script.run_census(**options)


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _write_close(tmp_path: Path, end: str, crossed: bool = False) -> Path:
    path = tmp_path / "trigger_close.json"
    path.write_text(json.dumps({"E": end, "crossed": crossed}))
    return path


def test_census_refuses_range_end_after_check_date_minus_two(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"

    with pytest.raises(ValueError, match="today"):
        _run(tmp_path, today=dt.date(2026, 10, 15))  # 10-14 > 10-15 - 2
    assert not ledger.exists()

    _run(tmp_path, today=dt.date(2026, 10, 16))  # 10-14 == 10-16 - 2 is allowed
    assert ledger.exists()

    _run(tmp_path, read_ledger=None)  # None resolves to the default path (under the patched home)
    assert guard.default_read_ledger().exists()


def test_census_records_every_second_look_invocation_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    seen_during_read: list[list[dict[str, Any]]] = []
    real = census_script.list_instance_ids

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen_during_read.append(_lines(ledger))
        return real(*args, **kwargs)

    monkeypatch.setattr(census_script, "list_instance_ids", spy)

    _run(tmp_path)

    (before,) = seen_during_read
    (pre,) = before
    assert set(pre) == _LEDGER_FIELDS
    assert (pre["sha"], pre["mode"], pre["from"], pre["to"]) == (
        _SHA2,
        "counts_only",
        "2026-10-14",
        "2026-10-14",
    )
    pre_line, post_line = _lines(ledger)
    assert pre_line == pre
    assert set(post_line) == _LEDGER_FIELDS
    assert post_line["mode"] == "counts_only_post"
    assert post_line["rows_chain_sha256"] != pre["rows_chain_sha256"]

    def failing(*args: Any, **kwargs: Any) -> Any:
        raise OSError("boom")

    monkeypatch.setattr(census_script, "list_instance_ids", failing)
    with pytest.raises(OSError, match="boom"):
        _run(tmp_path)
    assert len(_lines(ledger)) == 3  # the failed invocation still counts, pre-read line only


def test_post_read_line_commits_the_rows_chain(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"

    run = _run(tmp_path)

    pre, post = _lines(ledger)
    assert pre["rows_chain_sha256"] == guard.GENESIS_CHAIN
    fields = [guard.count_fields(r) for r in run.rows]
    assert post["rows_chain_sha256"] == guard.rows_chain(guard.GENESIS_CHAIN, fields)
    _run(tmp_path, day_to=dt.date(2026, 10, 15))
    third = _lines(ledger)[2]
    assert third["rows_chain_sha256"] == post["rows_chain_sha256"]  # pre carries committed rows


def test_counts_only_file_on_disk_has_exactly_four_fields_and_no_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(guard, "utc_today", lambda: _TODAY)
    monkeypatch.setenv(reg.TRIGGER_CHECK_ENV, "lock-token")
    capture = _capture(tmp_path)
    out = tmp_path / "out" / "counts.jsonl"
    marker = tmp_path / "close_absent.json"
    ledger = tmp_path / "ledger.jsonl"
    sha_file = (
        REPO_ROOT / "docs/evidence/RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16.md"
    )

    code = census_script.main(
        [
            "--from", "2026-10-14",
            "--to", "2026-10-14",
            "--stations", "LAX",
            "--catalog-root", str(capture),
            "--work-root", str(tmp_path / "work"),
            "--search-declaration", str(sha_file),
            "--counts-only",
            "--output", str(out),
            "--read-ledger", str(ledger),
            "--trigger-close", str(marker),
        ]
    )  # fmt: skip

    captured = capsys.readouterr()
    assert code == 0
    rows = _lines(out)
    assert rows and all(set(r) == _COUNT_FIELDS for r in rows)
    assert stat.S_IMODE(out.stat().st_mode) == 0o400
    text = captured.out + captured.err
    for banned in ("census_summary", "STOP", "N_cov", "n_eff", "census_provenance"):
        assert banned not in text


def test_counts_only_exit_is_zero_whatever_s5_unscreened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guard, "utc_today", lambda: _TODAY)
    monkeypatch.setenv(reg.TRIGGER_CHECK_ENV, "lock-token")
    capture = _capture(tmp_path)
    argv = [
        "--from", "2026-10-14",
        "--to", "2026-10-14",
        "--stations", "LAX",
        "--catalog-root", str(capture),
        "--work-root", str(tmp_path / "work"),
        "--search-declaration",
        str(_DOC_A),
        "--read-ledger", str(tmp_path / "ledger.jsonl"),
        "--trigger-close", str(tmp_path / "absent.json"),
    ]  # fmt: skip

    assert _run(tmp_path).summary.s5_unscreened is True  # the full-mode exit would be 4
    assert census_script.main([*argv, "--counts-only"]) == 0
    assert (
        census_script.main([*argv, "--output", str(tmp_path / "o.jsonl")]) == 2
    )  # full: before close


def test_full_census_before_close_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="close"):
        _run(tmp_path, counts_only=False)
    assert not (tmp_path / "ledger.jsonl").exists()


def test_second_full_census_under_doc_a_sha_refused(tmp_path: Path) -> None:
    close = _write_close(tmp_path, "2026-10-16")
    full = {"counts_only": False, "day_to": dt.date(2026, 10, 16), "trigger_close": close}

    with pytest.raises(ValueError, match="to must equal E"):
        _run(tmp_path, **{**full, "day_to": dt.date(2026, 10, 15)})
    with pytest.raises(ValueError, match="from must equal S"):
        _run(tmp_path, **{**full, "day_from": dt.date(2026, 10, 15)})
    assert not (tmp_path / "ledger.jsonl").exists()

    _run(tmp_path, **full)  # the one licensed full run: from == S, to == E
    with pytest.raises(ValueError, match="addendum"):
        _run(tmp_path, **full)
    modes = [line["mode"] for line in _lines(tmp_path / "ledger.jsonl")]
    assert modes == ["full", "full_post"]


def test_census_refuses_any_mode_past_close_e(tmp_path: Path) -> None:
    close = _write_close(tmp_path, "2026-10-15", crossed=True)
    past = {"day_to": dt.date(2026, 10, 16), "trigger_close": close}

    with pytest.raises(ValueError, match="after E"):
        _run(tmp_path, counts_only=True, **past)
    with pytest.raises(ValueError, match="after E"):
        _run(tmp_path, counts_only=False, **past)
    assert not (tmp_path / "ledger.jsonl").exists()

    close.write_text("{not json")
    with pytest.raises(ValueError, match="trigger_close"):
        _run(tmp_path, trigger_close=close)


def test_counts_only_outside_trigger_check_refused(tmp_path: Path) -> None:
    for token in (None, "", "  "):
        with pytest.raises(ValueError, match="trigger"):
            _run(tmp_path, trigger_check_token=token)
    assert not (tmp_path / "ledger.jsonl").exists()

    _run(tmp_path, trigger_check_token="lock-token")  # the C4 check passes the marker
    close = _write_close(tmp_path, "2026-10-16")
    _run(tmp_path, trigger_check_token=None, trigger_close=close)  # after close, within E


def test_read_ledger_default_path_is_pinned() -> None:
    expected = _REAL_HOME / ".local/share/breezy/derived/maker_stage0/search_read_ledger.jsonl"

    assert guard.DEFAULT_READ_LEDGER == expected
    assert (
        census_script._parse_args(["--from", "2026-09-22", "--to", "2026-09-22"]).read_ledger
        == expected
    )


def test_holdout_start_floor_is_max_invoked_day_plus_two(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    base = {"sha": _SHA2, "rows_chain_sha256": guard.GENESIS_CHAIN, "ts": "t"}
    lines = [
        {**base, "mode": "counts_only", "from": "2026-10-14", "to": "2026-10-20"},
        {**base, "mode": "counts_only_post", "from": "2026-10-14", "to": "2026-10-20"},
        {**base, "mode": "counts_only", "from": "2026-10-14", "to": "2026-10-18"},
    ]
    ledger.write_text("".join(json.dumps(x) + "\n" for x in lines))

    assert guard.holdout_start_floor(ledger) == dt.date(2026, 10, 22)
    with pytest.raises(ValueError, match="empty"):
        guard.holdout_start_floor(tmp_path / "missing.jsonl")


def test_firewall_refused_run_writes_no_ledger_line(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"

    with pytest.raises(FirewallRefused):
        _run(tmp_path, declaration_sha256=None)
    with pytest.raises(FirewallRefused):
        _run(tmp_path, declaration_sha256=_SHA1)  # first sha does not clear 10-14
    with pytest.raises(FirewallRefused):
        _run(tmp_path, day_from=dt.date(2026, 10, 13))  # block-1 day under the second sha
    with pytest.raises(FirewallRefused):
        _run(tmp_path, stations=("NYC",))
    assert not ledger.exists()


def test_v1_invocation_unaffected_by_guard(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    v1 = {
        "counts_only": False,
        "day_from": dt.date(2026, 10, 12),
        "day_to": dt.date(2026, 10, 13),
        "declaration_sha256": _SHA1,
        "trigger_check_token": None,
    }

    run = _run(tmp_path, **v1)  # ledger supplied, today far in the past: neither matters
    plain = census_script.run_census(
        catalog_root=tmp_path / "capture",
        work_root=tmp_path / "work",
        stations=("LAX",),
        day_from=dt.date(2026, 10, 12),
        day_to=dt.date(2026, 10, 13),
        declaration_sha256=_SHA1,
    )

    assert not ledger.exists()
    assert run.rows == plain.rows


def test_guard_none_trigger_close_resolves_to_default(tmp_path: Path, _isolated_home: Path) -> None:
    default = guard.default_trigger_close()
    assert default == _isolated_home / ".local/share/breezy/derived/maker_stage0/trigger_close.json"
    default.parent.mkdir(parents=True)
    default.write_text(json.dumps({"E": "2026-10-15", "crossed": False}))

    with pytest.raises(ValueError, match="after E"):
        _run(tmp_path, trigger_close=None, day_to=dt.date(2026, 10, 16))
    assert not (tmp_path / "ledger.jsonl").exists()


def test_counts_only_refuses_to_overwrite_existing_file(tmp_path: Path) -> None:
    out = tmp_path / "counts.jsonl"
    rows = [
        {"station": "LAX", "climate_day": "2026-10-14", "reason": "COVERED", "first_seen_ns": 1}
    ]

    guard.write_counts_only(out, rows)
    first = out.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        guard.write_counts_only(out, rows)
    assert out.read_bytes() == first
    assert not list(tmp_path.glob("*.tmp"))
