"""The unit-file lint (plan r5 AC-5, E-7a rule 1): wrapped units stay wrapped.

``lint_units(unit_dir, table)`` reads ``*.service``, ``*.timer`` and ``*.service.d/*.conf``
and returns every violation as a ``LintError`` (it never raises on a bad unit; an invalid
*table* still raises ``TableError``).

Scope. Full lint: every owned unit and every unit any row lists, except units in
``wrapper_line_only_units`` (B6-R4; empty in seam B), which get their **wrapper lines only**
linted. A unit naming the wrapper that no row lists is an error. Units in
``residual_units`` must not name the wrapper. Every ``breezy-autonomy-*.service`` file must be
in one of those scopes (tripwire), and every owned unit must have a file. Transient row units
(the seam B selftest rows) have no file and need none.

Full lint, per unit (drop-ins merged in file order, an empty assignment resets a list):

* every ``ExecStart=``/``ExecStopPost=`` is ``timeout -k K T`` -> (``flock``) -> wrapper -> a
  row listing the unit, with no ``+`` or ``!`` prefix; there is no ``ExecStartPost=``;
* every ``OnFailure=`` target is in scope; ``breezy-study-failed@`` is refused by name;
* ``E7A_R2_NOTIFY`` rows need ``NotifyAccess=all``; ``E7A_R2_RECONCILE`` rows need exactly one
  ``LoadCredential=`` per ``credential_names`` entry;
* ``ExecStartPre=`` lines are only (1) ``timeout -k 1 4`` ``install -d``/``chmod`` lines, then
  (2) iff the row has ``studies_lock``: the exact ``touch`` line (never ``install``: it replaces
  the inode), then (3) iff the row has ``bus_reads``: the exact ``--bus-snapshot`` line, last;
* each pre line's ``T + K`` is below ``TimeoutStartSec`` (M35: ``-`` does not survive systemd's
  own timeout).
"""

from __future__ import annotations

import math
import re
import shlex
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_OWNED_UNITS,
    ROW_NAME_RE,
    UNWRAPPED_RESIDUAL_UNITS,
    BwrapRow,
    effective_line_only_units,
    validate_table,
)

WRAPPER_PATH: Final = "/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap"
TIMEOUT: Final = "/usr/bin/timeout"
FLOCK: Final = "/usr/bin/flock"
TOUCH_LINE: Final = f"-{TIMEOUT} -k 1 4 /usr/bin/touch %t/breezy-studies.lock"
LOCK_NAME: Final = "breezy-studies.lock"
DEFAULT_TIMEOUT_START_SEC: Final = 90
AUTONOMY_PREFIX: Final = "breezy-autonomy-"
STUDY_FAILED_NOTIFIER: Final = "breezy-study-failed@"
BUS_SNAPSHOT_KILL_AFTER_S: Final = 2
BUS_SNAPSHOT_OUTER_MARGIN_S: Final = 3
BUS_TIMEOUT_START_SLACK_S: Final = 10
_SERVICE: Final = ".service"
_TEMPLATE_SUFFIX: Final = "@.service"
_EXEC_PREFIX_CHARS: Final = "@-:+!|"
_FORBIDDEN_EXEC_KEYS: Final = ("ExecStop", "ExecReload", "ExecCondition")
_ALL_EXEC_KEYS: Final = frozenset(
    {
        "ExecStart",
        "ExecStartPre",
        "ExecStartPost",
        "ExecStop",
        "ExecStopPost",
        "ExecReload",
        "ExecCondition",
    }
)
_SERVICE_DROPIN_DIR: Final = ".service.d"
_TOP_LEVEL_DROPIN_DIR: Final = "service.d"
_DURATION_RE: Final = re.compile(r"\d+(?:\.\d+)?[smhd]?")
_FLOCK_FLAGS: Final = frozenset({"-n", "-x", "-s"})
_FORM1_COMMANDS: Final = {"/usr/bin/install": "-d", "/usr/bin/chmod": None}
_SYSTEMD_TIME_UNITS: Final = {
    "": 1.0,
    "us": 1e-6,
    "usec": 1e-6,
    "ms": 1e-3,
    "msec": 1e-3,
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "min": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0,
    "day": 86400.0,
    "days": 86400.0,
}
_TIME_TOKEN_RE: Final = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]*)")
_PRE_FORM: Final = {"install": 1, "touch": 2, "snapshot": 3}


