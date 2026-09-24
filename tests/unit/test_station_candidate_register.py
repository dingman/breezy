"""AUD-08b §6b.2-§6b.4: the station-candidate register, its fold, and its emitter.

Advisory only. Nothing here can make a city tradeable: the register is
read by the AUD-09a census and by a human; ``SUPPORTED_STATIONS`` and
``sites.toml`` are untouched by every path under test.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from breezy.persistence.station_candidates import (
    SIGHTING_SCHEMA_VERSION,
    STATION_CANDIDATES_SCHEMA_VERSION,
    StationCandidate,
    Sufficiency,
    UnknownStationCandidateSchemaError,
    UnregisteredCitySighting,
    append_sighting,
    compact_station_candidates,
    merge_sightings,
    read_last_folded_day,
    read_station_candidates,
    write_station_candidates,
)
from breezy.runtime.health import AlertPayload

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "analysis"


def _load_script() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    name = "station_candidate_register"
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


register_script = _load_script()

VENUE = "polymarket_us"
NYC = (VENUE, "nyc")
BOS = (VENUE, "bos")


def _ts_ns(day: str, hour: int = 12) -> int:
    instant = dt.datetime.fromisoformat(day).replace(hour=hour, tzinfo=dt.UTC)
    return int(instant.timestamp()) * 1_000_000_000


def _sighting(
    city_token: str = "bos",
    *,
    day: str = "2026-09-20",
    climate_date: str = "2026-09-21",
    bounds: str = "lt79f",
) -> UnregisteredCitySighting:
    return UnregisteredCitySighting(
        schema_version=SIGHTING_SCHEMA_VERSION,
        venue=VENUE,
        city_token=city_token,
        slug=f"tc-temp-{city_token}high-{climate_date}-{bounds}",
        climate_date=climate_date,
        observed_ts_ns=_ts_ns(day),
    )


def _fold(
    existing: Sequence[StationCandidate],
    sightings: Sequence[UnregisteredCitySighting],
    *,
    today: str,
    seed_cities: Sequence[tuple[str, str]] = (),
    sufficiency_by_city: Mapping[tuple[str, str], Sufficiency] | None = None,
) -> tuple[StationCandidate, ...]:
    by_city: dict[tuple[str, str], Sufficiency] = {
        (s.venue, s.city_token): "NO_SETTLEMENT_TRUTH" for s in sightings
    }
    by_city.update(sufficiency_by_city or {})
    return merge_sightings(
        existing,
        sightings,
        seed_cities=seed_cities,
        today=today,
        sufficiency_by_city=by_city,
    )


# ---------------------------------------------------------------------------
# The pure fold (§6b.2 merge rules, A6/A7/A9/A15)
# ---------------------------------------------------------------------------


def test_a_first_sighting_creates_one_sighting_origin_record() -> None:
    records = _fold((), (_sighting(), _sighting(bounds="gte80f")), today="2026-09-21")

    assert records == (
        StationCandidate(
            schema_version=STATION_CANDIDATES_SCHEMA_VERSION,
            venue=VENUE,
            city_token="bos",
            origin="SIGHTING",
            first_seen_day="2026-09-21",
            last_seen_day="2026-09-20",
            distinct_slugs=2,
            distinct_climate_days=1,
            sufficiency="NO_SETTLEMENT_TRUTH",
        ),
    )


def test_refolding_the_same_sightings_on_the_same_day_is_a_no_op() -> None:
    """A7 at the fold level: the idempotency key is (venue, city_token, last_seen_day)."""
    sightings = (_sighting(), _sighting(bounds="gte80f"))
    once = _fold((), sightings, today="2026-09-21")

    assert _fold(once, sightings, today="2026-09-21") == once


def test_first_seen_day_never_moves_and_last_seen_day_is_monotone() -> None:
    day_one = _fold((), (_sighting(day="2026-09-20"),), today="2026-09-21")
    day_two = _fold(
        day_one,
        (_sighting(day="2026-09-20"), _sighting(day="2026-09-22", climate_date="2026-09-23")),
        today="2026-09-23",
    )
    # An older window (e.g. a replayed sidecar) never pulls last_seen_day back.
    day_three = _fold(day_two, (_sighting(day="2026-09-20"),), today="2026-09-24")

    for records in (day_two, day_three):
        (record,) = records
        assert record.first_seen_day == "2026-09-21"
        assert record.last_seen_day == "2026-09-22"
        assert record.distinct_climate_days == 2
        assert record.distinct_slugs == 2


def test_a_city_that_disappears_keeps_its_record() -> None:
    day_one = _fold((), (_sighting(),), today="2026-09-21")

    assert _fold(day_one, (), today="2026-09-22") == day_one


def test_counts_are_distinct_and_never_double_count_a_multi_day_listing() -> None:
    """One market listed on three sidecar days is one slug and one climate day."""
    listing = [_sighting(day=day) for day in ("2026-09-18", "2026-09-19", "2026-09-20")]

    (record,) = _fold((), listing, today="2026-09-21")

    assert record.distinct_slugs == 1
    assert record.distinct_climate_days == 1


def test_sufficiency_is_taken_from_the_input_mapping_never_computed() -> None:
    (record,) = merge_sightings(
        (),
        (_sighting(),),
        seed_cities=(),
        today="2026-09-21",
        sufficiency_by_city={BOS: "CAPTURED_INSUFFICIENT"},
    )
    assert record.sufficiency == "CAPTURED_INSUFFICIENT"

    with pytest.raises(ValueError, match="sufficiency_by_city"):
        merge_sightings(
            (), (_sighting(),), seed_cities=(), today="2026-09-21", sufficiency_by_city={}
        )


def test_a_seed_with_no_sighting_produces_a_registry_seed_record() -> None:
    """A9: NYC has a producer -- the seed input -- with the seed's own sufficiency."""
    (record,) = _fold(
        (),
        (),
        today="2026-09-21",
        seed_cities=(NYC,),
        sufficiency_by_city={NYC: "CAPTURED_INSUFFICIENT"},
    )

    assert record.origin == "REGISTRY_SEED"
    assert (record.venue, record.city_token) == NYC
    assert record.sufficiency == "CAPTURED_INSUFFICIENT"
    assert (record.distinct_slugs, record.distinct_climate_days) == (0, 0)
    assert record.first_seen_day == "2026-09-21"


