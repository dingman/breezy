"""Tests for `breezy.runtime.settings.load_settings`.

`load_settings` takes an injected `env: Mapping[str, str]` (defaulting to
`os.environ`) so the whole surface is testable without monkeypatching the
real process environment.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from breezy.registry.sites import default_registry
from breezy.runtime.settings import (
    BreezyRuntimeSettings,
    SettingsError,
    derive_disk_thresholds,
    load_quote_tape_settings,
    load_settings,
    probe_total_bytes,
)

MINIMAL_ENV = {
    "BREEZY_SITES": "polymarket_us:NYC",
    "BREEZY_CATALOG_BASE": "/data/breezy",
}


def _env(**overrides: str) -> dict[str, str]:
    merged = dict(MINIMAL_ENV)
    merged.update(overrides)
    return merged


def _one_site_registry_toml() -> str:
    """A registry holding ONE site, built from the packaged file's own NYC row.

    Sliced out of `sites.toml` rather than retyped so the fixture cannot
    drift from the settlement truth it is standing in for.
    """
    from breezy.registry.sites import DEFAULT_REGISTRY_PATH

    source = DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8")
    version = next(
        line for line in source.splitlines() if line.startswith("registry_version")
    )
    _, _, rest = source.partition("[sites.polymarket_us.NYC]")
    body, _, _ = rest.partition("[sites.polymarket_us.SFO]")
    body = body.rsplit("# ---", 1)[0]
    return f"{version}\n\n[sites.polymarket_us.NYC]{body}"




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
# Log level validation
# ---------------------------------------------------------------------------


def test_unrecognized_log_level_raises_settings_error() -> None:
    with pytest.raises(SettingsError, match="BREEZY_LOG_LEVEL"):
        load_settings(_env(BREEZY_LOG_LEVEL="VERBOSE"))


@pytest.mark.parametrize(
    "raw",
    ["OFF", "TRACE", "DEBUG", "INFO", "WARNING", "ERROR"],
)
def test_each_nautilus_supported_log_level_is_accepted(raw: str) -> None:
    settings = load_settings(_env(BREEZY_LOG_LEVEL=raw))
    assert settings.log_level == raw


def test_lowercase_log_level_is_normalized_to_uppercase() -> None:
    settings = load_settings(_env(BREEZY_LOG_LEVEL="debug"))
    assert settings.log_level == "DEBUG"


def test_unsupported_python_logging_alias_raises_settings_error() -> None:
    """`WARN`/`CRITICAL` are valid `logging` module aliases but are NOT in
    NautilusTrader's `LogLevel` (`OFF`/`TRACE`/`DEBUG`/`INFO`/`WARNING`/
    `ERROR`, verified against the installed `nautilus_pyo3.LogLevel`), so
    they must fail fast here rather than reach Nautilus and fail there.
    """
    with pytest.raises(SettingsError, match="BREEZY_LOG_LEVEL"):
        load_settings(_env(BREEZY_LOG_LEVEL="WARN"))


def test_nws_runbook_matches_runtime_environment_contract() -> None:
    runbook = Path("docs/core/RUNBOOK_NWS_COLLECTION.md").read_text()
    required_table = runbook.split("**Required:**", maxsplit=1)[1].split(
        "**Optional:**", maxsplit=1
    )[0]
    optional_table = runbook.split("**Optional:**", maxsplit=1)[1].split(
        "### 1a.", maxsplit=1
    )[0]

    assert "| `BREEZY_USER_AGENT` |" in required_table
    assert "| `BREEZY_USER_AGENT` |" not in optional_table
    assert "startup fails exit 2" in required_table
    assert "`OFF`, `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`" in optional_table
    log_level_row = next(
        line for line in optional_table.splitlines() if line.startswith("| `BREEZY_LOG_LEVEL` |")
    )
    log_level_columns = [column.strip() for column in log_level_row.strip("|").split("|")]
    assert log_level_columns[2] == "`OFF`, `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`"
    assert "CRITICAL" not in log_level_columns[2]
    assert "Does NOT bridge stdlib `logging` to Nautilus" not in runbook
    assert "stdlib `logging` records are bridged to Nautilus" in optional_table


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
        _ = settings.__dict__


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
            super().__init__(*args, **kwargs)
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


def test_load_settings_env_parameter_is_injected_not_os_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting `BREEZY_TRADER_ID` in real `os.environ` must not leak in when
    an explicit `env` mapping is supplied -- the whole surface is testable
    without monkeypatching the real process environment.
    """
    monkeypatch.setenv("BREEZY_TRADER_ID", "FROM-REAL-OS-ENVIRON")
    settings = load_settings(_env())
    assert settings.trader_id == "BREEZY-001"


