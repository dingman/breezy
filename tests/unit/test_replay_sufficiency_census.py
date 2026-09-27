"""Unit tests for `scripts/analysis/replay_sufficiency_census.py` (RED first, AUD-09a).

Most of the script's real I/O wiring against a full feather/catalog capture
is exercised by the plan's "one real run", not by these tests. Two real,
minimal feather fixtures ARE built here (`TestLiveAndEmptyInstancesGetARow`)
because the completeness bug they cover -- a station-day whose only
instances are LIVE or EMPTY silently getting no row at all -- can only be
proven through the real `list_instance_ids`/`scan_instance`/`classify_instance`
wiring, not through the pure `build_census`/`classify_station_day` cores
alone. Everything else stays at the aggregation/contract level: one row per
`(station, climate_day)`, the H1 candidate-register contract (now backed by
the real `breezy.persistence.station_candidates`, merged via AUD-08b), and
byte-idempotent writes -- all pure or local-file I/O, all network-free by the
repo-wide socket block (`tests/conftest.py`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import AssetClass, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import replay_sufficiency_census as census_module
from replay_sufficiency_census import (
    CensusCompletenessError,
    _assert_census_is_complete,
    _candidate_rows_to_replay_sufficiency,
    _live_instance_registrations,
    _locked_cache,
    _locked_work_dir,
    _read_station_candidates,
    build_census,
    run_census,
)

from breezy.analysis.instance_span_cache import (
    SPAN_ALGO_VERSION,
    CachedInstanceSpans,
    append_instance_span_cache_entry,
    read_instance_span_cache,
    write_instance_span_cache,
)
from breezy.analysis.replay_sufficiency import (
    CANDIDATE_UNSUPPORTED_STATION,
    CORRUPT_ONLY,
    NO_CLEAN_INSTANCE,
    InstanceSpan,
    decision_window_ns,
)
from breezy.persistence.feather_preflight import PREFLIGHT_CLASSIFIER_VERSION
from breezy.persistence.station_candidates import (
    STATION_CANDIDATES_SCHEMA_VERSION,
    StationCandidate,
    UnknownStationCandidateSchemaError,
)

COMPUTED_DAY = "2026-09-24"
_VENUE = Venue("BREEZY_TEST")


class _FakeWindow:
    std_utc_offset_hours = -8.0


class _FakeRegistry:
    def __init__(self, offsets: dict[str, float] | None = None) -> None:
        self.offsets = offsets or {"SFO": -8.0, "LAX": -8.0, "MIA": -5.0, "NYC": -5.0}

    def pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(("polymarket_us", station) for station in sorted(self.offsets))

    def climate_day_window(self, _venue: str, station: str) -> _FakeWindow:
        return SimpleNamespace(std_utc_offset_hours=self.offsets[station])


def _span(verdict: str, depth: float = 0.0, instance_id: str = "instance-1") -> InstanceSpan:
    return InstanceSpan(
        instance_id=instance_id,
        verdict=verdict,  # type: ignore[arg-type]
        depth_window_minutes=depth,
        quote_window_minutes=0.0,
        distinct_instruments=1,
    )


def _cached_entry(*, instance_id: str, last_full_scan: str) -> CachedInstanceSpans:
    return CachedInstanceSpans(
        spans={("SFO", "2026-09-01"): _span("CLEAN", depth=45.0, instance_id=instance_id)},
        station_offsets={"SFO": -8.0},
        last_full_scan=last_full_scan,
    )


def _make_instance(root: Path, instance_id: str, payload: bytes | None = None) -> Path:
    instance_dir = root / "live" / instance_id
    instance_dir.mkdir(parents=True)
    (instance_dir / "binary_option_0.feather").write_bytes(
        payload or f"payload-{instance_id}".encode()
    )
    return instance_dir


def _clean_entry_for(instance_dir: Path, *, station: str, day: str, depth: float = 45.0) -> tuple:
    instance_id = instance_dir.name
    files = census_module._instance_file_fingerprints(instance_dir)
    fingerprint = census_module._instance_fingerprint(files)
    entry = CachedInstanceSpans(
        spans={(station, day): _span("CLEAN", depth=depth, instance_id=instance_id)},
        station_offsets={station: -8.0 if station in {"SFO", "LAX"} else -5.0},
        last_full_scan="2026-09-27",
        files=files,
    )
    return (instance_id, fingerprint, SPAN_ALGO_VERSION, PREFLIGHT_CLASSIFIER_VERSION), entry


def _patch_fake_census(
    monkeypatch: pytest.MonkeyPatch,
    *,
    instance_ids: list[str],
    verdicts: dict[str, str],
    clean_meta: dict[str, tuple[str, str, float]],
    converted: list[str] | None = None,
    scanned: list[str] | None = None,
    registry: _FakeRegistry | None = None,
) -> None:
    converted = converted if converted is not None else []
    scanned = scanned if scanned is not None else []
    fake_registry = registry or _FakeRegistry()
    window_bounds: dict[tuple[str, str], tuple[int, int]] = {}
    monkeypatch.setattr(census_module, "default_registry", lambda: fake_registry)
    monkeypatch.setattr(
        census_module, "list_instance_ids", lambda _root, _subdir: tuple(instance_ids)
    )
    monkeypatch.setattr(
        census_module,
        "scan_instance",
        lambda _root, instance_id, _subdir: scanned.append(instance_id) or instance_id,
    )
    monkeypatch.setattr(
        census_module,
        "classify_instance",
        lambda report, *, now_ns: verdicts[str(report)],
    )

    def _discover(**kwargs):
        instance_id = kwargs["clean_ids"][0]
        converted.append(instance_id)
        station, day, depth = clean_meta[instance_id]
        bounds = census_module._window_bounds_for(
            station,
            day,
            registry=fake_registry,
            window_bounds=window_bounds,
        )
        return (
            {(station, day): [_span("CLEAN", depth=depth, instance_id=instance_id)]},
            {(station, day)},
            {(station, day): bounds},
        )

    monkeypatch.setattr(census_module, "_discover_clean_spans", _discover)
    monkeypatch.setattr(
        census_module,
        "_corrupt_instance_station_days",
        lambda quote_catalog, subdirectory, corrupt_ids: {
            (
                clean_meta.get(instance_id, ("MIA", "2026-09-03", 0.0))[0],
                dt.date.fromisoformat(clean_meta.get(instance_id, ("MIA", "2026-09-03", 0.0))[1]),
            )
            for instance_id in corrupt_ids
        },
    )
    monkeypatch.setattr(
        census_module,
        "_live_instance_registrations",
        lambda quote_catalog, subdirectory, live_ids: {
            instance_id: (
                {
                    (
                        clean_meta.get(instance_id, ("NYC", "2026-09-04", 0.0))[0],
                        dt.date.fromisoformat(
                            clean_meta.get(instance_id, ("NYC", "2026-09-04", 0.0))[1]
                        ),
                    )
                },
                0,
            )
            for instance_id in live_ids
        },
    )
    monkeypatch.setattr(census_module, "_read_station_candidates", lambda path: ())


def _seed_cached_instance(
    tmp_path: Path, *, instance_id: str = "instance-1", last_full_scan: str = "2026-09-27"
) -> tuple[Path, Path]:
    instance_dir = tmp_path / "live" / instance_id
    instance_dir.mkdir(parents=True)
    (instance_dir / "binary_option_0.feather").write_bytes(b"not-real-arrow-but-fingerprinted")
    files = census_module._instance_file_fingerprints(instance_dir)
    fingerprint = census_module._instance_fingerprint(files)
    cache_path = tmp_path / "instance_spans.v2.jsonl"
    entry = _cached_entry(instance_id=instance_id, last_full_scan=last_full_scan)
    entry = CachedInstanceSpans(
        spans=dict(entry.spans),
        station_offsets=dict(entry.station_offsets),
        last_full_scan=entry.last_full_scan,
        files=files,
    )
    append_instance_span_cache_entry(
        cache_path,
        (instance_id, fingerprint, SPAN_ALGO_VERSION, PREFLIGHT_CLASSIFIER_VERSION),
        entry,
    )
    return instance_dir, cache_path


def test_build_census_emits_one_row_per_station_climate_day() -> None:
    spans = {
        ("SFO", "2026-09-01"): [_span("CLEAN", depth=45.0)],
        ("LAX", "2026-09-01"): [_span("CLEAN", depth=10.0)],
    }

    rows = build_census(station_day_spans=spans, computed_day=COMPUTED_DAY)

    keys = {(row.station, row.climate_day) for row in rows}
    assert keys == {("SFO", "2026-09-01"), ("LAX", "2026-09-01")}


def test_build_census_marks_a_corrupt_only_day_corrupt_only_and_never_selected() -> None:
    spans = {("MIA", "2026-08-20"): [_span("CORRUPT")]}

    rows = build_census(station_day_spans=spans, computed_day=COMPUTED_DAY)

    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "INSUFFICIENT"
    assert row.reason == CORRUPT_ONLY
    assert row.winner_instance_id is None


def test_build_census_includes_candidate_rows_alongside_tape_rows() -> None:
    spans = {("SFO", "2026-09-01"): [_span("CLEAN", depth=45.0)]}
    candidate_rows = _candidate_rows_to_replay_sufficiency(
        [_fake_candidate(venue="polymarket_us", city_token="nyc", last_seen_day="2026-09-20")],
        computed_day=COMPUTED_DAY,
    )

    rows = build_census(
        station_day_spans=spans, candidate_rows=candidate_rows, computed_day=COMPUTED_DAY
    )

    assert len(rows) == 2
    candidate_row = next(row for row in rows if row.reason == CANDIDATE_UNSUPPORTED_STATION)
    assert candidate_row.verdict == "INSUFFICIENT"
    assert candidate_row.winner_instance_id is None
    assert candidate_row.climate_day == "2026-09-20"


def _fake_candidate(*, venue: str, city_token: str, last_seen_day: str) -> StationCandidate:
    return StationCandidate(
        schema_version=STATION_CANDIDATES_SCHEMA_VERSION,
        venue=venue,
        city_token=city_token,
        origin="SIGHTING",
        first_seen_day=last_seen_day,
        last_seen_day=last_seen_day,
        distinct_slugs=1,
        distinct_climate_days=1,
        sufficiency="NO_SETTLEMENT_TRUTH",
    )


def test_read_station_candidates_missing_file_warns_and_yields_empty_set(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "station_candidates.jsonl"

    result = _read_station_candidates(missing)

    assert result == ()
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert str(missing) in captured.err


def test_read_station_candidates_parses_one_line_per_candidate(tmp_path: Path) -> None:
    path = tmp_path / "station_candidates.jsonl"

    candidate = _fake_candidate(venue="polymarket_us", city_token="nyc", last_seen_day="2026-09-20")
    path.write_text(json.dumps(asdict(candidate)) + "\n", encoding="utf-8")

    result = _read_station_candidates(path)

    assert len(result) == 1
    assert result[0].venue == "polymarket_us"
    assert result[0].city_token == "nyc"


def test_read_station_candidates_refuses_an_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "station_candidates.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "venue": "polymarket_us",
                "city_token": "nyc",
                "origin": "SIGHTING",
                "first_seen_day": "2026-09-20",
                "last_seen_day": "2026-09-20",
                "distinct_slugs": 1,
                "distinct_climate_days": 1,
                "sufficiency": "NO_SETTLEMENT_TRUTH",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(UnknownStationCandidateSchemaError) as excinfo:
        _read_station_candidates(path)

    assert str(path) in str(excinfo.value)


def test_candidate_rows_excludes_a_key_the_tape_already_discovered() -> None:
    """AUD-09b dup fix (2026-09-25): a candidate colliding with a key the
    tape-derived census already classified must not also emit a
    `CANDIDATE_UNSUPPORTED_STATION` placeholder for that same key -- that
    collision is exactly what produced the production duplicate
    `('NYC', '2026-09-25')`."""
    candidate = _fake_candidate(venue="polymarket_us", city_token="nyc", last_seen_day="2026-09-25")

    rows = _candidate_rows_to_replay_sufficiency(
        [candidate],
        computed_day="2026-09-25",
        exclude_keys=frozenset({("NYC", "2026-09-25")}),
    )

    assert rows == ()


def test_candidate_rows_keeps_a_key_the_tape_never_discovered() -> None:
    candidate = _fake_candidate(venue="polymarket_us", city_token="nyc", last_seen_day="2026-09-20")

    rows = _candidate_rows_to_replay_sufficiency(
        [candidate],
        computed_day="2026-09-24",
        exclude_keys=frozenset({("NYC", "2026-09-25")}),
    )

    assert len(rows) == 1
    assert rows[0].reason == CANDIDATE_UNSUPPORTED_STATION


def test_candidate_rows_never_enter_the_replay_queue() -> None:
    """H1: a candidate is recorded, never queued -- it always carries the
    closed CANDIDATE_UNSUPPORTED_STATION reason and no winner instance."""
    candidate = _fake_candidate(venue="polymarket_us", city_token="nyc", last_seen_day="2026-09-20")

    rows = _candidate_rows_to_replay_sufficiency([candidate], computed_day=COMPUTED_DAY)

    assert len(rows) == 1
    assert rows[0].reason == CANDIDATE_UNSUPPORTED_STATION
    assert rows[0].verdict == "INSUFFICIENT"
    assert rows[0].winner_instance_id is None


class TestIncrementalInstanceSpanCache:
    def test_e1_cold_warm_and_cache_disabled_outputs_match(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        ids = ["clean-a", "clean-b", "corrupt-a", "live-a"]
        meta = {
            "clean-a": ("SFO", "2026-09-01", 45.0),
            "clean-b": ("LAX", "2026-09-02", 10.0),
            "corrupt-a": ("MIA", "2026-09-03", 0.0),
            "live-a": ("NYC", "2026-09-04", 0.0),
        }
        for instance_id in ids:
            _make_instance(tmp_path, instance_id)
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={
                "clean-a": "CLEAN",
                "clean-b": "CLEAN",
                "corrupt-a": "CORRUPT",
                "live-a": "LIVE",
            },
            clean_meta=meta,
        )

        cold = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        warm = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        disabled = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
        )

        assert cold == warm == disabled
        outputs: list[bytes] = []
        for idx, rows in enumerate((cold, warm, disabled)):
            output = tmp_path / f"out-{idx}.jsonl"
            census_module.write_replay_sufficiency(output, rows)
            outputs.append(output.read_bytes())
        assert outputs[0] == outputs[1] == outputs[2]

    def test_e2_one_clean_file_change_reconverts_only_that_instance(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        ids = ["clean-a", "clean-b"]
        meta = {
            "clean-a": ("SFO", "2026-09-01", 45.0),
            "clean-b": ("LAX", "2026-09-02", 10.0),
        }
        for instance_id in ids:
            _make_instance(tmp_path, instance_id)
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        converted: list[str] = []
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={"clean-a": "CLEAN", "clean-b": "CLEAN"},
            clean_meta=meta,
            converted=converted,
        )
        run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        converted.clear()
        (tmp_path / "live" / "clean-b" / "binary_option_0.feather").write_bytes(b"changed")
        meta["clean-b"] = ("LAX", "2026-09-02", 25.0)

        warm = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        warm_converted = list(converted)
        converted.clear()
        full = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
        )

        assert warm_converted == ["clean-b"]
        assert converted == ["clean-a", "clean-b"]
        assert warm == full
        assert next(row for row in warm if row.station == "LAX").depth_window_minutes == 25.0

    def test_e3_station_offset_change_only_reconverts_instances_with_that_station(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        ids = ["clean-sfo", "clean-lax"]
        meta = {
            "clean-sfo": ("SFO", "2026-09-01", 45.0),
            "clean-lax": ("LAX", "2026-09-02", 10.0),
        }
        for instance_id in ids:
            _make_instance(tmp_path, instance_id)
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        converted: list[str] = []
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={"clean-sfo": "CLEAN", "clean-lax": "CLEAN"},
            clean_meta=meta,
            converted=converted,
        )
        run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )

        converted.clear()
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={"clean-sfo": "CLEAN", "clean-lax": "CLEAN"},
            clean_meta=meta,
            converted=converted,
            registry=_FakeRegistry({"SFO": -7.0, "LAX": -8.0, "MIA": -5.0, "NYC": -5.0}),
        )
        run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        assert converted == ["clean-sfo"]

        converted.clear()
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={"clean-sfo": "CLEAN", "clean-lax": "CLEAN"},
            clean_meta=meta,
            converted=converted,
            registry=_FakeRegistry(
                {"SFO": -7.0, "LAX": -8.0, "MIA": -5.0, "NYC": -5.0, "DEN": -7.0}
            ),
        )
        run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        assert converted == []

    def test_warm_clean_hit_skips_scan_and_conversion(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _instance_dir, cache_path = _seed_cached_instance(tmp_path)
        monkeypatch.setattr(census_module, "default_registry", lambda: _FakeRegistry())
        monkeypatch.setattr(
            census_module,
            "scan_instance",
            lambda *args, **kwargs: pytest.fail("warm cache hit must not scan"),
        )
        monkeypatch.setattr(
            census_module,
            "_discover_clean_spans",
            lambda **kwargs: pytest.fail("warm cache hit must not convert"),
        )
        monkeypatch.setattr(census_module, "_read_station_candidates", lambda path: ())

        rows = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )

        assert [(row.station, row.climate_day) for row in rows] == [("SFO", "2026-09-01")]

    def test_due_clean_hit_rescans_without_reconversion(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _instance_dir, cache_path = _seed_cached_instance(tmp_path, last_full_scan="2026-09-19")
        scanned: list[str] = []
        monkeypatch.setattr(census_module, "default_registry", lambda: _FakeRegistry())
        monkeypatch.setattr(
            census_module,
            "scan_instance",
            lambda _root, instance_id, _subdir: scanned.append(instance_id) or object(),
        )
        monkeypatch.setattr(census_module, "classify_instance", lambda _report, *, now_ns: "CLEAN")
        monkeypatch.setattr(
            census_module,
            "_discover_clean_spans",
            lambda **kwargs: pytest.fail("due unchanged CLEAN entry must not reconvert"),
        )
        monkeypatch.setattr(census_module, "_read_station_candidates", lambda path: ())

        rows = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )

        assert scanned == ["instance-1"]
        assert [(row.station, row.climate_day) for row in rows] == [("SFO", "2026-09-01")]

    def test_cache_sidecar_lock_fails_loudly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        monkeypatch.setattr(
            census_module.fcntl,
            "flock",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(BlockingIOError()),
        )

        with pytest.raises(RuntimeError, match="already held"), _locked_cache(cache_path):
            pass

    def test_work_sweep_skips_lockless_and_young_dirs(self, tmp_path: Path) -> None:
        parent = tmp_path / "work-parent"
        lockless = parent / "replay-sufficiency-census-lockless"
        young = parent / "replay-sufficiency-census-young"
        lockless.mkdir(parents=True)
        young.mkdir(parents=True)
        (young / ".lock").touch()

        with _locked_work_dir(parent) as work_dir:
            assert work_dir.exists()
            assert (work_dir / ".lock").exists()

        assert not work_dir.exists()
        assert lockless.exists()
        assert young.exists()

    def test_i4_old_locked_workdir_survives_but_stale_unlocked_dir_is_removed(
        self, tmp_path: Path
    ) -> None:
        parent = tmp_path / "work-parent"
        locked = parent / "replay-sufficiency-census-locked"
        stale = parent / "replay-sufficiency-census-stale"
        locked.mkdir(parents=True)
        stale.mkdir(parents=True)
        (locked / ".lock").touch()
        (stale / ".lock").touch()
        old = time.time() - 600
        os.utime(locked, (old, old))
        os.utime(stale, (old, old))

        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import fcntl, pathlib, sys, time;"
                    "p=pathlib.Path(sys.argv[1]);"
                    "h=p.open('a+');"
                    "fcntl.flock(h.fileno(), fcntl.LOCK_EX);"
                    "print('ready', flush=True);"
                    "time.sleep(30)"
                ),
                str(locked / ".lock"),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "ready"
            with _locked_work_dir(parent):
                pass
        finally:
            holder.terminate()
            holder.wait(timeout=5)

        assert locked.exists()
        assert not stale.exists()

    def test_migration_is_atomically_persisted_before_instance_loop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        ids = ["migrated-a", "cold-a", "migrated-b", "cold-b"]
        meta = {
            "migrated-a": ("SFO", "2026-09-01", 45.0),
            "cold-a": ("LAX", "2026-09-02", 10.0),
            "migrated-b": ("SFO", "2026-09-03", 30.0),
            "cold-b": ("LAX", "2026-09-04", 20.0),
        }
        for instance_id in ids:
            _make_instance(tmp_path, instance_id)
        legacy_path = tmp_path / "instance_spans.jsonl"
        registry = _FakeRegistry()
        offset_fp = census_module._registry_offset_table_fingerprint(registry)
        with legacy_path.open("w", encoding="utf-8") as handle:
            for instance_id in ("migrated-a", "migrated-b"):
                instance_dir = tmp_path / "live" / instance_id
                fingerprint = census_module._legacy_instance_fingerprint(
                    instance_dir,
                    offset_table_fingerprint=offset_fp,
                )
                station, day, depth = meta[instance_id]
                handle.write(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "instance_id": instance_id,
                            "fingerprint": fingerprint,
                            "algo_version": SPAN_ALGO_VERSION,
                            "spans": [
                                {
                                    "station": station,
                                    "climate_day": day,
                                    "depth_window_minutes": depth,
                                    "quote_window_minutes": 0.0,
                                    "distinct_instruments": 1,
                                    "first_in_window_ns": None,
                                    "last_in_window_ns": None,
                                }
                            ],
                        }
                    )
                    + "\n"
                )
        converted: list[str] = []
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={instance_id: "CLEAN" for instance_id in ids},
            clean_meta=meta,
            converted=converted,
            registry=registry,
        )
        original_discover = census_module._discover_clean_spans

        def _fail_on_second_cold(**kwargs):
            if kwargs["clean_ids"][0] == "cold-b":
                raise RuntimeError("boom after first checkpoint")
            return original_discover(**kwargs)

        monkeypatch.setattr(census_module, "_discover_clean_spans", _fail_on_second_cold)
        cache_path = tmp_path / "instance_spans.v2.jsonl"

        with pytest.raises(RuntimeError, match="boom"):
            run_census(
                catalog_root=tmp_path,
                subdirectory="live",
                work_root=tmp_path / "work",
                station_candidates_path=tmp_path / "station_candidates.jsonl",
                computed_day="2026-09-27",
                now_ns=1,
                instance_spans_cache_path=cache_path,
            )

        converted.clear()
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={instance_id: "CLEAN" for instance_id in ids},
            clean_meta=meta,
            converted=converted,
            registry=registry,
        )
        run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )

        assert converted == ["cold-b"]

    def test_e5_checkpoint_resume_converts_only_the_remainder(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        ids = ["clean-a", "clean-b", "clean-c"]
        meta = {
            "clean-a": ("SFO", "2026-09-01", 45.0),
            "clean-b": ("LAX", "2026-09-02", 10.0),
            "clean-c": ("SFO", "2026-09-03", 30.0),
        }
        for instance_id in ids:
            _make_instance(tmp_path, instance_id)
        converted: list[str] = []
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={instance_id: "CLEAN" for instance_id in ids},
            clean_meta=meta,
            converted=converted,
        )
        original_discover = census_module._discover_clean_spans

        def _raise_on_second(**kwargs):
            if kwargs["clean_ids"][0] == "clean-b":
                raise RuntimeError("converter failed")
            return original_discover(**kwargs)

        monkeypatch.setattr(census_module, "_discover_clean_spans", _raise_on_second)
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        with pytest.raises(RuntimeError, match="converter failed"):
            run_census(
                catalog_root=tmp_path,
                subdirectory="live",
                work_root=tmp_path / "work",
                station_candidates_path=tmp_path / "station_candidates.jsonl",
                computed_day="2026-09-27",
                now_ns=1,
                instance_spans_cache_path=cache_path,
            )
        assert len(read_instance_span_cache(cache_path)) == 1

        converted.clear()
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={instance_id: "CLEAN" for instance_id in ids},
            clean_meta=meta,
            converted=converted,
        )
        run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        assert converted == ["clean-b", "clean-c"]

    def test_e6_sigterm_cleans_workdir_and_keeps_completed_checkpoints(
        self,
        tmp_path: Path,
    ) -> None:
        marker = tmp_path / "ready"
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        work_parent = tmp_path / "work"
        code = f"""
