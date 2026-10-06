"""F7b-core: `FqEvaluator` and the pure `evaluate_e_process`.

Module under test: `evaluators/forecast_quantile_ladder.py`.

F7B-R7/R26: the plug-in class defines ONLY `label` and `has_scorer`; the guard chain
(`check_forward_shadow_inputs`) and `evaluate_e_process` are module-level functions tested directly.
R11: the calibration guard is an optional design field; unpinned gives `guard_unpinned`. R12: the
first terminal event wins and a same-day PASS+KILL is FAIL. R17/R27: backtest input is refused
outright and `_cap_backtest_outcome` is the second line. R23/R24: unsettled takes and coverage gaps
are refused.
"""

from __future__ import annotations

import datetime as dt
import inspect
import math
from collections.abc import Sequence
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final

import pytest

from breezy.analysis.autonomy import evidence_row
from breezy.analysis.autonomy.eprocess import (
    EProcessDesign,
    EProcessRefused,
    GuardThresholds,
)
from breezy.analysis.autonomy.evaluators import forecast_quantile_ladder as fq
from breezy.analysis.autonomy.evaluators.forecast_quantile_ladder import (
    BSS_ALL_DECISIONS_UNAVAILABLE,
    PIT_PER_RUNG_UNAVAILABLE,
    REGISTERED_FORWARD_SHADOW_SOURCES,
    ForwardShadowRefused,
    FqEvaluator,
    FqShadowEvaluation,
    _cap_backtest_outcome,
    check_forward_shadow_inputs,
    evaluate_e_process,
)
from breezy.analysis.autonomy.evidence_row import (
    EvidenceClass,
    EvidenceRefused,
    LoadedEvidence,
    RawEvidence,
    StoreKind,
    load_evidence_rows,
)
from breezy.analysis.autonomy.offline_plugins import OFFLINE_PLUGINS
from breezy.analysis.labeling.scoring_batch import ScoringBatch
from breezy.persistence.autonomy.plugin import PluginRefused, RefusingPlugin, is_complete
from breezy.persistence.autonomy.verdict import VerdictOutcome
from tests.support.fq_eprocess_fixtures import (
    FIXTURE_A,
    FIXTURE_A_DAYS,
    Row,
    climate_day,
    fixture_b,
    ts_ns,
)

SHADOW: Final = StoreKind.NODE_C1_SHADOW_TAKES
P = VerdictOutcome


