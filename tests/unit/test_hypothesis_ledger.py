"""RED-first unit tests for `src/breezy/analysis/hypothesis_ledger.py` (AUD-18
Slice A, plan steps 1/2/7).

Plan: `docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md`
SS6.1/SS6.2, SS7 step 1, D1/D4/D6(i)/D12/D13.
"""

from __future__ import annotations

import json
from dataclasses import replace as dc_replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.hypothesis_ledger import (
    _SUPPORTED_SCHEMA_VERSIONS,
    EVIDENCED_FEE_THETA,
    HORIZON_TOLLING_LANDED,
    HYPOTHESIS_LEDGER_SCHEMA_VERSION,
    HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2,
    HYPOTHESIS_LEDGER_SCHEMA_VERSION_V3,
    MAX_HYPOTHESES,
    MAX_SINGLE_DAY_LEG_SHARE,
    MAX_VARIANTS_PER_HYPOTHESIS,
    MIN_PER_VARIANT_ALPHA,
    PROGRAMME_ALPHA,
    RE_ARM_GATING_PROGRAMME_ALPHA,
    RULED_HORIZON_DAYS,
    STATION_DAY_STATISTIC,
    VARIANCE_BOUND,
    DuplicateHypothesisIdError,
    DuplicateHypothesisLedgerRecordError,
    DuplicateStratumAxisError,
    HorizonTollingNotLandedError,
    HypothesisLedgerRecordError,
    HypothesisLook,
    HypothesisRecord,
    InvalidLookPolicyError,
    MalformedStratumRangeError,
    MdeMismatchError,
    NonMeanStationDayStatisticError,
    NonPinnedLegShareCapError,
    NonPositiveVariantCountError,
    NonUnitOrderQuantityError,
    PowerPrimaryOnlyRequiredError,
    ProgrammeBudgetExhaustedError,
    StaleFeeThetaError,
    StratumFilterCountMismatchError,
    UnjustifiedVarianceBoundError,
    UnknownHypothesisLedgerSchemaError,
    UnknownStratumAxisError,
    VariantCountCeilingExceededError,
    alpha_remaining,
    break_even,
    evaluate_pooled_pnl_veto,
    filter_zero_take_station_days,
    is_variant_eligible,
    max_single_day_leg_share,
    may_gate_re_arm,
    parse_stratum_filter,
    pooled_net_pnl_per_contract,
    programme_budget_remaining,
    read_hypothesis_ledger,
    recompute_mde,
    register_hypothesis,
    replace_record_status,
    station_day_mean_variance,
    station_day_mean_x,
    write_hypothesis_ledger,
)
from breezy.settlement.current_rung_hold_v2 import CombinedDraw, StratumRow, combine_station_day

REGISTERED_AT = "2026-09-25"
FREEZE_COMMIT = "abc1234"
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "hypothesis"
LIVE_LEDGER_V1_FIXTURE = FIXTURES_DIR / "hypothesis_ledger_v1_2026-09-27.jsonl"
LIVE_LEDGER_V2_FIXTURE = FIXTURES_DIR / "hypothesis_ledger_v2_2026-09-27.jsonl"
LIVE_LEDGER_V3_FIXTURE = FIXTURES_DIR / "hypothesis_ledger_v3_2026-09-27.jsonl"


def _mde_for(k_variants: int, min_station_days: int) -> float:
    if k_variants < 1:
        return 0.0
    per_variant_alpha = (PROGRAMME_ALPHA / MAX_HYPOTHESES) / k_variants
    return recompute_mde(per_variant_alpha=per_variant_alpha, n_station_days=min_station_days)


def _mde_for_alpha(programme_alpha: float, k_variants: int, min_station_days: int) -> float:
    if k_variants < 1:
        return 0.0
    per_variant_alpha = (programme_alpha / MAX_HYPOTHESES) / k_variants
    return recompute_mde(per_variant_alpha=per_variant_alpha, n_station_days=min_station_days)


def _valid_kwargs(**overrides: Any) -> dict[str, Any]:
    k_variants = overrides.get("k_variants", 4)
    min_station_days = overrides.get("min_station_days", 300)
    assert isinstance(k_variants, int)
    assert isinstance(min_station_days, int)
    kwargs: dict[str, Any] = {
        "hypothesis_id": "H-NO-SIDE-REST-2026-09-25",
        "hypothesis_class": "NO_SIDE_HUNTING",
        "registered_at": REGISTERED_AT,
        "k_variants": k_variants,
        "freeze_commit": FREEZE_COMMIT,
        "existing_records": (),
        "min_station_days": min_station_days,
        "max_single_day_leg_share_cap": MAX_SINGLE_DAY_LEG_SHARE,
        "mde_at_allocated_alpha": _mde_for(k_variants, min_station_days),
        "mde_plausibility_bound": 0.5,
        "power_is_primary_only": True,
        "mde_reference_ask": 0.30,
        "mde_fee_theta": EVIDENCED_FEE_THETA,
        "mde_slippage_allowance": 0.01,
        "mde_variance_bound": VARIANCE_BOUND,
        "station_day_statistic": STATION_DAY_STATISTIC,
        "order_quantity": 1,
        "look_policy": "SINGLE_LOOK",
    }
    kwargs.update(overrides)
    return kwargs


# --------------------------------------------------------------------------
# Basic registration refusals
# --------------------------------------------------------------------------


def test_k_variants_below_one_is_refused() -> None:
    with pytest.raises(NonPositiveVariantCountError):
        register_hypothesis(**_valid_kwargs(k_variants=0))


def test_duplicate_hypothesis_id_is_refused() -> None:
    first = register_hypothesis(**_valid_kwargs())
    with pytest.raises(DuplicateHypothesisIdError):
        register_hypothesis(**_valid_kwargs(existing_records=(first,)))


def test_unknown_schema_version_names_path_line_and_version(tmp_path: Path) -> None:
    path = tmp_path / "hypothesis_ledger.jsonl"
    path.write_text(json.dumps({"schema_version": 99}) + "\n", encoding="utf-8")
    with pytest.raises(UnknownHypothesisLedgerSchemaError) as excinfo:
        read_hypothesis_ledger(path)
    message = str(excinfo.value)
    assert str(path) in message
    assert ":1:" in message
    assert "99" in message
    assert str(HYPOTHESIS_LEDGER_SCHEMA_VERSION) in message


