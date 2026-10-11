"""EXEC-PAR BG-10(a): the label-only cost/budget bucket reader.

The reader returns ONLY the ladder label. The BG-10 dhat script's ``--bucket-reader`` prints
only a ladder label. No cap value reaches a return value, a message or stdout.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from breezy.adapters.polymarket_us import operator_controls
from breezy.adapters.polymarket_us.operator_controls import (
    COST_BUDGET_BUCKET_ORDER,
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailySpendLedger,
    cost_budget_bucket_label,
)
from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError
from tests.unit.operator_control_env import operator_control_env, operator_control_unset

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "docs" / "evidence" / "exec_par" / "exec_parallel_dhat_v2.py"
WP0_SCRIPT = REPO / "docs" / "evidence" / "m1v3" / "exec_parallel_dhat.py"
READER_SPEC = "breezy.adapters.polymarket_us.operator_controls:cost_budget_bucket_label"
WP0_SHA256 = "37bc13cc26ef796b1b5dfb5c3cd134e20e4f274940debf98d39e2a81a9f312eb"

CASES = [
    ("1.00", "≤0.02"),
    ("2.00", "≤0.02"),
    ("5.00", "0.05"),
    ("7.77", "0.10"),
    ("25.00", "0.25"),
    ("50.00", "0.50"),
    ("50.01", ">0.50"),
]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exec_parallel_dhat_v2_reader", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["exec_parallel_dhat_v2_reader"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("cap", "label"), CASES)
def test_reader_returns_the_ladder_label_and_nothing_else(cap: str, label: str) -> None:
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "100.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, cap),
    ):
        got = cost_budget_bucket_label()
        ledger_label = DailySpendLedger().cost_budget_bucket()
    assert got == label == ledger_label
    assert got in COST_BUDGET_BUCKET_ORDER
    assert cap not in got and "100" not in got


def test_reader_raises_without_echoing_a_value_when_a_control_is_unset() -> None:
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "100.00"),
        operator_control_unset(MAX_POSITION_COST_USD_ENV_VAR),
        pytest.raises(LiveTradingPermissionError) as err,
    ):
        cost_budget_bucket_label()
    assert "100" not in str(err.value)


def test_reader_is_a_module_level_function() -> None:
    assert cost_budget_bucket_label.__module__ == operator_controls.__name__
    assert cost_budget_bucket_label.__qualname__ == "cost_budget_bucket_label"


@pytest.mark.parametrize(("cap", "label"), CASES)
def test_bucket_reader_flag_prints_only_a_ladder_label(
    cap: str, label: str, capsys: pytest.CaptureFixture[str]
) -> None:
    sim = _load()
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "100.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, cap),
    ):
        rc = sim.main(["--bucket-reader", READER_SPEC, "--label-only"])
    out = capsys.readouterr()
    assert rc == 0
    printed = out.out.strip()
    assert printed == sim.canonical_label(label)
    assert printed in {sim.canonical_label(x) for x in COST_BUDGET_BUCKET_ORDER}
    assert "\n" not in printed
    assert cap not in out.out + out.err
    assert "100" not in out.out + out.err


def test_bucket_reader_flag_refuses_a_non_label_without_echoing_it(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _load()
    fake = ModuleType("bg10_leaky_reader")
    setattr(fake, "leak", lambda: "123.45")  # noqa: B010
    monkeypatch.setitem(sys.modules, "bg10_leaky_reader", fake)
    rc = sim.main(["--bucket-reader", "bg10_leaky_reader:leak", "--label-only"])
    out = capsys.readouterr()
    assert rc == 3
    assert "123.45" not in out.out + out.err


def test_the_wp0_script_stays_byte_identical() -> None:
    assert hashlib.sha256(WP0_SCRIPT.read_bytes()).hexdigest() == WP0_SHA256


def test_the_bg10_script_names_no_operator_value_or_control() -> None:
    source = SCRIPT.read_text()
    assert "max_daily_budget" not in source and "max_per_position" not in source
    assert MAX_DAILY_BUDGET_USD_ENV_VAR not in source
    assert MAX_POSITION_COST_USD_ENV_VAR not in source
