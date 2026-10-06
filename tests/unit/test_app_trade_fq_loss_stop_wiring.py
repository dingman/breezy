"""F6 FQ-BRIDGE wiring: the real ``app.trade.run`` FQ boot composes ONE veto
(family halt first, then the loss stop) that reaches both the strategies and
the exec client, and ``app/trade.py`` changes only
``_compose_forecast_quantile_ladder`` (E-28 / RC-7 carve-out).
"""

from __future__ import annotations

import ast
import io
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    SCHEMA,
    FqComposedVeto,
    LossStopProbeActor,
    compute_digest,
)
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
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


def _write_artefact(path: Path, *, verdict: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    as_of = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "verdict": verdict,
                "as_of": as_of,
                "c2_hwm": "c2-1",
                "truth_sha": "t" * 64,
                "digest": compute_digest(
                    verdict=verdict, as_of=as_of, c2_hwm="c2-1", truth_sha="t" * 64
                ),
            }
        )
    )
    path.chmod(0o600)


def _boot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, verdict: str | None) -> _Observed:
    family_id = "pm_us_fq_f6_wiring"
    families_dir = tmp_path / "deploy" / "families"
    _write_forecast_quantile_ladder_manifest(families_dir, family_id=family_id, stations=_STATIONS)
    monkeypatch.chdir(tmp_path)
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_d_plus_1_catalog(catalog_root)
    if verdict is not None:
        _write_artefact(tmp_path / "derived/fq-loss-stop/latest.json", verdict=verdict)
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


# --------------------------------------------------------------------------
# diff-scope guard (E-28)
# --------------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_REPO, check=True, capture_output=True, text=True
    ).stdout


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


def test_f6_trade_py_changes_only_compose_fq() -> None:
    base = _merge_base()
    if base is None:
        pytest.skip("no merge base available")
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
    }
)


def test_f6_diff_name_only_is_within_scope() -> None:
    base = _merge_base()
    if base is None:
        pytest.skip("no merge base available")
    names = set(_git("diff", "--name-only", base).split())

    assert names <= _ALLOWED_DIFF
