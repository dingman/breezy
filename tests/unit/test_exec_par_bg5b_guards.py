"""EXEC-PAR BG-5b structural guards: the node never promotes, no network imports, report shape."""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.exec_par_stage_report import report_json
from breezy.runtime.exec_par_stage_types import DayStat, StageReport

_RUNTIME: Final = Path(__file__).resolve().parents[2] / "src" / "breezy" / "runtime"
_NEW_MODULES: Final = (
    "exec_par_stage_runner.py",
    "exec_par_stage_snapshot.py",
    "exec_par_stage_report.py",
    "exec_par_counter_store.py",
    "exec_par_latch_stage.py",
)
#: Writers that move the floor, the K, a look or the cleanup record: the evaluator (r4.5 O5)
#: and everything it calls must never reach them. Only the CLI / BG-10(f) / coordinator do.
_PROMOTING_WRITERS: Final = frozenset(
    {
        "write_stage_reset",
        "write_look",
        "write_cleanup_demotion",
        "write_epoch_row",
        "write_epoch_stop_ts",
        "write_amendment",
        "write_force_k1_cleared",
        "clear_force_k1_flag",
        "clear_flag_write_failed",
        "reset_breaker_halt",
        "write_settled_pnl_day",
        "write_stage_eval_dry",
    }
)
_NETWORK_ROOTS: Final = frozenset({"urllib", "socket", "httpx", "http", "requests", "aiohttp"})


def _names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.Name):
            found.add(node.id)
    return found


@pytest.mark.parametrize("module", ["exec_par_stage_runner.py", "exec_par_stage_snapshot.py"])
def test_the_evaluator_path_never_references_a_promoting_or_floor_moving_writer(
    module: str,
) -> None:
    assert _names(_RUNTIME / module).isdisjoint(_PROMOTING_WRITERS)


@pytest.mark.parametrize("module", _NEW_MODULES)
def test_new_modules_import_no_network_client(module: str) -> None:
    tree = ast.parse((_RUNTIME / module).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots.isdisjoint(_NETWORK_ROOTS)


@pytest.mark.parametrize("module", ["exec_par_stage_runner.py", "exec_par_stage_snapshot.py"])
def test_pure_and_runner_modules_import_no_exec_client_package(module: str) -> None:
    text = (_RUNTIME / module).read_text(encoding="utf-8")
    assert "polymarket_us.exec" not in text


def test_report_json_is_compact_sorted_decimal_strings_with_per_day_ambiguous_counts() -> None:
    report = StageReport(
        stage="S1", configured_k=2, effective_k=2, floor_day="2026-12-01", today="2026-12-05",
        closed_days=3, nonexcluded_days=3, excluded_days=(), posted=9, ambiguous=2,
        ambiguous_rate=Decimal("0.2222"), fills=0, filled_orders=0, days_with_fill=0,
        m_bar=Decimal(3), day_stats=(DayStat("2026-12-02", 3, 1, 0),), minima_met=False,
        dropped_share=None, station_day_flag_days=(), window_flag_days=(), slippage_mean=None,
        slippage_tail_share=None, parity_diff=None, fee_unreconciled_share=None,
        per_fill_fee_mismatches=0, section5_halt_in_stage=False, held_days=0,
        promotion_blocked_reason=None, promotion_pending_commit=False, pnl_pending=0,
        pnl_overdue=0, pnl_ambiguous_unresolved=0, programme_paused=False, notes=("n",),
    )  # fmt: skip
    text = report_json(report)
    assert text == report_json(report)  # deterministic
    assert " " not in text.replace("n", "")  # compact separators
    decoded = json.loads(text)
    assert decoded["ambiguous_rate"] == "0.2222" and decoded["m_bar"] == "3"
    assert decoded["day_stats"] == [{"ambiguous": 1, "day": "2026-12-02", "fills": 0, "posted": 3}]
    assert list(decoded) == sorted(decoded)


def test_the_real_latch_satisfies_the_evaluator_ports_statically(tmp_path: Path) -> None:
    """A mypy-visible conformance check: the latch IS the store, snapshot reads and counter side."""
    from breezy.runtime.breaker_watcher import ExecParStorePort
    from breezy.runtime.exec_par_counter_store import CounterStoreLatch, LatchCounterStore
    from breezy.runtime.exec_par_reconcile import CounterStorePort
    from breezy.runtime.exec_par_stage_runner import StageEvalStore
    from breezy.runtime.exec_par_stage_snapshot import SnapshotReads
    from breezy.runtime.submit_intent import SubmitIntentLatch

    def check(latch: SubmitIntentLatch) -> None:
        store: StageEvalStore = latch
        reads: SnapshotReads = latch
        counter_latch: CounterStoreLatch = latch
        counters: CounterStorePort = LatchCounterStore(latch, wall_ns=lambda: 0)
        writer: ExecParStorePort = latch
        assert [store, reads, counter_latch, counters, writer]

    assert callable(check)