# --------------------------------------------------------------------------
# D12 allocation
# --------------------------------------------------------------------------


def test_allocated_and_per_variant_alpha_are_assigned_exactly() -> None:
    record = register_hypothesis(**_valid_kwargs(k_variants=4))
    assert record.allocated_alpha == pytest.approx(PROGRAMME_ALPHA / MAX_HYPOTHESES)
    assert record.per_variant_alpha == pytest.approx(record.allocated_alpha / 4)


def test_rearm_gating_hypothesis_uses_0_025_not_programme_alpha() -> None:
    record = register_hypothesis(
        **_valid_kwargs(
            k_variants=1,
            mde_at_allocated_alpha=_mde_for_alpha(0.025, 1, 300),
            programme_alpha_override=0.025,
        )
    )
    assert record.allocated_alpha == pytest.approx(0.025 / MAX_HYPOTHESES)
    assert record.per_variant_alpha == pytest.approx(0.00625)


def test_missing_programme_alpha_override_keeps_programme_alpha_allocation_and_serialisation() -> (
    None
):
    implicit = register_hypothesis(**_valid_kwargs(k_variants=1))
    explicit_none = register_hypothesis(
        **_valid_kwargs(k_variants=1, programme_alpha_override=None)
    )
    assert implicit.per_variant_alpha == pytest.approx(PROGRAMME_ALPHA / MAX_HYPOTHESES)
    assert json.dumps(implicit.to_dict(), sort_keys=True) == json.dumps(
        explicit_none.to_dict(), sort_keys=True
    )


@pytest.mark.parametrize("override", [0.0, -0.001, PROGRAMME_ALPHA + 0.001])
def test_programme_alpha_override_must_be_positive_and_no_larger_than_programme_alpha(
    override: float,
) -> None:
    with pytest.raises(ValueError):
        register_hypothesis(
            **_valid_kwargs(
                k_variants=1,
                mde_at_allocated_alpha=_mde_for_alpha(PROGRAMME_ALPHA, 1, 300),
                programme_alpha_override=override,
            )
        )


@pytest.mark.parametrize("override", ["0.025", True, object()])
def test_programme_alpha_override_must_be_numeric_when_present(override: Any) -> None:
    with pytest.raises(ValueError):
        register_hypothesis(
            **_valid_kwargs(
                k_variants=1,
                mde_at_allocated_alpha=_mde_for_alpha(PROGRAMME_ALPHA, 1, 300),
                programme_alpha_override=override,
            )
        )


def test_caller_supplied_alpha_is_refused_structurally() -> None:
    with pytest.raises(TypeError):
        register_hypothesis(**_valid_kwargs(), allocated_alpha=0.01)  # type: ignore[call-arg]


def test_summed_nominal_alpha_never_exceeds_programme_alpha() -> None:
    records: list[HypothesisRecord] = []
    for index in range(MAX_HYPOTHESES):
        record = register_hypothesis(
            **_valid_kwargs(
                hypothesis_id=f"H-{index}",
                k_variants=index + 1,
                existing_records=tuple(records),
            )
        )
        records.append(record)
    total_nominal_alpha = sum(r.per_variant_alpha * r.k_variants for r in records)
    assert total_nominal_alpha <= PROGRAMME_ALPHA + 1e-12


def test_exhausted_programme_budget_refuses_next_registration() -> None:
    records: list[HypothesisRecord] = []
    for index in range(MAX_HYPOTHESES):
        record = register_hypothesis(
            **_valid_kwargs(hypothesis_id=f"H-{index}", existing_records=tuple(records))
        )
        records.append(record)
    with pytest.raises(ProgrammeBudgetExhaustedError):
        register_hypothesis(
            **_valid_kwargs(hypothesis_id="H-overflow", existing_records=tuple(records))
        )


def test_rejected_hypothesis_share_is_not_recycled() -> None:
    registered = register_hypothesis(**_valid_kwargs(hypothesis_id="H-0"))
    rejected_fields: dict[str, Any] = {
        **registered.to_dict(),
        "hypothesis_id": "H-1",
        "status": "REJECTED",
    }
    rejected = HypothesisRecord(**rejected_fields)
    third = register_hypothesis(
        **_valid_kwargs(hypothesis_id="H-2", existing_records=(registered, rejected))
    )
    fourth = register_hypothesis(
        **_valid_kwargs(hypothesis_id="H-3", existing_records=(registered, rejected, third))
    )
    with pytest.raises(ProgrammeBudgetExhaustedError):
        register_hypothesis(
            **_valid_kwargs(
                hypothesis_id="H-4", existing_records=(registered, rejected, third, fourth)
            )
        )


def test_non_single_look_policy_is_refused() -> None:
    with pytest.raises(InvalidLookPolicyError):
        register_hypothesis(**_valid_kwargs(look_policy="LD_OBF"))


def test_alpha_remaining_has_no_cross_variant_pooling() -> None:
    record = register_hypothesis(**_valid_kwargs(k_variants=2))
    look_a = HypothesisLook(
        hypothesis_id=record.hypothesis_id,
        variant_id="variant-a",
        looked_at="2026-10-01",
        n_station_days=300,
        n_station_days_observed=300,
        n_station_days_with_takes=300,
        take_rate=1.0,
        ci_lower=0.01,
        ci_upper=0.05,
        pooled_net_pnl_per_contract=10.0,
        max_single_day_leg_share=0.1,
        veto_reason="NONE",
        alpha_spent_cumulative=record.per_variant_alpha,
        is_terminal_look=True,
    )
    assert alpha_remaining(record, (look_a,), "variant-a") == pytest.approx(0.0)
    remaining_b = alpha_remaining(record, (look_a,), "variant-b")
    assert remaining_b == pytest.approx(record.per_variant_alpha)


