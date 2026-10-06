"""F6 FQ-BRIDGE wiring: the real ``app.trade.run`` FQ boot composes ONE veto
(family halt first, then the loss stop) that reaches both the strategies and
the exec client, and ``app/trade.py`` changes only
``_compose_forecast_quantile_ladder`` (E-28 / RC-7 carve-out).
"""

from __future__ import annotations

import ast
import io
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.app.trade import run
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
)
from breezy.runtime.trade_cli import EXIT_OK
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import (
    PARITY_SUBJECT,
    FqComposedVeto,
    LossStopProbeActor,
)
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
from tests.support.fq_loss_stop_artefact import write_artefact
from tests.unit.test_forecast_quantile_ladder_boot import (
    _write_d_plus_1_catalog,
    _write_forecast_quantile_ladder_manifest,
)
from tests.unit.test_trade_cli_current_rung_hold import (  # noqa: F401 -- fixtures
    RecordingNode,
    _clean_nodes,
    _operator_order_ceiling,
    _trade_env,
)

_REPO: Final[Path] = Path(__file__).resolve().parents[2]
_TRADE_PY: Final[str] = "src/breezy/app/trade.py"
_COMPOSE_FQ: Final[str] = "_compose_forecast_quantile_ladder"
_STATIONS: Final = ("LAX", "MDW", "MIA", "SFO")
_BASE_BRANCH: Final[str] = "feat/data-capture-and-risk"


@dataclass(frozen=True)
class _Observed:
    strategy_vetoes: tuple[str | None, ...]
    strategy_veto_ids: tuple[int, ...]
    exec_veto: object
    exec_reason: str | None
    actor_types: tuple[type, ...]


class _Node(RecordingNode):
    observed: _Observed | None = None

    def run(self) -> None:
        strategies = [
            s for s in self.trader.strategies if isinstance(s, ForecastQuantileLadderStrategy)
        ]
        assert strategies
        exec_veto = self.config.exec_clients[POLYMARKET_US_CLIENT_NAME].submit_veto
        assert callable(exec_veto)
        vetoes = [s._submit_veto for s in strategies]
        assert all(v is not None for v in vetoes)
        _Node.observed = _Observed(
            strategy_vetoes=tuple(v() for v in vetoes if v is not None),
            strategy_veto_ids=tuple(id(v) for v in vetoes),
            exec_veto=exec_veto,
            exec_reason=exec_veto(),
            actor_types=tuple(type(a) for a in self.trader.actors),
        )
        super().run()


def _boot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    verdict: str | None,
    family_id: str = "pm_us_fq_f6_wiring",
) -> _Observed:
    families_dir = tmp_path / "deploy" / "families"
    _write_forecast_quantile_ladder_manifest(families_dir, family_id=family_id, stations=_STATIONS)
    monkeypatch.chdir(tmp_path)
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_d_plus_1_catalog(catalog_root)
    if verdict is not None:
        write_artefact(tmp_path / "derived/fq-loss-stop/latest.json", verdict=verdict)
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: family_id,
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    _Node.observed = None
    assert run(env=env, node_factory=_Node, stderr=io.StringIO()) == EXIT_OK
    assert _Node.observed is not None
    return _Node.observed


def test_boot_without_artefact_refuses_fail_closed_on_both_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    obs = _boot(tmp_path, monkeypatch, verdict=None)

    assert set(obs.strategy_vetoes) == {"fq_loss_stop_unknown"}
    assert obs.exec_reason == "fq_loss_stop_unknown"
    assert isinstance(obs.exec_veto, FqComposedVeto)
    assert set(obs.strategy_veto_ids) == {id(obs.exec_veto)}  # ONE shared object
    assert LossStopProbeActor in obs.actor_types


def test_boot_with_fresh_pass_artefact_adds_no_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    obs = _boot(tmp_path, monkeypatch, verdict="PASS")

    assert set(obs.strategy_vetoes) == {None}
    assert obs.exec_reason is None


def test_boot_with_fail_artefact_sets_the_halt_and_halt_reason_comes_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    obs = _boot(tmp_path, monkeypatch, verdict="FAIL")

    assert set(obs.strategy_vetoes) == {"family_halt"}
    assert obs.exec_reason == "family_halt"


def test_boot_of_the_parity_family_wires_the_timer_refreshed_parity_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    # fresh loss-stop PASS, but no derived/fq-parity files: the parity branch
    # (cache refreshed at boot, then on the actor timer) refuses fail closed.
    obs = _boot(tmp_path, monkeypatch, verdict="PASS", family_id=PARITY_SUBJECT)

    assert set(obs.strategy_vetoes) == {"fq_parity_fill_count_unreadable"}
    assert obs.exec_reason == "fq_parity_fill_count_unreadable"
    assert LossStopProbeActor in obs.actor_types


