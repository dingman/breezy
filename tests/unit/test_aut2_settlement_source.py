"""AUT-2 r7 WP3 / section 3.5: the settlement source is a per-venue registry."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from breezy.analysis.labeling.settlement_source import (
    SETTLEMENT_SOURCES,
    NwsCliFinal,
    RefusingSettlementSource,
    SettlementSourceRefused,
    settlement_source_for,
)
from tests.contract.test_catalog_nws_records import (
    _PRELIM_ISSUED_NS,
    _PRELIM_RETRIEVED_NS,
    make_climate_day,
)

_DAY = dt.date(2026, 8, 22)


def _catalog(tmp_path: Path) -> ParquetDataCatalog:
    root = tmp_path / "catalog"
    root.mkdir()
    return ParquetDataCatalog(path=root)


def test_kalshi_settlement_source_refuses_until_twc_reader(tmp_path: Path) -> None:
    source = settlement_source_for("kalshi", _catalog(tmp_path))

    assert isinstance(source, RefusingSettlementSource)
    with pytest.raises(SettlementSourceRefused, match="twc_reader_absent"):
        source.record("NYC", _DAY)


def test_an_unknown_venue_refuses_rather_than_defaulting(tmp_path: Path) -> None:
    source = settlement_source_for("somewhere_else", _catalog(tmp_path))

    with pytest.raises(SettlementSourceRefused, match="unknown_venue"):
        source.record("NYC", _DAY)


def test_polymarket_uses_nws_cli_final_latest_revision(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    preliminary: Any = make_climate_day(
        tmax_f=82,
        is_final=False,
        revision_seq=1,
        issuance_time_ns=_PRELIM_ISSUED_NS,
        retrieved_at_ns=_PRELIM_RETRIEVED_NS,
        ts_event=_PRELIM_ISSUED_NS,
    )
    final: Any = make_climate_day(tmax_f=84, is_final=True, revision_seq=2)
    catalog.write_data([preliminary])
    catalog.write_data([final])

    source = settlement_source_for("polymarket_us", catalog)
    record = source.record("NYC", _DAY)

    assert isinstance(source, NwsCliFinal)
    assert SETTLEMENT_SOURCES["polymarket_us"] is NwsCliFinal
    assert record is not None and record.is_final is True and record.tmax_f == 84
    assert source.record("NYC", dt.date(2026, 8, 23)) is None