def test_k_variants_above_ceiling_is_refused() -> None:
    with pytest.raises(VariantCountCeilingExceededError):
        register_hypothesis(**_valid_kwargs(k_variants=MAX_VARIANTS_PER_HYPOTHESIS + 1))


def test_per_variant_alpha_never_falls_below_the_floor() -> None:
    for k in range(1, MAX_VARIANTS_PER_HYPOTHESIS + 1):
        record = register_hypothesis(**_valid_kwargs(hypothesis_id=f"H-k{k}", k_variants=k))
        assert record.per_variant_alpha >= MIN_PER_VARIANT_ALPHA - 1e-15
    floor_record = register_hypothesis(
        **_valid_kwargs(hypothesis_id="H-floor", k_variants=MAX_VARIANTS_PER_HYPOTHESIS)
    )
    assert floor_record.per_variant_alpha == pytest.approx(MIN_PER_VARIANT_ALPHA)


def test_max_hypotheses_equals_open_classes_plus_one_reserve() -> None:
    assert MAX_HYPOTHESES == 4


# --------------------------------------------------------------------------
# D13 power check and pins
# --------------------------------------------------------------------------


def test_underpowered_registration_consumes_no_alpha_slot_or_look() -> None:
    record = register_hypothesis(
        **_valid_kwargs(mde_at_allocated_alpha=0.1032, mde_plausibility_bound=0.01)
    )
    assert record.status == "UNDERPOWERED_NOT_REGISTERED"
    assert record.allocated_alpha == 0.0
    assert record.per_variant_alpha == 0.0
    assert record.is_zero_look is True
    assert programme_budget_remaining((record,)) == MAX_HYPOTHESES
    assert is_variant_eligible(record, (), "any-variant") is False


def test_recompute_mde_matches_worked_examples_and_pins_power_primary_only() -> None:
    per_variant_alpha = MIN_PER_VARIANT_ALPHA
    assert per_variant_alpha == pytest.approx(0.003125)
    mde_300 = recompute_mde(per_variant_alpha=per_variant_alpha, n_station_days=300)
    mde_600 = recompute_mde(per_variant_alpha=per_variant_alpha, n_station_days=600)
    assert round(mde_300, 4) == 0.1032
    assert round(mde_600, 4) == 0.0730

    record = register_hypothesis(
        **_valid_kwargs(
            k_variants=MAX_VARIANTS_PER_HYPOTHESIS,
            min_station_days=300,
            mde_at_allocated_alpha=mde_300,
            mde_plausibility_bound=0.5,
        )
    )
    assert record.power_is_primary_only is True


def test_power_is_primary_only_false_is_refused() -> None:
    with pytest.raises(PowerPrimaryOnlyRequiredError):
        register_hypothesis(**_valid_kwargs(power_is_primary_only=False))


def test_caller_mde_mismatch_names_both_numbers() -> None:
    with pytest.raises(MdeMismatchError) as excinfo:
        register_hypothesis(
            **_valid_kwargs(
                k_variants=MAX_VARIANTS_PER_HYPOTHESIS,
                min_station_days=300,
                mde_at_allocated_alpha=0.9999,
            )
        )
    message = str(excinfo.value)
    assert "0.9999" in message
    assert "0.1032" in message


def test_stale_fee_theta_is_refused() -> None:
    with pytest.raises(StaleFeeThetaError):
        register_hypothesis(**_valid_kwargs(mde_fee_theta=0.06))


def test_unjustified_variance_bound_is_refused() -> None:
    with pytest.raises(UnjustifiedVarianceBoundError):
        register_hypothesis(**_valid_kwargs(mde_variance_bound=0.30))


def test_justified_stricter_variance_bound_is_accepted() -> None:
    record = register_hypothesis(
        **_valid_kwargs(
            mde_variance_bound=0.20,
            mde_variance_bound_justification="outcome-free tighter bound, stated in the ruling",
            mde_plausibility_bound=0.5,
            mde_at_allocated_alpha=0.1032,
        )
    )
    assert record.status in ("REGISTERED", "UNDERPOWERED_NOT_REGISTERED")


def test_break_even_worked_example() -> None:
    be = break_even(reference_ask=0.30, fee_theta=0.0695, slippage=0.01)
    assert be == pytest.approx(0.324595)


def test_non_unit_order_quantity_is_refused() -> None:
    with pytest.raises(NonUnitOrderQuantityError):
        register_hypothesis(**_valid_kwargs(order_quantity=2))
    ok = register_hypothesis(**_valid_kwargs(hypothesis_id="H-unit-qty", order_quantity=1))
    assert ok.order_quantity == 1


def test_mixed_side_fixture_sum_variance_exceeds_bound_mean_does_not() -> None:
    yes_leg = StratumRow(
        entry_ask=Decimal("0.5"), fee=Decimal(0), held=True, station="SFO", side="yes", rung="A"
    )
    no_leg = StratumRow(
        entry_ask=Decimal("0.5"), fee=Decimal(0), held=False, station="SFO", side="no", rung="B"
    )
    draw = combine_station_day((yes_leg, no_leg))
    assert draw.variance == pytest.approx(1.0)
    assert draw.variance > VARIANCE_BOUND
    assert station_day_mean_variance(draw) <= VARIANCE_BOUND + 1e-12

    with pytest.raises(NonMeanStationDayStatisticError):
        register_hypothesis(
            **_valid_kwargs(hypothesis_id="H-sum-stat", station_day_statistic="SUM")
        )


def test_many_legs_fixture_mean_bound_holds() -> None:
    # Six legs, mixed sides, distinct rungs, kept admissible (Sum_i q_i <= 1):
    # YES legs at ask=0.05 (q=BE=0.05) and NO legs at ask=0.95 (q=1-BE=0.05).
    rows = tuple(
        StratumRow(
            entry_ask=Decimal("0.05") if index % 2 == 0 else Decimal("0.95"),
            fee=Decimal(0),
            held=(index % 2 == 0),
            station="SFO",
            side="yes" if index % 2 == 0 else "no",
            rung=f"rung-{index}",
        )
        for index in range(6)
    )
    draw = combine_station_day(rows)
    mean_x = station_day_mean_x(draw)
    mean_variance = station_day_mean_variance(draw)
    assert -1.0 <= mean_x <= 1.0
    assert mean_variance <= VARIANCE_BOUND + 1e-12