import pathlib
import select
import sys
from types import SimpleNamespace

repo = pathlib.Path({str(REPO_ROOT)!r})
sys.path.insert(0, str(repo / "scripts/analysis"))

import replay_sufficiency_census as c
from breezy.analysis.replay_sufficiency import InstanceSpan

root = pathlib.Path({str(tmp_path)!r})
marker = pathlib.Path({str(marker)!r})


class _Registry:
    def pairs(self):
        return (("polymarket_us", "SFO"),)

    def climate_day_window(self, _venue, _station):
        return SimpleNamespace(std_utc_offset_hours=-8.0)


registry = _Registry()
window_bounds = {{}}
c.default_registry = lambda: registry
c.list_instance_ids = lambda _root, _subdir: ("done", "blocked")
c.scan_instance = lambda _root, instance_id, _subdir: instance_id
c.classify_instance = lambda report, *, now_ns: "CLEAN"
c._read_station_candidates = lambda path: ()
c._corrupt_instance_station_days = lambda quote_catalog, subdirectory, corrupt_ids: set()
c._live_instance_registrations = lambda quote_catalog, subdirectory, live_ids: {{}}


def _discover(**kwargs):
    instance_id = kwargs["clean_ids"][0]
    if instance_id == "blocked":
        marker.write_text("ready", encoding="utf-8")
        while not c._TERMINATE_REQUESTED:
            select.select([], [], [], 0.05)
        raise SystemExit(143)
    span = InstanceSpan(
        instance_id=instance_id,
        verdict="CLEAN",
        depth_window_minutes=45.0,
        quote_window_minutes=0.0,
        distinct_instruments=1,
    )
    return (
        {{("SFO", "2026-09-01"): [span]}},
        {{("SFO", "2026-09-01")}},
        {{
            ("SFO", "2026-09-01"): c._window_bounds_for(
                "SFO",
                "2026-09-01",
                registry=registry,
                window_bounds=window_bounds,
            )
        }},
    )


