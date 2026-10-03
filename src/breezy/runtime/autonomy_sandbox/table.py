"""The autonomy bwrap table, its row types and ``validate_table`` (plan r5, AC-1/AC-9).

Pure data and pure validation: no filesystem access, no subprocess, stdlib only.
``validate_table`` is the first gate in the wrapper's check order (a failure is
exit 78); every rule has a failing fixture in ``test_autonomy_sandbox_table.py``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

#: The seven exception labels a row may carry (E-7e(e)). There is no user-bus
#: label and no bus-action label: the user bus is never reachable in a sandbox.
KNOWN_EXCEPTIONS: Final[frozenset[str]] = frozenset(
    {
        "E7A_R2_PROC",
        "E7A_R2_NOTIFY",
        "E7A_R2_RECONCILE",
        "E7B_EVAL_OFFLINE_ADAPTER_MODULES",
        "E7_CONFIG_DIR",
        "E7_STUDIES_LOCK",
        "E7_FIXTURE_ROOT",
    }
)
DEFAULT_BIND_BASE: Final = "data_root"
#: Alternate bind bases, relative to the home directory (``E7_FIXTURE_ROOT`` rows).
ALTERNATE_BIND_BASES: Final[Mapping[str, str]] = MappingProxyType(
    {"aut4_fixture": ".local/share/breezy-autonomy-fixture"}
)
#: ``--size`` for ``--tmpfs /tmp`` on a row that sets no ``tmpfs_size_bytes`` (E-13 ER-1),
#: and the largest value any row may set. A malformed value fails closed (exit 78).
DEFAULT_TMPFS_SIZE_BYTES: Final = 256 * 1024**2
MAX_TMPFS_SIZE_BYTES: Final = 16 * 1024**3
NOTIFIER_FALLBACK_ROWS: Final[frozenset[str]] = frozenset()
AUTONOMY_OWNED_UNITS: Final[frozenset[str]] = frozenset()
#: unit -> its E-7a rule-5 citation. Empty in seam B; filled by AUT-1.
UNWRAPPED_RESIDUAL_UNITS: Final[Mapping[str, str]] = MappingProxyType({})
#: unit -> owning-plan citation. Row units that are NOT autonomy-owned and only have their
#: wrapper lines linted (B6-R4). Empty in seam B; AUT-1 adds the recorder in its own commit.
WRAPPER_LINE_ONLY_UNITS: Final[Mapping[str, str]] = MappingProxyType({})

#: ``credential_env`` keys are applied by ``--setenv`` AFTER the fixed
#: environment, so a table edit could otherwise override it (B5-R4).
CREDENTIAL_ENV_DENIED_EXACT: Final[frozenset[str]] = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "GLIBC_TUNABLES",
        "GCONV_PATH",
        "LOCPATH",
        "NOTIFY_SOCKET",
        "CREDENTIALS_DIRECTORY",
        "BASH_ENV",
        "NODE_OPTIONS",
    }
)
CREDENTIAL_ENV_DENIED_PREFIXES: Final[tuple[str, ...]] = (
    "XDG_",
    "LD_",
    "PYTHON",
    "BREEZY_AUTONOMY_",
    "SSL_CERT_",
)
#: A bus read may never name a property carrying a unit's environment or credentials (B6-R3).
_SECRET_PROPERTY_MARKERS: Final[tuple[str, ...]] = ("Environment", "Credential")
_PROPERTY_OPTION_PREFIX: Final = "--property="

#: The only home-relative config paths a row may bind read-only (B6-R2).
CONFIG_RO_ALLOWLIST: Final[frozenset[str]] = frozenset({".config/systemd/user"})

SYSTEMCTL: Final = "/usr/bin/systemctl"
#: The read verbs of the bus-snapshot grammar. ``kill``/``start``/``stop``/
#: ``restart``/``try-restart`` and ``systemd-run`` are structurally absent.
BUS_READ_VERBS: Final[frozenset[str]] = frozenset({"show", "list-units", "list-timers"})
#: The one and only ``run-*`` bus read (M40: ``'run-*.service'`` matches exactly
#: the failed transient, where ``'run-*'`` also matches mounts).
RUN_TRANSIENT_SHOW_ARGV: Final[tuple[str, ...]] = (
    SYSTEMCTL,
    "--user",
    "show",
    "-p",
    "Id,Description,ExecStart,InvocationID,Result,Transient",
    "--",
    "run-*.service",
)
INSTANCE_TOKEN: Final = "{instance}"
BUS_SNAPSHOT_BUDGET_RANGE_S: Final = (1, 25)
BUS_SNAPSHOT_BIND_PREFIX: Final = "cache/"
POSITIVE_PROBE_KINDS: Final[frozenset[str]] = frozenset({"tmpfile", "subdir"})

ROW_NAME_RE: Final = re.compile(r"breezy-[a-z0-9-]+(@[a-z0-9-]*)?([.#][a-z0-9-]+)?")
UNIT_ENTRY_RE: Final = re.compile(r"breezy-[a-z0-9-]+(\.service|@)")
UNIT_INSTANCE_RE: Final = re.compile(r"[a-z0-9][a-z0-9@_.-]{0,200}")
_CREDENTIAL_NAME_RE: Final = re.compile(r"[a-z][a-z0-9_]*")
_CREDENTIAL_ENV_KEY_RE: Final = re.compile(r"[A-Z][A-Z0-9_]*")
_PROPERTY_RE: Final = re.compile(r"[A-Za-z,]+")
_PROPERTY_OPTION_RE: Final = re.compile(r"--property=[A-Za-z,]+")
_STATE_OPTION_RE: Final = re.compile(r"--state=[a-z]+")
_TYPE_OPTION_RE: Final = re.compile(r"--type=[a-z]+")
_UNIT_TOKEN_RE: Final = re.compile(r"breezy-[a-z0-9@._*-]+")
_BARE_OPTIONS: Final[frozenset[str]] = frozenset(
    {"--all", "--plain", "--no-legend", "--no-pager", "--failed", "--value"}
)
_SERVICE_SUFFIX: Final = ".service"
_RESIDUAL_CITATION_MARKER: Final = "E-7a"


class TableError(ValueError):
    """The table (or one row) breaks a ``validate_table`` rule. Build-time only."""


@dataclass(frozen=True, slots=True)
class BusRead:
    """One read-only ``systemctl --user`` call made unsandboxed in ``ExecStartPre``."""

    name: str
    argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PositiveProbe:
    """What the self-probe may create inside one bind: a ``tmpfile`` or a ``subdir``."""

    kind: str


@dataclass(frozen=True, slots=True)
class SandboxRoots:
    """The host paths a row's binds and ``/run`` re-binds resolve against."""

    home: Path
    data_root: Path
    repo_root: Path
    python_prefix: Path
    uid: int
    run_user: Path