@dataclass(frozen=True, slots=True)
class LintError:
    """One violation: the unit file name, a stable rule code and a path-free message."""

    unit: str
    rule: str
    message: str


Entry = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class UnitFile:
    """Parsed directives in file order. ``values`` applies the empty-assignment reset."""

    entries: tuple[Entry, ...]

    def values(self, section: str, key: str) -> list[str]:
        found: list[str] = []
        for sec, name, value in self.entries:
            if (sec, name) != (section, key):
                continue
            if value == "":
                found.clear()
            else:
                found.append(value)
        return found


def _logical_lines(text: str) -> Iterable[str]:
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if pending:
            line = f"{pending} {line}"
            pending = ""
        if line.endswith("\\"):
            pending = line[:-1].strip()
            continue
        yield line
    if pending:
        yield pending


def parse_unit(*texts: str) -> UnitFile:
    """Parse one unit file, or a unit file followed by its drop-ins, into one directive list."""
    entries: list[Entry] = []
    for text in texts:
        section = ""
        for line in _logical_lines(text):
            if not line or line[0] in "#;":
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif "=" in line:
                key, _, value = line.partition("=")
                entries.append((section, key.strip(), value.strip()))
    return UnitFile(tuple(entries))


def _seconds(text: str) -> float | None:
    """A systemd time span in seconds; ``None`` for ``infinity``; ``ValueError`` if unparsable."""
    cleaned = text.strip().lower()
    if cleaned == "infinity":
        return None
    total, position = 0.0, 0
    for match in _TIME_TOKEN_RE.finditer(cleaned):
        if cleaned[position : match.start()].strip() or match.group(2) not in _SYSTEMD_TIME_UNITS:
            raise ValueError(text)
        total += float(match.group(1)) * _SYSTEMD_TIME_UNITS[match.group(2)]
        position = match.end()
    if position == 0 or cleaned[position:].strip():
        raise ValueError(text)
    return total


def _timeout_start_s(unit: UnitFile) -> float | None:
    value = str(DEFAULT_TIMEOUT_START_SEC)
    for section, key, setting in unit.entries:
        if section == "Service" and key in ("TimeoutStartSec", "TimeoutSec"):
            value = setting
    return _seconds(value)


def _split(line: str) -> tuple[str, list[str]]:
    """``(prefix characters, tokens)`` of an ``Exec*=`` value; ``ValueError`` if unquotable."""
    stripped = line.lstrip(_EXEC_PREFIX_CHARS)
    return line[: len(line) - len(stripped)], shlex.split(stripped)


def _timeout_bound_s(tokens: Sequence[str]) -> int | None:
    """``K + T`` for a ``timeout -k K T ...`` line, else ``None``."""
    if (
        len(tokens) >= 4
        and tokens[0] == TIMEOUT
        and tokens[1] == "-k"
        and _DURATION_RE.fullmatch(tokens[2])
        and _DURATION_RE.fullmatch(tokens[3])
    ):
        seconds = [_seconds(token) for token in (tokens[2], tokens[3])]
        return math.ceil(sum(value for value in seconds if value is not None))
    return None


def _pre_bound_s(line: str, start_s: float | None) -> int:
    try:
        bound = _timeout_bound_s(_split(line)[1])
    except ValueError:
        bound = None
    if bound is not None:
        return bound
    return DEFAULT_TIMEOUT_START_SEC if start_s is None else math.ceil(start_s)


def _unit_text_files(unit_dir: Path, name: str) -> list[Path]:
    main = unit_dir / name
    dropins = sorted((unit_dir / f"{name}.d").glob("*.conf"))
    return ([main] if main.is_file() else []) + [d for d in dropins if d.is_file()]


def _load(unit_dir: Path, name: str) -> UnitFile:
    return parse_unit(*(path.read_text() for path in _unit_text_files(unit_dir, name)))


def start_phase_bound_s(unit_path: Path) -> int:
    """The sum, over the unit's ``ExecStartPre=`` lines, of each line's own bound.

    A line wrapped in ``timeout -k K T`` counts ``K + T``; any other counts ``TimeoutStartSec``
    (``TimeoutStartSec`` re-arms per command, M35). ``ExecStart``'s bound is its own ``timeout``.
    Drop-ins beside ``unit_path`` are merged. For the E-9 owners.
    """
    unit = _load(unit_path.parent, unit_path.name)
    start_s = _timeout_start_s(unit)
    return sum(_pre_bound_s(line, start_s) for line in unit.values("Service", "ExecStartPre"))


