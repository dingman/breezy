"""Partial-write safety and resumability for the IEM 1-min backfill CLI (WP-3).

Conventions follow ``tests/integration/test_archive_cache_roundtrip.py``: a
fake fetch, a frozen clock, a ``tmp_path`` cache root, and no network. An
interrupted station-year must leave NO payload the manifest claims and NO
manifest entry claiming coverage that was never written -- a later run must
re-fetch it rather than treat it as covered.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final, cast

import pytest

from breezy.persistence import archive_cache as archive_cache_module
from breezy.persistence.archive_cache import IEM_ASOS_1MIN_SOURCE, ArchiveCache

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CLI_PATH: Final[Path] = REPO_ROOT / "scripts/archive/iem_asos1min_backfill.py"
MANIFEST_NAME: Final[str] = "coverage.json"


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"breezy_script_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return _load_script(CLI_PATH)


class _Clock:
    def timestamp_ns(self) -> int:
        return 1_704_067_200_000_000_000


def _csv(station: str, year: int) -> bytes:
    head = "station,valid(UTC),tmpf,dwpf\n"
    rows = "".join(
        f"{station},{year}-01-01 00:{minute:02d},32.0,30.0\n" for minute in range(4)
    )
    return (head + rows).encode()


def _manifest(root: Path) -> dict[str, Any]:
    path = root / IEM_ASOS_1MIN_SOURCE / MANIFEST_NAME
    if not path.exists():
        return {"entries": {}}
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _payloads(root: Path) -> list[Path]:
    return sorted(root.rglob("*.csv"))


def test_a_fetch_that_fails_midway_leaves_no_payload_and_no_coverage_claim(
    cli: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "cache"
    attempts: list[str] = []

    def failing(request: Any) -> bytes:
        attempts.append(f"{request.station}-{request.window_start}")
        if request.station == "KSFO":
            raise ConnectionResetError("connection reset mid-body")
        return _csv(request.station, 2021)

    plan = cli.build_plan(stations=("KMIA", "KSFO"), first_year=2021, through_year=2021)
    report = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=failing, clock=_Clock()),
        plan=plan,
        progress=lambda line: None,
    )

    assert report.fetched == 1
    assert [(item.station, item.year) for item in report.failed] == [("KSFO", 2021)]

    entries = _manifest(root)["entries"]
    ksfo_key = cli.request_for(cli.StationYear("KSFO", 2021, "1min")).cache_key()
    kmia_key = cli.request_for(cli.StationYear("KMIA", 2021, "1min")).cache_key()
    assert ksfo_key not in entries, "the manifest claims coverage that was never fetched"
    assert kmia_key in entries
    assert [path.name for path in _payloads(root)] == [f"{kmia_key}.csv"]

    # A later run re-fetches the failed station-year and skips the covered one.
    healed: list[str] = []

    def healthy(request: Any) -> bytes:
        healed.append(request.station)
        return _csv(request.station, 2021)

    second = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=healthy, clock=_Clock()),
        plan=plan,
        progress=lambda line: None,
    )
    assert healed == ["KSFO"]
    assert second.fetched == 1
    assert second.skipped == 1
    assert ksfo_key in _manifest(root)["entries"]


def test_a_crash_between_the_payload_write_and_the_manifest_write_is_not_coverage(
    cli: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cache"
    real_atomic_write = archive_cache_module._atomic_write

    def crashing(path: Path, data: bytes) -> None:
        if path.name == MANIFEST_NAME:
            raise OSError("ENOSPC while committing the manifest")
        real_atomic_write(path, data)

    monkeypatch.setattr(archive_cache_module, "_atomic_write", crashing)

    plan = cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2021)
    report = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=lambda r: _csv(r.station, 2021), clock=_Clock()),
        plan=plan,
        progress=lambda line: None,
    )

    key = cli.request_for(plan[0]).cache_key()
    assert report.fetched == 0
    assert len(report.failed) == 1
    assert key not in _manifest(root)["entries"], (
        "a manifest entry survived a failed manifest commit"
    )

    monkeypatch.setattr(archive_cache_module, "_atomic_write", real_atomic_write)

    fetched: list[str] = []

    def refetch(request: Any) -> bytes:
        fetched.append(request.station)
        return _csv(request.station, 2021)

    cache = ArchiveCache(root=root, fetch=refetch, clock=_Clock())
    assert cache.missing(cli.request_for(plan[0])) is True
    second = cli.run_backfill(cache=cache, plan=plan, progress=lambda line: None)

    assert fetched == ["KMIA"], "the half-written station-year was treated as covered"
    assert second.fetched == 1
    body = cache.read(cli.request_for(plan[0]))
    assert body == _csv("KMIA", 2021)
    assert _manifest(root)["entries"][key]["sha256"] == hashlib.sha256(body).hexdigest()


def test_an_interrupt_mid_run_leaves_the_cache_consistent(
    cli: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "cache"

    def interrupting(request: Any) -> bytes:
        if request.station == "KSFO":
            raise KeyboardInterrupt
        return _csv(request.station, 2021)

    plan = cli.build_plan(
        stations=("KMIA", "KSFO", "KLAX"), first_year=2021, through_year=2021
    )
    with pytest.raises(KeyboardInterrupt):
        cli.run_backfill(
            cache=ArchiveCache(root=root, fetch=interrupting, clock=_Clock()),
            plan=plan,
            progress=lambda line: None,
        )

    entries = _manifest(root)["entries"]
    assert set(entries) == {cli.request_for(cli.StationYear("KMIA", 2021, "1min")).cache_key()}
    assert len(_payloads(root)) == 1

    # Every manifest entry is backed by a readable payload of the claimed digest.
    cache = ArchiveCache(root=root, fetch=lambda r: _csv(r.station, 2021), clock=_Clock())
    for item in plan:
        request = cli.request_for(item)
        if request.cache_key() in entries:
            assert hashlib.sha256(cache.read(request)).hexdigest() == (
                entries[request.cache_key()]["sha256"]
            )
        else:
            assert cache.missing(request) is True


def test_a_full_four_station_run_is_idempotent_and_then_dry_runs_clean(
    cli: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "cache"
    calls: list[tuple[str, int]] = []

    def fetch(request: Any) -> bytes:
        calls.append((request.station, request.window_start))
        return _csv(request.station, 2021)

    plan = cli.build_plan(first_year=2021, through_year=2022)
    assert len(plan) == 8

    first = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda line: None,
    )
    assert first.fetched == 8
    assert len(calls) == 8

    second = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda line: None,
    )
    assert len(calls) == 8
    assert second.skipped == 8

    dry = cli.run_backfill(
        cache=ArchiveCache(
            root=root,
            fetch=lambda r: (_ for _ in ()).throw(AssertionError("no fetch")),
            clock=_Clock(),
        ),
        plan=plan,
        progress=lambda line: None,
        dry_run=True,
    )
    assert {outcome.status for outcome in dry.outcomes} == {"SKIPPED"}
    assert "0 to fetch" in cli.render_summary(dry)
