"""AUT-2 FQ-R41 / ARCH C6 l.756-760: the offline registry carries a real Scorer for FQ and both CRH
kinds while every plug-in stays ``refusing`` (so none is complete)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from breezy.analysis.autonomy.evaluators.forecast_quantile_ladder import FqEvaluator
from breezy.analysis.autonomy.offline_plugins import (
    OFFLINE_PLUGINS,
    ContinuousRungHoldOfflinePlugin,
    CurrentRungHoldOfflinePlugin,
)
from breezy.analysis.labeling.attribution import Attribution
from breezy.analysis.labeling.fq_scorer import FqFillInput, Reconciliation
from breezy.analysis.labeling.legacy_crh_scorer import LEGACY_SCORER_ID, LegacyFillInput
from breezy.analysis.labeling.scoring_batch import ScoredBatch, ScoringBatch
from breezy.persistence.autonomy.label_schema import ExcludedReason
from breezy.persistence.autonomy.plugin import PluginRefused
from tests.contract.test_catalog_nws_records import make_climate_day
from tests.support.aut2_fixtures import (
    HOUR_NS,
    RELEASE_NS,
    TS,
    YES,
    durable_fill,
    make_decision,
    make_link,
)

_DAY = dt.date(2026, 10, 2)
_NOW = RELEASE_NS + HOUR_NS


class _Settlements:
    def record(self, station: str, climate_day: dt.date):  # type: ignore[no-untyped-def]
        return make_climate_day(station="LAX", climate_day=_DAY, tmax_f=89)


def _fq_input() -> FqFillInput:
    fill = durable_fill(instrument_id=YES, ts_event=TS)
    decision = make_decision(instrument_id=YES)
    link = make_link(fill.client_order_id, decision.decision_id, instrument_id=YES)
    attribution = Attribution("pm_us_crh_fq_v1", decision, link, False, False, ())
    return FqFillInput(
        fill=fill,
        attribution=attribution,
        scheduled_release_at_ns=RELEASE_NS,
        reconciliation=Reconciliation(True, Decimal(0), "venue_get"),
    )


def test_the_fq_plugin_labels_a_batch_through_the_real_scorer() -> None:
    plugin = OFFLINE_PLUGINS["forecast_quantile_ladder"]
    assert type(plugin) is FqEvaluator

    scored = plugin.label(_DAY, ScoringBatch(_NOW, (), (_fq_input(),)), _Settlements())

    assert isinstance(scored, ScoredBatch) and len(scored.rows) == 1
    row = scored.rows[0]
    assert row.admissible is True and row.realized_pnl == Decimal("0.57")
    assert (scored.p_null_count, scored.non_c1_post_epoch_count) == (0, 0)


def test_the_fq_plugin_stamps_label_seq_against_the_prior_rows() -> None:
    plugin = OFFLINE_PLUGINS["forecast_quantile_ladder"]
    first = plugin.label(_DAY, ScoringBatch(_NOW, (), (_fq_input(),)), _Settlements())

    again = plugin.label(_DAY, ScoringBatch(_NOW + 1, first.rows, (_fq_input(),)), _Settlements())

    assert again.rows == ()  # unchanged content writes no new row


@pytest.mark.parametrize(
    ("kind", "cls"),
    [
        ("current_rung_hold", CurrentRungHoldOfflinePlugin),
        ("continuous_rung_hold", ContinuousRungHoldOfflinePlugin),
    ],
)
def test_both_crh_plugins_label_through_the_legacy_scorer(kind: str, cls: type) -> None:
    plugin = OFFLINE_PLUGINS[kind]
    assert type(plugin) is cls
    legacy = LegacyFillInput(
        fill=durable_fill(instrument_id=YES, ts_event=TS),
        label_family="pm_us_crh_v2",
        trial_id="pm_us_crh_v2/trial/LAX/2026-10-02",
        scored=None,
    )

    scored = plugin.label(_DAY, ScoringBatch(_NOW, (), (legacy,)), None)

    assert len(scored.rows) == 1
    assert scored.rows[0].scorer_id == LEGACY_SCORER_ID
    assert scored.rows[0].excluded_reason is ExcludedReason.UNATTRIBUTED
    assert scored.rows[0].admissible is False and scored.legacy_sell_rows == 0


def test_a_label_call_with_anything_but_a_scoring_batch_is_a_type_error() -> None:
    for plugin in (
        OFFLINE_PLUGINS["forecast_quantile_ladder"],
        OFFLINE_PLUGINS["current_rung_hold"],
        OFFLINE_PLUGINS["continuous_rung_hold"],
    ):
        with pytest.raises(TypeError):
            plugin.label(_DAY, [_fq_input()], _Settlements())


def test_forecast_ladder_still_refuses_label() -> None:
    with pytest.raises(PluginRefused):
        OFFLINE_PLUGINS["forecast_ladder"].label(_DAY, ScoringBatch(_NOW, (), ()), None)


def test_the_label_run_runs_a_refusing_plugin_that_carries_a_scorer(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from breezy.analysis.labeling.label_core import FamilyInfo, run_labels
    from breezy.persistence.autonomy.label_store import RunOutcome
    from tests.support.aut2_run_fixtures import FQ_KIND, make_deps

    deps = make_deps(
        tmp_path,
        registry={FQ_KIND: OFFLINE_PLUGINS[FQ_KIND]},
        families=lambda: (FamilyInfo("pm_us_crh_fq_v1", FQ_KIND, retired=False),),
    )

    result = run_labels(deps)

    assert result.exit_code == 0 and result.run_outcome is RunOutcome.LABELLED