# ---------------------------------------------------------------- scope helpers


def _entry(unit_name: str) -> str:
    """The row-``units`` spelling of a unit file name.

    ``name@.service`` and the instance file ``name@x.service`` both give ``name@`` (B6-R6).
    """
    if "@" in unit_name and unit_name.endswith(_SERVICE):
        return unit_name.split("@", 1)[0] + "@"
    return unit_name


def _file_name(entry: str) -> str:
    """The unit file name of a row-``units`` entry (``name@`` -> ``name@.service``)."""
    return entry + _SERVICE if entry.endswith("@") else entry


def _lists(row: BwrapRow, unit_name: str) -> bool:
    return _entry(unit_name) in row.units


def _service_names(unit_dir: Path) -> set[str]:
    names: set[str] = set()
    for path in unit_dir.glob("*.service"):
        names.add(path.name)
    for path in unit_dir.glob("*.service.d"):
        if path.is_dir():
            names.add(path.name.removesuffix(".d"))
    return names


# ---------------------------------------------------------------- exec lines


def _err(unit: str, rule: str, message: str) -> LintError:
    return LintError(unit, rule, message)


def _check_wrapped_tokens(
    unit: str, tokens: Sequence[str], rows: Mapping[str, BwrapRow]
) -> list[LintError]:
    """The ``timeout -k`` -> (``flock``) -> wrapper -> row shape of one ``Exec`` line."""
    if WRAPPER_PATH not in tokens:
        return [_err(unit, "not_wrapped", "an Exec line does not go through the wrapper")]
    if _timeout_bound_s(tokens) is None:
        return [_err(unit, "wrapper_order", "the wrapper line must start with timeout -k K T")]
    index = 4
    if index < len(tokens) and tokens[index] == FLOCK:
        index += 1
        while index < len(tokens) and (tokens[index] in _FLOCK_FLAGS or tokens[index] == "-w"):
            index += 2 if tokens[index] == "-w" else 1
        index += 1  # the lock path
    if index + 1 >= len(tokens) or tokens[index] != WRAPPER_PATH:
        return [
            _err(
                unit,
                "wrapper_order",
                "expected timeout -k, then flock, then the wrapper, then a row",
            )
        ]
    if not ROW_NAME_RE.fullmatch(tokens[index + 1]):
        return [_err(unit, "wrapper_order", "the wrapper must be followed directly by a row name")]
    row = rows.get(tokens[index + 1])
    if row is None:
        return [_err(unit, "unknown_row", "the wrapper line names a row that is not in the table")]
    if not _lists(row, unit):
        return [_err(unit, "row_not_listing_unit", "the named row does not list this unit")]
    return []


def _check_exec_line(
    unit: str, line: str, rows: Mapping[str, BwrapRow], *, wrapper_lines_only: bool
) -> list[LintError]:
    if wrapper_lines_only and WRAPPER_PATH not in line:
        return []
    errors: list[LintError] = []
    if ";" in line:
        errors.append(_err(unit, "exec_semicolon", "an Exec line may not contain ';' (B6-R5)"))
    try:
        prefix, tokens = _split(line)
    except ValueError:
        return errors + [_err(unit, "not_wrapped", "an Exec line could not be parsed")]
    if prefix:
        errors.append(_err(unit, "exec_prefix", "ExecStart/ExecStopPost allow no prefix (B6-R7)"))
    return errors + _check_wrapped_tokens(unit, tokens, rows)


# ---------------------------------------------------------------- pre lines


def _snapshot_line(row: BwrapRow) -> str:
    budget = row.bus_snapshot_budget_s or 0
    outer = budget + BUS_SNAPSHOT_OUTER_MARGIN_S
    head = f"-{TIMEOUT} -k {BUS_SNAPSHOT_KILL_AFTER_S} {outer}"
    return f"{head} {WRAPPER_PATH} --bus-snapshot {row.name}"


