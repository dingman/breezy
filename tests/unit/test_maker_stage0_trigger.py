"""MAKER-S2 second look (C4): the trigger tool `check` / `close` (census faked)."""

from __future__ import annotations

import datetime as dt
import fcntl
import functools
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import maker_tape_census as core
from breezy.analysis.maker_search_declarations import SEARCH_DECLARATIONS, TRIGGER_CHECK_ENV
from scripts.analysis import maker_stage0_trigger as trig
from scripts.analysis import maker_tape_census_guard as guard
from scripts.analysis.maker_stage0_probe_core import listing_abstain
from scripts.analysis.maker_stage0_rule import listed_in_time
from scripts.analysis.maker_stage0_trigger_rule import first_crossing

ROW = SEARCH_DECLARATIONS[1]
S, CAP = ROW.first_day, ROW.last_day
STATIONS = ("LAX", "MDW", "MIA", "SFO")
_NS = 1_000_000_000
_ONE = dt.timedelta(days=1)

Rows = Callable[[dt.date], list[dict[str, Any]]]


def _ns(day: dt.date, hour: int) -> int:
    return int(dt.datetime.combine(day, dt.time(hour), tzinfo=dt.UTC).timestamp()) * _NS


def _covered(day: dt.date, *, n: int = 4, late: bool = False) -> list[dict[str, Any]]:
    hour = 13 if late else 6  # D-1 06:00Z is in time, D-1 13:00Z is late
    return [
        {"station": s, "climate_day": day.isoformat(), "reason": "COVERED",
         "first_seen_ns": _ns(day - _ONE, hour)}
        for s in STATIONS[:n]
    ]  # fmt: skip