c._discover_clean_spans = _discover
for instance_id in ("done", "blocked"):
    instance_dir = root / "live" / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / "binary_option_0.feather").write_bytes(instance_id.encode())

raise SystemExit(
    c.main([
        "--catalog-root", str(root),
        "--subdirectory", "live",
        "--output", str(root / "out.jsonl"),
        "--station-candidates", str(root / "station_candidates.jsonl"),
        "--instance-spans-cache", {str(cache_path)!r},
        "--work-parent", {str(work_parent)!r},
    ])
)
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{REPO_ROOT / 'src'}:{env.get('PYTHONPATH', '')}"
        process = subprocess.Popen([sys.executable, "-c", code], env=env)
        deadline = time.monotonic() + 10
        try:
            while not marker.exists():
                if time.monotonic() > deadline:
                    raise AssertionError("child did not reach blocking converter within 10s")
                try:
                    process.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    continue
                raise AssertionError(f"child exited before marker: rc={process.returncode}")
            process.send_signal(signal.SIGTERM)
            returncode = process.wait(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

        assert returncode != 0
        assert not list(work_parent.glob("replay-sufficiency-census-*"))
        entries = read_instance_span_cache(cache_path)
        assert [key[0] for key in entries] == ["done"]

    @pytest.mark.parametrize("mode", ["failed", "empty"])
    def test_i7_failed_or_empty_listing_never_prunes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mode: str,
    ) -> None:
        instance_dir = _make_instance(tmp_path, "clean-a")
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        key, entry = _clean_entry_for(instance_dir, station="SFO", day="2026-09-01")
        write_instance_span_cache(cache_path, {key: entry})
        if mode == "failed":
            monkeypatch.setattr(
                census_module,
                "list_instance_ids",
                lambda _root, _subdir: (_ for _ in ()).throw(census_module.PreflightError("x")),
            )
        else:
            monkeypatch.setattr(census_module, "list_instance_ids", lambda _root, _subdir: ())
        monkeypatch.setattr(census_module, "default_registry", lambda: _FakeRegistry())
        monkeypatch.setattr(census_module, "_read_station_candidates", lambda path: ())
        monkeypatch.setattr(
            census_module,
            "_corrupt_instance_station_days",
            lambda quote_catalog, subdirectory, corrupt_ids: set(),
        )
        monkeypatch.setattr(
            census_module,
            "_live_instance_registrations",
            lambda quote_catalog, subdirectory, live_ids: {},
        )

        run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )

        assert read_instance_span_cache(cache_path) == {key: entry}

    def test_r3b_main_exits_nonzero_when_sidecar_lock_is_held(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        lock_path = tmp_path / "instance_spans.v2.jsonl.lock"
        lock_path.touch()
        holder_code = (
            "import fcntl, pathlib, sys, time;"
            "h=pathlib.Path(sys.argv[1]).open('a+');"
            "fcntl.flock(h.fileno(), fcntl.LOCK_EX);"
            "print('ready', flush=True);"
            "time.sleep(30)"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", holder_code, str(lock_path)],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "ready"
            env = dict(os.environ)
            env["PYTHONPATH"] = f"{REPO_ROOT / 'src'}:{env.get('PYTHONPATH', '')}"
            code = (
                "import sys;"
                f"sys.path.insert(0, {str(REPO_ROOT / 'scripts/analysis')!r});"
                "import replay_sufficiency_census as c;"
                "raise SystemExit(c.main(sys.argv[1:]))"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    code,
                    "--catalog-root",
                    str(tmp_path),
                    "--subdirectory",
                    "live",
                    "--output",
                    str(tmp_path / "out.jsonl"),
                    "--station-candidates",
                    str(tmp_path / "station_candidates.jsonl"),
                    "--instance-spans-cache",
                    str(cache_path),
                    "--work-parent",
                    str(tmp_path / "work"),
                ],
                capture_output=True,
                check=False,
                env=env,
                text=True,
            )
        finally:
            holder.terminate()
            holder.wait(timeout=5)

        assert result.returncode != 0
        assert "instance span cache lock is already held" in result.stderr

    def test_e7_tail_appended_between_scan_and_cache_write_forces_corrupt_rescan(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        instance_id = "clean-a"
        meta = {instance_id: ("SFO", "2026-09-01", 45.0)}
        instance_dir = _make_instance(tmp_path, instance_id)
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        _patch_fake_census(
            monkeypatch,
            instance_ids=[instance_id],
            verdicts={instance_id: "CLEAN"},
            clean_meta=meta,
        )
        original_discover = census_module._discover_clean_spans

        def _append_tail_before_cache_write(**kwargs):
            (instance_dir / "binary_option_0.feather").write_bytes(b"changed-tail")
            return original_discover(**kwargs)

        monkeypatch.setattr(census_module, "_discover_clean_spans", _append_tail_before_cache_write)
        run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        _patch_fake_census(
            monkeypatch,
            instance_ids=[instance_id],
            verdicts={instance_id: "CORRUPT"},
            clean_meta=meta,
        )

        rows = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )

        assert rows[0].reason == CORRUPT_ONLY

    def test_e9_staggered_rescan_bound_and_due_clean_reuses_cached_spans(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        count = 21
        ids = [f"clean-{idx:02d}" for idx in range(count)]
        meta = {
            instance_id: ("SFO", f"2026-09-{idx + 1:02d}", 45.0)
            for idx, instance_id in enumerate(ids)
        }
        seed_day = dt.date(2026, 9, 27)
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        entries = {}
        for instance_id in ids:
            instance_dir = _make_instance(tmp_path, instance_id)
            key, entry = _clean_entry_for(
                instance_dir,
                station=meta[instance_id][0],
                day=meta[instance_id][1],
            )
            entries[key] = CachedInstanceSpans(
                spans=entry.spans,
                station_offsets=entry.station_offsets,
                last_full_scan=census_module.staggered_last_full_scan(
                    instance_id,
                    seed_day.isoformat(),
                ),
                files=entry.files,
            )
        write_instance_span_cache(cache_path, entries)
        scanned: list[str] = []
        converted: list[str] = []
        _patch_fake_census(
            monkeypatch,
            instance_ids=ids,
            verdicts={instance_id: "CLEAN" for instance_id in ids},
            clean_meta=meta,
            scanned=scanned,
            converted=converted,
        )

        due_day_by_id = {
            instance_id: seed_day
            + dt.timedelta(
                days=7
                - (
                    int.from_bytes(
                        hashlib.sha256(instance_id.encode("utf-8")).digest()[:2],
                        "big",
                    )
                    % 7
                )
            )
            for instance_id in ids
        }
        rescanned_by_day: dict[str, list[str]] = {}
        for offset in range(1, 8):
            computed_day = (seed_day + dt.timedelta(days=offset)).isoformat()
            before = len(scanned)
            run_census(
                catalog_root=tmp_path,
                subdirectory="live",
                work_root=tmp_path / "work",
                station_candidates_path=tmp_path / "station_candidates.jsonl",
                computed_day=computed_day,
                now_ns=1,
                instance_spans_cache_path=cache_path,
            )
            rescanned = scanned[before:]
            expected = [
                instance_id
                for instance_id in ids
                if due_day_by_id[instance_id].isoformat() == computed_day
            ]
            assert rescanned == expected
            rescanned_by_day[computed_day] = rescanned

        assert sorted(scanned) == sorted(ids)
        assert len(scanned) == count
        assert all(
            due_day_by_id[instance_id].isoformat() == day
            for day, rescanned in rescanned_by_day.items()
            for instance_id in rescanned
        )
        assert converted == []
        reread = read_instance_span_cache(cache_path)
        assert all(
            (dt.date(2026, 10, 4) - dt.date.fromisoformat(entry.last_full_scan)).days < 7
            for entry in reread.values()
        )

    def test_e10_middle_edit_preserving_stat_and_head_tail_is_clean_until_due(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        instance_id = "clean-a"
        payload = b"h" * 4096 + b"middle-A" + b"t" * 4096
        instance_dir = _make_instance(tmp_path, instance_id, payload=payload)
        target = instance_dir / "binary_option_0.feather"
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        key, entry = _clean_entry_for(instance_dir, station="SFO", day="2026-09-01")
        write_instance_span_cache(cache_path, {key: entry})
        stat = target.stat()
        target.write_bytes(b"h" * 4096 + b"middle-B" + b"t" * 4096)
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        scanned: list[str] = []
        _patch_fake_census(
            monkeypatch,
            instance_ids=[instance_id],
            verdicts={instance_id: "CORRUPT"},
            clean_meta={instance_id: ("SFO", "2026-09-01", 45.0)},
            scanned=scanned,
        )

        rows = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-09-27",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        assert scanned == []
        assert rows[0].winner_instance_id == instance_id

        rows = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "station_candidates.jsonl",
            computed_day="2026-10-04",
            now_ns=1,
            instance_spans_cache_path=cache_path,
        )
        assert scanned == [instance_id]
        assert rows[0].reason == CORRUPT_ONLY


class TestCensusCompletenessAssertion:
    def test_matching_sets_is_a_no_op(self) -> None:
        _assert_census_is_complete(
            discovered={("SFO", "2026-09-01")}, written={("SFO", "2026-09-01")}
        )

    def test_a_missing_row_raises_loudly(self) -> None:
        with pytest.raises(CensusCompletenessError) as excinfo:
            _assert_census_is_complete(discovered={("SFO", "2026-09-01")}, written=set())

        assert "SFO" in str(excinfo.value)
        assert "2026-09-01" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Real, minimal feather fixtures: the LIVE/EMPTY completeness fix (HIGH)
# ---------------------------------------------------------------------------


def _weather_binary_option(*, station: str, climate_day: str, ts_init: int) -> BinaryOption:
    symbol = Symbol(f"TC-TEMP-{station}HIGH-{climate_day}-70")
    info = {
        "weather_facts_status": "KNOWN",
        "settlement_station": station,
        "climate_date": climate_day,
        "measure": "high",
        "strike_lower_f": 70,
        "strike_upper_f": None,
    }
    return BinaryOption(
        instrument_id=InstrumentId(symbol=symbol, venue=_VENUE),
        raw_symbol=symbol,
        outcome="Yes",
        description="AUD-09a census fixture",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        size_precision=0,
        size_increment=Quantity.from_int(1),
        activation_ns=0,
        expiration_ns=1_800_000_000_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=ts_init,
        ts_init=ts_init,
        info=info,
    )


def _write_binary_option_feather(path: Path, instruments: list[BinaryOption]) -> None:
    batch = ArrowSerializer.serialize_batch(instruments, data_cls=BinaryOption)
    table = pa.Table.from_batches([batch]) if isinstance(batch, pa.RecordBatch) else batch
    table = table.replace_schema_metadata({"class": BinaryOption.__name__})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, table.schema)
        writer.write_table(table)
        writer.close()


def _quote_tick(index: int) -> QuoteTick:
    return QuoteTick(
        instrument_id=InstrumentId(symbol=Symbol("EUR/USD"), venue=_VENUE),
        bid_price=Price.from_str("1.00000"),
        ask_price=Price.from_str("1.00010"),
        bid_size=Quantity.from_int(1),
        ask_size=Quantity.from_int(1),
        ts_event=1_000_000_000 + index,
        ts_init=1_000_000_000 + index,
    )


def _write_truncated_open_stream(path: Path, objects: list[QuoteTick]) -> None:
    """An OPEN (never-closed) IPC stream, then drop its tail -- classified
    truncated (not a clean EOS) by `inspect_feather_file`, and recently
    modified so `classify_instance` reads it as LIVE, not CORRUPT."""
    path.parent.mkdir(parents=True, exist_ok=True)
    first = ArrowSerializer.serialize_batch([objects[0]], data_cls=QuoteTick)
    with path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, first.schema)
        for obj in objects:
            piece = ArrowSerializer.serialize_batch([obj], data_cls=QuoteTick)
            if isinstance(piece, pa.RecordBatch):
                writer.write_batch(piece)
            else:
                writer.write_table(piece)
        # Deliberately never closed/`.close()`-d: no end-of-stream marker.
    with path.open("r+b") as handle:
        handle.truncate(max(path.stat().st_size - 8, 0))