# --------------------------------------------------------------------------
# diff-scope guard (E-28)
# --------------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_REPO, check=True, capture_output=True, text=True
    ).stdout


_F6_MARKER: Final = "src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py"


def _merge_base() -> str | None:
    try:
        return _git("merge-base", "HEAD", _BASE_BRANCH).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _top_level_digests(source: str) -> dict[str, str]:
    """AST dump of every top-level statement, keyed by name (or ordinal)."""
    out: dict[str, str] = {}
    for index, node in enumerate(ast.parse(source).body):
        name = getattr(node, "name", None) or f"<stmt-{index}:{type(node).__name__}>"
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.Import | ast.ImportFrom):
            name = f"<stmt:{ast.unparse(node)[:80]}>"
        out[name] = ast.dump(node)
    return out


def _base_contains_f6(base: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{base}:{_F6_MARKER}"],
            cwd=_REPO,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _base_or_skip_or_fail() -> str:
    """The merge base; when unavailable FAIL under CI / BREEZY_REQUIRE_MERGE_BASE, else skip.

    These are branch-review guards for F6: once F6 is in the base they are vacuous
    (the skip is deliberate and is not converted to a failure by CI).
    """
    base = _merge_base()
    if base is not None:
        if _base_contains_f6(base):
            pytest.skip("F6 already merged into base; diff scope verified at merge")
        return base
    if os.environ.get("CI") or os.environ.get("BREEZY_REQUIRE_MERGE_BASE"):
        pytest.fail("merge base unavailable but CI/BREEZY_REQUIRE_MERGE_BASE requires it")
    pytest.skip("no merge base available")


def test_f6_trade_py_changes_only_compose_fq() -> None:
    base = _base_or_skip_or_fail()
    old = _top_level_digests(_git("show", f"{base}:{_TRADE_PY}"))
    new = _top_level_digests((_REPO / _TRADE_PY).read_text())

    changed = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}

    assert changed <= {_COMPOSE_FQ}


_ALLOWED_DIFF: Final[frozenset[str]] = frozenset(
    {
        _TRADE_PY,
        "src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py",
        "tests/unit/test_fq_loss_stop_probe.py",
        "tests/unit/test_app_trade_fq_loss_stop_wiring.py",
        "tests/unit/test_ct12_fq_halt_through_run.py",
        # additive widening (review fix item 10): the shared artefact helper
        "tests/support/fq_loss_stop_artefact.py",
    }
)


def test_f6_diff_name_only_is_within_scope() -> None:
    base = _base_or_skip_or_fail()
    names = set(_git("diff", "--name-only", base).split())

    assert names <= _ALLOWED_DIFF


@pytest.mark.parametrize("env_name", ["CI", "BREEZY_REQUIRE_MERGE_BASE"])
def test_item9_missing_merge_base_fails_when_ci_or_require_flag_is_set(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("BREEZY_REQUIRE_MERGE_BASE", raising=False)
    monkeypatch.setenv(env_name, "1")
    monkeypatch.setattr(f"{__name__}._merge_base", lambda: None)

    with pytest.raises(pytest.fail.Exception):
        _base_or_skip_or_fail()


def test_item9_missing_merge_base_skips_when_no_flag_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("BREEZY_REQUIRE_MERGE_BASE", raising=False)
    monkeypatch.setattr(f"{__name__}._merge_base", lambda: None)

    with pytest.raises(pytest.skip.Exception):
        _base_or_skip_or_fail()


def test_item9_present_merge_base_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr(f"{__name__}._merge_base", lambda: "abc123")

    assert _base_or_skip_or_fail() == "abc123"


def test_scope_guards_skip_once_f6_is_in_base(monkeypatch: pytest.MonkeyPatch) -> None:
    # HEAD itself contains the probe module, i.e. F6 is already in the base.
    monkeypatch.setenv("CI", "1")
    monkeypatch.setenv("BREEZY_REQUIRE_MERGE_BASE", "1")
    monkeypatch.setattr(f"{__name__}._merge_base", lambda: _git("rev-parse", "HEAD").strip())

    with pytest.raises(pytest.skip.Exception):
        _base_or_skip_or_fail()


def test_scope_guards_stay_active_when_base_lacks_f6(monkeypatch: pytest.MonkeyPatch) -> None:
    pre_f6 = _git("rev-parse", "HEAD~3").strip()
    monkeypatch.setattr(f"{__name__}._merge_base", lambda: pre_f6)

    assert _base_or_skip_or_fail() == pre_f6
