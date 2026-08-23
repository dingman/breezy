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
