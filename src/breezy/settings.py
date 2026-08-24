"""Environment-sourced runtime configuration for Breezy.

`BreezySettings.from_env` is the single place production code reads process
configuration. It is deliberately narrow:

- **No secrets.** `user_agent_contact` is PII-adjacent (a monitored role
  mailbox an operator controls), never a credential. There is no Redis
  config here -- its absence is a recorded decision (Breezy has no Redis
  dependency today), not an oversight.
- **`BREEZY_USER_AGENT` is required.** This mirrors the fail-fast fix in
  `breezy.ingest.http._default_user_agent`: an unset contact must never
  silently default, because NWS permanently blocklists misbehaving clients
  and an unmonitored address is worse than refusing to start. See
  `docs/plans/WEATHER_INGESTION_PROPOSAL.md` §0 decision 2 and §6.
- **Sites are validated against the real settlement-site registry**
  (`breezy.registry.sites`), never trusted verbatim -- an unknown
  `venue/city` is a deployment defect (typo, stale config, wrong venue), not
  something to silently drop.
- **Stagger is derived, never per-site-configured.** Actor `i` gets
  `i * poll_stagger_ns` via :meth:`BreezySettings.poll_offset_ns`, a pure
  function of position. A per-site offset list would let two cities share an
  offset by accident; a single base increment cannot.
- **Paths are canonicalized.** `BREEZY_CATALOG_BASE` / `BREEZY_STATE_PATH`
  come from the environment and become filesystem paths a settlement-grade
  process writes to, so each is required to be absolute and is resolved
  through `os.path.realpath` (collapsing `..` and symlinks to their real
  target) before it is trusted. This is the same rigor
  `ingest/http.py._validated_path_identifier` applies to network-derived path
  segments, applied here to config-derived ones.

**Where each default came from (`docs/plans/WEATHER_INGESTION_PROPOSAL.md`
§6, "Reliability and data-quality controls"):**

- `parse_timeout_s = 0.25` -- taken verbatim from §6's
  `PARSE_TIME_CEILING_SECONDS`, the fuzz-tested wall-clock ceiling on inline
  CLI-product parsing.
- `poll_interval_ns` / `poll_stagger_ns` defaults -- §6 does **not** specify a
  numeric discovery-list poll cadence (Open-Meteo's hourly forecast cadence
  is given explicitly; the NWS discovery-list cadence is not). Absent that,
  a 5-minute (300s) default poll interval is chosen: the late-final-CLI
  escalation table in §6 spans a 90-minute WARN (06:00 ET) -> CRIT (07:30 ET)
  window, so a 5-minute poll grants roughly 18 chances to observe a
  transition inside that window without polling NWS aggressively enough to
  itself risk the abuse-block §6 warns about. The stagger default (30s) is
  chosen so five sites spread across the first 150s of every 300s cycle
  rather than opening five connections simultaneously, while leaving ample
  headroom before the next cycle begins.
- `freshness_degraded_after_ns` / `freshness_blocked_after_ns` -- §6 gives a
  freshness *escalation* shape (WARN/CRIT/BLOCKED at fixed times of day) but
  not a duration-based watchdog threshold of the kind
  `breezy.ingest.gate.SettlementGate.check_freshness` takes. Absent a
  documented number, 30 minutes (three-plus missed 5-minute polls -- a real
  signal, not scheduler jitter or an ordinary backoff cycle) is chosen for
  DEGRADED, and 90 minutes for BLOCKED, matching the width of §6's own
  WARN->CRIT window and leaving comfortable margin before the 08:00 ET
  settlement deadline.
- `catalog_io_workers = 2` -- §6 does not size this pool. Catalog writes are
  one per site per poll cycle (five sites total) and are I/O-bound, not
  CPU-bound, so this is sized to avoid serializing every write behind a
  single worker without over-provisioning a workload that is fundamentally
  bounded by disk throughput rather than concurrency.

Every one of these four bullets is stated here explicitly, per the operating
rule that an unspecified threshold must never be invented silently.

## Built on `NautilusConfig`, not hand-rolled

`BreezySettings` is a `nautilus_trader.common.config.NautilusConfig`
subclass (a frozen, kw-only, `forbid_unknown_fields` `msgspec.Struct`) rather
than a bespoke `@dataclass`. This buys, for free: `.json()` / `.parse()`
round-tripping, `.json_schema()`, `.id` (a content hash), and unknown-field
rejection -- and it means a `BreezySettings` instance can ride inside an
`ImportableActorConfig.config` dict across the JSON boundary
`nautilus_trader.common.config.ActorFactory.create` uses
(`common/config.py:609-614`), which a plain dataclass could never do.

Three findings from verifying this against the installed
`nautilus_trader==1.231.0` tree (msgspec 0.21.1) shaped the design below and
are recorded here because they contradict what a cursory reading of
`common/config.py` would suggest:

1. **`Meta`-constrained types (`PositiveInt`, `NonNegativeInt`,
   `PositiveFloat`, ...) are validated only on msgspec's *decode* path
   (`.parse()`, `msgspec.convert(..., strict=True)`), never on direct
   `__init__` construction.** `BreezySettings(poll_interval_ns=-5, ...)`
   is accepted by the bare constructor with no error. This means the
   constrained-type annotations below do **not**, by themselves, replace
   the hand-rolled positivity checks that used to live in `__post_init__` --
   they only guard the decode boundary. `__post_init__` therefore still
   re-checks every one of these constraints explicitly, as the sole
   enforcement path for direct construction (which the class docstring has
   always supported for tests). The two layers are intentionally redundant:
   the `Annotated`/`Meta` types buy correct `.json_schema()` output and
   decode-time validation "for free"; `__post_init__` buys the same
   guarantee for direct construction, which Nautilus's own constrained
   types do not cover.
2. **`__post_init__` is fully supported on a frozen `msgspec.Struct`** (this
   *did* hold as documented) and runs on every construction path: direct
   `__init__`, `msgspec.convert`, and `.parse()`/`json.decode`.
3. **`Path` and `tuple[tuple[str, str], ...]` are not natively
   msgspec-encodable** -- confirmed: `msgspec_encoding_hook` /
   `msgspec_decoding_hook` (`common/config.py:148-176`) have no `Path`
   branch, and encoding a bare `Path` raises `TypeError` even without those
   hooks. `tuple[tuple[str, str], ...]` *is* natively supported (msgspec
   encodes/decodes plain tuples out of the box) and needs no special
   handling. Two ways to close the `Path` gap were evaluated:
   - `register_config_encoding(PosixPath, str)` /
     `register_config_decoding(Path, Path)` -- Nautilus's own public
     extension point (`common/config.py:223-230`). Rejected: it mutates a
     **global, process-wide, mutable dict** shared by every `NautilusConfig`
     subclass in the process (not just ours), as a module-import side
     effect, and its lookup is by **exact runtime type**
     (`type(obj) in CUSTOM_ENCODINGS`) -- `Path("/x")` is actually a
     `PosixPath` instance, so registering the abstract `Path` key silently
     fails to match (verified empirically); the working registration is
     platform-specific (`PosixPath`, not `WindowsPath`) and easy to get
     wrong again elsewhere in the process.
   - **Chosen: a local `enc_hook`/`dec_hook` pair, scoped to this module,
     that special-cases `Path` via `isinstance` (robust to both
     `PosixPath`/`WindowsPath`) and delegates every other type to
     Nautilus's own `msgspec_encoding_hook` / `msgspec_decoding_hook`.**
     This still fully reuses Nautilus's hooks (no reimplementation, no
     duplication for the types Nautilus already handles) without mutating
     shared global state or tripping the exact-type-match footgun above.
     `.json()` and `.parse()` are overridden to use these local hooks;
     every other `NautilusConfig` method (`.dict()`, `.json_primitives()`,
     `.validate()`, `.id`) is inherited unmodified and works correctly
     through the override because each calls `self.json()` /
     `self.parse()` polymorphically.

## `from_env` and the native `adapters/env.py` helpers

The task that produced this module asked `from_env` to be "a thin adapter
over `get_env_key` / `get_env_key_or`" while also preserving that a passed
`env` mapping is used **exclusively** (never falling back to `os.environ`).
Verified against the installed tree: `get_env_key` / `get_env_key_or`
(`adapters/env.py:19-30`) are hardcoded to read `os.environ` directly --
there is no mapping parameter, and every real call site in Nautilus
(`adapters/polymarket/common/credentials.py`,
`adapters/databento/factories.py`, `adapters/binance/common/credentials.py`)
calls them exactly that way. They cannot service the "exclusive explicit
mapping" contract at all; monkeypatching `os.environ` to redirect them would
be exactly the kind of workaround this module's tests exist to prevent
(process-global mutable state, unsafe under concurrent tests). Resolution:
`get_env_key_or` is used for the two *optional* cadence knobs
(`BREEZY_POLL_INTERVAL_S` / `BREEZY_POLL_STAGGER_S`) **only when no explicit
`env` was supplied** (i.e. only on the branch that already means
"`os.environ`, with a default") -- its one genuinely correct, drop-in fit.
For every required field, and for the explicit-`env` branch generally, this
module reads `source.get(...)` directly: required fields raise
domain-specific `SettingsError` messages `get_env_key`'s generic
`RuntimeError` text cannot express, and the explicit-mapping path cannot use
`get_env_key`/`get_env_key_or` at all without breaking the pinned
"exclusive mapping" contract.

## The sanctioned, type-validated construction entry point

Because direct construction does not validate `Meta` constraints or field
types (finding 1 above), `from_env` does not call `BreezySettings(**values)`
directly. It builds a plain values dict and calls
:meth:`BreezySettings.from_mapping`, which routes through
`msgspec.convert(data, type=cls, strict=True, dec_hook=...)` -- the same
validated-decode machinery `.parse()` uses for raw JSON, just accepting an
already-typed Python mapping instead of bytes. This closes the gap a
"NautilusConfig subclass = automatically type-safe" assumption would
otherwise leave open: a wrong-typed or out-of-range value passed through
`from_mapping` is caught there, not silently accepted. `from_mapping`'s own
type/range failures surface as `msgspec.ValidationError` -- the same
exception `.parse()` raises for the identical class of failure, keeping the
two decode-equivalent entry points consistent. `SettingsError` is reserved
for the checks Nautilus cannot express (registry lookups, path
canonicalization, the freshness cross-field invariant) and for `from_env`'s
own field-presence/parsing errors, raised before construction is attempted.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import msgspec
from msgspec import Meta
from nautilus_trader.adapters.env import get_env_key_or
from nautilus_trader.common.config import (
    InvalidConfiguration,
    NautilusConfig,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)
from nautilus_trader.common.config import (
    msgspec_decoding_hook as _nautilus_decoding_hook,
)
from nautilus_trader.common.config import (
    msgspec_encoding_hook as _nautilus_encoding_hook,
)

from breezy.ingest.http import DEFAULT_CONTACT, USER_AGENT_ENV_VAR
from breezy.registry.sites import SiteNotFoundError, default_registry

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

SITES_ENV_VAR = "BREEZY_SITES"
CATALOG_BASE_ENV_VAR = "BREEZY_CATALOG_BASE"
STATE_PATH_ENV_VAR = "BREEZY_STATE_PATH"
POLL_INTERVAL_ENV_VAR = "BREEZY_POLL_INTERVAL_S"
POLL_STAGGER_ENV_VAR = "BREEZY_POLL_STAGGER_S"

_NS_PER_SECOND = 1_000_000_000

# See the module docstring's "Where each default came from" section for the
# reasoning behind every constant below -- none of these is sourced from the
# environment, and none is invented without a stated justification.
_DEFAULT_POLL_INTERVAL_S: float = 300.0
_DEFAULT_POLL_STAGGER_S: float = 30.0
_DEFAULT_FRESHNESS_DEGRADED_AFTER_NS: int = 30 * 60 * _NS_PER_SECOND
_DEFAULT_FRESHNESS_BLOCKED_AFTER_NS: int = 90 * 60 * _NS_PER_SECOND
_DEFAULT_PARSE_TIMEOUT_S: float = 0.25
_DEFAULT_CATALOG_IO_WORKERS: int = 2

# Genuinely ours: Nautilus has no non-empty-string constrained type, only
# the numeric Positive*/NonNegative* family (see module docstring).
_NonEmptyStr = Annotated[str, Meta(min_length=1)]


# ---------------------------------------------------------------------------
# Local encode/decode hooks -- close the Path encoding-hook gap without
# mutating Nautilus's global, process-wide CUSTOM_ENCODINGS/CUSTOM_DECODINGS
# registries (see module docstring for why `register_config_encoding` was
# rejected).
# ---------------------------------------------------------------------------


def _encode_hook(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    return _nautilus_encoding_hook(obj)


def _decode_hook(obj_type: type, obj: Any) -> Any:
    if obj_type is Path:
        return Path(obj)
    return _nautilus_decoding_hook(obj_type, obj)


class SettingsError(InvalidConfiguration):
    """Raised for any invalid, missing, or unsafe Breezy runtime setting.

    Based on `nautilus_trader.common.config.InvalidConfiguration` so config
    failures share the framework's own configuration-error type -- callers
    that already catch `InvalidConfiguration` around Nautilus config loading
    catch this too, with no Breezy-specific `except` clause required.

    Every raise site names the offending environment variable and, where the
    value itself is not untrusted network data, the offending value -- so a
    misconfigured deployment fails loudly with an actionable message rather
    than falling back to a silent guess.
    """


class BreezySettings(NautilusConfig, frozen=True, kw_only=True):
    """Validated, immutable runtime configuration for one Breezy process.

    Construct via :meth:`from_env` (production) or :meth:`from_mapping`
    (the sanctioned, type-validated entry point `from_env` itself uses), not
    directly with unvalidated values. Direct construction is supported for
    tests that want to build a known-good instance without an environment
    mapping or a mapping-shaped payload, and is guarded by
    :meth:`__post_init__` so a directly-constructed instance still cannot
    violate the same invariants `from_env` enforces -- though, per the
    module docstring's finding 1, direct construction does **not** validate
    the `Meta`-constrained field types below; only `.parse()` and
    `.from_mapping()` do.

    `frozen=True` and `kw_only=True` are restated explicitly even though
    `frozen` (and `forbid_unknown_fields`) are inherited automatically from
    `NautilusConfig` -- `kw_only` is verified **not** to be inherited by
    subclasses (confirmed empirically), so it must be restated here to keep
    construction keyword-only, matching `NautilusConfig`'s own declared
    intent and this class's pre-existing keyword-only usage pattern.
    """

    sites: tuple[tuple[str, str], ...]
    catalog_base: Path
    state_store_path: Path
    poll_interval_ns: PositiveInt
    poll_stagger_ns: NonNegativeInt
    user_agent_contact: _NonEmptyStr
    freshness_degraded_after_ns: PositiveInt
    freshness_blocked_after_ns: PositiveInt
    parse_timeout_s: PositiveFloat
    catalog_io_workers: PositiveInt
    require_durable_store: bool = True

    def __post_init__(self) -> None:
        # -- Redundant-by-design re-checks of the Meta-constrained fields
        # above. See module docstring finding 1: msgspec validates Meta
        # constraints only on decode (`.parse()` / `.from_mapping()`), never
        # on direct `__init__` construction, so this is the only enforcement
        # path for that route. ------------------------------------------
        if self.poll_interval_ns <= 0:
            raise SettingsError(f"poll_interval_ns must be positive, got {self.poll_interval_ns}")
        if self.poll_stagger_ns < 0:
            raise SettingsError(f"poll_stagger_ns must be >= 0, got {self.poll_stagger_ns}")
        if not self.user_agent_contact:
            raise SettingsError("user_agent_contact must not be empty")
        if self.freshness_degraded_after_ns <= 0:
            raise SettingsError(
                "freshness_degraded_after_ns must be positive, got "
                f"{self.freshness_degraded_after_ns}"
            )
        if self.parse_timeout_s <= 0:
            raise SettingsError(f"parse_timeout_s must be positive, got {self.parse_timeout_s}")
        if self.catalog_io_workers < 1:
            raise SettingsError(
                f"catalog_io_workers must be >= 1, got {self.catalog_io_workers}"
            )

        # -- Genuinely ours: no native Nautilus equivalent (see module
        # docstring's "what stays genuinely ours"). --------------------
        if not self.sites:
            raise SettingsError("BreezySettings.sites must not be empty")
        if len(set(self.sites)) != len(self.sites):
            raise SettingsError(f"BreezySettings.sites contains duplicate entries: {self.sites}")
        if not self.catalog_base.is_absolute():
            raise SettingsError(f"catalog_base must be absolute, got {self.catalog_base}")
        if not self.state_store_path.is_absolute():
            raise SettingsError(f"state_store_path must be absolute, got {self.state_store_path}")
        if self.freshness_blocked_after_ns <= self.freshness_degraded_after_ns:
            raise SettingsError(
                "freshness_blocked_after_ns must exceed freshness_degraded_after_ns "
                f"({self.freshness_blocked_after_ns} <= {self.freshness_degraded_after_ns})"
            )

    def json(self) -> bytes:
        """Serialize to JSON, closing the `Path` encoding-hook gap locally.

        See module docstring finding 3 for why this overrides the inherited
        `NautilusConfig.json()` rather than globally registering a `Path`
        encoder.
        """
        return msgspec.json.encode(self, enc_hook=_encode_hook)

    @classmethod
    def parse(cls, raw: bytes | str) -> BreezySettings:
        """Decode from JSON, closing the `Path` decoding-hook gap locally."""
        return msgspec.json.decode(raw, type=cls, dec_hook=_decode_hook)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> BreezySettings:
        """The sanctioned, type-validated construction entry point.

        Builds a `BreezySettings` via `msgspec.convert(..., strict=True)` --
        the same validated-decode machinery `.parse()` uses for raw JSON
        bytes, just accepting an already-typed Python mapping instead. Per
        the module docstring's finding 1, direct `BreezySettings(...)`
        construction does **not** validate field types or `Meta`
        constraints; `from_env` and any other caller assembling settings
        from already-typed values should route through here rather than
        calling the constructor directly, so a wrong-typed or out-of-range
        field is caught here instead of silently accepted.
        """
        return msgspec.convert(dict(data), type=cls, strict=True, dec_hook=_decode_hook)

    def poll_offset_ns(self, site_index: int) -> int:
        """Return the poll-schedule offset for the site at `site_index`.

        `site_index` is the **zero-based position** of a site within
        `self.sites` (matching Actor construction order), never a
        venue/city lookup key. This is a pure function of the index alone --
        it does not read `self.sites` -- so two differently-sized site lists
        agree on the offset for any given index, which is the property that
        makes "derived, not configured" true rather than aspirational: there
        is no per-site table for two cities to accidentally collide in.
        """
        if site_index < 0:
            raise SettingsError(f"site_index must be >= 0, got {site_index}")
        return site_index * self.poll_stagger_ns

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BreezySettings:
        """Build settings strictly from `env`, defaulting to `os.environ`.

        When `env` is explicitly supplied, it is the **exclusive** source --
        `os.environ` is never consulted, even to fill a gap `env` leaves
        open. This makes settings construction deterministic under test and
        prevents a real deployment's ambient environment from leaking into a
        settings object built for a different purpose (e.g. a dry-run tool
        that intentionally constructs from a partial, explicit mapping). See
        the module docstring for why the native `get_env_key`/`get_env_key_or`
        helpers can only partially serve this method (they are hardcoded to
        `os.environ`, with no mapping parameter).
        """
        using_os_environ = env is None
        source: Mapping[str, str] = env if env is not None else os.environ

        user_agent_contact = source.get(USER_AGENT_ENV_VAR)
        if not user_agent_contact:
            raise SettingsError(
                f"{USER_AGENT_ENV_VAR} is not set. Breezy settings refuse to "
                "construct with a guessed contact address, for the same reason "
                "breezy.ingest.http.HttpTransport refuses to: NWS permanently "
                "blocklists misbehaving clients, so an unmonitored contact "
                "address is worse than refusing to start. Set it to a "
                f"monitored role mailbox, e.g. {DEFAULT_CONTACT!r}."
            )

        sites_raw = source.get(SITES_ENV_VAR)
        if not sites_raw or not sites_raw.strip():
            raise SettingsError(
                f"{SITES_ENV_VAR} is not set; at least one venue/city site is required "
                "(comma-separated 'venue/city' entries, e.g. 'polymarket_us/NYC')."
            )
        sites = _parse_sites(sites_raw)

        catalog_base = _validated_path(source.get(CATALOG_BASE_ENV_VAR), var_name=CATALOG_BASE_ENV_VAR)
        state_store_path = _validated_path(
            source.get(STATE_PATH_ENV_VAR), var_name=STATE_PATH_ENV_VAR
        )

        # The one genuinely correct fit for `get_env_key_or` (see module
        # docstring): a get-with-default read, and only on the branch that
        # already means "os.environ, with a default" -- the explicit-mapping
        # branch cannot use it without breaking the "exclusive mapping"
        # contract, since `get_env_key_or` is hardcoded to `os.environ`.
        if using_os_environ:
            poll_interval_raw = get_env_key_or(POLL_INTERVAL_ENV_VAR, "")
            poll_stagger_raw = get_env_key_or(POLL_STAGGER_ENV_VAR, "")
        else:
            poll_interval_raw = source.get(POLL_INTERVAL_ENV_VAR, "")
            poll_stagger_raw = source.get(POLL_STAGGER_ENV_VAR, "")

        poll_interval_s = _positive_float(
            poll_interval_raw,
            var_name=POLL_INTERVAL_ENV_VAR,
            default=_DEFAULT_POLL_INTERVAL_S,
        )
        poll_stagger_s = _positive_float(
            poll_stagger_raw,
            var_name=POLL_STAGGER_ENV_VAR,
            default=_DEFAULT_POLL_STAGGER_S,
        )

        return cls.from_mapping(
            {
                "sites": sites,
                "catalog_base": catalog_base,
                "state_store_path": state_store_path,
                "poll_interval_ns": int(poll_interval_s * _NS_PER_SECOND),
                "poll_stagger_ns": int(poll_stagger_s * _NS_PER_SECOND),
                "user_agent_contact": user_agent_contact,
                "freshness_degraded_after_ns": _DEFAULT_FRESHNESS_DEGRADED_AFTER_NS,
                "freshness_blocked_after_ns": _DEFAULT_FRESHNESS_BLOCKED_AFTER_NS,
                "parse_timeout_s": _DEFAULT_PARSE_TIMEOUT_S,
                "catalog_io_workers": _DEFAULT_CATALOG_IO_WORKERS,
            }
        )


# ---------------------------------------------------------------------------
# Field-level parsers -- each raises SettingsError naming the variable/value
# ---------------------------------------------------------------------------


def _parse_sites(raw: str) -> tuple[tuple[str, str], ...]:
    """Parse and registry-validate `BREEZY_SITES`.

    Raises `SettingsError` naming the offending entry for: a malformed
    entry (not exactly one `/`), an unknown `(venue, city)` pair, or a
    duplicate entry. Order is preserved -- it is the Actor construction
    order `poll_offset_ns` derives from.
    """
    entries = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    if not entries:
        raise SettingsError(f"{SITES_ENV_VAR} must name at least one venue/city site")

    registry = default_registry()
    parsed: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for entry in entries:
        parts = entry.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise SettingsError(
                f"{SITES_ENV_VAR} entry {entry!r} is not well-formed; expected "
                "exactly one 'venue/city' pair."
            )
        pair = (parts[0], parts[1])
        if pair in seen:
            raise SettingsError(f"{SITES_ENV_VAR} lists {entry!r} more than once")
        seen.add(pair)

        try:
            registry.settlement_site(pair[0], pair[1])
        except SiteNotFoundError as exc:
            raise SettingsError(
                f"{SITES_ENV_VAR} entry {entry!r} is not a known (venue, city) pair "
                "in the settlement-site registry."
            ) from exc

        parsed.append(pair)

    return tuple(parsed)


def _validated_path(raw: str | None, *, var_name: str) -> Path:
    """Require, then canonicalize (realpath), an environment-supplied path.

    Required absolute so the resolved value never depends on the invoking
    process's current working directory -- a settlement-grade daemon's
    filesystem targets must not vary with how it happens to be launched.
    Resolved via `os.path.realpath` (collapses `..` components and resolves
    symlinks to their real target) before being trusted, the same rigor
    `ingest/http.py` applies to network-derived path segments, applied here
    to config-derived ones per the task's standing project constraint.
    """
    if not raw or not raw.strip():
        raise SettingsError(f"{var_name} is not set")
    if not raw.startswith("/"):
        raise SettingsError(f"{var_name} must be an absolute path, got {raw!r}")
    return Path(os.path.realpath(raw))


def _positive_float(raw: str | None, *, var_name: str, default: float) -> float:
    """Parse a positive float, or apply `default` if `raw` is absent.

    Absence and malformation are different failures: an unset variable
    silently takes the documented default (see the module docstring's
    "Where each default came from"), while a *present but malformed* value
    always raises, naming `var_name` -- there is no silent coercion of a
    bad value to the default.
    """
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError(f"{var_name} must be a number, got {raw!r}") from exc
    if math.isnan(value):
        raise SettingsError(f"{var_name} must be a finite positive number, got {raw!r}")
    if value <= 0:
        raise SettingsError(f"{var_name} must be a positive number, got {value!r}")
    return value
