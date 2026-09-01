"""Serializable configuration for the Polymarket.us live data client.

Authority: ``docs/plans/archive/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
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

**No venue FACT is an operator input.** G-19 (``docs/plans/backlog/
G-19-autonomy-sweep.md``) states the governing principle: the bot discovers
anything the venue can tell it, and operator input is reserved strictly for
enablement ceilings -- credentials, spend caps, contact strings, deploy paths.
So the endpoint triple is PINNED here from captured venue evidence, the
discovery cadence is DERIVED from the discovered market payloads, and the
matching environment variables survive only as optional overrides. The single
remaining required field is ``user_agent``: a contact string, which is an
enablement ceiling and must never be guessed.

An override is still validated. ``msgspec.Struct`` performs NO type validation
on direct construction, so ``__post_init__`` is the only place a misspelled
``signing_variant`` or an ``http://`` endpoint downgrade is caught before it
becomes an authentication failure or a cleartext request against the venue.

The quota, timeout and heartbeat numbers DO keep defaults, because they are
Breezy policy rather than venue truth.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import msgspec
from nautilus_trader.live.config import LiveDataClientConfig

from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSSecretsRefConfig,
    assert_config_type_excludes_secrets,
)
from breezy.adapters.polymarket_us.signing import SigningVariant
from breezy.registry.sites import SiteRegistry, default_registry
from breezy.runtime.settings import SettingsError

__all__ = [
    "POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR",
    "POLYMARKET_US_API_BASE_URL",
    "POLYMARKET_US_GATEWAY_BASE_URL",
    "POLYMARKET_US_ORIGIN_DOMAIN",
    "POLYMARKET_US_WS_BASE_URL",
    "PolymarketUSDataClientConfig",
    "PolymarketUSMarketDiscoveryConfig",
    "discovery_city_codes_from_registry",
]

#: The registrable domain every venue origin must sit under. VENUE FACT: all
#: three pinned origins (``api``, ``gateway``, ``wss``) are hosts under it.
POLYMARKET_US_ORIGIN_DOMAIN: str = "polymarket.us"

#: The ONE deliberately-named escape from :data:`POLYMARKET_US_ORIGIN_DOMAIN`.
#:
#: The operator is the trust root, so this is not about distrusting them. It
#: exists because the two ways to relocate credentialed traffic are NOT
#: equivalently reviewed: changing a pinned constant goes through code review
#: and git history, while setting ``POLYMARKET_US_API_BASE`` lands via a CI
#: variable, a container spec, or a dependency mutating ``os.environ`` -- none
#: reviewed, none traceable in the repo. Requiring a second, separately-named
#: variable makes a staging or test-double run deliberate and makes a typo a
#: startup failure rather than a credentialed request to a stranger.
#:
#: Precedent, and the decisive argument: ``breezy/ingest/http.py:558`` already
#: host-allowlists the NWS path and re-validates every URL before a socket
#: opens. The path carrying SIGNING CREDENTIALS was the one without it.
POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR: str = "POLYMARKET_US_ALLOW_FOREIGN_ORIGIN"

#: Exact value required to engage the escape. Deliberately not "any truthy
#: string": ``true``/``yes``/``0`` must not silently unlock it.
_ALLOW_FOREIGN_ORIGIN_VALUE: str = "1"

#: Authenticated REST origin. VENUE FACT, not operator preference (G-19 B1).
#:
#: Evidence: ``docs/evidence/venue/polymarket_us/docs_snapshots/
#: api-reference_introduction_2026-08-25.md:14``, the fenced block under the
#: heading "## Authenticated API". Corroborated at ``:104`` of
#: ``api-reference_authentication_2026-08-25.md`` (the worked signing example
#: targets ``https://api.polymarket.us/v1/portfolio/positions``) and at
#: ``VENUE_FACTS_2026-08-25.md:837``.
POLYMARKET_US_API_BASE_URL: str = "https://api.polymarket.us"

#: Public (unauthenticated) REST origin. VENUE FACT (G-19 B1).
#:
#: Evidence: ``docs/evidence/venue/polymarket_us/docs_snapshots/
#: api-reference_introduction_2026-08-25.md:35``, the fenced block under the
#: heading "## Public API". Corroborated by every captured public read in
#: ``VENUE_FACTS_2026-08-25.md`` (e.g. ``:145``, ``:676``, ``:843``), each of
#: which records a live ``GET https://gateway.polymarket.us/v1/...``.
POLYMARKET_US_GATEWAY_BASE_URL: str = "https://gateway.polymarket.us"

#: Markets WebSocket ORIGIN, path deliberately excluded. VENUE FACT (G-19 B1).
#:
#: Evidence: ``docs/evidence/venue/polymarket_us/docs_snapshots/
#: api-reference_introduction_2026-08-25.md:30`` publishes
#: ``wss://api.polymarket.us/v1/ws/markets``; the same URL appears at
#: ``api-reference_websocket_markets_2026-08-25.md:22``. Only the ORIGIN is
#: pinned here because the path is owned by
#: :data:`breezy.adapters.polymarket_us.websocket.WS_PATH`, so the connected
#: path and the SIGNED path cannot drift apart.
POLYMARKET_US_WS_BASE_URL: str = "wss://api.polymarket.us"

#: Origin fields and the single scheme each one is allowed to carry.
#:
#: Applied to the pinned constant AND to any environment override, so a
#: staging host or a test double is held to the same shape as production and
#: an accidental ``http://`` downgrade cannot reach the transport.
ORIGIN_FIELD_SCHEMES: tuple[tuple[str, str], ...] = (
    ("api_base_url", "https"),
    ("gateway_base_url", "https"),
    ("ws_url", "wss"),
)

#: Fields with no safe default: unset means "operator has not configured it".
#:
#: Only ONE entry survives G-19. ``user_agent`` is a contact string: a
#: legitimate operator ceiling that the bot cannot and must not self-derive.
#: The endpoint triple and the reload cadence were removed because both are
#: venue facts the venue itself publishes (see the constants above and
#: :func:`breezy.adapters.polymarket_us.data.derive_reload_delay_secs`).
REQUIRED_FIELDS: tuple[str, ...] = ("user_agent",)

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


def discovery_city_codes_from_registry(
    registry: SiteRegistry | None = None,
    *,
    venue: str = "polymarket_us",
) -> tuple[str, ...]:
    """Derive discovery city slugs from settlement truth, not a recited tuple.

    Config construction has no live venue series payload; the active registry is
    the narrower load-time source because it is the set Breezy can settle. The
    venue-side equality/refusal remains in ``series.derive_site_pairs`` where a
    venue payload actually exists.
    """
    active_registry = default_registry() if registry is None else registry
    codes = tuple(
        active_registry.venue_symbology(registered_venue, city).venue_city_token
        for registered_venue, city in active_registry.pairs()
        if registered_venue == venue
    )
    if not codes:
        raise SettingsError(
            f"market_discovery.city_codes cannot be derived: registry holds no "
            f"sites for venue {venue!r}"
        )
    if len(set(codes)) != len(codes):
        raise SettingsError(
            "market_discovery.city_codes cannot be derived: registry venue_city_token "
            f"values for venue {venue!r} collide"
        )
    return codes


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
    city_codes: tuple[str, ...] = msgspec.field(default_factory=discovery_city_codes_from_registry)

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
        Authenticated REST origin. Defaults to the pinned venue constant
        :data:`POLYMARKET_US_API_BASE_URL`; set only to override (staging).
    gateway_base_url : str
        Public REST origin. Defaults to :data:`POLYMARKET_US_GATEWAY_BASE_URL`.
    ws_url : str
        Markets WebSocket origin WITHOUT the path; the path is owned by
        :data:`breezy.adapters.polymarket_us.websocket.WS_PATH` so the
        connected path and the signed path cannot drift apart. Defaults to
        :data:`POLYMARKET_US_WS_BASE_URL`.
    market_discovery : PolymarketUSMarketDiscoveryConfig
        The venue list-query and city registry used to discover markets.
    instrument_reload_interval_mins : int | None
        OPTIONAL fixed reload cadence, in minutes. ``None`` -- the default --
        means "derive it from the discovered market set", which is the
        autonomous path: every market payload carries ``startDate`` /
        ``endDate`` / ``gameStartTime``, so the venue states its own turnover
        instants and no operator has to recite one. See
        :func:`breezy.adapters.polymarket_us.data.derive_reload_delay_secs`.
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
    api_base_url: str = POLYMARKET_US_API_BASE_URL
    gateway_base_url: str = POLYMARKET_US_GATEWAY_BASE_URL
    ws_url: str = POLYMARKET_US_WS_BASE_URL
    market_discovery: PolymarketUSMarketDiscoveryConfig = msgspec.field(
        default_factory=PolymarketUSMarketDiscoveryConfig
    )
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

    #: Escape from the venue-domain origin allowlist. NOT a secret, and
    #: deliberately a FIELD rather than an environment read performed here.
    #:
    #: Two reasons it belongs on the struct. First, this module must not
    #: consult the environment at all -- the factory owns every environment
    #: lookup (``developer_guide/adapters.md:263-266``), and
    #: ``test_config_module_never_imports_os`` enforces it. Second, a field is
    #: AUDITABLE: it appears in ``config.json()`` and is hashed into the run
    #: identifier by ``tokenize_config``, so a run that relocated its
    #: credentialed traffic off the venue domain says so in its own record.
    #: A hidden environment read would have left no trace.
    #:
    #: The factory sets it from
    #: :data:`POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR`; test doubles and
    #: staging wiring set it explicitly in code, which is reviewed.
    allow_foreign_origin: bool = False

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
        for field, scheme in ORIGIN_FIELD_SCHEMES:
            assert_well_formed_origin(
                field,
                getattr(self, field),
                scheme=scheme,
                allow_foreign=self.allow_foreign_origin,
            )
        if self.instrument_reload_interval_mins is not None:
            value = self.instrument_reload_interval_mins
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise SettingsError(
                    "instrument_reload_interval_mins is an OPTIONAL override; when "
                    f"set it must be a positive integer, was {value!r}"
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


def _assert_host_on_the_venue_domain(
    field: str, origin: str, host: str, *, allow_foreign: bool
) -> None:
    """Refuse a host that is not the venue domain or a subdomain of it.

    Three normalizations happen before the comparison, each closing a case
    that a naive check accepts:

    * a **trailing dot** (``api.polymarket.us.``) is the FQDN-root form of the
      same host and is stripped, so it neither bypasses the check nor is
      rejected as a stranger;
    * a **non-ASCII host** (the Cyrillic homograph of ``api``) is refused
      outright rather than IDNA-normalized. It is always a typo or an attack,
      never intent, and refusing is louder than silently rewriting an operator's
      string into a different one. A genuine internationalized label must be
      supplied in its ``xn--`` form.
    * the suffix match is **dot-bounded**, so ``api.polymarket.us.evil.com``
      and ``notpolymarket.us`` are refused where a substring test accepts them.
    """
    normalized = host.rstrip(".")
    if not normalized:
        raise SettingsError(
            f"PolymarketUSDataClientConfig.{field} must carry a host, was {origin!r}"
        )
    if not normalized.isascii():
        raise SettingsError(
            f"PolymarketUSDataClientConfig.{field} host {normalized!r} contains "
            "non-ASCII characters. A homograph of a venue host is a typo or an "
            "attack, never intent; supply the 'xn--' punycode form if an "
            "internationalized label is genuinely meant."
        )
    if normalized == POLYMARKET_US_ORIGIN_DOMAIN or normalized.endswith(
        f".{POLYMARKET_US_ORIGIN_DOMAIN}"
    ):
        return
    if allow_foreign:
        return
    raise SettingsError(
        f"PolymarketUSDataClientConfig.{field} host {normalized!r} is not "
        f"{POLYMARKET_US_ORIGIN_DOMAIN!r} or a subdomain of it. Breezy refuses to "
        "send signing credentials to a host outside the venue domain. If a "
        "staging host or a test double is genuinely intended, set "
        f"{POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR}="
        f"{_ALLOW_FOREIGN_ORIGIN_VALUE} deliberately."
    )


def assert_well_formed_origin(
    field: str, value: object, *, scheme: str, allow_foreign: bool = False
) -> str:
    """Refuse anything that is not a bare ``<scheme>://<host>`` origin.

    Applied identically to the pinned venue constant and to an environment
    override, so an override can relocate the host WITHIN the venue domain but
    can never relax the transport: no scheme downgrade, no embedded
    credentials, no path, query or fragment (the path is owned by the caller --
    ``WS_PATH`` for the socket, the endpoint constants for REST -- and a path
    here would be silently concatenated into a URL nobody wrote), and no
    foreign host without the separately-named escape.

    The value is validated EXACTLY as written. A frozen ``msgspec.Struct``
    cannot normalize in ``__post_init__``, so accepting-and-returning a
    stripped value while the struct keeps the raw one would mean the validator
    inspects one string and the transport composes another -- measured:
    ``' https://api.polymarket.us '`` composed to
    ``' https://api.polymarket.us /v1/markets'``. Refusing a non-normalized
    value is the only outcome that keeps the two strings identical.
    """
    if not isinstance(value, str) or not value.strip():
        raise SettingsError(
            f"PolymarketUSDataClientConfig.{field} must be a non-empty "
            f"{scheme} origin, was {value!r}"
        )
    if value != value.strip():
        raise SettingsError(
            f"PolymarketUSDataClientConfig.{field} must carry no surrounding "
            f"whitespace, was {value!r}. The frozen config keeps the raw string, "
            "so a value this function had to strip is not the value the "
            "transport would compose a URL from."
        )
    origin = value
    parts = urlsplit(origin)
    if parts.scheme != scheme:
        raise SettingsError(
            f"PolymarketUSDataClientConfig.{field} must use the {scheme!r} "
            f"scheme, was {origin!r}"
        )
    if not parts.netloc or not parts.hostname:
        raise SettingsError(
            f"PolymarketUSDataClientConfig.{field} must carry a host, was {origin!r}"
        )
    if "@" in parts.netloc:
        raise SettingsError(
            f"PolymarketUSDataClientConfig.{field} must not embed credentials"
        )
    # Keyed on the RAW delimiters, not on the parsed components. `urlsplit`
    # reports an EMPTY query for 'https://api.polymarket.us?' and an EMPTY
    # fragment for '...#', so a component test passes both. The composed URL
    # then lands on '/' while the signature covers '/v1/markets' -- the signed
    # path and the requested path silently desync.
    if parts.path.strip("/") or "?" in origin or "#" in origin:
        raise SettingsError(
            f"PolymarketUSDataClientConfig.{field} must be a bare origin with no "
            f"path, query or fragment, was {origin!r}"
        )
    _assert_host_on_the_venue_domain(
        field, origin, parts.hostname, allow_foreign=allow_foreign
    )
    return origin


def _is_present(value: object) -> bool:
    """True when a required string field carries a usable value."""
    return isinstance(value, str) and bool(value.strip())


def _is_required_field_present(name: str, value: object) -> bool:
    del name  # every remaining required field is a non-empty string
    return _is_present(value)


assert_config_type_excludes_secrets(PolymarketUSDataClientConfig)
