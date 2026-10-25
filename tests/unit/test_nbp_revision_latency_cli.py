"""RED-first tests for the LAT-1 scorer shell and core (plan r3 + r3.1).

Synthetic books only: no tape, no NBP partition and no network is read. Every stage must refuse
while ``PREREG_SHA256`` is UNFROZEN, and the exit fixture fills INSIDE the W window.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import math
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import scripts.analysis.nbp_revision_latency as cli
import scripts.analysis.nbp_revision_latency_core as core
from breezy.analysis.revision_latency import LeakGuardError
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.quantile_density import Rung
from breezy.strategy.no_ladder_maker.pno_store import VectorChain
from breezy.strategy.weather_common.revision_gate import (
    NS,
    W_NS,
    BookRow,
    BookSeries,
    ExitBid,
    GapSpan,
    SignedBands,
)

_ROOT = Path(__file__).resolve().parents[2]
_DAY = dt.date(2026, 10, 20)
_NAN = math.nan


def _ns(stamp: str) -> int:
    parsed = dt.datetime.fromisoformat(stamp)
    return int(parsed.replace(tzinfo=dt.UTC).timestamp()) * NS


def _vector(avail: int, runtime: int, day: dt.date = _DAY) -> ForecastQuantileVector:
    return ForecastQuantileVector(
        q10=60.0,
        q25=65.0,
        q50=70.0,
        q75=75.0,
        q90=80.0,
        mean=70.0,
        sd=3.0,
        available_at_ns=avail,
        cycle_runtime_ns=runtime,
        climate_day=day,
        model_version="v5",
    )


_PREV_RUNTIME = _ns("2026-10-19T13:00:00")
_PREV_AVAIL = _ns("2026-10-19T14:05:00")
_CUR_RUNTIME = _ns("2026-10-19T19:00:00")
_CUR_AVAIL = _ns("2026-10-19T20:05:00")
_T_DEC = _CUR_AVAIL + core.L_PRIMARY_NS + 1
_T_EXIT = _T_DEC + core.X_PRIMARY_NS
_BANDS = SignedBands("r1", "r2", 0.30, -0.20)


def _book_rows(*, exit_in_window: bool = True) -> list[BookRow]:
    rows = [
        BookRow(_CUR_AVAIL - 1, 0.30, 0.35),  # the ask when the file became available
        BookRow(_T_DEC - 60 * NS, 0.40, 0.45),  # the entry book
        BookRow(_T_EXIT - 5, _NAN, 0.55),  # the bid has vanished at t_exit
    ]
    if exit_in_window:
        rows.append(BookRow(_T_EXIT + 5 * 60 * NS, 0.62, 0.66))  # fills INSIDE W, not at t_exit
    return rows


def _data(
    rows: list[BookRow] | None = None,
    *,
    later_vector_at: int | None = None,
    gaps: tuple[GapSpan, ...] = (),
    heartbeat: tuple[int, ...] | None = None,
    cur_runtime: int = _CUR_RUNTIME,
    cur_avail: int = _CUR_AVAIL,
) -> tuple[core.StationDayData, ForecastQuantileVector]:
    prev = _vector(_PREV_AVAIL, _PREV_RUNTIME)
    cur = _vector(cur_avail, cur_runtime)
    vectors = [prev, cur]
    if later_vector_at is not None:
        vectors.append(_vector(later_vector_at, cur_runtime + 1))
    chain = VectorChain(
        tuple(v.available_at_ns for v in vectors),
        tuple(vectors),
        tuple(v.available_at_ns for v in vectors),
    )
    series = BookSeries(_book_rows() if rows is None else rows)
    beat = (
        (cur_avail - 1, cur_avail + core.L_PRIMARY_NS - 30 * NS, _T_EXIT, _T_EXIT + 5 * 60 * NS)
        if heartbeat is None
        else heartbeat
    )
    data = core.StationDayData(
        station="LAX",
        climate_day=_DAY,
        chain=chain,
        ladder=(Rung("r1", 70, 74), Rung("r2", 75, None)),
        calibration=None,  # type: ignore[arg-type]
        latitude_deg=33.9,
        offset_hours=-8.0,
        books={"r1": series},
        gaps={"r1": gaps},
        heartbeat=beat,
    )
    return data, cur


def _ctx(
    cur: ForecastQuantileVector,
    *,
    stratum: str | None = core.TRADABLE_STRATUM,
    bands: SignedBands | None = _BANDS,
    reason: str | None = None,
) -> core.EventContext:
    return core.EventContext("LAX", _DAY, stratum, cur, bands, reason)


def _score(data: core.StationDayData, ctx: core.EventContext, **kw: object) -> core.Take | str:
    return core.score_event(data, ctx, core.VARIANTS[0], 0.13, **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------ fees and markout


def test_markout_charges_two_cent_rounded_fees_before_the_fee_drift() -> None:
    pre = _ns("2026-09-16T16:50:00")
    exit_bid = ExitBid(bid=0.60, ts_ns=pre + NS, missing_exit=False, filled_inside_window=False)
    result = cli_markout(ask=0.50, t_dec=pre, exit_bid=exit_bid)
    assert isinstance(result, core.MarkoutResult)
    # 0.06*0.50*0.50 = 0.015 -> 0.02 half-even; 0.06*0.60*0.40 = 0.0144 -> 0.01
    assert result.entry_fee == pytest.approx(0.02)
    assert result.exit_fee == pytest.approx(0.01)
    assert result.pnl == pytest.approx(0.60 - 0.50 - 0.02 - 0.01)


def test_markout_is_refused_inside_the_ambiguous_fee_window_and_priced_after_it() -> None:
    ambiguous = _ns("2026-09-17T00:00:00")
    bid = ExitBid(0.60, ambiguous + NS, False, False)
    assert cli_markout(ask=0.50, t_dec=ambiguous, exit_bid=bid) == core.DROP_ENTRY_FEE
    pre = _ns("2026-09-16T16:50:00")
    assert cli_markout(ask=0.50, t_dec=pre, exit_bid=ExitBid(0.60, ambiguous, False, False)) == (
        core.DROP_EXIT_FEE
    )
    post = _ns("2026-09-17T17:00:00")
    after = cli_markout(ask=0.45, t_dec=post, exit_bid=ExitBid(0.50, post + NS, False, False))
    assert isinstance(after, core.MarkoutResult)
    assert after.entry_fee == pytest.approx(0.02)  # 0.0695*0.45*0.55 = 0.0172 -> 0.02
    assert after.exit_fee == pytest.approx(0.02)  # 0.0695*0.5*0.5 = 0.0174 -> 0.02


def test_missing_exit_is_a_zero_bid_loss_with_one_fee_and_never_a_drop() -> None:
    pre = _ns("2026-09-16T16:50:00")
    result = cli_markout(ask=0.40, t_dec=pre, exit_bid=ExitBid(0.0, None, True, False))
    assert isinstance(result, core.MarkoutResult)
    assert result.missing_exit is True
    assert result.exit_fee == 0.0
    assert result.pnl == pytest.approx(-0.40 - 0.01)  # 0.06*0.4*0.6 = 0.0144 -> 0.01


def test_one_tick_worse_stress_lowers_the_pnl() -> None:
    pre = _ns("2026-09-16T16:50:00")
    bid = ExitBid(0.60, pre + NS, False, False)
    base = cli_markout(ask=0.50, t_dec=pre, exit_bid=bid)
    worse = cli_markout(ask=0.50, t_dec=pre, exit_bid=bid, tick=core.STRESS_TICK)
    assert isinstance(base, core.MarkoutResult) and isinstance(worse, core.MarkoutResult)
    assert worse.pnl < base.pnl
    assert worse.ask == pytest.approx(0.51)
    assert worse.bid == pytest.approx(0.59)


def cli_markout(**kw: object) -> core.MarkoutResult | str:
    return core.markout_pnl(
        ask=kw["ask"],  # type: ignore[arg-type]
        t_dec_ns=kw["t_dec"],  # type: ignore[arg-type]
        exit_bid=kw["exit_bid"],  # type: ignore[arg-type]
        tick=kw.get("tick", 0.0),  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- permit


def test_permit_must_hold_at_t_dec_t_exit_and_t_exit_plus_w() -> None:
    t_dec = _ns("2026-10-20T02:00:00")  # the permit (16:50Z + 10 h) closes at 02:50Z
    assert core.permit_ok(t_dec, t_dec + 10 * 60 * NS) is True
    assert core.permit_ok(t_dec, t_dec + 25 * 60 * NS) is False  # only t_exit + W is outside
    assert core.permit_ok(t_dec, t_dec + 55 * 60 * NS) is False  # t_exit itself is outside
    assert core.permit_ok(_ns("2026-10-19T16:49:00"), _ns("2026-10-19T17:10:00")) is False
    assert W_NS == 30 * 60 * NS


# --------------------------------------------------------------------------- scoring


def test_a_19z_take_exits_inside_the_w_window_not_at_t_exit() -> None:
    data, cur = _data()
    take = _score(data, _ctx(cur))
    assert isinstance(take, core.Take)
    assert take.rung_id == "r1"
    assert take.t_dec_ns == _T_DEC
    assert take.ask == pytest.approx(0.45)
    assert take.bid == pytest.approx(0.62)
    assert take.filled_inside_window is True
    assert take.missing_exit is False
    # 0.62 - 0.45 - fee(0.45)=0.02 - fee(0.62)=0.02
    assert take.pnl == pytest.approx(0.13)
    assert take.stress_pnl is not None and take.stress_pnl < take.pnl
    mix = core.exit_mix([take])
    assert mix["exit_in_window"]["n"] == 1
    assert mix["exit_at_t_exit"]["n"] == 0
    assert mix["missing_exit"]["n"] == 0


def test_no_bid_anywhere_in_the_window_is_a_flagged_missing_exit_take() -> None:
    data, cur = _data(_book_rows(exit_in_window=False))
    take = _score(data, _ctx(cur))
    assert isinstance(take, core.Take)
    assert take.missing_exit is True
    assert take.bid == 0.0
    assert take.pnl < -0.45


def test_a_01z_event_is_never_eligible_and_13z_is_report_only() -> None:
    data, cur = _data()
    assert _score(data, _ctx(cur, stratum="01Z_D")) == core.DROP_REPORT_ONLY
    assert _score(data, _ctx(cur, stratum="13Z_D-1")) == core.DROP_REPORT_ONLY
    assert core.stratum_of(_ns("2026-10-20T01:00:00"), _DAY) == "01Z_D"
    assert core.stratum_of(_CUR_RUNTIME, _DAY) == core.TRADABLE_STRATUM
    assert core.stratum_of(_ns("2026-10-19T07:00:00"), _DAY) is None


def test_drop_reasons_cover_tau_superseded_gap_heartbeat_rule_b_and_permit() -> None:
    data, cur = _data()
    assert _score(data, _ctx(cur, bands=SignedBands("r1", None, 0.05, None))) == core.DROP_BELOW_TAU
    assert _score(data, _ctx(cur, bands=SignedBands(None, "r2", None, -0.2))) == core.DROP_NO_R_PLUS
    assert _score(data, _ctx(cur, reason=core.DROP_NO_PREV)) == core.DROP_NO_PREV
    later, cur_later = _data(later_vector_at=_CUR_AVAIL + 60 * NS)
    assert _score(later, _ctx(cur_later)) == core.DROP_SUPERSEDED
    gapped, cur_gap = _data(gaps=(GapSpan(_T_DEC - NS, _T_DEC + NS, True),))
    assert _score(gapped, _ctx(cur_gap)) == core.DROP_BOOK_GAP
    dead, cur_dead = _data(heartbeat=(_T_DEC - 3600 * NS,))
    assert _score(dead, _ctx(cur_dead)) == core.DROP_BOOK_HEARTBEAT
    expensive, cur_exp = _data([BookRow(_T_DEC - NS, 0.96, 0.98)])
    assert _score(expensive, _ctx(cur_exp)) == core.DROP_ASK_ABOVE_CAP
    no_ask, cur_na = _data([BookRow(_T_DEC - NS, 0.40, _NAN)])
    assert _score(no_ask, _ctx(cur_na)) == core.DROP_NO_ASK
    moved, cur_mv = _data([BookRow(_CUR_AVAIL - 1, 0.30, 0.35), BookRow(_T_DEC - NS, 0.69, 0.71)])
    assert _score(moved, _ctx(cur_mv)) == core.DROP_RULE_B_MOVED
    assert _score(moved, _ctx(cur_mv), apply_rule_b=False) != core.DROP_RULE_B_MOVED
    unref, cur_ur = _data([BookRow(_T_DEC - NS, 0.40, 0.45)])
    assert _score(unref, _ctx(cur_ur)) == core.DROP_RULE_B_REFERENCE


def test_a_late_release_whose_exit_window_leaves_the_permit_is_a_permit_drop() -> None:
    avail = _ns("2026-10-20T01:30:00")  # t_exit + W lands after the 02:50Z close
    runtime = avail - 65 * 60 * NS
    late, cur = _data(
        [BookRow(avail - 1, 0.30, 0.35), BookRow(avail + 200 * NS, 0.40, 0.45)],
        cur_avail=avail,
        cur_runtime=runtime,
        heartbeat=(avail - 1, avail + 250 * NS),
    )
    assert _score(late, _ctx(cur)) == core.DROP_PERMIT


def test_leak_guard_4_is_fatal_for_a_release_earlier_than_the_publication_floor() -> None:
    data, cur = _data(cur_runtime=_CUR_AVAIL - 30 * 60 * NS)
    with pytest.raises(LeakGuardError) as raised:
        _score(data, _ctx(cur))
    assert raised.value.guard == 4


def test_census_identity_holds_end_to_end_and_a_broken_census_is_fatal() -> None:
    data, cur = _data()
    census = core.Census()
    outcomes = [
        _score(data, _ctx(cur)),
        _score(data, _ctx(cur, stratum="01Z_D")),
        _score(data, _ctx(cur, reason=core.DROP_NO_PREV)),
        _score(data, _ctx(cur, bands=SignedBands("r1", None, 0.05, None))),
    ]
    for outcome in outcomes:
        census.record(outcome)
    report = census.report()
    assert report["population"] == 4
    assert report["takes"] == 1
    assert sum(report["drops"].values()) == 3
    census.population += 1
    with pytest.raises(LeakGuardError) as raised:
        census.check()
    assert raised.value.guard == 10


def _placebo_rows() -> list[BookRow]:
    avail = _CUR_AVAIL
    return _book_rows() + [
        BookRow(avail - 90 * 60 * NS, 0.20, 0.25),
        BookRow(avail - 80 * 60 * NS, 0.22, 0.26),
    ]


def _placebo_heartbeat() -> tuple[int, ...]:
    shifted = _T_DEC - core.PRE_RELEASE_SHIFT_NS
    points = {
        _CUR_AVAIL - core.PRE_RELEASE_SHIFT_NS - 1,
        _CUR_AVAIL - 1,
        shifted - 30 * NS,
        shifted + core.X_PRIMARY_NS,
        _T_DEC - 30 * NS,
        _T_EXIT,
        _T_EXIT + 5 * 60 * NS,
    }
    return tuple(sorted(points))


def test_the_pre_release_placebo_take_is_scored_look_ahead_and_diagnostic() -> None:
    data, cur = _data(_placebo_rows(), heartbeat=_placebo_heartbeat())
    run = core.VariantRun()
    core.score_station_day(data, [_ctx(cur)], core.VARIANTS[0], 0.13, run, apply_rule_b=False)
    assert run.census.takes == 1
    assert len(run.takes) == 1
    assert len(run.placebo_takes) == 1
    placebo = run.placebo_takes[0]
    assert placebo.t_dec_ns == _T_DEC - core.PRE_RELEASE_SHIFT_NS
    assert placebo.ask == pytest.approx(0.25)
    assert placebo.bid == pytest.approx(0.22)
    # 0.22 - 0.25 - fee(0.25)=0.01 - fee(0.22)=0.01
    assert placebo.pnl == pytest.approx(-0.05)


def test_a_dropped_pre_release_placebo_leaves_no_placebo_take() -> None:
    data, cur = _data()
    run = core.VariantRun()
    core.score_station_day(data, [_ctx(cur)], core.VARIANTS[0], 0.13, run, apply_rule_b=False)
    assert len(run.takes) == 1
    assert run.placebo_takes == []


# ---------------------------------------------------------------------------- stages


def _patched_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "rung_deltas", lambda **_kw: {"r1": 0.30, "r2": -0.20})


def test_stage_1_and_stage_0_run_end_to_end_on_synthetic_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    data, _cur = _data()
    tau = core.TauValues(0.13, 0.18, "test")

    def loader(station: str, day: dt.date) -> core.StationDayData | None:
        return data if (station, day) == ("LAX", _DAY) else None

    report = core.run_stage_1(
        loader, ("LAX", "MIA"), (_DAY, dt.date(2026, 10, 27)), tau, iterations=20
    )
    assert report["counts"]["excluded_day"] == 1  # D = 10-27 is excluded and counted
    assert report["counts"]["no_station_day_data"] == 1
    for name, variant in report["variants"].items():
        census = variant["census"]
        assert census["population"] == census["takes"] + sum(census["drops"].values()), name
    assert report["variants"]["V0"]["census"]["takes"] == 1
    assert report["selection"]["status"] == "AUDIT-PENDING"  # one lucky take trips an audit trigger
    assert report["selection"]["chosen"] == ()

    stage0 = core.run_stage_0(loader, ("LAX",), (_DAY,), tau, iterations=20)
    assert stage0["census_after_rule_b"]["takes"] == 1
    assert stage0["kill_cost"]["after_rule_b"]["verdict"] == "INCONCLUSIVE"
    assert stage0["mechanism"]["n_events"] >= 1


def test_stage_tau_uses_only_19z_cycles_available_before_the_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    data, _cur = _data()

    def loader(_station: str, _day: dt.date) -> core.StationDayData:
        return data

    before = core.run_stage_tau(loader, ("LAX",), (_DAY,), freeze_ns=_CUR_AVAIL + 1)
    assert before["tau"]["n_input"] == 1
    with pytest.raises(ValueError):  # a cycle available AT the freeze does not exist yet
        core.run_stage_tau(loader, ("LAX",), (_DAY,), freeze_ns=_CUR_AVAIL)


# ----------------------------------------------------------------------- pins and CLI


def _args(stage: str, start: str, end: str, **extra: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "stage": stage,
        "start": dt.date.fromisoformat(start),
        "end": dt.date.fromisoformat(end),
        "prereg": None,
        "selection": None,
        "artefact": None,
        "derived_root": None,
        "tape_root": None,
        "output": None,
        "freeze_utc": None,
        "tau_primary": None,
        "tau_alt": None,
    }
    base.update(extra)
    return argparse.Namespace(**base)


def test_stages_0_1_2_refuse_while_the_prereg_pin_is_unfrozen(tmp_path: Path) -> None:
    assert cli.PREREG_SHA256 == cli.UNFROZEN
    prereg = tmp_path / "prereg.md"
    prereg.write_text("DEFAULT_SPLITS holdout_start", encoding="utf-8")
    for stage in ("0", "1", "2"):
        argv = ["--stage", stage, "--start", "2026-10-13", "--end", "2026-10-26"]
        assert cli.main([*argv, "--prereg", str(prereg)]) == 2, stage
    with pytest.raises(cli.PinRefused):
        cli.require_prereg(prereg)


def test_stage_tau_is_exempt_from_the_prereg_pin_but_keeps_the_confirm_day_refusal() -> None:
    assert cli.PREREG_SHA256 == cli.UNFROZEN
    ok = _args(
        "tau",
        "2026-10-13",
        "2026-10-26",
        artefact=Path("a.json"),
        freeze_utc="2026-10-26T00:00:00+00:00",
    )
    assert cli.preflight(ok) is None  # no prereg text yet; the pin is not consulted
    late = _args(
        "tau",
        "2026-10-20",
        "2026-10-28",
        artefact=Path("a.json"),
        freeze_utc="2026-10-26T00:00:00+00:00",
    )
    with pytest.raises(cli.ConfirmDayRefused):
        cli.preflight(late)
    for stage in ("0", "1"):
        with pytest.raises(cli.PinRefused):
            cli.preflight(_args(stage, "2026-10-13", "2026-10-26"))


def test_preflight_refuses_naive_freeze_missing_artefact_and_tau_below_the_floors(
    tmp_path: Path,
) -> None:
    artefact = tmp_path / "a.json"
    artefact.write_text("{}", encoding="utf-8")
    common = {"artefact": artefact}
    with pytest.raises(cli.RefusalError, match="tz-aware"):
        cli.preflight(
            _args("tau", "2026-10-13", "2026-10-26", freeze_utc="2026-10-26T00:00:00", **common)
        )
    with pytest.raises(cli.RefusalError, match="freeze"):
        cli.preflight(_args("tau", "2026-10-13", "2026-10-26", **common))
    with pytest.raises(cli.RefusalError, match="artefact"):
        cli.preflight(
            _args("tau", "2026-10-13", "2026-10-26", freeze_utc="2026-10-26T00:00:00+00:00")
        )


def test_tau_values_below_the_floors_are_refused_for_stages_0_and_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = tmp_path / "prereg.md"
    prereg.write_text("DEFAULT_SPLITS holdout_start", encoding="utf-8")
    monkeypatch.setattr(cli, "PREREG_SHA256", hashlib.sha256(prereg.read_bytes()).hexdigest())
    artefact = tmp_path / "a.json"
    artefact.write_text("{}", encoding="utf-8")
    base = {"prereg": prereg, "artefact": artefact}
    for primary, alt in ((0.05, 0.18), (0.13, 0.10), (None, 0.18)):
        with pytest.raises(cli.RefusalError, match="tau"):
            cli.preflight(
                _args("1", "2026-10-13", "2026-10-26", tau_primary=primary, tau_alt=alt, **base)
            )


def test_main_returns_2_only_for_policy_refusals_and_lets_bugs_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = ["--stage", "tau", "--start", "2026-10-13", "--end", "2026-10-26"]
    for refusal in (LeakGuardError(5, "x"), cli.PinRefused("p"), cli.UsageRefused("u")):

        def _refuse(*_a: object, _raised: Exception = refusal) -> None:
            raise _raised

        monkeypatch.setattr(cli, "preflight", _refuse)
        assert cli.main(argv) == 2
    assert issubclass(cli.ConfirmDayRefused, cli.RefusalError)
    assert issubclass(cli.StageRefused, cli.RefusalError)

    def _bug(*_a: object) -> None:
        raise ValueError("a real bug with a message")

    monkeypatch.setattr(cli, "preflight", _bug)
    with pytest.raises(ValueError, match="real bug"):
        cli.main(argv)


def test_the_address_space_cap_is_set_before_any_file_is_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli.resource, "setrlimit", lambda *_a: calls.append("cap"))
    args = _args("tau", "2026-10-13", "2026-10-26", artefact=tmp_path / "absent.json")
    with pytest.raises(FileNotFoundError):
        cli._run(args, None)
    assert calls == ["cap"]


def test_stage_0_1_tau_values_must_equal_the_tau_recorded_in_the_prereg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = tmp_path / "prereg.md"
    prereg.write_text("DEFAULT_SPLITS holdout_start\nTAU_PRIMARY=0.14 TAU_ALT=0.19\n", "utf-8")
    monkeypatch.setattr(cli, "PREREG_SHA256", hashlib.sha256(prereg.read_bytes()).hexdigest())
    artefact = tmp_path / "a.json"
    artefact.write_text("{}", encoding="utf-8")
    base = {"prereg": prereg, "artefact": artefact}
    ok = _args("1", "2026-10-13", "2026-10-26", tau_primary=0.14, tau_alt=0.19, **base)
    assert cli.preflight(ok) is not None
    assert cli._tau_values(ok, cli.prereg_tau(prereg.read_text("utf-8"))).source == "prereg_text"
    with pytest.raises(cli.RefusalError, match="prereg"):
        cli.preflight(
            _args("0", "2026-10-13", "2026-10-26", tau_primary=0.15, tau_alt=0.19, **base)
        )
    prereg.write_text("DEFAULT_SPLITS holdout_start\n", "utf-8")
    monkeypatch.setattr(cli, "PREREG_SHA256", hashlib.sha256(prereg.read_bytes()).hexdigest())
    with pytest.raises(cli.RefusalError, match="TAU_PRIMARY"):
        cli.preflight(ok)


def test_a_mismatched_prereg_sha_is_refused_and_a_matching_one_returns_the_text(
    tmp_path: Path,
) -> None:
    prereg = tmp_path / "prereg.md"
    prereg.write_text("frozen text", encoding="utf-8")
    digest = hashlib.sha256(prereg.read_bytes()).hexdigest()
    assert cli.require_prereg(prereg, pin=digest) == "frozen text"
    with pytest.raises(cli.PinRefused):
        cli.require_prereg(prereg, pin="0" * 64)
    with pytest.raises(cli.PinRefused):
        cli.require_prereg(None, pin=digest)


def test_selection_pin_mismatch_and_a_missing_artefact_are_refused(tmp_path: Path) -> None:
    artefact = tmp_path / "selection.json"
    artefact.write_text("{}", encoding="utf-8")
    digest = hashlib.sha256(artefact.read_bytes()).hexdigest()
    cli.require_selection(artefact, pin=digest)
    with pytest.raises(cli.PinRefused):
        cli.require_selection(artefact, pin="f" * 64)
    with pytest.raises(cli.PinRefused):
        cli.require_selection(None, pin=digest)
    with pytest.raises(cli.PinRefused):
        cli.require_selection(artefact)  # SELECTION_SHA256 is UNSET


def test_stage_2_without_a_selection_artefact_is_refused_even_with_a_valid_prereg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = tmp_path / "prereg.md"
    prereg.write_text("DEFAULT_SPLITS holdout_start", encoding="utf-8")
    monkeypatch.setattr(cli, "PREREG_SHA256", hashlib.sha256(prereg.read_bytes()).hexdigest())
    argv = ["--stage", "2", "--start", "2026-10-28", "--end", "2026-10-28", "--prereg", str(prereg)]
    assert cli.main(argv) == 2
    selection = tmp_path / "selection.json"
    selection.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "SELECTION_SHA256", hashlib.sha256(selection.read_bytes()).hexdigest())
    assert cli.main([*argv, "--selection", str(selection)]) == 2  # stage 2 itself is a stub


def test_pre_stage_2_stages_refuse_any_confirm_period_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = tmp_path / "prereg.md"
    prereg.write_text("DEFAULT_SPLITS holdout_start", encoding="utf-8")
    monkeypatch.setattr(cli, "PREREG_SHA256", hashlib.sha256(prereg.read_bytes()).hexdigest())
    for stage in ("tau", "0", "1"):
        argv = [
            "--stage",
            stage,
            "--start",
            "2026-10-20",
            "--end",
            "2026-10-28",
            "--prereg",
            str(prereg),
        ]
        assert cli.main(argv) == 2, stage
    with pytest.raises(cli.ConfirmDayRefused):
        cli.refuse_confirm_days((dt.date(2026, 10, 28),))
    cli.refuse_confirm_days((dt.date(2026, 10, 26), dt.date(2026, 10, 27)))


def test_nbp_source_is_imported_explicitly_by_name_and_has_the_partition_methods() -> None:
    tree = ast.parse((_ROOT / "scripts/analysis/nbp_revision_latency_io.py").read_text("utf-8"))
    imported = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert ("scripts.analysis.p2_nbp_ask_murphy", "_NbpSource") in imported
    from scripts.analysis.p2_nbp_ask_murphy import _NbpSource

    for method in ("partition_path", "read_partition", "clear"):
        assert callable(getattr(_NbpSource, method))


def test_markout_fee_comes_from_the_p2_cash_taker_fee() -> None:
    from scripts.analysis.p2_nbp_ask_murphy import cash_taker_fee_usd

    assert vars(core)["cash_taker_fee_usd"] is cash_taker_fee_usd


# ------------------------------------------------------------------ review fixes (HIGH/MEDIUM)


def _hb(start: int, stop: int, step: int = 120 * NS) -> tuple[int, ...]:
    return tuple(range(start, stop, step))


def test_every_stage_report_names_the_book_clock_ts_init(monkeypatch: pytest.MonkeyPatch) -> None:
    _patched_deltas(monkeypatch)
    data, _cur = _data()
    tau = core.TauValues(0.13, 0.18, "test")

    def loader(_s: str, _d: dt.date) -> core.StationDayData:
        return data

    assert (
        core.run_stage_tau(loader, ("LAX",), (_DAY,), freeze_ns=_CUR_AVAIL + 1)["book_clock"]
        == "ts_init"
    )
    assert (
        core.run_stage_0(loader, ("LAX",), (_DAY,), tau, iterations=10)["book_clock"] == "ts_init"
    )
    assert (
        core.run_stage_1(loader, ("LAX",), (_DAY,), tau, iterations=10)["book_clock"] == "ts_init"
    )


def _write_depth(path: Path, rows: list[tuple[int, int, float | None, float | None]]) -> None:
    """rows: (ts_event, ts_init, bid, ask); None = empty side (size 0)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    def price(value: float | None) -> bytes:
        return round((value or 0.0) * 1e16).to_bytes(8, "little") + bytes(8)

    def size(value: float | None) -> bytes:
        return (0 if value is None else 1).to_bytes(8, "little") + bytes(8)

    table = pa.table(
        {
            "ts_event": pa.array([r[0] for r in rows], pa.uint64()),
            "ts_init": pa.array([r[1] for r in rows], pa.uint64()),
            "bid_price_0": pa.array([price(r[2]) for r in rows], pa.binary(16)),
            "bid_size_0": pa.array([size(r[2]) for r in rows], pa.binary(16)),
            "ask_price_0": pa.array([price(r[3]) for r in rows], pa.binary(16)),
            "ask_size_0": pa.array([size(r[3]) for r in rows], pa.binary(16)),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def test_the_loader_reads_ts_init_so_a_row_received_after_t_dec_is_never_used(
    tmp_path: Path,
) -> None:
    from scripts.analysis.nbp_revision_latency_io import read_l0_book

    t_dec = 2_000 * NS
    _write_depth(
        tmp_path / "inst" / "a.parquet",
        [
            (t_dec - 10 * NS, t_dec - 5 * NS, 0.40, 0.44),
            (t_dec - 10 * NS, t_dec + 10 * NS, 0.90, 0.95),  # ts_event < t_dec < ts_init
            (t_dec - 1 * NS, t_dec + 20 * NS, None, 0.60),
        ],
    )
    book = read_l0_book(tmp_path / "inst")
    assert [row.ts_init for row in book] == [t_dec - 5 * NS, t_dec + 10 * NS, t_dec + 20 * NS]
    series = BookSeries(book)
    got = series.as_of(t_dec)
    assert got is not None and got.ask == pytest.approx(0.44)
    assert math.isnan(book[2].bid) and book[2].ask == pytest.approx(0.60)


def test_the_loader_drops_rows_received_at_or_after_the_cutoff(tmp_path: Path) -> None:
    from breezy.analysis.revision_latency import CUTOFF_C_NS
    from scripts.analysis.nbp_revision_latency_io import read_l0_book

    _write_depth(
        tmp_path / "inst" / "a.parquet",
        [(CUTOFF_C_NS - 2, CUTOFF_C_NS - 1, 0.4, 0.5), (CUTOFF_C_NS - 1, CUTOFF_C_NS, 0.4, 0.5)],
    )
    assert [r.ts_init for r in read_l0_book(tmp_path / "inst")] == [CUTOFF_C_NS - 1]


def test_an_exit_during_a_recorder_gap_is_not_carried_forward_and_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    gap = GapSpan(_T_EXIT - NS, _T_EXIT + W_NS + NS, True)
    data, cur = _data(
        [BookRow(_CUR_AVAIL - 1, 0.30, 0.35), BookRow(_T_DEC - 60 * NS, 0.40, 0.45)],
        gaps=(gap,),
        heartbeat=(_CUR_AVAIL - 1, _T_DEC - 30 * NS, _T_EXIT, _T_EXIT + 5 * 60 * NS),
    )
    take = _score(data, _ctx(cur))
    assert isinstance(take, core.Take)
    assert take.missing_exit is True  # the pre-gap bid .40 is NOT the exit
    assert take.bid == 0.0
    assert take.y_raw is None  # the t_exit mid is missing by gap, not carried forward
    tau = core.TauValues(0.13, 0.18, "test")
    report = _stage0_report(data, tau)
    assert report["kill_cost"]["after_rule_b"]["missing_exit_rate"] == 1.0


def _stage0_report(data: core.StationDayData, tau: core.TauValues) -> dict[str, Any]:
    def loader(_s: str, _d: dt.date) -> core.StationDayData:
        return data

    return core.run_stage_0(loader, ("LAX",), (_DAY,), tau, iterations=10)


def test_the_rule_b_reference_ask_is_not_used_when_missing_by_gap() -> None:
    gap = GapSpan(_CUR_AVAIL - NS, _CUR_AVAIL + NS, True)
    data, cur = _data(gaps=(gap,))
    assert _score(data, _ctx(cur)) == core.DROP_RULE_B_REFERENCE


def test_y60m_is_the_sixty_minute_move_not_the_one_minute_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    t_a = _CUR_AVAIL
    rows = [
        BookRow(t_a - 1, 0.28, 0.32),  # mid 0.30
        BookRow(t_a + 30 * NS, 0.30, 0.32),  # mid 0.31: the 60 s move is only +0.01
        BookRow(t_a + 3000 * NS, 0.40, 0.44),  # mid 0.42: the 3600 s move is +0.12
    ]
    data, cur = _data(rows, heartbeat=_hb(t_a - 600 * NS, t_a + 11_000 * NS))
    mech = core._mechanism(data, [_ctx(cur)], Counter())
    row = next(r for r in mech if r["sign"] == 1.0)
    assert row["scorable"] is True
    assert row["y60m"] == pytest.approx(0.12)
    assert "y60" not in row
    assert row["y_grid"][1] == pytest.approx(0.01)  # the 60 s point still exists on the grid


def test_mechanism_grid_points_in_a_gap_are_unscorable_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    t_a = _CUR_AVAIL
    gap = GapSpan(t_a + 3500 * NS, t_a + 3700 * NS, True)  # covers the 3600 s grid point
    data, cur = _data(
        [BookRow(t_a - 1, 0.28, 0.32), BookRow(t_a + 30 * NS, 0.30, 0.34)],
        gaps=(gap,),
        heartbeat=_hb(t_a - 600 * NS, t_a + 11_000 * NS),
    )
    skips: Counter[str] = Counter()
    mech = core._mechanism(data, [_ctx(cur)], skips)
    assert all(r["scorable"] is False for r in mech)
    assert skips["19Z_D-1:grid_missing"] == 1  # r+ reads the gapped rung
    assert skips["19Z_D-1:no_book"] == 1  # r- has no tape book in the fixture


def test_mechanism_reads_at_or_after_the_cutoff_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    t_a = _CUR_AVAIL
    monkeypatch.setattr(core, "before_cutoff", lambda t: t < t_a + 600 * NS)
    data, cur = _data(
        [BookRow(t_a - 1, 0.28, 0.32)], heartbeat=_hb(t_a - 600 * NS, t_a + 11_000 * NS)
    )
    skips: Counter[str] = Counter()
    mech = core._mechanism(data, [_ctx(cur)], skips)
    assert all(r["scorable"] is False for r in mech)
    assert skips["19Z_D-1:after_cutoff"] >= 1


def test_stage_1_records_the_tau_source_without_fabricated_zero_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    data, _cur = _data()
    report = core.run_stage_1(
        lambda _s, _d: data,
        ("LAX",),
        (_DAY,),
        core.TauValues(0.14, 0.2, "prereg-tau-report"),
        iterations=10,
    )
    assert report["tau"] == {"primary": 0.14, "alt": 0.2, "source": "prereg-tau-report"}


def test_stage_1_reports_the_v0_test_and_holm_over_v1_to_v4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    data, _cur = _data()
    report = core.run_stage_1(
        lambda _s, _d: data, ("LAX",), (_DAY,), core.TauValues(0.13, 0.18, "t"), iterations=10
    )
    tests = report["tests"]
    assert tests["V0"]["alpha"] == 0.025
    assert tests["V0"]["reject"] == (tests["V0"]["p_value"] <= 0.025)
    pvals = [report["variants"][n]["p_value"] for n in ("V1", "V2", "V3", "V4")]
    from breezy.analysis.revision_latency import secondary_holm

    assert tests["holm_V1_V4"]["reject"] == list(secondary_holm(pvals))
    assert tests["holm_V1_V4"]["p_values"] == pvals


def test_summary_flags_no_placebo_evidence_and_computes_timing_consistency_from_the_takes() -> None:
    data, cur = _data()
    run = core.VariantRun()
    core.score_station_day(data, [_ctx(cur)], core.VARIANTS[0], 0.13, run, apply_rule_b=False)
    summary = core.summarize(core.VARIANTS[0], run, iterations=10)
    assert summary.n_placebo == 0
    assert summary.timing_consistent is True
    bad = core.VariantRun(takes=[replace(run.takes[0], t_dec_ns=run.takes[0].available_at_ns)])
    assert core.summarize(core.VARIANTS[0], bad, iterations=10).timing_consistent is False


def test_guard_2_is_enforced_on_the_real_path(monkeypatch: pytest.MonkeyPatch) -> None:
    data, cur = _data()
    monkeypatch.setattr(core, "decision_instant", lambda avail, lag: avail + lag)  # not strict
    with pytest.raises(LeakGuardError) as raised:
        _score(data, _ctx(cur))
    assert raised.value.guard == 2


def test_guard_3_is_enforced_when_the_book_serves_a_future_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data, cur = _data()
    monkeypatch.setattr(BookSeries, "as_of", lambda self, t: BookRow(t + 1, 0.4, 0.45))
    with pytest.raises(LeakGuardError) as raised:
        _score(data, _ctx(cur))
    assert raised.value.guard == 3


def test_guard_11_is_enforced_when_the_permit_precheck_is_bypassed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avail = _ns("2026-10-20T01:30:00")
    late, cur = _data(
        [BookRow(avail - 1, 0.30, 0.35), BookRow(avail + 200 * NS, 0.40, 0.45)],
        cur_avail=avail,
        cur_runtime=avail - 65 * 60 * NS,
        heartbeat=(avail - 1, avail + 250 * NS),
    )
    monkeypatch.setattr(core, "permit_ok", lambda *_a: True)
    with pytest.raises(LeakGuardError) as raised:
        _score(late, _ctx(cur))
    assert raised.value.guard == 11


def test_guard_9_is_enforced_on_every_placebo_instant(monkeypatch: pytest.MonkeyPatch) -> None:
    data, cur = _data()
    take = _score(data, _ctx(cur))
    assert isinstance(take, core.Take)
    inside_release = data.chain.releases[0] + 60 * NS
    monkeypatch.setattr(core, "placebo_instants", lambda **_kw: (inside_release,))
    with pytest.raises(LeakGuardError) as raised:
        core._placebos_for(data, take, core.VARIANTS[0])
    assert raised.value.guard == 9


def test_placebo_reads_at_or_after_the_cutoff_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    data, cur = _data(heartbeat=_hb(_CUR_AVAIL - 3600 * NS, _CUR_AVAIL + 20_000 * NS, 60 * NS))
    take = _score(data, _ctx(cur))
    assert isinstance(take, core.Take)
    instant = _ns("2026-10-20T15:00:00")
    monkeypatch.setattr(core, "placebo_instants", lambda **_kw: (instant,))
    monkeypatch.setattr(core, "before_cutoff", lambda t: t < instant)
    assert core._placebos_for(data, take, core.VARIANTS[0]) == []


def test_the_ladder_for_an_event_holds_only_rungs_listed_by_t_dec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, ...]] = []

    def _capture(**kw: object) -> dict[str, float]:
        seen.append(tuple(r.rung_id for r in kw["ladder"]))  # type: ignore[attr-defined]
        return {"r1": 0.30, "r2": -0.20}

    monkeypatch.setattr(core, "rung_deltas", _capture)
    data, _cur = _data()
    listed = replace(data, listed_at={"r1": _CUR_AVAIL - NS, "r2": _CUR_AVAIL + 3600 * NS})
    core.build_events(listed)
    assert seen and all(ladder == ("r1",) for ladder in seen)