def test_zero_take_filter_drops_fills_zero_and_reports_counts() -> None:
    fills = [0] * 28 + [1] * 12
    result = filter_zero_take_station_days(fills)
    assert result.n_station_days_observed == 40
    assert result.n_station_days_with_takes == 12
    assert result.take_rate == pytest.approx(0.3)


def test_pooled_pnl_veto_counterexample_yields_primary_passed_pnl_veto() -> None:
    # Nine one-leg winners at ask=0.02 (each its own station-day, trivially
    # admissible) against one 100-leg loser at ask=0.98. A single real
    # station-day of 100 legs each carrying q=0.98 would itself violate
    # combine_station_day's own Sum_i q_i <= 1 admission gate (it would sum to
    # 98), so the 100-leg CombinedDraw is built directly from the SS6.1-pinned
    # per-leg arithmetic (x_i = held_i - BE_i, BE_i = ask_i at fee=0) rather
    # than routed through that gate -- this fixture is illustrating the
    # pooled-P&L veto's pure decision logic over an already-built draw set,
    # not re-testing combine_station_day's own admission gate.
    def _winner_row() -> StratumRow:
        return StratumRow(entry_ask=Decimal("0.02"), fee=Decimal(0), held=True, station="SFO")

    winner_draws = [combine_station_day((_winner_row(),)) for _ in range(9)]
    loser_draw = CombinedDraw(x=100 * (0.0 - 0.98), variance=100 * 0.98 * 0.02, n_constituents=100)
    draws = [*winner_draws, loser_draw]
    pooled = pooled_net_pnl_per_contract(draws)
    assert pooled < 0
    outcome = evaluate_pooled_pnl_veto(
        primary_excludes_zero=True,
        pooled_net_pnl_per_contract=pooled,
        max_single_day_leg_share=max_single_day_leg_share(draws),
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
    )
    assert outcome.status == "PRIMARY_PASSED_PNL_VETO"
    assert outcome.veto_reason == "POOLED_PNL_NON_POSITIVE"


def test_failed_primary_with_positive_pnl_stays_rejected() -> None:
    outcome = evaluate_pooled_pnl_veto(
        primary_excludes_zero=False,
        pooled_net_pnl_per_contract=100.0,
        max_single_day_leg_share=0.05,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
    )
    assert outcome.status == "REJECTED"


def test_leg_share_above_cap_vetoes_when_pnl_is_positive() -> None:
    outcome = evaluate_pooled_pnl_veto(
        primary_excludes_zero=True,
        pooled_net_pnl_per_contract=5.0,
        max_single_day_leg_share=0.5,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
    )
    assert outcome.status == "PRIMARY_PASSED_PNL_VETO"
    assert outcome.veto_reason == "LEG_SHARE_ABOVE_CAP"


def test_non_pinned_leg_share_cap_is_refused() -> None:
    with pytest.raises(NonPinnedLegShareCapError):
        register_hypothesis(**_valid_kwargs(max_single_day_leg_share_cap=0.5))
    with pytest.raises(NonPinnedLegShareCapError):
        evaluate_pooled_pnl_veto(
            primary_excludes_zero=True,
            pooled_net_pnl_per_contract=1.0,
            max_single_day_leg_share=0.1,
            max_single_day_leg_share_cap=0.5,
        )


# --------------------------------------------------------------------------
# JSONL atomic write round-trip
# --------------------------------------------------------------------------


def test_jsonl_atomic_write_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "hypothesis" / "hypothesis_ledger.jsonl"
    record = register_hypothesis(**_valid_kwargs())
    write_hypothesis_ledger(path, (record,))
    assert path.exists()
    round_tripped = read_hypothesis_ledger(path)
    assert round_tripped == (record,)

    second = register_hypothesis(
        **_valid_kwargs(hypothesis_id="H-second", existing_records=(record,))
    )
    write_hypothesis_ledger(path, (record, second))
    round_tripped_two = read_hypothesis_ledger(path)
    expected_ids = {record.hypothesis_id, second.hypothesis_id}
    assert {r.hypothesis_id for r in round_tripped_two} == expected_ids


def test_duplicate_hypothesis_id_on_disk_is_a_hard_error(tmp_path: Path) -> None:
    path = tmp_path / "hypothesis_ledger.jsonl"
    record = register_hypothesis(**_valid_kwargs())
    line = json.dumps(record.to_dict())
    path.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(DuplicateHypothesisLedgerRecordError):
        read_hypothesis_ledger(path)


# --------------------------------------------------------------------------
# RA-2 (EDGE-5, 2026-09-27): schema-v2 hypothesis/variant -> stratum binding
# --------------------------------------------------------------------------


_VALID_FILTER = "station=SFO|hour_lst=10-11|side=YES|composition_kind=taker"


def test_read_hypothesis_ledger_accepts_v1_v2_v3_and_refuses_v4(tmp_path: Path) -> None:
    """Renamed from `..._refuses_v3` (LEDGER-V3 D-7): the refusal keeps its
    exact assertions, now naming schema_version=4, and pins the exact
    supported set (`_SUPPORTED_SCHEMA_VERSIONS == frozenset({1, 2, 3})`)."""
    assert _SUPPORTED_SCHEMA_VERSIONS == frozenset({1, 2, 3})
    v1_record = register_hypothesis(**_valid_kwargs(hypothesis_id="H-V1"))
    v2_record = register_hypothesis(
        **_valid_kwargs(
            hypothesis_id="H-V2",
            k_variants=1,
            variant_stratum_filters=(_VALID_FILTER,),
        )
    )
    assert v2_record.schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2
    path = tmp_path / "hypothesis_ledger.jsonl"
    write_hypothesis_ledger(path, (v1_record, v2_record))
    round_tripped = {r.hypothesis_id: r for r in read_hypothesis_ledger(path)}
    assert round_tripped["H-V1"].schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION
    assert round_tripped["H-V2"].schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2
    assert round_tripped["H-V2"].variant_stratum_filters == (_VALID_FILTER,)

    bad_path = tmp_path / "v4_ledger.jsonl"
    bad_path.write_text(json.dumps({"schema_version": 4}) + "\n", encoding="utf-8")
    with pytest.raises(UnknownHypothesisLedgerSchemaError) as excinfo:
        read_hypothesis_ledger(bad_path)
    message = str(excinfo.value)
    assert "4" in message
    assert "1" in message and "2" in message and "3" in message


