"""SL-13 -- ``forecast_quantile_ladder`` composition_kind boots for real
through ``app.trade.run`` (never a stub), and the pre-existing
``forecast_ladder`` refusal is unaffected.

Mirrors ``tests/unit/test_wp11b_active_family_registry.py``'s manifest-
fixture-writing style (``_write_forecast_ladder_manifest``) and
``test_each_composition_kind_boots_alone``'s real-boot-via-RecordingNode
style.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import date, timedelta
from pathlib import Path
from typing import cast

import pytest
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.app.trade import run
from breezy.runtime.settings import LIVE_OBSERVATIONS_VAR, SENDING_FAMILY_ID_VAR, TRADE_CATALOG_ROOT_VAR
from breezy.runtime.trade_cli import EXIT_CONFIG_ERROR, EXIT_OK
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.ingest.nbm_quantile_actor import NbmQuantileActor
from tests.unit.test_trade_cli_current_rung_hold import (  # noqa: F401 -- reused harness
    RecordingNode,
    _clean_nodes,
    _instrument,
    _operator_order_ceiling,
    _today_by_station,
    _trade_env,
    _write_today_catalog,
)
from tests.unit.test_wp11b_active_family_registry import _write_forecast_ladder_manifest


def _write_d_plus_1_catalog(catalog_root: Path) -> None:
    """Same shape as ``_write_today_catalog``, but every instrument's own
    ``climate_day`` is TOMORROW in its station's LST -- this family trades
    D+1 only (SL-13 fix-first follow-up: ``build_forecast_quantile_ladder_
    strategies`` now resolves D+1, never today, so a boot-level test must
    give it a D+1-dated catalog to find anything)."""
    catalog = ParquetDataCatalog(str(catalog_root))
    catalog.write_data(
        [
            # `_today_by_station` is typed `dict[str, object]` upstream (a
            # pre-existing widening, not introduced here); every real value
            # is a `datetime.date` (`climate_day_for_instant`'s own return
            # type), so `.isoformat()`/`+ timedelta` are always valid at
            # runtime -- `cast` documents that, matching this module's own
            # `_write_today_catalog` caller convention.
            _instrument(station=station, climate_day=cast("date", day) + timedelta(days=1))
            for station, day in _today_by_station().items()
        ],
    )

_ARTEFACT_PAYLOAD = {
    "schema_version": 1,
    "cdf_method": "normal",
    "recalibration": "emos",
    "correction_form": "additive",
    "delta": 1.0,
    "kappa": 1.0,
    "emos_params_by_version": {"v1": [0.0, 0.0]},
    "emos_draws_by_version": {"v1": [[0.0, 0.0], [0.05, 0.02], [-0.05, -0.01]]},
    "emos": {"a": 0.0, "gamma": 0.0, "delta": 1.0},
    "n_min": 30,
    "sigma_d": 1.0,
    "rung_probability_bounds": {},
    "fit_status": "OK",
}


def _write_forecast_quantile_ladder_manifest(
    families_dir: Path, *, family_id: str, stations: tuple[str, ...],
) -> None:
    artefacts_dir = families_dir / "artefacts"
    artefacts_dir.mkdir(parents=True, exist_ok=True)
    artefact_path = artefacts_dir / f"{family_id}_density.json"
    raw = json.dumps(_ARTEFACT_PAYLOAD).encode("utf-8")
    artefact_path.write_bytes(raw)
    artefact_sha = hashlib.sha256(raw).hexdigest()

    boundary_path = families_dir / "gs_boundary_fixture.json"
    if not boundary_path.exists():
        boundary_path.write_text(json.dumps({"boundary": "fixture"}))
    boundary_sha = hashlib.sha256(boundary_path.read_bytes()).hexdigest()

    payload = {
        "family_id": family_id,
        "venue": "polymarket_us",
        "trial_id_prefix": f"forecast_quantile_ladder/trial/{family_id}/",
        "d0_climate_day": "2026-09-19",
        "taker_fee_coefficient": "0.06",
        "boundary_artefact_path": str(boundary_path),
        "boundary_inputs_sha256": boundary_sha,
        "composition_kind": "forecast_quantile_ladder",
        "density_artefact_path": str(artefact_path),
        "density_artefact_sha256": artefact_sha,
        "stations": list(stations),
        "status": "REGISTERED",
    }
    (families_dir / f"{family_id}.json").write_text(json.dumps(payload))


def test_forecast_quantile_ladder_composes_real_strategies_and_actors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    families_dir = tmp_path / "deploy" / "families"
    _write_forecast_quantile_ladder_manifest(
        families_dir, family_id="pm_us_crh_fq_test_boot", stations=("LAX", "MDW", "MIA", "SFO"),
    )
    monkeypatch.chdir(tmp_path)

    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_d_plus_1_catalog(catalog_root)

    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_fq_test_boot",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    forecast_strategies = [
        s for s in node.trader.strategies if isinstance(s, ForecastQuantileLadderStrategy)
    ]
    assert forecast_strategies
    assert any(isinstance(a, ForecastQuantileStateActor) for a in node.trader.actors)
    assert any(isinstance(a, NbmQuantileActor) for a in node.trader.actors)


def _write_manifest_pointing_at(
    families_dir: Path, *, family_id: str, artefact_path: Path, artefact_sha256: str,
) -> None:
    """A REGISTERED manifest naming an arbitrary (possibly bad) artefact
    path/sha -- unlike ``_write_forecast_quantile_ladder_manifest``, this
    never writes the artefact file itself; the caller has already written
    (or deliberately NOT written) it."""
    boundary_path = families_dir / "gs_boundary_fixture.json"
    boundary_path.parent.mkdir(parents=True, exist_ok=True)
    if not boundary_path.exists():
        boundary_path.write_text(json.dumps({"boundary": "fixture"}))
    boundary_sha = hashlib.sha256(boundary_path.read_bytes()).hexdigest()

    payload = {
        "family_id": family_id,
        "venue": "polymarket_us",
        "trial_id_prefix": f"forecast_quantile_ladder/trial/{family_id}/",
        "d0_climate_day": "2026-09-19",
        "taker_fee_coefficient": "0.06",
        "boundary_artefact_path": str(boundary_path),
        "boundary_inputs_sha256": boundary_sha,
        "composition_kind": "forecast_quantile_ladder",
        "density_artefact_path": str(artefact_path),
        "density_artefact_sha256": artefact_sha256,
        "stations": ["LAX", "MDW", "MIA", "SFO"],
        "status": "REGISTERED",
    }
    (families_dir / f"{family_id}.json").write_text(json.dumps(payload))


def _boot_env_and_catalog(tmp_path: Path, *, family_id: str) -> dict[str, str]:
    catalog_root = tmp_path / "catalog"
    if not catalog_root.exists():
        catalog_root.mkdir()
        # D+1-dated (not `_write_today_catalog`'s D0): `build_forecast_
        # quantile_ladder_strategies` now resolves D+1 instruments BEFORE
        # ever loading the artefact, so these artefact-failure tests need a
        # catalog that clears instrument resolution -- otherwise a bad
        # artefact would never be reached, and `NoTradableForecastInstrumentsError`
        # (also a clean `EXIT_CONFIG_ERROR`) would mask the property each of
        # these tests actually names.
        _write_d_plus_1_catalog(catalog_root)
    return _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: family_id,
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )


def test_a_sha_mismatched_artefact_fails_closed_with_a_clean_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    families_dir = tmp_path / "deploy" / "families"
    artefacts_dir = families_dir / "artefacts"
    artefacts_dir.mkdir(parents=True, exist_ok=True)
    artefact_path = artefacts_dir / "sha_mismatch_density.json"
    artefact_path.write_bytes(json.dumps(_ARTEFACT_PAYLOAD).encode("utf-8"))
    family_id = "pm_us_crh_fq_sha_mismatch"
    _write_manifest_pointing_at(
        families_dir, family_id=family_id, artefact_path=artefact_path, artefact_sha256="a" * 64,
    )
    monkeypatch.chdir(tmp_path)

    code = run(
        env=_boot_env_and_catalog(tmp_path, family_id=family_id),
        node_factory=RecordingNode,
        stderr=io.StringIO(),
    )

    assert code == EXIT_CONFIG_ERROR
    assert RecordingNode.instances == []


def test_a_malformed_json_artefact_fails_closed_with_a_clean_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    families_dir = tmp_path / "deploy" / "families"
    artefacts_dir = families_dir / "artefacts"
    artefacts_dir.mkdir(parents=True, exist_ok=True)
    artefact_path = artefacts_dir / "malformed_density.json"
    raw = b"{not valid json at all"
    artefact_path.write_bytes(raw)
    family_id = "pm_us_crh_fq_malformed"
    _write_manifest_pointing_at(
        families_dir,
        family_id=family_id,
        artefact_path=artefact_path,
        artefact_sha256=hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.chdir(tmp_path)

    code = run(
        env=_boot_env_and_catalog(tmp_path, family_id=family_id),
        node_factory=RecordingNode,
        stderr=io.StringIO(),
    )

    assert code == EXIT_CONFIG_ERROR
    assert RecordingNode.instances == []


def test_a_schema_missing_key_artefact_fails_closed_with_a_clean_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    families_dir = tmp_path / "deploy" / "families"
    artefacts_dir = families_dir / "artefacts"
    artefacts_dir.mkdir(parents=True, exist_ok=True)
    artefact_path = artefacts_dir / "missing_key_density.json"
    payload = dict(_ARTEFACT_PAYLOAD)
    del payload["emos_draws_by_version"]  # schema-missing key -> KeyError inside the loader
    raw = json.dumps(payload).encode("utf-8")
    artefact_path.write_bytes(raw)
    family_id = "pm_us_crh_fq_missing_key"
    _write_manifest_pointing_at(
        families_dir,
        family_id=family_id,
        artefact_path=artefact_path,
        artefact_sha256=hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.chdir(tmp_path)

    code = run(
        env=_boot_env_and_catalog(tmp_path, family_id=family_id),
        node_factory=RecordingNode,
        stderr=io.StringIO(),
    )

    assert code == EXIT_CONFIG_ERROR
    assert RecordingNode.instances == []


def test_a_non_converged_fit_status_artefact_fails_closed_with_a_clean_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    """SL-8b2: an artefact whose own `fit_status` is not `"OK"` must refuse
    to boot exactly like a bad sha pin, malformed JSON, or a schema-missing
    key -- `load_bounds_artefact_draws` raises `BoundsArtefactPinMismatchError`,
    already in `app/trade.py`'s clean `EXIT_CONFIG_ERROR` tuple."""
    families_dir = tmp_path / "deploy" / "families"
    artefacts_dir = families_dir / "artefacts"
    artefacts_dir.mkdir(parents=True, exist_ok=True)
    artefact_path = artefacts_dir / "not_converged_density.json"
    payload = dict(_ARTEFACT_PAYLOAD, fit_status="FIT_NOT_CONVERGED")
    raw = json.dumps(payload).encode("utf-8")
    artefact_path.write_bytes(raw)
    family_id = "pm_us_crh_fq_not_converged"
    _write_manifest_pointing_at(
        families_dir,
        family_id=family_id,
        artefact_path=artefact_path,
        artefact_sha256=hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.chdir(tmp_path)

    code = run(
        env=_boot_env_and_catalog(tmp_path, family_id=family_id),
        node_factory=RecordingNode,
        stderr=io.StringIO(),
    )

    assert code == EXIT_CONFIG_ERROR
    assert RecordingNode.instances == []


def test_a_missing_artefact_file_fails_closed_with_a_clean_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    families_dir = tmp_path / "deploy" / "families"
    artefact_path = families_dir / "artefacts" / "does_not_exist_density.json"
    family_id = "pm_us_crh_fq_missing_file"
    _write_manifest_pointing_at(
        families_dir, family_id=family_id, artefact_path=artefact_path, artefact_sha256="b" * 64,
    )
    monkeypatch.chdir(tmp_path)

    code = run(
        env=_boot_env_and_catalog(tmp_path, family_id=family_id),
        node_factory=RecordingNode,
        stderr=io.StringIO(),
    )

    assert code == EXIT_CONFIG_ERROR
    assert RecordingNode.instances == []


def test_forecast_ladder_still_refuses_to_boot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    """The PRE-EXISTING ``forecast_ladder`` composition_kind (WP-14, not
    this slice) must keep refusing unconditionally -- SL-13 adds an
    ADJACENT ``forecast_quantile_ladder`` branch, never touches this one."""
    families_dir = tmp_path / "deploy" / "families"
    _write_forecast_ladder_manifest(
        families_dir, family_id="pm_us_crh_fc_sl13_check", trial_suffix="sl13",
    )
    monkeypatch.chdir(tmp_path)

    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)

    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_fc_sl13_check",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_CONFIG_ERROR
    assert RecordingNode.instances == []