def test_unknown_era_and_nonfinite_deltas_are_counted_drops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
        CalibrationArtefactUnknownVersionError,
    )

    data, _cur = _data()

    def _unknown(**_kw: object) -> dict[str, float]:
        raise CalibrationArtefactUnknownVersionError("v9")

    monkeypatch.setattr(core, "rung_deltas", _unknown)
    assert {c.prev_reason for c in core.build_events(data)} >= {core.DROP_UNKNOWN_ERA}
    monkeypatch.setattr(core, "rung_deltas", lambda **_kw: {"r1": math.nan, "r2": 0.1})
    assert {c.prev_reason for c in core.build_events(data)} >= {core.DROP_NONFINITE}


def test_dropped_events_and_mechanism_skips_are_counted_per_stratum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    data, _cur = _data()
    lonely = _vector(_PREV_AVAIL, _PREV_RUNTIME)  # the 13Z D-1 cycle has no predecessor
    chain = VectorChain((lonely.available_at_ns,), (lonely,), (lonely.available_at_ns,))
    report = core.run_stage_0(
        lambda _s, _d: replace(data, chain=chain),
        ("LAX",),
        (_DAY,),
        core.TauValues(0.13, 0.18, "t"),
        iterations=10,
    )
    assert report["counts"]["event_skip:13Z_D-1:no_prev_same_day"] == 1
    assert report["mechanism"]["skipped"]["13Z_D-1:no_prev_same_day"] == 1


