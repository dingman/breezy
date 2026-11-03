"""Synthetic, outcome-blind contracts for LEAK-NULL seam A."""

from __future__ import annotations

import datetime as dt
import hashlib
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import pytest

import breezy.analysis.leak_null as ln
import breezy.analysis.multisource_blend as msb
from breezy.analysis.multisource_blend_features import _assert_admissible
from tests.unit.test_multisource_blend import _lamp_feature, _pct, _row, make_rows
from tests.unit.test_multisource_blend_skill import _PINS


def _null_fixture() -> tuple[tuple[msb.FeatureRow, ...], msb.FoldPlan, msb.BlendSettings]:
    rows = make_rows(days=84, start=dt.date(2025, 1, 1), version="v4.2", seed=11)
    rows += make_rows(days=84, start=dt.date(2025, 3, 26), version="v4.3", seed=12)
    rows = [
        replace(r, lamp=msb.MISSING_LAMP) if r.horizon == "D-1" or (i // 2) % 3 == 0 else r
        for i, r in enumerate(rows)
    ]
    plan = msb.build_folds(
        msb.days_by_version(rows),
        source_breaks=[],
        block_days=28,
        min_train_days=28,
        min_blocks=2,
    )
    settings = msb.BlendSettings(
        nu=_PINS["student_t_nu"],
        sigma_floor_f=_PINS["sigma_floor_f"],
        weight_sum_lambda=_PINS["weight_sum_lambda"],
        min_cell_rows=_PINS["min_cell_rows"],
    )
    return tuple(rows), plan, settings


def _tied_rows() -> tuple[msb.FeatureRow, ...]:
    return tuple(
        _row(
            station="NYC",
            day=dt.date(2025, 1, 1) + dt.timedelta(days=i),
            version="v4.2",
            horizon=h,
            y=70,
            nbp=69,
            sd=2.5,
            obs=None,
            lamp=None,
            pfm=None,
            mos=None,
        )
        for i in range(20)
        for h in ("D-1", "D0")
    )


def _key(r: Any) -> tuple[Any, ...]:
    return r.version, r.station, r.climate_day, r.horizon


def _train_rows(
    rows: Sequence[msb.FeatureRow],
    fold: msb.Fold,
    embargo: int,
) -> tuple[msb.FeatureRow, ...]:
    return tuple(
        r
        for r in rows
        if r.version == fold.version
        and r.climate_day in fold.train_days
        and all(abs((r.climate_day - h).days) > embargo for h in fold.held_days)
    )


@pytest.fixture(scope="module")
def scored_fixture() -> tuple[list[msb.ScoredRow], list[msb.ScoredRow], msb.FoldPlan]:
    rows, plan, settings = _null_fixture()
    labels = ln.null_label_rows(rows, 31)
    first = msb.out_of_fold_scores(
        labels.rows,
        plan,
        settings,
        levels=(0, 3),
        champion=False,
        embargo_days=3,
    )
    third = msb.out_of_fold_scores(
        ln.scramble_sources(labels, 31).rows,
        plan,
        settings,
        levels=(0, 3),
        champion=False,
        embargo_days=3,
    )
    return first, third, plan


def test_null_label_rows_equals_shuffle_labels_same_seed() -> None:
    rows, _, _ = _null_fixture()
    labels = ln.null_label_rows(rows, 31)
    assert labels.rows == tuple(msb.shuffle_labels(rows, seed=31))
    assert labels == ln.null_label_rows(rows, 31)
    assert labels.moved_fraction >= 0.5
    assert all(replace(b, cli_tmax_f=a.cli_tmax_f) == a for a, b in zip(rows, labels.rows))


def test_moved_fraction_counts_keys_not_values_under_integer_ties() -> None:
    rows = _tied_rows()
    keys = list(dict.fromkeys((r.version, r.station, r.climate_day) for r in rows))
    permuted = keys.copy()
    random.Random(31).shuffle(permuted)
    expected = sum(a != b for a, b in zip(keys, permuted)) / len(keys)
    labels = ln.null_label_rows(rows, 31)
    assert labels.rows == rows
    assert labels.moved_fraction == expected >= 0.5


def test_moved_fraction_replay_mismatch_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    rows, _, _ = _null_fixture()
    shuffled = msb.shuffle_labels(rows, seed=31)
    shuffled[0] = replace(shuffled[0], cli_tmax_f=shuffled[0].cli_tmax_f + 1)
    monkeypatch.setattr(msb, "shuffle_labels", lambda rows, *, seed: shuffled)
    with pytest.raises(ln.Refusal, match="replay"):
        ln.null_label_rows(rows, 31)


def test_below_min_moved_fraction_refused() -> None:
    with pytest.raises(ln.Refusal, match="moved_fraction"):
        ln.null_label_rows(_tied_rows()[:2], 31)
    with pytest.raises(ln.Refusal):
        ln.null_label_rows((), 31)


def test_scramble_nested_replace_only_rem_max_pfm_mos() -> None:
    rows, _, _ = _null_fixture()
    labels = ln.null_label_rows(rows, 31)
    scrambled = ln.scramble_sources(labels, 31)
    changed = [False, False, False]
    for a, b in zip(labels.rows, scrambled.rows, strict=True):
        assert replace(b, lamp=a.lamp, pfm_mu_f=a.pfm_mu_f, mos_mu_f=a.mos_mu_f) == a
        assert replace(b.lamp, rem_max_f=a.lamp.rem_max_f) == a.lamp
        for j, pair in enumerate(
            ((a.lamp, b.lamp), (a.pfm_mu_f, b.pfm_mu_f), (a.mos_mu_f, b.mos_mu_f))
        ):
            changed[j] |= pair[0] != pair[1]
    assert all(changed)
    assert scrambled.moved_fraction == labels.moved_fraction
    assert scrambled == ln.scramble_sources(labels, 31)


def test_scramble_preserves_prefix_level_presence_and_timestamps() -> None:
    rows, _, _ = _null_fixture()
    rows = tuple(replace(r, pfm_mu_f=None) if i % 5 == 0 else r for i, r in enumerate(rows))
    rows = tuple(replace(r, mos_mu_f=None) if i % 7 == 0 else r for i, r in enumerate(rows))
    before = ln.null_label_rows(rows, 31)
    after = ln.scramble_sources(before, 31)
    assert ln.prefix_preserved(before.rows, after.rows)
    for a, b in zip(before.rows, after.rows, strict=True):
        assert (a.pfm_mu_f is None) == (b.pfm_mu_f is None)
        assert (a.mos_mu_f is None) == (b.mos_mu_f is None)
        assert replace(b, lamp=a.lamp, pfm_mu_f=a.pfm_mu_f, mos_mu_f=a.mos_mu_f) == a
    assert not ln.prefix_preserved(before.rows, after.rows[:-1])
    present = next(i for i, r in enumerate(after.rows) if not r.lamp.missing)
    broken = list(after.rows)
    broken[present] = replace(broken[present], lamp=msb.MISSING_LAMP)
    assert not ln.prefix_preserved(before.rows, broken)


def test_scramble_permutes_within_version_horizon_only() -> None:
    rows, _, _ = _null_fixture()
    before = ln.null_label_rows(rows, 31)
    after = ln.scramble_sources(before, 31)
    for version in ("v4.2", "v4.3"):
        for horizon in ("D-1", "D0"):
            a = [r for r in before.rows if (r.version, r.horizon) == (version, horizon)]
            b = [r for r in after.rows if (r.version, r.horizon) == (version, horizon)]
            for field in ("pfm_mu_f", "mos_mu_f"):
                assert Counter(getattr(r, field) for r in a) == Counter(
                    getattr(r, field) for r in b
                )
            assert Counter(r.lamp.rem_max_f for r in a) == Counter(r.lamp.rem_max_f for r in b)


def test_scrambled_rows_pass_assert_admissible() -> None:
    rows, _, _ = _null_fixture()
    scrambled = ln.scramble_sources(ln.null_label_rows(rows, 31), 31)
    _assert_admissible(scrambled.rows)


def test_lamp_input_f_follows_rem_max() -> None:
    rows, _, _ = _null_fixture()
    labels = ln.null_label_rows(rows, 31)
    scrambled = ln.scramble_sources(labels, 31)
    assert any(a.lamp_input_f != b.lamp_input_f for a, b in zip(labels.rows, scrambled.rows))
    for r in scrambled.rows:
        if not r.lamp.missing:
            assert r.obs_so_far_f is not None and r.lamp.rem_max_f is not None
            assert r.lamp_input_f == max(r.obs_so_far_f, r.lamp.rem_max_f)
    anchor = rows[0].anchor_ns
    r = replace(
        rows[0],
        obs_so_far_f=60,
        percentiles=_pct(69, 2.5),
        lamp=_lamp_feature(72, anchor_ns=anchor),
    )
    assert r.lamp_input_f == 72


def test_plant_only_on_lamp_present_rows_and_from_null_labels() -> None:
    rows, _, _ = _null_fixture()
    labels = ln.null_label_rows(rows, 31)
    planted = ln.plant_leak(labels, seed=31, noise_sd_f=1.0)
    rng = random.Random(ln.subseed(31, "plant"))
    for a, b in zip(labels.rows, planted.rows, strict=True):
        if a.lamp.missing:
            assert a == b
        else:
            assert b.lamp.rem_max_f == a.cli_tmax_f + rng.gauss(0, 1.0)
            assert replace(b, lamp=a.lamp) == a
            assert replace(b.lamp, rem_max_f=a.lamp.rem_max_f) == a.lamp
    assert ln.prefix_preserved(labels.rows, planted.rows)
    assert planted.moved_fraction == labels.moved_fraction
    assert planted == ln.plant_leak(labels, seed=31, noise_sd_f=1.0)


def test_null_settings_n2_only_changes_lambda() -> None:
    _, _, settings = _null_fixture()
    assert ln.null_settings(settings, ln.NullId.N1) == settings
    assert ln.null_settings(settings, ln.NullId.N3) == settings
    assert ln.null_settings(settings, ln.NullId.N2) == replace(settings, weight_sum_lambda=0)
    assert settings.weight_sum_lambda == 1.0


def test_subseed_distinct_per_tag_and_stable() -> None:
    tags = ["boot:" + str(n) for n in ln.NullId] + [
        "scramble:lamp",
        "scramble:pfm",
        "scramble:mos",
        "plant",
    ]
    assert len({ln.subseed(31, t) for t in tags}) == len(tags)
    for tag in tags:
        assert ln.subseed(31, tag) == int(
            hashlib.sha256(f"leak_null:31:{tag}".encode()).hexdigest()[:16],
            16,
        )


def test_fold_disjointness_clean_on_fixture() -> None:
    rows, plan, _ = _null_fixture()
    assert len(plan.folds) == 6
    assert ln.fold_disjointness_defects(rows, plan, 3) == ()
    duplicate = replace(plan, folds=(*plan.folds, plan.folds[0]))
    assert any("held" in d for d in ln.fold_disjointness_defects(rows, duplicate, 3))
    missing = replace(plan, folds=plan.folds[1:])
    assert any("held 0 times" in d for d in ln.fold_disjointness_defects(rows, missing, 3))


def test_fold_disjointness_flags_planted_overlap() -> None:
    rows, plan, _ = _null_fixture()
    first = plan.folds[0]
    broken = replace(first, train_days=(*first.train_days, first.held_days[0]))
    corrupt = replace(plan, folds=(broken, *plan.folds[1:]))
    assert any("overlap" in d for d in ln.fold_disjointness_defects(rows, corrupt, 3))


def test_fold_disjointness_flags_embargo_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    rows, plan, _ = _null_fixture()
    assert any("embargo" in d for d in ln.fold_disjointness_defects(rows, plan, -1))
    for fold in plan.folds:
        effective = _train_rows(rows, fold, 3)
        assert min(abs((r.climate_day - h).days) for r in effective for h in fold.held_days) > 3

    def unfiltered_train(
        rows: Sequence[msb.FeatureRow],
        fold: msb.Fold,
        embargo_days: int,
    ) -> tuple[msb.FeatureRow, ...]:
        return tuple(
            r for r in rows if r.version == fold.version and r.climate_day in fold.train_days
        )

    monkeypatch.setattr(ln, "_effective_train", unfiltered_train)
    assert any("embargo violation" in d for d in ln.fold_disjointness_defects(rows, plan, 3))


def test_scored_fold_defect_flags_wrong_fold_id(
    scored_fixture: tuple[list[msb.ScoredRow], list[msb.ScoredRow], msb.FoldPlan],
) -> None:
    scored, _, plan = scored_fixture
    assert ln.scored_fold_defects(scored, plan) == ()
    assert ln.scored_fold_defects([replace(scored[0], fold_id=999)], plan)
    assert ln.scored_fold_defects([replace(scored[0], fold_id=1)], plan)
    assert ln.scored_fold_defects([replace(scored[0], version="wrong")], plan)


def test_level0_rows_have_exactly_zero_delta(
    scored_fixture: tuple[list[msb.ScoredRow], list[msb.ScoredRow], msb.FoldPlan],
) -> None:
    scored, _, _ = scored_fixture
    level0 = [r for r in scored if r.levels["M3"] == 0]
    assert level0
    assert all(r.crps["M0prime"] == r.crps["M3"] for r in level0)
    assert ln.level0_max_abs(scored) == 0
    broken = replace(level0[0], crps={"M0prime": 2, "M3": 1})
    assert ln.level0_max_abs([broken]) == 1


def test_n3_m0prime_equals_n1_m0prime(
    scored_fixture: tuple[list[msb.ScoredRow], list[msb.ScoredRow], msb.FoldPlan],
) -> None:
    first, third, _ = scored_fixture
    assert ln.m0prime_max_abs(first, third) <= 1e-9
    assert ln.m0prime_max_abs(first, third[:-1]) == float("inf")
    assert ln.m0prime_max_abs(first, list(reversed(third))) == float("inf")
    broken = replace(third[0], crps={**third[0].crps, "M0prime": first[0].crps["M0prime"] + 1})
    assert ln.m0prime_max_abs(first[:1], [broken]) == pytest.approx(1)


def test_train_set_rederivation_matches_out_of_fold_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    rows, plan, settings = _null_fixture()
    labels = ln.null_label_rows(rows, 31)
    actual: list[tuple[int, tuple[tuple[Any, ...], ...]]] = []
    original = msb.fit_blend

    def spy(
        train: Sequence[msb.FeatureRow],
        *,
        level: int,
        settings: msb.BlendSettings,
    ) -> msb.BlendFit:
        actual.append((level, tuple(_key(r) for r in train)))
        return original(train, level=level, settings=settings)

    monkeypatch.setattr("breezy.analysis.multisource_blend_folds.fit_blend", spy)
    scored = msb.out_of_fold_scores(
        labels.rows,
        plan,
        settings,
        levels=(0, 3),
        champion=False,
        embargo_days=3,
    )
    expected = [
        (level, tuple(_key(r) for r in _train_rows(labels.rows, fold, 3)))
        for fold in plan.folds
        for level in (0, 3)
    ]
    rederived = [
        (level, tuple(_key(r) for r in ln._effective_train(labels.rows, fold, 3)))
        for fold in plan.folds
        for level in (0, 3)
    ]
    assert rederived == expected
    assert actual == expected
    assert ln.fold_disjointness_defects(labels.rows, plan, 3) == ()
    assert ln.scored_fold_defects(scored, plan) == ()