# ---------------------------------------------------------------------------
# BREEZY_HEALTH_SNAPSHOT_DIR (WI-12 wiring)
# ---------------------------------------------------------------------------


def test_health_snapshot_dir_defaults_to_none() -> None:
    """Unset is VALID: the feature is simply off and no artifact is dropped
    in whatever directory the process happened to start in.
    """
    settings = load_settings(_env())
    assert settings.health_snapshot_dir is None


def test_health_snapshot_dir_is_parsed_when_set() -> None:
    settings = load_settings(_env(BREEZY_HEALTH_SNAPSHOT_DIR="/var/lib/breezy/health"))
    assert settings.health_snapshot_dir == Path("/var/lib/breezy/health")


def test_blank_health_snapshot_dir_is_rejected() -> None:
    with pytest.raises(SettingsError, match="BREEZY_HEALTH_SNAPSHOT_DIR"):
        load_settings(_env(BREEZY_HEALTH_SNAPSHOT_DIR="   "))


def test_relative_health_snapshot_dir_is_rejected() -> None:
    """A relative path resolves against the process CWD, which under systemd
    is not a property any operator controls -- the snapshot would land
    somewhere nobody monitors, and the runbook's "stale file means the
    process is dead" check would read a file that never existed.
    """
    with pytest.raises(SettingsError, match="BREEZY_HEALTH_SNAPSHOT_DIR"):
        load_settings(_env(BREEZY_HEALTH_SNAPSHOT_DIR="health"))


def test_health_snapshot_dir_with_a_nul_byte_is_rejected() -> None:
    with pytest.raises(SettingsError, match="BREEZY_HEALTH_SNAPSHOT_DIR"):
        load_settings(_env(BREEZY_HEALTH_SNAPSHOT_DIR="/var/lib/bre\x00ezy"))


# ---------------------------------------------------------------------------
# G-19 B4 -- BREEZY_SITES is an OVERRIDE, not a required venue fact
# ---------------------------------------------------------------------------


def test_the_runtime_starts_with_none_of_the_derivable_env_vars_set() -> None:
    """G-19's deliverable: no human recites a venue fact to start the bot.

    ``BREEZY_CATALOG_BASE`` stays required -- it is a deploy path, an (A)
    enablement ceiling, not something the venue can tell us.
    """
    settings = load_settings({"BREEZY_CATALOG_BASE": "/data/breezy"})

    assert settings.sites == default_registry().pairs()
    assert settings.poll_interval_seconds == 300


def test_unset_sites_defaults_to_every_registered_site() -> None:
    env = dict(MINIMAL_ENV)
    del env["BREEZY_SITES"]

    assert load_settings(env).sites == default_registry().pairs()


def test_the_derived_default_is_exactly_the_five_polymarket_us_cities() -> None:
    env = dict(MINIMAL_ENV)
    del env["BREEZY_SITES"]

    sites = load_settings(env).sites

    assert {city for _, city in sites} == {"NYC", "SFO", "MIA", "MDW", "LAX"}
    assert all(venue == "polymarket_us" for venue, _ in sites)


def test_an_explicit_sites_value_still_narrows_the_run() -> None:
    """The override survives: a staged rollout stays an explicit choice."""
    settings = load_settings(_env(BREEZY_SITES="polymarket_us:NYC"))

    assert settings.sites == (("polymarket_us", "NYC"),)
    assert len(settings.sites) < len(default_registry().pairs())


def test_a_blank_sites_value_is_still_refused() -> None:
    """Unset means "derive"; blank means an operator botched the value."""
    with pytest.raises(SettingsError, match="BREEZY_SITES"):
        load_settings(_env(BREEZY_SITES=""))


def test_the_derived_default_honours_breezy_registry_path(tmp_path: Path) -> None:
    """The safety property: derived sites come from the registry in force.

    A deployment pointed at a narrower registry derives the narrower set --
    it never falls back to the packaged five.
    """
    fixture = tmp_path / "sites.toml"
    fixture.write_text(
        _one_site_registry_toml(),
        encoding="utf-8",
    )
    env = dict(MINIMAL_ENV)
    del env["BREEZY_SITES"]
    env["BREEZY_REGISTRY_PATH"] = str(fixture)

    assert load_settings(env).sites == (("polymarket_us", "NYC"),)