def test_a_seed_and_a_later_sighting_of_the_same_token_collapse_into_one_seed_record() -> None:
    """A6 (round-3 A8-4): one row per city; origin records how it entered."""
    seeded = _fold(
        (),
        (),
        today="2026-09-21",
        seed_cities=(NYC,),
        sufficiency_by_city={NYC: "REGISTRY_ONLY_NO_CAPTURE"},
    )
    later = _fold(
        seeded,
        (_sighting("nyc", day="2026-09-22"),),
        today="2026-09-23",
        seed_cities=(NYC,),
        sufficiency_by_city={NYC: "REGISTRY_ONLY_NO_CAPTURE"},
    )

    assert len(later) == 1
    assert later[0].origin == "REGISTRY_SEED"
    assert later[0].first_seen_day == "2026-09-21"


def test_origin_never_changes_once_set() -> None:
    sighted = _fold((), (_sighting("nyc"),), today="2026-09-21")
    reseeded = _fold(
        sighted,
        (),
        today="2026-09-22",
        seed_cities=(NYC,),
        sufficiency_by_city={NYC: "CAPTURE_SUFFICIENT"},
    )

    assert [r.origin for r in reseeded] == ["SIGHTING"]


def test_records_are_ordered_deterministically_by_key() -> None:
    records = _fold(
        (),
        (_sighting("phx"), _sighting("bos")),
        today="2026-09-21",
        seed_cities=(NYC,),
        sufficiency_by_city={NYC: "REGISTRY_ONLY_NO_CAPTURE"},
    )
    assert [r.city_token for r in records] == ["bos", "nyc", "phx"]


