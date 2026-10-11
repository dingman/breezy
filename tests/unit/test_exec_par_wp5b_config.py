"""EXEC-PAR WP5b: node config constants, the marker gate and the config threading.

None of the constants is env-derived, none is an operator control, and at the
shipped K=1 the node config, the ledger and the latch are the K=1 ones.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import re
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


# ---------------------------------------------------------------------------
# BG-9: EXEC-PAR D-PREREG freeze enforcement and the single-family boot invariant
# ---------------------------------------------------------------------------
#
# Marker convention (the prereg doc is not frozen yet, so this defines it): the
# frozen doc carries, anywhere in its body, one machine-readable line
#
#     <!-- EXEC_PAR_FROZEN_BUCKET: 0.05 -->
#
# That marker is authoritative. If it is absent the parse falls back to the
# prose line "**Frozen label `0.05`.**" (§3). If both exist and disagree, or
# the marker appears twice with different values, the label is unparseable and
# the check fails. "Status:" is read from the doc's "- **Status:** FROZEN" /
# "Status: FROZEN" line. The sibling EXEC-PAR-D-PREREG.sha256 holds the sha256
# hex of the doc bytes (optionally followed by "  <filename>", sha256sum style).
# At configured K=1 the real-repo check is skipped; the checks themselves are
# pure functions over (repo_root, K, frozen_bucket) so K>1 is testable here.


_PREREG_DIR = Path("docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04")
_PREREG_DOC = "EXEC-PAR-D-PREREG.md"
_PREREG_SHA = "EXEC-PAR-D-PREREG.sha256"
_MARKER_RE = re.compile(r"<!--\s*EXEC_PAR_FROZEN_BUCKET:\s*([^\s>]+)\s*-->")
_LABEL_LINE_RE = re.compile(r"\*\*Frozen label\s+`([^`]+)`\.?\*\*")
_STATUS_RE = re.compile(r"^\s*(?:[-*]\s*)?\**Status:\**\s*([A-Za-z]+)", re.MULTILINE)


def parse_frozen_label(text: str) -> str | None:
    """The §3 frozen label: the marker if present, else the prose label line.
    None when absent or ambiguous (conflicting values)."""
    marked = set(_MARKER_RE.findall(text))
    prose = set(_LABEL_LINE_RE.findall(text))
    found = marked or prose
    if marked and prose and marked != prose:
        return None
    return next(iter(found)) if len(found) == 1 else None


def parse_status(text: str) -> str | None:
    match = _STATUS_RE.search(text)
    return match.group(1).upper() if match else None


def freeze_violations(repo_root: Path, k: int, frozen_bucket: str) -> list[str]:
    """Every freeze-enforcement failure at this K; empty at K<=1 (skipped)."""
    if k <= 1:
        return []
    base = repo_root / _PREREG_DIR
    doc = base / _PREREG_DOC
    if not doc.is_file():
        return [f"frozen doc missing: {doc}"]
    doc_bytes = doc.read_bytes()
    problems: list[str] = []
    sha_file = base / _PREREG_SHA
    if not sha_file.is_file():
        problems.append(f"sha256 sibling missing: {sha_file}")
    else:
        tokens = sha_file.read_text(encoding="utf-8").split()
        recorded = tokens[0].lower() if tokens else ""
        if recorded != hashlib.sha256(doc_bytes).hexdigest():
            problems.append("sha256 sibling does not match the doc bytes")
    text = doc_bytes.decode("utf-8", errors="replace")
    status = parse_status(text)
    if status != "FROZEN":
        problems.append(f"doc Status is {status!r}, not 'FROZEN'")
    label = parse_frozen_label(text)
    if label != frozen_bucket:
        problems.append(f"doc frozen label {label!r} != EXEC_PAR_FROZEN_BUCKET {frozen_bucket!r}")
    return problems


def _write_prereg(
    root: Path,
    *,
    status: str = "FROZEN",
    marker: str | None = "0.05",
    sha: str | None = "auto",
    write_doc: bool = True,
) -> None:
    base = root / _PREREG_DIR
    base.mkdir(parents=True)
    body = f"# EXEC-PAR D-PREREG\n\n- **Status:** {status}\n\n"
    if marker is not None:
        body += f"<!-- EXEC_PAR_FROZEN_BUCKET: {marker} -->\n"
    if write_doc:
        (base / _PREREG_DOC).write_text(body, encoding="utf-8")
    if sha == "auto":
        sha = hashlib.sha256(body.encode()).hexdigest() + f"  {_PREREG_DOC}\n"
    if sha is not None:
        (base / _PREREG_SHA).write_text(sha, encoding="utf-8")


def test_freeze_checks_are_skipped_at_k1(tmp_path: Path) -> None:
    # nothing on disk at all: K=1 must not care
    assert freeze_violations(tmp_path, 1, "0.05") == []


def test_freeze_valid_doc_passes_at_k_gt_1(tmp_path: Path) -> None:
    _write_prereg(tmp_path)
    assert freeze_violations(tmp_path, 6, "0.05") == []


def test_freeze_missing_doc_fails_at_k_gt_1(tmp_path: Path) -> None:
    _write_prereg(tmp_path, write_doc=False)
    problems = freeze_violations(tmp_path, 2, "0.05")
    assert len(problems) == 1 and "doc missing" in problems[0]


def test_freeze_missing_sha_sibling_fails(tmp_path: Path) -> None:
    _write_prereg(tmp_path, sha=None)
    assert any("sibling missing" in p for p in freeze_violations(tmp_path, 2, "0.05"))


def test_freeze_bad_hash_fails(tmp_path: Path) -> None:
    _write_prereg(tmp_path, sha="0" * 64 + "\n")
    assert any("does not match" in p for p in freeze_violations(tmp_path, 2, "0.05"))


def test_freeze_empty_sha_file_fails(tmp_path: Path) -> None:
    _write_prereg(tmp_path, sha="")
    assert any("does not match" in p for p in freeze_violations(tmp_path, 2, "0.05"))


def test_freeze_not_frozen_status_fails(tmp_path: Path) -> None:
    _write_prereg(tmp_path, status="DRAFT, not frozen")
    problems = freeze_violations(tmp_path, 2, "0.05")
    assert any("not 'FROZEN'" in p for p in problems)


def test_freeze_label_mismatch_fails(tmp_path: Path) -> None:
    _write_prereg(tmp_path, marker="0.10")
    assert any("!= EXEC_PAR_FROZEN_BUCKET" in p for p in freeze_violations(tmp_path, 2, "0.05"))


def test_freeze_missing_label_fails(tmp_path: Path) -> None:
    _write_prereg(tmp_path, marker=None)
    assert any("None" in p for p in freeze_violations(tmp_path, 2, "0.05"))


def test_parse_frozen_label_marker_prose_and_conflict() -> None:
    assert parse_frozen_label("<!-- EXEC_PAR_FROZEN_BUCKET: 0.05 -->") == "0.05"
    assert parse_frozen_label("- **Frozen label `0.05`.** The unit") == "0.05"
    both_ok = "<!-- EXEC_PAR_FROZEN_BUCKET: 0.05 -->\n**Frozen label `0.05`.**"
    assert parse_frozen_label(both_ok) == "0.05"
    both_bad = "<!-- EXEC_PAR_FROZEN_BUCKET: 0.10 -->\n**Frozen label `0.05`.**"
    assert parse_frozen_label(both_bad) is None
    two_markers = "<!-- EXEC_PAR_FROZEN_BUCKET: 0.10 -->\n<!-- EXEC_PAR_FROZEN_BUCKET: 0.05 -->"
    assert parse_frozen_label(two_markers) is None
    assert parse_frozen_label("nothing here") is None


def test_parse_status_variants() -> None:
    assert parse_status("- **Status:** FROZEN") == "FROZEN"
    assert parse_status("Status: frozen") == "FROZEN"
    assert parse_status("- **Status:** DRAFT, not frozen") == "DRAFT"
    assert parse_status("no status") is None


def test_real_repo_freeze_enforcement() -> None:
    if EXEC_PAR_MAX_CONCURRENT_INTENTS <= 1:
        pytest.skip("configured K=1: D-PREREG freeze checks apply at K>1 only")
    assert freeze_violations(_REPO, EXEC_PAR_MAX_CONCURRENT_INTENTS, EXEC_PAR_FROZEN_BUCKET) == []


def _trade_run_ast() -> ast.FunctionDef:
    from breezy.app import trade

    tree = ast.parse(inspect.getsource(trade))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")


def test_boot_loads_only_the_settings_sending_family() -> None:
    """Single-family invariant (any K): every manifest load in `run` is keyed on
    `settings.sending_family_id` and nothing else."""
    run = _trade_run_ast()
    loads = [
        n
        for n in ast.walk(run)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "load_family_manifest"
    ]
    assert len(loads) == 1
    arg_names = {ast.unparse(n) for n in ast.walk(loads[0].args[0]) if isinstance(n, ast.Attribute)}
    assert "settings.sending_family_id" in arg_names
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "glob"
        for n in ast.walk(run)
    )


def test_boot_raises_settings_error_on_manifest_family_mismatch() -> None:
    run = _trade_run_ast()
    guards = [
        n
        for n in ast.walk(run)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare)
        and ast.unparse(n.test) == "manifest.family_id != settings.sending_family_id"
    ]
    assert len(guards) == 1
    raised = [n for n in ast.walk(guards[0]) if isinstance(n, ast.Raise)]
    assert len(raised) == 1
    assert isinstance(raised[0].exc, ast.Call)
    assert ast.unparse(raised[0].exc.func) == "SettingsError"