def test_v1_record_round_trip_is_byte_unchanged(tmp_path: Path) -> None:
    original_bytes = LIVE_LEDGER_V1_FIXTURE.read_bytes()
    path = tmp_path / "hypothesis_ledger.jsonl"
    path.write_bytes(original_bytes)
    records = read_hypothesis_ledger(path)
    assert len(records) == 3
    assert all(record.schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION for record in records)
    assert all(record.variant_stratum_filters == () for record in records)
    write_hypothesis_ledger(path, records)
    assert path.read_bytes() == original_bytes


def test_v1_record_to_dict_never_emits_variant_stratum_filters() -> None:
    record = register_hypothesis(**_valid_kwargs(hypothesis_id="H-V1-DICT"))
    assert record.schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION
    payload = record.to_dict()
    assert "variant_stratum_filters" not in payload


def test_v2_record_to_dict_emits_its_own_variant_stratum_filters() -> None:
    record = register_hypothesis(
        **_valid_kwargs(
            hypothesis_id="H-V2-DICT",
            k_variants=1,
            variant_stratum_filters=(_VALID_FILTER,),
        )
    )
    payload = record.to_dict()
    assert payload["schema_version"] == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2
    assert payload["variant_stratum_filters"] == [_VALID_FILTER]


def test_mixed_v1_v2_whole_file_rewrite_leaves_existing_v1_lines_byte_identical(
    tmp_path: Path,
) -> None:
    """`write_hypothesis_ledger` rewrites the WHOLE file -- adding one new v2
    record must not perturb the pre-existing v1 lines' own bytes."""
    original_bytes = LIVE_LEDGER_V1_FIXTURE.read_bytes()
    path = tmp_path / "hypothesis_ledger.jsonl"
    path.write_bytes(original_bytes)
    existing = read_hypothesis_ledger(path)

    new_v2 = register_hypothesis(
        **_valid_kwargs(
            hypothesis_id="H-ZZZ-NEW-V2",
            k_variants=1,
            existing_records=existing,
            variant_stratum_filters=(_VALID_FILTER,),
        )
    )
    write_hypothesis_ledger(path, (*existing, new_v2))

    rewritten_lines = path.read_text(encoding="utf-8").splitlines()
    original_lines = original_bytes.decode("utf-8").splitlines()
    # H-ZZZ-NEW-V2 sorts after all 3 existing ids (H-ARCHIVE.., H-FORECAST..,
    # H-NO-SIDE..) -- write_hypothesis_ledger orders by hypothesis_id.
    assert rewritten_lines[:3] == original_lines
    assert len(rewritten_lines) == 4
    assert json.loads(rewritten_lines[3])["hypothesis_id"] == "H-ZZZ-NEW-V2"

    round_tripped = read_hypothesis_ledger(path)
    ids = {r.hypothesis_id for r in round_tripped}
    assert ids == {r.hypothesis_id for r in existing} | {"H-ZZZ-NEW-V2"}


def test_variant_stratum_filter_rejects_unknown_axis() -> None:
    with pytest.raises(UnknownStratumAxisError):
        parse_stratum_filter("planet=Mars|hour_lst=ALL|side=YES|composition_kind=taker")


def test_variant_stratum_filter_rejects_malformed_range() -> None:
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter("station=SFO|hour_lst=14-10|side=YES|composition_kind=taker")
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter("station=SFO|hour_lst=25|side=YES|composition_kind=taker")
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter("station=SFO|hour_lst=not-a-range|side=YES|composition_kind=taker")


def test_variant_stratum_filter_rejects_duplicate_axis() -> None:
    with pytest.raises(DuplicateStratumAxisError):
        parse_stratum_filter("station=SFO|station=MDW|hour_lst=ALL|side=YES|composition_kind=taker")


def test_variant_stratum_filter_accepts_a_well_formed_spec() -> None:
    parsed = parse_stratum_filter(_VALID_FILTER)
    assert parsed.station == "SFO"
    assert parsed.hour_lst == "10-11"
    assert parsed.side == "YES"
    assert parsed.composition_kind == "taker"


@pytest.mark.parametrize("value", ["ALL", "5", "5-10"])
def test_hour_lst_single_forms_stay_byte_identical_in_behaviour(value: str) -> None:
    """RA-2b: widening `hour_lst` to accept a comma-separated list must not
    change ALL/H/H-H, the three pre-existing single-item forms."""
    parsed = parse_stratum_filter(f"station=SFO|hour_lst={value}|side=YES|composition_kind=taker")
    assert parsed.hour_lst == value


def test_hour_lst_accepts_disjoint_ascending_range_union() -> None:
    """RULING_RA-9 §6: the exact RED this ruling names."""
    parsed = parse_stratum_filter("station=SFO|hour_lst=0-9,12-23|side=YES|composition_kind=taker")
    assert parsed.hour_lst == "0-9,12-23"


def test_hour_lst_accepts_a_list_mixing_single_hours_and_ranges() -> None:
    parsed = parse_stratum_filter(
        "station=SFO|hour_lst=0-9,11,14-23|side=YES|composition_kind=taker"
    )
    assert parsed.hour_lst == "0-9,11,14-23"


def test_hour_lst_rejects_overlapping_ranges() -> None:
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter("station=SFO|hour_lst=0-9,5-12|side=YES|composition_kind=taker")


def test_hour_lst_rejects_descending_order() -> None:
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter("station=SFO|hour_lst=12-23,0-9|side=YES|composition_kind=taker")


