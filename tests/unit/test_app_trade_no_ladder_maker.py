"""ARM C2: the ``no_ladder_maker`` kind boots through the real ``app.trade.run``.

The committed manifest, calibration and boundary artefacts are copied into a temp tree (shas
unchanged, so the real loader and the real sha pins run). The node is the shared ``RecordingNode``
(never started), so what is observed is exactly what ``run`` composed: one strategy, its veto
(the SAME object on the strategy and on the exec client config), the strict harm-stop probe on the
maker's own artefact path, the NBP publisher, and shadow sending when orders are not
requested (the permit is absent; the ruling itself is declared and copied into the temp tree).
"""

from __future__ import annotations

import io
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.app import trade as trade_module
from breezy.app.trade import run
from breezy.ingest.nbm_quantile_actor import NbmQuantileActor
from breezy.persistence import live_orders_gate
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
)
from breezy.runtime.trade_cli import EXIT_OK
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import (
    FqComposedVeto,
    LossStopProbeActor,
)
from breezy.strategy.no_ladder_maker.strategy import NoLadderMakerStrategy
from tests.support.fq_loss_stop_artefact import write_artefact
from tests.unit.test_trade_cli_current_rung_hold import (  # noqa: F401 -- fixtures
    RecordingNode,
    _clean_nodes,
    _operator_order_ceiling,
    _trade_env,
)

REPO: Final[Path] = Path(__file__).resolve().parents[2]
FAMILY: Final[str] = "pm_us_no_maker_sharp_v1"
STATIONS: Final = ("LAX", "MDW", "MIA", "SFO")
ARTEFACTS: Final = (
    "pm_us_no_maker_sharp_v1.json",
    "artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json",
    "artefacts/not_applicable_boundary.json",
    "rulings/RULING_MAKER_sharp_v1_live_small_2026-10-21.md",
)
RULING_ID: Final[str] = "RULING_MAKER_sharp_v1_live_small_2026-10-21"
REAL_D0: Final[str] = "2026-10-25"


@dataclass(frozen=True)
class _Observed:
    strategies: tuple[NoLadderMakerStrategy, ...]
    strategy_vetoes: tuple[str | None, ...]
    strategy_veto_ids: tuple[int, ...]
    exec_veto: object
    exec_reason: str | None
    actor_types: tuple[type, ...]
    probe_strict: tuple[bool, ...]


class _Node(RecordingNode):
    observed: _Observed | None = None

    def run(self) -> None:
        strategies = tuple(
            s for s in self.trader.strategies if isinstance(s, NoLadderMakerStrategy)
        )
        exec_veto = self.config.exec_clients[POLYMARKET_US_CLIENT_NAME].submit_veto
        assert callable(exec_veto)
        vetoes = [s._submit_veto for s in strategies]
        _Node.observed = _Observed(
            strategies=strategies,
            strategy_vetoes=tuple(v() for v in vetoes if v is not None),
            strategy_veto_ids=tuple(id(v) for v in vetoes),
            exec_veto=exec_veto,
            exec_reason=exec_veto(),
            actor_types=tuple(type(a) for a in self.trader.actors),
            probe_strict=tuple(
                a._probe._strict_staleness
                for a in self.trader.actors
                if isinstance(a, LossStopProbeActor)
            ),
        )
        super().run()


def _tree(tmp_path: Path) -> Path:
    families = tmp_path / "deploy" / "families"
    for name in ARTEFACTS:
        target = families / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "deploy" / "families" / name, target)
    return families


def _boot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, verdict: str | None) -> _Observed:
    _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    if verdict is not None:
        write_artefact(tmp_path / "derived/maker-loss-stop/latest.json", verdict=verdict)
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: FAMILY,
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    _Node.observed = None
    assert run(env=env, node_factory=_Node, stderr=io.StringIO()) == EXIT_OK
    assert _Node.observed is not None
    return _Node.observed


