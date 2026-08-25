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

from nautilus_trader.live.config import LiveDataClientConfig

from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSSecretsRefConfig,
    assert_config_type_excludes_secrets,
)
from breezy.adapters.polymarket_us.signing import SigningVariant
from breezy.runtime.settings import SettingsError

__all__ = ["PolymarketUSDataClientConfig"]

#: Fields with no safe default: unset means "operator has not configured it".
REQUIRED_FIELDS: tuple[str, ...] = (
    "api_base_url",
    "gateway_base_url",
    "ws_url",
    "user_agent",
)

#: Fields that are Breezy policy, but must still be strictly positive.
POSITIVE_FIELDS: tuple[str, ...] = (
    "http_timeout_secs",
    "global_requests_per_second",
    "instrument_requests_per_minute",
    "book_requests_per_minute",
    "ws_heartbeat_secs",
    "ws_idle_timeout_secs",
)


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
    market_slugs : tuple[str, ...]
        The market slugs this client subscribes on connect. Must be non-empty.
    user_agent : str
        A specific, contactable User-Agent. Never a generic placeholder.
    signing_variant : SigningVariant
        Which canonical-string builder to sign with.
    """

    secrets: PolymarketUSSecretsRefConfig = PolymarketUSSecretsRefConfig()
    api_base_url: str | None = None
    gateway_base_url: str | None = None
    ws_url: str | None = None
    market_slugs: tuple[str, ...] = ()
    user_agent: str | None = None
    signing_variant: SigningVariant = SigningVariant.PATH_ONLY
    http_timeout_secs: int = 10
    global_requests_per_second: int = 15
    instrument_requests_per_minute: int = 6
    book_requests_per_minute: int = 12
    ws_heartbeat_secs: int = 20
    ws_idle_timeout_secs: int = 60

    def __post_init__(self) -> None:
        unset = [name for name in REQUIRED_FIELDS if not _is_present(getattr(self, name))]
        if not self.market_slugs:
            unset.append("market_slugs")
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


assert_config_type_excludes_secrets(PolymarketUSDataClientConfig)