def test_a_record_older_than_180_days_compacts_idempotently_and_is_never_deleted() -> None:
    """A15."""
    (stale,) = _fold((), (_sighting(day="2026-01-01"),), today="2026-01-02")
    (fresh,) = _fold((), (_sighting("phx", day="2026-09-20"),), today="2026-09-21")
    records = (stale, fresh)

    once = compact_station_candidates(records, today="2026-09-21", sufficiency_by_city={})
    twice = compact_station_candidates(once, today="2026-09-21", sufficiency_by_city={})

    assert once == twice
    assert len(once) == 2
    assert once[0].last_seen_day == stale.last_seen_day
    assert (once[0].distinct_slugs, once[0].distinct_climate_days) == (1, 1)


# ---------------------------------------------------------------------------
# Writer / reader (§6b.4, A8)
# ---------------------------------------------------------------------------


def test_the_register_round_trips_with_stable_key_order(tmp_path: Path) -> None:
    path = tmp_path / "station_candidates.jsonl"
    records = _fold((), (_sighting(),), today="2026-09-21")

    write_station_candidates(path, records)

    assert read_station_candidates(path) == records
    (line,) = path.read_text(encoding="utf-8").splitlines()
    assert list(json.loads(line)) == sorted(json.loads(line))


def test_the_writer_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed replace leaves the previous register intact and no temp file behind."""
    import breezy.persistence.station_candidates as module

    path = tmp_path / "station_candidates.jsonl"
    write_station_candidates(path, _fold((), (_sighting(),), today="2026-09-21"))
    before = path.read_bytes()

    def boom(src: object, dst: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(f"{module.__name__}.os.replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        write_station_candidates(path, _fold((), (_sighting("phx"),), today="2026-09-21"))

    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["station_candidates.jsonl"]


def test_an_unknown_register_schema_version_raises_with_path_line_and_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "station_candidates.jsonl"
    write_station_candidates(path, _fold((), (_sighting(),), today="2026-09-21"))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["schema_version"] = 2
    path.write_text(path.read_text(encoding="utf-8") + json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(UnknownStationCandidateSchemaError) as excinfo:
        read_station_candidates(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "line 2" in message
    assert "schema_version 2" in message


def test_an_absent_register_reads_as_empty(tmp_path: Path) -> None:
    assert read_station_candidates(tmp_path / "station_candidates.jsonl") == ()


# ---------------------------------------------------------------------------
# The sufficiency mapping (§6b.3, A9)
# ---------------------------------------------------------------------------


def test_sufficiency_mapping_boundaries_come_from_the_imported_floor() -> None:
    floor = register_script.MIN_STRUCTURAL_DEAD_STATION_DAYS
    mapping = register_script.sufficiency_from_covered_listed_days

    assert mapping(0) == "REGISTRY_ONLY_NO_CAPTURE"
    assert mapping(floor - 1) == "CAPTURED_INSUFFICIENT"
    assert mapping(floor) == "CAPTURE_SUFFICIENT"
    with pytest.raises(ValueError):
        mapping(-1)


def test_the_seed_set_is_derived_in_the_venue_city_token_domain() -> None:
    """Round-3 A8-4: NYC is the ONE registered-but-unsupported PM.us city, keyed 'nyc'."""
    seeds = register_script.registry_seed_cities(VENUE)

    assert [(venue, token) for venue, token, _station in seeds] == [NYC]
    assert [station for _venue, _token, station in seeds] == ["NYC"]


# ---------------------------------------------------------------------------
# The emitter (§6b.4, A9 fourth arm, A16, A17)
# ---------------------------------------------------------------------------


class RecordingAlertSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class _Counter:
    def __init__(self, count: int = 0, *, raises: BaseException | None = None) -> None:
        self.count = count
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> int:
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.count


@pytest.fixture
def catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    (root / "data" / "order_book_depths").mkdir(parents=True)
    return root


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "station_candidates"


def _run(
    *,
    catalog_root: Path,
    state_dir: Path,
    today: str,
    counter: _Counter,
    monkeypatch: pytest.MonkeyPatch,
    alert_sink: RecordingAlertSink | None = None,
) -> int:
    monkeypatch.setattr(register_script, "count_covered_listed_station_days_from_catalog", counter)
    result: int = register_script.run(
        catalog_root=catalog_root,
        state_dir=state_dir,
        today=dt.date.fromisoformat(today),
        alert_sink=alert_sink if alert_sink is not None else RecordingAlertSink(),
    )
    return result


def _write_sidecar_day(state_dir: Path, *sightings: UnregisteredCitySighting) -> None:
    for sighting in sightings:
        append_sighting(state_dir / "sightings", sighting)


@pytest.mark.parametrize(
    ("count_offset", "expected"),
    [
        (None, "REGISTRY_ONLY_NO_CAPTURE"),
        (-1, "CAPTURED_INSUFFICIENT"),
        (0, "CAPTURE_SUFFICIENT"),
    ],
)
def test_the_nyc_seed_sufficiency_equals_the_mapping_of_the_counter(
    catalog_root: Path,
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    count_offset: int | None,
    expected: str,
) -> None:
    """A9: equality against §6b.3's mapping, boundary from the imported constant."""
    floor = register_script.MIN_STRUCTURAL_DEAD_STATION_DAYS
    count = 0 if count_offset is None else floor + count_offset
    counter = _Counter(count)

    assert (
        _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today="2026-09-24",
            counter=counter,
            monkeypatch=monkeypatch,
        )
        == 0
    )

    (record,) = read_station_candidates(state_dir / "station_candidates.jsonl")
    assert (record.venue, record.city_token, record.origin) == (VENUE, "nyc", "REGISTRY_SEED")
    assert record.sufficiency == expected
    assert record.sufficiency == register_script.sufficiency_from_covered_listed_days(count)
    assert counter.calls == [{"catalog_root": catalog_root, "cities": ("NYC",)}]