def test_boot_composes_one_shadow_only_maker_for_the_four_stations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    obs = _boot(tmp_path, monkeypatch, verdict="PASS")
    (strategy,) = obs.strategies
    assert strategy.config.stations == STATIONS
    assert strategy.config.shadow_only is True, "permit absent: orders were not requested"
    assert strategy.config.allow_short is False and strategy.config.manage_gtd_expiry is True
    assert strategy._theta == 0.0695
    assert strategy._params.max_rungs == 2
    assert NbmQuantileActor in obs.actor_types and LossStopProbeActor in obs.actor_types


def test_the_strategy_and_the_exec_client_share_one_composed_veto_with_a_strict_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    obs = _boot(tmp_path, monkeypatch, verdict="PASS")
    assert isinstance(obs.exec_veto, FqComposedVeto)
    assert set(obs.strategy_veto_ids) == {id(obs.exec_veto)}
    assert obs.probe_strict == (True,), "D1 review K2: the maker's probe is strict"
    assert set(obs.strategy_vetoes) == {None} and obs.exec_reason is None


def test_no_artefact_vetoes_both_paths_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    obs = _boot(tmp_path, monkeypatch, verdict=None)
    assert set(obs.strategy_vetoes) == {"fq_loss_stop_unknown"}
    assert obs.exec_reason == "fq_loss_stop_unknown"


def test_a_fail_artefact_sets_the_family_halt_on_both_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    obs = _boot(tmp_path, monkeypatch, verdict="FAIL")
    assert set(obs.strategy_vetoes) == {"family_halt"}
    assert obs.exec_reason == "family_halt"


def test_the_maker_artefact_path_is_not_the_fq_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    """An FQ PASS must not unlock the maker: the artefact is read at its own directory."""
    _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    write_artefact(tmp_path / "derived/fq-loss-stop/latest.json", verdict="PASS")
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: FAMILY,
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    _Node.observed = None
    assert run(env=env, node_factory=_Node, stderr=io.StringIO()) == EXIT_OK
    assert _Node.observed is not None
    assert set(_Node.observed.strategy_vetoes) == {"fq_loss_stop_unknown"}


# --- the live-orders gate (D6): shipped ruling enables; a closed copy still posts nothing ----


