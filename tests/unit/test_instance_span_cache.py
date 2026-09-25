"""Unit tests for `src/breezy/analysis/instance_span_cache.py` (RED first,
AUD-09b amendment Rev 2.1 Stage A, C6; tests A6, A7)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from breezy.analysis.instance_span_cache import (
    INSTANCE_SPANS_SCHEMA_VERSION,
    InstanceFileFingerprint,
    InstanceSpanCacheCorruptError,
    UnknownInstanceSpanCacheSchemaError,
    fingerprint_instance_files,
    lookup,
    read_instance_span_cache,
    write_instance_span_cache,
)
from breezy.analysis.replay_sufficiency import InstanceSpan

STATION = "SFO"
CLIMATE_DAY = "2026-09-01"


def _clean_span(*, instance_id: str = "instance-1", depth: float = 45.0) -> InstanceSpan:
    return InstanceSpan(
        instance_id=instance_id,
        verdict="CLEAN",
        depth_window_minutes=depth,
        quote_window_minutes=0.0,
        distinct_instruments=1,
        first_in_window_ns=1_000,
        last_in_window_ns=2_000,
    )


# ---------------------------------------------------------------------------
# A6: cache hit reuses spans; fingerprint mismatch recomputes (i.e. misses);
# an algo-version bump invalidates; LIVE/CORRUPT/EMPTY are never written;
# cold and warm runs over the same entries are byte-identical.
# ---------------------------------------------------------------------------


def test_a6_write_then_read_round_trips_a_clean_span(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    span = _clean_span()
    entries = {("instance-1", "fp-abc", 1): {(STATION, CLIMATE_DAY): span}}

    write_instance_span_cache(path, entries)
    cache = read_instance_span_cache(path)

    hit = lookup(cache, instance_id="instance-1", fingerprint="fp-abc", algo_version=1)
    assert hit is not None
    assert hit[(STATION, CLIMATE_DAY)] == span


def test_a6_a_fingerprint_mismatch_is_a_cache_miss(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    entries = {("instance-1", "fp-abc", 1): {(STATION, CLIMATE_DAY): _clean_span()}}
    write_instance_span_cache(path, entries)
    cache = read_instance_span_cache(path)

    miss = lookup(cache, instance_id="instance-1", fingerprint="fp-changed", algo_version=1)
    assert miss is None


def test_a6_an_algo_version_bump_invalidates_every_entry(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    entries = {("instance-1", "fp-abc", 1): {(STATION, CLIMATE_DAY): _clean_span()}}
    write_instance_span_cache(path, entries)
    cache = read_instance_span_cache(path)

    miss = lookup(cache, instance_id="instance-1", fingerprint="fp-abc", algo_version=2)
    assert miss is None


@pytest.mark.parametrize("verdict", ["LIVE", "CORRUPT", "EMPTY"])
def test_a6_a_non_clean_span_is_never_written(tmp_path: Path, verdict: str) -> None:
    path = tmp_path / "instance_spans.jsonl"
    non_clean = InstanceSpan(
        instance_id="instance-1",
        verdict=verdict,  # type: ignore[arg-type]
        depth_window_minutes=0.0,
        quote_window_minutes=0.0,
        distinct_instruments=0,
    )
    entries = {("instance-1", "fp-abc", 1): {(STATION, CLIMATE_DAY): non_clean}}

    with pytest.raises(InstanceSpanCacheCorruptError):
        write_instance_span_cache(path, entries)
    assert not path.exists()


def test_a6_cold_and_warm_runs_over_the_same_entries_are_byte_identical(tmp_path: Path) -> None:
    span_a = _clean_span(instance_id="instance-1", depth=45.0)
    span_b = _clean_span(instance_id="instance-2", depth=10.0)
    forward = {
        ("instance-1", "fp-a", 1): {(STATION, CLIMATE_DAY): span_a},
        ("instance-2", "fp-b", 1): {("LAX", CLIMATE_DAY): span_b},
    }
    reverse = {
        ("instance-2", "fp-b", 1): {("LAX", CLIMATE_DAY): span_b},
        ("instance-1", "fp-a", 1): {(STATION, CLIMATE_DAY): span_a},
    }
    path_cold = tmp_path / "cold.jsonl"
    path_warm = tmp_path / "warm.jsonl"

    write_instance_span_cache(path_cold, forward)
    write_instance_span_cache(path_warm, reverse)

    assert path_cold.read_bytes() == path_warm.read_bytes()


def test_a6_reader_refuses_an_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    path.write_text(
        '{"schema_version": 99, "instance_id": "x", "fingerprint": "y", '
        '"algo_version": 1, "spans": []}\n',
        encoding="utf-8",
    )

    with pytest.raises(UnknownInstanceSpanCacheSchemaError):
        read_instance_span_cache(path)
    assert INSTANCE_SPANS_SCHEMA_VERSION == 1  # the version this reader actually knows


# ---------------------------------------------------------------------------
# A7 (residual pin, DOMAIN 3): an edit that preserves both size and mtime is
# NOT detected -- a known, accepted gap, not an oversight.
# ---------------------------------------------------------------------------


def test_a7_an_edit_preserving_size_and_mtime_is_not_detected(tmp_path: Path) -> None:
    target = tmp_path / "a.feather"
    target.write_bytes(b"original-content!!!!")
    original_stat = target.stat()
    fingerprint_before = fingerprint_instance_files(
        [
            InstanceFileFingerprint(
                relpath="a.feather", size=original_stat.st_size, mtime_ns=original_stat.st_mtime_ns,
            )
        ]
    )

    # Same length as before, different bytes -- then the mtime is restored.
    tampered = b"tampered-content!!!!"
    assert len(tampered) == len(b"original-content!!!!")
    target.write_bytes(tampered)
    os.utime(target, ns=(original_stat.st_mtime_ns, original_stat.st_mtime_ns))
    tampered_stat = target.stat()

    fingerprint_after = fingerprint_instance_files(
        [
            InstanceFileFingerprint(
                relpath="a.feather", size=tampered_stat.st_size, mtime_ns=tampered_stat.st_mtime_ns,
            )
        ]
    )

    # KNOWN residual gap (AUD-09b amendment §9): size+mtime alone cannot
    # detect this edit. Pinned deliberately, not a bug to "fix" here.
    assert fingerprint_before == fingerprint_after


def test_fingerprint_instance_files_is_order_independent(tmp_path: Path) -> None:
    files = [
        InstanceFileFingerprint(relpath="b.feather", size=10, mtime_ns=200),
        InstanceFileFingerprint(relpath="a.feather", size=5, mtime_ns=100),
    ]

    assert fingerprint_instance_files(files) == fingerprint_instance_files(list(reversed(files)))


def test_fingerprint_instance_files_changes_when_a_file_changes() -> None:
    base = [InstanceFileFingerprint(relpath="a.feather", size=5, mtime_ns=100)]
    changed = [InstanceFileFingerprint(relpath="a.feather", size=6, mtime_ns=100)]

    assert fingerprint_instance_files(base) != fingerprint_instance_files(changed)
