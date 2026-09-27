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
import json
import sys
from collections.abc import Iterable
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
)
from breezy.analysis.replay_sufficiency import (
    CANDIDATE_UNSUPPORTED_STATION,
    CORRUPT_ONLY,
    NO_CLEAN_INSTANCE,
    InstanceSpan,
    WindowExtent,
    decision_window_ns,
    window_extent,
)
from breezy.domain.weather_bucket_facts import read_weather_bucket_facts
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
    def pairs(self) -> tuple[tuple[str, str], ...]:
        return (("polymarket_us", "SFO"),)

    def climate_day_window(self, _venue: str, _station: str) -> _FakeWindow:
        return _FakeWindow()


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


def test_a10_discover_clean_spans_calls_window_extent_through_the_seam(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
    tape_instrument = SimpleNamespace(
        instrument=instrument,
        facts=read_weather_bucket_facts(instrument.info),
        depths=[depth],
        quotes=[quote],
        closes=[],
    )

    calls: list[tuple[tuple[int, ...], int, int]] = []

    def _recording_window_extent(
        ts_event_ns: Iterable[int],
        *,
        start_ns: int,
        end_ns: int,
    ) -> WindowExtent:
        values = tuple(ts_event_ns)
        calls.append((values, start_ns, end_ns))
        return window_extent(values, start_ns=start_ns, end_ns=end_ns)

    monkeypatch.setattr(census_module, "window_extent", _recording_window_extent)
    monkeypatch.setattr(
        census_module,
        "_convert_live_capture",
        lambda **kwargs: SimpleNamespace(instruments=lambda: [instrument]),
    )
    monkeypatch.setattr(
        census_module,
        "_select_capture_instruments",
        lambda catalog, *, climate_day: [tape_instrument],
    )

    spans, clean_station_days, window_bounds = census_module._discover_clean_spans(
        catalog_root=tmp_path,
        subdirectory="live",
        clean_ids=["instance-1"],
        work_root=tmp_path / "work",
    )

    assert calls, "window_extent must be called, not re-implemented inline"
    assert (station, climate_day.isoformat()) in clean_station_days
    span = spans[(station, climate_day.isoformat())][0]
    assert span.first_in_window_ns == ts_event
    assert span.last_in_window_ns == ts_event
    assert (station, climate_day.isoformat()) in window_bounds
