"""G-19 items B1 and B2: the bot discovers venue facts, the operator does not.

Authority: ``docs/plans/backlog/G-19-autonomy-sweep.md`` (governing principle,
stated twice by the operator: *"The bot itself must be capable of autonomous
discovery, the operator will never provide that information."*).

Two defect shapes are removed here, and both are the same shape: a
**required-no-default environment variable holding a venue FACT**.

* **B1** -- the endpoint triple. ``api.polymarket.us`` /
  ``gateway.polymarket.us`` / ``wss://api.polymarket.us`` are published by the
  venue's own API introduction page and captured in this repository. They are
  pinned as module constants and the environment variables survive only as
  optional overrides (a staging host or a test double).
* **B2** -- the discovery reload cadence. Every weather market payload carries
  ``startDate`` / ``endDate`` / ``gameStartTime``, so the venue states exactly
  when each market turns over. The cadence is DERIVED from the discovered
  market set rather than recited by an operator.

The deliverable that proves the principle is
:func:`test_adapter_config_builds_with_no_venue_environment_at_all`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.config import (
    POLYMARKET_US_API_BASE_URL,
    POLYMARKET_US_GATEWAY_BASE_URL,
    POLYMARKET_US_WS_BASE_URL,
    REQUIRED_FIELDS,
    PolymarketUSDataClientConfig,
)
from breezy.adapters.polymarket_us.data import (
    DISCOVERY_RELOAD_CEILING_SECS,
    DISCOVERY_RELOAD_FLOOR_SECS,
    derive_reload_delay_secs,
    instrument_boundaries_ns,
)
from breezy.adapters.polymarket_us.factories import (
    API_BASE_ENV_VAR,
    DISCOVERY_RELOAD_INTERVAL_ENV_VAR,
    GATEWAY_BASE_ENV_VAR,
    POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR,
    USER_AGENT_ENV_VAR,
    WS_URL_ENV_VAR,
    config_from_env,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.settings import SettingsError

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "docs/evidence/venue/polymarket_us"

#: The only remaining operator ceiling on this config: a contactable identity.
#: It cannot be self-derived and must never be guessed.
USER_AGENT = "breezy-test/1.0 (+mailto:ops@example.invalid)"

NANOS_PER_SEC = 1_000_000_000


def _rfc3339_to_ns(value: str) -> int:
    """Convert a captured venue timestamp (always ``...Z``) to epoch nanos."""
    from datetime import datetime

    moment = datetime.fromisoformat(value)
    return int(moment.timestamp()) * NANOS_PER_SEC


def make_instrument(slug: str, *, activation_ns: int, expiration_ns: int) -> BinaryOption:
    symbol = Symbol(slug)
    price_increment = Price.from_str("0.001")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=InstrumentId(symbol=symbol, venue=POLYMARKET_US_VENUE),
        raw_symbol=symbol,
        outcome="Yes",
        description="Test weather market",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=price_increment.precision,
        price_increment=price_increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=activation_ns,
        expiration_ns=expiration_ns,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=0,
        ts_init=0,
    )


# ---------------------------------------------------------------------------
# B1 -- the endpoint triple is a pinned venue constant
# ---------------------------------------------------------------------------


def test_pinned_origins_match_the_captured_venue_documentation() -> None:
    """Each pinned origin appears verbatim in the captured docs snapshot.

    This is the anti-invention barrier: if somebody edits a constant to a
    hostname the venue never published, this fails without any network call.
    """
    snapshot = (EVIDENCE / "docs_snapshots/api-reference_introduction_2026-08-25.md").read_text(
        encoding="utf-8"
    )

    assert POLYMARKET_US_API_BASE_URL in snapshot
    assert POLYMARKET_US_GATEWAY_BASE_URL in snapshot
    # The markets socket origin is published only with its path attached;
    # `websocket.WS_PATH` owns that path so the two cannot drift.
    assert f"{POLYMARKET_US_WS_BASE_URL}/v1/ws/markets" in snapshot


def test_endpoint_triple_is_no_longer_a_required_field() -> None:
    for field in ("api_base_url", "gateway_base_url", "ws_url"):
        assert field not in REQUIRED_FIELDS


def test_config_defaults_to_the_pinned_origins() -> None:
    config = PolymarketUSDataClientConfig(user_agent=USER_AGENT)

    assert config.api_base_url == POLYMARKET_US_API_BASE_URL
    assert config.gateway_base_url == POLYMARKET_US_GATEWAY_BASE_URL
    assert config.ws_url == POLYMARKET_US_WS_BASE_URL


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_base_url", "http://api.polymarket.us"),
        ("api_base_url", "https://user:pw@api.polymarket.us"),
        ("api_base_url", "api.polymarket.us"),
        ("api_base_url", "https://api.polymarket.us/v1"),
        ("gateway_base_url", "wss://gateway.polymarket.us"),
        ("gateway_base_url", "https://"),
        ("ws_url", "https://api.polymarket.us"),
        ("ws_url", "wss://api.polymarket.us/v1/ws/markets"),
    ],
)
def test_origin_override_must_still_be_a_well_formed_origin(field: str, value: str) -> None:
    """The override is optional, never unvalidated."""
    kwargs: dict[str, Any] = {"user_agent": USER_AGENT, field: value}
    with pytest.raises(SettingsError, match=field):
        PolymarketUSDataClientConfig(**kwargs)


def test_origin_override_from_the_environment_wins_over_the_pinned_value() -> None:
    config = config_from_env(
        {
            USER_AGENT_ENV_VAR: USER_AGENT,
            API_BASE_ENV_VAR: "https://api.staging.example.invalid",
            GATEWAY_BASE_ENV_VAR: "https://gateway.staging.example.invalid",
            WS_URL_ENV_VAR: "wss://api.staging.example.invalid",
            # Security finding M2: relocating credentialed traffic OFF the
            # venue domain now requires this second, separately-named
            # variable. An override alone can no longer do it.
            POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR: "1",
        }
    )

    assert config.allow_foreign_origin is True
    assert config.api_base_url == "https://api.staging.example.invalid"
    assert config.gateway_base_url == "https://gateway.staging.example.invalid"
    assert config.ws_url == "wss://api.staging.example.invalid"


def test_a_foreign_origin_override_alone_is_refused_without_the_escape() -> None:
    """M2: an unreviewed env var must not relocate credentialed traffic."""
    with pytest.raises(SettingsError, match=API_BASE_ENV_VAR):
        config_from_env(
            {
                USER_AGENT_ENV_VAR: USER_AGENT,
                API_BASE_ENV_VAR: "https://api.staging.example.invalid",
            }
        )


def test_a_venue_domain_origin_override_needs_no_escape() -> None:
    """Relocating WITHIN polymarket.us stays a one-variable operation."""
    config = config_from_env(
        {
            USER_AGENT_ENV_VAR: USER_AGENT,
            API_BASE_ENV_VAR: "https://api.staging.polymarket.us",
        }
    )

    assert config.api_base_url == "https://api.staging.polymarket.us"
    assert config.allow_foreign_origin is False


def test_a_malformed_origin_override_is_rejected_by_the_environment_reader() -> None:
    with pytest.raises(SettingsError, match=API_BASE_ENV_VAR):
        config_from_env({USER_AGENT_ENV_VAR: USER_AGENT, API_BASE_ENV_VAR: "not-a-url"})


# ---------------------------------------------------------------------------
# The deliverable: no venue environment at all
# ---------------------------------------------------------------------------


def test_adapter_config_builds_with_no_venue_environment_at_all() -> None:
    """THE deliverable of G-19 B1+B2.

    Only ``POLYMARKET_US_USER_AGENT`` -- a contact string, a legitimate (A)
    operator ceiling -- is present. None of the four (B) venue-fact variables
    is set, and the adapter config still constructs.
    """
    config = config_from_env({USER_AGENT_ENV_VAR: USER_AGENT})

    assert config.api_base_url == POLYMARKET_US_API_BASE_URL
    assert config.gateway_base_url == POLYMARKET_US_GATEWAY_BASE_URL
    assert config.ws_url == POLYMARKET_US_WS_BASE_URL
    # ``None`` is the explicit "derive it from the venue payload" sentinel.
    assert config.instrument_reload_interval_mins is None


def test_no_venue_fact_variable_is_named_as_missing() -> None:
    """A missing (B) variable must never be reported as an operator failure."""
    with pytest.raises(SettingsError) as excinfo:
        config_from_env({})

    message = str(excinfo.value)
    assert USER_AGENT_ENV_VAR in message
    for name in (
        API_BASE_ENV_VAR,
        GATEWAY_BASE_ENV_VAR,
        WS_URL_ENV_VAR,
        DISCOVERY_RELOAD_INTERVAL_ENV_VAR,
    ):
        assert name not in message


# ---------------------------------------------------------------------------
# B2 -- the reload cadence is derived from the discovered market set
# ---------------------------------------------------------------------------


def test_captured_climate_payload_carries_the_three_boundary_fields() -> None:
    """VERIFY the premise before depending on it (brief requirement)."""
    payload = json.loads(
        (EVIDENCE / "raw/markets_categories_climate.json").read_text(encoding="utf-8")
    )
    markets: list[dict[str, Any]] = payload["markets"]

    assert markets, "captured climate payload is empty"
    for market in markets:
        for field in ("startDate", "endDate", "gameStartTime"):
            assert isinstance(market[field], str) and market[field].endswith("Z")


def test_instrument_boundaries_come_from_the_native_nautilus_instrument() -> None:
    """Null hypothesis: ``startDate``/``endDate`` are ALREADY on the instrument.

    ``parsing.parse_binary_option`` maps them onto the native
    ``BinaryOption.activation_ns`` / ``.expiration_ns``, so no parallel
    boundary store is built.
    """
    activation = _rfc3339_to_ns("2026-08-24T09:45:21Z")
    expiration = _rfc3339_to_ns("2026-08-26T05:00:00Z")
    instrument = make_instrument(
        "tc-temp-nychigh-2026-08-25-lt79f",
        activation_ns=activation,
        expiration_ns=expiration,
    )

    assert instrument_boundaries_ns([instrument]) == (activation, expiration)


def test_derived_delay_targets_the_soonest_upcoming_boundary() -> None:
    now = _rfc3339_to_ns("2026-08-25T12:00:00Z")
    soonest = now + 3 * 3600 * NANOS_PER_SEC
    latest = now + 20 * 3600 * NANOS_PER_SEC

    outcome = derive_reload_delay_secs(now_ns=now, boundaries_ns=(latest, soonest))

    assert outcome.boundary_ns == soonest
    assert outcome.seconds == pytest.approx(3 * 3600)
    assert outcome.clamped is None


def test_derived_cadence_changes_when_the_discovered_end_dates_change() -> None:
    """Brief requirement: a different market set yields a different cadence."""
    now = _rfc3339_to_ns("2026-08-26T02:00:00Z")
    # The real captured pair: today's ladder expires at 05:00Z, tomorrow's was
    # listed the previous morning and expires 24h later.
    today = make_instrument(
        "tc-temp-nychigh-2026-08-25-lt79f",
        activation_ns=_rfc3339_to_ns("2026-08-24T09:45:21Z"),
        expiration_ns=_rfc3339_to_ns("2026-08-26T05:00:00Z"),
    )
    tomorrow = make_instrument(
        "tc-temp-nychigh-2026-08-26-lt79f",
        activation_ns=_rfc3339_to_ns("2026-08-25T09:45:21Z"),
        expiration_ns=_rfc3339_to_ns("2026-08-27T05:00:00Z"),
    )

    before = derive_reload_delay_secs(now_ns=now, boundaries_ns=instrument_boundaries_ns([today]))
    # Today's ladder settles and drops out of discovery: the endDate set has
    # changed, and so must the cadence.
    after = derive_reload_delay_secs(
        now_ns=now, boundaries_ns=instrument_boundaries_ns([tomorrow])
    )

    assert before.seconds == pytest.approx(3 * 3600)
    assert before.seconds != after.seconds

    # Adding a market can only pull the next reload earlier or leave it
    # unchanged; it can never push it out.
    both = derive_reload_delay_secs(
        now_ns=now, boundaries_ns=instrument_boundaries_ns([today, tomorrow])
    )
    assert both.seconds <= before.seconds


def test_a_boundary_further_out_than_the_ceiling_is_clamped_and_reported() -> None:
    now = _rfc3339_to_ns("2026-08-25T12:00:00Z")
    far = now + int(DISCOVERY_RELOAD_CEILING_SECS + 10_000) * NANOS_PER_SEC

    outcome = derive_reload_delay_secs(now_ns=now, boundaries_ns=(far,))

    assert outcome.seconds == DISCOVERY_RELOAD_CEILING_SECS
    assert outcome.clamped == "ceiling"


def test_a_stale_payload_whose_boundaries_all_passed_is_clamped_to_the_floor() -> None:
    """No hot loop: every boundary in the past still costs a full floor wait."""
    now = _rfc3339_to_ns("2026-08-25T12:00:00Z")
    stale = now - 3600 * NANOS_PER_SEC

    outcome = derive_reload_delay_secs(now_ns=now, boundaries_ns=(stale,))

    assert outcome.seconds == DISCOVERY_RELOAD_FLOOR_SECS
    assert outcome.clamped == "floor"
    assert outcome.boundary_ns is None


def test_a_boundary_inside_the_floor_is_clamped_to_the_floor() -> None:
    now = _rfc3339_to_ns("2026-08-25T12:00:00Z")
    imminent = now + 5 * NANOS_PER_SEC

    outcome = derive_reload_delay_secs(now_ns=now, boundaries_ns=(imminent,))

    assert outcome.seconds == DISCOVERY_RELOAD_FLOOR_SECS
    assert outcome.clamped == "floor"


def test_floor_and_ceiling_are_ordered_and_rate_limit_safe() -> None:
    assert 0 < DISCOVERY_RELOAD_FLOOR_SECS < DISCOVERY_RELOAD_CEILING_SECS
    # The discovery quota is 6 requests/minute; one reload is >= 1 request.
    assert DISCOVERY_RELOAD_FLOOR_SECS >= 60


def test_an_underivable_cadence_retries_at_the_floor_rather_than_failing_shut() -> None:
    """DELIBERATE INVERSION of the original G-19 assertion. Security finding M4.

    The original test asserted that a zero-boundary set is "a broken invariant,
    not a default", and that reading was wrong about reachability: the state is
    reachable at a cold start inside a fully-settled window, because
    ``load_all_async`` refuses only a ZERO-DISCOVERED cycle. If every discovered
    market carries a ``resolved_reason`` it ``continue``s before ``self.add``,
    so discovery SUCCEEDS while ``get_all()`` stays empty. Raising there was the
    first statement inside the reload loop, before any ``await``, and the loop
    caught only ``CancelledError`` -- so the task died on iteration one,
    permanently, and the reload loop is the only path to the next day's ladder.

    This is not a weakened guard. The fail-shut reading traded a BOUNDED cost
    (one discovery request every ``DISCOVERY_RELOAD_FLOOR_SECS``, well inside
    the 6/min quota) for an UNBOUNDED one (silent, irrecoverable blindness).
    The floor is still reported as ``clamped`` so it is logged loudly and never
    applied silently.
    """
    outcome = derive_reload_delay_secs(
        now_ns=_rfc3339_to_ns("2026-08-25T12:00:00Z"), boundaries_ns=()
    )

    assert outcome.seconds == DISCOVERY_RELOAD_FLOOR_SECS
    assert outcome.clamped == "floor"
    assert outcome.boundary_ns is None


def test_reload_interval_is_no_longer_a_required_field() -> None:
    assert "instrument_reload_interval_mins" not in REQUIRED_FIELDS


def test_an_explicit_reload_override_is_still_accepted_and_validated() -> None:
    assert (
        config_from_env(
            {USER_AGENT_ENV_VAR: USER_AGENT, DISCOVERY_RELOAD_INTERVAL_ENV_VAR: "7"}
        ).instrument_reload_interval_mins
        == 7
    )
    with pytest.raises(SettingsError, match=DISCOVERY_RELOAD_INTERVAL_ENV_VAR):
        config_from_env(
            {USER_AGENT_ENV_VAR: USER_AGENT, DISCOVERY_RELOAD_INTERVAL_ENV_VAR: "0"}
        )
