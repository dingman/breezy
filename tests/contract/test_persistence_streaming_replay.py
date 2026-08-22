"""Contract test settling the `chunk_size` streaming-replay question.

The proposal (SS5) recorded `chunk_size` streaming as raising `RuntimeError` for
Cython `@customdataclass` types, but **unverified for our hand-written
`register_arrow` classes** and not reproducible at the time. Executed here against
the real `NwsClimateDay` on nautilus-trader 1.231.0: it **does** raise.

Mechanism: `BacktestNode._run_streaming` (`backtest/node.py:590`) builds a Rust
`DataBackendSession` via `catalog.backend_session(...)`, which registers our class
by NAME with `session.add_custom_file(...)`. The Rust backend has no knowledge of a
schema registered through the **Python** `register_arrow` registry, so it rejects
the type. `_run_oneshot` never touches the Rust backend for custom data -- it goes
through `_query_pyarrow`, which uses the Python schema -- so one-shot works.

Consequence to carry forward: **backtest replay of Breezy's records is one-shot
only, and therefore capped by memory.** That is a known limit, not a bug to fix
here; closing it would mean moving to a pyo3 record type, which forfeits
`BacktestDataConfig` replay (the pyo3 catalog's on-disk layout reads 0 records
through the Python catalog).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    LoggingConfig,
)

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.persistence.catalog import open_station_catalog, write_records

pytestmark = pytest.mark.contract

_DAY = dt.date(2026, 8, 1)
_BASE_NS = int(dt.datetime(2026, 8, 2, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_DAY_NS = 86_400_000_000_000
_SHA = hashlib.sha256(b"CDUS41 KOKX 020631").hexdigest()


def make_climate_day(index: int, **overrides: Any) -> NwsClimateDay:
    retrieved_at_ns = _BASE_NS + index * _DAY_NS
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY + dt.timedelta(days=index),
        "tmax_f": 80 + index,
        "tmin_f": 60,
        "tavg_f": 70,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": retrieved_at_ns - 60_000_000_000,
        "retrieved_at_ns": retrieved_at_ns,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "1.0.0",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": retrieved_at_ns - 120_000_000_000,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


@pytest.fixture
def populated_catalog_path(tmp_path: Path) -> str:
    catalog = open_station_catalog(tmp_path / "nws", "polymarket_us", "NYC")

    # One file per record, so a streaming session would have several to walk.
    for index in range(4):
        write_records(catalog, [make_climate_day(index)])

    return str(catalog.path)


def _run_config(catalog_path: str, chunk_size: int | None) -> BacktestRunConfig:
    return BacktestRunConfig(
        engine=BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)),
        data=[
            BacktestDataConfig(
                catalog_path=catalog_path,
                # `fully_qualified_name()` returns the COLON form the loader needs;
                # the dotted example in the 1.231.0 docs is a doc bug.
                data_cls=NwsClimateDay.fully_qualified_name(),
                client_id="WEATHER",
            ),
        ],
        venues=[],
        chunk_size=chunk_size,
        raise_exception=True,
    )


def test_chunk_size_streaming_raises_for_our_register_arrow_class(
    populated_catalog_path: str,
) -> None:
    """SETTLED: streaming replay is unavailable for `NwsClimateDay`.

    The plan's "unverified, could not reproduce" is resolved -- it reproduces on
    our hand-written class, for the reason given in the module docstring.
    """
    node = BacktestNode(configs=[_run_config(populated_catalog_path, chunk_size=2)])

    with pytest.raises(RuntimeError) as excinfo:
        node.run()

    assert "NwsClimateDay" in str(excinfo.value)
    assert "ts_init" in str(excinfo.value)


def test_one_shot_replay_loads_our_records(populated_catalog_path: str) -> None:
    """`chunk_size=None` takes the pyarrow path and works. This is the only path."""
    node = BacktestNode(configs=[_run_config(populated_catalog_path, chunk_size=None)])

    results = node.run()

    assert len(results) == 1
