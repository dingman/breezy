"""The ``aut6.health`` C4 verdict writer (plan r15 sections 3.4.1 and 3.11; P6-13)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.persistence.autonomy.paths import AutonomyPaths
from breezy.persistence.autonomy.verdict import (
    ActionClass,
    Assumption,
    Verdict,
    VerdictKind,
    VerdictOutcome,
    read_verdict,
)
from breezy.runtime.unit_health_store import NS, HealthStore
from breezy.runtime.unit_health_types import HostVerdict
from breezy.runtime.unit_health_verdict import (
    HEALTH_PRODUCER_ID,
    HEALTH_VALIDITY_S,
    REFRESH_S,
    HealthVerdictWriter,
    slot_start_ns,
    verdict_metrics,
)

SHA = "ab" * 32
DETECTOR = "aut6.producer_stale"
# 2026-10-09T12:11:30Z: inside the 12:11 slot
T0 = 1_791_548_400 * NS + 11 * 60 * NS + 30 * NS
FAMILY = "pm_us_crh_fq_v1"


def _files(root: Path) -> list[Path]:
    return sorted(p for p in (root / "derived" / "verdicts").rglob("*.json"))


def _writer(tmp_path: Path, subject: str = FAMILY) -> tuple[HealthVerdictWriter, Path, HealthStore]:
    root = tmp_path / "data"
    root.mkdir(mode=0o700, exist_ok=True)
    store = HealthStore(root / "evidence" / "unit_health")
    writer = HealthVerdictWriter(AutonomyPaths(root), store, code_sha=SHA, subject=lambda: subject)
    return writer, root, store


def _result(outcome: str = "PASS", ts: int = T0, **metrics: str) -> HostVerdict:
    return HostVerdict(DETECTOR, outcome, metrics, ts)


def _read(root: Path, path: Path) -> Verdict:
    day = path.parent.name
    return read_verdict(AutonomyPaths(root), path.parent.parent.name, day, path.stem)


def test_producer_id_is_the_p6_13_pin_name() -> None:
    assert HEALTH_PRODUCER_ID == "aut6.health"
    assert HEALTH_VALIDITY_S == 8 * 3600 and REFRESH_S == 3600


@pytest.mark.parametrize(
    ("offset_s", "slot_offset_s"),
    [(0, -540), (59, -540), (60, 60), (61, 60), (659, 60), (660, 660)],
)
def test_slot_start_is_the_ten_minute_boundary_at_minute_one(
    offset_s: int, slot_offset_s: int
) -> None:
    hour = 1_791_548_400  # 12:00:00Z; the slots are :01, :11, ... so 12:00:00 is in 11:51
    assert slot_start_ns((hour + offset_s) * NS) == (hour + slot_offset_s) * NS


def test_a_verdict_is_a_slot_anchored_health_verdict_with_the_pinned_code_sha(
    tmp_path: Path,
) -> None:
    writer, root, _ = _writer(tmp_path)
    writer(_result("FAIL", fold_reason="empty"))
    (path,) = _files(root)
    verdict = _read(root, path)
    assert verdict.kind is VerdictKind.HEALTH
    assert verdict.outcome is VerdictOutcome.FAIL
    assert verdict.subject_family_id == FAMILY and verdict.detector == DETECTOR
    assert verdict.producer_code_sha == SHA
    assert verdict.valid_until_ns == slot_start_ns(T0) + HEALTH_VALIDITY_S * NS
    assert verdict.produced_at_ns == T0
    assert verdict.assumptions == (Assumption.NO_POLICY_RULING,)
    assert verdict.declared_action_class is ActionClass.ALERT
    assert dict(verdict.metrics) == {"cause_class": "INFRA", "fold_reason": "empty"}
    assert (verdict.k_life, verdict.alpha_k, verdict.n_min_eff, verdict.n_cap) == (None,) * 4


def test_the_host_subject_writes_under_the_host_directory(tmp_path: Path) -> None:
    writer, root, _ = _writer(tmp_path, subject="_host")
    writer(_result())
    (path,) = _files(root)
    assert path.parent.parent.name == "_host"
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_the_subject_is_read_at_each_write(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    store = HealthStore(root / "evidence" / "unit_health")
    names = iter(["_host", FAMILY])
    writer = HealthVerdictWriter(
        AutonomyPaths(root), store, code_sha=SHA, subject=lambda: next(names)
    )
    writer(_result("FAIL"))
    writer(_result("PASS", T0 + 60 * NS))
    assert sorted(p.parent.parent.name for p in _files(root)) == ["_host", FAMILY]


def test_same_outcome_inside_the_refresh_period_writes_nothing_more(tmp_path: Path) -> None:
    writer, root, _ = _writer(tmp_path)
    writer(_result("PASS"))
    writer(_result("PASS", T0 + 600 * NS))
    writer(_result("PASS", T0 + (REFRESH_S - 1) * NS))
    assert len(_files(root)) == 1


def test_same_outcome_is_refreshed_once_the_period_has_passed(tmp_path: Path) -> None:
    writer, root, _ = _writer(tmp_path)
    writer(_result("PASS"))
    writer(_result("PASS", T0 + REFRESH_S * NS))
    assert len(_files(root)) == 2


def test_an_outcome_change_writes_at_once(tmp_path: Path) -> None:
    writer, root, _ = _writer(tmp_path)
    writer(_result("PASS"))
    writer(_result("FAIL", T0 + 600 * NS))
    outcomes = {_read(root, p).outcome for p in _files(root)}
    assert outcomes == {VerdictOutcome.PASS, VerdictOutcome.FAIL}


def test_a_recompute_in_the_same_slot_dedupes(tmp_path: Path) -> None:
    writer, root, store = _writer(tmp_path)
    writer(_result("FAIL", n="3"))
    first = _files(root)
    store.write_seen(f"verdict_{FAMILY}_{DETECTOR}", {})  # forget the refresh clock: write again
    writer(_result("FAIL", T0 + 5 * NS, n="3"))
    assert _files(root) == first  # same body, same slot: EXISTS_EQUAL, never a second file


def test_each_detector_and_subject_keeps_its_own_refresh_clock(tmp_path: Path) -> None:
    writer, root, _ = _writer(tmp_path)
    writer(_result("PASS"))
    writer(HostVerdict("aut6.timer_liveness", "PASS", {}, T0 + 60 * NS))
    assert len(_files(root)) == 2


def test_an_unknown_detector_is_refused_not_guessed(tmp_path: Path) -> None:
    writer, root, _ = _writer(tmp_path)
    with pytest.raises(ValueError, match="not in the AUT-6 catalogue"):
        writer(HostVerdict("aut6.not_a_detector", "PASS", {}, T0))
    assert _files(root) == []


def test_a_node_local_detector_declares_no_verdict(tmp_path: Path) -> None:
    writer, root, _ = _writer(tmp_path)
    with pytest.raises(ValueError, match="declares no action class"):
        writer(HostVerdict("feed_stale", "PASS", {}, T0))
    assert _files(root) == []


def test_an_unknown_outcome_is_refused(tmp_path: Path) -> None:
    writer, _root, _ = _writer(tmp_path)
    with pytest.raises(KeyError):
        writer(HostVerdict(DETECTOR, "MAYBE", {}, T0))


def test_the_last_write_is_kept_in_the_seen_store_not_a_new_file_kind(tmp_path: Path) -> None:
    writer, root, store = _writer(tmp_path)
    writer(_result("FAIL"))
    seen = store.read_seen(f"verdict_{FAMILY}_{DETECTOR}")
    assert seen is not None and seen["outcome"] == "FAIL" and seen["ts_ns"] == T0
    assert json.loads(_files(root)[0].read_text())["detector"] == DETECTOR


# --------------------------------------------------------------------------- metric hygiene


def test_metrics_carry_cause_class_and_are_sorted_and_unique() -> None:
    metrics = verdict_metrics({"b": "x", "a": "y"}, "INFRA")
    assert metrics == (("a", "y"), ("b", "x"), ("cause_class", "INFRA"))


def test_a_canonical_decimal_text_becomes_a_decimal() -> None:
    metrics = dict(verdict_metrics({"age_s": "900", "ratio": "0.5", "ver": "1.50"}, "INFRA"))
    assert metrics["age_s"] == Decimal(900) and metrics["ratio"] == Decimal("0.5")
    assert metrics["ver"] == "1.50"  # not canonical: stays text


def test_text_is_reduced_to_the_verdict_charset_and_bounded() -> None:
    metrics = dict(
        verdict_metrics(
            {"Path Name": "/home/jon/x y", "empty": "", "long": "z" * 300, "1st": "v"}, "INFRA"
        )
    )
    assert metrics["path_name"] == "_home_jon_x_y"
    assert metrics["empty"] == "none"
    assert metrics["long"] == "z" * 128
    assert metrics["m_1st"] == "v"


def test_a_metric_cannot_override_the_cause_class() -> None:
    assert dict(verdict_metrics({"cause_class": "MODEL"}, "INFRA"))["cause_class"] == "INFRA"


def test_names_that_collide_after_cleaning_keep_the_first() -> None:
    metrics = dict(verdict_metrics({"a-b": "1x", "a b": "2x"}, "INFRA"))
    assert metrics["a_b"] in {"1x", "2x"} and len(metrics) == 2