class TestLiveAndEmptyInstancesGetARow:
    def test_a_live_only_day_gets_a_no_clean_instance_row_not_no_row_at_all(
        self,
        tmp_path: Path,
    ) -> None:
        instance_dir = tmp_path / "live" / "instance-live-1"
        _write_binary_option_feather(
            instance_dir / "binary_option_0.feather",
            [_weather_binary_option(station="SFO", climate_day="2026-09-05", ts_init=1)],
        )
        _write_truncated_open_stream(
            instance_dir / "quote_tick_0.feather", [_quote_tick(0), _quote_tick(1)]
        )

        now_ns = int(dt.datetime.now(dt.UTC).timestamp() * 1_000_000_000)

        rows = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "no-such-register.jsonl",
            computed_day=COMPUTED_DAY,
            now_ns=now_ns,
        )

        assert len(rows) == 1
        row = rows[0]
        assert (row.station, row.climate_day) == ("SFO", "2026-09-05")
        assert row.verdict == "INSUFFICIENT"
        assert row.reason == NO_CLEAN_INSTANCE

    def test_an_empty_only_instance_yields_zero_rows_and_does_not_crash(
        self,
        tmp_path: Path,
    ) -> None:
        instance_dir = tmp_path / "live" / "instance-empty-1"
        instance_dir.mkdir(parents=True)
        (instance_dir / "binary_option_0.feather").touch()  # 0 bytes: EMPTY_FILE

        now_ns = int(dt.datetime.now(dt.UTC).timestamp() * 1_000_000_000)

        rows = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=tmp_path / "no-such-register.jsonl",
            computed_day=COMPUTED_DAY,
            now_ns=now_ns,
        )

        assert rows == ()

    def test_a_registry_seed_candidate_never_duplicates_a_live_tape_key(
        self,
        tmp_path: Path,
    ) -> None:
        """Reproduces the 2026-09-25 production incident byte-for-byte: NYC
        seeded as a candidate for the SAME still-open day a live instance is
        already capturing real NYC quotes under. `run_census` must emit
        exactly one row for `(NYC, climate_day)`, carrying the real
        tape-derived verdict -- never the two-row
        `NO_CLEAN_INSTANCE`/`CANDIDATE_UNSUPPORTED_STATION` duplicate
        `read_replay_sufficiency` correctly refused."""
        instance_dir = tmp_path / "live" / "instance-live-1"
        _write_binary_option_feather(
            instance_dir / "binary_option_0.feather",
            [_weather_binary_option(station="NYC", climate_day="2026-09-25", ts_init=1)],
        )
        _write_truncated_open_stream(
            instance_dir / "quote_tick_0.feather", [_quote_tick(0), _quote_tick(1)]
        )

        register_path = tmp_path / "station_candidates.jsonl"
        candidate = _fake_candidate(
            venue="polymarket_us",
            city_token="nyc",
            last_seen_day="2026-09-25",
        )
        register_path.write_text(json.dumps(asdict(candidate)) + "\n", encoding="utf-8")

        now_ns = int(dt.datetime.now(dt.UTC).timestamp() * 1_000_000_000)

        rows = run_census(
            catalog_root=tmp_path,
            subdirectory="live",
            work_root=tmp_path / "work",
            station_candidates_path=register_path,
            computed_day=COMPUTED_DAY,
            now_ns=now_ns,
        )

        keys = [(row.station, row.climate_day) for row in rows]
        assert keys.count(("NYC", "2026-09-25")) == 1
        row = next(r for r in rows if (r.station, r.climate_day) == ("NYC", "2026-09-25"))
        assert row.reason == NO_CLEAN_INSTANCE