def _line(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


class Env:
    """A work root, ledger and fake census; every census call is recorded."""

    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.work, self.close = tmp / "trigger", tmp / "trigger_close.json"
        self.ledger = tmp / "ledger.jsonl"
        self.calls: list[dict[str, Any]] = []
        self.rows_for: Rows = _covered
        monkeypatch.setattr(trig, "run_counts_only", self.fake)
        monkeypatch.setattr(
            trig, "first_crossing", functools.partial(first_crossing, threshold=3.0)
        )

    def fake(
        self, *, day_from: dt.date, day_to: dt.date, out: Path, env: dict[str, str], **kw: Any
    ) -> int:
        self.calls.append({"from": day_from, "to": day_to, "env": env, **kw})
        days = [day_from + dt.timedelta(days=i) for i in range((day_to - day_from).days + 1)]
        guard.write_counts_only(out, [r for d in days for r in self.rows_for(d)])
        return 0

    def run(self, cmd: str, *extra: str, today: str | None = None) -> int:
        args = ["--work-root", str(self.work), "--trigger-close", str(self.close),
                "--read-ledger", str(self.ledger), *extra]  # fmt: skip
        if today is not None:
            args += ["--today", today]
        return trig.main([cmd, *args])

    def rows(self) -> list[dict[str, Any]]:
        path = self.work / "trigger_rows.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def ledger_lines(self, *tos: dt.date) -> None:
        with self.ledger.open("w") as fh:
            for to in tos:
                line = {
                    "sha": ROW.sha256, "mode": "counts_only", "from": S.isoformat(),
                    "to": to.isoformat(), "rows_chain_sha256": guard.GENESIS_CHAIN, "ts": "t",
                }  # fmt: skip
                fh.write(json.dumps(line, sort_keys=True) + "\n")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


def test_check_stops_at_first_crossing_inside_a_catch_up_batch(env: Env) -> None:
    assert env.run("check", today="2026-10-21") == 0  # batch S..S+5; 1.6/day, T=3.0
    rows = env.rows()
    assert rows[-1] == {"CROSSED": True, "E": (S + _ONE).isoformat()}
    assert {r["climate_day"] for r in rows[:-1]} == {S.isoformat(), (S + _ONE).isoformat()}
    assert len(rows) == 9  # 2 days x 4 stations + the terminal row; later days discarded
    assert len(env.calls) == 1 and env.calls[0]["to"] == S + 5 * _ONE


def test_post_crossing_check_refused(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    assert env.run("check", today="2026-10-21") == 0
    env.calls.clear()
    capsys.readouterr()
    assert env.run("check", today="2026-10-25") == 2
    assert "crossed" in capsys.readouterr().err.lower()
    assert env.calls == []


def test_trigger_counts_only_covered_listed_in_time(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(trig, "first_crossing", first_crossing)  # real T=34: never crosses here

    def rows(day: dt.date) -> list[dict[str, Any]]:
        late = _covered(day, n=2, late=True)[1:]  # covered but listed after D-1 12:00Z
        other = [{**r, "reason": "NO_TAPE"} for r in _covered(day, n=4)[2:3]]
        return _covered(day, n=1) + late + other

    env.rows_for = rows
    assert env.run("check", today="2026-10-16") == 0  # to = S
    assert "n_eff=1.000 crossed=False" in capsys.readouterr().out
    assert len(env.rows()) == 3  # every row is recorded; only the counted one scores


def test_listed_in_time_boundary_exactly_d_minus_1_1200z_counts() -> None:
    edge = _ns(S - _ONE, 12)
    assert listed_in_time(edge, S) is True
    assert listed_in_time(edge + 1, S) is False
    assert listed_in_time(None, S) is False


def test_listed_in_time_agrees_with_probe_listing_abstain() -> None:
    for day in (S, S + 5 * _ONE):
        start = core.maker_window_ns(climate_day=day, std_utc_offset_hours=-8.0).start_ns
        for ns in (None, start - _NS, start - 1, start, start + 1, start + _NS):
            assert listed_in_time(ns, day) is (not listing_abstain(ns, start))


def test_close_hashes_only_rows_up_to_e(env: Env) -> None:
    env.work.mkdir(parents=True)
    keep = [*_covered(S, n=1), *_covered(S + _ONE, n=1)]
    body = [_line(r) for r in keep]
    extra = _line(_covered(S + 2 * _ONE, n=1)[0])
    crossed = json.dumps({"CROSSED": True, "E": (S + _ONE).isoformat()})
    (env.work / "trigger_rows.jsonl").write_text("\n".join([*body, crossed, extra]) + "\n")
    env.ledger_lines(S + 3 * _ONE)
    copy = env.work.parent / "repo_rows.jsonl"
    assert env.run("close", "--repo-copy", str(copy)) == 0
    out = json.loads(env.close.read_text())
    assert out["rows_sha256"] == hashlib.sha256(("\n".join(body) + "\n").encode()).hexdigest()
    assert out["E"] == (S + _ONE).isoformat() and out["crossed"] is True
    assert out["rows_chain_sha256"] == guard.rows_chain(guard.GENESIS_CHAIN, keep)
    assert copy.read_text() == "\n".join(body) + "\n"
    assert env.run("close") == 2  # never overwrites an existing close


def test_close_forfeiture_matches_read_ledger(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    assert env.run("check", today="2026-10-21") == 0
    env.ledger_lines(S + 5 * _ONE, S + 3 * _ONE)  # max invoked day = S+5 -> 4 * 6
    capsys.readouterr()
    assert env.run("close") == 0
    assert "forfeiture=24" in capsys.readouterr().out


def test_close_at_cap_without_crossing(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trig, "first_crossing", lambda rows: None)
    env.rows_for = lambda d: _covered(d, n=1)
    assert env.run("close") == 2  # nothing checked yet
    assert env.run("check", today="2026-11-17") == 0
    assert (env.work / "checked_through.txt").read_text().strip() == CAP.isoformat()
    env.ledger_lines(CAP)
    assert env.run("close") == 0
    out = json.loads(env.close.read_text())
    assert out["E"] == CAP.isoformat() and out["crossed"] is False
    assert set(out) == {"E", "crossed", "rows_sha256", "rows_chain_sha256", "closed_at"}


def test_check_refuses_when_lock_held(env: Env) -> None:
    env.work.mkdir(parents=True)
    with (env.work / "trigger.lock").open("a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert env.run("check", today="2026-10-21") == 2
    assert env.calls == []


def test_check_refuses_when_lock_file_vanishes(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    real = fcntl.flock

    def flock_then_unlink(handle: Any, flags: int) -> None:
        real(handle, flags)
        (env.work / "trigger.lock").unlink()

    monkeypatch.setattr(fcntl, "flock", flock_then_unlink)
    assert env.run("check", today="2026-10-21") == 2
    assert env.calls == []


def test_check_passes_nonce_token_and_restores_env(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(TRIGGER_CHECK_ENV, "outer")
    seen: list[str] = []

    def spy(**kw: Any) -> int:
        seen.append((env.work / "trigger.lock").read_text().strip())
        return env.fake(**kw)

    monkeypatch.setattr(trig, "run_counts_only", spy)
    assert env.run("check", today="2026-10-21") == 0
    token = env.calls[0]["env"][TRIGGER_CHECK_ENV]
    assert token == seen[0] and len(token) >= 16 and token != "outer"
    assert os.environ[TRIGGER_CHECK_ENV] == "outer"


def test_check_nothing_to_do_before_s_plus_two(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    assert env.run("check", today=(S + _ONE).isoformat()) == 0  # to = S-1 < S
    assert "nothing to check" in capsys.readouterr().out
    assert env.calls == []