@pytest.mark.parametrize("value", ["0-9,", ",12-23", "0-9,,12-23"])
def test_hour_lst_rejects_empty_item_or_trailing_comma(value: str) -> None:
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter(f"station=SFO|hour_lst={value}|side=YES|composition_kind=taker")


def test_hour_lst_rejects_an_hour_outside_0_23_within_a_list() -> None:
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter("station=SFO|hour_lst=0-9,20-25|side=YES|composition_kind=taker")


def test_hour_lst_rejects_start_greater_than_end_within_a_list_item() -> None:
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter("station=SFO|hour_lst=0-9,15-12|side=YES|composition_kind=taker")


def test_hour_lst_rejects_adjacent_touching_ranges_as_overlap() -> None:
    """`0-9,9-12` shares hour 9 -- not disjoint, so it is refused too."""
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter("station=SFO|hour_lst=0-9,9-12|side=YES|composition_kind=taker")


def test_hour_lst_rejects_a_wrap_range_even_inside_a_list() -> None:
    """RULING_RA-9 §6: `17-8` (a wrap) must keep refusing."""
    with pytest.raises(MalformedStratumRangeError):
        parse_stratum_filter("station=SFO|hour_lst=0-9,17-8|side=YES|composition_kind=taker")


def test_hour_lst_ruling_ra9_exact_offwindow_filter_string() -> None:
    """Pins the exact `variant_stratum_filters` string RULING_RA-9 §6 names
    for `H-OFFWINDOW-T4-2026-09`'s eventual Path A zero-look registration."""
    parsed = parse_stratum_filter(
        "station=ALL|hour_lst=0-8,17-23|side=YES|composition_kind=pm_us_crh_offwindow_price_cap_v1"
    )
    assert parsed.hour_lst == "0-8,17-23"


def test_live_ledger_v1_fixture_rows_still_parse_after_hour_lst_widening() -> None:
    """RA-2b must not perturb existing ledger lines -- the 3 live v1 fixture
    rows carry no `variant_stratum_filters` (all zero-look), so this pins
    that `read_hypothesis_ledger` still parses them to the same values."""
    records = read_hypothesis_ledger(LIVE_LEDGER_V1_FIXTURE)
    assert len(records) == 3
    assert all(record.variant_stratum_filters == () for record in records)
    ids = {record.hypothesis_id for record in records}
    assert ids == {
        "H-ARCHIVE-RECAL-2026-09",
        "H-FORECAST-TAKER-RUNG-SCREEN-2026-09-20",
        "H-NO-SIDE-2026-09",
    }


def test_register_hypothesis_variant_stratum_filters_count_mismatch_is_refused() -> None:
    with pytest.raises(StratumFilterCountMismatchError):
        register_hypothesis(
            **_valid_kwargs(
                hypothesis_id="H-COUNT-MISMATCH",
                k_variants=2,
                variant_stratum_filters=(_VALID_FILTER,),
            )
        )


def test_register_hypothesis_variant_stratum_filters_refused_for_closed_disposition() -> None:
    with pytest.raises(ValueError):
        register_hypothesis(
            hypothesis_id="H-CLOSED-FILTERS",
            hypothesis_class="FORECAST_TAKER",
            registered_at=REGISTERED_AT,
            k_variants=1,
            freeze_commit=FREEZE_COMMIT,
            existing_records=(),
            disposition="CLOSED",
            variant_stratum_filters=(_VALID_FILTER,),
        )


def test_v1_from_dict_refuses_an_unexpected_variant_stratum_filters_key() -> None:
    record = register_hypothesis(**_valid_kwargs(hypothesis_id="H-V1-EXTRA"))
    payload = {**record.to_dict(), "variant_stratum_filters": [_VALID_FILTER]}
    with pytest.raises(HypothesisLedgerRecordError):
        HypothesisRecord.from_dict(payload)


# --------------------------------------------------------------------------
# LEDGER-V3 (RA-9d horizon_days + RA-8c re_arm_gating), EDGE-5 2026-09-27
# --------------------------------------------------------------------------


def _direct_v3_record(
    *,
    hypothesis_id: str = "H-V3-DIRECT",
    horizon_days: int | None = None,
    re_arm_gating: bool = False,
    status: str = "UNDERPOWERED_NOT_REGISTERED",
    is_zero_look: bool = True,
    k_variants: int = 1,
    allocated_alpha: float = 0.0,
    per_variant_alpha: float = 0.0,
    variant_stratum_filters: tuple[str, ...] = (),
) -> HypothesisRecord:
    """A schema_version=3 `HypothesisRecord`, built directly rather than via
    `register_hypothesis` -- lets a test hold `HORIZON_TOLLING_LANDED=False`
    and `re_arm_gating`/`is_zero_look` combinations `register_hypothesis`'s
    own REGISTERED-branch refusals would otherwise block (mirrors the triage
    tests, which build `HypothesisRecord` directly for the same reason)."""
    return HypothesisRecord(
        schema_version=HYPOTHESIS_LEDGER_SCHEMA_VERSION_V3,
        hypothesis_id=hypothesis_id,
        hypothesis_class="V3_DIRECT_TEST",
        registered_at=REGISTERED_AT,
        k_variants=k_variants,
        allocated_alpha=allocated_alpha,
        per_variant_alpha=per_variant_alpha,
        min_station_days=300,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=0.5,
        mde_plausibility_bound=0.5,
        power_is_primary_only=True,
        mde_reference_ask=0.30,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=0.01,
        mde_variance_bound=VARIANCE_BOUND,
        mde_variance_bound_justification=None,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=1,
        look_policy="SINGLE_LOOK",
        freeze_commit=FREEZE_COMMIT,
        status=status,
        is_zero_look=is_zero_look,
        variant_stratum_filters=variant_stratum_filters,
        horizon_days=horizon_days,
        re_arm_gating=re_arm_gating,
    )