# ------------------------------------------------------------------ round 2


def test_stage_tau_uses_the_same_listed_by_rule_as_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, ...]] = []

    def _capture(**kw: object) -> dict[str, float]:
        seen.append(tuple(r.rung_id for r in kw["ladder"]))  # type: ignore[attr-defined]
        return {"r1": 0.30, "r2": -0.20}

    monkeypatch.setattr(core, "rung_deltas", _capture)
    data, _cur = _data()
    listed = replace(data, listed_at={"r1": _CUR_AVAIL - NS, "r2": _CUR_AVAIL + 3600 * NS})
    core.run_stage_tau(lambda _s, _d: listed, ("LAX",), (_DAY,), freeze_ns=_CUR_AVAIL + 1)
    assert seen and all(ladder == ("r1",) for ladder in seen)


def test_first_ts_init_reads_only_the_listing_instant_before_the_cutoff(tmp_path: Path) -> None:
    from breezy.analysis.revision_latency import CUTOFF_C_NS
    from scripts.analysis.nbp_revision_latency_io import read_first_ts_init

    _write_depth(tmp_path / "a" / "x.parquet", [(5, 50, 0.4, 0.5), (6, 40, 0.4, 0.5)])
    _write_depth(tmp_path / "a" / "y.parquet", [(7, 60, 0.4, 0.5), (9, CUTOFF_C_NS, 0.4, 0.5)])
    assert read_first_ts_init(tmp_path / "a") == 40
    assert read_first_ts_init(tmp_path / "none") is None


