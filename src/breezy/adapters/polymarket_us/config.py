"""Serializable configuration for the Polymarket.us live data client.

Authority: ``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
section 6 ``config.py`` (``:602-630``), section 7 environment contract
(``:930-952``) and section 8.2 quota design.

Two rules shape every field here.

**No secret, ever.** A :class:`~nautilus_trader.config.NautilusConfig` is a
serialisation target: the kernel may write ``config.json()`` to disk and
``tokenize_config`` hashes it into a run identifier. So the config carries the
*names* of the environment variables that hold credentials
(:class:`PolymarketUSSecretsRefConfig`) and never a value.
:func:`assert_config_type_excludes_secrets` runs at import so a future field
with a secret-bearing annotation fails at collection time, not in production.
Resolution happens in the factory, as
``developer_guide/adapters.md:263-266`` mandates.

**Every venue parameter is a required input.** ``TRADING_ENABLEMENT_FINDINGS``
(``:254-256``) forbids venue defaults, and a frozen kw-only ``msgspec`` struct
expresses "required" with a ``None`` sentinel plus a ``__post_init__`` that
refuses it. That check is not optional decoration: ``msgspec.Struct`` performs
NO type validation on direct construction, so without it a misspelled
``signing_variant`` string would be accepted here and only fail much later, at
signing time, as an authentication error against the live venue.

The quota, timeout and heartbeat numbers DO keep defaults, because they are
Breezy policy rather than venue truth.
"""

from __future__ import annotations

import msgspec
from nautilus_trader.live.config import LiveDataClientConfig

from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSSecretsRefConfig,
    assert_config_type_excludes_secrets,
)
from breezy.adapters.polymarket_us.signing import SigningVariant
from breezy.runtime.settings import SettingsError

__all__ = [
    "DEFAULT_DISCOVERY_CITY_CODES",
    "PolymarketUSDataClientConfig",
    "PolymarketUSMarketDiscoveryConfig",
]

DEFAULT_DISCOVERY_CITY_CODES: tuple[str, ...] = ("nyc", "sfo", "mia", "mdw", "lax")

#: Fields with no safe default: unset means "operator has not configured it".
REQUIRED_FIELDS: tuple[str, ...] = (
    "api_base_url",
    "gateway_base_url",
    "ws_url",
    "instrument_reload_interval_mins",
    "user_agent",
)

#: Fields that are Breezy policy, but must still be strictly positive.
POSITIVE_FIELDS: tuple[str, ...] = (
    "http_timeout_secs",
    "global_requests_per_second",
    "instrument_requests_per_minute",
    "discovery_requests_per_minute",
    "book_requests_per_minute",
    "ws_heartbeat_secs",
    "ws_idle_timeout_secs",
)


class PolymarketUSMarketDiscoveryConfig(msgspec.Struct, frozen=True):
    """Venue list-query configuration for autonomous weather-market discovery."""

    limit: int = 100
    order_by: tuple[str, ...] = ("endDate",)
    order_direction: str = "asc"
    categories: tuple[str, ...] = ("climate",)
    active: bool | None = True
    closed: bool | None = False
    archived: bool | None = False
    include_closed: bool = False
    city_codes: tuple[str, ...] = DEFAULT_DISCOVERY_CITY_CODES

    def __post_init__(self) -> None:
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit <= 0:
            raise SettingsError(f"market_discovery.limit must be positive, was {self.limit!r}")
        if self.order_direction not in {"asc", "desc"}:
            raise SettingsError(
                "market_discovery.order_direction must be 'asc' or 'desc', "
                f"was {self.order_direction!r}"
            )
        for field in ("order_by", "categories", "city_codes"):
            values = getattr(self, field)
            if not isinstance(values, tuple) or not values:
                raise SettingsError(f"market_discovery.{field} must be a non-empty tuple")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise SettingsError(f"market_discovery.{field} must not contain a blank entry")
        if any(code != code.lower() for code in self.city_codes):
            raise SettingsError("market_discovery.city_codes must use lowercase slug codes")


