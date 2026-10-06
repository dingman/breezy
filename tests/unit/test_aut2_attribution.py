"""AUT-2 r7 WP2 / section 3.4: attribution is C1 and nothing else after the epoch.

A POST_EPOCH fill is attributed only through ``client_order_id -> OrderLink -> DecisionRecord``.
A PRE_EPOCH fill gets a storage key for the label file and is never admissible. The C5 fold is a
consistency check, never an attribution source.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling import attribution
from breezy.analysis.labeling.attribution import (
    Attribution,
    BackfillRefused,
    PreEpochAttribution,
    Unresolved,
    UnresolvedRow,
    attribute_fill,
    attribute_post_epoch,
    backfill_family,
    fill_key_sha,
    fq_trial_id,
    label_family_set,
    latch_key_exists,
    write_unresolved_journal,
)
from breezy.analysis.labeling.epoch import C1Index, EpochClass
from breezy.persistence.autonomy.capture_reader import C1View, DecisionView, OrderLinkView
from breezy.persistence.autonomy.label_schema import ExcludedReason
from breezy.persistence.autonomy.single_read import SingleReadReason, SingleReadRefused
from breezy.persistence.family_manifest import FamilyManifest
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.trial_day_latch import open_trial_day_latch
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
    PersistentQuantileLadderLatch,
)
from tests.support.aut2_fixtures import NO, TS, VENUE, durable_fill, make_decision, make_link

_REPO_ROOT = Path(__file__).resolve().parents[2]
_decision = make_decision
_link = make_link


def _c1(*links: OrderLinkView, decisions: tuple[DecisionView, ...] = ()) -> C1Index:
    view = C1View(
        family_id="pm_us_crh_fq_v1",
        decisions=decisions or (_decision(),),
        order_links=links or (_link(),),
        lifecycle_events=(),
        position_marks=(),
        detector_events=(),
    )
    return C1Index([view])


def _manifest(**over: Any) -> FamilyManifest:
    base: dict[str, Any] = {
        "family_id": "pm_us_crh_fq_v1",
        "venue": VENUE,
        "taker_fee_coefficient": __import__("decimal").Decimal("0.0695"),
        "trial_id_prefix": "forecast_quantile_ladder/trial/pm_us_crh_fq_v1/",
        "d0_climate_day": "2026-10-02",
        "boundary_artefact_path": Path("deploy/families/gs_boundary_pm_us_crh_v2.json"),
        "boundary_inputs_sha256": "a" * 64,
        "composition_kind": "forecast_quantile_ladder",
        "density_artefact_path": Path("deploy/families/artefacts/not_applicable_density.json"),
        "density_artefact_sha256": "b" * 64,
        "stations": ("LAX", "SFO"),
        "status": "REGISTERED",
        "manifest_sha256": "e" * 64,
    }
    base.update(over)
    return FamilyManifest(**base)


def _fill(coid: str = "O-1", **over: Any) -> Any:
    return durable_fill(venue_order_id="vo-1", client_order_id=coid, ts_event=TS, **over)


# -- POST_EPOCH: C1 only --------------------------------------------------------------------------


def test_post_epoch_attribution_is_c1_family_only() -> None:
    result = attribute_post_epoch(_fill(), _c1(), venue=VENUE)

    assert isinstance(result, Attribution)
    assert result.family_id == "pm_us_crh_fq_v1"
    assert result.decision.decision_id == "dec-1" and result.link.client_order_id == "O-1"
    assert (result.drill, result.voided_pair, result.alerts) == (False, False, ())
    assert result.excluded_reason is None


@pytest.mark.parametrize(
    ("c1", "reason"),
    [
        (_c1(_link("O-other")), "no_order_link"),
        (_c1(_link(decision_id="dec-gone")), "no_decision"),
        (_c1(_link(), _link(decision_id="dec-2")), "link_conflict"),
        (_c1(decisions=(_decision(p_hat=""),)), "take_without_p_hat"),
    ],
    ids=["no_link", "no_decision", "link_conflict", "null_p_hat"],
)
def test_post_epoch_without_a_clean_c1_join_is_unresolved(c1: C1Index, reason: str) -> None:
    result = attribute_post_epoch(_fill(), c1, venue=VENUE)

    assert result == Unresolved(reason=reason, critical=True)


class _Evidence(C1Index):
    """C1 index plus a fixed epoch, standing in for the production ``C1Epoch``."""

    def __init__(self, c1: C1Index, start: int | None) -> None:
        self._c1 = c1
        self._start = start

    def epoch_start_ns(self) -> int | None:
        return self._start

    def order_link(self, client_order_id: str) -> OrderLinkView | None:
        return self._c1.order_link(client_order_id)

    def order_links(self, client_order_id: str) -> tuple[OrderLinkView, ...]:
        return self._c1.order_links(client_order_id)

    def decision(self, decision_id: str) -> DecisionView | None:
        return self._c1.decision(decision_id)

    def earliest_order_link_ns(self) -> int | None:
        return self._c1.earliest_order_link_ns()


def test_scorer_never_attributes_by_trial_id_prefix() -> None:
    # behaviour: the manifest's prefix names family A, C1 names family B, and C1 wins
    prefix_family = _manifest(
        family_id="pm_us_crh_fq_a", trial_id_prefix="forecast_quantile_ladder/trial/"
    )
    c1 = _c1(decisions=(_decision(family_id="pm_us_crh_fq_b"),))
    result = attribute_fill(
        _fill(),
        _Evidence(c1, start=TS - 100),
        (prefix_family,),
        venue=VENUE,
        trial_key_exists=lambda key: True,
    )
    assert isinstance(result, Attribution) and result.family_id == "pm_us_crh_fq_b"

    # structure: no labelling module reads or passes the prefix field (docstrings may name it)
    def names_prefix(source: str) -> bool:
        return any(
            (isinstance(n, ast.Attribute) and n.attr == "trial_id_prefix")
            or (isinstance(n, ast.Name) and n.id == "trial_id_prefix")
            or (isinstance(n, ast.keyword) and n.arg == "trial_id_prefix")
            for n in ast.walk(ast.parse(source))
        )

    offenders = [
        path.name
        for path in (_REPO_ROOT / "src" / "breezy" / "analysis" / "labeling").glob("*.py")
        if names_prefix(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert names_prefix("def f(m):\n    return m.trial_id_prefix\n")  # positive control


def test_c1_fold_disagreement_alerts_but_never_reattributes() -> None:
    result = attribute_post_epoch(
        _fill(), _c1(), venue=VENUE, champion_at=lambda venue, ts: "pm_us_crh_other"
    )

    assert isinstance(result, Attribution)
    assert result.family_id == "pm_us_crh_fq_v1"  # the C1 family, unchanged
    assert result.alerts == ("c1_fold_disagreement",)
    agreeing = attribute_post_epoch(
        _fill(), _c1(), venue=VENUE, champion_at=lambda venue, ts: "pm_us_crh_fq_v1"
    )
    assert isinstance(agreeing, Attribution) and agreeing.alerts == ()


def test_voided_pair_c1_family_labelled_voided_pair() -> None:
    result = attribute_post_epoch(
        _fill(), _c1(), venue=VENUE, pair_voided=lambda family, ts: family == "pm_us_crh_fq_v1"
    )

    assert isinstance(result, Attribution)
    assert result.family_id == "pm_us_crh_fq_v1"  # the record keeps the C1 family (ARCH C1)
    assert result.voided_pair is True
    assert result.excluded_reason is ExcludedReason.VOIDED_PAIR


def test_drill_flag_taken_from_c1_record() -> None:
    drill = attribute_post_epoch(
        _fill(),
        _c1(decisions=(_decision(drill=True),)),
        venue=VENUE,
        pair_voided=lambda family, ts: False,
    )
    live = attribute_post_epoch(_fill(), _c1(), venue=VENUE)

    assert isinstance(drill, Attribution) and isinstance(live, Attribution)
    assert drill.drill is True and drill.excluded_reason is ExcludedReason.DRILL
    assert live.drill is False
    # the flag is the record's own: a drill fill is still attributed to its C1 family
    assert drill.family_id == live.family_id


# -- PRE_EPOCH: storage key only ----------------------------------------------------------


def _champion(family: str | None) -> Any:
    return lambda venue, ts: family


def test_pre_epoch_fill_never_admissible() -> None:
    result = backfill_family(
        _fill(),
        (_manifest(),),
        epoch_class=EpochClass.PRE_EPOCH,
        champion_at=_champion("pm_us_crh_fq_v1"),
        trial_key_exists=lambda key: True,
        venue=VENUE,
    )

    assert isinstance(result, PreEpochAttribution)
    assert result.storage_key == "pm_us_crh_fq_v1"
    assert result.decision_id is None
    assert result.admissible is False
    assert result.excluded_reason is ExcludedReason.UNATTRIBUTED
    assert {s.value for s in result.allowed_p_sources} == {"artefact_recompute", "none"}


def test_backfill_rules_never_run_post_epoch() -> None:
    with pytest.raises(BackfillRefused):
        backfill_family(
            _fill(),
            (_manifest(),),
            epoch_class=EpochClass.POST_EPOCH,
            champion_at=_champion("pm_us_crh_fq_v1"),
            trial_key_exists=lambda key: True,
            venue=VENUE,
        )


def test_backfill_disagreement_is_unresolved() -> None:
    result = backfill_family(
        _fill(),
        (_manifest(),),
        epoch_class=EpochClass.PRE_EPOCH,
        champion_at=_champion("pm_us_crh_someone_else"),  # (b) says one family
        trial_key_exists=lambda key: True,  # (c) the bridge says another
        venue=VENUE,
    )
    assert result == Unresolved(reason="backfill_disagreement", critical=True)

    neither = backfill_family(
        _fill(),
        (_manifest(),),
        epoch_class=EpochClass.PRE_EPOCH,
        champion_at=None,
        trial_key_exists=lambda key: False,
        venue=VENUE,
    )
    assert neither == Unresolved(reason="no_backfill_family", critical=True)
    two = backfill_family(
        _fill(),
        (_manifest(), _manifest(family_id="pm_us_crh_fq_v2")),
        epoch_class=EpochClass.PRE_EPOCH,
        champion_at=None,
        trial_key_exists=lambda key: True,
        venue=VENUE,
    )
    assert two == Unresolved(reason="no_backfill_family", critical=True)


def test_bridge_alone_resolves_when_it_names_exactly_one_manifest() -> None:
    seen: list[str] = []

    def _exists(key: str) -> bool:
        seen.append(key)
        return True

    result = backfill_family(
        _fill(),
        (_manifest(), _manifest(family_id="pm_us_crh_fq_old", terminal_climate_day="2026-09-30")),
        epoch_class=EpochClass.PRE_EPOCH,
        champion_at=None,
        trial_key_exists=_exists,
        venue=VENUE,
    )

    assert isinstance(result, PreEpochAttribution) and result.storage_key == "pm_us_crh_fq_v1"
    assert seen == [fq_trial_id("LAX", "2026-10-02", "89_90", "yes")]


def test_pre_epoch_family_is_storage_key_only() -> None:
    """No consumer reads the storage key of a ``decision_id=null`` row for a statistic: the name
    ``storage_key`` is read only inside the attribution module itself."""

    def readers(source: str) -> list[int]:
        return [
            node.lineno
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Attribute) and node.attr == "storage_key"
        ]

    offenders = [
        path.relative_to(_REPO_ROOT).as_posix()
        for root in (_REPO_ROOT / "src", _REPO_ROOT / "scripts")
        for path in root.rglob("*.py")
        if path.name != "attribution.py" and readers(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    # positive control: the scan does flag a planted reader
    assert readers("def f(row):\n    return row.storage_key\n") == [2]


# -- the set of families, trial identity, the journal -------------------------------------


def test_retired_family_labelled_until_last_fill() -> None:
    families = label_family_set(
        non_retired=("pm_us_crh_fq_v1",),
        unlabelled_attributed={"pm_us_crh_v4": 2, "pm_us_crh_cont": 0},
    )

    assert families == frozenset({"pm_us_crh_fq_v1", "pm_us_crh_v4"})
    assert label_family_set(non_retired=(), unlabelled_attributed={}) == frozenset()


def test_trial_id_is_stored_latch_key(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        trial_latch = open_trial_day_latch(
            intent_latch, key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX, family_id="pm_us_fq_test"
        )
        PersistentQuantileLadderLatch(trial_latch).latch(
            station="LAX", climate_day=date(2026, 10, 2), rung_id="89_90", side="yes"
        )

    trial_id = fq_trial_id("LAX", "2026-10-02", "89_90", "yes")

    assert trial_id == "forecast_quantile_ladder/trial/LAX/2026-10-02/89_90:yes.POLYMARKET_US"
    assert latch_key_exists(store_path, trial_id) is True  # the key the real writer stored
    assert latch_key_exists(store_path, fq_trial_id("LAX", "2026-10-02", "89_90", "no")) is False
    with pytest.raises(ValueError, match="separator"):
        fq_trial_id("LAX", "2026-10-02", "89:90", "yes")


def test_unresolved_writes_write_once_journal_row(tmp_path: Path) -> None:
    fill = _fill()
    rows = [
        UnresolvedRow(
            fill_key_sha=fill_key_sha(fill),
            base_slug="tc-temp-laxhigh-2026-10-02-gte89lt90f",
            ts_event=fill.ts_event,
            epoch_class=None,
            rule_outcomes=("post_epoch_fill_without_order_link",),
        )
    ]

    path = write_unresolved_journal(tmp_path, rows, now_ns=TS, day="2026-10-06")

    assert (
        path
        == tmp_path / "evidence" / "aut2" / "unresolved" / "2026-10-06" / f"{TS}_label_run.json"
    )
    body = json.loads(path.read_text())
    assert body["rows"][0]["fill_key_sha"] == fill_key_sha(fill)
    assert re.fullmatch(r"[0-9a-f]{64}", body["rows"][0]["fill_key_sha"])
    assert not {"qty", "cost", "fee", "pnl", "price"} & set(body["rows"][0])  # no amounts
    assert write_unresolved_journal(tmp_path, rows, now_ns=TS, day="2026-10-06") == path
    with pytest.raises(SingleReadRefused) as refused:
        write_unresolved_journal(
            tmp_path, [replace(rows[0], ts_event=1)], now_ns=TS, day="2026-10-06"
        )
    assert refused.value.reason is SingleReadReason.EXISTS_DIFFERENT
    assert attribution.UNRESOLVED_JOURNAL_DIR == ("evidence", "aut2", "unresolved")


# -- D1: the decision, the link and the fill must agree in time and on the instrument ------------


@pytest.mark.parametrize(
    ("c1", "reason"),
    [
        (_c1(decisions=(_decision(ts_ns=TS - 4),)), "decision_after_link"),  # link ts is TS - 5
        (_c1(_link(ts_ns=TS + 1)), "link_after_fill"),
        (_c1(decisions=(_decision(instrument_id=NO),)), "instrument_mismatch"),
        (_c1(_link(instrument_id=NO)), "instrument_mismatch"),
    ],
)
def test_post_epoch_attribution_fails_closed_on_time_order_and_instrument(
    c1: C1Index, reason: str
) -> None:
    result = attribute_post_epoch(_fill(), c1, venue=VENUE)

    assert isinstance(result, Unresolved) and result.reason == reason and result.critical is True


def test_a_fill_on_another_instrument_than_its_decision_is_unresolved() -> None:
    result = attribute_post_epoch(_fill(instrument_id=NO), _c1(), venue=VENUE)

    assert isinstance(result, Unresolved) and result.reason == "instrument_mismatch"


def test_equal_timestamps_are_accepted() -> None:
    c1 = _c1(_link(ts_ns=TS - 10), decisions=(_decision(ts_ns=TS - 10),))

    assert isinstance(attribute_post_epoch(_fill(), c1, venue=VENUE), Attribution)
