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

import os
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
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """The ONLY way a test in this module may build a subprocess env for a
    wrapper spawn (AM-22 pins this by AST). `HOME` and `XDG_RUNTIME_DIR` are
    always fresh directories under `tmp_path`, named with `run_token` so any
    byte a mis-redirected wrapper writes carries it; every `output_dirs`
    value must already be a `BREEZY_*_OUTPUT_DIR`-shaped key pointing inside
    `tmp_path`. Self-validates via :func:`assert_wrapper_env_safe` before
    returning -- fail-closed by construction, not by caller discipline.
    """
    home = tmp_path / f"{run_token}-home"
    xdg_runtime_dir = tmp_path / f"{run_token}-xdg-runtime"
    home.mkdir(parents=True, exist_ok=True)
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
    #: `st_size` at import time, or `None` if the path did not exist yet
    #: (both real lock paths are measured ABSENT at session start -- see the
    #: module docstring and SP-1.rev4.md's round-4 measurement block).
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


def test_no_wrapper_test_wrote_into_the_real_breezy_state_directory() -> None:
    """A-19, the real guard (X-L27): scans ONLY the bytes appended (or, for
    the three `$OUT` directories, the names added) to the enumerated
    five-path scope SINCE this module was imported -- i.e. across every
    wrapper-spawning test this file contains, not just the ones defined
    above this point. Deliberately placed LAST in the file (pytest runs a
    module's tests in source order): every later increment that adds a
    subprocess-spawning test to this module MUST be inserted ABOVE this
    test, never below it, or this guard stops covering it.

    Measured baseline (SP-1.rev4.md round-4): both real lock paths are
    ABSENT today, so "absent at session start ⇒ still absent now" is a
    clean, non-flaky assertion -- this guard never touches directory
    equality on `~/.local/share/breezy/`, which the live node, recorder and
    supervisor write to continuously (X-L27's reason for existing).
    """
    run_token_marker = "sp1-leakguard-"  # every token this module mints starts with this
    for state in _SESSION_START_STATE:
        if state.path.name == "breezy-studies.lock":
            assert not state.path.is_file(), (
                f"{state.path} exists now but was ABSENT at session start -- a "
                "wrapper test flocked the REAL studies lock"
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
