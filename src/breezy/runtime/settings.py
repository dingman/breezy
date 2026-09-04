"""Process-wide runtime settings for the Breezy composition root.

Every field is read from an **injected** `env: Mapping[str, str]` mapping,
defaulting to `os.environ` -- never read from `os.environ` directly inside
the parsing logic -- so the whole surface is testable without monkeypatching
the real process environment.

This module imports no `nautilus_trader`: it is a plain, pre-Nautilus
configuration layer that the composition root consumes before any Actor,
Trader, or Nautilus kernel object is constructed.

`BREEZY_USER_AGENT` is deliberately **never read here**. It is owned
exclusively by `breezy.ingest.http` (`HttpTransport`'s own env-var reader);
a second reader in this module would be a second, competing policy for the
same variable.

`BREEZY_SITES` is an **override, not a requirement** (G-19 item B4). Which
cities exist is a VENUE FACT, and the bot must discover venue facts itself
-- an operator who has to recite the city list into an environment file is
supplying something the venue already publishes. Unset therefore means
"every `(venue, city)` Breezy holds settlement truth for", read from the
site registry in force (`BREEZY_REGISTRY_PATH`, else the packaged
`sites.toml`). Setting it narrows a run deliberately, which is a real
operational need during a staged rollout; setting it BLANK is still a
malformed value and is still refused.

That default is the registry, not the venue payload, on purpose. The
registry is the narrower of the two and is the one that carries settlement
truth, so deriving from it can never enable a city Breezy cannot settle.
The venue side of the intersection is derived by
`breezy.adapters.polymarket_us.series.derive_site_pairs`, which refuses --
loudly -- if the venue trades a city with no registry entry;
`tests/unit/test_polymarket_us_series.py` pins the two sets equal against
the captured venue payloads, so the over-approximation here is a CHECKED
equality rather than an assumption. Cross-checking an explicitly configured
`BREEZY_SITES` against the registry remains the composition root's job via
`SharedIngestState`.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from breezy.registry.sites import RegistryError, default_registry, load_registry

_TRADER_ID_VAR = "BREEZY_TRADER_ID"
_SITES_VAR = "BREEZY_SITES"
_CATALOG_BASE_VAR = "BREEZY_CATALOG_BASE"
_STATE_DB_VAR = "BREEZY_STATE_DB"
_POLL_INTERVAL_VAR = "BREEZY_POLL_INTERVAL_SECONDS"
_PARSE_TIMEOUT_VAR = "BREEZY_PARSE_TIMEOUT_MS"
_LOG_LEVEL_VAR = "BREEZY_LOG_LEVEL"
_ALLOW_PROXY_ENV_VAR = "BREEZY_ALLOW_PROXY_ENV"
_REGISTRY_PATH_VAR = "BREEZY_REGISTRY_PATH"
_HEALTH_SNAPSHOT_DIR_VAR = "BREEZY_HEALTH_SNAPSHOT_DIR"
#: Read ONLY by :func:`load_quote_tape_settings`, never by
#: :func:`load_settings`. See that function's docstring for why the venue
#: role is loaded separately.
QUOTE_TAPE_CATALOG_VAR = "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"
_QUOTE_TAPE_MIN_FREE_BYTES_WARNING_VAR = (
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_WARNING"
)
_QUOTE_TAPE_MIN_FREE_BYTES_ERROR_VAR = "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_ERROR"
_QUOTE_TAPE_MAX_FILE_BYTES_WARNING_VAR = (
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_WARNING"
)
_QUOTE_TAPE_MAX_FILE_BYTES_ERROR_VAR = "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_ERROR"
_QUOTE_TAPE_DISK_CHECK_INTERVAL_VAR = (
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_DISK_CHECK_INTERVAL_SECONDS"
)

#: The TRADING role's own trader id. Read ONLY by
#: :func:`load_trade_settings`, and deliberately a DIFFERENT variable from
#: ``BREEZY_TRADER_ID`` with NO default.
#:
#: ``TraderId`` is stamped on every order and every position the trading
#: process will ever create. Two reasons this is separate and required:
#:
#: * a host provisioned only for weather ingestion carries
#:   ``BREEZY_TRADER_ID`` (which defaults anyway), so reusing it would let a
#:   collector host start a trading process by accident -- the fail-OPEN
#:   direction, on the one process that can eventually spend money;
#: * an order attributed to the collector's shared ``BREEZY-001`` is
#:   ambiguous in the venue's records and in ours.
#:
#: There is no default because there is no correct value to invent.
TRADE_TRADER_ID_VAR = "BREEZY_TRADE_TRADER_ID"

#: BL-24 Seam B section 6: registers the per-station NWS observation Actors
#: on the TRADING node. OFF unless set to exactly ``"1"`` -- absent or any
#: other value registers nothing. Parsed in the `_parse_check_proxy_env`
#: idiom. The ingest node and the tape recorder never read it.
LIVE_OBSERVATIONS_VAR = "BREEZY_LIVE_OBSERVATIONS"

#: Shadow-mode ``current_rung_hold`` enablement for the TRADING role. OFF
#: unless set to exactly ``"1"``. Requires :data:`LIVE_OBSERVATIONS_VAR` --
#: the strategy prices against ``StationObservation``, so enabling it without
#: the publisher would latch ``observation_unavailable`` on every station-day
#: and burn the one trial. The tape recorder never reads this variable.
CURRENT_RUNG_HOLD_VAR = "BREEZY_CURRENT_RUNG_HOLD"

#: Trade-role catalog root used as the pre-build discovery source when
#: :data:`CURRENT_RUNG_HOLD_VAR` is on. Distinct from
#: :data:`QUOTE_TAPE_CATALOG_VAR`, which remains the recorder's single-reader
#: contract. Required, absolute, no ``..`` segment, only when the flag is on.
TRADE_CATALOG_ROOT_VAR = "BREEZY_TRADE_CATALOG_ROOT"

#: CRH enablement step 8 (converged review item 7): a build-side REQUEST
#: for the order path to be reachable, not an enablement by itself. OFF
#: unless set to exactly ``"1"`` -- same idiom as :data:`LIVE_OBSERVATIONS_VAR`
#: and :data:`CURRENT_RUNG_HOLD_VAR`. Requires both of those to already be on:
#: the strategy has no order path to gate without ``current_rung_hold``, and
#: no fresh price to gate it against without ``live_observations``. This
#: field is a REQUEST that ``runtime.order_enablement.issue_order_submission_
#: permit`` reads and validates alongside five other preconditions -- it is
#: never, on its own, sufficient to submit an order. It is a build-side flag,
#: not an operator-reserved control, so its name may appear in tracked files.
ORDERS_ENABLED_VAR = "BREEZY_ORDERS_ENABLED"

_DEFAULT_TRADER_ID = "BREEZY-001"

#: G-19 item B11 asked for this to be derived from the NWS CLI issuance
#: cadence. It is NOT derivable, and the reasoning is recorded here so the
#: question is not re-opened.
#:
#: The cadence the repo actually holds is "two issuances per day per site"
#: (`src/breezy/ingest/product_index.py:72`, and the preliminary ~16:44 /
#: final ~02:27 local instants in the `nws-cli-settlement` skill). A poll interval is not a
#: function of that cadence: it is a DETECTION-LATENCY choice -- how long a
#: published product may sit unfetched -- bounded below by api.weather.gov
#: politeness and above by the settlement deadline. Two issuances per day
#: constrains it only to "well under ten hours", which is four orders of
#: magnitude wider than the value in use. Any formula yielding 300 would be
#: reverse-engineered from the answer, which is worse than an honest constant.
#:
#: 300 s = five sites polled once per five minutes = 1 request per site per
#: 300 s, and a missed product is caught within five minutes of issuance.
#: `BREEZY_POLL_INTERVAL_SECONDS` overrides it.
_DEFAULT_POLL_INTERVAL_SECONDS = 300
_DEFAULT_PARSE_TIMEOUT_MS = 250
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_QUOTE_TAPE_DISK_CHECK_INTERVAL_SECONDS = 30

#: NautilusTrader's genuine accepted set, verified against the installed
#: package (`nautilus_trader.core.nautilus_pyo3.LogLevel`), not the stdlib
#: `logging` module's level names -- `WARN`/`CRITICAL` are `logging`
#: aliases NOT present on Nautilus's `LogLevel` and must be rejected here.
_SUPPORTED_LOG_LEVELS = frozenset({"OFF", "TRACE", "DEBUG", "INFO", "WARNING", "ERROR"})
_STATE_DB_RELATIVE_PATH = Path("state") / "breezy-state.sqlite3"


class SettingsError(ValueError):
    """Raised when the runtime settings environment is missing or malformed.

    Every message names the offending environment variable, so a
    misconfigured deployment fails loudly and specifically rather than with
    a bare `ValueError`.
    """


@dataclass(frozen=True, slots=True)
class BreezyRuntimeSettings:
    """Validated, immutable process-wide runtime configuration.

    Construct only via `load_settings` -- the constructor takes fully
    validated data so that all validation happens in one place, at load
    time, exactly like `breezy.registry.sites.SiteRegistry`.
    """

    trader_id: str
    sites: tuple[tuple[str, str], ...]
    catalog_base: Path
    state_db_path: Path
    poll_interval_seconds: int
    parse_timeout_ms: int
    log_level: str
    check_proxy_env: bool
    registry_path: Path | None
    #: Directory the per-site health snapshots are written into, or
    #: `None` (the default) for "feature off, write nothing". A
    #: DIRECTORY rather than a file path because each Actor knows only
    #: its own site: five Actors sharing one file would clobber each
    #: other. `breezy.runtime.composition.site_snapshot_path` derives
    #: the one file per `(venue, city)` beneath it.
    health_snapshot_dir: Path | None = None


def _require(env: Mapping[str, str], var: str) -> str:
    value = env.get(var)
    if value is None:
        raise SettingsError(f"{var} is required and was not set")
    return value


def _parse_sites(raw: str) -> tuple[tuple[str, str], ...]:
    stripped = raw.strip()
    if not stripped:
        raise SettingsError(f"{_SITES_VAR} must not be empty")

    pairs: list[tuple[str, str]] = []
    for entry in stripped.split(","):
        candidate = entry.strip()
        if not candidate:
            raise SettingsError(
                f"{_SITES_VAR} contains a blank entry (check for a stray comma): {raw!r}"
            )
        parts = candidate.split(":")
        if len(parts) != 2:
            raise SettingsError(
                f"{_SITES_VAR} entry {candidate!r} must have exactly one ':' "
                "separating venue and city"
            )
        venue, city = parts[0].strip(), parts[1].strip()
        if not venue or not city:
            raise SettingsError(
                f"{_SITES_VAR} entry {candidate!r} must have a non-blank venue and city"
            )
        pairs.append((venue, city))

    if len(set(pairs)) != len(pairs):
        raise SettingsError(f"{_SITES_VAR} contains a duplicate (venue, city) pair: {raw!r}")

    return tuple(pairs)


def _registry_site_pairs(registry_path: Path | None) -> tuple[tuple[str, str], ...]:
    """Every `(venue, city)` in the registry in force, in file order.

    This is the ONLY filesystem read `load_settings` performs, and it happens
    only when `BREEZY_SITES` is unset -- the override path neither pays for it
    nor fails on it. `RegistryError` and the `OSError` family are re-raised as
    `SettingsError` naming `BREEZY_REGISTRY_PATH`, because from the operator's
    point of view this IS a configuration failure and must exit as one rather
    than as an unhandled traceback.
    """
    try:
        registry = default_registry() if registry_path is None else load_registry(registry_path)
    except (RegistryError, OSError, ValueError) as exc:
        raise SettingsError(
            f"{_SITES_VAR} is unset, so the active site set is derived from the "
            f"site registry, but the registry could not be loaded "
            f"({_REGISTRY_PATH_VAR}={registry_path}): {exc}"
        ) from exc
    return registry.pairs()


def _resolve_sites(
    env: Mapping[str, str], registry_path: Path | None
) -> tuple[tuple[str, str], ...]:
    """Return the configured site set, or derive it when `BREEZY_SITES` is unset.

    Unset is NOT an error (G-19 B4): the city universe is a venue fact and the
    bot derives it. A blank or malformed value still is an error -- that is an
    operator mistake, not an absence of opinion.
    """
    raw = env.get(_SITES_VAR)
    if raw is None:
        derived = _registry_site_pairs(registry_path)
        if not derived:
            raise SettingsError(
                f"{_SITES_VAR} is unset and the site registry holds no sites, so "
                "there is nothing to run; refusing to start with an empty site set"
            )
        return derived
    return _parse_sites(raw)


def _parse_positive_int(env: Mapping[str, str], var: str, default: int) -> int:
    raw = env.get(var)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{var} must be an integer, was {raw!r}") from exc
    if value <= 0:
        raise SettingsError(f"{var} must be a positive integer, was {raw!r}")
    return value


def _parse_log_level(env: Mapping[str, str]) -> str:
    raw = env.get(_LOG_LEVEL_VAR, _DEFAULT_LOG_LEVEL)
    normalized = raw.upper()
    if normalized not in _SUPPORTED_LOG_LEVELS:
        raise SettingsError(
            f"{_LOG_LEVEL_VAR} must be one of "
            f"{sorted(_SUPPORTED_LOG_LEVELS)} (NautilusTrader's LogLevel), was {raw!r}"
        )
    return normalized


def _parse_check_proxy_env(env: Mapping[str, str]) -> bool:
    return env.get(_ALLOW_PROXY_ENV_VAR) != "1"


def _parse_live_observations(env: Mapping[str, str]) -> bool:
    return env.get(LIVE_OBSERVATIONS_VAR) == "1"


def _parse_current_rung_hold(env: Mapping[str, str]) -> bool:
    return env.get(CURRENT_RUNG_HOLD_VAR) == "1"


def _parse_orders_enabled(env: Mapping[str, str]) -> bool:
    return env.get(ORDERS_ENABLED_VAR) == "1"


def _parse_trade_catalog_root(env: Mapping[str, str]) -> Path:
    """Parse :data:`TRADE_CATALOG_ROOT_VAR`; required, absolute, no ``..``."""
    raw = _require(env, TRADE_CATALOG_ROOT_VAR)
    if not raw.strip():
        raise SettingsError(f"{TRADE_CATALOG_ROOT_VAR} is required and must not be blank")
    if "\x00" in raw:
        raise SettingsError(f"{TRADE_CATALOG_ROOT_VAR} must not contain a NUL byte")
    catalog_root = Path(raw.strip())
    if not catalog_root.is_absolute():
        raise SettingsError(
            f"{TRADE_CATALOG_ROOT_VAR} must be an absolute path, was {raw!r}"
        )
    if any(part == ".." for part in catalog_root.parts):
        raise SettingsError(
            f"{TRADE_CATALOG_ROOT_VAR} must not contain a '..' segment, was {raw!r}"
        )
    return catalog_root


def proxy_env_check_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether proxy/TLS environment hygiene is enforced.

    Public because the Polymarket.us adapter factory needs the SAME answer as
    `runtime/composition.py` without depending on a fully-built `Settings`:
    `LiveDataClientFactory.create` receives only loop/name/config/msgbus/
    cache/clock (`live/factories.py:33-39`). One operator switch,
    `BREEZY_ALLOW_PROXY_ENV`, governs both transports rather than two.
    """
    return _parse_check_proxy_env(os.environ if env is None else env)