@dataclass(frozen=True, slots=True)
class BwrapRow:
    """One wrapped unit's sandbox shape. ``resolves_dns`` is required (no default)."""

    name: str
    owner_plan: str
    units: frozenset[str]
    binds: tuple[str, ...]
    entry_modules: tuple[str, ...]
    resolves_dns: bool
    bind_base: str = DEFAULT_BIND_BASE
    host_proc: bool = False
    studies_lock: bool = False
    credential_names: tuple[str, ...] = ()
    credential_env: Mapping[str, str] = MappingProxyType({})
    config_ro_binds: tuple[str, ...] = ()
    config_ro_dirs: tuple[str, ...] = ()
    bus_reads: tuple[BusRead, ...] = ()
    bus_snapshot_bind: str | None = None
    bus_snapshot_budget_s: int | None = None
    tmpfs_size_bytes: int | None = None
    exceptions: frozenset[str] = frozenset()
    notifier_fallback: bool = False
    positive_probe: Mapping[str, PositiveProbe] = MappingProxyType({})


_SELFTEST_BIND: Final = "cache/autonomy_selftest"
_SELFTEST_ENTRY: Final = ("breezy.runtime.autonomy_sandbox.selftest_cli",)


def _selftest_row(suffix: str, **flags: Any) -> BwrapRow:
    name = f"breezy-autonomy-selftest{suffix}"
    return BwrapRow(
        name=name,
        owner_plan="ARCH-0",
        units=frozenset({f"{name}{_SERVICE_SUFFIX}"}),
        binds=(_SELFTEST_BIND,),
        entry_modules=_SELFTEST_ENTRY,
        **flags,
    )


