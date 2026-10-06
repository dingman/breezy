"""CT-12: the FQ manifest through the real ``app.trade.run`` + ``RecordingNode``.

The halt row is written by ``TrialDayLatch.record_policy_halt`` (the
set-family-halt writer) before boot. The halted twin's composed
``submit_veto`` refuses; the unhalted twin permits. The manifest taker
coefficient reaches ``required_fee_coefficient`` -- not the stale CRH
0.06 default, and not the strategy config's own 0.0695 default.

The family-halt key is family-id scoped, so it does not move when the
halt preamble's trial ``key_prefix`` changes. The composed latch reading
a row written under ``forecast_quantile_ladder/trial/`` is what makes
that prefix observable. Not marked ``heavy``: T3 selects this file by path.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.app.trade import run
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.runtime.trade_cli import EXIT_OK
from breezy.strategy.current_rung_hold.trial_day_latch import open_trial_day_latch
from breezy.strategy.forecast_quantile_ladder.decision import Take
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
    PersistentQuantileLadderLatch,
)
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
from tests.unit.test_app_trade_fq_loss_stop_wiring import (
    _write_artefact as _write_loss_stop_artefact,
)
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

# Neither the CRH config default (0.06) nor the FQ config default (0.0695).
_MANIFEST_FEE = "0.055"
_SEEDED_DAY = date(2026, 10, 3)
_SEEDED_RUNG = "gte80lt81"
_SEEDED_STATION = "LAX"
_STATIONS = ("LAX", "MDW", "MIA", "SFO")


_A_TAKE = Take(
    instrument_id="X.POLYMARKET_US",
    station=_SEEDED_STATION,
    climate_day=_SEEDED_DAY,
    side="yes",
    rung_id=_SEEDED_RUNG,
    qty=1,
    ev_net=0.1,
    p_hat=0.5,
    p_lower=0.4,
    p_upper=0.6,
)


@dataclass(frozen=True)
class _BootObservation:
    veto: str | None
    exec_client_veto: str | None
    try_submit_refusal: str | None
    fees: tuple[float, ...]
    allow_short: tuple[bool, ...]
    prefix_row_visible: bool


def _write_manifest(families_dir: Path, *, family_id: str) -> None:
    _write_forecast_quantile_ladder_manifest(
        families_dir,
        family_id=family_id,
        stations=_STATIONS,
    )
    path = families_dir / f"{family_id}.json"
    payload = json.loads(path.read_text())
    payload["taker_fee_coefficient"] = _MANIFEST_FEE
    path.write_text(json.dumps(payload))


def _seed_store(store_path: Path, *, family_id: str, halted: bool) -> None:
    """Real writer, then release the flock so ``run`` can take it."""
    with (
        SqliteStateStore(store_path) as store,
        open_submit_intent_latch(store, store_path) as intent_latch,
    ):
        trial = open_trial_day_latch(
            intent_latch,
            key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
            family_id=family_id,
        )
        PersistentQuantileLadderLatch(trial, now_ns_fn=lambda: 1).latch(
            station=_SEEDED_STATION,
            climate_day=_SEEDED_DAY,
            rung_id=_SEEDED_RUNG,
            side="yes",
        )
        if halted:
            trial.record_policy_halt(
                reason="ct-12 characterization",
                evidence_sha256="a" * 64,
                ts_ns=1,
            )


class _ProbeNode(RecordingNode):
    """Reads the composed strategies while ``run`` still holds the flock."""

    observation: _BootObservation | None = None

    def run(self) -> None:
        strategies = [
            strategy
            for strategy in self.trader.strategies
            if isinstance(strategy, ForecastQuantileLadderStrategy)
        ]
        assert strategies
        assert len({id(strategy._latch) for strategy in strategies}) == 1
        vetoes = []
        for strategy in strategies:
            assert strategy._submit_veto is not None
            vetoes.append(strategy._submit_veto())
        assert len(set(vetoes)) == 1
        # The callable `run` hands the exec client (the chokepoint at the
        # venue boundary), not just the one the strategies were given.
        exec_veto = self.config.exec_clients[POLYMARKET_US_CLIENT_NAME].submit_veto
        assert callable(exec_veto)
        # Test-local stand-in permit so `try_submit` reaches the veto guard
        # (Phase 0 hands the strategies no permit); no real permit is touched.
        # The fee guard is disabled (the unregistered strategy has no
        # clock), so the family-halt veto is the only guard that can refuse.
        refusals = set()
        for strategy in strategies:
            strategy._order_submission_permit = object()  # type: ignore[assignment]
            strategy._fee_verified = None
            refusals.add(strategy.try_submit(_A_TAKE))
        assert len(refusals) == 1
        latch = strategies[0]._latch
        self.observation = _BootObservation(
            veto=vetoes[0],
            exec_client_veto=exec_veto(),
            try_submit_refusal=refusals.pop(),
            fees=tuple(strategy.config.required_fee_coefficient for strategy in strategies),
            allow_short=tuple(strategy.config.allow_short for strategy in strategies),
            prefix_row_visible=latch.is_latched(
                station=_SEEDED_STATION,
                climate_day=_SEEDED_DAY,
                rung_id=_SEEDED_RUNG,
                side="yes",
            ),
        )
        super().run()


def _boot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    family_id: str,
    halted: bool,
) -> _BootObservation:
    families_dir = tmp_path / "deploy" / "families"
    _write_manifest(families_dir, family_id=family_id)
    monkeypatch.chdir(tmp_path)
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_d_plus_1_catalog(catalog_root)
    # F6: the composed veto also reads the loss-stop artefact (fail closed
    # when absent); the unhalted twin gets a fresh PASS so its assertions hold.
    _write_loss_stop_artefact(tmp_path / "derived/fq-loss-stop/latest.json", verdict="PASS")
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: family_id,
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    _seed_store(Path(env["POLYMARKET_US_EXEC_STATE_DB"]), family_id=family_id, halted=halted)

    code = run(env=env, node_factory=_ProbeNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = _ProbeNode.instances[-1]
    assert isinstance(node, _ProbeNode)
    assert node.observation is not None
    return node.observation


def _assert_manifest_fee_and_prefix(observed: _BootObservation) -> None:
    assert observed.fees
    assert set(observed.fees) == {float(_MANIFEST_FEE)}
    assert float(_MANIFEST_FEE) != 0.06
    assert float(_MANIFEST_FEE) != 0.0695
    assert set(observed.allow_short) == {False}
    assert observed.prefix_row_visible is True


def test_ct12_halted_twin_submit_veto_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    observed = _boot(
        tmp_path,
        monkeypatch,
        family_id="pm_us_fq_ct12_halted",
        halted=True,
    )

    assert observed.veto == "family_halt"
    assert observed.exec_client_veto == "family_halt"
    assert observed.try_submit_refusal == "family_halt"
    _assert_manifest_fee_and_prefix(observed)


def test_ct12_unhalted_twin_submit_veto_permits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    observed = _boot(
        tmp_path,
        monkeypatch,
        family_id="pm_us_fq_ct12_open",
        halted=False,
    )

    assert observed.veto is None
    assert observed.exec_client_veto is None
    assert observed.try_submit_refusal is None
    _assert_manifest_fee_and_prefix(observed)
