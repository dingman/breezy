"""SP-1 (2026-09-12): serialization for the nightly analysis studies.

`breezy-k1-daily.service` and `breezy-mb-daily.service` are two independent
`systemd --user` timers with no shared lock, so they can (and, per the
2026-09-11 incident, did) run concurrently -- each already capped at its own
`MemoryHigh=12G`/`MemoryMax=16G` (`tests/unit/test_analysis_units_memory_capped.py`),
but nothing stops two 12-16G studies stacking at once, nor stops either from
starting beside the live trading node (pid 895135) during its LST-derived
decision window. This module is I2's whole test suite: the protected window
derivation, the shared `breezy-studies.slice` aggregate ceiling, the
host-wide `flock` mutual exclusion in every heavy wrapper, and the
ingest-unit deprioritisation -- see `SP-1.rev4.md` for the full design.

L-27 (A-19): the real-state-directory leak guard. `~/.local/share/breezy/`
is written continuously by the live node, recorder and supervisor, so a
before/after stat-equality check on that directory is RED by construction
during ANY gate run -- see `SP-1.rev4.md`'s "X-L27" item. This module's
guard is a sentinel + byte-offset design instead: a run-unique token is
embedded in every wrapper-test env this module builds; at import time this
module records the CURRENT state (byte offsets on the two real lock paths,
directory listings on the three real wrapper `$OUT` dirs) of an ENUMERATED,
five-path risk scope; `test_no_wrapper_test_wrote_into_the_real_breezy_state_directory`
(placed last in this file, deliberately -- see its own docstring) scans only
the bytes APPENDED since then for the token, and asserts no new path in
scope names the token. `test_the_state_leak_scanner_detects_a_planted_sentinel`
is the guard's own negative control (L-24): a scanner that silently reads
nothing and always passes is worse than no guard at all.

Every subprocess-spawning test in this module builds its env with
`build_wrapper_env` (AM-22, below `test_no_study_wrapper_enables_posix_mode`
once it lands) -- never `os.environ`, `os.environ.copy()`, or a dict
literal -- so the fail-closed check below cannot be bypassed by a
hand-rolled spawn. `build_wrapper_env` itself resolves `HOME` and
`XDG_RUNTIME_DIR` to fresh directories under the test's own `tmp_path`, so a
forgotten override can never silently fall through to the real
`/run/user/1000` or the real `$HOME` -- see `assert_wrapper_env_safe`.
"""

from __future__ import annotations

import ast
import datetime as dt
import fcntl
import os
import re
import subprocess
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEPLOY_DIR: Final[Path] = _REPO_ROOT / "deploy" / "systemd"

#: The REAL `XDG_RUNTIME_DIR`, resolved once at import time -- i.e. before
#: any test in this module has had a chance to build a redirected env for a
#: subprocess spawn (R3-B1). This is the value a mis-redirected wrapper
#: would inherit if a test's constructed env ever forgot the key.
_REAL_XDG_RUNTIME_DIR: Final[str | None] = os.environ.get("XDG_RUNTIME_DIR")

#: The REAL `$HOME`, resolved the same way, for the fallback lock path.
_REAL_HOME: Final[str | None] = os.environ.get("HOME")


class WrapperEnvError(ValueError):
    """Raised by :func:`assert_wrapper_env_safe` / :func:`build_wrapper_env`
    when a subprocess env for a wrapper-spawning test would not be fully
    contained inside the test's own `tmp_path` (R3-B1). Fail-closed: a
    forgotten key is a loud error here, never a silent fall-through to the
    real runtime directory or the real `$HOME`.
    """


#: R4-N2: the one environment variable that turns default GNU bash into
#: POSIX mode at startup, under which `exec … || { …; }` aborts even though
#: the `||` guard is present (measured in SP-1.rev4.md's B3 block). A
#: wrapper-test env must never carry it.
_POSIXLY_CORRECT_KEY: Final[str] = "POSIXLY_CORRECT"

_REQUIRED_KEYS: Final[frozenset[str]] = frozenset({"HOME", "XDG_RUNTIME_DIR"})


def _resolved_inside(path_str: str, tmp_path: Path) -> bool:
    try:
        Path(path_str).resolve().relative_to(tmp_path.resolve())
    except ValueError:
        return False
    return True


def assert_wrapper_env_safe(env: dict[str, str], *, tmp_path: Path) -> None:
    """Fail-closed validation for a wrapper-test subprocess env (R3-B1,
    R4-N2). Raises :class:`WrapperEnvError` when:

    - `HOME` or `XDG_RUNTIME_DIR` is absent from `env`;
    - no key matching `BREEZY_*_OUTPUT_DIR` is present in `env`;
    - `HOME`, `XDG_RUNTIME_DIR`, or any `BREEZY_*_OUTPUT_DIR` value resolves
      OUTSIDE `tmp_path`;
    - `POSIXLY_CORRECT` is present in `env` at all.

    Never mutates `env`. A well-formed env is returned implicitly by not
    raising.
    """
    missing_required = _REQUIRED_KEYS - env.keys()
    if missing_required:
        raise WrapperEnvError(
            f"wrapper-test env is missing required key(s): {sorted(missing_required)}"
        )
    output_dir_keys = [
        key for key in env if key.startswith("BREEZY_") and key.endswith("_OUTPUT_DIR")
    ]
    if not output_dir_keys:
        raise WrapperEnvError(
            "wrapper-test env carries no BREEZY_*_OUTPUT_DIR key -- a wrapper "
            "spawned with this env would default its output dir to the real "
            "~/.local/share/breezy tree"
        )
    if _POSIXLY_CORRECT_KEY in env:
        raise WrapperEnvError(
            "wrapper-test env must never set POSIXLY_CORRECT (R4-N2): it "
            "turns on POSIX mode, the one condition under which the lock "
            "preamble's `exec … || { …; }` aborts despite its guard"
        )
    for key in ("HOME", "XDG_RUNTIME_DIR", *output_dir_keys):
        if not _resolved_inside(env[key], tmp_path):
            raise WrapperEnvError(
                f"wrapper-test env key {key!r} = {env[key]!r} resolves outside "
                f"tmp_path ({tmp_path}) -- refusing to spawn a wrapper that "
                "could reach the real breezy state directory"
            )


