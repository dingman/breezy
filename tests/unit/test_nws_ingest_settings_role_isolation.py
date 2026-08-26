"""Regression guard: venue configuration is NOT a startup requirement for NWS ingest.

Why this file exists, separately from ``test_runtime_settings.py``
------------------------------------------------------------------
``BreezyRuntimeSettings`` / ``load_settings`` is the startup path of the LIVE
weather-ingestion process (``breezy-nws-ingest.service``). A change that made
seven Polymarket.us venue variables unconditionally required on that path
turned every restart of a *running* collector into a startup failure -- a
failure invisible for as long as the old process kept running, and total the
moment it did not. This repo has already lost one data catalog; a collector
that cannot restart is the same class of loss.

The rule this file pins is a ROLE boundary, not a field list:

    The weather-ingestion role must load its settings from an environment
    that contains no venue configuration whatsoever.

The quote-tape recorder is a DIFFERENT role with its own loader
(:func:`breezy.runtime.settings.load_quote_tape_settings`), validated strictly
on its own terms. Its variables are tested there, and must never migrate back
onto the shared type.

The assertions below are deliberately expressed as "the ingest process starts",
not as "the dataclass has N fields": a future refactor is free to reshape the
type, and is not free to make the collector unstartable.
"""

from __future__ import annotations

import pytest

from breezy.runtime.settings import load_settings

#: The environment a correctly-provisioned NWS ingestion host actually carries.
#: Deliberately written out in full rather than imported from another test
#: module, so a later edit to a shared ``MINIMAL_ENV`` cannot quietly
#: reintroduce a venue variable here and hide the regression.
NWS_INGEST_ONLY_ENV: dict[str, str] = {
    "BREEZY_SITES": "polymarket_us:NYC,polymarket_us:MDW",
    "BREEZY_CATALOG_BASE": "/data/breezy",
}

#: Every venue variable that must stay OPTIONAL for this role. Named
#: individually so that adding an eighth one without thinking fails a review,
#: not a production restart.
VENUE_ONLY_VARS: tuple[str, ...] = (
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG",
    "POLYMARKET_US_API_BASE",
    "POLYMARKET_US_GATEWAY_BASE",
    "POLYMARKET_US_WS_URL",
    "POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS",
    "POLYMARKET_US_USER_AGENT",
    "POLYMARKET_US_SIGNING_VARIANT",
)


def test_nws_ingest_settings_load_with_no_venue_configuration_at_all() -> None:
    """The collector starts on a host that has never heard of Polymarket.us."""
    settings = load_settings(NWS_INGEST_ONLY_ENV)

    assert settings.sites == (("polymarket_us", "NYC"), ("polymarket_us", "MDW"))
    assert str(settings.catalog_base) == "/data/breezy"


@pytest.mark.parametrize("name", VENUE_ONLY_VARS)
def test_no_single_venue_variable_can_block_nws_ingest_startup(name: str) -> None:
    """Removing any one venue variable from a fully-provisioned host is harmless.

    Starts from an environment that HAS every venue variable set (the
    quote-tape host), removes exactly one, and requires the ingest role to
    still start. This catches the partial-provisioning case that a
    "nothing set at all" test does not.
    """
    env = dict(NWS_INGEST_ONLY_ENV)
    env.update({var: "placeholder" for var in VENUE_ONLY_VARS})
    del env[name]

    assert load_settings(env).sites == (("polymarket_us", "NYC"), ("polymarket_us", "MDW"))


def test_venue_variables_are_ignored_rather_than_absorbed_by_the_ingest_role() -> None:
    """A venue variable present in the ingest environment changes nothing.

    Behavioural statement of the role boundary: two environments differing
    only by venue configuration must produce identical ingest settings. If a
    venue value ever starts leaking onto the shared type, this fails.
    """
    without = load_settings(NWS_INGEST_ONLY_ENV)
    with_venue = load_settings(
        {**NWS_INGEST_ONLY_ENV, **{var: "placeholder" for var in VENUE_ONLY_VARS}}
    )

    assert without == with_venue