def test_a_broken_registry_path_fails_as_a_settings_error(tmp_path: Path) -> None:
    """Loudly, naming the variable -- never a bare FileNotFoundError."""
    env = dict(MINIMAL_ENV)
    del env["BREEZY_SITES"]
    env["BREEZY_REGISTRY_PATH"] = str(tmp_path / "does-not-exist.toml")

    with pytest.raises(SettingsError, match="BREEZY_REGISTRY_PATH"):
        load_settings(env)


def test_the_registry_is_not_read_when_sites_is_set(tmp_path: Path) -> None:
    """The override path must not pay for -- or fail on -- a registry read."""
    env = dict(MINIMAL_ENV)
    env["BREEZY_REGISTRY_PATH"] = str(tmp_path / "does-not-exist.toml")

    assert load_settings(env).sites == (("polymarket_us", "NYC"),)


# ---------------------------------------------------------------------------
# G-19 B11 -- BREEZY_POLL_INTERVAL_SECONDS
# ---------------------------------------------------------------------------


def test_the_poll_interval_default_cites_why_it_is_not_derived() -> None:
    """Pushback, pinned: CLI issuance cadence does NOT determine this value.

    The cadence the repo holds is "two issuances per day per site"
    (``ingest/product_index.py:72``). A poll interval is a DETECTION-LATENCY
    choice bounded by api.weather.gov politeness, not a function of that
    cadence -- any formula yielding 300 would be reverse-engineered. The
    constant therefore stays, but it must carry the citation so the next
    reader does not re-open the question.
    """
    source = Path("src/breezy/runtime/settings.py").read_text(encoding="utf-8")
    head, _, _ = source.partition("_DEFAULT_POLL_INTERVAL_SECONDS = 300")

    assert "product_index.py" in head
    assert "two issuances per day" in head
    assert "DETECTION-LATENCY" in head


# ---------------------------------------------------------------------------
# G-19 B10 -- the four tape disk thresholds are DERIVED from disk state
# ---------------------------------------------------------------------------

_GIB = 1024**3
_MIB = 1024**2

#: Simulated volumes: a laptop partition, a small VPS, a normal server
#: volume, a big array, and a deliberately absurd one at each end.
_SIMULATED_TOTALS = (
    64 * _MIB,
    512 * _MIB,
    20 * _GIB,
    500 * _GIB,
    4 * 1024 * _GIB,
    128 * 1024 * _GIB,
)


@pytest.mark.parametrize("total", _SIMULATED_TOTALS)
def test_derived_thresholds_are_ordered_and_positive(total: int) -> None:
    thresholds = derive_disk_thresholds(total)

    assert thresholds.min_free_bytes_error > 0
    assert thresholds.min_free_bytes_error < thresholds.min_free_bytes_warning
    assert thresholds.max_file_bytes_warning > 0
    assert thresholds.max_file_bytes_error > thresholds.max_file_bytes_warning


@pytest.mark.parametrize("total", _SIMULATED_TOTALS)
def test_derived_thresholds_can_never_be_permanently_tripped(total: int) -> None:
    """A threshold at or above the whole volume alarms forever and is ignored.

    That is the specific way a derived default renders an ALERT-ONLY monitor
    useless, so it is asserted at every simulated size.
    """
    thresholds = derive_disk_thresholds(total)

    assert thresholds.min_free_bytes_warning < total
    assert thresholds.max_file_bytes_error < total


@pytest.mark.parametrize("total", _SIMULATED_TOTALS)
def test_derived_thresholds_leave_real_headroom_before_the_volume_fills(
    total: int,
) -> None:
    """The other failure mode: an alarm that never precedes ENOSPC.

    The operability property, stated in the tape's own units: when the
    free-space WARNING trips, at least one more warning-sized daily file must
    still fit before the ERROR floor. An alarm that leaves less than one day
    of headroom is an alarm nobody can act on.
    """
    thresholds = derive_disk_thresholds(total)

    headroom = thresholds.min_free_bytes_warning - thresholds.min_free_bytes_error
    assert headroom >= thresholds.max_file_bytes_warning
    assert thresholds.min_free_bytes_error >= 1024**2


def test_a_very_small_volume_scales_the_thresholds_down_rather_than_alarming() -> None:
    """A 64 MiB volume must not inherit a gibibyte-scale free-space floor."""
    thresholds = derive_disk_thresholds(64 * _MIB)

    assert thresholds.min_free_bytes_warning <= 64 * _MIB // 4
    assert thresholds.min_free_bytes_error < thresholds.min_free_bytes_warning


