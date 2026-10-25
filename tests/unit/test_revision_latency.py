"""RED-first tests for revision-latency statistics, leak guards, and tau.

KILL-COST uses the raw executable form (amendment 1). DiD is diagnostic and
never decides the verdict. Mark changes are anchored at ``t_dec`` (amendment 2).
Missing-exit is "no bid in ``[t_exit, t_exit + W]``" (amendment 3).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.nbp_calibration import SplitBounds, Splits
from breezy.analysis.release_timing import (
    EventObservation,
    day_block_bootstrap_slope_ci,
    holm_reject,
    metar_offset_placebo_instants,
    time_to_fraction_of_move,
)
from breezy.analysis.revision_latency import (
    ARTEFACT_SHA256,
    CUTOFF_C_NS,
    KILL_BOOTSTRAP_DRAWS,
    STAGE1_FRAMING,
    STAGE2_MIN_NET_USD,
    KillRow,
    LeakGuardError,
    TauCycle,
    VariantSummary,
    aligned_mark_change,
    assert_guard_1,
    assert_guard_2,
    assert_guard_3,
    assert_guard_4,
    assert_guard_5,
    assert_guard_7,
    assert_guard_9,
    assert_guard_10,
    assert_guard_11,
    audit_pending,
    before_cutoff,
    chain_for,
    decision_record_sha256,
    derive_tau,
    fraction_of_move,
    kill_cost,
    mechanism_slope_ci,
    missing_attribution,
    pinned_cycles,
    placebo_instants,
    qualifies,
    report_settlement,
    rung_deltas,
    secondary_holm,
    select,
    wider_cluster_interval,
)
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.forecast_state import (
    NBP_QUANTILE_VARIABLES,
    ForecastQuantileState,
    ForecastQuantileVector,
)
from breezy.strategy.ladder_ev.location_correction import CorrectionForm
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams, Rung
from breezy.strategy.no_ladder_maker.pno_store import build_chain
from breezy.strategy.weather_common.revision_gate import NS, BookRow, MissingClass

_DAY = dt.date(2026, 10, 20)
_CITATION = "builder used DEFAULT_SPLITS; holdout_start ends the fit"


def _ns(day: dt.date, hour: int, minute: int = 0) -> int:
    stamp = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC)
    return int(stamp.timestamp()) * NS


def _row(
    *,
    station: str = "LAX",
    day: dt.date | None = None,
    y_raw: float = -1.0,
    cost: float = 0.05,
    placebos: int = 2,
    missing: bool = False,
) -> KillRow:
    return KillRow(
        station=station,
        climate_day=_DAY if day is None else day,
        y_raw=y_raw,
        placebo_ys=tuple(0.0 for _ in range(placebos)),
        cost_e=cost,
        missing_exit=missing,
    )


def _panel(*, missing: int = 0, placebos: int = 2, y_raw: float = -1.0) -> list[KillRow]:
    rows: list[KillRow] = []
    for index in range(30):
        day = dt.date(2026, 9, 1) + dt.timedelta(days=index % 15)
        station = "LAX" if index < 15 else "MIA"
        rows.append(
            _row(
                station=station,
                day=day,
                y_raw=y_raw,
                placebos=placebos,
                missing=index < missing,
            )
        )
    return rows


def _summary(
    name: str,
    *,
    primary: bool = False,
    point: float = 0.02,
    lo: float = 0.01,
    hi: float = 0.03,
    n: int = 40,
    n_climate: int = 20,
    missing_exit_rate: float = 0.0,
    hit_rate: float = 0.5,
    mean_over_sd: float = 0.5,
    placebo_point: float = 0.0,
    n_placebo: int = 5,
    p_value: float = 0.20,
    leak_ok: bool = True,
) -> VariantSummary:
    return VariantSummary(
        name=name,
        primary=primary,
        point=point,
        lo=lo,
        hi=hi,
        n=n,
        n_climate=n_climate,
        missing_exit_rate=missing_exit_rate,
        hit_rate=hit_rate,
        mean_over_sd=mean_over_sd,
        placebo_point=placebo_point,
        n_placebo=n_placebo,
        p_value=p_value,
        leak_ok=leak_ok,
    )


def test_placebo_window_rejects_a_release_including_nominal_07z() -> None:
    day = _DAY
    releases = (_ns(day, 12, 30),)
    raw = metar_offset_placebo_instants(
        minute_of_hour=0, releases_ns=releases, days=(day,), exclusion_s=0
    )
    kept = placebo_instants(
        minute_of_hour=0,
        releases_ns=releases,
        days=(day,),
        climate_day=day,
        offset_hours=-8.0,
        instrument_id="LAX-r",
        event_instrument_id="LAX-r",
    )
    assert set(kept) <= set(raw)
    assert _ns(day, 8) not in kept  # nominal [07:55Z, 09:40Z] sits inside [07:00, 11:00]
    assert _ns(day, 12) not in kept  # point release at 12:30Z
    assert _ns(day, 15) in kept
    assert _ns(day, 3) not in kept  # 03:00Z is the previous local-standard date at -8h


def test_placebo_on_another_instrument_is_rejected() -> None:
    kept = placebo_instants(
        minute_of_hour=0,
        releases_ns=(),
        days=(_DAY,),
        climate_day=_DAY,
        offset_hours=-8.0,
        instrument_id="MIA-r",
        event_instrument_id="LAX-r",
    )
    assert kept == ()


def test_aligned_mark_change_starts_at_t_dec_not_at_release() -> None:
    t_dec = 10_000
    rows = (
        BookRow(t_dec - 5_000, 0.10, 0.20),  # mid 0.15, the pre-decision jump
        BookRow(t_dec, 0.48, 0.52),  # mid 0.50
        BookRow(t_dec + 60 * NS, 0.54, 0.56),  # mid 0.55
    )
    assert aligned_mark_change(rows, t_dec_ns=t_dec, x_ns=60 * NS) == pytest.approx(0.05)


def test_fraction_of_move_delegates_to_release_timing() -> None:
    t0 = 1_000 * NS
    series = ((t0 + 30 * NS, 0.46), (t0 + 90 * NS, 0.50))
    assert fraction_of_move(series, t0, 0.40) == pytest.approx(30.0)
    assert fraction_of_move(series, t0, 0.40) == time_to_fraction_of_move(
        series, t0, 0.40, fraction=0.5, min_move=0.01
    )


def test_mechanism_slope_ci_delegates_to_day_block_bootstrap() -> None:
    events = (
        EventObservation(_DAY, 1.0, 0.10),
        EventObservation(_DAY, 2.0, 0.20),
        EventObservation(_DAY + dt.timedelta(days=1), 1.0, 0.05),
        EventObservation(_DAY + dt.timedelta(days=1), 3.0, 0.30),
    )
    direct = day_block_bootstrap_slope_ci(events, n_boot=20, alpha=0.05, seed=1)
    got = mechanism_slope_ci(events, n_boot=20, seed=1)
    assert got.slope == direct.slope
    assert got.lo == direct.lo
    assert got.hi == direct.hi


def test_secondary_holm_delegates_and_keeps_input_order() -> None:
    pvalues = (0.001, 0.50, 0.40, 0.30)
    assert secondary_holm(pvalues) == holm_reject(pvalues, alpha=0.025)


def test_kill_cost_raw_kills_when_the_upper_bound_is_below_zero() -> None:
    result = kill_cost(_panel(), iterations=40, seed=1)
    assert result.verdict == "KILL"
    assert result.k_raw_hi is not None and result.k_raw_hi < 0
    assert result.killed_on == "k_raw"
    assert KILL_BOOTSTRAP_DRAWS == 20000


def test_negative_did_does_not_kill_a_positive_raw_result() -> None:
    rows = _panel(y_raw=0.20)
    # Placebos moved further than the event, so DiD is negative while raw is not.
    flipped = [
        KillRow(
            station=row.station,
            climate_day=row.climate_day,
            y_raw=row.y_raw,
            placebo_ys=(0.80, 0.80),
            cost_e=row.cost_e,
            missing_exit=False,
        )
        for row in rows
    ]
    result = kill_cost(flipped, iterations=40, seed=1)
    assert result.k_raw is not None and result.k_raw > 0
    assert result.k_did is not None and result.k_did < 0
    assert result.verdict == "GO"
    assert result.killed_on == "k_raw"


def test_positive_did_does_not_save_a_negative_raw_result() -> None:
    rows = [
        KillRow(
            station=row.station,
            climate_day=row.climate_day,
            y_raw=-0.40,
            placebo_ys=(-0.90, -0.90),
            cost_e=0.05,
            missing_exit=False,
        )
        for row in _panel()
    ]
    result = kill_cost(rows, iterations=40, seed=1)
    assert result.k_did is not None and result.k_did > 0
    assert result.verdict == "KILL"


def test_kill_cost_is_inconclusive_exec_above_25_percent_missing_exit() -> None:
    result = kill_cost(_panel(missing=8), iterations=20, seed=1)
    assert result.missing_exit_rate > 0.25
    assert result.verdict == "INCONCLUSIVE-EXEC"


def test_kill_cost_is_inconclusive_when_n_is_too_small() -> None:
    rows = _panel()[:10]
    result = kill_cost(rows, iterations=20, seed=1)
    assert result.verdict == "INCONCLUSIVE"


def test_kill_cost_is_inconclusive_when_the_placebo_median_is_below_two() -> None:
    result = kill_cost(_panel(placebos=1), iterations=20, seed=1)
    assert result.median_placebos < 2
    assert result.verdict == "INCONCLUSIVE"


def test_missing_attribution_splits_gap_and_heartbeat() -> None:
    flags = (
        MissingClass(True, "quote_tape_gap"),
        MissingClass(True, "heartbeat"),
        MissingClass(False, "present"),
    )
    report = missing_attribution(flags)
    assert report.n_missing == 2
    assert report.n_gap == 1
    assert report.n_heartbeat == 1
    assert report.share_gap == pytest.approx(0.5)
    assert report.share_heartbeat == pytest.approx(0.5)


def test_guards_1_through_4_and_7_through_11_raise_on_a_crafted_violation() -> None:
    with pytest.raises(LeakGuardError) as guard_1:
        assert_guard_1(
            prev_available_at_ns=5,
            cur_available_at_ns=5,
            prev_climate_day=_DAY,
            cur_climate_day=_DAY,
            climate_day=_DAY,
        )
    assert guard_1.value.guard == 1
    with pytest.raises(LeakGuardError) as guard_2:
        assert_guard_2(
            available_at_ns=1_000,
            lag_ns=300,
            t_dec_ns=1_300,
            chain_available_at_ns=1_000,
        )
    assert guard_2.value.guard == 2
    with pytest.raises(LeakGuardError) as guard_2_super:
        assert_guard_2(
            available_at_ns=1_000,
            lag_ns=300,
            t_dec_ns=1_301,
            chain_available_at_ns=2_000,
        )
    assert guard_2_super.value.guard == 2
    with pytest.raises(LeakGuardError) as guard_3:
        assert_guard_3((BookRow(11, 0.4, 0.5),), 10)
    assert guard_3.value.guard == 3
    with pytest.raises(LeakGuardError) as guard_4:
        assert_guard_4(available_at_ns=1_000, cycle_runtime_ns=1_000)
    assert guard_4.value.guard == 4
    with pytest.raises(LeakGuardError) as guard_7:
        assert_guard_7(
            climate_day=dt.date(2026, 10, 28),
            t_dec_ns=0,
            pre_stage2=True,
        )
    assert guard_7.value.guard == 7
    with pytest.raises(LeakGuardError) as guard_9:
        assert_guard_9(
            instant_ns=_ns(_DAY, 8),
            releases_ns=(),
            climate_day=_DAY,
            offset_hours=-8.0,
            instrument_id="LAX-r",
            event_instrument_id="LAX-r",
        )
    assert guard_9.value.guard == 9
    with pytest.raises(LeakGuardError) as guard_10:
        assert_guard_10(5, 1, {"permit": 1})
    assert guard_10.value.guard == 10
    with pytest.raises(LeakGuardError) as guard_11:
        assert_guard_11(1, 2, 3, inside_permit=lambda _ts: False)
    assert guard_11.value.guard == 11


def test_guard_5_reads_default_splits_and_fails_when_they_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    days = (dt.date(2026, 9, 18),)
    assert_guard_5(days, artefact_sha256=ARTEFACT_SHA256, prereg_text=_CITATION)
    import breezy.analysis.nbp_calibration as calibration

    monkeypatch.setattr(
        calibration,
        "DEFAULT_SPLITS",
        Splits(
            train=SplitBounds("train", dt.date(2021, 1, 1), dt.date(2024, 12, 31)),
            validate=SplitBounds("validate", dt.date(2025, 1, 1), dt.date(2026, 5, 3)),
            v5_fit_slice=SplitBounds("v5_fit_slice", dt.date(2026, 5, 4), dt.date(2026, 9, 17)),
            holdout_start=dt.date(2026, 9, 18),
        ),
    )
    with pytest.raises(LeakGuardError) as raised:
        assert_guard_5(days, artefact_sha256=ARTEFACT_SHA256, prereg_text=_CITATION)
    assert raised.value.guard == 5


def test_guard_5_refuses_a_wrong_artefact_sha_or_a_missing_citation() -> None:
    days = (dt.date(2026, 9, 18),)
    with pytest.raises(LeakGuardError) as sha:
        assert_guard_5(days, artefact_sha256="0" * 64, prereg_text=_CITATION)
    assert sha.value.guard == 5
    with pytest.raises(LeakGuardError) as citation:
        assert_guard_5(days, artefact_sha256=ARTEFACT_SHA256, prereg_text="no citation")
    assert citation.value.guard == 5


def test_guard_6_hashes_decision_records_before_the_truth_join() -> None:
    records: list[dict[str, object]] = [{"instrument": "A", "t_dec_ns": 1}]
    before = decision_record_sha256(records)

    def _open_clean() -> dict[str, int]:
        return {"tmax_f": 70}

    truth, digest = report_settlement(records, _open_clean)
    assert truth == {"tmax_f": 70}
    assert digest == before == decision_record_sha256(records)

    def _open_mutating() -> dict[str, int]:
        records[0]["instrument"] = "B"
        return {"tmax_f": 71}

    # The opener mutates the very list that was hashed (the original test passed a fresh
    # literal, so nothing the opener touched was ever the hashed object).
    with pytest.raises(LeakGuardError) as raised:
        report_settlement(records, _open_mutating)
    assert raised.value.guard == 6


def test_derive_tau_uses_only_19z_cycles_available_before_the_freeze() -> None:
    freeze = 1_000
    cycles = (
        TauCycle(available_at_ns=100, cycle_hour=19, delta_r_plus=0.10),
        TauCycle(available_at_ns=200, cycle_hour=19, delta_r_plus=0.20),
        TauCycle(available_at_ns=300, cycle_hour=19, delta_r_plus=0.30),
        TauCycle(available_at_ns=400, cycle_hour=19, delta_r_plus=0.40),
        TauCycle(available_at_ns=500, cycle_hour=19, delta_r_plus=0.50),
        TauCycle(available_at_ns=freeze, cycle_hour=19, delta_r_plus=0.99),
        TauCycle(available_at_ns=50, cycle_hour=13, delta_r_plus=0.99),
        TauCycle(available_at_ns=50, cycle_hour=1, delta_r_plus=0.99),
        TauCycle(available_at_ns=150, cycle_hour=19, delta_r_plus=-0.20),
    )
    report = derive_tau(cycles, freeze_ns=freeze)
    assert report.n_input == 5
    assert report.tau_primary == pytest.approx(max(0.13, report.q60))
    assert report.tau_alt == pytest.approx(max(0.18, report.q80))
    assert report.n_at_primary == sum(
        1 for value in (0.10, 0.20, 0.30, 0.40, 0.50) if value >= report.tau_primary
    )
    assert report.floor_primary_binds is (report.q60 < 0.13)


def test_derive_tau_floor_binds_when_the_quantile_is_below_it() -> None:
    cycles = tuple(
        TauCycle(available_at_ns=index, cycle_hour=19, delta_r_plus=0.05) for index in range(1, 6)
    )
    report = derive_tau(cycles, freeze_ns=100)
    assert report.q60 == pytest.approx(0.05)
    assert report.tau_primary == pytest.approx(0.13)
    assert report.floor_primary_binds is True
    assert report.n_at_primary == 0
    assert report.tau_alt == pytest.approx(0.18)
    assert report.floor_alt_binds is True


def test_selection_rules_audit_hold_and_stage2_point_gate() -> None:
    v0 = _summary("V0", primary=True, point=0.02, lo=0.005)
    v1 = _summary("V1", lo=0.02)
    v2 = _summary("V2", lo=0.001)
    chosen = select((v0, v1, v2, _summary("V3"), _summary("V4", lo=0.0)))
    assert chosen.status == "SELECTED"
    assert chosen.chosen == ("V0", "V1")
    assert chosen.stage2_go is False

    held = select(
        (
            _summary("V0", primary=True, point=0.05, hit_rate=1.0, mean_over_sd=2.0),
            _summary("V1", point=-0.01, hi=-0.001),
        )
    )
    assert held.status == "AUDIT-PENDING"
    assert held.chosen == ()
    assert held.audit_names == ("V0",)
    assert audit_pending(_summary("V0", primary=True, point=0.05))
    assert not audit_pending(_summary("V0", primary=True, point=0.04, hit_rate=0.75))
    assert audit_pending(_summary("V0", primary=True, point=0.01, hit_rate=0.76))
    assert audit_pending(_summary("V0", primary=True, point=0.01, mean_over_sd=1.01))

    failed = select(
        (
            _summary("V0", primary=True, point=-0.01, hi=-0.001, hit_rate=0.4),
            _summary("V1", point=-0.02, hi=-0.001, hit_rate=0.4),
        )
    )
    assert failed.status == "SCREEN-FAIL"
    assert STAGE2_MIN_NET_USD == 0.035
    assert "0.019" in STAGE1_FRAMING
    assert "not evidence of edge" in STAGE1_FRAMING
    ready = select((_summary("V0", primary=True, point=0.035, lo=0.01),))
    assert ready.stage2_go is True
    assert qualifies(v0)
    assert not qualifies(_summary("V1", placebo_point=0.02, point=0.02))


def test_rung_deltas_call_ladder_p_yes() -> None:
    day = _DAY
    ladder: Sequence[Rung] = (
        Rung("low", None, 75),
        Rung("mid", 76, 84),
        Rung("high", 85, None),
    )
    identity = EmosParams(a=0.0, gamma=0.0, delta=1.0)
    calibration = LiveCalibration(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        correction_form=CorrectionForm.NONE,
        linear_coefficients=None,
        month_offsets={},
        point_by_version={"v5": identity},
        draws_by_version={"v5": (identity,)},
    )

    def _vector(mean: float, available: int) -> ForecastQuantileVector:
        return ForecastQuantileVector(
            q10=mean - 3.0,
            q25=mean - 1.5,
            q50=mean,
            q75=mean + 1.5,
            q90=mean + 3.0,
            mean=mean,
            sd=2.5,
            available_at_ns=available,
            cycle_runtime_ns=available - 4_000,
            climate_day=day,
            model_version="v5",
        )

    delta = rung_deltas(
        prev=_vector(70.0, 1_000),
        cur=_vector(90.0, 2_000),
        ladder=ladder,
        calibration=calibration,
        latitude_deg=33.9,
        climate_day=day,
    )
    assert delta["high"] > 0
    assert delta["low"] < 0


def test_chain_for_and_pinned_cycles_use_the_store_helpers(tmp_path: object) -> None:
    del tmp_path
    day = _DAY
    state = ForecastQuantileState()
    values = (60.0, 65.0, 70.0, 75.0, 80.0, 70.0, 3.0)
    for variable, value in zip(NBP_QUANTILE_VARIABLES, values, strict=True):
        state.push(
            variable=variable,
            value_f=value,
            available_at_ns=2_000,
            cycle_runtime_ns=1_000,
            climate_day=day,
            model_version="v5",
        )
    direct = build_chain(state, day)
    wrapped = chain_for(state, day)
    assert wrapped.at(2_000) == direct.at(2_000)
    assert wrapped.at(1_999) is None

    class _Source:
        def partition_path(self, cycle_date: dt.date, hour: int) -> Path:
            return Path("/no/such/lat1-nbp") / f"{cycle_date.isoformat()}-{hour}"

        def read_partition(self, path: Path) -> Sequence[Any]:
            raise AssertionError(f"missing partition must not be read: {path}")

    pinned = pinned_cycles(_Source(), "KLAX", day)
    assert len(pinned.missing) == 3


def test_aligned_mark_change_is_none_when_an_endpoint_is_missing_by_gap() -> None:
    t_dec = 10_000
    rows = (BookRow(t_dec - 1, 0.48, 0.52), BookRow(t_dec + 60 * NS - 1, 0.54, 0.56))
    assert aligned_mark_change(rows, t_dec_ns=t_dec, x_ns=60 * NS) == pytest.approx(0.05)
    gap_at_end = lambda t: t >= t_dec + 60 * NS
    assert aligned_mark_change(rows, t_dec_ns=t_dec, x_ns=60 * NS, missing_at=gap_at_end) is None


def test_no_placebo_evidence_means_the_variant_does_not_qualify_and_is_flagged() -> None:
    bare = _summary("V0", primary=True, point=0.02, lo=0.01, n_placebo=0)
    assert not qualifies(bare)
    assert qualifies(_summary("V0", primary=True, point=0.02, lo=0.01, n_placebo=1))
    result = select((bare, _summary("V1", lo=0.01)))
    assert result.chosen == ("V1",)
    assert result.flags == ("V0:NO_PLACEBO_EVIDENCE",)


def test_a_pending_audit_that_could_change_the_ranking_withholds_the_selection() -> None:
    pending = _summary("V0", primary=True, point=0.05, lo=0.02)
    others = (_summary("V1", lo=0.02), _summary("V2", lo=0.01))
    held = select((pending, *others))
    assert held.status == "AUDIT-PENDING"
    assert held.chosen == ()
    assert held.stage2_go is False
    assert held.audit_names == ("V0",)
    # An audit trigger on a variant that would not qualify anyway cannot change the ranking.
    harmless = _summary("V0", primary=True, point=0.05, lo=0.02, placebo_point=0.04)
    free = select((harmless, *others))
    assert free.status == "SELECTED"
    assert free.chosen == ("V1", "V2")


def test_wider_cluster_interval_is_shared_and_reports_a_one_sided_p() -> None:
    rows = [
        KillRow("LAX", dt.date(2026, 9, 1) + dt.timedelta(days=i), 0.10, (), 0.0, False)
        for i in range(20)
    ]
    got = wider_cluster_interval(rows, lambda r: r.y_raw, iterations=50, seed=1)
    assert got.mean == pytest.approx(0.10)
    assert got.lo == pytest.approx(0.10) and got.hi == pytest.approx(0.10)
    assert got.p_one_sided == 0.0


def test_guard_5_skips_only_the_citation_when_no_prereg_exists_yet() -> None:
    days = (dt.date(2026, 9, 18),)
    assert_guard_5(days, artefact_sha256=ARTEFACT_SHA256, prereg_text=None)
    with pytest.raises(LeakGuardError):
        assert_guard_5(days, artefact_sha256="0" * 64, prereg_text=None)


def test_reads_at_or_after_the_cutoff_are_rejected() -> None:
    assert before_cutoff(CUTOFF_C_NS - 1) is True
    assert before_cutoff(CUTOFF_C_NS) is False