def _parse_health_snapshot_dir(env: Mapping[str, str]) -> Path | None:
    """Parse `BREEZY_HEALTH_SNAPSHOT_DIR`; `None` when unset.

    Unset is deliberately VALID -- an unconfigured deployment writes no
    snapshot at all rather than dropping artifacts in whatever directory
    the process happened to start in.

    Set-but-malformed fails fast, naming the variable, exactly like every
    other setting here. Three rejections, each with a production failure
    behind it:

    * blank/whitespace -- an operator who meant to unset it instead wrote an
      empty value, and `Path("")` is `Path(".")`, silently the CWD;
    * relative -- resolves against the process CWD, which under systemd is
      not a property the operator controls, so the snapshot lands somewhere
      nobody monitors and the runbook's "stale file means the process is
      dead" check reads a path that never existed;
    * embedded NUL -- accepted by `Path()` and rejected only later by the
      first syscall, i.e. inside the poll cycle rather than at startup.

    No filesystem I/O: this module stays pure, and the directory is created
    (with its parents) by `write_snapshot_atomic` at first write.
    """
    raw = env.get(_HEALTH_SNAPSHOT_DIR_VAR)
    if raw is None:
        return None
    if not raw.strip():
        raise SettingsError(
            f"{_HEALTH_SNAPSHOT_DIR_VAR} must not be blank; unset it entirely to "
            "disable health snapshots"
        )
    if "\x00" in raw:
        raise SettingsError(f"{_HEALTH_SNAPSHOT_DIR_VAR} must not contain a NUL byte")
    path = Path(raw)
    if not path.is_absolute():
        raise SettingsError(
            f"{_HEALTH_SNAPSHOT_DIR_VAR} must be an absolute path, was {raw!r}"
        )
    return path