def _is_form1(tokens: Sequence[str], line: str) -> bool:
    if LOCK_NAME in line or tokens[:4] != [TIMEOUT, "-k", "1", "4"] or len(tokens) < 6:
        return False
    required = _FORM1_COMMANDS.get(tokens[4], "absent")
    if required == "absent":
        return False
    return required is None or tokens[5] == required


def _classify_pre(line: str) -> str:
    """``install`` | ``touch`` | ``snapshot`` | ``other``."""
    normal = " ".join(line.split())
    if normal == TOUCH_LINE:
        return "touch"
    if WRAPPER_PATH in line or "--bus-snapshot" in line:
        return "snapshot"
    try:
        tokens = shlex.split(line)
    except ValueError:
        return "other"
    return "install" if _is_form1(tokens, line) else "other"


def _pre_hygiene_errors(unit: str, lines: Sequence[str], exact: set[str]) -> list[LintError]:
    """``;`` anywhere is red; a prefix character is red unless the line is an exact ``-`` form."""
    errors: list[LintError] = []
    for line in lines:
        if ";" in line:
            errors.append(_err(unit, "exec_semicolon", "an Exec line may not contain ';' (B6-R5)"))
        if line[:1] in _EXEC_PREFIX_CHARS and " ".join(line.split()) not in exact:
            errors.append(_err(unit, "exec_prefix", "ExecStartPre allows only the exact - forms"))
    return errors


def _check_pre_lines(
    unit: str, lines: Sequence[str], rows: Sequence[BwrapRow], start_s: float | None
) -> list[LintError]:
    errors: list[LintError] = []
    kinds = [_classify_pre(line) for line in lines]
    wanted_snapshots = [" ".join(_snapshot_line(r).split()) for r in rows if r.bus_reads]
    errors += _pre_hygiene_errors(unit, lines, {TOUCH_LINE, *wanted_snapshots})
    for kind in kinds:
        if kind == "other":
            errors.append(_err(unit, "pre_form", "ExecStartPre is not a permitted form"))
    ranks = [_PRE_FORM[k] for k in kinds if k in _PRE_FORM]
    if ranks != sorted(ranks):
        errors.append(
            _err(unit, "pre_order", "pre lines must be install, then touch, then the snapshot")
        )
    touches = kinds.count("touch")
    if touches != (1 if any(r.studies_lock for r in rows) else 0):
        errors.append(
            _err(unit, "pre_lock_form", "exactly the studies rows carry exactly one touch line")
        )
    present = [
        " ".join(line.split()) for line, k in zip(lines, kinds, strict=True) if k == "snapshot"
    ]
    if sorted(present) != sorted(wanted_snapshots):
        errors.append(
            _err(unit, "pre_snapshot", "each bus row needs exactly one snapshot pre line")
        )
    return errors + _check_pre_bounds(unit, lines, start_s)


def _check_pre_bounds(unit: str, lines: Sequence[str], start_s: float | None) -> list[LintError]:
    if not lines:
        return []
    errors: list[LintError] = []
    for line in lines:
        try:
            tokens = _split(line)[1]
        except ValueError:
            continue
        bound = _timeout_bound_s(tokens)
        if bound is not None and start_s is not None and not bound < start_s:
            errors.append(
                _err(
                    unit, "pre_bound", f"a pre line bound of {bound} s is not below TimeoutStartSec"
                )
            )
    return errors


# ---------------------------------------------------------------- per-unit lint


def _targets(unit: UnitFile) -> list[str]:
    return " ".join(unit.values("Unit", "OnFailure")).split()


def _target_entry(target: str) -> str:
    if "@" in target:
        return target.split("@", 1)[0] + "@"
    return target


def _check_onfailure(unit: str, file: UnitFile, scope_entries: frozenset[str]) -> list[LintError]:
    errors: list[LintError] = []
    for target in _targets(file):
        if target.startswith(STUDY_FAILED_NOTIFIER):
            errors.append(
                _err(
                    unit,
                    "onfailure_study_failed",
                    f"OnFailure names {STUDY_FAILED_NOTIFIER}; use breezy-autonomy-failed@",
                )
            )
        elif _target_entry(target) not in scope_entries:
            errors.append(
                _err(unit, "onfailure_scope", "an OnFailure target is not an in-scope wrapped unit")
            )
    return errors


