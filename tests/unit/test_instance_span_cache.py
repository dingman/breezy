"""Unit tests for `src/breezy/analysis/instance_span_cache.py` (RED first,
AUD-09b amendment Rev 2.1 Stage A, C6; tests A6, A7)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from breezy.analysis.instance_span_cache import (
    INSTANCE_SPANS_SCHEMA_VERSION,
    CachedInstanceSpans,
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


def _probe(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    return hashlib.sha256(data[:4096]).hexdigest(), hashlib.sha256(data[-4096:]).hexdigest()


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


def _entry(
    *,
    instance_id: str = "instance-1",
    depth: float = 45.0,
    last_full_scan: str = "2026-09-27",
) -> CachedInstanceSpans:
    return CachedInstanceSpans(
        spans={(STATION, CLIMATE_DAY): _clean_span(instance_id=instance_id, depth=depth)},
        station_offsets={STATION: -8.0},
        last_full_scan=last_full_scan,
        files=(
            InstanceFileFingerprint(
                relpath="binary_option_0.feather",
                size=10,
                mtime_ns=20,
                st_ino=30,
                st_dev=40,
                head_digest="head",
                tail_digest="tail",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# A6: cache hit reuses spans; fingerprint mismatch recomputes (i.e. misses);
# an algo-version bump invalidates; LIVE/CORRUPT/EMPTY are never written;
# cold and warm runs over the same entries are byte-identical.
# ---------------------------------------------------------------------------


def test_a6_write_then_read_round_trips_a_clean_span(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    span = _clean_span()
    entries = {("instance-1", "fp-abc", 1, 1): _entry()}

    write_instance_span_cache(path, entries)
    cache = read_instance_span_cache(path)

    hit = lookup(
        cache,
        instance_id="instance-1",
        fingerprint="fp-abc",
        algo_version=1,
        preflight_classifier_version=1,
        station_offsets={STATION: -8.0},
    )
    assert hit is not None
    assert hit[(STATION, CLIMATE_DAY)] == span
    assert cache[("instance-1", "fp-abc", 1, 1)].last_full_scan == "2026-09-27"


def test_a6_a_fingerprint_mismatch_is_a_cache_miss(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    entries = {("instance-1", "fp-abc", 1, 1): _entry()}
    write_instance_span_cache(path, entries)
    cache = read_instance_span_cache(path)

    miss = lookup(
        cache,
        instance_id="instance-1",
        fingerprint="fp-changed",
        algo_version=1,
        preflight_classifier_version=1,
    )
    assert miss is None


def test_a6_an_algo_version_bump_invalidates_every_entry(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    entries = {("instance-1", "fp-abc", 1, 1): _entry()}
    write_instance_span_cache(path, entries)
    cache = read_instance_span_cache(path)

    miss = lookup(
        cache,
        instance_id="instance-1",
        fingerprint="fp-abc",
        algo_version=2,
        preflight_classifier_version=1,
    )
    assert miss is None


def test_a6_a_classifier_version_bump_invalidates_every_entry(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    entries = {("instance-1", "fp-abc", 1, 1): _entry()}
    write_instance_span_cache(path, entries)
    cache = read_instance_span_cache(path)

    miss = lookup(
        cache,
        instance_id="instance-1",
        fingerprint="fp-abc",
        algo_version=1,
        preflight_classifier_version=2,
    )
    assert miss is None


def test_a6_a_station_offset_change_invalidates_the_entry(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    entries = {("instance-1", "fp-abc", 1, 1): _entry()}
    write_instance_span_cache(path, entries)
    cache = read_instance_span_cache(path)

    miss = lookup(
        cache,
        instance_id="instance-1",
        fingerprint="fp-abc",
        algo_version=1,
        preflight_classifier_version=1,
        station_offsets={STATION: -7.0},
    )
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
    entries = {
        ("instance-1", "fp-abc", 1, 1): CachedInstanceSpans(
            spans={(STATION, CLIMATE_DAY): non_clean},
            station_offsets={STATION: -8.0},
            last_full_scan="2026-09-27",
        )
    }

    with pytest.raises(InstanceSpanCacheCorruptError):
        write_instance_span_cache(path, entries)
    assert not path.exists()


def test_a6_cold_and_warm_runs_over_the_same_entries_are_byte_identical(tmp_path: Path) -> None:
    span_b = _clean_span(instance_id="instance-2", depth=10.0)
    forward = {
        ("instance-1", "fp-a", 1, 1): _entry(instance_id="instance-1", depth=45.0),
        ("instance-2", "fp-b", 1, 1): CachedInstanceSpans(
            spans={("LAX", CLIMATE_DAY): span_b},
            station_offsets={"LAX": -8.0},
            last_full_scan="2026-09-27",
        ),
    }
    reverse = {
        ("instance-2", "fp-b", 1, 1): CachedInstanceSpans(
            spans={("LAX", CLIMATE_DAY): span_b},
            station_offsets={"LAX": -8.0},
            last_full_scan="2026-09-27",
        ),
        ("instance-1", "fp-a", 1, 1): _entry(instance_id="instance-1", depth=45.0),
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
        '"algo_version": 1, "preflight_classifier_version": 1, '
        '"station_offsets": {}, "last_full_scan": "2026-09-27", "spans": []}\n',
        encoding="utf-8",
    )

    with pytest.raises(UnknownInstanceSpanCacheSchemaError):
        read_instance_span_cache(path)
    assert INSTANCE_SPANS_SCHEMA_VERSION == 2  # the version this reader actually knows


# ---------------------------------------------------------------------------
# Code review MEDIUM: a malformed line must raise InstanceSpanCacheCorruptError
# naming the bad key -- never a bare KeyError/TypeError -- for a non-object
# line, a missing top-level key, and a wrong-type top-level key.
# ---------------------------------------------------------------------------


def test_read_refuses_a_non_object_line(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")

    with pytest.raises(InstanceSpanCacheCorruptError, match=str(path)):
        read_instance_span_cache(path)


def test_read_refuses_a_line_missing_a_required_top_level_key(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    path.write_text(
        '{"schema_version": 2, "fingerprint": "y", "algo_version": 1, '
        '"preflight_classifier_version": 1, "station_offsets": {}, '
        '"last_full_scan": "2026-09-27", "spans": []}\n',
        encoding="utf-8",
    )

    with pytest.raises(InstanceSpanCacheCorruptError, match="instance_id"):
        read_instance_span_cache(path)


def test_read_refuses_a_top_level_key_with_the_wrong_type(tmp_path: Path) -> None:
    path = tmp_path / "instance_spans.jsonl"
    path.write_text(
        '{"schema_version": 2, "instance_id": "x", "fingerprint": "y", '
        '"algo_version": "not-an-int", "preflight_classifier_version": 1, '
        '"station_offsets": {}, "last_full_scan": "2026-09-27", "spans": []}\n',
        encoding="utf-8",
    )

    with pytest.raises(InstanceSpanCacheCorruptError, match="algo_version"):
        read_instance_span_cache(path)


# ---------------------------------------------------------------------------
# A7/R3-A: head/tail digests and inode/dev are part of the cheap fingerprint.
# ---------------------------------------------------------------------------


def test_a7_an_edit_preserving_size_and_mtime_in_the_tail_is_detected(tmp_path: Path) -> None:
    target = tmp_path / "a.feather"
    target.write_bytes(b"original-content!!!!")
    original_stat = target.stat()
    original_head, original_tail = _probe(target)
    fingerprint_before = fingerprint_instance_files(
        [
            InstanceFileFingerprint(
                relpath="a.feather",
                size=original_stat.st_size,
                mtime_ns=original_stat.st_mtime_ns,
                st_ino=original_stat.st_ino,
                st_dev=original_stat.st_dev,
                head_digest=original_head,
                tail_digest=original_tail,
            )
        ]
    )

    # Same length as before, different bytes -- then the mtime is restored.
    tampered = b"tampered-content!!!!"
    assert len(tampered) == len(b"original-content!!!!")
    target.write_bytes(tampered)
    os.utime(target, ns=(original_stat.st_mtime_ns, original_stat.st_mtime_ns))
    tampered_stat = target.stat()
    tampered_head, tampered_tail = _probe(target)

    fingerprint_after = fingerprint_instance_files(
        [
            InstanceFileFingerprint(
                relpath="a.feather",
                size=tampered_stat.st_size,
                mtime_ns=tampered_stat.st_mtime_ns,
                st_ino=original_stat.st_ino,
                st_dev=original_stat.st_dev,
                head_digest=tampered_head,
                tail_digest=tampered_tail,
            )
        ]
    )

    assert fingerprint_before != fingerprint_after


def test_a7_inode_and_device_feed_the_fingerprint() -> None:
    base = [InstanceFileFingerprint(relpath="a.feather", size=5, mtime_ns=100, st_ino=1, st_dev=1)]
    changed = [
        InstanceFileFingerprint(relpath="a.feather", size=5, mtime_ns=100, st_ino=2, st_dev=1)
    ]

    assert fingerprint_instance_files(base) != fingerprint_instance_files(changed)


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
