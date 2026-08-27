"""Polymarket.us Nautilus extension package -- read-only authenticated slice.

Authority: ``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2).

What this package is
--------------------
A native extension of Nautilus Trader 1.231.0, never a modification of it.
Every class here implements or configures an upstream extension point:
``LiveMarketDataClient``, ``InstrumentProvider``, ``LiveDataClientConfig``,
``LiveDataClientFactory``. Nothing in Nautilus is patched, forked, vendored
or reimplemented.

Wiring it into a ``TradingNode``::

    from breezy.adapters.polymarket_us import (
        POLYMARKET_US_CLIENT_NAME,
        PolymarketUSLiveDataClientFactory,
        config_from_env,
    )

    node.add_data_client_factory(
        POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveDataClientFactory
    )

with the same name as the key in ``TradingNodeConfig.data_clients``, because
``ClientId(name)`` is derived from it (``live/node_builder.py:163,177``).

What is deliberately NOT here
-----------------------------
No execution client, no order path, no strategy. This slice is
GET-only across ordinary adapter/script paths: the signer refuses any method
but ``GET`` (barrier B2), the HTTP client exposes only two read methods (B1),
the transport keeps its pyo3 client out of attribute and bound-method
``__self__`` reachability (B3), and repo-wide AST barriers (B4/B5) scan
``src/`` and ``scripts/`` for write verbs and for imports of the venue SDK's
signing module. B3 is pinned by
``test_transport_does_not_expose_real_pyo3_client_through_bound_method_self``
and ``test_b3_constructed_transport_exposes_no_write_capable_receiver``.

``PolymarketUSFeeModel`` IS exported, and deliberately so. It is a backtest
extension point, not an order path: it prices a fill, it cannot place one.
Exporting it is half the fix for a real defect -- the model had zero callers
while ``BacktestEngine.add_venue`` defaults to ``MakerTakerFeeModel``
(``backtest/engine.pyx:643-644``), so the accurate model sat on the shelf and
the generic one was what would actually run. The other half is barrier F2 in
``tests/unit/test_polymarket_us_fee_guard.py``, which fails the suite for any
module under ``src/`` or ``scripts/`` that builds a venue without passing
``fee_model=PolymarketUSFeeModel()``.

No secret is exported, and none can be. Credentials live only in
``RedactedSecureString`` at runtime and are resolved exclusively in the
factory (control S3); the config carries environment variable NAMES.
"""

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSCredentials,
    PolymarketUSSecretsRefConfig,
    assert_config_type_excludes_secrets,
)
from breezy.adapters.polymarket_us.data import (
    MarketsFeed,
    PolymarketUSDataClient,
    build_data_client,
)
from breezy.adapters.polymarket_us.env import load_polymarket_us_credentials
from breezy.adapters.polymarket_us.errors import (
    CredentialSourceError,
    FeeScheduleUnknownError,
    GatewayForbiddenError,
    MakerRebateUnmodelledError,
    MethodNotPermittedError,
    PolymarketUSError,
    SignatureClockSkewError,
    VenueAuthError,
    VenuePayloadError,
    VenueRateLimitError,
    VenueStatusError,
    VenueTransportError,
)
from breezy.adapters.polymarket_us.factories import (
    POLYMARKET_US_CLIENT_NAME,
    PolymarketUSLiveDataClientFactory,
    config_from_env,
)
from breezy.adapters.polymarket_us.fees import PolymarketUSFeeModel
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.parsing import (
    parse_binary_option,
    parse_book_top,
    parse_quote_tick,
)
from breezy.adapters.polymarket_us.provider import PolymarketUSInstrumentProvider
from breezy.adapters.polymarket_us.redaction import (
    REDACTED,
    SENSITIVE_HEADERS,
    redact_headers,
    redact_secure,
    redact_text,
    redact_url,
)
from breezy.adapters.polymarket_us.safety import (
    LiveTradingPermit,
    assert_live_order_submission_permitted,
)
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import (
    CanonicalRequest,
    Ed25519RequestSigner,
    SigningVariant,
    build_canonical_path_with_query,
    build_canonical_path_without_query,
)
from breezy.adapters.polymarket_us.symbology import (
    INSTRUMENT_SEPARATOR,
    POLYMARKET_US_VENUE,
    WeatherSlug,
    assert_valid_slug,
    instrument_id_to_slug,
    parse_weather_slug,
    slug_to_instrument_id,
)
from breezy.adapters.polymarket_us.transport import (
    NautilusHttpTransport,
    PolymarketUSReadTransport,
    VenueResponse,
    build_default_quota,
    build_keyed_quotas,
)
from breezy.adapters.polymarket_us.websocket import (
    SUBSCRIPTION_TYPE_MARKET_DATA,
    WS_PATH,
    PolymarketUSMarketsWebSocket,
)

__all__ = [
    "INSTRUMENT_SEPARATOR",
    "POLYMARKET_US_CLIENT_NAME",
    "POLYMARKET_US_VENUE",
    "REDACTED",
    "SENSITIVE_HEADERS",
    "SUBSCRIPTION_TYPE_MARKET_DATA",
    "WS_PATH",
    "CanonicalRequest",
    "CredentialSourceError",
    "Ed25519RequestSigner",
    "FeeScheduleUnknownError",
    "GatewayForbiddenError",
    "LiveTradingPermit",
    "MakerRebateUnmodelledError",
    "MarketsFeed",
    "MethodNotPermittedError",
    "NautilusHttpTransport",
    "PolymarketUSCredentials",
    "PolymarketUSDataClient",
    "PolymarketUSDataClientConfig",
    "PolymarketUSError",
    "PolymarketUSFeeModel",
    "PolymarketUSHttpClient",
    "PolymarketUSInstrumentProvider",
    "PolymarketUSLiveDataClientFactory",
    "PolymarketUSMarketsWebSocket",
    "PolymarketUSReadTransport",
    "PolymarketUSSecretsRefConfig",
    "RedactedSecureString",
    "SignatureClockSkewError",
    "SigningVariant",
    "VenueAuthError",
    "VenuePayloadError",
    "VenueRateLimitError",
    "VenueResponse",
    "VenueStatusError",
    "VenueTransportError",
    "WeatherSlug",
    "assert_config_type_excludes_secrets",
    "assert_live_order_submission_permitted",
    "assert_valid_slug",
    "build_canonical_path_with_query",
    "build_canonical_path_without_query",
    "build_data_client",
    "build_default_quota",
    "build_keyed_quotas",
    "config_from_env",
    "instrument_id_to_slug",
    "load_polymarket_us_credentials",
    "parse_binary_option",
    "parse_book_top",
    "parse_quote_tick",
    "parse_weather_slug",
    "redact_headers",
    "redact_secure",
    "redact_text",
    "redact_url",
    "slug_to_instrument_id",
]