def _assert_refused_with_nothing_written(
    state_dir: Path, register_before: bytes, watermark_before: bytes
) -> None:
    register = state_dir / "station_candidates.jsonl"
    watermark = state_dir / "last_folded_day.json"
    assert register.read_bytes() == register_before
    assert watermark.read_bytes() == watermark_before
    assert "REGISTRY_ONLY_NO_CAPTURE" not in register.read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["root_absent", "depth_absent", "gap_refusal"])
def test_an_unreadable_catalog_refuses_and_never_reads_as_zero(
    tmp_path: Path,
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """A9 fourth arm (round-4 A8-6): exit non-zero, register and watermark byte-unchanged."""
    good_root = tmp_path / "good"
    (good_root / "data" / "order_book_depths").mkdir(parents=True)
    _write_sidecar_day(state_dir, _sighting(day="2026-09-20"))
    assert (
        _run(
            catalog_root=good_root,
            state_dir=state_dir,
            today="2026-09-21",
            counter=_Counter(3),
            monkeypatch=monkeypatch,
        )
        == 0
    )
    _write_sidecar_day(state_dir, _sighting("phx", day="2026-09-21"))
    register_before = (state_dir / "station_candidates.jsonl").read_bytes()
    watermark_before = (state_dir / "last_folded_day.json").read_bytes()
    sidecars_before = sorted(p.name for p in (state_dir / "sightings").iterdir())

    counter = _Counter(0)
    catalog_root = good_root
    if failure == "root_absent":
        catalog_root = tmp_path / "missing"
    elif failure == "depth_absent":
        catalog_root = tmp_path / "no_depth"
        catalog_root.mkdir()
    else:
        counter = _Counter(raises=register_script.QuoteTapeGapDataUnavailable("gaps unreadable"))

    code = _run(
        catalog_root=catalog_root,
        state_dir=state_dir,
        today="2026-09-22",
        counter=counter,
        monkeypatch=monkeypatch,
    )

    assert code != 0
    _assert_refused_with_nothing_written(state_dir, register_before, watermark_before)
    assert sorted(p.name for p in (state_dir / "sightings").iterdir()) == sidecars_before


def test_the_first_fold_refuses_on_an_absent_catalog_and_writes_nothing(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No previous value to keep: an absent catalog must never mint a seed row."""
    code = _run(
        catalog_root=tmp_path / "missing",
        state_dir=state_dir,
        today="2026-09-22",
        counter=_Counter(0),
        monkeypatch=monkeypatch,
    )

    assert code != 0
    assert not (state_dir / "station_candidates.jsonl").exists()
    assert not (state_dir / "last_folded_day.json").exists()


def test_a_new_sighting_candidate_alerts_exactly_once_across_two_folds(
    catalog_root: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A16: the dedupe is the durable register, not in-memory AlertState."""
    sink = RecordingAlertSink()
    _write_sidecar_day(state_dir, _sighting(day="2026-09-20"))
    for today in ("2026-09-21", "2026-09-22"):
        _write_sidecar_day(state_dir, _sighting(day=today))
        assert (
            _run(
                catalog_root=catalog_root,
                state_dir=state_dir,
                today=today,
                counter=_Counter(0),
                monkeypatch=monkeypatch,
                alert_sink=sink,
            )
            == 0
        )

    (payload,) = sink.payloads
    assert payload.event == "BREEZY_STATION_CANDIDATE_NEW"
    assert payload.site == "polymarket_us/bos"
    assert payload.severity == "WARN"
    assert "strategy-lead ruling" in payload.detail
    assert "sites.toml" in payload.detail
    assert "/" + "home" not in payload.detail
    assert str(state_dir) not in payload.detail


def test_a_registry_seed_never_alerts(
    catalog_root: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = RecordingAlertSink()

    assert (
        _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today="2026-09-21",
            counter=_Counter(0),
            monkeypatch=monkeypatch,
            alert_sink=sink,
        )
        == 0
    )

    assert [r.origin for r in read_station_candidates(state_dir / "station_candidates.jsonl")] == [
        "REGISTRY_SEED"
    ]
    assert sink.payloads == []


def test_a_rerun_on_the_same_day_is_byte_identical(
    catalog_root: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A7: byte-diff of two consecutive emissions."""
    _write_sidecar_day(state_dir, _sighting(day="2026-09-20"))
    outputs = []
    for _ in range(2):
        assert (
            _run(
                catalog_root=catalog_root,
                state_dir=state_dir,
                today="2026-09-21",
                counter=_Counter(4),
                monkeypatch=monkeypatch,
            )
            == 0
        )
        outputs.append(
            (
                (state_dir / "station_candidates.jsonl").read_bytes(),
                (state_dir / "last_folded_day.json").read_bytes(),
            )
        )
    assert outputs[0] == outputs[1]


def test_a_recovered_emitter_folds_every_missed_day_and_advances_the_watermark(
    catalog_root: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A17: three failed nights, then one run folds all of them in order."""
    _write_sidecar_day(state_dir, _sighting(day="2026-09-17"))
    assert (
        _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today="2026-09-18",
            counter=_Counter(0),
            monkeypatch=monkeypatch,
        )
        == 0
    )
    assert read_last_folded_day(state_dir / "last_folded_day.json") == "2026-09-17"

    _write_sidecar_day(
        state_dir,
        _sighting("phx", day="2026-09-18"),
        _sighting("sea", day="2026-09-19"),
        _sighting("den", day="2026-09-20"),
    )
    for today in ("2026-09-19", "2026-09-20", "2026-09-21"):
        assert (
            _run(
                catalog_root=catalog_root / "absent",
                state_dir=state_dir,
                today=today,
                counter=_Counter(0),
                monkeypatch=monkeypatch,
            )
            != 0
        )
    assert read_last_folded_day(state_dir / "last_folded_day.json") == "2026-09-17"

    sink = RecordingAlertSink()
    assert (
        _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today="2026-09-21",
            counter=_Counter(0),
            monkeypatch=monkeypatch,
            alert_sink=sink,
        )
        == 0
    )
    records = read_station_candidates(state_dir / "station_candidates.jsonl")
    assert {r.city_token for r in records} == {"bos", "phx", "sea", "den", "nyc"}
    assert read_last_folded_day(state_dir / "last_folded_day.json") == "2026-09-20"
    # A delayed fold delays the one-shot alert; it never skips it.
    assert sorted(p.site for p in sink.payloads) == [
        "polymarket_us/den",
        "polymarket_us/phx",
        "polymarket_us/sea",
    ]

    register_before = (state_dir / "station_candidates.jsonl").read_bytes()
    assert (
        _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today="2026-09-21",
            counter=_Counter(0),
            monkeypatch=monkeypatch,
        )
        == 0
    )
    assert (state_dir / "station_candidates.jsonl").read_bytes() == register_before