@pytest.fixture(autouse=True)
def _registered_shadow_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production registry is empty (E-25 rule 6b), so the evaluator refuses every input. The
    PASS/FAIL logic tests need a registered source: this fixture registers the shadow store for
    them. The guard-chain tests reset it to the production value explicitly."""
    monkeypatch.setattr(fq, "REGISTERED_FORWARD_SHADOW_SOURCES", frozenset({SHADOW}))


def design(guard: GuardThresholds | None = None, **kw: Any) -> EProcessDesign:
    base: dict[str, Any] = {
        "m_cap": 2,
        "x_max": 4.0,
        "lambda_max": 0.5,
        "mu_max": 0.5,
        "earliest_look_n": 3,
        "guard": guard,
    }
    return EProcessDesign(**{**base, **kw})


def guard(**kw: Any) -> GuardThresholds:
    base: dict[str, Any] = {
        "n_guard_min": 4,
        "spiegelhalter_abs_z_max": 1000.0,
        "slope_band": (-1000.0, 1000.0),
        "bin_edges": (0.0, 0.5, 1.0),
        "pooling": "pooled",
    }
    return GuardThresholds(**{**base, **kw})


def raw_rows(rows: Sequence[Row], tag: str = "shadow") -> tuple[dict[str, object], ...]:
    out = []
    for d, ts, st, rg, sd, ask, be, p, h, void in rows:
        out.append(
            {
                "evidence_tag": tag,
                "climate_day": climate_day(d).isoformat(),
                "decision_ts_ns": ts_ns(d, ts),
                "ref_ts_ns": ts_ns(d, ts) - 1,
                "station": st,
                "rung_id": rg,
                "side": sd,
                "be": repr(be),
                "raw_ask": repr(ask),
                "p_model": repr(p),
                "h": h,
                "void": void,
            }
        )
    return tuple(out)


def evidence(
    monkeypatch: pytest.MonkeyPatch,
    rows: Sequence[Row],
    days: int,
    kind: StoreKind = SHADOW,
    skip_cover: tuple[int, ...] = (),
) -> LoadedEvidence:
    tag = evidence_row.STORE_CLASS[kind].value
    covered = tuple(climate_day(i).isoformat() for i in range(days) if i not in skip_cover)

    def reader() -> RawEvidence:
        return RawEvidence(rows=raw_rows(rows, tag), covered_days=covered)

    monkeypatch.setattr(evidence_row, "_READERS", MappingProxyType({kind: reader}))
    return load_evidence_rows(kind)


def run(
    ev: LoadedEvidence,
    days: int,
    d: EProcessDesign | None = None,
    *,
    alpha_k: str = "0.9",
    alpha_kill: str = "0.05",
    window_end: int = 400,
    last: int | None = None,
) -> FqShadowEvaluation:
    return evaluate_e_process(
        ev,
        design=d or design(),
        alpha_k=Decimal(alpha_k),
        alpha_kill=Decimal(alpha_kill),
        first_day=climate_day(0),
        window_end=climate_day(window_end),
        last_settled_day=climate_day(days - 1 if last is None else last),
        bss_iterations=20,
    )


# ------------------------------------------------------------------ the plug-in class (R7, R26)


def test_fq_evaluator_is_refusing_and_incomplete() -> None:
    plugin = OFFLINE_PLUGINS["forecast_quantile_ladder"]
    assert type(plugin) is FqEvaluator
    assert plugin.refusing is True and is_complete(plugin) is False
    assert isinstance(plugin, RefusingPlugin)
    own = {n for n in vars(FqEvaluator) if not n.startswith("__")}
    assert own == {"label", "has_scorer"}  # F7B-R7: nothing else, forward_shadow included
    assert FqEvaluator.has_scorer is True
    with pytest.raises(PluginRefused):
        plugin.forward_shadow(None, None, None)
    for name, args in (("offline", (None, None)), ("live", (None,)), ("refit", (None,))):
        with pytest.raises(PluginRefused):
            getattr(plugin, name)(*args)


def test_label_still_routes_to_fq_scorer(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class FakeScorer:
        def __init__(self, *, now_ns: int, prior: tuple[Any, ...]) -> None:
            seen["init"] = (now_ns, prior)

        def label_with_alerts(self, day: object, inputs: list[Any], settlements: object) -> Any:
            seen["call"] = (day, inputs, settlements)
            return type("R", (), {"rows": (), "p_null_count": 2, "non_c1_post_epoch_count": 3})()

    monkeypatch.setattr(fq, "ForecastQuantileLadderScorer", FakeScorer)
    scored = FqEvaluator().label("day", ScoringBatch(7, (), ("x",)), "settle")
    assert seen["init"] == (7, ())
    assert seen["call"] == ("day", ["x"], "settle")
    assert (scored.p_null_count, scored.non_c1_post_epoch_count) == (2, 3)
    with pytest.raises(TypeError):
        FqEvaluator().label("day", "not a batch", "settle")


# ------------------------------------------------------------------ guard chain (R26)


def test_forward_shadow_refuses_non_loaded_evidence() -> None:
    for bad in (None, (), [], object()):
        with pytest.raises(ForwardShadowRefused) as err:
            check_forward_shadow_inputs(bad)
        assert err.value.reason == "evidence_not_loaded"
    assert issubclass(ForwardShadowRefused, PluginRefused)


def test_forward_shadow_refuses_without_registered_forward_shadow_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert REGISTERED_FORWARD_SHADOW_SOURCES == frozenset()  # E-25 rule 6b: empty until F5 rules
    assert isinstance(REGISTERED_FORWARD_SHADOW_SOURCES, frozenset)
    monkeypatch.setattr(fq, "REGISTERED_FORWARD_SHADOW_SOURCES", REGISTERED_FORWARD_SHADOW_SOURCES)
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    with pytest.raises(ForwardShadowRefused) as err:
        check_forward_shadow_inputs(ev)
    assert err.value.reason == "no_registered_forward_shadow_source"
    # the chain passes only for a registered source
    monkeypatch.setattr(fq, "REGISTERED_FORWARD_SHADOW_SOURCES", frozenset({SHADOW}))
    assert check_forward_shadow_inputs(ev) is ev


def test_evaluate_e_process_itself_runs_the_full_guard_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct call with otherwise valid, sealed shadow evidence still needs a REGISTERED source:
    the evaluator runs `check_forward_shadow_inputs`, not only the shadow-class check."""
    monkeypatch.setattr(fq, "REGISTERED_FORWARD_SHADOW_SOURCES", frozenset())
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    assert ev.evidence_class is EvidenceClass.SHADOW
    with pytest.raises(ForwardShadowRefused) as err:
        run(ev, FIXTURE_A_DAYS, design(guard()))
    assert err.value.reason == "no_registered_forward_shadow_source"
    monkeypatch.setattr(fq, "REGISTERED_FORWARD_SHADOW_SOURCES", frozenset({SHADOW}))
    assert run(ev, FIXTURE_A_DAYS, design(guard())).outcome is P.PASS


