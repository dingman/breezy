"""Tests for `breezy.settings` -- the environment-sourced runtime config.

RED-first: written before `src/breezy/settings.py` exists.

Governing rulings (see the task brief this module was built against):

* No secrets live here. `user_agent_contact` is PII-adjacent (a monitored
  role mailbox), never a credential.
* `BREEZY_USER_AGENT` is required -- `from_env` raises on absence, the exact
  mirror of the fail-fast fix in `breezy.ingest.http._default_user_agent`
  (see `tests/unit/test_http_transport.py`).
* Sites are validated against the real settlement-site registry
  (`breezy.registry.sites`); an unknown `venue/city` raises, naming the
  offending value.
* Poll stagger is DERIVED, never configured per-site: Actor `i` gets
  `i * poll_stagger_ns`, computed by `BreezySettings.poll_offset_ns`.
* `BREEZY_CATALOG_BASE` / `BREEZY_STATE_PATH` are canonicalized (realpath)
  before use.
* `from_env` reads only the `env` mapping it is given -- never `os.environ`
  directly -- when `env` is supplied.
"""

from __future__ import annotations

import os
from pathlib import Path

import msgspec
import pytest
from nautilus_trader.common.config import InvalidConfiguration, NautilusConfig

from breezy.registry.sites import default_registry
from breezy.settings import (
    BreezySettings,
    SettingsError,
)

# The registry's real, settled five-city keying (see sites.toml). Order
# matters for the stagger tests below -- it is the Actor construction order.
ALL_SITE_ENTRIES = "polymarket_us/NYC,polymarket_us/SFO,polymarket_us/MIA,polymarket_us/MDW,polymarket_us/LAX"
ALL_SITE_PAIRS = (
    ("polymarket_us", "NYC"),
    ("polymarket_us", "SFO"),
    ("polymarket_us", "MIA"),
    ("polymarket_us", "MDW"),
    ("polymarket_us", "LAX"),
)


def _base_env(**overrides: str) -> dict[str, str]:
    """A minimal, valid environment mapping `from_env` can build settings from."""
    env = {
        "BREEZY_USER_AGENT": "breezy-weather-ingest/0.1 (+mailto:breezy@jonathan.vc)",
        "BREEZY_SITES": ALL_SITE_ENTRIES,
        "BREEZY_CATALOG_BASE": "/tmp/breezy-test/catalog",
        "BREEZY_STATE_PATH": "/tmp/breezy-test/state.json",
    }
    env.update(overrides)
    return env