def load_settings(env: Mapping[str, str] | None = None) -> BreezyRuntimeSettings:
    """Load and validate `BreezyRuntimeSettings` from `env`.

    `env` defaults to `os.environ` but is always taken as a parameter, so
    every code path here is exercised in tests against an explicit mapping
    rather than the real process environment.

    Raises `SettingsError` naming the offending variable for any missing
    required value or malformed value. Does NOT cross-check an explicitly
    configured `sites` against the site registry -- see the module docstring.
    When `BREEZY_SITES` is unset the site set is DERIVED from that registry
    and is therefore registry-valid by construction.
    """
    active_env: Mapping[str, str] = os.environ if env is None else env

    trader_id = active_env.get(_TRADER_ID_VAR, _DEFAULT_TRADER_ID)
    registry_path_raw = active_env.get(_REGISTRY_PATH_VAR)
    registry_path = Path(registry_path_raw) if registry_path_raw else None
    sites = _resolve_sites(active_env, registry_path)
    catalog_base = Path(_require(active_env, _CATALOG_BASE_VAR))

    state_db_raw = active_env.get(_STATE_DB_VAR)
    state_db_path = Path(state_db_raw) if state_db_raw else catalog_base / _STATE_DB_RELATIVE_PATH

    poll_interval_seconds = _parse_positive_int(
        active_env, _POLL_INTERVAL_VAR, _DEFAULT_POLL_INTERVAL_SECONDS
    )
    parse_timeout_ms = _parse_positive_int(
        active_env, _PARSE_TIMEOUT_VAR, _DEFAULT_PARSE_TIMEOUT_MS
    )
    log_level = _parse_log_level(active_env)
    check_proxy_env = _parse_check_proxy_env(active_env)

    health_snapshot_dir = _parse_health_snapshot_dir(active_env)

    return BreezyRuntimeSettings(
        trader_id=trader_id,
        sites=sites,
        catalog_base=catalog_base,
        state_db_path=state_db_path,
        poll_interval_seconds=poll_interval_seconds,
        parse_timeout_ms=parse_timeout_ms,
        log_level=log_level,
        check_proxy_env=check_proxy_env,
        registry_path=registry_path,
        health_snapshot_dir=health_snapshot_dir,
    )