# ---------------------------------------------------------------------------
# A8 (census-local coverage): _live_instance_registrations attributes each
# LIVE instance's OWN capture start (min ts_init over its own registrations),
# never a merged/global minimum.
# ---------------------------------------------------------------------------


class TestLiveInstanceRegistrations:
    def test_returns_the_stations_days_and_the_instances_own_min_ts_init(
        self,
        tmp_path: Path,
    ) -> None:
        instance_dir = tmp_path / "live" / "instance-live-1"
        _write_binary_option_feather(
            instance_dir / "binary_option_0.feather",
            [
                _weather_binary_option(station="SFO", climate_day="2026-09-05", ts_init=5_000),
                _weather_binary_option(station="SFO", climate_day="2026-09-05", ts_init=1_000),
            ],
        )

        result = _live_instance_registrations(
            quote_catalog=tmp_path,
            subdirectory="live",
            live_ids=["instance-live-1"],
        )

        station_days, capture_start = result["instance-live-1"]
        assert station_days == {("SFO", dt.date(2026, 9, 5))}
        assert capture_start == 1_000  # the MIN over this instance's own rows

    def test_two_instances_each_keep_their_own_capture_start(self, tmp_path: Path) -> None:
        early = tmp_path / "live" / "instance-early"
        late = tmp_path / "live" / "instance-late"
        _write_binary_option_feather(
            early / "binary_option_0.feather",
            [_weather_binary_option(station="LAX", climate_day="2026-09-05", ts_init=100)],
        )
        _write_binary_option_feather(
            late / "binary_option_0.feather",
            [_weather_binary_option(station="LAX", climate_day="2026-09-05", ts_init=999_999)],
        )

        result = _live_instance_registrations(
            quote_catalog=tmp_path,
            subdirectory="live",
            live_ids=["instance-early", "instance-late"],
        )

        assert result["instance-early"][1] == 100
        assert result["instance-late"][1] == 999_999  # NOT merged into instance-early's start

    def test_an_instance_with_no_usable_registration_yields_none(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "live" / "instance-empty"
        instance_dir.mkdir(parents=True)
        (instance_dir / "binary_option_0.feather").touch()

        result = _live_instance_registrations(
            quote_catalog=tmp_path,
            subdirectory="live",
            live_ids=["instance-empty"],
        )

        station_days, capture_start = result["instance-empty"]
        assert station_days == set()
        assert capture_start is None


# ---------------------------------------------------------------------------
# A10: _discover_clean_spans calls window_extent through the module-level
# seam, rather than re-implementing the window filter inline. The catalog
# conversion itself is stubbed (not directly unit-tested per this module's
# own docstring); only `window_extent` is a real recording stub.
# ---------------------------------------------------------------------------


def _pad(
    side: OrderSide,
    levels: tuple[tuple[str, int], ...],
) -> tuple[list[BookOrder], list[int]]:
    filler = BookOrder(side, Price(0, 2), Quantity(0, 0), 0)
    orders = [BookOrder(side, Price.from_str(px), Quantity(size, 0), 0) for px, size in levels]
    counts = [1] * len(orders)
    while len(orders) < 10:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def _fake_depth(*, instrument_id: InstrumentId, ask: str, ts_event: int) -> OrderBookDepth10:
    bid_orders, bid_counts = _pad(OrderSide.BUY, (("0.01", 10),))
    ask_orders, ask_counts = _pad(OrderSide.SELL, ((ask, 5),))
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_event,
    )


