"""T1: 6-rung density partition identity (spec §3.2 / §13)."""

from __future__ import annotations

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