def _check_row_directives(unit: str, file: UnitFile, rows: Sequence[BwrapRow]) -> list[LintError]:
    errors: list[LintError] = []
    if any("E7A_R2_NOTIFY" in row.exceptions for row in rows):
        access = file.values("Service", "NotifyAccess")
        if not access or access[-1] != "all":
            errors.append(_err(unit, "notify_access", "E7A_R2_NOTIFY rows need NotifyAccess=all"))
    needed = sorted(
        name
        for row in rows
        if "E7A_R2_RECONCILE" in row.exceptions
        for name in row.credential_names
    )
    if needed:
        given = sorted(v.split(":", 1)[0] for v in file.values("Service", "LoadCredential"))
        if given != needed:
            errors.append(
                _err(unit, "loadcredential", "exactly one LoadCredential= per credential name")
            )
    return errors


def _lint_full(
    unit: str,
    file: UnitFile,
    rows_by_name: Mapping[str, BwrapRow],
    scope_entries: frozenset[str],
) -> list[LintError]:
    own_rows = [row for row in rows_by_name.values() if _lists(row, unit)]
    errors: list[LintError] = []
    execs = file.values("Service", "ExecStart") + file.values("Service", "ExecStopPost")
    for line in execs:
        errors += _check_exec_line(unit, line, rows_by_name, wrapper_lines_only=False)
    if file.values("Service", "ExecStartPost"):
        errors.append(_err(unit, "execstartpost", "an owned unit may not carry ExecStartPost="))
    for key in _FORBIDDEN_EXEC_KEYS:
        if file.values("Service", key):
            errors.append(_err(unit, "exec_directive_forbidden", f"{key}= is not allowed"))
    errors += _check_onfailure(unit, file, scope_entries)
    errors += _check_row_directives(unit, file, own_rows)
    start_s = _timeout_start_s_checked(file, unit, errors)
    errors += _check_pre_lines(unit, file.values("Service", "ExecStartPre"), own_rows, start_s)
    errors += _check_bus_start_timeout(unit, own_rows, start_s)
    return errors


def _check_bus_start_timeout(
    unit: str, rows: Sequence[BwrapRow], start_s: float | None
) -> list[LintError]:
    """B9-R3: a bus row's ``TimeoutStartSec`` must be at least ``budget_s + 10``."""
    if start_s is None:
        return []
    return [
        _err(
            unit,
            "pre_bound",
            f"TimeoutStartSec {start_s:g} s is below bus budget {row.bus_snapshot_budget_s} + 10",
        )
        for row in rows
        if row.bus_reads and start_s < (row.bus_snapshot_budget_s or 0) + BUS_TIMEOUT_START_SLACK_S
    ]


def _timeout_start_s_checked(file: UnitFile, unit: str, errors: list[LintError]) -> float | None:
    try:
        return _timeout_start_s(file)
    except ValueError:
        errors.append(_err(unit, "pre_bound", "TimeoutStartSec is not a parseable time span"))
        return 0.0


def _lint_wrapper_lines_only(
    unit: str, file: UnitFile, rows_by_name: Mapping[str, BwrapRow]
) -> list[LintError]:
    errors: list[LintError] = []
    for key in ("ExecStart", "ExecStopPost", "ExecStartPost"):
        for line in file.values("Service", key):
            errors += _check_exec_line(unit, line, rows_by_name, wrapper_lines_only=True)
    own_rows = [row for row in rows_by_name.values() if _lists(row, unit)]
    wanted = [" ".join(_snapshot_line(r).split()) for r in own_rows if r.bus_reads]
    for line in file.values("Service", "ExecStartPre"):
        if WRAPPER_PATH in line and ";" in line:
            errors.append(_err(unit, "exec_semicolon", "an Exec line may not contain ';' (B6-R5)"))
        if WRAPPER_PATH in line and " ".join(line.split()) not in wanted:
            errors.append(
                _err(unit, "pre_snapshot", "the bus-snapshot pre line is not the exact form")
            )
    return errors


# ---------------------------------------------------------------- entry point


