"""AUD-08b §6b.1 / A12: the sighting sidecar, and the provider's sink seam.

The sidecar is the durable input tape the nightly register emitter folds.
One writer (the recorder), one line per ``append_sighting`` call, one file
per UTC day of the sighting's OWN ``observed_ts_ns`` (never the wall clock,
never resolved once at attach). A trailing partial line is a crash artefact
and is skipped; a malformed non-final line is the two-writer defect and
refuses.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.provider import (
    PolymarketUSInstrumentProvider,
    SightingSinkAlreadyAttachedError,
)
from breezy.persistence.station_candidates import (
    SIGHTING_SCHEMA_VERSION,
    SightingSidecarCorruptError,
    UnknownSightingSchemaError,
    UnregisteredCitySighting,
    append_sighting,
    read_sightings,
    read_sightings_file,
    sighting_path,
)

#: 2026-09-24T23:59:59Z and 2026-09-25T00:00:01Z, in ns.
_BEFORE_MIDNIGHT_NS = 1_790_294_399 * 1_000_000_000
_AFTER_MIDNIGHT_NS = 1_790_294_401 * 1_000_000_000


def _sighting(
    *,
    city_token: str = "bos",
    slug: str = "tc-temp-boshigh-2026-09-25-lt79f",
    observed_ts_ns: int = _BEFORE_MIDNIGHT_NS,
) -> UnregisteredCitySighting:
    return UnregisteredCitySighting(
        schema_version=SIGHTING_SCHEMA_VERSION,
        venue="polymarket_us",
        city_token=city_token,
        slug=slug,
        climate_date="2026-09-25",
        observed_ts_ns=observed_ts_ns,
    )


def _line(**overrides: Any) -> str:
    record: dict[str, Any] = {
        "schema_version": SIGHTING_SCHEMA_VERSION,
        "venue": "polymarket_us",
        "city_token": "bos",
        "slug": "tc-temp-boshigh-2026-09-25-lt79f",
        "climate_date": "2026-09-25",
        "observed_ts_ns": _BEFORE_MIDNIGHT_NS,
    }
    record.update(overrides)
    return json.dumps(record, sort_keys=True)


def test_the_boundary_constants_straddle_a_utc_midnight() -> None:
    """Guards the fixture itself: a wrong constant would make the rotation arm vacuous."""
    assert sighting_path(Path("/d"), "2026-09-24").name == "sightings-2026-09-24.jsonl"
    before = append_day_name(_BEFORE_MIDNIGHT_NS)
    after = append_day_name(_AFTER_MIDNIGHT_NS)
    assert (before, after) == ("2026-09-24", "2026-09-25")


def append_day_name(ts_ns: int) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(ts_ns / 1e9, tz=dt.UTC).date().isoformat()


def test_append_sighting_writes_one_line_per_call_and_round_trips(tmp_path: Path) -> None:
    first = _sighting()
    second = _sighting(slug="tc-temp-boshigh-2026-09-25-gte80f")

    path_one = append_sighting(tmp_path, first)
    path_two = append_sighting(tmp_path, second)

    assert path_one == path_two == tmp_path / "sightings-2026-09-24.jsonl"
    raw = path_one.read_text(encoding="utf-8")
    assert raw.count("\n") == 2
    assert raw.endswith("\n")
    assert read_sightings(path_one) == (first, second)


def test_append_sighting_serializes_the_exact_expected_json_line(tmp_path: Path) -> None:
    """Pins the sidecar line's exact keys/values (AUD-08b credential-serialization
    guard fix: ``asdict`` replaced by explicit field-by-field serialization).
    Must keep passing unchanged across that refactor.
    """
    sighting = _sighting()

    path = append_sighting(tmp_path, sighting)

    (line,) = path.read_text(encoding="utf-8").splitlines()
    assert line == _line()
    assert json.loads(line) == {
        "schema_version": SIGHTING_SCHEMA_VERSION,
        "venue": "polymarket_us",
        "city_token": "bos",
        "slug": "tc-temp-boshigh-2026-09-25-lt79f",
        "climate_date": "2026-09-25",
        "observed_ts_ns": _BEFORE_MIDNIGHT_NS,
    }


def test_two_appends_straddling_utc_midnight_land_in_two_day_named_files(
    tmp_path: Path,
) -> None:
    """A12 rotation arm (round-4 a1): the day is resolved PER APPEND from the record."""
    late = _sighting(observed_ts_ns=_BEFORE_MIDNIGHT_NS)
    early = _sighting(observed_ts_ns=_AFTER_MIDNIGHT_NS, slug="tc-temp-boshigh-2026-09-26-lt79f")

    assert append_sighting(tmp_path, late).name == "sightings-2026-09-24.jsonl"
    assert append_sighting(tmp_path, early).name == "sightings-2026-09-25.jsonl"

    assert read_sightings(tmp_path / "sightings-2026-09-24.jsonl") == (late,)
    assert read_sightings(tmp_path / "sightings-2026-09-25.jsonl") == (early,)


def test_an_unstamped_sighting_is_refused_before_any_write(tmp_path: Path) -> None:
    """``observed_ts_ns == 0`` means the provider never stamped it: its day is unknowable."""
    with pytest.raises(ValueError, match="observed_ts_ns"):
        append_sighting(tmp_path, _sighting(observed_ts_ns=0))
    assert list(tmp_path.iterdir()) == []


def test_a_trailing_partial_line_is_skipped_with_a_warn_and_counted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "sightings-2026-09-24.jsonl"
    path.write_text(_line() + "\n" + _line()[:17], encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        result = read_sightings_file(path)

    assert result.sightings == (_sighting(),)
    assert result.partial_lines_skipped == 1
    assert any("partial" in record.getMessage() for record in caplog.records)


def test_a_malformed_non_final_line_is_a_hard_refusal(tmp_path: Path) -> None:
    """Interleaving means two writers raced: the emitter must refuse, never absorb."""
    path = tmp_path / "sightings-2026-09-24.jsonl"
    path.write_text(_line()[:17] + "\n" + _line() + "\n", encoding="utf-8")

    with pytest.raises(SightingSidecarCorruptError, match=r"line 1"):
        read_sightings(path)


def test_a_line_missing_a_field_is_a_hard_refusal(tmp_path: Path) -> None:
    path = tmp_path / "sightings-2026-09-24.jsonl"
    record = json.loads(_line())
    del record["slug"]
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(SightingSidecarCorruptError, match=r"line 1"):
        read_sightings(path)


def test_an_unknown_sighting_schema_version_raises_with_path_line_and_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sightings-2026-09-24.jsonl"
    path.write_text(_line() + "\n" + _line(schema_version=2) + "\n", encoding="utf-8")

    with pytest.raises(UnknownSightingSchemaError) as excinfo:
        read_sightings(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "line 2" in message
    assert "schema_version 2" in message


# ---------------------------------------------------------------------------
# The provider's sink seam (§6b.1 "The provider's call-site for the sink")
# ---------------------------------------------------------------------------


class RecordingSink:
    def __init__(self) -> None:
        self.appended: list[UnregisteredCitySighting] = []

    def append(self, sighting: UnregisteredCitySighting) -> None:
        self.appended.append(sighting)


def _bare_provider() -> PolymarketUSInstrumentProvider:
    # Construction only -- the seam under test never touches the client.
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.config import InstrumentProviderConfig

    from breezy.adapters.polymarket_us.config import PolymarketUSMarketDiscoveryConfig

    return PolymarketUSInstrumentProvider(
        client=object(),  # type: ignore[arg-type]
        config=InstrumentProviderConfig(load_all=True),
        discovery=PolymarketUSMarketDiscoveryConfig(limit=10),
        clock=TestClock(),
    )


def test_attach_sighting_sink_is_idempotent_by_identity_and_refuses_a_second_sink() -> None:
    provider = _bare_provider()
    sink = RecordingSink()

    provider.attach_sighting_sink(sink)
    provider.attach_sighting_sink(sink)

    with pytest.raises(SightingSinkAlreadyAttachedError):
        provider.attach_sighting_sink(RecordingSink())


def test_a_provider_has_no_sink_until_one_is_attached() -> None:
    assert _bare_provider().sighting_sink is None
