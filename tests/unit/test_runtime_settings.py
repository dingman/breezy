"""Tests for `breezy.runtime.settings.load_settings`.

`load_settings` takes an injected `env: Mapping[str, str]` (defaulting to
`os.environ`) so the whole surface is testable without monkeypatching the
real process environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.runtime.settings import (
    BreezyRuntimeSettings,
    SettingsError,
    load_settings,
)

MINIMAL_ENV = {
    "BREEZY_SITES": "polymarket_us:NYC",
    "BREEZY_CATALOG_BASE": "/data/breezy",
}


def _env(**overrides: str) -> dict[str, str]:
    merged = dict(MINIMAL_ENV)
    merged.update(overrides)
    return merged


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_load_settings_returns_breezy_runtime_settings() -> None:
    settings = load_settings(_env())
    assert isinstance(settings, BreezyRuntimeSettings)


def test_default_trader_id() -> None:
    settings = load_settings(_env())
    assert settings.trader_id == "BREEZY-001"


def test_default_poll_interval_seconds() -> None:
    settings = load_settings(_env())
    assert settings.poll_interval_seconds == 300


def test_default_parse_timeout_ms() -> None:
    settings = load_settings(_env())
    assert settings.parse_timeout_ms == 250


def test_default_log_level() -> None:
    settings = load_settings(_env())
    assert settings.log_level == "INFO"


def test_default_check_proxy_env_is_true() -> None:
    settings = load_settings(_env())
    assert settings.check_proxy_env is True


def test_default_registry_path_is_none() -> None:
    settings = load_settings(_env())
    assert settings.registry_path is None


def test_default_state_db_path_derived_from_catalog_base() -> None:
    settings = load_settings(_env(BREEZY_CATALOG_BASE="/data/breezy"))
    assert settings.state_db_path == Path("/data/breezy") / "state" / "breezy-state.sqlite3"


def test_catalog_base_is_path() -> None:
    settings = load_settings(_env())
    assert settings.catalog_base == Path("/data/breezy")
    assert isinstance(settings.catalog_base, Path)


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_override_trader_id() -> None:
    settings = load_settings(_env(BREEZY_TRADER_ID="BREEZY-PROD"))
    assert settings.trader_id == "BREEZY-PROD"


def test_override_poll_interval_seconds() -> None:
    settings = load_settings(_env(BREEZY_POLL_INTERVAL_SECONDS="60"))
    assert settings.poll_interval_seconds == 60


def test_override_parse_timeout_ms() -> None:
    settings = load_settings(_env(BREEZY_PARSE_TIMEOUT_MS="500"))
    assert settings.parse_timeout_ms == 500


def test_override_log_level() -> None:
    settings = load_settings(_env(BREEZY_LOG_LEVEL="DEBUG"))
    assert settings.log_level == "DEBUG"


def test_override_registry_path() -> None:
    settings = load_settings(_env(BREEZY_REGISTRY_PATH="/tmp/fixture-sites.toml"))
    assert settings.registry_path == Path("/tmp/fixture-sites.toml")


def test_explicit_state_db_path_override_wins_over_derivation() -> None:
    settings = load_settings(
        _env(
            BREEZY_CATALOG_BASE="/data/breezy",
            BREEZY_STATE_DB="/var/lib/breezy/state.sqlite3",
        )
    )
    assert settings.state_db_path == Path("/var/lib/breezy/state.sqlite3")


def test_check_proxy_env_flips_false_when_allow_proxy_env_is_1() -> None:
    settings = load_settings(_env(BREEZY_ALLOW_PROXY_ENV="1"))
    assert settings.check_proxy_env is False


@pytest.mark.parametrize("value", ["0", "", "false", "no"])
def test_check_proxy_env_stays_true_for_non_1_values(value: str) -> None:
    settings = load_settings(_env(BREEZY_ALLOW_PROXY_ENV=value))
    assert settings.check_proxy_env is True


# ---------------------------------------------------------------------------
# BREEZY_SITES parsing
# ---------------------------------------------------------------------------


def test_sites_single_pair_parses_to_tuple_of_tuples() -> None:
    settings = load_settings(_env(BREEZY_SITES="polymarket_us:NYC"))
    assert settings.sites == (("polymarket_us", "NYC"),)


def test_sites_multiple_pairs_parse_in_order() -> None:
    settings = load_settings(_env(BREEZY_SITES="polymarket_us:NYC,polymarket_us:SFO"))
    assert settings.sites == (("polymarket_us", "NYC"), ("polymarket_us", "SFO"))


def test_sites_whitespace_around_entries_is_tolerated() -> None:
    settings = load_settings(_env(BREEZY_SITES=" polymarket_us:NYC , polymarket_us:SFO "))
    assert settings.sites == (("polymarket_us", "NYC"), ("polymarket_us", "SFO"))


# ---------------------------------------------------------------------------
# Required fields missing
# ---------------------------------------------------------------------------


def test_missing_sites_raises_settings_error() -> None:
    env = dict(MINIMAL_ENV)
    del env["BREEZY_SITES"]
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(env)


def test_missing_catalog_base_raises_settings_error() -> None:
    env = dict(MINIMAL_ENV)
    del env["BREEZY_CATALOG_BASE"]
    with pytest.raises(SettingsError, match="BREEZY_CATALOG_BASE"):
        load_settings(env)


def test_empty_sites_value_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(_env(BREEZY_SITES=""))


def test_sites_with_only_whitespace_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(_env(BREEZY_SITES="   "))


# ---------------------------------------------------------------------------
# Malformed BREEZY_SITES
# ---------------------------------------------------------------------------


def test_sites_entry_without_colon_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(_env(BREEZY_SITES="polymarket_us_NYC"))


def test_sites_entry_with_two_colons_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(_env(BREEZY_SITES="polymarket_us:NYC:extra"))


def test_sites_entry_with_blank_venue_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(_env(BREEZY_SITES=":NYC"))


def test_sites_entry_with_blank_city_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(_env(BREEZY_SITES="polymarket_us:"))


def test_sites_duplicate_pair_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(_env(BREEZY_SITES="polymarket_us:NYC,polymarket_us:NYC"))


def test_sites_trailing_comma_yields_blank_entry_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(_env(BREEZY_SITES="polymarket_us:NYC,"))


# ---------------------------------------------------------------------------
# Integer validation
# ---------------------------------------------------------------------------


def test_non_integer_poll_interval_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_POLL_INTERVAL_SECONDS"):
        load_settings(_env(BREEZY_POLL_INTERVAL_SECONDS="not-a-number"))


def test_non_positive_poll_interval_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_POLL_INTERVAL_SECONDS"):
        load_settings(_env(BREEZY_POLL_INTERVAL_SECONDS="0"))


def test_negative_poll_interval_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_POLL_INTERVAL_SECONDS"):
        load_settings(_env(BREEZY_POLL_INTERVAL_SECONDS="-5"))


def test_non_integer_parse_timeout_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_PARSE_TIMEOUT_MS"):
        load_settings(_env(BREEZY_PARSE_TIMEOUT_MS="250.5"))


def test_non_positive_parse_timeout_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_PARSE_TIMEOUT_MS"):
        load_settings(_env(BREEZY_PARSE_TIMEOUT_MS="0"))


# ---------------------------------------------------------------------------
# Frozen / slots / immutability
# ---------------------------------------------------------------------------


def test_settings_is_frozen() -> None:
    settings = load_settings(_env())
    with pytest.raises(AttributeError):
        settings.trader_id = "MUTATED"  # type: ignore[misc]


def test_settings_has_no_dict_slots_only() -> None:
    settings = load_settings(_env())
    with pytest.raises(AttributeError):
        _ = settings.__dict__  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# BREEZY_USER_AGENT must never be read by this module
# ---------------------------------------------------------------------------


def test_settings_never_reads_breezy_user_agent_env_var() -> None:
    """`BREEZY_USER_AGENT` is owned exclusively by `breezy.ingest.http`.

    A second reader here would be a second, competing policy for the same
    env var -- this module must not look at it at all, even if it is set.
    """

    class TrackingEnv(dict[str, str]):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            self.accessed_keys: set[str] = set()

        def __getitem__(self, key: str) -> str:
            self.accessed_keys.add(key)
            return super().__getitem__(key)

        def get(self, key: str, default: object = None) -> object:  # type: ignore[override]
            self.accessed_keys.add(key)
            return super().get(key, default)

        def __contains__(self, key: object) -> bool:
            if isinstance(key, str):
                self.accessed_keys.add(key)
            return super().__contains__(key)

    env = TrackingEnv(_env(BREEZY_USER_AGENT="some-agent-string"))
    load_settings(env)
    assert "BREEZY_USER_AGENT" not in env.accessed_keys


def test_load_settings_env_parameter_is_injected_not_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting `BREEZY_TRADER_ID` in real `os.environ` must not leak in when
    an explicit `env` mapping is supplied -- the whole surface is testable
    without monkeypatching the real process environment.
    """
    monkeypatch.setenv("BREEZY_TRADER_ID", "FROM-REAL-OS-ENVIRON")
    settings = load_settings(_env())
    assert settings.trader_id == "BREEZY-001"
