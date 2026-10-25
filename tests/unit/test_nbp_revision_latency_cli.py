"""RED-first tests for the LAT-1 scorer shell and core (plan r3 + r3.1).

Synthetic books only: no tape, no NBP partition and no network is read. Every stage must refuse
while ``PREREG_SHA256`` is UNFROZEN, and the exit fixture fills INSIDE the W window.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import math
from pathlib import Path

import pytest

import scripts.analysis.nbp_revision_latency as cli
import scripts.analysis.nbp_revision_latency_core as core
from breezy.analysis.revision_latency import LeakGuardError, TauReport
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
    beat = (_T_DEC - 30 * NS, _T_EXIT, _T_EXIT + 5 * 60 * NS) if heartbeat is None else heartbeat
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
        heartbeat=(avail + 250 * NS,),
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


def test_the_pre_release_placebo_take_is_scored_look_ahead_and_diagnostic() -> None:
    avail = _CUR_AVAIL
    rows = _book_rows() + [
        BookRow(avail - 90 * 60 * NS, 0.20, 0.25),
        BookRow(avail - 80 * 60 * NS, 0.22, 0.26),
    ]
    data, cur = _data(rows)
    run = core.VariantRun()
    core.score_station_day(data, [_ctx(cur)], core.VARIANTS[0], 0.13, run, apply_rule_b=False)
    assert run.census.takes == 1
    assert len(run.takes) == 1


# ---------------------------------------------------------------------------- stages


def _patched_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "rung_deltas", lambda **_kw: {"r1": 0.30, "r2": -0.20})


def test_stage_1_and_stage_0_run_end_to_end_on_synthetic_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_deltas(monkeypatch)
    data, _cur = _data()
    tau = TauReport(5, 0.1, 0.2, 0.13, 0.18, True, True, 3, 2)

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
    assert report["selection"]["status"] in {"SCREEN-FAIL", "AUDIT-PENDING", "SELECTED"}

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


def test_every_stage_refuses_while_the_prereg_pin_is_unfrozen(tmp_path: Path) -> None:
    assert cli.PREREG_SHA256 == cli.UNFROZEN
    prereg = tmp_path / "prereg.md"
    prereg.write_text("DEFAULT_SPLITS holdout_start", encoding="utf-8")
    for stage in ("tau", "0", "1", "2"):
        argv = [
            "--stage",
            stage,
            "--start",
            "2026-10-13",
            "--end",
            "2026-10-26",
            "--prereg",
            str(prereg),
        ]
        assert cli.main(argv) == 2, stage
    with pytest.raises(cli.PinRefused):
        cli.require_prereg(prereg)


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