def test_a_very_large_volume_caps_the_thresholds_rather_than_alarming() -> None:
    """On a 128 TiB array, 5% free is 6.5 TiB -- an alarm nobody can satisfy."""
    thresholds = derive_disk_thresholds(128 * 1024 * _GIB)

    assert thresholds.min_free_bytes_warning <= 64 * _GIB
    assert thresholds.max_file_bytes_error <= 32 * _GIB


def test_a_zero_or_negative_volume_is_refused_rather_than_yielding_zero() -> None:
    for total in (0, -1):
        with pytest.raises(SettingsError, match="disk"):
            derive_disk_thresholds(total)


TAPE_ONLY_ENV = {"BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG": "/srv/breezy/venue/polymarket_us"}


def _fixed_total(total: int) -> Callable[[Path], int]:
    def probe(_path: Path) -> int:
        return total

    return probe


def test_the_recorder_starts_with_only_its_deploy_path_configured() -> None:
    """G-19's deliverable for the recorder role: one (A) value, nothing else."""
    settings = load_quote_tape_settings(
        TAPE_ONLY_ENV, total_bytes_probe=_fixed_total(500 * _GIB)
    )

    expected = derive_disk_thresholds(500 * _GIB)
    assert settings.min_free_bytes_warning == expected.min_free_bytes_warning
    assert settings.min_free_bytes_error == expected.min_free_bytes_error
    assert settings.max_file_bytes_warning == expected.max_file_bytes_warning
    assert settings.max_file_bytes_error == expected.max_file_bytes_error


@pytest.mark.parametrize("total", _SIMULATED_TOTALS)
def test_the_recorder_derives_a_usable_monitor_at_every_simulated_size(
    total: int,
) -> None:
    settings = load_quote_tape_settings(TAPE_ONLY_ENV, total_bytes_probe=_fixed_total(total))

    assert 0 < settings.min_free_bytes_error < settings.min_free_bytes_warning < total
    assert 0 < settings.max_file_bytes_warning < settings.max_file_bytes_error < total


def test_each_threshold_remains_an_operator_override() -> None:
    settings = load_quote_tape_settings(
        {
            **TAPE_ONLY_ENV,
            "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_WARNING": str(20 * _GIB),
            "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_ERROR": str(10 * _GIB),
            "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_WARNING": str(400 * _GIB),
            "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_ERROR": str(500 * _GIB),
        },
        total_bytes_probe=_fixed_total(4 * 1024 * _GIB),
    )

    assert settings.min_free_bytes_warning == 20 * _GIB
    assert settings.min_free_bytes_error == 10 * _GIB
    assert settings.max_file_bytes_warning == 400 * _GIB
    assert settings.max_file_bytes_error == 500 * _GIB


def test_a_half_override_that_inverts_the_ordering_still_fails_loudly() -> None:
    """Overriding one of a pair against a derived sibling must not pass silently."""
    with pytest.raises(SettingsError, match="MIN_FREE_BYTES_ERROR"):
        load_quote_tape_settings(
            {
                **TAPE_ONLY_ENV,
                "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_ERROR": str(400 * _GIB),
            },
            total_bytes_probe=_fixed_total(500 * _GIB),
        )


def test_an_unprobeable_volume_fails_as_a_settings_error() -> None:
    def exploding_probe(_path: Path) -> int:
        raise OSError("no such device")

    with pytest.raises(SettingsError, match="QUOTE_TAPE_CATALOG"):
        load_quote_tape_settings(TAPE_ONLY_ENV, total_bytes_probe=exploding_probe)


def test_the_probe_is_asked_about_the_configured_tape_root() -> None:
    """The seam is "total bytes for this path" -- nothing else is injected."""
    seen: list[Path] = []

    def recording_probe(path: Path) -> int:
        seen.append(path)
        return 500 * _GIB

    load_quote_tape_settings(TAPE_ONLY_ENV, total_bytes_probe=recording_probe)

    assert seen == [Path("/srv/breezy/venue/polymarket_us")]


def test_the_default_probe_walks_up_to_the_nearest_existing_ancestor(
    tmp_path: Path,
) -> None:
    """The tape root does not exist at first start; the volume still does.

    Without the walk, ``shutil.disk_usage`` raises ``FileNotFoundError`` on a
    fresh host and the recorder cannot start at all.
    """
    root = tmp_path / "venue" / "polymarket_us" / "tape"
    assert not root.exists()

    assert probe_total_bytes(root) == shutil.disk_usage(tmp_path).total
