"""AUT-4 WP2: the closed metric registry and the `eval_replay_path` names (r11 §3.11a)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from breezy.analysis.autonomy import metric_registry as registry

_NAME_RE = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z", re.ASCII)
_PARITY_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "analysis" / "nbp_shadow_parity_pure.py"
)


def test_every_registered_name_is_a_legal_verdict_metric_name() -> None:
    assert all(_NAME_RE.fullmatch(name) for name in registry.METRIC_NAMES)


def test_eval_replay_path_metric_names_registered_and_closed() -> None:
    assert registry.EVAL_REPLAY_PATH_METRICS == frozenset(
        {
            "tape_day",
            "closure_sha256",
            "subject_role",
            "admitted_station_days",
            "excluded_by_reason",
            "parity",
            "day_status",
        }
    )
    assert isinstance(registry.EVAL_REPLAY_PATH_METRICS, frozenset)  # immutable: closed
    assert registry.EVAL_REPLAY_PATH_METRICS <= registry.METRIC_NAMES
    assert registry.is_registered_metric("tape_day")
    assert not registry.is_registered_metric("pnl")
    assert not registry.is_registered_metric("ev_total")


def test_registered_names_carry_no_price_outcome_or_pnl() -> None:
    for name in registry.METRIC_NAMES:
        assert not re.search(r"pnl|price|profit", name), name


def test_eval_replay_path_parity_keys_equal_to_counts_dict_keys() -> None:
    spec = importlib.util.spec_from_file_location("_f7a_parity_pure", _PARITY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    counts_keys = set(module.diff_decision_keys([], []).to_counts_dict())
    assert registry.PARITY_KEYS == counts_keys | set(registry.PARITY_TAKE_COUNT_KEYS)
    assert len(registry.PARITY_TAKE_COUNT_KEYS) == 3


def test_reasons_are_the_plan_literals() -> None:
    assert registry.is_registered_reason("window_cap_below_n_min")
    assert registry.is_registered_reason("calibration_buckets_below_min")
    assert not registry.is_registered_reason("made_up")
    assert registry.DAY_STATUS_NO_INPUT == "NO_INPUT"
