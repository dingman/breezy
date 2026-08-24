"""Live end-to-end proof that Breezy's ingestion path works against the
REAL ``api.weather.gov``, not just against fixtures.

Why this module exists
-----------------------
``docs/core/PROGRESS.md`` logs a standing lesson: the unit suite was fully
green TWICE while the real deployment was dead. Every other test in this
repo runs `HttpTransport` through `respx` (transport-layer mocking) with
`tests/conftest.py` blocking real sockets as a second line of defense --
which means nothing committed had ever proven that a real NWS response
still parses, still passes the registry's `body_header_regex`, and still
persists through the real composition root. This module is that proof.

Every test here is `@pytest.mark.live`:

* Deselected by default (`pyproject.toml`'s `addopts` runs `-m 'not live'`).
* SKIPPED with a clear reason if selected without `BREEZY_LIVE=1`
  (`tests/conftest.py::pytest_collection_modifyitems`).
* Exempted from the autouse socket-blocking fixture
  (`tests/conftest.py::_block_network_sockets`).

Robustness to real-world variance
----------------------------------
Nothing here asserts on a specific date, temperature, product UUID, or
discovery-list length -- NWS's real feed changes under us daily. Every
assertion is on STRUCTURE (a well-formed `ParsedCliProduct` / domain
record), STATION IDENTITY (`station == "NYC"`, the registry's
`body_header_regex` match), or NON-EMPTINESS (at least one persisted
record of each type).

Good-citizen network use
-------------------------
`test_full_e2e_poll_persists_a_climate_day_and_a_raw_product` pre-seeds the
product-integrity index with every discovery entry EXCEPT the single
newest one (a placeholder digest is enough -- `_undeduped` only checks
*presence*, see `breezy.ingest.nws_actor.NwsIngestActor._undeduped`), so
the real `poll_once()` fetches exactly one product body instead of the
whole multi-day backlog a genuinely fresh deployment would otherwise
re-ingest on first boot. Total live requests across this module: THREE
discovery-list GETs and two product-body GETs. The e2e test alone accounts
for two of the three discovery-list GETs -- its own preparatory
`_discover()` call (to learn which uuids already exist, see
`_seed_all_but_newest`) plus the real `NwsIngestActor.poll_once()` ->
`_poll_cycle()`'s own internal `fetch_discovery_list` call
(`breezy.ingest.nws_actor`) -- and the transport-level test above accounts
for the third.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path

import pytest
from nautilus_trader.live.node import TradingNode

from breezy.ingest import ProductIntegrityIndex
from breezy.ingest.http import DEFAULT_BASE_URL, HttpTransport
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.ingest.nws_envelope import DiscoveryEntry, parse_discovery_list, parse_product_envelope
from breezy.ingest.shared_state import DEFAULT_ALLOWED_HOSTS
from breezy.normalize.cli_parse import ParsedCliProduct, parse_cli_product
from breezy.persistence.catalog import (
    FilesystemLocality,
    FilesystemProbe,
    open_station_catalog,
    read_climate_days,
    read_raw_products,
)
from breezy.registry.sites import default_registry
from breezy.runtime.composition import build_ingest_node, ingest_runtime
from breezy.runtime.settings import BreezyRuntimeSettings
from breezy.runtime.sqlite_store import SqliteStateStore

pytestmark = pytest.mark.live

VENUE = "polymarket_us"
CITY = "NYC"

#: A real, identifiable contact -- NWS's own API etiquette guidance asks for
#: one, and an unidentified/default UA is the documented route into a 403
#: UA-trap block.
LIVE_USER_AGENT = "breezy-live-test/0.1 (+mailto:jon@gopoint.com)"


def _local_probe(path: Path) -> FilesystemProbe:
    """A filesystem probe that never touches a real mount.

    The writer-lock durability check this stands in for is orthogonal to
    what this module proves (real network I/O -> real parse -> real
    persistence); every other test in this repo that drives
    `ingest_runtime` injects the same kind of fixed-verdict probe.
    """
    return FilesystemProbe(
        path=str(path),
        mount_point="/",
        fs_type="ext4",
        locality=FilesystemLocality.LOCAL,
        detail="live-test probe",
    )


def _seed_all_but_newest(
    state_db_path: Path, entries: tuple[DiscoveryEntry, ...], *, except_uuid: str
) -> None:
    """Mark every entry except `except_uuid` as already-known.

    A one-time courtesy to `api.weather.gov`: without this, a poll against a
    genuinely fresh state db fetches every product body currently on the
    discovery list (order ~10-20 for NYC today), every live-test run.
    `ProductIntegrityIndex.known_digest` -- what `_undeduped` (SS3.4 Job 1)
    consults -- only checks PRESENCE, so a placeholder digest is sufficient;
    nothing here needs to (and does not) claim to know the real content.

    Opens its own `SqliteStateStore` against the SAME path `ingest_runtime`
    will open next, then closes it before returning -- so by the time
    `ingest_runtime` constructs its own store and runs
    `enforce_bootstrap_witness`, that store's constructing thread is (once
    again) the caller's, and the witness sees a "genuine first boot" (no
    witness key, no marker file yet), never a false tamper verdict.
    """
    store = SqliteStateStore(state_db_path)
    try:
        index = ProductIntegrityIndex(store=store, clock=time.time_ns)
        for entry in entries:
            if entry.product_uuid == except_uuid:
                continue
            placeholder_digest = hashlib.sha256(entry.product_uuid.encode("utf-8")).hexdigest()
            index.observe(entry.product_uuid, placeholder_digest)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# (a) Transport-level: real discovery + real product fetch, parsed cleanly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_discovery_list_and_newest_product_parse_cleanly_for_nyc() -> None:
    """`HttpTransport` against the real host, through the real parse path.

    Fetches NYC's real discovery list, then fetches and parses the NEWEST
    product on it. Asserts structure and station identity only -- see the
    module docstring for why no date/temperature/UUID is pinned.
    """
    registry = default_registry()
    site = registry.settlement_site(VENUE, CITY)

    transport = HttpTransport(
        allowed_hosts=DEFAULT_ALLOWED_HOSTS,
        clock=time.time_ns,
        base_url=DEFAULT_BASE_URL,
        user_agent=LIVE_USER_AGENT,
    )

    discovery = await transport.fetch_discovery_list(site.cli_location)
    assert discovery.status_code == 200
    assert discovery.text is not None

    payload = json.loads(discovery.text)
    entries = parse_discovery_list(payload)
    if len(entries) < 1:
        pytest.skip(
            "NYC's real discovery list returned zero entries; nothing to "
            "assert a parse against. This is a live-data availability gap, "
            "not a code defect -- re-run once NWS has published again."
        )

    newest = max(entries, key=lambda entry: entry.issuance_time_ns)
    assert newest.product_uuid

    product = await transport.fetch_product(newest.product_uuid)
    assert product.status_code == 200
    assert product.text is not None
    assert len(product.text) > 0

    # `GET /products/{id}` responds with a JSON envelope (`ProductEnvelope`),
    # not the bare CLI text -- the verbatim product body lives at its
    # `productText` field. `parse_product_envelope` is the one place that
    # extraction happens; see `breezy.ingest.nws_envelope`'s module docstring
    # for why this module never re-derives it from `product_text` itself.
    envelope = parse_product_envelope(json.loads(product.text))
    assert envelope.product_uuid == newest.product_uuid

    parsed = parse_cli_product(
        envelope.product_text,
        cli_location=site.cli_location,
        body_header_regex=site.body_header_regex,
    )

    assert isinstance(parsed, ParsedCliProduct)
    # The endpoint fetched (`/products/types/CLI/locations/NYC`) is already
    # scoped to this one CLI location, so the returned product must be OURS
    # -- the registry's own station-identity guard proves it structurally
    # rather than by string-matching a city name.
    assert site.body_header_regex.match(parsed.station_header_line) is not None
    assert parsed.awips_pil == f"CLI{site.cli_location}"
    # Whole-degree Fahrenheit or an explicit sentinel -- never both absent.
    for reading in (parsed.tmax, parsed.tmin, parsed.tavg):
        assert (reading.value_f is not None) or (reading.sentinel != "NONE")


# ---------------------------------------------------------------------------
# (b) Full end-to-end: the real composition root, the real actor, one poll.
# ---------------------------------------------------------------------------


def test_full_e2e_poll_persists_a_climate_day_and_a_raw_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the REAL `ingest_runtime` + actor path for one poll cycle.

    Reuses `breezy.runtime.composition.ingest_runtime`/`build_ingest_node` --
    the same composition root the `breezy` console script uses -- rather than
    hand-assembling an Actor, so this proves the code path production
    actually runs, not a parallel test-only wiring of the same pieces.

    The node is built (`build_ingest_node`, which registers the Actor via
    `Trader.add_actor` -> `register_base`) but neither `node.build()` nor
    `node.run()` is called: `run()` is the blocking, timer-driven live loop,
    and the first poll would not fire for a full `poll_interval_seconds`.
    Calling the Actor's own `poll_once()` -- the exact coroutine the timer
    callback submits -- drives one real cycle directly and deterministically.
    """
    monkeypatch.setenv("BREEZY_USER_AGENT", LIVE_USER_AGENT)

    registry = default_registry()
    site = registry.settlement_site(VENUE, CITY)

    catalog_base = tmp_path / "nws"
    state_db_path = tmp_path / "state" / "breezy-state.sqlite3"

    settings = BreezyRuntimeSettings(
        trader_id="BREEZY-001",
        sites=((VENUE, CITY),),
        catalog_base=catalog_base,
        state_db_path=state_db_path,
        poll_interval_seconds=300,
        parse_timeout_ms=5_000,
        log_level="INFO",
        check_proxy_env=False,
        registry_path=None,
    )

    # One preparatory discovery fetch (see module docstring) to learn which
    # uuids already exist, so the real poll below fetches only the newest.
    async def _discover() -> tuple[DiscoveryEntry, ...]:
        transport = HttpTransport(
            allowed_hosts=DEFAULT_ALLOWED_HOSTS,
            clock=time.time_ns,
            base_url=DEFAULT_BASE_URL,
            user_agent=LIVE_USER_AGENT,
        )
        result = await transport.fetch_discovery_list(site.cli_location)
        assert result.text is not None
        return parse_discovery_list(json.loads(result.text))

    prep_entries = asyncio.run(_discover())
    if len(prep_entries) < 1:
        pytest.skip(
            "NYC's real discovery list returned zero entries; nothing for "
            "the real poll to persist. This is a live-data availability "
            "gap, not a code defect -- re-run once NWS has published again."
        )
    newest_uuid = max(prep_entries, key=lambda entry: entry.issuance_time_ns).product_uuid
    _seed_all_but_newest(state_db_path, prep_entries, except_uuid=newest_uuid)

    loop = asyncio.new_event_loop()
    try:
        with ingest_runtime(settings, probe=_local_probe) as runtime:
            node = build_ingest_node(runtime, node_factory=lambda cfg: TradingNode(cfg, loop=loop))
            try:
                actors = [a for a in node.trader.actors() if isinstance(a, NwsIngestActor)]
                assert len(actors) == 1
                loop.run_until_complete(actors[0].poll_once())
            finally:
                for actor in node.trader.actors():
                    if isinstance(actor, NwsIngestActor):
                        actor.shutdown_executor()
                node.dispose()
    finally:
        if not loop.is_closed():
            loop.close()

    catalog = open_station_catalog(catalog_base, VENUE, CITY)
    climate_days = read_climate_days(catalog)
    raw_products = read_raw_products(catalog)

    assert len(climate_days) >= 1, "real poll persisted no NwsClimateDay record"
    assert len(raw_products) >= 1, "real poll persisted no NwsRawProduct record"

    for day in climate_days:
        assert day.station == site.cli_location
        assert day.issuing_office == site.issuing_office
        for value, flag in (
            (day.tmax_f, day.tmax_flag),
            (day.tmin_f, day.tmin_flag),
            (day.tavg_f, day.tavg_flag),
        ):
            assert (value is not None) != (flag is not None), (
                "a temperature field and its sentinel flag must be "
                "mutually exclusive, never both set and never both absent"
            )

    for product in raw_products:
        assert product.station == site.cli_location
        assert product.product_code == "CLI"
        assert len(product.raw_text) > 0
        assert product.verify_digest(), "persisted raw_sha256 no longer matches raw_text"