class PolymarketUSDataClientConfig(LiveDataClientConfig, frozen=True):
    """Configuration for :class:`PolymarketUSDataClient`.

    Parameters
    ----------
    secrets : PolymarketUSSecretsRefConfig
        Environment variable NAMES for the credentials. Never values.
    api_base_url : str
        Authenticated REST origin, e.g. ``https://api.polymarket.us``.
    gateway_base_url : str
        Public REST origin, e.g. ``https://gateway.polymarket.us``.
    ws_url : str
        Markets WebSocket origin WITHOUT the path; the path is owned by
        :data:`breezy.adapters.polymarket_us.websocket.WS_PATH` so the
        connected path and the signed path cannot drift apart.
    market_discovery : PolymarketUSMarketDiscoveryConfig
        The venue list-query and city registry used to discover markets.
    instrument_reload_interval_mins : int
        Required reload cadence. Nautilus supplies the reload primitive but not
        a scheduler, and per-day weather markets need one.
    user_agent : str
        A specific, contactable User-Agent. Never a generic placeholder.
    signing_variant : SigningVariant
        Which canonical-string builder to sign with.
    recorder_instance_id : str | None
        The NATIVE Nautilus node ``instance_id`` of the process that owns this
        client, stamped onto every ``QuoteTapeGap`` row so gap rows from two
        recorder runs can be told apart after their catalogs are merged.

        Threaded through the config because it is not otherwise reachable:
        ``MessageBus`` accepts ``instance_id`` but exposes no attribute for it
        (no ``cdef readonly`` entry in ``common/component.pxd:273-299``), and
        ``LiveDataClientFactory.create`` (``live/factories.py:33-39``) receives
        only loop/name/config/msgbus/cache/clock. This is NOT a second identity
        scheme -- ``breezy.runtime.node_config.build_quote_tape_node_config``
        sets this field and ``TradingNodeConfig.instance_id`` from one value.
    """

    secrets: PolymarketUSSecretsRefConfig = PolymarketUSSecretsRefConfig()
    api_base_url: str | None = None
    gateway_base_url: str | None = None
    ws_url: str | None = None
    market_discovery: PolymarketUSMarketDiscoveryConfig = PolymarketUSMarketDiscoveryConfig()
    market_slugs: tuple[str, ...] = ()
    instrument_reload_interval_mins: int | None = None
    user_agent: str | None = None
    signing_variant: SigningVariant = SigningVariant.PATH_ONLY
    recorder_instance_id: str | None = None
    http_timeout_secs: int = 10
    global_requests_per_second: int = 15
    instrument_requests_per_minute: int = 6
    discovery_requests_per_minute: int = 6
    book_requests_per_minute: int = 12
    ws_heartbeat_secs: int = 20
    ws_idle_timeout_secs: int = 60

    def __post_init__(self) -> None:
        unset = [
            name
            for name in REQUIRED_FIELDS
            if not _is_required_field_present(name, getattr(self, name))
        ]
        if unset:
            raise SettingsError(
                "PolymarketUSDataClientConfig requires every venue parameter to be "
                f"set; unset or empty: {', '.join(unset)}"
            )
        for slug in self.market_slugs:
            if not isinstance(slug, str) or not slug.strip():
                raise SettingsError("market_slugs must not contain a blank entry")
        for name in POSITIVE_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise SettingsError(f"{name} must be a positive integer, was {value!r}")
        try:
            SigningVariant(self.signing_variant)
        except ValueError as exc:
            permitted = ", ".join(variant.value for variant in SigningVariant)
            raise SettingsError(
                f"signing_variant must be one of: {permitted}; was {self.signing_variant!r}"
            ) from exc


def _is_present(value: object) -> bool:
    """True when a required string field carries a usable value."""
    return isinstance(value, str) and bool(value.strip())


def _is_required_field_present(name: str, value: object) -> bool:
    if name == "instrument_reload_interval_mins":
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    return _is_present(value)


assert_config_type_excludes_secrets(PolymarketUSDataClientConfig)
