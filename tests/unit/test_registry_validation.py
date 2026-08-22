"""Load-time validation tests for the settlement-site registry loader.

The registry must fail loudly at load time rather than load with a hole in
it. Each malformed fixture under tests/fixtures/registry/ exercises exactly
one validation guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.registry.sites import RegistryError, SiteNotFoundError, load_registry

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "registry"


def test_loader_rejects_missing_required_field() -> None:
    with pytest.raises(RegistryError, match="issuing_office"):
        load_registry(FIXTURES_DIR / "missing_required_field.toml")


def test_loader_rejects_missing_iana_tz() -> None:
    # iana_tz is still required at load time even though no accessor
    # surfaces it -- validation and exposure are independent concerns.
    with pytest.raises(RegistryError, match="iana_tz"):
        load_registry(FIXTURES_DIR / "missing_iana_tz.toml")


def test_loader_rejects_uncompilable_regex() -> None:
    with pytest.raises(RegistryError, match="body_header_regex"):
        load_registry(FIXTURES_DIR / "uncompilable_regex.toml")


def test_loader_rejects_empty_never_substitute() -> None:
    with pytest.raises(RegistryError, match="never_substitute"):
        load_registry(FIXTURES_DIR / "empty_never_substitute.toml")


def test_loader_rejects_settlement_eligible_not_false() -> None:
    with pytest.raises(RegistryError, match="settlement_eligible"):
        load_registry(FIXTURES_DIR / "settlement_eligible_true.toml")


def test_loader_rejects_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_registry(FIXTURES_DIR / "does_not_exist.toml")


def test_loader_rejects_missing_open_meteo_table() -> None:
    with pytest.raises(RegistryError, match="open_meteo"):
        load_registry(FIXTURES_DIR / "missing_open_meteo.toml")


def test_loader_rejects_missing_registry_version() -> None:
    with pytest.raises(RegistryError, match="registry_version"):
        load_registry(FIXTURES_DIR / "missing_registry_version.toml")


def test_loader_rejects_missing_sites_table() -> None:
    with pytest.raises(RegistryError, match="sites"):
        load_registry(FIXTURES_DIR / "missing_sites_table.toml")


def test_loader_rejects_venue_with_no_sites() -> None:
    with pytest.raises(RegistryError, match="polymarket_us"):
        load_registry(FIXTURES_DIR / "venue_with_no_sites.toml")


def test_loader_rejects_site_that_is_not_a_table() -> None:
    with pytest.raises(RegistryError, match="not a table"):
        load_registry(FIXTURES_DIR / "site_not_a_table.toml")


def test_nonderivable_valid_fixture_loads_cleanly() -> None:
    registry = load_registry(FIXTURES_DIR / "nonderivable_valid.toml")
    assert registry.registry_version == "test-1"


def test_enrichment_accessor_raises_for_unknown_pair() -> None:
    registry = load_registry(FIXTURES_DIR / "nonderivable_valid.toml")
    with pytest.raises(SiteNotFoundError):
        registry.enrichment_coordinates("polymarket_us", "NOPE")
    with pytest.raises(SiteNotFoundError):
        registry.enrichment_coordinates("kalshi", "TST")
