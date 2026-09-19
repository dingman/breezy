"""Review finding A(1)/A(2) (``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md``
§5.1): ``breezy.app.trade.run`` must load the sending family's own manifest
(WP-11b: resolved from ``settings.sending_family_id`` against
``deploy/families/``, never a hardcoded module constant) and thread it into
BOTH the position monitor (via ``build_continuous_rung_hold_strategies``)
and the exec client (via ``trade_cli.run``/``build_trade_node_config``), or
the composition-level wiring in ``composition.py``/``config.py`` is
unreachable dead code in the real process.

Reuses the harness from ``test_trade_cli_current_rung_hold.py`` (env
builder, catalog writer, ``RecordingNode``) rather than redefining it.
"""

from __future__ import annotations

import io
from pathlib import Path

from breezy.app.trade import run
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
)
from breezy.runtime.trade_cli import EXIT_CONFIG_ERROR, EXIT_OK
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from tests.unit.test_trade_cli_current_rung_hold import (  # noqa: F401 -- reused harness
    RecordingNode,
    _operator_order_ceiling,
    _trade_env,
    _write_today_catalog,
)

_LIVE_MANIFEST_PATH = Path("deploy/families/pm_us_crh_cont.json")


def test_continuous_run_loads_and_wires_the_live_manifest_into_the_position_monitor(
    tmp_path: Path,
) -> None:
    """RED (pre-fix): `build_continuous_rung_hold_strategies` had no
    `exit_manifest` parameter and `app/trade.py::run` never loaded one, so
    every `PositionMonitor` this composition root ever built stayed
    permanently shadow (`_exit_manifest is None`), regardless of
    `deploy/families/pm_us_crh_cont.json`'s own content. GREEN: the REAL,
    checked-in manifest -- resolved via `settings.sending_family_id` -- is
    loaded exactly once and reaches the constructed strategy's own monitor.
    """
    assert _LIVE_MANIFEST_PATH.is_file(), "this test assumes the repo's own live manifest exists"
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_cont",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )

    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    strategies = [
        strategy
        for strategy in node.trader.strategies
        if isinstance(strategy, ContinuousRungHoldStrategy)
    ]
    assert strategies, "no ContinuousRungHoldStrategy was registered"
    for strategy in strategies:
        monitor = strategy._position_monitor
        assert monitor is not None
        assert monitor._exit_manifest is not None
        assert monitor._exit_manifest.family_id == "pm_us_crh_cont"
        assert monitor._exit_manifest.composition_kind == "continuous_rung_hold"
        # The LIVE manifest's own content (module docstring of
        # `persistence/exit_gate.py`): no `exit_rule` declared, so the gate
        # stays closed -- wiring it through must never itself arm anything.
        assert monitor._exit_manifest.exit_rule is None
        assert monitor._exit_family_id == "pm_us_crh_cont"


def test_continuous_run_reports_a_configuration_error_for_a_missing_manifest(
    tmp_path: Path,
) -> None:
    """A missing/malformed manifest is a deployment defect, refused cleanly
    (exit 2) -- never an unhandled crash mid-boot. WP-11b: since
    `runtime.settings.load_trade_settings` now validates the manifest at
    SETTINGS-LOAD time (before `run()` reaches composition at all), naming
    an unknown `sending_family_id` is refused there -- there is no module
    constant left to monkeypatch to reach the OLDER inner load."""
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "does_not_exist_2026_09_16",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )

    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_CONFIG_ERROR