@pytest.fixture(autouse=True)
def _no_ambient_breezy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from whatever the real process environment carries.

    `from_env(...)` with an explicit mapping must never consult `os.environ`
    (RED test 8 below already pins that directly), but this fixture also
    protects the `from_env(None)`-style implicit-default path used nowhere in
    this suite today from silently passing due to ambient CI/dev environment
    variables.
    """
    for var in (
        "BREEZY_USER_AGENT",
        "BREEZY_SITES",
        "BREEZY_CATALOG_BASE",
        "BREEZY_STATE_PATH",
        "BREEZY_POLL_INTERVAL_S",
        "BREEZY_POLL_STAGGER_S",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# RED 2 -- BREEZY_USER_AGENT is required
# ---------------------------------------------------------------------------


def test_from_env_raises_on_missing_user_agent() -> None:
    env = _base_env()
    del env["BREEZY_USER_AGENT"]

    with pytest.raises(SettingsError, match="BREEZY_USER_AGENT"):
        BreezySettings.from_env(env)


def test_from_env_raises_on_empty_user_agent() -> None:
    with pytest.raises(SettingsError, match="BREEZY_USER_AGENT"):
        BreezySettings.from_env(_base_env(BREEZY_USER_AGENT=""))


def test_from_env_empty_mapping_raises_on_missing_user_agent() -> None:
    """`from_env({})` -- the simplest possible RED case from the task brief."""
    with pytest.raises(SettingsError, match="BREEZY_USER_AGENT"):
        BreezySettings.from_env({})


def test_from_env_succeeds_with_a_complete_valid_environment() -> None:
    settings = BreezySettings.from_env(_base_env())

    assert settings.user_agent_contact == "breezy-weather-ingest/0.1 (+mailto:breezy@jonathan.vc)"
    assert settings.sites == ALL_SITE_PAIRS


# ---------------------------------------------------------------------------
# RED 3 -- unknown venue/city raises, naming the offending value
# ---------------------------------------------------------------------------


def test_unknown_site_raises_and_names_the_offending_value() -> None:
    env = _base_env(BREEZY_SITES="polymarket_us/NYC,polymarket_us/ATLANTIS")

    with pytest.raises(SettingsError, match="polymarket_us/ATLANTIS"):
        BreezySettings.from_env(env)


def test_unknown_venue_raises_and_names_the_offending_value() -> None:
    env = _base_env(BREEZY_SITES="kalshi/NYC")

    with pytest.raises(SettingsError, match="kalshi/NYC"):
        BreezySettings.from_env(env)


def test_malformed_site_entry_raises_and_names_the_offending_value() -> None:
    """No slash at all -- not a registry miss, a shape defect."""
    env = _base_env(BREEZY_SITES="polymarket_us")

    with pytest.raises(SettingsError, match="polymarket_us"):
        BreezySettings.from_env(env)


def test_site_entry_with_too_many_slashes_raises() -> None:
    env = _base_env(BREEZY_SITES="polymarket_us/NYC/extra")

    with pytest.raises(SettingsError, match="polymarket_us/NYC/extra"):
        BreezySettings.from_env(env)


def test_empty_sites_value_raises() -> None:
    env = _base_env(BREEZY_SITES="")

    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        BreezySettings.from_env(env)


def test_every_real_registry_pair_is_individually_accepted() -> None:
    """Cross-check against the live registry rather than a hardcoded list.

    Guards against this test file and `sites.toml` drifting apart silently.
    """
    registry = default_registry()
    for venue, city in registry.pairs():
        env = _base_env(BREEZY_SITES=f"{venue}/{city}")
        settings = BreezySettings.from_env(env)
        assert settings.sites == ((venue, city),)


# ---------------------------------------------------------------------------
# RED 4 -- duplicate sites raise
# ---------------------------------------------------------------------------


def test_duplicate_sites_raise() -> None:
    env = _base_env(BREEZY_SITES="polymarket_us/NYC,polymarket_us/SFO,polymarket_us/NYC")

    with pytest.raises(SettingsError, match="polymarket_us/NYC"):
        BreezySettings.from_env(env)


def test_duplicate_sites_raise_even_with_whitespace_variation() -> None:
    """Whitespace around an entry must not defeat duplicate detection."""
    env = _base_env(BREEZY_SITES="polymarket_us/NYC, polymarket_us/NYC")

    with pytest.raises(SettingsError):
        BreezySettings.from_env(env)


# ---------------------------------------------------------------------------
# RED 5 -- stagger is derived: a pure function of index, not of the site list
# ---------------------------------------------------------------------------


def test_five_sites_yield_five_distinct_poll_offsets() -> None:
    settings = BreezySettings.from_env(_base_env())

    offsets = [settings.poll_offset_ns(i) for i in range(len(settings.sites))]

    assert len(set(offsets)) == len(offsets)


def test_poll_offset_is_a_pure_function_of_index() -> None:
    settings = BreezySettings.from_env(_base_env())

    for i in range(10):
        assert settings.poll_offset_ns(i) == i * settings.poll_stagger_ns


def test_poll_offset_does_not_depend_on_the_configured_site_list() -> None:
    """Proves offsets come from the index alone, never a per-site table.

    A single-site config and a five-site config must agree on `poll_offset_ns`
    for any given index, including an index past the shorter list's length --
    a per-site offset table could not do that.
    """
    one_site_env = _base_env(BREEZY_SITES="polymarket_us/NYC")
    five_site_env = _base_env()

    one_site_settings = BreezySettings.from_env(one_site_env)
    five_site_settings = BreezySettings.from_env(five_site_env)

    for i in range(5):
        assert one_site_settings.poll_offset_ns(i) == five_site_settings.poll_offset_ns(i)


def test_poll_offset_rejects_a_negative_index() -> None:
    settings = BreezySettings.from_env(_base_env())

    with pytest.raises(SettingsError):
        settings.poll_offset_ns(-1)


# ---------------------------------------------------------------------------
# RED 6 -- path canonicalization for BREEZY_CATALOG_BASE / BREEZY_STATE_PATH
# ---------------------------------------------------------------------------


def test_catalog_base_containing_dotdot_is_canonicalized(tmp_path: object) -> None:
    from pathlib import Path

    base = Path(str(tmp_path))
    nested = base / "a" / "b"
    nested.mkdir(parents=True)
    raw = str(base / "a" / "b" / ".." / "b")

    env = _base_env(BREEZY_CATALOG_BASE=raw)
    settings = BreezySettings.from_env(env)

    assert settings.catalog_base == nested.resolve()
    assert ".." not in settings.catalog_base.parts


def test_state_path_containing_dotdot_is_canonicalized(tmp_path: object) -> None:
    from pathlib import Path

    base = Path(str(tmp_path))
    nested = base / "x" / "y"
    nested.mkdir(parents=True)
    raw = str(base / "x" / "y" / ".." / "y" / "state.json")

    env = _base_env(BREEZY_STATE_PATH=raw)
    settings = BreezySettings.from_env(env)

    assert settings.state_store_path == (nested / "state.json").resolve()


def test_catalog_base_symlink_is_resolved_to_its_real_target(tmp_path: object) -> None:
    from pathlib import Path

    base = Path(str(tmp_path))
    real_target = base / "real_catalog"
    real_target.mkdir()
    link = base / "catalog_link"
    link.symlink_to(real_target, target_is_directory=True)

    env = _base_env(BREEZY_CATALOG_BASE=str(link))
    settings = BreezySettings.from_env(env)

    assert settings.catalog_base == real_target.resolve()
    assert settings.catalog_base != link


def test_relative_catalog_base_is_rejected() -> None:
    env = _base_env(BREEZY_CATALOG_BASE="relative/catalog/path")

    with pytest.raises(SettingsError, match="BREEZY_CATALOG_BASE"):
        BreezySettings.from_env(env)


def test_relative_state_path_is_rejected() -> None:
    env = _base_env(BREEZY_STATE_PATH="relative/state.json")

    with pytest.raises(SettingsError, match="BREEZY_STATE_PATH"):
        BreezySettings.from_env(env)


def test_missing_catalog_base_raises() -> None:
    env = _base_env()
    del env["BREEZY_CATALOG_BASE"]

    with pytest.raises(SettingsError, match="BREEZY_CATALOG_BASE"):
        BreezySettings.from_env(env)


def test_missing_state_path_raises() -> None:
    env = _base_env()
    del env["BREEZY_STATE_PATH"]

    with pytest.raises(SettingsError, match="BREEZY_STATE_PATH"):
        BreezySettings.from_env(env)


# ---------------------------------------------------------------------------
# RED 7 -- malformed numerics raise, naming the variable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", ["abc", "-5", "0", "1e", "NaN"])
def test_malformed_poll_interval_raises_naming_the_variable(bad_value: str) -> None:
    env = _base_env(BREEZY_POLL_INTERVAL_S=bad_value)

    with pytest.raises(SettingsError, match="BREEZY_POLL_INTERVAL_S"):
        BreezySettings.from_env(env)


@pytest.mark.parametrize("bad_value", ["abc", "-5", "0", "1e", "NaN"])
def test_malformed_poll_stagger_raises_naming_the_variable(bad_value: str) -> None:
    env = _base_env(BREEZY_POLL_STAGGER_S=bad_value)

    with pytest.raises(SettingsError, match="BREEZY_POLL_STAGGER_S"):
        BreezySettings.from_env(env)


def test_empty_poll_interval_is_treated_as_unset_and_defaults() -> None:
    """An explicitly-empty value is treated the same as an absent key for the
    two optional cadence knobs -- consistent with how every other optional
    field in this module collapses '' to "not provided", and avoids two
    divergent code paths (missing key vs. present-but-empty) for the same
    intent. This is a deliberate product decision, not an oversight: an
    operator template that sets `BREEZY_POLL_INTERVAL_S=` (empty) should get
    the documented default, not a startup crash.
    """
    settings = BreezySettings.from_env(_base_env(BREEZY_POLL_INTERVAL_S=""))

    assert settings.poll_interval_ns > 0


def test_valid_poll_interval_and_stagger_are_honoured() -> None:
    env = _base_env(BREEZY_POLL_INTERVAL_S="60", BREEZY_POLL_STAGGER_S="10")

    settings = BreezySettings.from_env(env)

    assert settings.poll_interval_ns == 60_000_000_000
    assert settings.poll_stagger_ns == 10_000_000_000


def test_poll_interval_and_stagger_default_when_unset() -> None:
    """Absence of the two cadence knobs is not an error -- proposal §6 gives no
    explicit numeric cadence, so `from_env` falls back to a documented,
    defensible default rather than requiring every deployment to specify it.
    """
    env = _base_env()

    settings = BreezySettings.from_env(env)

    assert settings.poll_interval_ns > 0
    assert settings.poll_stagger_ns >= 0


# ---------------------------------------------------------------------------
# RED 8 -- from_env reads ONLY the passed mapping, never os.environ
# ---------------------------------------------------------------------------


def test_from_env_ignores_ambient_os_environ_when_env_is_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The strongest form of this contract: os.environ carries valid config,
    but the empty explicit mapping is what wins -- proving there is no
    merge/fallback onto the real environment.
    """
    monkeypatch.setenv("BREEZY_USER_AGENT", "should-never-be-read/1.0 (+mailto:x@example.com)")
    monkeypatch.setenv("BREEZY_SITES", ALL_SITE_ENTRIES)
    monkeypatch.setenv("BREEZY_CATALOG_BASE", "/tmp/should-not-be-read/catalog")
    monkeypatch.setenv("BREEZY_STATE_PATH", "/tmp/should-not-be-read/state.json")

    with pytest.raises(SettingsError, match="BREEZY_USER_AGENT"):
        BreezySettings.from_env({})


