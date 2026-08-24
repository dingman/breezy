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

`BREEZY_SITES` has deliberately **no "all sites" default**. A production
deployment must state which `(venue, city)` pairs it serves; a partial
deployment (e.g. during a staged rollout) must be an explicit, visible
choice in the environment, never an inferred one. Cross-checking the parsed
pairs against the site registry is NOT this module's job -- that happens at
the composition root via `SharedIngestState`, which is the single place
that already owns a `SiteRegistry` instance.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

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

_DEFAULT_TRADER_ID = "BREEZY-001"
_DEFAULT_POLL_INTERVAL_SECONDS = 300
_DEFAULT_PARSE_TIMEOUT_MS = 250
_DEFAULT_LOG_LEVEL = "INFO"

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
    required value or malformed value. Does NOT cross-check `sites` against
    the site registry -- see the module docstring.
    """
    active_env: Mapping[str, str] = os.environ if env is None else env

    trader_id = active_env.get(_TRADER_ID_VAR, _DEFAULT_TRADER_ID)
    sites = _parse_sites(_require(active_env, _SITES_VAR))
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

    registry_path_raw = active_env.get(_REGISTRY_PATH_VAR)
    registry_path = Path(registry_path_raw) if registry_path_raw else None
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