# ---------------------------------------------------------------------------
# G-19 B10 -- tape disk thresholds, derived from the volume the tape lands on
# ---------------------------------------------------------------------------

_MIB = 1024**2
_GIB = 1024**3

#: Fraction of the volume that must stay free before the ERROR floor trips.
#: The WARNING floor is exactly twice this, so the two can never invert.
_FREE_ERROR_FRACTION = 0.05
#: Absolute floor for the ERROR threshold on volumes small enough that 5% is
#: a handful of bytes. Capped by `_FREE_MAX_TOTAL_FRACTION` so it can never
#: exceed the volume it is measured against.
_FREE_ERROR_FLOOR_BYTES = 512 * _MIB
#: Absolute ceiling. Without it, 5% of a 128 TiB array is 6.5 TiB -- an alarm
#: no operator can ever satisfy, which is the same as no alarm at all.
_FREE_ERROR_CEILING_BYTES = 25 * _GIB
#: Hard cap as a fraction of the volume. Guarantees the WARNING floor (2x the
#: error floor) stays at or under a quarter of the disk, so a small volume
#: scales the thresholds DOWN instead of alarming from the moment it is empty.
_FREE_MAX_TOTAL_FRACTION = 0.125

#: One daily tape file (`QUOTE_TAPE_ROTATION_INTERVAL` is one day) is expected
#: to be megabytes for a handful of weather markets. These thresholds are a
#: FRAME-STORM detector, not a capacity plan: a day consuming a sixtieth of
#: the whole volume is anomalous by orders of magnitude.
_FILE_WARNING_DIVISOR = 60
_FILE_WARNING_FLOOR_BYTES = 16 * _MIB
_FILE_WARNING_CEILING_BYTES = 8 * _GIB
_FILE_MAX_TOTAL_DIVISOR = 24