def test_read_l0_book_decodes_the_same_prices_as_release_timing_b0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.analysis.nbp_revision_latency_io as io
    import scripts.analysis.release_timing_b0 as b0

    rows = [
        (t, t, bid, ask)
        for t, bid, ask in [
            (1, 0.41, 0.45),
            (2, None, 0.50),
            (3, 0.43, None),
            (4, 0.30, 0.31),
            (5, 0.12, 0.99),
            (6, None, None),
            (7, 0.55, 0.57),
        ]
    ]
    _write_depth(tmp_path / "inst" / "a.parquet", rows)
    for batch_rows in (65_536, 3):  # 3 forces sliced batches (non-zero array offsets)
        monkeypatch.setattr(io, "_BATCH_ROWS", batch_rows)
        monkeypatch.setattr(b0, "_BATCH_ROWS", batch_rows)
        mine = io.read_l0_book(tmp_path / "inst")
        theirs = b0.read_top_of_book(tmp_path / "inst")
        assert [r.ts_init for r in mine] == [int(t) for t in theirs.ts]
        for row, bid, ask in zip(mine, theirs.bid, theirs.ask, strict=True):
            assert (math.isnan(row.bid) and math.isnan(bid)) or row.bid == pytest.approx(bid)
            assert (math.isnan(row.ask) and math.isnan(ask)) or row.ask == pytest.approx(ask)


