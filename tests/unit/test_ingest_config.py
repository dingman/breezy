"""Tests for `breezy.ingest.config.NwsIngestActorConfig`.

`NwsIngestActorConfig` must be a msgspec-serialisable
`nautilus_trader.common.config.ActorConfig` -- imported from `common.config`
(typed `.py`), not `common.actor` (compiled Cython, erases to `Any`) -- and
carry only scalar fields so it survives `ImportableActorConfig` round-trips
at Trader-node startup.
"""

from __future__ import annotations

import pytest
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.model.identifiers import ComponentId

from breezy.ingest.config import NwsIngestActorConfig


def _config(**overrides: object) -> NwsIngestActorConfig:
    base: dict[str, object] = {"venue": "polymarket_us", "city": "NYC"}
    base.update(overrides)
    return NwsIngestActorConfig(**base)  # type: ignore[arg-type]


def test_is_an_actor_config() -> None:
    assert isinstance(_config(), ActorConfig)


def test_is_frozen() -> None:
    config = _config()
    with pytest.raises(AttributeError):
        config.venue = "kalshi"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


def test_venue_and_city_are_required() -> None:
    config = _config(venue="polymarket_us", city="SFO")
    assert config.venue == "polymarket_us"
    assert config.city == "SFO"


def test_missing_venue_raises() -> None:
    with pytest.raises(TypeError):
        NwsIngestActorConfig(city="NYC")  # type: ignore[call-arg]


def test_missing_city_raises() -> None:
    with pytest.raises(TypeError):
        NwsIngestActorConfig(venue="polymarket_us")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_poll_interval_seconds() -> None:
    assert _config().poll_interval_seconds == 300


def test_default_parse_timeout_ms() -> None:
    assert _config().parse_timeout_ms == 250


def test_default_discovery_max_bytes() -> None:
    assert _config().discovery_max_bytes == 262_144


def test_default_discovery_max_depth() -> None:
    assert _config().discovery_max_depth == 8


def test_default_final_deadline_check_interval_seconds() -> None:
    assert _config().final_deadline_check_interval_seconds == 300


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_override_poll_interval_seconds() -> None:
    assert _config(poll_interval_seconds=60).poll_interval_seconds == 60


def test_override_parse_timeout_ms() -> None:
    assert _config(parse_timeout_ms=500).parse_timeout_ms == 500


def test_override_discovery_max_bytes() -> None:
    assert _config(discovery_max_bytes=1024).discovery_max_bytes == 1024


def test_override_discovery_max_depth() -> None:
    assert _config(discovery_max_depth=3).discovery_max_depth == 3


def test_override_final_deadline_check_interval_seconds() -> None:
    assert (
        _config(final_deadline_check_interval_seconds=120).final_deadline_check_interval_seconds
        == 120
    )


# ---------------------------------------------------------------------------
# component_id (inherited from ActorConfig) is settable
# ---------------------------------------------------------------------------


def test_component_id_is_settable() -> None:
    component_id = ComponentId("NWS-NYC")
    config = _config(component_id=component_id)
    assert config.component_id == component_id


def test_component_id_defaults_to_none() -> None:
    assert _config().component_id is None


# ---------------------------------------------------------------------------
# msgspec round-trip -- proves this is serialisable for ImportableActorConfig
# ---------------------------------------------------------------------------


def test_round_trips_through_json_encode_decode() -> None:
    original = _config(
        venue="polymarket_us",
        city="SFO",
        poll_interval_seconds=120,
        parse_timeout_ms=400,
        discovery_max_bytes=4096,
        discovery_max_depth=2,
        final_deadline_check_interval_seconds=60,
        component_id=ComponentId("NWS-SFO"),
    )
    encoded = original.json()
    decoded = NwsIngestActorConfig.parse(encoded)
    assert decoded == original
    assert decoded.venue == "polymarket_us"
    assert decoded.city == "SFO"
    assert decoded.poll_interval_seconds == 120
    assert decoded.parse_timeout_ms == 400
    assert decoded.discovery_max_bytes == 4096
    assert decoded.discovery_max_depth == 2
    assert decoded.final_deadline_check_interval_seconds == 60
    assert decoded.component_id == ComponentId("NWS-SFO")


def test_round_trips_with_default_values() -> None:
    original = _config()
    decoded = NwsIngestActorConfig.parse(original.json())
    assert decoded == original


def test_round_trip_preserves_scalar_only_fields_are_json_primitives() -> None:
    """Every field must survive as a plain JSON primitive scalar -- no Path,
    no callables, no object references -- proving composition-time-only
    injection stays out of the config.
    """
    import json

    payload = json.loads(_config().json())
    for key, value in payload.items():
        if key == "component_id":
            assert value is None or isinstance(value, str)
        else:
            assert isinstance(value, (str, int, float, bool)) or value is None