def test_todays_still_growing_sidecar_is_never_folded(
    catalog_root: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorder is still appending to today's file; folding it would strand the rest."""
    _write_sidecar_day(state_dir, _sighting(day="2026-09-21"))

    assert (
        _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today="2026-09-21",
            counter=_Counter(0),
            monkeypatch=monkeypatch,
        )
        == 0
    )

    assert [
        r.city_token for r in read_station_candidates(state_dir / "station_candidates.jsonl")
    ] == ["nyc"]
    assert read_last_folded_day(state_dir / "last_folded_day.json") is None


def test_an_absent_watermark_folds_every_unpruned_file_and_old_files_are_pruned_and_counted(
    catalog_root: Path,
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_sidecar_day(
        state_dir,
        _sighting("old", day="2026-08-01"),
        _sighting("bos", day="2026-09-01"),
        _sighting("phx", day="2026-09-20"),
    )

    assert (
        _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today="2026-09-21",
            counter=_Counter(0),
            monkeypatch=monkeypatch,
        )
        == 0
    )

    tokens = {r.city_token for r in read_station_candidates(state_dir / "station_candidates.jsonl")}
    assert tokens == {"bos", "phx", "nyc"}
    assert sorted(p.name for p in (state_dir / "sightings").iterdir()) == [
        "sightings-2026-09-01.jsonl",
        "sightings-2026-09-20.jsonl",
    ]
    summary = capsys.readouterr().out
    assert "sidecar_days_lost=1" in summary
    assert "sidecars_pruned=1" in summary