def test_max_hypotheses_and_re_arm_gating_alpha_are_pinned() -> None:
    """D-1 MAX_HYPOTHESES coupling: both values are locked together by the
    RULING_RA-9 A-3a bound; changing either needs a new ruling first."""
    assert MAX_HYPOTHESES == 4, (
        "the RULING_RA-9 A-3a bound (allocated_alpha * MAX_HYPOTHESES <= 0.025) "
        "must be re-derived by a ruling before MAX_HYPOTHESES changes"
    )
    assert RE_ARM_GATING_PROGRAMME_ALPHA == 0.025, (
        "RULING_RA-9 A-3a fixes this bound; changing it needs a new ruling"
    )


def test_re_arm_gating_without_0_025_override_is_refused() -> None:
    with pytest.raises(ValueError):
        register_hypothesis(
            **_valid_kwargs(hypothesis_id="H-GATE-NO-OVERRIDE", k_variants=1, re_arm_gating=True)
        )
    with pytest.raises(ValueError):
        register_hypothesis(
            **_valid_kwargs(
                hypothesis_id="H-GATE-TOO-LOOSE",
                k_variants=1,
                re_arm_gating=True,
                programme_alpha_override=0.05,
            )
        )


def test_re_arm_gating_with_override_0_025_registers_v3() -> None:
    """`re_arm_gating=True` with a compliant override "registers" (no
    exception) as schema_version=3 -- forced UNDERPOWERED here so the call
    does not also need `HORIZON_TOLLING_LANDED` (RA-9 Path A, R3-2)."""
    record = register_hypothesis(
        **_valid_kwargs(
            hypothesis_id="H-GATE-OK",
            k_variants=1,
            re_arm_gating=True,
            programme_alpha_override=0.025,
            mde_at_allocated_alpha=_mde_for_alpha(0.025, 1, 300),
            mde_plausibility_bound=0.01,
        )
    )
    assert record.schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V3
    assert record.status == "UNDERPOWERED_NOT_REGISTERED"
    assert record.is_zero_look is True
    assert record.re_arm_gating is True


def test_research_only_may_keep_0_05_but_never_gates() -> None:
    record = register_hypothesis(
        **_valid_kwargs(
            hypothesis_id="H-RESEARCH-ONLY",
            k_variants=1,
            re_arm_gating=False,
            mde_plausibility_bound=0.01,
        )
    )
    assert record.schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V3
    assert record.re_arm_gating is False
    assert may_gate_re_arm(record) is False


def test_undeclared_v1_v2_record_cannot_gate_re_arm() -> None:
    v1 = register_hypothesis(**_valid_kwargs(hypothesis_id="H-UNDECLARED-V1"))
    assert v1.re_arm_gating is None
    assert may_gate_re_arm(v1) is False
    v2 = register_hypothesis(
        **_valid_kwargs(
            hypothesis_id="H-UNDECLARED-V2",
            k_variants=1,
            variant_stratum_filters=(_VALID_FILTER,),
        )
    )
    assert v2.re_arm_gating is None
    assert may_gate_re_arm(v2) is False


def test_replace_to_gating_above_0_025_raises() -> None:
    """The forgeability attack D-1 defends against: naively flipping
    `re_arm_gating` on a record registered at the default 0.05 programme
    alpha must not silently gate a re-arm."""
    record = register_hypothesis(**_valid_kwargs(hypothesis_id="H-REPLACE-GATE"))
    with pytest.raises(ValueError):
        dc_replace(
            record,
            schema_version=HYPOTHESIS_LEDGER_SCHEMA_VERSION_V3,
            re_arm_gating=True,
        )


def test_v3_from_dict_refuses_null_re_arm_gating() -> None:
    record = _direct_v3_record(horizon_days=180, re_arm_gating=True)
    payload = {**record.to_dict(), "re_arm_gating": None}
    with pytest.raises(HypothesisLedgerRecordError):
        HypothesisRecord.from_dict(payload)


def test_horizon_days_without_re_arm_gating_is_refused() -> None:
    with pytest.raises(ValueError):
        register_hypothesis(
            **_valid_kwargs(
                hypothesis_id="H-HORIZON-NO-GATE",
                horizon_days=180,
                mde_plausibility_bound=0.01,
            )
        )


def test_closed_disposition_refuses_v3_kwargs() -> None:
    with pytest.raises(ValueError):
        register_hypothesis(
            hypothesis_id="H-CLOSED-V3",
            hypothesis_class="FORECAST_TAKER",
            registered_at=REGISTERED_AT,
            k_variants=1,
            freeze_commit=FREEZE_COMMIT,
            existing_records=(),
            disposition="CLOSED",
            horizon_days=180,
            re_arm_gating=True,
        )


def test_v3_from_dict_refuses_missing_key() -> None:
    record = _direct_v3_record(horizon_days=180, re_arm_gating=True)
    payload = record.to_dict()
    del payload["re_arm_gating"]
    with pytest.raises(HypothesisLedgerRecordError):
        HypothesisRecord.from_dict(payload)


def test_v3_from_dict_refuses_extra_key() -> None:
    record = _direct_v3_record(horizon_days=180, re_arm_gating=True)
    payload = {**record.to_dict(), "unexpected_v3_key": 1}
    with pytest.raises(HypothesisLedgerRecordError):
        HypothesisRecord.from_dict(payload)


def test_v3_from_dict_refuses_bool_horizon_days() -> None:
    record = _direct_v3_record(horizon_days=180, re_arm_gating=True)
    payload = {**record.to_dict(), "horizon_days": True}
    with pytest.raises(HypothesisLedgerRecordError):
        HypothesisRecord.from_dict(payload)


@pytest.mark.parametrize("bad_horizon", [0, 1, 181, 90])
def test_horizon_days_not_in_ruled_set_is_refused(bad_horizon: int) -> None:
    assert bad_horizon not in RULED_HORIZON_DAYS
    with pytest.raises(ValueError):
        register_hypothesis(
            **_valid_kwargs(
                hypothesis_id=f"H-BAD-HORIZON-{bad_horizon}",
                horizon_days=bad_horizon,
                re_arm_gating=False,
                mde_plausibility_bound=0.01,
            )
        )