def build_wrapper_env(
    tmp_path: Path,
    run_token: str,
    *,
    output_dirs: dict[str, Path],
    xdg_runtime_dir: Path | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """The ONLY way a test in this module may build a subprocess env for a
    wrapper spawn (AM-22 pins this by AST). `HOME` is always a fresh
    directory under `tmp_path`, named with `run_token` so any byte a
    mis-redirected wrapper writes carries it; every `output_dirs` value must
    already be a `BREEZY_*_OUTPUT_DIR`-shaped key pointing inside `tmp_path`.
    Self-validates via :func:`assert_wrapper_env_safe` before returning --
    fail-closed by construction, not by caller discipline.

    `xdg_runtime_dir`, if given, is used AS-IS without being created --
    the lock-infrastructure-failure tests (A-17) deliberately pass a path
    shaped as a blocking FILE or a mode-0500 directory here; the default
    (`None`) creates a fresh, ordinary directory under `tmp_path`.
    """
    home = tmp_path / f"{run_token}-home"
    home.mkdir(parents=True, exist_ok=True)
    if xdg_runtime_dir is None:
        xdg_runtime_dir = tmp_path / f"{run_token}-xdg-runtime"
        xdg_runtime_dir.mkdir(parents=True, exist_ok=True)
    env: dict[str, str] = {
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(xdg_runtime_dir),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    for key, value in output_dirs.items():
        if not (key.startswith("BREEZY_") and key.endswith("_OUTPUT_DIR")):
            raise WrapperEnvError(f"{key!r} is not a BREEZY_*_OUTPUT_DIR key")
        env[key] = str(value)
    if extra:
        env.update(extra)
    assert_wrapper_env_safe(env, tmp_path=tmp_path)
    return env


def new_run_token() -> str:
    """A fresh, run-unique token (A-19 mechanism 1) -- embedded in every
    `tmp_path` name, fake pid, and lock filename a wrapper test constructs,
    so any byte a mis-redirected wrapper writes carries it.
    """
    return f"sp1-leakguard-{uuid.uuid4()}"


@dataclass(frozen=True)
class _RealPathState:
    """Session-start state of one path in the L-27 guard's enumerated
    five-path scope (A-19 mechanism 2)."""

    path: Path
    #: `st_size` at import time, or `None` if the path did not exist yet.
    #: The real `breezy-studies.lock` MAY be present (offset 0) once the
    #: first real wrapper run (`exec 9>>"$LOCK"`, no delete-on-exit by
    #: design) has created it for the lifetime of the tmpfs -- see the
    #: module docstring and SP-1.rev4.md's round-4 measurement block for the
    #: absent-at-that-time baseline. The guard below always compares the
    #: CURRENT state against THIS session-start snapshot, never against a
    #: fixed absent/present assumption.
    offset: int | None
    #: For a directory-scoped entry (the three `$OUT` dirs): the filenames
    #: present at import time, so a later scan can find NEW entries only.
    existing_names: frozenset[str]


def _real_state_scope() -> tuple[_RealPathState, ...]:
    """The enumerated five-path risk scope (A-19 mechanism 2, corrected by
    R3-B1): the wrapper preamble resolves `LOCK_DIR="${XDG_RUNTIME_DIR:-}"`
    FIRST, so `<real XDG_RUNTIME_DIR>/breezy-studies.lock` is the DEFAULT
    lock path, not merely a fallback -- both it and the `$HOME`-fallback
    lock are in scope. The three wrappers' real default `$OUT` directories
    round out the scope. The catalog, state and trade directories are
    outside the wrappers' reach and stay outside this guard.
    """
    entries: list[_RealPathState] = []
    if _REAL_XDG_RUNTIME_DIR:
        lock = Path(_REAL_XDG_RUNTIME_DIR) / "breezy-studies.lock"
        entries.append(
            _RealPathState(
                path=lock,
                offset=lock.stat().st_size if lock.is_file() else None,
                existing_names=frozenset(),
            )
        )
    if _REAL_HOME:
        home = Path(_REAL_HOME)
        fallback_lock = home / ".local" / "share" / "breezy" / "breezy-studies.lock"
        entries.append(
            _RealPathState(
                path=fallback_lock,
                offset=fallback_lock.stat().st_size if fallback_lock.is_file() else None,
                existing_names=frozenset(),
            )
        )
        for subdir in ("k1", "derived", "offer_gate"):
            out_dir = home / ".local" / "share" / "breezy" / subdir
            existing = (
                frozenset(p.name for p in out_dir.iterdir()) if out_dir.is_dir() else frozenset()
            )
            entries.append(_RealPathState(path=out_dir, offset=None, existing_names=existing))
    return tuple(entries)


#: Recorded at IMPORT time -- before any test in this module runs, and
#: therefore before any test could build a redirected env (A-19 mechanism 3).
_SESSION_START_STATE: Final[tuple[_RealPathState, ...]] = _real_state_scope()


def _scan_appended_bytes_for_token(path: Path, recorded_offset: int | None, token: str) -> bool:
    """True if `token` appears in the bytes appended to `path` since
    `recorded_offset` (A-19 mechanism 4). Rotation-tolerant: if the file is
    now SMALLER than the recorded offset, it rotated -- scan the whole
    current file instead of crashing. `recorded_offset is None` means the
    path did not exist at session start, so the whole current file (if any)
    is "appended".
    """
    if not path.is_file():
        return False
    size = path.stat().st_size
    start = 0 if recorded_offset is None or size < recorded_offset else recorded_offset
    with path.open("rb") as fh:
        fh.seek(start)
        appended = fh.read()
    return token.encode("utf-8") in appended


def _new_names_in_scope(state: _RealPathState) -> frozenset[str]:
    """Names present now under `state.path` that were NOT present at
    session start (A-19 mechanism 5, corrected scope: only entries WITHIN
    the enumerated scope, never a blanket "no new file anywhere" -- the
    recorder creates files continuously and that would be flaky for reasons
    unrelated to this guard)."""
    if not state.path.is_dir():
        return frozenset()
    current = frozenset(p.name for p in state.path.iterdir())
    return current - state.existing_names


def test_the_state_leak_scanner_detects_a_planted_sentinel(tmp_path: Path) -> None:
    """L-24 negative control: a scanner that silently reads nothing and
    always passes is worse than no guard at all. The token is planted into a
    fixture-owned file INSIDE `tmp_path` -- never into a real path."""
    token = new_run_token()
    scanned = tmp_path / "planted-sentinel.log"
    scanned.write_text("ordinary log line\n")
    offset = scanned.stat().st_size

    assert _scan_appended_bytes_for_token(scanned, offset, token) is False

    with scanned.open("a") as fh:
        fh.write(f"a wrapper wrote {token} here\n")

    assert _scan_appended_bytes_for_token(scanned, offset, token) is True


def test_the_wrapper_env_fixture_refuses_an_env_without_xdg_runtime_dir(tmp_path: Path) -> None:
    """R3-B1 + R4-N2: the env-building fixture RAISES rather than spawning
    if `XDG_RUNTIME_DIR`, `HOME`, or any `BREEZY_*_OUTPUT_DIR` is absent
    from the constructed env or resolves outside `tmp_path`, and when
    `POSIXLY_CORRECT` is present. Fail-closed: a forgotten key is a loud
    fixture error, never a silent fall-through to the real runtime dir."""
    outside = Path("/tmp") / f"outside-{uuid.uuid4()}"
    well_formed = {
        "HOME": str(tmp_path / "home"),
        "XDG_RUNTIME_DIR": str(tmp_path / "xdg"),
        "BREEZY_K1_OUTPUT_DIR": str(tmp_path / "k1"),
    }

    assert_wrapper_env_safe(dict(well_formed), tmp_path=tmp_path)  # does not raise

    missing_xdg = {k: v for k, v in well_formed.items() if k != "XDG_RUNTIME_DIR"}
    with pytest.raises(WrapperEnvError):
        assert_wrapper_env_safe(missing_xdg, tmp_path=tmp_path)

    missing_home = {k: v for k, v in well_formed.items() if k != "HOME"}
    with pytest.raises(WrapperEnvError):
        assert_wrapper_env_safe(missing_home, tmp_path=tmp_path)

    missing_output_dir = {k: v for k, v in well_formed.items() if k != "BREEZY_K1_OUTPUT_DIR"}
    with pytest.raises(WrapperEnvError):
        assert_wrapper_env_safe(missing_output_dir, tmp_path=tmp_path)

    path_outside = dict(well_formed) | {"XDG_RUNTIME_DIR": str(outside)}
    with pytest.raises(WrapperEnvError):
        assert_wrapper_env_safe(path_outside, tmp_path=tmp_path)

    posixly_correct_present = dict(well_formed) | {"POSIXLY_CORRECT": "1"}
    with pytest.raises(WrapperEnvError):
        assert_wrapper_env_safe(posixly_correct_present, tmp_path=tmp_path)

    # build_wrapper_env itself must also refuse an out-of-scope key.
    with pytest.raises(WrapperEnvError):
        build_wrapper_env(
            tmp_path,
            new_run_token(),
            output_dirs={"NOT_A_BREEZY_OUTPUT_DIR": tmp_path / "x"},
        )


##############################################################################
# I2 -- protected window, shared slice, wrapper flock, ingest deprioritisation
##############################################################################

_SITES_TOML: Final[Path] = _REPO_ROOT / "src" / "breezy" / "registry" / "sites.toml"
_MA_STUDY: Final[Path] = _REPO_ROOT / "scripts" / "analysis" / "ma_prelock_winner_ask_study.py"
_CONTINUOUS_STRATEGY: Final[Path] = (
    _REPO_ROOT / "src" / "breezy" / "strategy" / "current_rung_hold" / "continuous_strategy.py"
)
_STRATEGY_MODULE: Final[str] = "breezy.strategy.current_rung_hold.strategy"
_WINDOW_START_CONST: Final[str] = "_WINDOW_START_HOUR_LST"
_WINDOW_END_CONST: Final[str] = "_WINDOW_END_HOUR_LST"

_STUDIES_SLICE: Final[Path] = _DEPLOY_DIR / "breezy-studies.slice"
_LOCK_FILENAME: Final[str] = "breezy-studies.lock"

#: Literal expected sets (L-24 anti-vacuity): every test below that iterates
#: one of these asserts it equals the hardcoded expectation FIRST, so a
#: missing file fails loudly on set membership rather than silently
#: iterating over zero items.
_HEAVY_TIMERS: Final[frozenset[str]] = frozenset(
    {
        "breezy-k1-daily.timer",
        "breezy-mb-daily.timer",
        "breezy-offer-gate-daily.timer",
    }
)
_HEAVY_SERVICES: Final[frozenset[str]] = frozenset(
    {
        "breezy-k1-daily.service",
        "breezy-mb-daily.service",
        "breezy-offer-gate-daily.service",
    }
)
_WRAPPERS: Final[frozenset[str]] = frozenset(
    {
        "k1-daily-run.sh",
        "mb-daily-run.sh",
        "offer-gate-daily-run.sh",
    }
)

#: Every wrapper writes its own `$OUT`/log via a distinct env var, except
#: `offer-gate-daily-run.sh`, which takes `$OUT` as `argv[1]` (A-8) -- `None`
#: marks that case.
_WRAPPER_OUTPUT_ENV_VAR: Final[dict[str, str | None]] = {
    "k1-daily-run.sh": "BREEZY_K1_OUTPUT_DIR",
    "mb-daily-run.sh": "BREEZY_MB_OUTPUT_DIR",
    "offer-gate-daily-run.sh": None,
}
_WRAPPER_LOG_FILENAME: Final[dict[str, str]] = {
    "k1-daily-run.sh": "k1_daily.log",
    "mb-daily-run.sh": "mb_daily.log",
    "offer-gate-daily-run.sh": "offer_gate_daily.log",
}

_SIZE_MULTIPLIERS: Final[dict[str, int]] = {
    "": 1,
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
}
_SIZE_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+(?:\.\d+)?)([KMGT]?)$")


def _parse_systemd_size(raw: str) -> float:
    match = _SIZE_RE.match(raw.strip())
    assert match is not None, f"unparseable systemd size literal: {raw!r}"
    number, suffix = match.groups()
    return float(number) * _SIZE_MULTIPLIERS[suffix]


def _directive_value(unit_text: str, directive: str) -> str | None:
    prefix = f"{directive}="
    for line in unit_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(prefix):
            return stripped[len(prefix) :]
    return None


def _on_calendar_hhmm(timer_text: str) -> list[tuple[int, int]]:
    """Every literal `HH:MM` an `OnCalendar=... HH:MM:SS UTC` line in
    `timer_text` fires at. Deliberately text-only, mirroring
    `tests/unit/test_deploy_timer_hours.py`."""
    ticks: list[tuple[int, int]] = []
    pattern = re.compile(r"^OnCalendar=.*\s([\d,]+):(\d{2}):\d{2}\s+UTC\s*$")
    for line in timer_text.splitlines():
        match = pattern.match(line.strip())
        if match is None:
            continue
        hours_field, minute = match.groups()
        for hour in hours_field.split(","):
            ticks.append((int(hour), int(minute)))
    return ticks


def _std_utc_offsets_from_sites_toml() -> frozenset[float]:
    """`std_utc_offset_hours` values declared anywhere in
    `src/breezy/registry/sites.toml` -- never a UTC literal, never an IANA
    zone (Rev 2 BLOCK-1)."""
    raw = tomllib.loads(_SITES_TOML.read_text())
    offsets: set[float] = set()

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            value = node.get("std_utc_offset_hours")
            if isinstance(value, (int, float)):
                offsets.add(float(value))
            for child in node.values():
                _walk(child)

    _walk(raw)
    return frozenset(offsets)


@dataclass(frozen=True)
class _ProtectedWindow:
    """`P`, as minutes-of-day since 00:00Z. `end_minute` may be `>= 1440`,
    meaning the window crosses midnight -- callers use :meth:`contains`
    rather than comparing the raw fields directly."""

    start_minute: int
    end_minute: int

    def contains(self, hour: int, minute: int) -> bool:
        minute_of_day = hour * 60 + minute
        if self.end_minute >= 1440:
            wrapped_end = self.end_minute - 1440
            return minute_of_day >= self.start_minute or minute_of_day < wrapped_end
        return self.start_minute <= minute_of_day < self.end_minute

    def as_hhmm(self) -> tuple[dt.time, dt.time]:
        start = self.start_minute % 1440
        end = self.end_minute % 1440
        return (dt.time(start // 60, start % 60), dt.time(end // 60, end % 60))


def _protected_window() -> _ProtectedWindow:
    """`P`, derived exactly as `SP-1.rev4.md`'s "Window derivation" section
    computes it: offsets from `sites.toml`, LST bounds imported from the
    live gate, union over the per-offset UTC intervals, then +/-15 min."""
    from breezy.strategy.current_rung_hold.strategy import (
        _WINDOW_END_HOUR_LST,
        _WINDOW_START_HOUR_LST,
    )

    duration_minutes = (_WINDOW_END_HOUR_LST - _WINDOW_START_HOUR_LST) * 60
    intervals = []
    for offset in _std_utc_offsets_from_sites_toml():
        start = round((_WINDOW_START_HOUR_LST * 60) - (offset * 60)) % 1440
        intervals.append((start, start + duration_minutes))
    intervals.sort()
    merged_start, merged_end = intervals[0]
    for start, end in intervals[1:]:
        assert start <= merged_end, (
            f"per-offset windows do not merge into a single contiguous "
            f"protected window: {intervals}"
        )
        merged_end = max(merged_end, end)
    return _ProtectedWindow(start_minute=merged_start - 15, end_minute=merged_end + 15)


def _ast_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _time_call_args(node: ast.expr) -> tuple[int, int] | None:
    """If `node` is a call shaped like `dt.time(H, M)`, return `(H, M)`."""
    if not isinstance(node, ast.Call):
        return None
    if len(node.args) < 2:
        return None
    hour, minute = node.args[0], node.args[1]
    if (
        isinstance(hour, ast.Constant)
        and isinstance(minute, ast.Constant)
        and isinstance(hour.value, int)
        and isinstance(minute.value, int)
    ):
        return (hour.value, minute.value)
    return None


def _module_level_time_constants(
    module: ast.Module, names: frozenset[str]
) -> dict[str, tuple[int, int]]:
    found: dict[str, tuple[int, int]] = {}
    for node in module.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in names:
                parsed = _time_call_args(value) if value is not None else None
                if parsed is not None:
                    found[target.id] = parsed
    return found


def test_the_protected_window_is_derived_from_the_declared_std_offsets() -> None:
    offsets = _std_utc_offsets_from_sites_toml()
    assert offsets == frozenset({-5.0, -6.0, -8.0})

    window = _protected_window()
    start, end = window.as_hhmm()
    assert (start, end) == (dt.time(16, 45), dt.time(1, 15))

    module = _ast_module(_MA_STUDY)
    constants = _module_level_time_constants(
        module, frozenset({"AFTERNOON_WINDOW_START", "AFTERNOON_WINDOW_END"})
    )
    assert constants.get("AFTERNOON_WINDOW_START") == (12, 0)
    assert constants.get("AFTERNOON_WINDOW_END") == (17, 0)


@pytest.mark.parametrize("timer_name", sorted(_HEAVY_TIMERS))
def test_no_heavy_unit_timer_fires_inside_the_lst_derived_protected_window(timer_name: str) -> None:
    assert _HEAVY_TIMERS == {
        "breezy-k1-daily.timer",
        "breezy-mb-daily.timer",
        "breezy-offer-gate-daily.timer",
    }
    timer_path = _DEPLOY_DIR / timer_name
    assert timer_path.is_file(), f"{timer_name} does not exist"
    window = _protected_window()
    ticks = _on_calendar_hhmm(timer_path.read_text())
    assert ticks, f"{timer_name} has no parseable OnCalendar= line"
    for hour, minute in ticks:
        assert not window.contains(hour, minute), (
            f"{timer_name} fires at {hour:02d}:{minute:02d}Z, inside the "
            f"protected window {window.as_hhmm()}"
        )


def test_the_protected_window_predicate_rejects_a_synthetic_in_window_tick() -> None:
    """N6c negative control (L-24): the predicate above must be able to
    DETECT a violation, not just always return False."""
    window = _protected_window()
    assert window.contains(20, 0) is True
    assert window.contains(0, 30) is True
    assert window.contains(13, 30) is False


def test_the_v3_strategy_imports_the_v1_decision_window_and_redeclares_neither() -> None:
    module = _ast_module(_CONTINUOUS_STRATEGY)
    imported_no_alias: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module == _STRATEGY_MODULE:
            for alias in node.names:
                if alias.name in (_WINDOW_START_CONST, _WINDOW_END_CONST) and alias.asname is None:
                    imported_no_alias.add(alias.name)
    assert imported_no_alias == {_WINDOW_START_CONST, _WINDOW_END_CONST}, (
        "continuous_strategy.py must import both window constants by their "
        "exact name, unaliased -- an aliased re-export would satisfy a "
        "name-only check while leaving the module-level name free to be "
        "rebound (R4-N3)"
    )
    for node in module.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                assert target.id not in (_WINDOW_START_CONST, _WINDOW_END_CONST), (
                    f"{target.id} is re-declared at module level in "
                    "continuous_strategy.py -- it must only be imported"
                )


@pytest.mark.parametrize("service_name", sorted(_HEAVY_SERVICES))
def test_every_heavy_study_unit_declares_the_shared_studies_slice(service_name: str) -> None:
    assert _HEAVY_SERVICES == {
        "breezy-k1-daily.service",
        "breezy-mb-daily.service",
        "breezy-offer-gate-daily.service",
    }
    service_path = _DEPLOY_DIR / service_name
    assert service_path.is_file(), f"{service_name} does not exist"
    assert "Slice=breezy-studies.slice" in service_path.read_text().splitlines()


def test_the_studies_slice_declares_its_own_memory_ceiling() -> None:
    assert _STUDIES_SLICE.is_file()
    text = _STUDIES_SLICE.read_text()
    memory_high = _directive_value(text, "MemoryHigh")
    memory_max = _directive_value(text, "MemoryMax")
    assert memory_high is not None
    assert memory_max is not None
    assert _parse_systemd_size(memory_high) < _parse_systemd_size(memory_max)


def test_the_ingest_unit_is_deprioritised_against_the_studies() -> None:
    ingest_service = _DEPLOY_DIR / "breezy-quote-tape-ingest.service"
    text = ingest_service.read_text()
    assert _directive_value(text, "Nice") == "10"
    assert _directive_value(text, "IOSchedulingClass") == "best-effort"
    assert _directive_value(text, "IOSchedulingPriority") == "7"
    assert _directive_value(text, "MemoryHigh") == "4G"
    assert _directive_value(text, "MemoryMax") == "6G"


def test_the_ingest_unit_comment_matches_the_cli_exit_contract() -> None:
    text = (_DEPLOY_DIR / "breezy-quote-tape-ingest.service").read_text()
    assert "exit 3" in text
    assert "EXIT_CONVERSION_FAILED" in text


def test_the_offer_gate_unit_still_passes_the_systemd_home_specifier() -> None:
    text = (_DEPLOY_DIR / "breezy-offer-gate-daily.service").read_text()
    exec_start = _directive_value(text, "ExecStart")
    assert exec_start is not None
    assert "offer-gate-daily-run.sh" in exec_start
    assert "%h/.local/share/breezy/offer_gate" in exec_start
    for path in _DEPLOY_DIR.iterdir():
        if path.is_file():
            assert "BREEZY_OFFER_GATE_OUTPUT_DIR" not in path.read_text()


##############################################################################
# I2a/A-20 -- retimed doc claims, scoped grep + positive control + residual
##############################################################################

_A20_SCOPE: Final[frozenset[str]] = frozenset(
    {
        "deploy/systemd/breezy-k1-daily.timer",
        "deploy/systemd/breezy-offer-gate-daily.timer",
        "deploy/systemd/README.md",
    }
)
_A20_MOVED_MARKER: Final[str] = "MOVED 2026-09-12"
_A20_RESIDUAL: Final[frozenset[str]] = frozenset(
    {
        "breezy-pm-crh-v2-tally.timer",
        "breezy-live-tally.timer",
        "breezy-mb-daily.timer",
        "breezy-score-live-trials.timer",
        "breezy-quote-tape-ingest.timer",
    }
)


def test_no_retimed_unit_or_readme_line_still_asserts_the_old_tick() -> None:
    for relative in sorted(_A20_SCOPE):
        path = _REPO_ROOT / relative
        assert path.is_file(), f"{relative} does not exist"
        for line in path.read_text().splitlines():
            if "22:30" in line or "22:45" in line:
                assert _A20_MOVED_MARKER in line, (
                    f"{relative} still asserts the old tick without a "
                    f"{_A20_MOVED_MARKER!r} marker: {line!r}"
                )

    combined_text = "\n".join((_REPO_ROOT / relative).read_text() for relative in _A20_SCOPE)
    assert "01:35" in combined_text
    assert "02:05" in combined_text

    for residual_name in sorted(_A20_RESIDUAL):
        text = (_DEPLOY_DIR / residual_name).read_text()
        assert "22:30" in text or "22:45" in text, (
            f"{residual_name} was expected to still carry its declared-residual "
            "stale tick reference (A-20) -- a silent edit to a zero-diff-"
            "protected file would otherwise go undetected"
        )


##############################################################################
# I2c -- wrapper lock serialization
##############################################################################


def _spawn_wrapper(
    wrapper_filename: str,
    tmp_path: Path,
    *,
    provide_output_arg: bool = True,
    xdg_runtime_dir: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Spawn one wrapper under a fully isolated, `tmp_path`-scoped env.
    Returns `(result, out_dir, log_path)`."""
    token = new_run_token()
    out_dir = tmp_path / f"{token}-out"
    env_var = _WRAPPER_OUTPUT_ENV_VAR[wrapper_filename]
    output_dirs: dict[str, Path] = {(env_var or "BREEZY_OFFER_GATE_OUTPUT_DIR"): out_dir}
    env = build_wrapper_env(
        tmp_path, token, output_dirs=output_dirs, xdg_runtime_dir=xdg_runtime_dir
    )
    argv = ["bash", str(_DEPLOY_DIR / wrapper_filename)]
    if env_var is None and provide_output_arg:
        argv.append(str(out_dir))
    result = subprocess.run(
        argv, env=env, capture_output=True, text=True, timeout=30, check=False
    )
    log_path = out_dir / _WRAPPER_LOG_FILENAME[wrapper_filename]
    return result, out_dir, log_path


@pytest.mark.parametrize("wrapper_filename", sorted(_WRAPPERS))
def test_every_heavy_study_wrapper_takes_the_studies_flock_and_skips_when_held(
    wrapper_filename: str, tmp_path: Path
) -> None:
    assert _WRAPPERS == {"k1-daily-run.sh", "mb-daily-run.sh", "offer-gate-daily-run.sh"}
    token = new_run_token()
    xdg_runtime_dir = tmp_path / f"{token}-xdg-runtime"
    xdg_runtime_dir.mkdir(parents=True)
    lock_path = xdg_runtime_dir / _LOCK_FILENAME
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, out_dir, log_path = _spawn_wrapper(
            wrapper_filename, tmp_path, xdg_runtime_dir=xdg_runtime_dir
        )
        assert result.returncode == 0
        assert log_path.is_file()
        expected = "SKIPPED -- another study holds the studies lock"
        assert expected in log_path.read_text()
        assert expected in result.stdout
        artefacts = [p for p in out_dir.iterdir() if p != log_path]
        assert artefacts == [], f"the study ran despite the held lock: {artefacts}"
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


@pytest.mark.skipif(os.geteuid() == 0, reason="permission refusals are bypassed as root")
@pytest.mark.parametrize("wrapper_filename", sorted(_WRAPPERS))
def test_the_wrapper_skips_when_the_lock_directory_is_missing_or_unwritable(
    wrapper_filename: str, tmp_path: Path
) -> None:
    # Case 1: a FILE occupies the path `mkdir -p "$LOCK_DIR"` must create --
    # "non-creatable".
    blocked_runtime_dir = tmp_path / f"{new_run_token()}-blocked"
    blocked_runtime_dir.write_bytes(b"")
    result, _out_dir, log_path = _spawn_wrapper(
        wrapper_filename, tmp_path, xdg_runtime_dir=blocked_runtime_dir
    )
    assert result.returncode == 75
    combined = result.stdout + (log_path.read_text() if log_path.is_file() else "")
    assert "SKIPPED-INFRA" in combined
    assert "SKIPPED -- another study holds the studies lock" not in combined

    # Case 2: LOCK_DIR exists but is unwritable (mode 0500) -- `mkdir -p`
    # succeeds trivially; opening a NEW file inside it fails.
    restricted_runtime_dir = tmp_path / f"{new_run_token()}-restricted"
    restricted_runtime_dir.mkdir(parents=True)
    restricted_runtime_dir.chmod(0o500)
    try:
        result2, _out_dir2, log_path2 = _spawn_wrapper(
            wrapper_filename, tmp_path, xdg_runtime_dir=restricted_runtime_dir
        )
        assert result2.returncode == 75
        combined2 = result2.stdout + (log_path2.read_text() if log_path2.is_file() else "")
        assert "SKIPPED-INFRA" in combined2
        assert "SKIPPED -- another study holds the studies lock" not in combined2
    finally:
        restricted_runtime_dir.chmod(0o700)


def test_the_offer_gate_wrapper_requires_its_output_dir_as_an_argument(tmp_path: Path) -> None:
    result, _out_dir, _log_path = _spawn_wrapper(
        "offer-gate-daily-run.sh", tmp_path, provide_output_arg=False
    )
    assert result.returncode != 0
    assert "offer-gate output directory is required" in result.stderr


@pytest.mark.parametrize("wrapper_filename", sorted(_WRAPPERS))
def test_every_study_wrapper_is_executable(wrapper_filename: str) -> None:
    path = _DEPLOY_DIR / wrapper_filename
    assert path.is_file(), f"{wrapper_filename} does not exist"
    assert os.access(path, os.X_OK), f"{wrapper_filename} is not executable"


def test_all_three_wrappers_name_the_same_lock_path() -> None:
    expected_line = f'LOCK="$LOCK_DIR/{_LOCK_FILENAME}"'
    for wrapper_filename in sorted(_WRAPPERS):
        text = (_DEPLOY_DIR / wrapper_filename).read_text()
        assert expected_line in text.splitlines(), (
            f"{wrapper_filename} does not name the shared lock path identically"
        )


_EXEC_LOCK_LINE_RE: Final[re.Pattern[str]] = re.compile(r'^exec 9>>"\$LOCK"\s')


@pytest.mark.parametrize("wrapper_filename", sorted(_WRAPPERS))
def test_the_exec_line_carries_no_stderr_redirect(wrapper_filename: str) -> None:
    """R4-N1, measured: an `exec` with no command applies its redirections
    to the SHELL for the rest of the run (74 bytes of subsequent shell
    stderr measurably leaked into the log in SP-1.rev4.md's round-4 block).
    `2>>"$LOG"` is safe on the `mkdir -p` line above (a simple command's
    redirect is scoped to it) but must NEVER appear on the `exec` line."""
    lines = (_DEPLOY_DIR / wrapper_filename).read_text().splitlines()
    exec_lines = [line for line in lines if _EXEC_LOCK_LINE_RE.match(line.strip())]
    assert len(exec_lines) == 1, f"{wrapper_filename}: expected exactly one exec-lock line"
    assert "2>>" not in exec_lines[0], (
        f"{wrapper_filename}'s exec line redirects the shell's stderr: {exec_lines[0]!r}"
    )


_INTERPRETER_INVOCATION_RE: Final[re.Pattern[str]] = re.compile(
    r'^\s*(if\s+)?"\$(PY|REPO/\.venv/bin/python)"\s'
)
_PREAMBLE_MARKER: Final[str] = "unset POSIXLY_CORRECT"


@pytest.mark.parametrize("wrapper_filename", sorted(_WRAPPERS))
def test_the_lock_preamble_precedes_the_first_interpreter_invocation_in_every_wrapper(
    wrapper_filename: str,
) -> None:
    lines = (_DEPLOY_DIR / wrapper_filename).read_text().splitlines()
    preamble_index = next(
        (i for i, line in enumerate(lines) if line.strip() == _PREAMBLE_MARKER), None
    )
    assert preamble_index is not None, f"{wrapper_filename} has no lock preamble"
    invocation_index = next(
        (i for i, line in enumerate(lines) if _INTERPRETER_INVOCATION_RE.match(line)), None
    )
    assert invocation_index is not None, (
        f"{wrapper_filename} has no recognisable interpreter invocation"
    )
    assert preamble_index < invocation_index, (
        f"{wrapper_filename} invokes the interpreter (line {invocation_index + 1}) "
        f"before the lock preamble (line {preamble_index + 1})"
    )


@pytest.mark.parametrize("wrapper_filename", sorted(_WRAPPERS))
def test_no_study_wrapper_enables_posix_mode(wrapper_filename: str) -> None:
    """C2-B3 + R4-N2: neither door is open -- no ACTUAL `set -o posix`
    directive (a mention of the literal string inside an explanatory
    comment, as the preamble's own header carries, does not count), and
    `unset POSIXLY_CORRECT` is present exactly once."""
    lines = (_DEPLOY_DIR / wrapper_filename).read_text().splitlines()
    for line in lines:
        code_part = line.strip().split("#", 1)[0]  # P1-c: strip inline comments too
        assert "set -o posix" not in code_part, f"{wrapper_filename} enables POSIX mode: {line!r}"
    assert lines.count(_PREAMBLE_MARKER) == 1


##############################################################################
# AM-22 -- every subprocess call in THIS module takes env= from the fixture,
# hardened by SP-1 P1 (round-2 python-reviewer items 3-4) against:
#   (i)  an import-binding bypass -- `import subprocess as sp; sp.run(...)`
#        or `from subprocess import run as _run; _run(...)` -- the original
#        check keyed on the LITERAL name "subprocess" and only recognised
#        `run`/`Popen`/`check_call`/`call`, missing `check_output` too;
#   (ii) post-construction mutation blindness -- `env = build_wrapper_env(
#        ...); env["X"] = "y"; subprocess.run(..., env=env)` passed the old
#        check because it only inspected the LAST `Assign` to a bare `Name`,
#        never a `Subscript` target, an `AugAssign`, or an
#        `.update(`/`.setdefault(`/`.pop(` call in between.
##############################################################################

_ALLOWED_ENV_BUILDERS: Final[frozenset[str]] = frozenset({"build_wrapper_env"})
_RECOGNIZED_SUBPROCESS_FUNCS: Final[frozenset[str]] = frozenset(
    {"run", "Popen", "call", "check_call", "check_output"}
)
_ENV_MUTATING_METHODS: Final[frozenset[str]] = frozenset({"update", "setdefault", "pop"})


def _env_keyword_source(call: ast.Call) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == "env":
            return keyword.value
    return None


@dataclass(frozen=True)
class _SubprocessBindings:
    """The local names THIS module's own import statements actually bind to
    the `subprocess` module, and to specific `subprocess` functions imported
    by name -- resolved from `Import`/`ImportFrom` nodes (incl. `asname`),
    never from the literal string `"subprocess"`."""

    module_names: frozenset[str]
    function_names: dict[str, str]  # local name -> real subprocess function name


def _resolve_subprocess_bindings(module: ast.Module) -> _SubprocessBindings:
    module_names: set[str] = set()
    function_names: dict[str, str] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    module_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in _RECOGNIZED_SUBPROCESS_FUNCS:
                    function_names[alias.asname or alias.name] = alias.name
    return _SubprocessBindings(module_names=frozenset(module_names), function_names=function_names)


def _subprocess_call_or_none(call: ast.Call, bindings: _SubprocessBindings) -> str | None:
    """The REAL subprocess function name `call` invokes, resolved through
    `bindings` -- e.g. `sp.run(...)` -> `"run"` when `sp` is bound by
    `import subprocess as sp`; `_run(...)` -> `"run"` when `_run` is bound
    by `from subprocess import run as _run`. `None` if `call` is not a
    recognised subprocess spawn at all."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id in bindings.module_names and func.attr in _RECOGNIZED_SUBPROCESS_FUNCS:
            return func.attr
        return None
    if isinstance(func, ast.Name):
        return bindings.function_names.get(func.id)
    return None


def _enclosing_function(module: ast.Module, target: ast.AST) -> ast.FunctionDef | None:
    """The innermost `FunctionDef` in `module` containing `target` -- there
    are no nested `def`s in this module, so a plain containment walk is
    unambiguous."""
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and any(
            child is target for child in ast.walk(node)
        ):
            return node
    return None


def _is_call_to_allowed_builder(value: ast.expr) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in _ALLOWED_ENV_BUILDERS
    )


def _is_name(node: ast.expr, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _last_qualifying_assignment(
    module: ast.Module, call: ast.Call, env_source: ast.expr
) -> ast.Assign | None:
    """The LAST `Assign` in `call`'s enclosing function, at or before
    `call`'s own line, whose target is the bare `Name` `env_source` and
    whose value is a call to an allowed builder -- e.g. `env =
    build_wrapper_env(...)`. `None` if `env_source` is not a bare `Name`,
    the enclosing function cannot be found, or no such assignment exists."""
    if not isinstance(env_source, ast.Name):
        return None
    enclosing = _enclosing_function(module, call)
    if enclosing is None:
        return None
    best: ast.Assign | None = None
    for node in ast.walk(enclosing):
        if not (isinstance(node, ast.Assign) and node.lineno <= call.lineno):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == env_source.id
                and _is_call_to_allowed_builder(node.value)
                and (best is None or node.lineno > best.lineno)
            ):
                best = node
    return best


def _env_arg_traces_to_allowed_builder(
    module: ast.Module, call: ast.Call, env_source: ast.expr
) -> bool:
    """True if `env_source` is either a direct call to an allowed builder,
    or a bare `Name` whose LAST same-function assignment before this call
    is such a call -- e.g. `env = build_wrapper_env(...); subprocess.run(
    ..., env=env)`. Never `os.environ`, `os.environ.copy()`, or a dict
    literal (AM-22)."""
    if _is_call_to_allowed_builder(env_source):
        return True
    return _last_qualifying_assignment(module, call, env_source) is not None


def _env_mutated_between_construction_and_call(
    module: ast.Module, call: ast.Call, env_source: ast.expr
) -> bool:
    """True if anything touches the `env_source` NAME between its qualifying
    `build_wrapper_env` assignment and this `call` -- a `Subscript` assign
    (`env["X"] = ...`), a second `Assign`/`AugAssign` to the same name, or
    an `.update(`/`.setdefault(`/`.pop(` call -- so a compliant
    CONSTRUCTION cannot be laundered by a post-construction edit (P1-a).
    `env=build_wrapper_env(...)` inline has nothing to mutate between."""
    if _is_call_to_allowed_builder(env_source):
        return False
    qualifying = _last_qualifying_assignment(module, call, env_source)
    if qualifying is None or not isinstance(env_source, ast.Name):
        return False  # already flagged as non-compliant by the trace check
    enclosing = _enclosing_function(module, call)
    assert enclosing is not None
    name = env_source.id
    for node in ast.walk(enclosing):
        lineno = getattr(node, "lineno", None)
        if lineno is None or not (qualifying.lineno < lineno <= call.lineno):
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and _is_name(target.value, name):
                    return True
                if isinstance(target, ast.Name) and target.id == name:
                    return True
            continue
        is_augassign_mutation = isinstance(node, ast.AugAssign) and _is_name(node.target, name)
        is_mutating_method_call = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and _is_name(node.func.value, name)
            and node.func.attr in _ENV_MUTATING_METHODS
        )
        if is_augassign_mutation or is_mutating_method_call:
            return True
    return False


def test_every_subprocess_call_takes_env_from_the_wrapper_env_fixture() -> None:
    """AM-22 (hardened, P1-a): every subprocess spawn -- resolved through
    this module's ACTUAL import bindings, never the literal string
    "subprocess", and covering `run`/`Popen`/`call`/`check_call`/
    `check_output` -- takes its `env=` from an UNMUTATED
    `build_wrapper_env(...)` result. Never `os.environ`, `os.environ.copy()`,
    a dict literal, nor a `build_wrapper_env(...)` result edited afterward."""
    module = _ast_module(Path(__file__))
    bindings = _resolve_subprocess_bindings(module)
    subprocess_calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and _subprocess_call_or_none(node, bindings) is not None
    ]
    assert subprocess_calls, "expected at least one subprocess call in this module"
    for call in subprocess_calls:
        env_source = _env_keyword_source(call)
        assert env_source is not None, "a subprocess call is missing env="
        assert _env_arg_traces_to_allowed_builder(module, call, env_source), (
            f"env= ({ast.dump(env_source)}) does not trace back to a call to "
            f"one of {sorted(_ALLOWED_ENV_BUILDERS)} -- never os.environ, "
            "os.environ.copy(), or a dict literal"
        )
        assert not _env_mutated_between_construction_and_call(module, call, env_source), (
            f"env= at line {call.lineno} is mutated after its build_wrapper_env(...) "
            "construction and before this spawn -- a post-construction edit can "
            "reintroduce an unsafe key"
        )


def test_no_wrapper_test_wrote_into_the_real_breezy_state_directory() -> None:
    """A-19, the real guard (X-L27): scans ONLY the bytes appended (or, for
    the three `$OUT` directories, the names added) to the enumerated
    five-path scope SINCE this module was imported -- i.e. across every
    wrapper-spawning test this file contains, not just the ones defined
    above this point. Deliberately placed LAST in the file (pytest runs a
    module's tests in source order): every later increment that adds a
    subprocess-spawning test to this module MUST be inserted ABOVE this
    test, never below it, or this guard stops covering it.

    Measured baseline (SP-1.rev4.md round-4): both real lock paths were
    ABSENT at that time. Since the first real study run (03:13:31Z
    2026-09-13, `exec 9>>"$LOCK"` in `deploy/systemd/k1-daily-run.sh`, no
    delete-on-exit by design), `/run/user/1000/breezy-studies.lock` now
    legitimately EXISTS at size 0 for the lifetime of the tmpfs -- so the
    guard below compares each lock path's CURRENT state against its OWN
    `_SESSION_START_STATE` snapshot (`offset is None` ⇒ still absent;
    `offset is not None` ⇒ still present at the SAME size) rather than
    hard-coding "absent then, so absent now." This guard never touches
    directory equality on `~/.local/share/breezy/`, which the live node,
    recorder and supervisor write to continuously (X-L27's reason for
    existing).

    P1-b (L-24 anti-vacuity, literal-set-first): with `XDG_RUNTIME_DIR` and
    `HOME` both absent from the RUNNER's own environment, `_SESSION_START_STATE`
    would resolve to `()` and the loop below would iterate ZERO times --
    passing vacuously without ever having scanned anything. The three
    assertions below fail loudly on that condition instead, mirroring this
    module's own `_HEAVY_TIMERS`-style literal-expected-set pattern.
    """
    assert _REAL_XDG_RUNTIME_DIR, (
        "XDG_RUNTIME_DIR was empty/absent at import -- the guard's five-path "
        "scope would be silently narrowed"
    )
    assert _REAL_HOME, (
        "HOME was empty/absent at import -- the guard's five-path scope "
        "would be silently narrowed"
    )
    expected_scope_shapes = (
        Path(_REAL_XDG_RUNTIME_DIR) / _LOCK_FILENAME,
        Path(_REAL_HOME) / ".local" / "share" / "breezy" / _LOCK_FILENAME,
        Path(_REAL_HOME) / ".local" / "share" / "breezy" / "k1",
        Path(_REAL_HOME) / ".local" / "share" / "breezy" / "derived",
        Path(_REAL_HOME) / ".local" / "share" / "breezy" / "offer_gate",
    )
    assert len(_SESSION_START_STATE) == 5, (
        f"expected exactly 5 real-path scope entries, got "
        f"{len(_SESSION_START_STATE)}: {[str(s.path) for s in _SESSION_START_STATE]} -- "
        "an empty scope iterates zero times below and passes vacuously (L-24)"
    )
    assert tuple(state.path for state in _SESSION_START_STATE) == expected_scope_shapes, (
        f"the resolved scope does not match the expected five path shapes: "
        f"{[str(s.path) for s in _SESSION_START_STATE]} != "
        f"{[str(p) for p in expected_scope_shapes]}"
    )

    run_token_marker = "sp1-leakguard-"  # every token this module mints starts with this
    for state in _SESSION_START_STATE:
        if state.path.name == "breezy-studies.lock":
            if state.offset is None:
                assert not state.path.is_file(), (
                    f"{state.path} exists now but was ABSENT at session start -- a "
                    "wrapper test flocked the REAL studies lock"
                )
            else:
                assert state.path.is_file(), (
                    f"{state.path} was PRESENT at session start (size "
                    f"{state.offset}) but is gone now -- a wrapper test deleted "
                    "the REAL studies lock"
                )
                current_size = state.path.stat().st_size
                assert current_size == state.offset, (
                    f"{state.path} was present at session start with size "
                    f"{state.offset} but is now size {current_size} -- a wrapper "
                    "test wrote through the REAL studies lock"
                )
            continue
        if state.offset is not None or state.path.is_file():
            found = any(
                _scan_appended_bytes_for_token(state.path, state.offset, run_token_marker)
                for _ in (0,)
            )
            assert not found, f"a run token leaked into {state.path}"
        new_names = _new_names_in_scope(state)
        leaked_new_names = {name for name in new_names if run_token_marker in name}
        assert not leaked_new_names, (
            f"a run-token-named path appeared under {state.path}: {leaked_new_names}"
        )