def test_a_corrupt_sidecar_refuses_with_the_register_untouched(
    catalog_root: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar = state_dir / "sightings" / "sightings-2026-09-20.jsonl"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("{not json\n{}\n", encoding="utf-8")

    assert (
        _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today="2026-09-21",
            counter=_Counter(0),
            monkeypatch=monkeypatch,
        )
        != 0
    )
    assert not (state_dir / "station_candidates.jsonl").exists()


def test_a_flood_of_new_cities_refuses_with_the_register_untouched(
    catalog_root: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9: more new cities in one fold than the registry holds pairs for the venue."""
    cap = register_script.flood_cap(VENUE)
    tokens = [f"x{index:02d}" for index in range(cap + 1)]
    _write_sidecar_day(state_dir, *(_sighting(token, day="2026-09-20") for token in tokens))

    assert (
        _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today="2026-09-21",
            counter=_Counter(0),
            monkeypatch=monkeypatch,
        )
        != 0
    )
    assert not (state_dir / "station_candidates.jsonl").exists()
    assert (state_dir / "sightings" / "sightings-2026-09-20.jsonl").exists()


def test_the_emitter_parses_catalog_root_with_the_shared_default() -> None:
    args = register_script.parse_args([])
    assert args.catalog_root == str(register_script.DEFAULT_QUOTE_TAPE_CATALOG)