#: The seam B rows. They run only as transient ``systemd-run --unit=<name>`` units.
AUTONOMY_BWRAP_TABLE: Final[Mapping[str, BwrapRow]] = MappingProxyType(
    {
        row.name: row
        for row in (
            _selftest_row(
                "",
                resolves_dns=True,
                bus_reads=(
                    BusRead(
                        "self_show",
                        (
                            SYSTEMCTL,
                            "--user",
                            "show",
                            "-p",
                            "Id,ActiveState",
                            "--",
                            "breezy-autonomy-selftest.service",
                        ),
                    ),
                ),
                bus_snapshot_bind=_SELFTEST_BIND,
                bus_snapshot_budget_s=10,
            ),
            _selftest_row(
                "-notify",
                resolves_dns=False,
                exceptions=frozenset({"E7A_R2_NOTIFY"}),
            ),
            _selftest_row(
                "-proc",
                resolves_dns=False,
                host_proc=True,
                studies_lock=True,
                exceptions=frozenset({"E7A_R2_PROC", "E7_STUDIES_LOCK"}),
            ),
        )
    }
)


def unit_matches_row(row: BwrapRow, leaf: str) -> bool:
    """True iff ``leaf`` is one of the row's units, or ``name@<instance>.service``."""
    if leaf in row.units:
        return True
    if not leaf.endswith(_SERVICE_SUFFIX):
        return False
    stem = leaf[: -len(_SERVICE_SUFFIX)]
    for unit in row.units:
        if (
            unit.endswith("@")
            and stem.startswith(unit)
            and UNIT_INSTANCE_RE.fullmatch(stem[len(unit) :])
        ):
            return True
    return False


def _fail(row: str, message: str) -> TableError:
    return TableError(f"row {row!r}: {message}")


def _check_identity(key: str, row: BwrapRow) -> None:
    if key != row.name:
        raise _fail(row.name, f"table key {key!r} differs from the row name")
    if not ROW_NAME_RE.fullmatch(row.name):
        raise _fail(row.name, "name does not match the row grammar")
    if not row.units or not all(UNIT_ENTRY_RE.fullmatch(unit) for unit in row.units):
        raise _fail(row.name, "units must be a non-empty set of breezy-*.service or breezy-*@")
    for flag in ("resolves_dns", "host_proc", "studies_lock", "notifier_fallback"):
        if type(getattr(row, flag)) is not bool:
            raise _fail(row.name, f"{flag} must be a bool")
    size = row.tmpfs_size_bytes
    if size is not None and (type(size) is not int or not 0 < size <= MAX_TMPFS_SIZE_BYTES):
        raise _fail(
            row.name, "tmpfs_size_bytes must be an int in (0, MAX_TMPFS_SIZE_BYTES] or None"
        )


def _check_labels(row: BwrapRow) -> None:
    unknown = row.exceptions - KNOWN_EXCEPTIONS
    if unknown:
        raise _fail(row.name, f"unknown exception label(s) {sorted(unknown)}")
    pairs = (
        (row.host_proc, "E7A_R2_PROC", "host_proc"),
        (row.studies_lock, "E7_STUDIES_LOCK", "studies_lock"),
        (row.bind_base != DEFAULT_BIND_BASE, "E7_FIXTURE_ROOT", "a non-default bind_base"),
    )
    for flag, label, what in pairs:
        if flag != (label in row.exceptions):
            raise _fail(row.name, f"{what} holds exactly when {label} is declared")
    if row.bind_base != DEFAULT_BIND_BASE and row.bind_base not in ALTERNATE_BIND_BASES:
        raise _fail(row.name, "bind_base is not a known alternate base")