def _fake_quote(*, instrument_id: InstrumentId, ts_event: int) -> QuoteTick:
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str("0.49"),
        ask_price=Price.from_str("0.51"),
        bid_size=Quantity.from_int(5),
        ask_size=Quantity.from_int(5),
        ts_event=ts_event,
        ts_init=ts_event,
    )


def test_a10_discover_clean_spans_calls_the_column_scan_seam(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REPLAY-BIGINST: `_discover_clean_spans` delegates window filtering to
    `breezy.persistence.catalog_column_scan.scan_depth_window`/
    `scan_quote_window` (the object-free column-scan seam) instead of
    reimplementing it inline. Direct successor of this test's pre-
    REPLAY-BIGINST version, which pinned the same property against the now-
    replaced `window_extent`-on-`TapeInstrument`-objects seam -- that seam no
    longer exists in `_discover_clean_spans` at all, by design (the plan's
    whole point), so the spy moves to the seam that replaced it."""
    station = "SFO"
    climate_day = dt.date(2026, 9, 1)
    offset = -8.0
    start_ns, _end_ns = decision_window_ns(climate_day=climate_day, std_utc_offset_hours=offset)
    ts_event = start_ns + 10 * 60_000_000_000  # 10 minutes into the window

    instrument = _weather_binary_option(
        station=station,
        climate_day=climate_day.isoformat(),
        ts_init=0,
    )
    depth = _fake_depth(instrument_id=instrument.id, ask="0.50", ts_event=ts_event)
    quote = _fake_quote(instrument_id=instrument.id, ts_event=ts_event)

    catalog = ParquetDataCatalog(tmp_path / "catalog")
    catalog.write_data([instrument])
    catalog.write_data([depth])
    catalog.write_data([quote])

    real_scan_depth_window = census_module.scan_depth_window
    real_scan_quote_window = census_module.scan_quote_window
    depth_calls: list[tuple[int, int]] = []
    quote_calls: list[tuple[int, int]] = []

    def _recording_scan_depth_window(files, *, start_ns, end_ns, should_stop, **kwargs):
        depth_calls.append((start_ns, end_ns))
        return real_scan_depth_window(
            files, start_ns=start_ns, end_ns=end_ns, should_stop=should_stop, **kwargs
        )

    def _recording_scan_quote_window(files, *, start_ns, end_ns, should_stop, **kwargs):
        quote_calls.append((start_ns, end_ns))
        return real_scan_quote_window(
            files, start_ns=start_ns, end_ns=end_ns, should_stop=should_stop, **kwargs
        )

    monkeypatch.setattr(census_module, "scan_depth_window", _recording_scan_depth_window)
    monkeypatch.setattr(census_module, "scan_quote_window", _recording_scan_quote_window)
    monkeypatch.setattr(census_module, "_convert_live_capture", lambda **kwargs: catalog)

    spans, clean_station_days, window_bounds = census_module._discover_clean_spans(
        catalog_root=tmp_path,
        subdirectory="live",
        clean_ids=["instance-1"],
        work_root=tmp_path / "work",
    )

    assert depth_calls, "scan_depth_window must be called, not re-implemented inline"
    assert quote_calls, "scan_quote_window must be called, not re-implemented inline"
    assert (station, climate_day.isoformat()) in clean_station_days
    span = spans[(station, climate_day.isoformat())][0]
    assert span.first_in_window_ns == ts_event
    assert span.last_in_window_ns == ts_event
    assert (station, climate_day.isoformat()) in window_bounds