def test_re_arm_gating_boundary_exact_0_025_passes_and_0_025_plus_eps_fails() -> None:
    """R3-8: an EXACT float comparison, no tolerance."""
    base_kwargs: dict[str, Any] = {
        "schema_version": HYPOTHESIS_LEDGER_SCHEMA_VERSION_V3,
        "hypothesis_class": "TEST",
        "registered_at": REGISTERED_AT,
        "k_variants": 1,
        "min_station_days": 300,
        "max_single_day_leg_share_cap": MAX_SINGLE_DAY_LEG_SHARE,
        "mde_at_allocated_alpha": 0.5,
        "mde_plausibility_bound": 0.5,
        "power_is_primary_only": True,
        "mde_reference_ask": 0.30,
        "mde_fee_theta": EVIDENCED_FEE_THETA,
        "mde_slippage_allowance": 0.01,
        "mde_variance_bound": VARIANCE_BOUND,
        "mde_variance_bound_justification": None,
        "station_day_statistic": STATION_DAY_STATISTIC,
        "order_quantity": 1,
        "look_policy": "SINGLE_LOOK",
        "freeze_commit": FREEZE_COMMIT,
        "status": "REGISTERED",
        "is_zero_look": False,
        "variant_stratum_filters": (_VALID_FILTER,),
        "horizon_days": None,
        "re_arm_gating": True,
    }
    exact_alpha = RE_ARM_GATING_PROGRAMME_ALPHA / MAX_HYPOTHESES
    passing = HypothesisRecord(
        hypothesis_id="H-BOUNDARY-PASS",
        allocated_alpha=exact_alpha,
        per_variant_alpha=exact_alpha,
        **base_kwargs,
    )
    assert passing.allocated_alpha * MAX_HYPOTHESES == RE_ARM_GATING_PROGRAMME_ALPHA
    with pytest.raises(ValueError):
        HypothesisRecord(
            hypothesis_id="H-BOUNDARY-FAIL",
            allocated_alpha=exact_alpha + 1e-9,
            per_variant_alpha=exact_alpha + 1e-9,
            **base_kwargs,
        )


def test_replace_record_status_refuses_frozen_field_change() -> None:
    """R3-1: the signature accepts ONLY `status` -- every other field is
    frozen by construction (a keyword `replace_record_status` doesn't
    declare is a `TypeError`, not a deny-list to keep in sync)."""
    record = register_hypothesis(**_valid_kwargs(hypothesis_id="H-REPLACE-STATUS"))
    with pytest.raises(TypeError):
        replace_record_status(  # type: ignore[call-arg]
            record, status="REJECTED", hypothesis_class="OTHER"
        )
    updated = replace_record_status(record, status="REJECTED")
    assert updated.status == "REJECTED"
    assert updated.hypothesis_class == record.hypothesis_class
    assert updated.schema_version == record.schema_version
    assert updated.is_zero_look == record.is_zero_look


def test_v3_look_taking_refused_while_tolling_not_landed() -> None:
    assert HORIZON_TOLLING_LANDED is False
    with pytest.raises(HorizonTollingNotLandedError):
        register_hypothesis(
            **_valid_kwargs(
                hypothesis_id="H-V3-TOLLING",
                k_variants=1,
                re_arm_gating=False,
                variant_stratum_filters=(_VALID_FILTER,),
            )
        )


def test_v3_look_taking_without_filters_refused() -> None:
    """Distinct from the tolling refusal above (`StratumFilterCountMismatchError`
    vs `HorizonTollingNotLandedError`) -- R3-2 places the filters check first,
    so a missing-filters call fails for its OWN reason even though
    `HORIZON_TOLLING_LANDED` is also False."""
    with pytest.raises(StratumFilterCountMismatchError):
        register_hypothesis(
            **_valid_kwargs(hypothesis_id="H-V3-NO-FILTERS", k_variants=1, re_arm_gating=False)
        )


def test_v3_underpowered_call_with_no_filters_and_tolling_not_landed_registers_fine() -> None:
    """R3-2: RA-9 Path A keeps working -- a v3 UNDERPOWERED outcome is never
    blocked by either REGISTERED-branch-only refusal."""
    assert HORIZON_TOLLING_LANDED is False
    record = register_hypothesis(
        **_valid_kwargs(
            hypothesis_id="H-V3-PATH-A",
            k_variants=1,
            re_arm_gating=False,
            mde_plausibility_bound=0.01,
        )
    )
    assert record.status == "UNDERPOWERED_NOT_REGISTERED"
    assert record.schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V3
    assert record.is_zero_look is True
    assert record.variant_stratum_filters == ()


@pytest.mark.parametrize(
    "fixture_path", [LIVE_LEDGER_V1_FIXTURE, LIVE_LEDGER_V2_FIXTURE, LIVE_LEDGER_V3_FIXTURE]
)
def test_each_fixture_round_trips_byte_identically(fixture_path: Path, tmp_path: Path) -> None:
    original_bytes = fixture_path.read_bytes()
    path = tmp_path / fixture_path.name
    path.write_bytes(original_bytes)
    records = read_hypothesis_ledger(path)
    assert len(records) >= 1
    write_hypothesis_ledger(path, records)
    assert path.read_bytes() == original_bytes


def test_mixed_v1_v2_v3_whole_file_rewrite_leaves_existing_lines_byte_identical(
    tmp_path: Path,
) -> None:
    """AC1 extends the pre-existing v1+v2 mixed-rewrite test to v1+v2+v3."""
    v1_bytes = LIVE_LEDGER_V1_FIXTURE.read_bytes()
    v2_bytes = LIVE_LEDGER_V2_FIXTURE.read_bytes()
    v3_bytes = LIVE_LEDGER_V3_FIXTURE.read_bytes()
    path = tmp_path / "mixed.jsonl"
    path.write_bytes(v1_bytes + v2_bytes + v3_bytes)
    existing = read_hypothesis_ledger(path)
    write_hypothesis_ledger(path, existing)
    rewritten_lines = set(path.read_text(encoding="utf-8").splitlines())
    original_lines = set((v1_bytes + v2_bytes + v3_bytes).decode("utf-8").splitlines())
    assert rewritten_lines == original_lines
