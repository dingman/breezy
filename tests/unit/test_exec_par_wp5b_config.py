"""EXEC-PAR WP5b: node config constants, the marker gate and the config threading.

None of the constants is env-derived, none is an operator control, and at the
shipped K=1 the node config, the ledger and the latch are the K=1 ones.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us import factories
from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.runtime import node_config
from breezy.runtime.exec_par_constants import EXEC_PAR_MAX_CONCURRENT_INTENTS
from breezy.runtime.node_config import (
    BREAKER_HEARTBEAT_MAX_AGE_NS,
    BREAKER_OPEN_AMBIGUOUS_FRACTION,
    EXEC_PAR_FROZEN_BUCKET,
    EXEC_PAR_MARKER_ABSENT_REASON,
    OPEN_EXPOSURE_BOUND_FRACTION,
    RESOLVER_PASS_STALE_NS,
    TRADE_RISK_MAX_ORDER_SUBMIT_RATE,
    build_trade_node_config,
    force_k1_without_supervisor_marker,
)
from breezy.runtime.submit_intent import SubmitIntentLatch, open_submit_intent_latch
from breezy.runtime.submit_intent_slots import (
    BREAKER_HEARTBEAT_MAX_AGE_NS as LATCH_HEARTBEAT_MAX_AGE_NS,
)
from breezy.runtime.submit_intent_slots import (
    BREAKER_RESOLVER_PASS_MAX_AGE_NS as LATCH_RESOLVER_PASS_MAX_AGE_NS,
)
from tests.unit.test_runtime_trade_node_config import (
    make_data_client_config,
    make_exec_client_config,
    make_trade_settings,
)

SEC = 1_000_000_000
_REPO = Path(__file__).resolve().parents[2]
_CONSTANTS = (
    "EXEC_PAR_MAX_CONCURRENT_INTENTS",
    "OPEN_EXPOSURE_BOUND_FRACTION",
    "BREAKER_OPEN_AMBIGUOUS_FRACTION",
    "BREAKER_HEARTBEAT_MAX_AGE_NS",
    "RESOLVER_PASS_STALE_NS",
    "EXEC_PAR_FROZEN_BUCKET",
)


@pytest.fixture(autouse=True)
def _native_order_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    """The native per-order ceiling `build_trade_node_config` requires (not one
    of the two operator-reserved controls; the same stand-in its sibling suite
    uses)."""
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, "25")


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


@contextmanager
def _latch(tmp_path: Path, *, k: int) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(_Store(), tmp_path / "s.db", max_slots=k) as latch:
        yield latch


def _module_assignments() -> dict[str, ast.AnnAssign]:
    tree = ast.parse(Path(inspect.getfile(node_config)).read_text(encoding="utf-8"))
    return {
        node.target.id: node
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


# ---------------------------------------------------------------------------
# The constants
# ---------------------------------------------------------------------------


_CONSTANTS_MODULE = _REPO / "src/breezy/runtime/exec_par_constants.py"


def _constants_module() -> dict[str, ast.AnnAssign]:
    return {
        node.target.id: node
        for node in ast.parse(_CONSTANTS_MODULE.read_text(encoding="utf-8")).body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def test_k_lives_in_a_dependency_free_module_that_node_config_reexports() -> None:
    from breezy.runtime import exec_par_constants

    tree = ast.parse(_CONSTANTS_MODULE.read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported == {"typing"}
    assert exec_par_constants.EXEC_PAR_MAX_CONCURRENT_INTENTS is EXEC_PAR_MAX_CONCURRENT_INTENTS
    assert vars(node_config)["EXEC_PAR_MAX_CONCURRENT_INTENTS"] is EXEC_PAR_MAX_CONCURRENT_INTENTS


def test_constants_are_final_and_not_env_derived() -> None:
    assignments = _module_assignments()
    for name in _CONSTANTS:
        node = assignments[name] if name in assignments else _constants_module()[name]
        annotation = ast.unparse(node.annotation)
        assert annotation.startswith("Final"), name
        assert node.value is not None
        source = ast.unparse(node.value)
        assert "environ" not in source and "getenv" not in source and "os." not in source, name
    assert EXEC_PAR_MAX_CONCURRENT_INTENTS == 1
    assert OPEN_EXPOSURE_BOUND_FRACTION == Decimal("0.50")
    assert BREAKER_OPEN_AMBIGUOUS_FRACTION == Decimal("0.25")
    assert BREAKER_OPEN_AMBIGUOUS_FRACTION < OPEN_EXPOSURE_BOUND_FRACTION
    assert BREAKER_HEARTBEAT_MAX_AGE_NS == 60 * SEC
    assert RESOLVER_PASS_STALE_NS == 600 * SEC
    assert EXEC_PAR_FROZEN_BUCKET == "0.05"


def test_node_constants_agree_with_the_latch_admission_bounds() -> None:
    assert BREAKER_HEARTBEAT_MAX_AGE_NS == LATCH_HEARTBEAT_MAX_AGE_NS
    assert RESOLVER_PASS_STALE_NS == LATCH_RESOLVER_PASS_MAX_AGE_NS


def test_frozen_label_matches_the_wp0_findings_and_is_a_known_bucket() -> None:
    from breezy.adapters.polymarket_us.operator_controls import COST_BUDGET_BUCKET_ORDER

    findings = (_REPO / "docs/evidence/m1v3/exec_parallel_wp0_findings.md").read_text(
        encoding="utf-8"
    )
    assert EXEC_PAR_FROZEN_BUCKET in COST_BUDGET_BUCKET_ORDER
    assert "0.05" in findings


def test_throttle_value_is_unchanged_and_the_comment_states_the_k_gt_1_reasoning() -> None:
    assert TRADE_RISK_MAX_ORDER_SUBMIT_RATE == "5/00:00:01"
    source = Path(inspect.getfile(node_config)).read_text(encoding="utf-8")
    head = source[: source.index("TRADE_RISK_MAX_ORDER_SUBMIT_RATE: Final")]
    comment = head[head.rindex("#: Plan A3") :]
    assert "K>1" in comment and "DROPPED" in comment and "NOT raised" in comment


# ---------------------------------------------------------------------------
# The marker gate
# ---------------------------------------------------------------------------


def test_k_forced_1_when_marker_absent(tmp_path: Path) -> None:
    with _latch(tmp_path, k=2) as latch:
        assert force_k1_without_supervisor_marker(latch, tmp_path / "s.db", admits=lambda _p: False)
        assert latch.max_slots() == 1
        assert latch.k_forced_reason == EXEC_PAR_MARKER_ABSENT_REASON


def test_marker_admits_keeps_k(tmp_path: Path) -> None:
    with _latch(tmp_path, k=2) as latch:
        assert not force_k1_without_supervisor_marker(
            latch, tmp_path / "s.db", admits=lambda _p: True
        )
        assert latch.max_slots() == 2


def test_a_raising_marker_read_counts_as_not_admitted(tmp_path: Path) -> None:
    def boom(_path: Path) -> bool:
        raise OSError("marker unreadable")

    with _latch(tmp_path, k=3) as latch:
        assert force_k1_without_supervisor_marker(latch, tmp_path / "s.db", admits=boom)
        assert latch.max_slots() == 1


def test_at_k1_the_marker_is_never_consulted(tmp_path: Path) -> None:
    calls: list[Path] = []

    def spy(path: Path) -> bool:
        calls.append(path)
        return False

    with _latch(tmp_path, k=1) as latch:
        assert not force_k1_without_supervisor_marker(latch, tmp_path / "s.db", admits=spy)
        assert latch.k_forced_reason is None
    assert calls == []


# ---------------------------------------------------------------------------
# Config threading and K=1 neutrality of the ledger
# ---------------------------------------------------------------------------


def test_trade_node_config_threads_the_constants_to_the_exec_client_config(tmp_path: Path) -> None:
    with _latch(tmp_path, k=1) as latch:
        config = build_trade_node_config(
            make_trade_settings(),
            make_data_client_config(),
            make_exec_client_config(),
            submit_intent_latch=latch,
        )
        wired = config.exec_clients[POLYMARKET_US_CLIENT_NAME]
        assert wired.max_concurrent_intents == EXEC_PAR_MAX_CONCURRENT_INTENTS == 1
        assert wired.open_exposure_bound_fraction == OPEN_EXPOSURE_BOUND_FRACTION
        assert wired.breaker_open_ambiguous_fraction == BREAKER_OPEN_AMBIGUOUS_FRACTION
        assert wired.frozen_cost_budget_bucket == EXEC_PAR_FROZEN_BUCKET


def test_trade_node_config_without_a_latch_carries_k1(tmp_path: Path) -> None:
    config = build_trade_node_config(
        make_trade_settings(), make_data_client_config(), make_exec_client_config()
    )
    wired = config.exec_clients[POLYMARKET_US_CLIENT_NAME]
    assert wired.max_concurrent_intents == 1


def test_trade_node_config_carries_the_latch_k_when_it_exceeds_one(tmp_path: Path) -> None:
    with _latch(tmp_path, k=3) as latch:
        config = build_trade_node_config(
            make_trade_settings(),
            make_data_client_config(),
            make_exec_client_config(),
            submit_intent_latch=latch,
        )
        assert config.exec_clients[POLYMARKET_US_CLIENT_NAME].max_concurrent_intents == 3


def test_k1_ledger_has_no_bounds_and_k_gt_1_ledger_has_the_constants() -> None:
    k1 = factories._spend_ledger_for(make_exec_client_config())
    assert k1._f_adm is None and k1._f_breaker is None
    wired = make_exec_client_config(
        max_concurrent_intents=2,
        open_exposure_bound_fraction=OPEN_EXPOSURE_BOUND_FRACTION,
        breaker_open_ambiguous_fraction=BREAKER_OPEN_AMBIGUOUS_FRACTION,
    )
    k2 = factories._spend_ledger_for(wired)
    assert k2._f_adm == OPEN_EXPOSURE_BOUND_FRACTION
    assert k2._f_breaker == BREAKER_OPEN_AMBIGUOUS_FRACTION


def test_subscribe_trades_off_and_inflight_interval_zero() -> None:
    config = build_trade_node_config(
        make_trade_settings(), make_data_client_config(), make_exec_client_config()
    )
    assert config.exec_engine.inflight_check_interval_ms == 0
    assert config.data_clients[POLYMARKET_US_CLIENT_NAME].subscribe_trades is False


# ---------------------------------------------------------------------------
# No new operator-controls importer
# ---------------------------------------------------------------------------

_IMPORTER_PIN = [
    "scripts/analysis/portfolio_roi_report.py",
    "scripts/operator/print_operator_controls.py",
    "src/breezy/adapters/polymarket_us/exec/client.py",
    "src/breezy/adapters/polymarket_us/factories.py",
    "src/breezy/adapters/polymarket_us/safety.py",
    "src/breezy/runtime/order_enablement.py",
    "src/breezy/strategy/current_rung_hold/continuous_no_side.py",
    "src/breezy/strategy/current_rung_hold/continuous_strategy.py",
]


def test_no_operator_controls_importer_added() -> None:
    importers = sorted(
        path.relative_to(_REPO).as_posix()
        for root in ("src", "scripts")
        for path in (_REPO / root).rglob("*.py")
        if "__pycache__" not in path.parts
        and "operator_controls" in path.read_text(encoding="utf-8")
        and path.name != "operator_controls.py"
    )
    assert importers == _IMPORTER_PIN


@pytest.mark.parametrize(
    "module",
    [
        "src/breezy/runtime/breaker_watcher.py",
        "src/breezy/runtime/exec_par_telemetry.py",
        "src/breezy/runtime/breaker_supervisor_watch.py",
    ],
)
def test_new_modules_name_no_operator_control(module: str) -> None:
    text = (_REPO / module).read_text(encoding="utf-8")
    for needle in (
        "operator_controls",
        "MAX_DAILY_BUDGET",
        "MAX_POSITION_COST",
        "BREEZY_ORDERS_ENABLED",
    ):
        assert needle not in text


# ---------------------------------------------------------------------------
# Bucket guard (E6): one unit, cap / budget; the sentinel forces K=1
# ---------------------------------------------------------------------------


def test_bucket_label_above_0_50_is_sentinel_forcing_k1() -> None:
    from breezy.adapters.polymarket_us.operator_controls import (
        COST_BUDGET_BUCKET_ABOVE_SENTINEL,
        COST_BUDGET_BUCKET_ORDER,
        cost_budget_bucket_rank,
    )

    assert COST_BUDGET_BUCKET_ABOVE_SENTINEL == ">0.50"
    frozen_rank = cost_budget_bucket_rank(EXEC_PAR_FROZEN_BUCKET)
    sentinel_rank = cost_budget_bucket_rank(COST_BUDGET_BUCKET_ABOVE_SENTINEL)
    assert sentinel_rank == len(COST_BUDGET_BUCKET_ORDER) - 1
    assert all(
        sentinel_rank > cost_budget_bucket_rank(label)
        for label in COST_BUDGET_BUCKET_ORDER
        if label != COST_BUDGET_BUCKET_ABOVE_SENTINEL
    )
    # the guard's condition (live rank above frozen rank) is true for the sentinel
    assert sentinel_rank > frozen_rank


def test_frozen_label_and_guard_share_cap_over_budget_units() -> None:
    import ast as _ast

    from breezy.adapters.polymarket_us import operator_controls as oc

    derive = _ast.unparse(
        next(
            n
            for n in _ast.walk(_ast.parse(inspect.getsource(oc.DailySpendLedger)))
            if isinstance(n, _ast.FunctionDef) and n.name == "cost_budget_bucket"
        )
    )
    # the live label is cap / budget (never realized cost / budget) ...
    assert "operator_max_position_cost_usd() / operator_max_daily_budget_usd()" in derive
    # ... and the frozen label is a member of that same ordered label set
    assert EXEC_PAR_FROZEN_BUCKET in oc.COST_BUDGET_BUCKET_ORDER
    assert oc.cost_budget_bucket_rank("0.05") < oc.cost_budget_bucket_rank("0.10")
