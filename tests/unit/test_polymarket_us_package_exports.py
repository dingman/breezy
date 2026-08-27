"""The adapter package's public surface (plan section 6, "Files modified").

Every seam in this slice deliberately avoided editing ``__init__.py`` so that
parallel work could not collide in one file. The consequence is that the
package's exported surface drifted behind its contents, and an integration
caller -- the ``TradingNode`` wiring, the smoke script, a future execution
slice -- had to reach into private module paths to find the factory.

This suite pins the surface, and pins the two properties that make it safe:

* the Phase-0 exports keep working, so nothing that already imported from the
  package breaks;
* nothing secret-bearing is exported. ``__init__`` is the most-imported name
  in the package, and a credential-shaped export here would be the easiest
  possible accident.
"""

from __future__ import annotations

import importlib

import pytest

import breezy.adapters.polymarket_us as pkg

#: The Phase-0 surface. Removing any of these is a breaking change.
#:
#: The permit seam is pinned in full deliberately. It is the enablement
#: ceiling on real money, and a caller cannot use it safely without all four
#: names: the issuer (the ONLY way to obtain authority), the permit, the
#: capability the chokepoint returns, and the error every refusal raises. An
#: export list carrying the type but not its issuer would leave the type
#: looking constructible, which is the exact defect this seam closed.
PHASE_0_EXPORTS = (
    "LiveOrderSubmissionAuthorization",
    "LiveTradingPermissionError",
    "LiveTradingPermit",
    "PolymarketUSCredentials",
    "PolymarketUSSecretsRefConfig",
    "assert_live_order_submission_permitted",
    "issue_live_trading_permit",
)

#: The read-only slice's integration surface.
SLICE_EXPORTS = (
    "Ed25519RequestSigner",
    "NautilusHttpTransport",
    "POLYMARKET_US_CLIENT_NAME",
    "POLYMARKET_US_VENUE",
    "PolymarketUSDataClient",
    "PolymarketUSDataClientConfig",
    "PolymarketUSHttpClient",
    "PolymarketUSInstrumentProvider",
    "PolymarketUSLiveDataClientFactory",
    "PolymarketUSMarketsWebSocket",
    "PolymarketUSReadTransport",
    "RedactedSecureString",
    "SigningVariant",
    "VenueResponse",
    "config_from_env",
    "instrument_id_to_slug",
    "load_polymarket_us_credentials",
    "parse_binary_option",
    "parse_quote_tick",
    "redact_headers",
    "redact_text",
    "slug_to_instrument_id",
)


@pytest.mark.parametrize("name", PHASE_0_EXPORTS)
def test_phase_0_exports_still_resolve(name: str) -> None:
    assert hasattr(pkg, name)
    assert name in pkg.__all__


@pytest.mark.parametrize("name", SLICE_EXPORTS)
def test_read_only_slice_export_resolves(name: str) -> None:
    assert hasattr(pkg, name)
    assert name in pkg.__all__


def test_every_declared_export_actually_exists() -> None:
    missing = [name for name in pkg.__all__ if not hasattr(pkg, name)]

    assert missing == []


def test_all_is_free_of_duplicates() -> None:
    assert len(set(pkg.__all__)) == len(pkg.__all__)


def test_all_follows_the_package_ordering_convention() -> None:
    """Constants first, then classes, then functions -- as every sibling module.

    Asserted against the convention actually in use (``data.py``,
    ``transport.py``, ``signing.py`` all order this way) rather than against a
    plain ``sorted()``, which would put ``CanonicalRequest`` ahead of
    ``WS_PATH`` and contradict every other ``__all__`` in the package.
    """
    expected = sorted(pkg.__all__, key=lambda name: (not name.isupper(), name))

    assert list(pkg.__all__) == expected


def test_no_export_is_named_after_a_credential_value() -> None:
    """``__init__`` must never become a convenient handle on a secret."""
    banned = ("secret_key", "SECRET_KEY", "private_key", "api_secret", "get_value")

    for name in pkg.__all__:
        for fragment in banned:
            assert fragment not in name


def test_the_factory_export_is_the_native_extension_point() -> None:
    from nautilus_trader.live.factories import LiveDataClientFactory

    assert issubclass(pkg.PolymarketUSLiveDataClientFactory, LiveDataClientFactory)


def test_no_execution_client_name_is_exported() -> None:
    for name in pkg.__all__:
        assert "Exec" not in name


def test_the_package_imports_cleanly_from_a_cold_module_cache() -> None:
    """A stale partially-initialised package would hide a circular import."""
    reloaded = importlib.reload(pkg)

    assert reloaded.POLYMARKET_US_CLIENT_NAME == "POLYMARKET_US"