@pytest.mark.parametrize("kind", [StoreKind.C2_LABEL_STORE, StoreKind.HARNESS, StoreKind.FS_REPLAY])
def test_non_shadow_store_kinds_are_not_accepted(
    monkeypatch: pytest.MonkeyPatch, kind: StoreKind
) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS, kind=kind)
    with pytest.raises(ForwardShadowRefused) as err:
        check_forward_shadow_inputs(ev)
    assert err.value.reason == "store_kind_not_accepted"
    with pytest.raises(ForwardShadowRefused) as err2:
        run(ev, FIXTURE_A_DAYS)
    assert err2.value.reason == "store_kind_not_accepted"  # R17: refused outright


def test_fq_evaluator_refuses_untagged_and_unknown_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    def reader_with(tag: object) -> None:
        rows = [dict(r) for r in raw_rows(FIXTURE_A)]
        for r in rows:
            r["evidence_tag"] = tag
        monkeypatch.setattr(
            evidence_row,
            "_READERS",
            MappingProxyType({SHADOW: lambda: RawEvidence(tuple(rows), ("2026-03-01",))}),
        )

    for tag, reason in ((None, "untagged_row"), ("mystery", "unknown_tag")):
        reader_with(tag)
        with pytest.raises(EvidenceRefused, match=reason):
            load_evidence_rows(SHADOW)
    with pytest.raises(ForwardShadowRefused, match="evidence_not_loaded"):
        evaluate_e_process(
            list(range(3)),  # type: ignore[arg-type]
            design=design(),
            alpha_k=Decimal("0.9"),
            alpha_kill=Decimal("0.05"),
            first_day=climate_day(0),
            window_end=climate_day(10),
            last_settled_day=climate_day(5),
        )


def test_backtest_only_input_never_yields_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS, kind=StoreKind.HARNESS)
    assert ev.evidence_class is EvidenceClass.BACKTEST
    with pytest.raises(ForwardShadowRefused):
        run(ev, FIXTURE_A_DAYS, design(guard()))
    assert _cap_backtest_outcome(P.PASS, EvidenceClass.BACKTEST) is P.UNDERPOWERED  # second line


