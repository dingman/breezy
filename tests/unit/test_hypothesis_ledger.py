"""RED-first unit tests for `src/breezy/analysis/hypothesis_ledger.py` (AUD-18
Slice A, plan steps 1/2/7).

Plan: `docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md`
SS6.1/SS6.2, SS7 step 1, D1/D4/D6(i)/D12/D13.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.hypothesis_ledger import (
    EVIDENCED_FEE_THETA,
    HYPOTHESIS_LEDGER_SCHEMA_VERSION,
    MAX_HYPOTHESES,
    MAX_SINGLE_DAY_LEG_SHARE,
    MAX_VARIANTS_PER_HYPOTHESIS,
    MIN_PER_VARIANT_ALPHA,
    PROGRAMME_ALPHA,
    STATION_DAY_STATISTIC,
    VARIANCE_BOUND,
    DuplicateHypothesisIdError,
    DuplicateHypothesisLedgerRecordError,
    HypothesisLook,
    HypothesisRecord,
    InvalidLookPolicyError,
    MdeMismatchError,
    NonMeanStationDayStatisticError,
    NonPinnedLegShareCapError,
    NonPositiveVariantCountError,
    NonUnitOrderQuantityError,
    PowerPrimaryOnlyRequiredError,
    ProgrammeBudgetExhaustedError,
    StaleFeeThetaError,
    UnjustifiedVarianceBoundError,
    UnknownHypothesisLedgerSchemaError,
    VariantCountCeilingExceededError,
    alpha_remaining,
    break_even,
    evaluate_pooled_pnl_veto,
    filter_zero_take_station_days,
    is_variant_eligible,
    max_single_day_leg_share,
    pooled_net_pnl_per_contract,
    programme_budget_remaining,
    read_hypothesis_ledger,
    recompute_mde,
    register_hypothesis,
    station_day_mean_variance,
    station_day_mean_x,
    write_hypothesis_ledger,
)
from breezy.settlement.current_rung_hold_v2 import CombinedDraw, StratumRow, combine_station_day

REGISTERED_AT = "2026-09-25"
FREEZE_COMMIT = "abc1234"


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
