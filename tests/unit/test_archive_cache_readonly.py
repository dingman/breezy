"""Read-only snapshot cache: one manifest parse per source, no write path."""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.persistence.archive_cache import (
    ArchiveCache,
    ArchiveCacheMissingPayloadError,
    ArchiveRequest,
    iem_mos_request,
)

SRC = "iem-mos"


class _Clock:
    def timestamp_ns(self) -> int:
        return 1_704_067_200_000_000_000


def _fixture_archive(root: Path, years: tuple[int, ...] = (2021, 2022, 2023)) -> dict[int, bytes]:
    bodies = {y: f"station,valid,tmpf\nKSFO,{y},50\n".encode() for y in years}
    writer = ArchiveCache(root, fetch=lambda r: bodies[_year(r)], clock=_Clock())
    for year in years:
        writer.get_or_fetch(iem_mos_request("KSFO", year, "NBS"))
    return bodies


def _year(request: ArchiveRequest) -> int:
    import datetime as dt

    return dt.datetime.fromtimestamp(request.window_start / 1e9, tz=dt.UTC).year


def _readonly(root: Path):  # type: ignore[no-untyped-def]
    from breezy.persistence.archive_cache_readonly import ReadOnlyArchiveCache

    return ReadOnlyArchiveCache(root)


def test_manifest_is_parsed_once_per_source_across_many_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture_archive(tmp_path)
    cache = _readonly(tmp_path)
    calls: list[Path] = []
    original = ArchiveCache._read_manifest

    def spy(self: ArchiveCache, path: Path):  # type: ignore[no-untyped-def]
        calls.append(path)
        return original(self, path)

    monkeypatch.setattr(ArchiveCache, "_read_manifest", spy)
    for _ in range(5):
        for year in (2021, 2022, 2023):
            cache.read(iem_mos_request("KSFO", year, "NBS"))
    assert cache.entries(SRC)
    assert not cache.missing(iem_mos_request("KSFO", 2021, "NBS"))
    assert len(calls) == 1


def test_reads_match_the_writer_cache_bytes_and_entries(tmp_path: Path) -> None:
    bodies = _fixture_archive(tmp_path)
    writer = ArchiveCache(tmp_path, fetch=lambda r: b"", clock=_Clock())
    cache = _readonly(tmp_path)
    for year, body in bodies.items():
        request = iem_mos_request("KSFO", year, "NBS")
        assert cache.read(request) == writer.read(request) == body
    assert cache.entries(SRC) == writer.entries(SRC)


def test_a_miss_still_raises_missing_payload(tmp_path: Path) -> None:
    _fixture_archive(tmp_path)
    with pytest.raises(ArchiveCacheMissingPayloadError):
        _readonly(tmp_path).read(iem_mos_request("KSFO", 1999, "NBS"))


def test_an_absent_source_reads_as_empty(tmp_path: Path) -> None:
    cache = _readonly(tmp_path / "none")
    assert cache.entries(SRC) == ()
    assert cache.missing(iem_mos_request("KSFO", 2021, "NBS"))


def test_write_methods_raise_and_leave_the_disk_untouched(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache_readonly import ReadOnlyCacheWriteError

    cache = _readonly(tmp_path)
    request = iem_mos_request("KSFO", 2021, "NBS")
    with pytest.raises(ReadOnlyCacheWriteError):
        cache.get_or_fetch(request)
    with pytest.raises(ReadOnlyCacheWriteError):
        cache._commit_miss(request, b"x\n")
    with pytest.raises(ReadOnlyCacheWriteError):
        cache._acquire_lock(tmp_path / SRC / "coverage.json.lock")
    assert list(tmp_path.iterdir()) == []


def test_snapshot_is_frozen_against_later_writer_commits(tmp_path: Path) -> None:
    _fixture_archive(tmp_path, years=(2021,))
    cache = _readonly(tmp_path)
    assert len(cache.entries(SRC)) == 1
    _fixture_archive(tmp_path, years=(2021, 2022))
    assert len(cache.entries(SRC)) == 1


def test_the_builder_factory_returns_the_read_only_cache(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache_readonly import ReadOnlyArchiveCache
    from scripts.analysis.multisource_blend_features_build import read_only_cache

    assert isinstance(read_only_cache(tmp_path), ReadOnlyArchiveCache)