def _check_credentials(row: BwrapRow) -> None:
    names, env = row.credential_names, row.credential_env
    declared = "E7A_R2_RECONCILE" in row.exceptions
    if not (bool(names) == bool(env) == declared):
        raise _fail(
            row.name,
            "credential_names, credential_env and E7A_R2_RECONCILE hold together or not at all",
        )
    if len(set(names)) != len(names) or not all(_CREDENTIAL_NAME_RE.fullmatch(n) for n in names):
        raise _fail(row.name, "credential_names must be unique lowercase file names")
    if set(env.values()) != set(names):
        raise _fail(row.name, "credential_env values must equal the set of credential_names")
    for key in env:
        if not _CREDENTIAL_ENV_KEY_RE.fullmatch(key):
            raise _fail(row.name, "credential_env keys must match ^[A-Z][A-Z0-9_]*$")
        if key in CREDENTIAL_ENV_DENIED_EXACT or key.startswith(CREDENTIAL_ENV_DENIED_PREFIXES):
            raise _fail(row.name, f"credential_env key {key!r} is denied (B5-R4)")


def _rel_parts(row: str, rel: object, what: str) -> tuple[str, ...]:
    if not isinstance(rel, str):
        raise _fail(row, f"{what} must be a string")
    parts = tuple(rel.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise _fail(row, f"{what} {rel!r} must be a normalised relative path")
    return parts


def _check_binds(row: BwrapRow) -> None:
    parts = [_rel_parts(row.name, rel, "bind") for rel in row.binds]
    for one in parts:
        if one[0] == "state":
            raise _fail(row.name, "a bind may never be or sit under state/")
    for index, one in enumerate(parts):
        for other in parts[index + 1 :]:
            shorter = min(len(one), len(other))
            if one[:shorter] == other[:shorter]:
                raise _fail(row.name, "binds must be distinct and not nested")
    config = (*row.config_ro_binds, *row.config_ro_dirs)
    for rel in config:
        _rel_parts(row.name, rel, "config bind")
    if config and "E7_CONFIG_DIR" not in row.exceptions:
        raise _fail(row.name, "config binds require the E7_CONFIG_DIR exception")
    if any(rel not in CONFIG_RO_ALLOWLIST for rel in config):
        raise _fail(row.name, "config bind is not on the CONFIG_RO_ALLOWLIST allowlist")
    for rel, probe in row.positive_probe.items():
        if rel not in row.binds or probe.kind not in POSITIVE_PROBE_KINDS:
            raise _fail(row.name, "positive_probe needs a bound path and a known kind")


def _check_bus_read(row: str, read: BusRead) -> None:
    argv = read.argv
    if not isinstance(argv, tuple) or not all(isinstance(token, str) for token in argv):
        raise _fail(row, f"bus read {read.name!r}: argv must be a tuple of strings")
    if argv == RUN_TRANSIENT_SHOW_ARGV:
        return
    if len(argv) < 3 or argv[:2] != (SYSTEMCTL, "--user") or argv[2] not in BUS_READ_VERBS:
        raise _fail(
            row, f"bus read {read.name!r}: only systemctl --user show/list-units/list-timers"
        )
    tokens, index = argv[3:], 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            _check_unit_tokens(row, read.name, tokens[index + 1 :])
            return
        if token == "-p":
            index += 1
            if index >= len(tokens) or not _PROPERTY_RE.fullmatch(tokens[index]):
                raise _fail(row, f"bus read {read.name!r}: -p takes exactly one property token")
            _check_property_names(row, read.name, tokens[index])
        elif not _is_bare_option(token):
            raise _fail(row, f"bus read {read.name!r}: option {token!r} is not in the grammar")
        elif token.startswith(_PROPERTY_OPTION_PREFIX):
            _check_property_names(row, read.name, token[len(_PROPERTY_OPTION_PREFIX) :])
        index += 1


def _check_property_names(row: str, name: str, value: str) -> None:
    if any(marker in value for marker in _SECRET_PROPERTY_MARKERS):
        raise _fail(
            row, f"bus read {name!r}: Environment/Credential properties are refused (B6-R3)"
        )


def _is_bare_option(token: str) -> bool:
    return (
        token in _BARE_OPTIONS
        or _PROPERTY_OPTION_RE.fullmatch(token) is not None
        or _STATE_OPTION_RE.fullmatch(token) is not None
        or _TYPE_OPTION_RE.fullmatch(token) is not None
    )


def _check_unit_tokens(row: str, name: str, units: tuple[str, ...]) -> None:
    if not units:
        raise _fail(row, f"bus read {name!r}: '--' must be followed by unit tokens")
    for unit in units:
        if unit != INSTANCE_TOKEN and not _UNIT_TOKEN_RE.fullmatch(unit):
            raise _fail(row, f"bus read {name!r}: unit token {unit!r} is not in the grammar")


def _check_bus(row: BwrapRow) -> None:
    names = [read.name for read in row.bus_reads]
    if len(set(names)) != len(names):
        raise _fail(row.name, "bus read names must be unique")
    for read in row.bus_reads:
        _check_bus_read(row.name, read)
    budget, bind = row.bus_snapshot_budget_s, row.bus_snapshot_bind
    low, high = BUS_SNAPSHOT_BUDGET_RANGE_S
    if not row.bus_reads:
        if bind is not None or budget is not None:
            raise _fail(row.name, "a snapshot bind/budget exists only when bus_reads is non-empty")
        return
    if bind is None or bind not in row.binds or not bind.startswith(BUS_SNAPSHOT_BIND_PREFIX):
        raise _fail(row.name, "bus_snapshot_bind must be one of the binds, under cache/")
    if type(budget) is not int or not low <= budget <= high:
        raise _fail(row.name, f"bus_snapshot_budget_s must be an int in [{low}, {high}]")


def _check_residual(
    table: Mapping[str, BwrapRow],
    owned_units: frozenset[str],
    residual_units: Mapping[str, str],
) -> None:
    row_units = frozenset(unit for row in table.values() for unit in row.units)
    for unit, citation in residual_units.items():
        if unit in owned_units or unit in row_units:
            raise TableError(f"residual unit {unit!r} must be disjoint from owned and row units")
        if not isinstance(citation, str) or _RESIDUAL_CITATION_MARKER not in citation:
            raise TableError(f"residual unit {unit!r} needs an E-7a rule-5 citation")


def _check_line_only(
    table: Mapping[str, BwrapRow],
    owned_units: frozenset[str],
    residual_units: Mapping[str, str],
    line_only_units: Mapping[str, str],
) -> None:
    row_units = frozenset(unit for row in table.values() for unit in row.units)
    for unit, citation in line_only_units.items():
        if unit not in row_units:
            raise TableError(f"wrapper-line-only unit {unit!r} must be listed by a row")
        if unit in owned_units or unit in residual_units:
            raise TableError(f"wrapper-line-only unit {unit!r} must not be owned or residual")
        if not isinstance(citation, str) or not citation:
            raise TableError(f"wrapper-line-only unit {unit!r} needs an owning-plan citation")


def validate_table(
    table: Mapping[str, BwrapRow] = AUTONOMY_BWRAP_TABLE,
    *,
    owned_units: frozenset[str] = AUTONOMY_OWNED_UNITS,
    residual_units: Mapping[str, str] = UNWRAPPED_RESIDUAL_UNITS,
    wrapper_line_only_units: Mapping[str, str] = WRAPPER_LINE_ONLY_UNITS,
) -> None:
    """Raise ``TableError`` on the first rule the table breaks; return ``None`` if sound."""
    if not table:
        raise TableError("the table has no rows")
    for key, row in table.items():
        _check_identity(key, row)
        _check_labels(row)
        _check_credentials(row)
        _check_binds(row)
        _check_bus(row)
    _check_residual(table, owned_units, residual_units)
    _check_line_only(table, owned_units, residual_units, wrapper_line_only_units)
