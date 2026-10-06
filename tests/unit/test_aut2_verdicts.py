"""AUT-2 r7 WP5 / section 3.7: the RECONCILIATION and HEALTH ``label_lag`` verdict builders."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling.constants import (
    LABEL_LAG_MAX_H,
    RECON_DAILY_VALIDITY_H,
    RECON_INTRADAY_VALIDITY_H,
    WINDOW_INCOMPLETE_MAX_H,
)
from breezy.analysis.labeling.verdicts import (
    LABEL_LAG_DETECTOR,
    RECONCILIATION_DETECTOR,
    LagFill,
    PolicyBlock,
    ReconMode,
    build_label_lag_verdict,
    build_reconciliation_verdict,
    lag_start_ns,
)
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.verdict import (
    ActionClass,
    Assumption,
    Verdict,
    VerdictKind,
    VerdictOutcome,
)
from tests.support.aut2_fixtures import (
    ART,
    HOUR_NS,
    NOW,
    PASS,
    SHA,
    make_coverage,
    make_recon_facts,
)

_H = HOUR_NS
RULING = "b" * 64


def _metrics(verdict: Verdict) -> dict[str, Any]:
    return dict(verdict.metrics)


def test_daily_reconciliation_valid_26h() -> None:
    daily = build_reconciliation_verdict(make_recon_facts())
    intraday = build_reconciliation_verdict(make_recon_facts(mode=ReconMode.INTRADAY))

    assert daily.valid_until_ns - daily.produced_at_ns == RECON_DAILY_VALIDITY_H * _H == 26 * _H
    assert intraday.valid_until_ns - intraday.produced_at_ns == RECON_INTRADAY_VALIDITY_H * _H
    assert (daily.kind, daily.detector) == (VerdictKind.RECONCILIATION, RECONCILIATION_DETECTOR)
    assert daily.outcome is PASS


def test_subject_sha_is_bound_artefact_sha() -> None:
    verdict = build_reconciliation_verdict(make_recon_facts())

    assert verdict.subject_artefact_sha256 == ART


def test_action_class_read_from_policy_block_only() -> None:
    policy = PolicyBlock(ActionClass.HALT, RULING)

    with_block = build_reconciliation_verdict(make_recon_facts(policy=policy))
    other = build_reconciliation_verdict(
        make_recon_facts(policy=PolicyBlock(ActionClass.ALERT, RULING))
    )

    assert with_block.declared_action_class is ActionClass.HALT
    assert other.declared_action_class is ActionClass.ALERT
    assert with_block.policy_ruling_sha256 == RULING and with_block.assumptions == ()


def test_no_policy_ruling_assumption_without_block() -> None:
    verdict = build_reconciliation_verdict(make_recon_facts(policy=None))

    assert Assumption.NO_POLICY_RULING in verdict.assumptions
    assert verdict.policy_ruling_sha256 is None
    assert verdict.declared_action_class is ActionClass.NONE


@pytest.mark.parametrize(
    "facts",
    [
        {"coverage": make_coverage(unresolved=1, c2_final=9), "breaches": ("unresolved",)},
        {"coverage": make_coverage(missing_label=1, c2_final=9), "breaches": ("missing_label",)},
    ],
)
def test_unresolved_and_missing_label_fail_reconciliation(facts: dict[str, Any]) -> None:
    verdict = build_reconciliation_verdict(make_recon_facts(**facts))

    assert verdict.outcome is VerdictOutcome.FAIL
    m = _metrics(verdict)
    assert m["unresolved"] + m["missing_label"] == Decimal(1)


def test_legs_combine_fail_over_inconclusive_over_pass() -> None:
    assert build_reconciliation_verdict(
        make_recon_facts(position=VerdictOutcome.INCONCLUSIVE)
    ).outcome is (VerdictOutcome.INCONCLUSIVE)
    assert (
        build_reconciliation_verdict(
            make_recon_facts(cash=VerdictOutcome.FAIL, position=VerdictOutcome.INCONCLUSIVE)
        ).outcome
        is VerdictOutcome.FAIL
    )


def test_metrics_include_p_null_and_non_c1_counts() -> None:
    m = _metrics(build_reconciliation_verdict(make_recon_facts()))

    assert m["p_null_count"] == Decimal(2) and m["non_c1_post_epoch_count"] == Decimal(0)
    assert m["durable_fill_count"] == Decimal(10) and m["legacy_labelled"] == Decimal(6)
    assert m["n_min_reason"] == "deterministic_equality_check"


# -- HEALTH label_lag ---------------------------------------------------------------------------


def _lag(fills: list[LagFill], now: int, **kw: Any) -> Verdict:
    return build_label_lag_verdict(
        family_id="pm_us_crh_fq_v1",
        mode=ReconMode.DAILY,
        produced_at_ns=now,
        now_ns=now,
        fills=fills,
        producer_code_sha=SHA,
        subject_artefact_sha256=ART,
        **kw,
    )


def test_no_cli_final_fails_label_lag_at_24h() -> None:
    start = NOW
    fill = LagFill("O-1", start, None)

    inside = _lag([fill], start + 23 * _H)
    past = _lag([fill], start + 25 * _H)

    assert inside.outcome is PASS
    assert past.outcome is VerdictOutcome.FAIL
    assert (past.kind, past.detector) == (VerdictKind.HEALTH, LABEL_LAG_DETECTOR)
    assert _metrics(past)["fills_lagging"] == Decimal(1)


def test_label_lag_clock_starts_at_min_of_settlement_record_and_venue_instant() -> None:
    assert lag_start_ns(1_000, 5_000) == 1_000
    assert lag_start_ns(9_000, 5_000) == 5_000
    assert lag_start_ns(None, 5_000) == 5_000  # an NWS outage still starts the clock


def test_lag_clock_stops_only_on_final_label() -> None:
    start = NOW
    labelled = LagFill("O-1", start, start + 3 * _H)
    late = LagFill("O-2", start, start + 30 * _H)

    assert _lag([labelled], start + 100 * _H).outcome is PASS
    assert _lag([late], start + 100 * _H).outcome is VerdictOutcome.FAIL


def test_fallback_pending_carries_its_cause_metric() -> None:
    fill = LagFill("O-1", NOW, None, awaiting_venue_fallback=True)

    verdict = _lag([fill], NOW + 30 * _H)

    assert _metrics(verdict)["awaiting_venue_fallback"] == Decimal(1)


def test_label_lag_horizon_pinned_under_max_verdict_validity() -> None:
    assert LABEL_LAG_MAX_H == 24 <= pins.MAX_VERDICT_VALIDITY_H
    assert WINDOW_INCOMPLETE_MAX_H == 48
    assert RECON_INTRADAY_VALIDITY_H <= pins.ATTEST_VERDICT_VALIDITY_H  # W1 ATTEST fit
    assert 30 <= pins.INTRADAY_ATTEST_VERDICT_PERIOD_MIN


def test_autonomy_payload_hygiene_scan_covers_aut2_writers() -> None:
    from tests.support.autonomy_scan import relative_path, scan_files
    from tests.unit.test_autonomy_envelope import _scan_payload_hygiene

    root = Path(__file__).resolve().parents[2] / "src/breezy/analysis/labeling"
    writers = [
        root / f"{name}.py"
        for name in (
            "reconcile",
            "verdicts",
            "delivery",
            "skip_journal",
            "prelaunch_intents",
            "attribution",
        )
    ] + [root.parents[1] / "persistence/autonomy/label_store.py"]

    assert all(path.is_file() for path in writers)
    assert scan_files(writers, _scan_payload_hygiene) == []
    planted = _scan_payload_hygiene(
        relative_path(writers[0]), 'def f(path):\n    raise ValueError(f"bad {path}")\n'
    )
    assert [f.detail for f in planted] == ["interpolates path"]


@pytest.mark.parametrize("field", ["unresolved", "missing_label", "n_undecodable"])
def test_coverage_breach_fails_the_verdict_without_caller_breaches(field: str) -> None:
    coverage = make_coverage(**{field: 1})

    verdict = build_reconciliation_verdict(make_recon_facts(coverage=coverage, breaches=()))

    assert verdict.outcome is VerdictOutcome.FAIL


def test_clean_coverage_with_no_breaches_still_passes() -> None:
    assert build_reconciliation_verdict(make_recon_facts(breaches=())).outcome is PASS


def test_caller_metrics_may_not_shadow_core_metrics() -> None:
    with pytest.raises(ValueError, match="unresolved"):
        build_reconciliation_verdict(make_recon_facts(metrics={"unresolved": 0}))


def test_recon_facts_metrics_are_immutable() -> None:
    facts = make_recon_facts(metrics={"p_null_count": 1})

    with pytest.raises(TypeError):
        facts.metrics["p_null_count"] = 2  # type: ignore[index]


def test_label_lag_unreadable_or_empty_fill_store_is_inconclusive_never_pass() -> None:
    empties: tuple[list[LagFill] | None, ...] = (None, [])
    for fills in empties:
        verdict = build_label_lag_verdict(
            family_id="pm_us_crh_fq_v1",
            mode=ReconMode.DAILY,
            produced_at_ns=NOW,
            now_ns=NOW,
            fills=fills,
            producer_code_sha=SHA,
            subject_artefact_sha256=ART,
        )
        assert verdict.outcome is VerdictOutcome.INCONCLUSIVE