def test_read_l0_book_names_the_missing_column(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from scripts.analysis.nbp_revision_latency_io import BookSchemaError, read_l0_book

    (tmp_path / "inst").mkdir()
    pq.write_table(
        pa.table({"ts_event": pa.array([1], pa.uint64())}), tmp_path / "inst" / "a.parquet"
    )
    with pytest.raises(BookSchemaError, match="ts_init"):
        read_l0_book(tmp_path / "inst")


def test_placebo_instants_skipped_by_the_cutoff_are_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data, cur = _data(heartbeat=_hb(_CUR_AVAIL - 3600 * NS, _CUR_AVAIL + 20_000 * NS, 60 * NS))
    take = _score(data, _ctx(cur))
    assert isinstance(take, core.Take)
    instant = _ns("2026-10-20T15:00:00")
    monkeypatch.setattr(core, "placebo_instants", lambda **_kw: (instant,))
    monkeypatch.setattr(core, "before_cutoff", lambda t: t < instant)
    skips: Counter[str] = Counter()
    assert core._placebos_for(data, take, core.VARIANTS[0], skips) == []
    assert skips["placebo_after_cutoff"] == 1


def test_stage_output_labels_missing_flags_entry_time_only_and_records_peak_rss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    data, _cur = _data()
    tau = core.TauValues(0.13, 0.18, "t")
    stage0 = core.run_stage_0(lambda _s, _d: data, ("LAX",), (_DAY,), tau, iterations=10)
    assert stage0["missing_attribution"]["scope"] == "entry_time_only"
    assert "placebo_skips" in stage0
    stage1 = core.run_stage_1(lambda _s, _d: data, ("LAX",), (_DAY,), tau, iterations=10)
    for report in (stage0, stage1):
        rss = report["peak_rss_kib_by_station_day"]
        assert rss["LAX:2026-10-20"] > 0