def test_the_shipped_gate_enables_under_a_permit_and_a_closed_copy_posts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Permit present: the shipped ruling enables. A copy with the ruling stripped still answers
    ``no_ruling``, so ``shadow_only`` stays True and a wanted rung produces ZERO commands.

    A real ``OrderSubmissionPermit`` needs the operator-reserved cap environment, which this change
    must not name or assign; the gate's only permit input is a presence bool (what is varied).
    """
    import dataclasses

    from breezy.persistence.family_manifest import load_family_manifest
    from tests.strategy.no_ladder_maker.maker_strategy_support import (
        NOW_NS,
        Harness,
        want,
    )

    manifest = load_family_manifest(REPO / "deploy" / "families" / f"{FAMILY}.json")
    gate = live_orders_gate.live_orders_authorized(manifest, REPO, permit_present=True)
    assert (gate.enabled, gate.reason) == (True, "ok")
    assert gate.ruling_sha256 == (
        "3dd44653bd9d6814ca2b0ea87e9d8bc1f028fa6f612e655216a486c113825152"
    )

    closed = dataclasses.replace(manifest, live_orders_ruling=None)
    closed_gate = live_orders_gate.live_orders_authorized(closed, REPO, permit_present=True)
    assert (closed_gate.enabled, closed_gate.reason, closed_gate.ruling_sha256) == (
        False,
        "no_ruling",
        None,
    )
    h = Harness(shadow_only=not closed_gate.enabled, permit_expires_at_ns=NOW_NS + 10**13)
    rung = h.rung("gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    assert h.drain() == [], "ZERO post_order calls under the closed gate"


def test_a_ruling_id_alone_with_a_permit_present_enables_nothing_and_refuses_the_boot() -> None:
    """X3 (bool level): a manifest naming a ruling, a permit present, no allowlist row -> the
    gate REFUSES (``not_allowlisted``), so ``_compose_no_ladder_maker`` raises ``SettingsError``
    and no strategy is built: REGISTERED / a ruling id alone is not the second key."""
    import dataclasses

    from breezy.persistence.family_manifest import load_family_manifest

    manifest = load_family_manifest(REPO / "deploy" / "families" / f"{FAMILY}.json")
    named = dataclasses.replace(
        manifest, live_orders_ruling="RULING_not_allowlisted_for_sharp_2026-10-21"
    )
    with pytest.raises(live_orders_gate.LiveOrdersGateRefusedError) as refused:
        live_orders_gate.live_orders_authorized(named, REPO, permit_present=True)
    assert refused.value.reason == "not_allowlisted"


def test_the_maker_compose_branch_derives_shadow_only_from_the_gate_output() -> None:
    """The +1 shadow-gate site: ``shadow_only=not live_orders.enabled`` is in BOTH composers."""
    import ast

    tree = ast.parse((REPO / "src/breezy/app/trade.py").read_text(encoding="utf-8"))
    homes: set[str] = set()
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        for node in ast.walk(func):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "shadow_only"
                and ast.unparse(node.value) == "not live_orders.enabled"
            ):
                homes.add(func.name)
    assert homes == {"_compose_forecast_quantile_ladder", "_compose_no_ladder_maker"}
    assert hasattr(trade_module, "_compose_no_ladder_maker")


# --- W6: the D0 placeholder never reaches a live send ------------------------------------------

PLACEHOLDER_D0: Final[str] = "2026-10-28"


def test_the_shipped_manifest_carries_the_real_d0_and_the_ruling() -> None:
    """The ARM commit replaced the sentinel. The shipped manifest is the real D0 plus the ruling."""
    from breezy.persistence.family_manifest import load_family_manifest

    manifest = load_family_manifest(REPO / "deploy" / "families" / f"{FAMILY}.json")
    assert manifest.d0_climate_day == REAL_D0
    assert manifest.live_orders_ruling == RULING_ID


def test_the_placeholder_d0_is_refused_whenever_the_maker_would_send() -> None:
    import dataclasses

    from breezy.persistence.family_manifest import load_family_manifest
    from breezy.strategy.no_ladder_maker.composition import (
        PlaceholderD0Error,
        refuse_placeholder_d0,
    )

    shipped = load_family_manifest(REPO / "deploy" / "families" / f"{FAMILY}.json")
    manifest = dataclasses.replace(shipped, d0_climate_day=PLACEHOLDER_D0, live_orders_ruling=None)
    refuse_placeholder_d0(manifest, shadow_only=True)  # shadow with the sentinel: allowed
    with pytest.raises(PlaceholderD0Error, match="placeholder"):
        refuse_placeholder_d0(manifest, shadow_only=False)
    with_ruling = dataclasses.replace(manifest, live_orders_ruling="RULING_x")
    with pytest.raises(PlaceholderD0Error, match="placeholder"):
        refuse_placeholder_d0(with_ruling, shadow_only=True)
    real_d0 = dataclasses.replace(manifest, d0_climate_day="2026-11-03", live_orders_ruling="R")
    refuse_placeholder_d0(real_d0, shadow_only=False)  # a real D0 passes this guard


def test_boot_refuses_the_placeholder_d0_when_the_gate_answers_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    """Through ``run``: a gate that (hypothetically) said enabled still cannot boot the sentinel.

    The shipped manifest is no longer the sentinel, so this plants a synthetic placeholder copy
    in the temp tree. The gate's output is replaced by a stand-in; no cap is read or assigned.
    """
    import json
    from types import SimpleNamespace

    monkeypatch.setattr(
        trade_module,
        "live_orders_authorized",
        lambda *a, **k: SimpleNamespace(enabled=True, reason="ok", ruling_sha256="0" * 64),
    )
    _tree(tmp_path)
    copied = tmp_path / "deploy" / "families" / f"{FAMILY}.json"
    payload = json.loads(copied.read_text(encoding="utf-8"))
    payload["d0_climate_day"] = PLACEHOLDER_D0
    copied.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: FAMILY,
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    stderr = io.StringIO()
    _Node.observed = None
    assert run(env=env, node_factory=_Node, stderr=stderr) != EXIT_OK
    assert _Node.observed is None, "no node was built"
    assert "placeholder" in stderr.getvalue()