def test_backtest_rows_reject_only() -> None:
    assert _cap_backtest_outcome(P.FAIL, EvidenceClass.BACKTEST) is P.FAIL
    for outcome in (P.UNDERPOWERED, P.INCONCLUSIVE, P.ERROR):
        assert _cap_backtest_outcome(outcome, EvidenceClass.BACKTEST) is outcome
    for cls in (EvidenceClass.SHADOW, EvidenceClass.LIVE):
        assert _cap_backtest_outcome(P.PASS, cls) is P.PASS


# ------------------------------------------------------------------ the evaluation


def test_calibration_guard_unpinned_blocks_pass_f7b_r11(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(ev, FIXTURE_A_DAYS)  # alpha .9: the joint statistic DOES cross (day 5)
    assert out.pass_crossing_n == 13
    assert out.outcome is P.UNDERPOWERED
    assert out.reason == "guard_unpinned"
    assert out.guard_status == "INSUFFICIENT(guard_unpinned)"


def test_pass_when_crossing_and_guard_ok_on_the_same_day(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(ev, FIXTURE_A_DAYS, design(guard()))
    assert out.outcome is P.PASS and out.reason is None
    assert out.terminal_day == climate_day(5) and out.n_cum == 13
    assert out.guard_status == "OK"
    # a later day cannot change a terminal event
    ev_more = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    again = run(ev_more, FIXTURE_A_DAYS, design(guard()), last=FIXTURE_A_DAYS - 1)
    assert (again.outcome, again.terminal_day, again.n_cum) == (out.outcome, out.terminal_day, 13)


def test_calibration_guard_insufficient_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(ev, FIXTURE_A_DAYS, design(guard(n_guard_min=10_000)))
    assert out.outcome is P.UNDERPOWERED and out.reason == "guard_insufficient"
    assert out.guard_status == "INSUFFICIENT(n_guard_min)"
    assert out.terminal_day is None  # a guard-blocked crossing is not terminal; the process goes on


def test_calibration_guard_failing_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(ev, FIXTURE_A_DAYS, design(guard(spiegelhalter_abs_z_max=1e-9)))
    assert out.outcome is P.UNDERPOWERED and out.reason == "guard_failing"
    assert out.guard_status == "FAIL(spiegelhalter_z)"
    slope_fail = run(ev, FIXTURE_A_DAYS, design(guard(slope_band=(5.0, 6.0))))
    assert slope_fail.guard_status == "FAIL(reliability_slope)"


def test_guard_is_evaluated_per_day_jointly_with_the_crossing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard needs n_guard_min takes. On day 5 (cumulative takes 12) it is sufficient, on
    earlier days it is not: PASS lands on the first day where BOTH hold."""
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(ev, FIXTURE_A_DAYS, design(guard(n_guard_min=9)), alpha_k="0.9")
    scored_by_day5 = sum(1 for r in FIXTURE_A if r[0] <= 5 and not r[9])
    assert scored_by_day5 >= 9
    assert out.outcome is P.PASS and out.terminal_day == climate_day(5)
    late = run(ev, FIXTURE_A_DAYS, design(guard(n_guard_min=15)))
    assert late.outcome is not P.PASS  # the guard never became sufficient inside the window


def test_reported_guard_status_is_the_current_days_not_the_last_crossing_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """alpha_k .8437 (bar .1699): the statistic crosses on day 6 only (.194), not on day 5 (.159)
    or day 7 (.160). The guard (n_guard_min 14) is insufficient on day 6 (13 settled takes) and OK
    on day 7 (14), so the reported guard is the day-7 one while the crossing stays blocked."""
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(ev, FIXTURE_A_DAYS, design(guard(n_guard_min=14)), alpha_k="0.8437")
    assert out.pass_crossing_n == 15  # a crossing was seen, and blocked, on day 6
    assert out.outcome is P.UNDERPOWERED and out.terminal_day is None
    assert out.guard_status == "OK"  # the guard on the LAST settled day
    assert out.reason == "no_crossing_yet"  # not a stale guard_insufficient


def test_window_end_guard_blocked_reports_the_final_days_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(
        ev,
        FIXTURE_A_DAYS,
        design(guard(n_guard_min=14)),
        alpha_k="0.8437",
        window_end=FIXTURE_A_DAYS - 1,
    )
    assert (out.outcome, out.reason) == (P.INCONCLUSIVE, "window_end_guard_blocked")
    assert out.guard_status == "OK"
    # a guard that stays insufficient is still reported as such
    stuck = run(
        ev,
        FIXTURE_A_DAYS,
        design(guard(n_guard_min=10_000)),
        alpha_k="0.8437",
        window_end=FIXTURE_A_DAYS - 1,
    )
    assert stuck.reason == "window_end_guard_blocked"
    assert stuck.guard_status == "INSUFFICIENT(n_guard_min)"


def test_pass_requires_both_e_a_and_e_b_at_alpha_k(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    # alpha .6: e_a crosses (n = 7 at m_cap 2) but e_b does not -> the intersection never does
    out = run(ev, FIXTURE_A_DAYS, design(guard()), alpha_k="0.6")
    assert out.outcome is not P.PASS
    assert out.pass_crossing_n is None
    assert out.log_e_a >= -math.log(0.6) > out.log_e_b


def test_no_pass_or_fail_below_earliest_look_n(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(ev, FIXTURE_A_DAYS, design(guard(), earliest_look_n=99))
    assert out.outcome is P.UNDERPOWERED and out.reason == "below_earliest_look_n"
    ev_b = evidence(monkeypatch, fixture_b(), 40)
    killed = run(ev_b, 40, design(earliest_look_n=6))
    assert killed.outcome is P.FAIL
    held = run(ev_b, 40, design(earliest_look_n=200))
    assert held.outcome is not P.FAIL and held.kill_n is None


def test_kill_is_fail_at_the_first_look(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, fixture_b(), 40)
    out = run(ev, 40, design(earliest_look_n=6))
    assert out.outcome is P.FAIL and out.reason is None
    assert out.kill_n == 78 and out.n_cum == 78  # the F5 MC reference value
    assert out.terminal_day == climate_day(38)


def test_terminal_precedence_same_day_kill_wins_and_first_event_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    plain = run(ev, FIXTURE_A_DAYS, design(guard()))
    assert plain.outcome is P.PASS and plain.terminal_day == climate_day(5)

    # force a KILL on the very day PASS lands (day 5): the result is FAIL, not PASS
    def kill_from_day5(ys: Sequence[float], *, x_max: float) -> tuple[tuple[float, ...], ...]:
        return tuple((100.0,) * 5 if i >= 5 else (0.0,) * 5 for i in range(len(ys)))

    monkeypatch.setattr(fq, "kill_log_capitals", kill_from_day5)
    both = run(ev, FIXTURE_A_DAYS, design(guard()))
    assert both.outcome is P.FAIL and both.terminal_day == climate_day(5)

    # the first terminal event is final: PASS on day 5 stays PASS when KILL only fires on day 6
    def kill_from_day6(ys: Sequence[float], *, x_max: float) -> tuple[tuple[float, ...], ...]:
        return tuple((100.0,) * 5 if i >= 6 else (0.0,) * 5 for i in range(len(ys)))

    monkeypatch.setattr(fq, "kill_log_capitals", kill_from_day6)
    first = run(ev, FIXTURE_A_DAYS, design(guard()))
    assert first.outcome is P.PASS and first.terminal_day == climate_day(5)


def test_window_end_no_crossing_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    open_window = run(ev, FIXTURE_A_DAYS, design(guard()), alpha_k="0.05", window_end=400)
    assert open_window.outcome is P.UNDERPOWERED and open_window.reason == "no_crossing_yet"
    closed = run(ev, FIXTURE_A_DAYS, design(guard()), alpha_k="0.05", window_end=FIXTURE_A_DAYS - 1)
    assert closed.outcome is P.INCONCLUSIVE and closed.reason == "window_end_no_crossing"
    # a guard-blocked crossing at window end is named differently from "no crossing"
    blocked = run(ev, FIXTURE_A_DAYS, design(), window_end=FIXTURE_A_DAYS - 1)
    assert blocked.outcome is P.INCONCLUSIVE and blocked.reason == "window_end_guard_blocked"


def test_days_after_the_window_are_not_processed(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, fixture_b(), 40)
    out = run(ev, 40, design(earliest_look_n=6), window_end=10)
    assert out.days == 11 and out.outcome is not P.FAIL


def test_coverage_gap_and_unsettled_take_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    gap = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS, skip_cover=(3,))
    with pytest.raises(EProcessRefused, match="coverage_gap"):
        run(gap, FIXTURE_A_DAYS)
    unsettled_rows = [*FIXTURE_A, (7, 99, "KNYC", "r8", "yes", 0.3, 0.3, 0.4, None, False)]
    ev = evidence(monkeypatch, unsettled_rows, FIXTURE_A_DAYS)
    with pytest.raises(EProcessRefused, match="unsettled_take_in_settled_day"):
        run(ev, FIXTURE_A_DAYS)
    # the same row on a day that is not yet settled is simply not processed
    ok = run(ev, FIXTURE_A_DAYS, last=FIXTURE_A_DAYS - 2)
    assert ok.days == FIXTURE_A_DAYS - 1


def test_metrics_disclosed_and_market_baseline_paths_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(ev, FIXTURE_A_DAYS, alpha_k="0.05")
    assert out.eprocess_uncounted_takes == 4
    assert out.bss_all_decisions == BSS_ALL_DECISIONS_UNAVAILABLE
    assert BSS_ALL_DECISIONS_UNAVAILABLE == "UNAVAILABLE(market_baseline_absent)"
    assert out.pit_per_rung == PIT_PER_RUNG_UNAVAILABLE == "UNAVAILABLE(pit_spec_absent)"
    scored = [r for r in FIXTURE_A if not r[9]]
    ps, hs = [r[7] for r in scored], [int(r[8] or 0) for r in scored]
    num = sum((h - p) * (1 - 2 * p) for p, h in zip(ps, hs, strict=True))
    den = math.sqrt(sum((1 - 2 * p) ** 2 * p * (1 - p) for p in ps))
    assert out.spiegelhalter_z is not None and math.isclose(out.spiegelhalter_z, num / den)
    pnl = sum(h - r[6] for r, h in zip(scored, hs, strict=True)) / FIXTURE_A_DAYS
    assert math.isclose(out.net_pnl_per_day or 0.0, pnl, rel_tol=1e-12)
    assert out.bss_on_takes is not None and out.bss_on_takes.n_clusters == 7  # day 3 has no take
    assert out.murphy_reliability is not None


def test_no_market_baseline_import_or_use() -> None:
    src = inspect.getsource(fq)
    assert "import market_baseline" not in src and "from breezy.analysis.market_baseline" not in src
    assert inspect.isfunction(evaluate_e_process)


def test_evaluation_is_a_frozen_value(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = run(ev, FIXTURE_A_DAYS)
    with pytest.raises(AttributeError):
        out.outcome = P.PASS  # type: ignore[misc]


def test_empty_range_is_underpowered(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = evidence(monkeypatch, FIXTURE_A, FIXTURE_A_DAYS)
    out = evaluate_e_process(
        ev,
        design=design(),
        alpha_k=Decimal("0.9"),
        alpha_kill=Decimal("0.05"),
        first_day=climate_day(0),
        window_end=climate_day(400),
        last_settled_day=climate_day(-1),
    )
    assert out.outcome is P.UNDERPOWERED and out.days == 0 and out.n_cum == 0


def test_dates_are_real_dates() -> None:
    assert climate_day(0) == dt.date(2026, 3, 1)
