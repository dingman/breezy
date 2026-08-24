"""The `ActorConfig` for the per-`(venue, city)` NWS ingest Actor.

Imported from `nautilus_trader.common.config` (typed `.py`) rather than
`nautilus_trader.common.actor` (compiled Cython, erases to `Any`) --
importing from the wrong module would make every field on this config
untyped under mypy strict.

`NwsIngestActorConfig` carries only msgspec-serialisable scalar fields (plus
the `component_id: ComponentId | None` it inherits from `ActorConfig`) so it
survives an `ImportableActorConfig` round-trip at Trader-node startup. Every
object this Actor actually needs at runtime -- the shared
`SettlementGate`, `ProductIntegrityIndex`, `HttpTransport`, clock, and
`SiteRegistry` -- is composition-time-only and passed via `__init__`, never
placed on this config: a `Path`, a callable, or an object reference here
would either fail to serialise or silently diverge between the value on
disk and the live object a later run reconstructs.
"""

from __future__ import annotations

from nautilus_trader.common.config import ActorConfig

DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_PARSE_TIMEOUT_MS = 250
DEFAULT_DISCOVERY_MAX_BYTES = 262_144
DEFAULT_DISCOVERY_MAX_DEPTH = 8
DEFAULT_FINAL_DEADLINE_CHECK_INTERVAL_SECONDS = 300
DEFAULT_STAGGER_OFFSET_SECONDS = 0
DEFAULT_PRODUCT_FETCH_DELAY_SECONDS = 0.5
MAX_PRODUCT_FETCH_DELAY_SECONDS = 5.0


class NwsIngestActorConfig(ActorConfig, frozen=True):
    """Configuration for one NWS ingest Actor serving one `(venue, city)` site.

    `venue` and `city` are required and have no default: an Actor
    constructed without an explicit site would otherwise silently bind to an
    arbitrary one.
    """

    venue: str
    city: str
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    parse_timeout_ms: int = DEFAULT_PARSE_TIMEOUT_MS
    discovery_max_bytes: int = DEFAULT_DISCOVERY_MAX_BYTES
    discovery_max_depth: int = DEFAULT_DISCOVERY_MAX_DEPTH
    final_deadline_check_interval_seconds: int = DEFAULT_FINAL_DEADLINE_CHECK_INTERVAL_SECONDS
    #: Polite intra-site pacing between `/products/{id}` body fetches. The first
    #: product in a poll is never delayed; this applies only before the second
    #: and later body requests so a fresh site does not send a cold-start burst.
    product_fetch_delay_seconds: float = DEFAULT_PRODUCT_FETCH_DELAY_SECONDS
    #: Phase shift, in seconds, applied to this site's timers via the
    #: NATIVE `Clock.set_timer(start_time=...)` parameter
    #: (`nautilus_trader/common/component.pyx:419-478`). Assigned by
    #: `breezy.runtime.composition.site_stagger_offset_seconds`, which is
    #: the only place that knows how many sites this process serves.
    #: `0` (the default) means no shift, so a single-site or hand-built
    #: Actor behaves exactly as before.
    stagger_offset_seconds: int = DEFAULT_STAGGER_OFFSET_SECONDS

    def __post_init__(self) -> None:
        if self.product_fetch_delay_seconds < 0:
            raise ValueError(
                "`product_fetch_delay_seconds` must be non-negative, was "
                f"{self.product_fetch_delay_seconds}"
            )
        if self.product_fetch_delay_seconds > MAX_PRODUCT_FETCH_DELAY_SECONDS:
            # The observed cold-start ceiling is 14 products. Delaying before
            # product 2..14 at 5 s adds at most 65 s: enough to blunt a burst,
            # still far below the 300 s default poll cadence so `_poll_in_flight`
            # does not silently turn pacing into dropped cycles.
            raise ValueError(
                "`product_fetch_delay_seconds` must be <= "
                f"{MAX_PRODUCT_FETCH_DELAY_SECONDS}, was {self.product_fetch_delay_seconds}"
            )
