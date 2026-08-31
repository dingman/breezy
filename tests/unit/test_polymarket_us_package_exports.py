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
#: THE ISSUER IS NO LONGER HERE, and the reason it was is recorded rather than
#: deleted. This tuple used to carry ``issue_live_trading_permit`` with the
#: argument that "an export list carrying the type but not its issuer would
#: leave the type looking constructible". That argument was about
#: DISCOVERABILITY; it was answered by the wrong mechanism. NS-2 defect D-2:
#: the issuer takes no ceiling parameter and reads the operator gate, both
#: spend ceilings and the operator identity from ``os.environ``, so exporting
#: it from the most-imported module in the package put self-issuance one
#: import away for every module in the tree, with no caller barrier of any
#: kind. The type still cannot be constructed directly --
#: ``LiveTradingPermit.__post_init__`` refuses -- so the discoverability
#: argument's actual concern is met by ``safety.py``, which is where the
#: operator-enablement seam lives and is tested.
#:
#: The name moved to ``PERMANENTLY_UNEXPORTED`` below, where its absence is
#: asserted in both halves. A positive pin became a prohibition: strictly
#: stronger, and re-adding the export now fails a test that names the reason.
PHASE_0_EXPORTS = (
    "LiveOrderSubmissionAuthorization",
    "LiveTradingPermissionError",
    "LiveTradingPermit",
    "PolymarketUSCredentials",
    "PolymarketUSSecretsRefConfig",
    "assert_live_order_submission_permitted",
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


#: Names the package must NOT re-export, with the reason each is barred.
#:
#: This is a prohibition, not an omission: an entry here is asserted absent
#: from ``__all__`` AND unreachable as an attribute, so re-adding the import
#: line alone -- without touching ``__all__`` -- still fails.
PERMANENTLY_UNEXPORTED: tuple[tuple[str, str], ...] = (
    (
        "issue_live_trading_permit",
        (
            "NS-2 defect D-2: the issuer derives every field of a permit from the "
            "operator's environment and takes no ceiling parameter, so re-exporting "
            "it from the most-imported module in the package put self-issuance one "
            "import away for every caller in the tree. Reachable only through "
            "`breezy.adapters.polymarket_us.safety`, and callable from nothing in "
            "`src/` or `scripts/` (barrier B7)."
        ),
    ),
)


@pytest.mark.parametrize(
    ("name", "reason"),
    PERMANENTLY_UNEXPORTED,
    ids=[name for name, _ in PERMANENTLY_UNEXPORTED],
)
def test_a_barred_name_is_not_reachable_from_the_package(name: str, reason: str) -> None:
    """B7's other half: unreachable, not merely undeclared.

    ``__all__`` governs ``import *`` and nothing else -- leaving the import
    line in place while dropping the ``__all__`` entry would still let
    ``from breezy.adapters.polymarket_us import issue_live_trading_permit``
    succeed. Both halves are asserted.
    """
    assert name not in pkg.__all__, reason
    assert not hasattr(pkg, name), reason


def test_the_barred_name_is_still_reachable_from_its_defining_module() -> None:
    """Removing an export must not remove the function.

    ``safety.py`` is untouched by NS-2. The issuer still exists, still works,
    and its own suites still exercise it -- what changed is only how far it
    reaches.
    """
    from breezy.adapters.polymarket_us import safety

    assert callable(safety.issue_live_trading_permit)


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