def test_from_env_uses_the_explicit_mapping_value_over_a_conflicting_os_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BREEZY_USER_AGENT", "from-os-environ/1.0 (+mailto:x@example.com)")

    env = _base_env(BREEZY_USER_AGENT="from-explicit-mapping/1.0 (+mailto:y@example.com)")
    settings = BreezySettings.from_env(env)

    assert settings.user_agent_contact == "from-explicit-mapping/1.0 (+mailto:y@example.com)"
    assert os.environ["BREEZY_USER_AGENT"] == "from-os-environ/1.0 (+mailto:x@example.com)"


def test_from_env_defaults_to_os_environ_when_env_argument_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`env=None` (the default) DOES read the real environment -- only an
    explicitly-supplied mapping is exclusive.
    """
    for key, value in _base_env().items():
        monkeypatch.setenv(key, value)

    settings = BreezySettings.from_env()

    assert settings.user_agent_contact == _base_env()["BREEZY_USER_AGENT"]


# ---------------------------------------------------------------------------
# No secrets / structural checks
# ---------------------------------------------------------------------------


def test_settings_is_frozen_and_slotted() -> None:
    """`BreezySettings` is now a `NautilusConfig` (msgspec `Struct`), not a
    stdlib `@dataclass` -- so mutating a frozen instance raises `AttributeError`
    (msgspec's own frozen-violation type), not `dataclasses.FrozenInstanceError`.
    The *meaning* of this test (mutation is rejected) is unchanged; only the
    raised exception type changed, forced by the underlying object-model
    migration (a msgspec `Struct` has no `__dict__`, confirmed empirically --
    the "slotted" half of the assertion still holds).
    """
    settings = BreezySettings.from_env(_base_env())

    with pytest.raises(AttributeError):
        settings.poll_interval_ns = 1  # type: ignore[misc]

    assert not hasattr(settings, "__dict__")


def test_no_redis_or_secret_looking_fields_exist() -> None:
    """Absence of Redis settings is a recorded decision, not an oversight --
    and nothing field-shaped here should look like a credential.

    `BreezySettings` is a msgspec `Struct` (via `NautilusConfig`), not a
    `@dataclass`, so field introspection goes through `msgspec.structs.fields`
    rather than `dataclasses.fields` -- same intent, different introspection
    API, forced by the same object-model migration as the test above.
    """
    field_names = {f.name for f in msgspec.structs.fields(BreezySettings)}

    assert not any("redis" in name.lower() for name in field_names)
    assert not any("secret" in name.lower() or "password" in name.lower() for name in field_names)
    assert not any("api_key" in name.lower() or "token" in name.lower() for name in field_names)


def test_require_durable_store_defaults_true() -> None:
    settings = BreezySettings.from_env(_base_env())

    assert settings.require_durable_store is True


def test_parse_timeout_matches_the_proposal_documented_ceiling() -> None:
    """§6: `PARSE_TIME_CEILING_SECONDS` is explicitly 0.25s in the proposal."""
    settings = BreezySettings.from_env(_base_env())

    assert settings.parse_timeout_s == 0.25


def test_catalog_io_workers_is_a_positive_int() -> None:
    settings = BreezySettings.from_env(_base_env())

    assert isinstance(settings.catalog_io_workers, int)
    assert settings.catalog_io_workers >= 1


def test_freshness_blocked_after_exceeds_degraded_after() -> None:
    settings = BreezySettings.from_env(_base_env())

    assert settings.freshness_blocked_after_ns > settings.freshness_degraded_after_ns > 0


# ---------------------------------------------------------------------------
# RED (rewrite) 1 -- BreezySettings is a NautilusConfig subclass and frozen
# ---------------------------------------------------------------------------


def test_breezy_settings_is_a_nautilus_config_subclass() -> None:
    assert issubclass(BreezySettings, NautilusConfig)


def test_breezy_settings_struct_config_is_frozen() -> None:
    assert BreezySettings.__struct_config__.frozen is True


def test_breezy_settings_forbids_unknown_fields_at_the_struct_level() -> None:
    """`forbid_unknown_fields` is `NautilusConfig`'s own struct-level config
    and is inherited automatically by every subclass (verified empirically --
    unlike `kw_only`, which is not); this pins that it is still in force.
    """
    assert BreezySettings.__struct_config__.forbid_unknown_fields is True


# ---------------------------------------------------------------------------
# RED (rewrite) 2 -- `.json()` -> `.parse()` round-trips losslessly
# ---------------------------------------------------------------------------


def test_json_parse_round_trips_losslessly_including_paths_and_sites() -> None:
    """The capability this rewrite exists to buy: a `BreezySettings` must
    survive a full `.json()` -> `.parse()` round trip with no data loss,
    including the two `Path` fields and the `tuple[tuple[str, str], ...]`
    sites field -- neither of which msgspec encodes natively (see the
    module docstring for the encoding-hook gap and how it is closed).
    """
    settings = BreezySettings.from_env(_base_env())

    round_tripped = BreezySettings.parse(settings.json())

    assert round_tripped == settings
    assert round_tripped.catalog_base == settings.catalog_base
    assert isinstance(round_tripped.catalog_base, type(settings.catalog_base))
    assert round_tripped.state_store_path == settings.state_store_path
    assert round_tripped.sites == settings.sites == ALL_SITE_PAIRS
    assert round_tripped.require_durable_store == settings.require_durable_store


def test_json_encodes_paths_as_plain_strings() -> None:
    """Confirms the encoding side of the round trip concretely: `Path` fields
    serialize to JSON strings, not some opaque/unsupported representation.
    """
    settings = BreezySettings.from_env(_base_env())

    primitives = msgspec.json.decode(settings.json())

    assert primitives["catalog_base"] == str(settings.catalog_base)
    assert primitives["state_store_path"] == str(settings.state_store_path)
    assert primitives["sites"] == [list(pair) for pair in settings.sites]


def test_round_trip_survives_the_importable_actor_config_json_boundary() -> None:
    """Mirrors `nautilus_trader.common.config.ActorFactory.create`: a settings
    object's JSON-primitive form is re-encoded with Nautilus's own global
    `msgspec_encoding_hook` (not our local one) before being handed back to
    `BreezySettings.parse` -- this is the exact boundary the whole rewrite
    exists to cross (`ImportableActorConfig.config: dict`).
    """
    from nautilus_trader.common.config import msgspec_encoding_hook

    settings = BreezySettings.from_env(_base_env())
    importable_config_payload = settings.json_primitives()

    re_encoded = msgspec.json.encode(importable_config_payload, enc_hook=msgspec_encoding_hook)
    recovered = BreezySettings.parse(re_encoded)

    assert recovered == settings


# ---------------------------------------------------------------------------
# RED (rewrite) 3 -- positivity violations raise via native constrained types
# ---------------------------------------------------------------------------


def _valid_settings_mapping() -> dict[str, object]:
    settings = BreezySettings.from_env(_base_env())
    return dict(msgspec.json.decode(settings.json()))


@pytest.mark.parametrize(
    "field_name",
    ["poll_interval_ns", "poll_stagger_ns", "catalog_io_workers", "parse_timeout_s"],
)
def test_negative_value_for_constrained_field_raises_via_native_constrained_type(
    field_name: str,
) -> None:
    """msgspec `Annotated`/`Meta` constraints (the native `PositiveInt` /
    `NonNegativeInt` / `PositiveFloat` types) are enforced on msgspec's
    decode path, not on direct `__init__` construction (verified empirically
    against msgspec 0.21.1 -- see the module docstring). `.parse()` is the
    decode path, so this is where the constraint violation must surface.
    """
    data = _valid_settings_mapping()
    data[field_name] = -1

    with pytest.raises(msgspec.ValidationError):
        BreezySettings.parse(msgspec.json.encode(data))


def test_zero_poll_interval_raises_via_native_constrained_type() -> None:
    data = _valid_settings_mapping()
    data["poll_interval_ns"] = 0

    with pytest.raises(msgspec.ValidationError):
        BreezySettings.parse(msgspec.json.encode(data))


def test_zero_catalog_io_workers_raises_via_native_constrained_type() -> None:
    data = _valid_settings_mapping()
    data["catalog_io_workers"] = 0

    with pytest.raises(msgspec.ValidationError):
        BreezySettings.parse(msgspec.json.encode(data))


def test_wrong_typed_field_via_the_sanctioned_from_mapping_entry_point_raises() -> None:
    """Direct `BreezySettings(...)` construction does not validate field
    types or `Meta` constraints (msgspec only validates on decode/convert --
    verified empirically). `from_mapping` is the sanctioned, type-safe
    construction entry point `from_env` itself routes through, built on
    `msgspec.convert(..., strict=True)` so the same decode-path validation
    `.parse()` uses actually runs for values that never passed through raw
    JSON bytes.
    """
    data = _valid_settings_mapping()
    data["poll_interval_ns"] = "not-an-int"

    with pytest.raises(msgspec.ValidationError):
        BreezySettings.from_mapping(data)


def test_from_mapping_accepts_a_fully_valid_mapping() -> None:
    data = _valid_settings_mapping()

    settings = BreezySettings.from_mapping(data)

    assert settings.sites == ALL_SITE_PAIRS


# ---------------------------------------------------------------------------
# RED (rewrite) 4 -- the freshness cross-field invariant still raises
# ---------------------------------------------------------------------------


def test_freshness_cross_field_invariant_raises_on_direct_construction() -> None:
    """Genuinely ours -- no native `Meta` constraint expresses a cross-field
    relationship, so this remains a `__post_init__` check, and `__post_init__`
    runs on direct construction (verified empirically for frozen msgspec
    `Struct`s), so this must raise here too.
    """
    with pytest.raises(SettingsError, match="freshness_blocked_after_ns"):
        BreezySettings(
            sites=ALL_SITE_PAIRS,
            catalog_base=Path("/tmp/breezy-test/catalog"),
            state_store_path=Path("/tmp/breezy-test/state.json"),
            poll_interval_ns=300_000_000_000,
            poll_stagger_ns=30_000_000_000,
            user_agent_contact="breezy-weather-ingest/0.1 (+mailto:breezy@jonathan.vc)",
            freshness_degraded_after_ns=100,
            freshness_blocked_after_ns=100,
            parse_timeout_s=0.25,
            catalog_io_workers=2,
        )


def test_freshness_cross_field_invariant_raises_via_parse() -> None:
    """`__post_init__` also runs on the decode path (verified empirically),
    so the same invariant must raise there too.
    """
    data = _valid_settings_mapping()
    data["freshness_degraded_after_ns"] = 100
    data["freshness_blocked_after_ns"] = 100

    with pytest.raises(SettingsError, match="freshness_blocked_after_ns"):
        BreezySettings.parse(msgspec.json.encode(data))


# ---------------------------------------------------------------------------
# RED (rewrite) 5 -- SettingsError is catchable as InvalidConfiguration
# ---------------------------------------------------------------------------


def test_settings_error_is_a_subclass_of_invalid_configuration() -> None:
    assert issubclass(SettingsError, InvalidConfiguration)


def test_settings_error_from_from_env_is_catchable_as_invalid_configuration() -> None:
    env = _base_env()
    del env["BREEZY_USER_AGENT"]

    with pytest.raises(InvalidConfiguration):
        BreezySettings.from_env(env)


def test_freshness_cross_field_settings_error_is_catchable_as_invalid_configuration() -> None:
    with pytest.raises(InvalidConfiguration):
        BreezySettings(
            sites=ALL_SITE_PAIRS,
            catalog_base=Path("/tmp/breezy-test/catalog"),
            state_store_path=Path("/tmp/breezy-test/state.json"),
            poll_interval_ns=300_000_000_000,
            poll_stagger_ns=30_000_000_000,
            user_agent_contact="breezy-weather-ingest/0.1 (+mailto:breezy@jonathan.vc)",
            freshness_degraded_after_ns=100,
            freshness_blocked_after_ns=50,
            parse_timeout_s=0.25,
            catalog_io_workers=2,
        )


# ---------------------------------------------------------------------------
# RED (rewrite) 6 -- unknown fields are rejected (forbid_unknown_fields)
# ---------------------------------------------------------------------------


def test_parse_rejects_an_unknown_field() -> None:
    data = _valid_settings_mapping()
    data["totally_bogus_field"] = "surprise"

    with pytest.raises(msgspec.ValidationError, match="unknown field"):
        BreezySettings.parse(msgspec.json.encode(data))


def test_from_mapping_rejects_an_unknown_field() -> None:
    data = _valid_settings_mapping()
    data["totally_bogus_field"] = "surprise"

    with pytest.raises(msgspec.ValidationError, match="unknown field"):
        BreezySettings.from_mapping(data)