@dataclass(frozen=True, slots=True)
class DiskThresholds:
    """The four quote-tape disk thresholds, derived or overridden.

    Invariants held by :func:`derive_disk_thresholds` and re-checked against
    any operator override in :func:`load_quote_tape_settings`:
    ``min_free_bytes_error < min_free_bytes_warning`` and
    ``max_file_bytes_warning < max_file_bytes_error``.
    """

    min_free_bytes_warning: int
    min_free_bytes_error: int
    max_file_bytes_warning: int
    max_file_bytes_error: int


def derive_disk_thresholds(total_bytes: int) -> DiskThresholds:
    """Derive the four thresholds from the size of the volume the tape lands on.

    G-19 item B10: only "how much disk am I willing to spend" is an operator
    ceiling; the shape of the alarm is a property of the disk and of the tape's
    daily rotation, both of which the process can see for itself.

    Two failure modes are designed against explicitly, because the monitor
    (`breezy.runtime.quote_tape_disk_monitor`) is ALERT-ONLY -- it never stops
    the recorder, so a badly-calibrated threshold degrades silently:

    * a threshold at or above the whole volume alarms from the first check and
      is trained away. Every derived value is bounded well below `total_bytes`.
    * a threshold so low it never precedes ENOSPC. The free-space WARNING is
      set so at least one more warning-sized daily file fits before the ERROR
      floor, which is the smallest headroom an operator could act on.
    """
    if total_bytes <= 0:
        raise SettingsError(
            "cannot derive quote-tape disk thresholds: the reported disk total "
            f"is {total_bytes} bytes"
        )

    free_error = min(
        max(int(total_bytes * _FREE_ERROR_FRACTION), _FREE_ERROR_FLOOR_BYTES),
        _FREE_ERROR_CEILING_BYTES,
        int(total_bytes * _FREE_MAX_TOTAL_FRACTION),
    )
    file_warning = min(
        max(total_bytes // _FILE_WARNING_DIVISOR, _FILE_WARNING_FLOOR_BYTES),
        _FILE_WARNING_CEILING_BYTES,
        total_bytes // _FILE_MAX_TOTAL_DIVISOR,
    )
    if free_error < 1 or file_warning < 1:
        raise SettingsError(
            "cannot derive quote-tape disk thresholds: the volume is too small "
            f"to alarm meaningfully ({total_bytes} bytes total)"
        )

    return DiskThresholds(
        min_free_bytes_warning=free_error * 2,
        min_free_bytes_error=free_error,
        max_file_bytes_warning=file_warning,
        max_file_bytes_error=file_warning * 2,
    )


def probe_total_bytes(path: Path) -> int:
    """Total bytes of the volume `path` lives on, walking up if it is absent.

    The tape root does not exist on a host's first start -- Nautilus creates it
    on the first write -- so probing it directly would raise `FileNotFoundError`
    and stop the recorder from ever starting. Walking to the nearest existing
    ancestor reports the same volume in every realistic case, and `/` always
    exists, so the walk terminates.
    """
    candidate = path
    while True:
        if candidate.exists():
            return shutil.disk_usage(candidate).total
        parent = candidate.parent
        if parent == candidate:
            raise SettingsError(
                f"cannot size the volume for {path}: no existing ancestor directory"
            )
        candidate = parent


#: Injected so the derivation is testable at simulated disk sizes without a
#: real volume of that size.
TotalBytesProbe = Callable[[Path], int]


@dataclass(frozen=True, slots=True)
class PolymarketUSQuoteTapeSettings:
    """Validated settings for the **quote-tape recorder** role.

    A SEPARATE type from :class:`BreezyRuntimeSettings` on purpose. The two
    are different processes with different jobs and different failure
    consequences:

    * the NWS ingestion process collects weather observations and must start
      on a host that carries no venue configuration at all;
    * the quote-tape recorder connects to Polymarket.us and is useless
      without every venue endpoint.

    Folding the venue variables onto the shared type made them mandatory for
    BOTH, which turned a running weather collector into one that could not
    restart. Role separation is what prevents that class of outage, not
    per-field defaults: defaults would instead let the recorder start
    half-configured and silently record nothing.

    Note what is NOT here: no venue endpoint, slug list, user agent or
    signing variant. Those are owned by
    :func:`breezy.adapters.polymarket_us.factories.config_from_env`, which
    already implements the section 7 environment contract and produces the
    ``PolymarketUSDataClientConfig`` the node needs. Reading them a second
    time here would be a second, competing policy for the same variables --
    exactly what this module's header forbids for ``BREEZY_USER_AGENT``.
    """

    trader_id: str
    log_level: str
    #: Root of the ``ParquetDataCatalog`` the recorded tape lands under.
    #: Absolute, for the same reason ``health_snapshot_dir`` is: under systemd
    #: the process CWD is not a property the operator controls, and a tape
    #: written somewhere nobody reads is indistinguishable from no tape.
    catalog_root: Path
    min_free_bytes_warning: int
    min_free_bytes_error: int
    max_file_bytes_warning: int
    max_file_bytes_error: int
    disk_check_interval_seconds: int


def load_quote_tape_settings(
    env: Mapping[str, str] | None = None,
    *,
    total_bytes_probe: TotalBytesProbe = probe_total_bytes,
) -> PolymarketUSQuoteTapeSettings:
    """Load and validate the quote-tape recorder's own settings.

    Strict where strictness is legitimate: :data:`QUOTE_TAPE_CATALOG_VAR` is a
    deploy path, an operator ceiling, and is required with no default. Every
    rejection names the variable. Calling this is the act of starting the
    recorder role, so failing here fails the right process -- never the weather
    collector.

    The four disk thresholds are NOT required (G-19 item B10). They are derived
    from the size of the volume the tape lands on -- see
    :func:`derive_disk_thresholds` -- and each remains an operator override for
    a deployment that wants to spend less disk than the derivation allows. A
    partial override is deliberately supported and deliberately still checked:
    an override that inverts the ordering against its derived sibling raises,
    rather than quietly producing a monitor that can never fire.
    """
    active_env: Mapping[str, str] = os.environ if env is None else env

    raw = _require(active_env, QUOTE_TAPE_CATALOG_VAR)
    if not raw.strip():
        raise SettingsError(f"{QUOTE_TAPE_CATALOG_VAR} is required and must not be blank")
    if "\x00" in raw:
        raise SettingsError(f"{QUOTE_TAPE_CATALOG_VAR} must not contain a NUL byte")
    catalog_root = Path(raw.strip())
    if not catalog_root.is_absolute():
        raise SettingsError(
            f"{QUOTE_TAPE_CATALOG_VAR} must be an absolute path, was {raw!r}"
        )
    # Refused, not resolved. Normalising would mean the directory an operator
    # reads in the unit file is not the directory the tape lands in, and the
    # tape is the one artifact that cannot be re-created if it lands somewhere
    # unwatched. Compared as a path SEGMENT, so a directory merely named
    # ``tape..v2`` is still legal.
    if any(part == ".." for part in catalog_root.parts):
        raise SettingsError(
            f"{QUOTE_TAPE_CATALOG_VAR} must not contain a '..' segment, was {raw!r}"
        )

    try:
        total_bytes = total_bytes_probe(catalog_root)
    except SettingsError:
        raise
    except OSError as exc:
        raise SettingsError(
            f"cannot size the volume behind {QUOTE_TAPE_CATALOG_VAR}="
            f"{catalog_root}, so the disk thresholds cannot be derived: {exc}"
        ) from exc
    derived = derive_disk_thresholds(total_bytes)

    min_free_bytes_warning = _parse_positive_int(
        active_env,
        _QUOTE_TAPE_MIN_FREE_BYTES_WARNING_VAR,
        derived.min_free_bytes_warning,
    )
    min_free_bytes_error = _parse_positive_int(
        active_env,
        _QUOTE_TAPE_MIN_FREE_BYTES_ERROR_VAR,
        derived.min_free_bytes_error,
    )
    max_file_bytes_warning = _parse_positive_int(
        active_env,
        _QUOTE_TAPE_MAX_FILE_BYTES_WARNING_VAR,
        derived.max_file_bytes_warning,
    )
    max_file_bytes_error = _parse_positive_int(
        active_env,
        _QUOTE_TAPE_MAX_FILE_BYTES_ERROR_VAR,
        derived.max_file_bytes_error,
    )
    disk_check_interval_seconds = _parse_positive_int(
        active_env,
        _QUOTE_TAPE_DISK_CHECK_INTERVAL_VAR,
        _DEFAULT_QUOTE_TAPE_DISK_CHECK_INTERVAL_SECONDS,
    )

    if min_free_bytes_error >= min_free_bytes_warning:
        raise SettingsError(
            f"{_QUOTE_TAPE_MIN_FREE_BYTES_ERROR_VAR} must be less than "
            f"{_QUOTE_TAPE_MIN_FREE_BYTES_WARNING_VAR}"
        )
    if max_file_bytes_error <= max_file_bytes_warning:
        raise SettingsError(
            f"{_QUOTE_TAPE_MAX_FILE_BYTES_ERROR_VAR} must be greater than "
            f"{_QUOTE_TAPE_MAX_FILE_BYTES_WARNING_VAR}"
        )

    return PolymarketUSQuoteTapeSettings(
        trader_id=active_env.get(_TRADER_ID_VAR, _DEFAULT_TRADER_ID),
        log_level=_parse_log_level(active_env),
        catalog_root=catalog_root,
        min_free_bytes_warning=min_free_bytes_warning,
        min_free_bytes_error=min_free_bytes_error,
        max_file_bytes_warning=max_file_bytes_warning,
        max_file_bytes_error=max_file_bytes_error,
        disk_check_interval_seconds=disk_check_interval_seconds,
    )


# ---------------------------------------------------------------------------
# EXEC SPINE R-2 -- the TRADING role
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BreezyTradeSettings:
    """Validated settings for the **trading** role.

    A THIRD type alongside :class:`BreezyRuntimeSettings` and
    :class:`PolymarketUSQuoteTapeSettings`, for the reason the other two are
    separate: three processes, three jobs, three different things that must
    make them refuse to start. Folding the trading role's required identity
    onto a shared type would make it mandatory for the weather collector and
    the recorder as well, which is exactly the outage this repo has already
    taken once.

    Deliberately SMALL. Everything the trading process needs beyond an
    identity and a log level is owned elsewhere and is not re-read here:

    * venue endpoints, user agent and signing belong to
      :func:`breezy.adapters.polymarket_us.factories.config_from_env`, which
      already implements the section 7 environment contract; a second reader
      would be a second competing policy for the same variables;
    * the two OPERATOR-RESERVED controls -- max daily budget and max per
      position -- are **not fields here and never will be**. They are added as
      mechanism in a later increment, they are never given a value by Breezy,
      and their absence must fail closed. A settings field is precisely where
      a default would silently appear, so there is none.
    """

    trader_id: str
    log_level: str
    #: BL-24 Seam B: whether the NWS observation Actors are registered on
    #: this node. Default OFF; see :data:`LIVE_OBSERVATIONS_VAR`.
    live_observations: bool = False
    #: Shadow-mode ``current_rung_hold``. Default OFF; see
    #: :data:`CURRENT_RUNG_HOLD_VAR`. ``orders_enabled`` is not a field here
    #: and cannot be reached from this object.
    current_rung_hold: bool = False
    #: Pre-build discovery catalog, set only when ``current_rung_hold`` is on.
    #: See :data:`TRADE_CATALOG_ROOT_VAR`.
    catalog_root: Path | None = None
    #: CRH enablement step 8: a REQUEST that the order path be reachable.
    #: Default OFF; see :data:`ORDERS_ENABLED_VAR`. This is NOT an
    #: enablement -- it can never, by itself, cause an order to be
    #: submitted. It is one of six preconditions
    #: ``runtime.order_enablement.issue_order_submission_permit`` reads off
    #: this already-loaded settings object (never re-parsing the env) before
    #: minting the sealed, unforgeable ``OrderSubmissionPermit`` that the
    #: strategy actually gates on. Requires ``current_rung_hold`` and
    #: ``live_observations`` to both be True; refused otherwise at load time.
    orders_enabled_requested: bool = False


def load_trade_settings(env: Mapping[str, str] | None = None) -> BreezyTradeSettings:
    """Load and validate the trading process's own settings.

    Exactly one required variable, :data:`TRADE_TRADER_ID_VAR`, with no
    default and no fallback to the collector's ``BREEZY_TRADER_ID``. Calling
    this IS the act of starting the trading role, so failing here fails the
    right process and never the weather collector.

    The trader id's SHAPE is validated later, by
    :func:`breezy.runtime.node_config.validated_trader_id`, which owns that
    rule for all three roles. What is checked here is presence and
    non-blankness -- the part that is an environment-contract question rather
    than an identifier-format one.
    """
    active_env: Mapping[str, str] = os.environ if env is None else env

    raw = _require(active_env, TRADE_TRADER_ID_VAR)
    if not raw.strip():
        raise SettingsError(f"{TRADE_TRADER_ID_VAR} is required and must not be blank")

    live_observations = _parse_live_observations(active_env)
    current_rung_hold = _parse_current_rung_hold(active_env)
    if current_rung_hold and not live_observations:
        raise SettingsError(
            f"{CURRENT_RUNG_HOLD_VAR}=1 requires {LIVE_OBSERVATIONS_VAR}=1: "
            "the strategy prices against StationObservation, so enabling it "
            "without the publisher would latch observation_unavailable on "
            "every station-day and burn the one trial"
        )
    orders_enabled_requested = _parse_orders_enabled(active_env)
    if orders_enabled_requested and not (current_rung_hold and live_observations):
        raise SettingsError(
            f"{ORDERS_ENABLED_VAR}=1 requires {CURRENT_RUNG_HOLD_VAR}=1 and "
            f"{LIVE_OBSERVATIONS_VAR}=1: a request for the order path to be "
            "reachable is meaningless without the strategy and its price "
            "source both enabled"
        )
    catalog_root = _parse_trade_catalog_root(active_env) if current_rung_hold else None

    return BreezyTradeSettings(
        trader_id=raw.strip(),
        log_level=_parse_log_level(active_env),
        live_observations=live_observations,
        current_rung_hold=current_rung_hold,
        catalog_root=catalog_root,
        orders_enabled_requested=orders_enabled_requested,
    )