def lint_units(
    unit_dir: Path,
    table: Mapping[str, BwrapRow],
    *,
    owned_units: frozenset[str] = AUTONOMY_OWNED_UNITS,
    residual_units: Mapping[str, str] = UNWRAPPED_RESIDUAL_UNITS,
    wrapper_line_only_units: Mapping[str, str] | None = None,
) -> tuple[LintError, ...]:
    """Lint every in-scope unit under ``unit_dir`` against ``table``; ``()`` means clean."""
    wrapper_line_only_units = effective_line_only_units(table, wrapper_line_only_units)
    validate_table(
        table,
        owned_units=owned_units,
        residual_units=residual_units,
        wrapper_line_only_units=wrapper_line_only_units,
    )
    row_entries = frozenset(unit for row in table.values() for unit in row.units)
    owned = frozenset(_entry(unit) for unit in owned_units)
    residual = frozenset(_entry(unit) for unit in residual_units)
    line_only = frozenset(_entry(unit) for unit in wrapper_line_only_units)
    scope_entries = row_entries | owned
    errors: list[LintError] = []
    present = _service_names(unit_dir)
    for unit in sorted(present):
        errors += _lint_one(
            unit_dir, unit, table, (owned, residual, line_only), row_entries, scope_entries
        )
    errors += _dropin_exec_errors(unit_dir, scope_entries | line_only)
    for unit in sorted(owned_units):
        if not _unit_text_files(unit_dir, _file_name(unit)):
            errors.append(_err(unit, "owned_no_file", "an owned unit has no unit file"))
    for timer in sorted(unit_dir.glob("*.timer")):
        if WRAPPER_PATH in timer.read_text():
            errors.append(
                _err(timer.name, "timer_names_wrapper", "a timer may not name the wrapper")
            )
    return tuple(errors)


def _dropin_applies(dirname: str, scope_entries: frozenset[str]) -> bool:
    """Does systemd apply this ``*.service.d`` directory to an in-scope unit? (B6-R6)"""
    if dirname == _TOP_LEVEL_DROPIN_DIR:
        return True
    if not dirname.endswith(_SERVICE_DROPIN_DIR):
        return False
    name = dirname[: -len(".d")]
    if _entry(name) in scope_entries:
        return True
    stem = name[: -len(_SERVICE)]
    if not stem.endswith("-"):
        return False
    return any(_file_name(entry).startswith(stem) for entry in scope_entries)


def _dropin_exec_errors(unit_dir: Path, scope_entries: frozenset[str]) -> list[LintError]:
    """Any ``Exec*`` directive in an in-scope drop-in is an error: drop-ins may not run code."""
    errors: list[LintError] = []
    candidates = [*unit_dir.glob(f"*{_SERVICE_DROPIN_DIR}"), unit_dir / _TOP_LEVEL_DROPIN_DIR]
    for directory in sorted(candidates):
        if not directory.is_dir() or not _dropin_applies(directory.name, scope_entries):
            continue
        for conf in sorted(directory.glob("*.conf")):
            keys = {key for _, key, _ in parse_unit(conf.read_text()).entries}
            if keys & _ALL_EXEC_KEYS:
                errors.append(
                    _err(
                        f"{directory.name}/{conf.name}",
                        "drop_in_exec",
                        "a drop-in on an in-scope unit may not set or reset Exec directives",
                    )
                )
    return errors


def _lint_one(
    unit_dir: Path,
    unit: str,
    table: Mapping[str, BwrapRow],
    classes: tuple[frozenset[str], frozenset[str], frozenset[str]],
    row_entries: frozenset[str],
    scope_entries: frozenset[str],
) -> list[LintError]:
    texts = [path.read_text() for path in _unit_text_files(unit_dir, unit)]
    file = parse_unit(*texts)
    owned, residual, line_only = classes
    entry = _entry(unit)
    names_wrapper = any(WRAPPER_PATH in text for text in texts)
    if entry in residual:
        if names_wrapper:
            return [
                _err(
                    unit, "residual_wrapped", "an unwrapped-residual unit may not name the wrapper"
                )
            ]
        return []
    if entry in line_only:
        return _lint_wrapper_lines_only(unit, file, table)
    if entry in owned or entry in row_entries:
        return _lint_full(unit, file, table, scope_entries)
    if names_wrapper:
        return [
            _err(
                unit,
                "wrapper_unit_not_in_row",
                "a unit naming the wrapper must be listed by a row (or be owned)",
            )
        ]
    if unit.startswith(AUTONOMY_PREFIX):
        return [_err(unit, "tripwire", "an autonomy unit file is outside every lint scope")]
    return []
