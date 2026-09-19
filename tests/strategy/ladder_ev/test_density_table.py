"""T1: 6-rung density partition identity (spec §3.2 / §13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.strategy.ladder_ev.density_table import (
    CORPUS_SHA256,
    ON_DISK_BUILD_RAN,
    RUNG_IDS,
    DensityRecord,
    build_density_table,
    partition_check,
)


def test_partition_sums_to_one_per_key() -> None:
    records = [
        DensityRecord(
            station="MDW",
            season="JJA",
            hour_lst=14,
            width_code=0,
            m_code=0,
            rung_id=rung_id,
        )
        for rung_id, count in zip(RUNG_IDS, (10, 20, 30, 15, 15, 10), strict=True)
        for _ in range(count)
    ]
    table = build_density_table(records)
    partition_check(table)
    key = ("MDW", "JJA", 14, 0, 0)
    p_hats = [table[key][rung_id].p_hat for rung_id in RUNG_IDS]
    assert sum(p_hats) == pytest.approx(1.0, abs=1e-9)
    assert table[key]["lt"].n_cell == 100
    assert table[key]["i1"].p_hat == pytest.approx(0.30)


def test_partition_check_rejects_a_broken_key() -> None:
    from dataclasses import replace

    records = [
        DensityRecord(
            station="LAX",
            season="DJF",
            hour_lst=12,
            width_code=1,
            m_code=0,
            rung_id=rung_id,
        )
        for rung_id in RUNG_IDS
    ]
    table = build_density_table(records)
    key = ("LAX", "DJF", 12, 1, 0)
    cells = dict(table[key])
    cells["gte"] = replace(cells["gte"], p_hat=cells["gte"].p_hat + 0.5)
    with pytest.raises(AssertionError):
        partition_check({key: cells})


def test_corpus_sha256_is_a_hex_pin() -> None:
    from breezy.strategy.current_rung_hold.archive_table import (
        CORPUS_SHA256 as CRH_CORPUS_SHA256,
    )

    assert len(CORPUS_SHA256) == 64
    int(CORPUS_SHA256, 16)
    assert CORPUS_SHA256 == CRH_CORPUS_SHA256


def test_on_disk_build_flag_is_explicit() -> None:
    assert ON_DISK_BUILD_RAN is False


def test_density_cell_bounds_are_non_optional() -> None:
    """Degraded 6-rung cells keep a structurally non-null Wilson interval."""
    from typing import get_type_hints

    from breezy.strategy.ladder_ev.density_table import DensityCell

    hints = get_type_hints(DensityCell)
    assert hints["p_lower"] is float
    assert hints["p_upper"] is float


def test_forecast_density_cell_bounds_are_nullable() -> None:
    from typing import get_args, get_type_hints

    from breezy.strategy.ladder_ev.density_table import ForecastDensityCell

    hints = get_type_hints(ForecastDensityCell)
    assert type(None) in get_args(hints["p_lower"])
    assert type(None) in get_args(hints["p_upper"])
    assert float in get_args(hints["p_lower"])
    assert float in get_args(hints["p_upper"])


def test_forecast_density_key_uses_the_closed_outcome_alphabet() -> None:
    from breezy.strategy.ladder_ev.density_table import (
        FORECAST_OUTCOME_ALPHABET,
        ForecastDensityRecord,
        build_forecast_density_table,
        partition_check,
    )

    assert FORECAST_OUTCOME_ALPHABET == ("below", "contains", "above1", "above2", "above3+")
    records = [
        ForecastDensityRecord(
            station="MIA",
            season="JJA",
            hour_lst=14,
            forecast_bucket="txn_bucket_0",
            outcome=outcome,
        )
        for outcome, count in zip(
            FORECAST_OUTCOME_ALPHABET, (20, 30, 20, 15, 15), strict=True
        )
        for _ in range(count)
    ]
    table = build_forecast_density_table(records, n_min_cell=90)
    partition_check(table)
    key = ("MIA", "JJA", 14, "txn_bucket_0")
    cells = table[key]
    assert set(cells) == set(FORECAST_OUTCOME_ALPHABET)
    assert sum(cell.p_hat for cell in cells.values()) == pytest.approx(1.0, abs=1e-9)
    contains = cells["contains"]
    assert contains.n_cell == 100
    assert contains.k_r == 30
    assert contains.p_upper is not None
    assert contains.p_lower is not None
    assert contains.p_upper >= contains.p_lower
    assert (1.0 - contains.p_upper) <= (1.0 - contains.p_lower)


def test_forecast_density_unknown_outcome_is_refused() -> None:
    from breezy.strategy.ladder_ev.density_table import (
        ForecastDensityRecord,
        build_forecast_density_table,
    )

    with pytest.raises(ValueError, match="outcome"):
        build_forecast_density_table(
            [
                ForecastDensityRecord(
                    station="MIA",
                    season="JJA",
                    hour_lst=14,
                    forecast_bucket="txn_bucket_0",
                    outcome="above4",
                )
            ]
        )


def test_forecast_density_bounds_are_none_below_n_min_cell() -> None:
    from breezy.strategy.ladder_ev.density_table import (
        FORECAST_OUTCOME_ALPHABET,
        ForecastDensityRecord,
        build_forecast_density_table,
    )

    records = [
        ForecastDensityRecord(
            station="LAX",
            season="DJF",
            hour_lst=12,
            forecast_bucket="sparse",
            outcome=outcome,
        )
        for outcome in FORECAST_OUTCOME_ALPHABET
    ]
    table = build_forecast_density_table(records, n_min_cell=90)
    cell = table[("LAX", "DJF", 12, "sparse")]["contains"]
    assert cell.n_cell == 5
    assert cell.p_lower is None
    assert cell.p_upper is None


def test_load_forecast_density_table_hashes_artefact_bytes_not_a_src_constant(
    tmp_path: Path,
) -> None:
    import hashlib
    import json

    from breezy.strategy.ladder_ev.config import ForecastCorpusPinMismatchError
    from breezy.strategy.ladder_ev.density_table import (
        FORECAST_OUTCOME_ALPHABET,
        load_forecast_density_table,
    )

    payload = {
        "records": [
            {
                "station": "SFO",
                "season": "JJA",
                "hour_lst": 15,
                "forecast_bucket": "b0",
                "outcome": outcome,
            }
            for outcome, count in zip(
                FORECAST_OUTCOME_ALPHABET, (18, 22, 20, 20, 20), strict=True
            )
            for _ in range(count)
        ]
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    path = tmp_path / "forecast_density.json"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ForecastCorpusPinMismatchError):
        load_forecast_density_table(path, density_artefact_sha256="ab" * 32)
    table = load_forecast_density_table(path, density_artefact_sha256=digest)
    key = ("SFO", "JJA", 15, "b0")
    assert key in table
    assert table[key]["contains"].n_cell == 100
