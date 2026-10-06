"""EDGE-6 AC-6a-5 (ops-reliability plan r2, `EDGE-6_ops_reliability_plan_r2_
2026-09-27.md` sections 1/5/6; r1 spec `EDGE-6_ops_reliability_plan_r1_
2026-09-27.md:36,204,227-231`): a regression test that runs each venv-python
unit's `ExecStart=` AS THE UNIT WOULD -- under its own `WorkingDirectory=`,
with a scrubbed environment, and with the repo root itself absent from
`PYTHONPATH` -- not the way `python -m pytest` (or an ad-hoc `python
script.py`) happens to run it.

This closes three gaps `tests/unit/test_discovery_pull_exec_import.py` (kept
unmodified, per the plan) left open (`EDGE-6 r1` `:87-90`; `r2` `:139-140`):

1. it hard-codes ``cwd=_REPO_ROOT`` for the direct-file branch instead of
   reading the unit's own `WorkingDirectory=`;
2. it inherits the whole test-runner environment, so a repo root that
   happened to be on `PYTHONPATH` (as it is not, today, but could become
   through an unrelated change) would silently paper over exactly the
   `-m`-vs-direct-file distinction 2e109ec fixed;
3. it covers exactly one unit. `breezy-fee-evidence-pull.service` also
   invokes the venv interpreter directly against a repo file and was never
   characterized.

2026-09-26 16:52:47Z: the timer-triggered run of `breezy-discovery-pull.
service` died with ``ModuleNotFoundError: No module named 'scripts'``
(`scripts/analysis/discovery_venue_pull.py:29`,
``from scripts.analysis.discovery_set_equality import ...`` -- a
package-qualified import of a sibling script namespace package) under the
old direct-file ExecStart, because invoking a `.py` file directly puts only
that file's OWN directory on `sys.path[0]`, never `WorkingDirectory=`.
2e109ec switched to `python -m scripts.analysis.discovery_venue_pull`,
which puts the process's current working directory on `sys.path[0]`
instead -- the exact mechanism this test now proves the fix actually
depends on (`test_execstart_working_directory_is_honoured` below).

No unit file is changed by this test (AC-6a-5 is tests-only; any unit
edit -- e.g. 6a-2's `MemoryHigh=` bump -- is a separate, conditional slice
gated on the 16:52Z proof, per the plan's §2.1 rule).
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_HOST_REPO_ROOT = "/home/jon/breezy"
_VENV_PYTHON_HOST_PATHS = frozenset(
    {f"{_HOST_REPO_ROOT}/.venv/bin/python", f"{_HOST_REPO_ROOT}/.venv/bin/python3"}
)


def _directive_lines(text: str) -> list[str]:
    """Logical lines: a physical line ending in `\\` is joined to the next with one space, as
    systemd does, BEFORE blank/comment filtering. A comment line is never extended."""
    logical: list[str] = []
    pending = ""
    for physical in text.splitlines():
        stripped = physical.strip()
        if not pending and stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1].rstrip() + " "
            continue
        logical.append((pending + stripped).strip())
        pending = ""
    if pending.strip():
        logical.append(pending.strip())
    return [line for line in logical if line and not line.startswith("#")]


def _directive(text: str, name: str) -> str | None:
    """Return the single `NAME=...` directive's value, or ``None`` if absent."""
    prefix = f"{name}="
    matches = [line[len(prefix) :] for line in _directive_lines(text) if line.startswith(prefix)]
    if not matches:
        return None
    assert len(matches) == 1, f"expected exactly one {name}=, found {matches}"
    return matches[0]


def _expand_home_specifier(token: str, *, home: Path) -> str:
    """Expand systemd's `%h` (the only specifier any covered unit's
    ExecStart/WorkingDirectory carries; `%n`/`%i` appear only in
    `OnFailure=`, which this harness never resolves or invokes)."""
    return token.replace("%h", str(home))


def _map_host_repo_root(path_str: str, *, repo_root: Path) -> str:
    """Translate a literal `/home/jon/breezy` prefix onto this worktree, so
    the harness runs THIS worktree's copy of the code -- never the host
    checkout -- exactly as `test_discovery_pull_exec_import.py` and
    `test_score_live_trials_deploy.py` already do for their own fixtures."""
    if path_str == _HOST_REPO_ROOT:
        return str(repo_root)
    prefix = _HOST_REPO_ROOT + "/"
    if path_str.startswith(prefix):
        return str(repo_root) + "/" + path_str[len(prefix) :]
    return path_str


def resolve_execstart_invocation(
    unit_text: str, *, repo_root: Path, home: Path
) -> tuple[list[str], Path]:
    """Return ``(argv, cwd)`` exactly as systemd would invoke this unit's
    `ExecStart=`, with every token after the module/script replaced by
    ``--help`` -- a `ModuleNotFoundError` happens at module-load time, before
    any real argument is ever parsed, so this needs no real flags, no I/O,
    and no egress (mirrors `test_discovery_pull_exec_import.py`'s own
    `--help` substitution).

    Honours `WorkingDirectory=` (gap 1 above): a caller that hardcoded the
    real repo root here could never prove the `-m` fix depends on it.
    """
    exec_start = _directive(unit_text, "ExecStart")
    assert exec_start is not None, "unit declares no ExecStart="
    working_directory = _directive(unit_text, "WorkingDirectory")
    assert working_directory is not None, "unit declares no WorkingDirectory="

    cwd = Path(
        _map_host_repo_root(
            _expand_home_specifier(working_directory, home=home), repo_root=repo_root
        )
    )

    raw_tokens = shlex.split(_expand_home_specifier(exec_start, home=home))
    interpreter = raw_tokens[0]
    assert interpreter in _VENV_PYTHON_HOST_PATHS, (
        f"not a direct venv-python ExecStart: {interpreter!r}"
    )

    if raw_tokens[1] == "-m":
        module = raw_tokens[2]
        argv = [interpreter, "-m", module, "--help"]
    else:
        script = _map_host_repo_root(raw_tokens[1], repo_root=repo_root)
        argv = [interpreter, script, "--help"]
    return argv, cwd


def _venv_python_direct_script_units() -> list[Path]:
    """Every `deploy/systemd/*.service` whose `ExecStart=` runs the venv
    interpreter directly against a repo-tracked script or module --
    deliberately EXCLUDING an interpreter invoked against an installed
    console-script entry point under `.venv/bin/` (e.g.
    `breezy-quote-tape.service`'s `python3 .../.venv/bin/breezy-quote-tape`):
    those import solely through the venv's own site-packages install, are
    importable regardless of `sys.path[0]`, and are not the failure class
    this test guards against."""
    units: list[Path] = []
    for path in sorted(_SYSTEMD_DIR.glob("*.service")):
        text = path.read_text()
        exec_start = _directive(text, "ExecStart")
        if exec_start is None:
            continue
        tokens = shlex.split(_expand_home_specifier(exec_start, home=Path("/placeholder-home")))
        if not tokens or tokens[0] not in _VENV_PYTHON_HOST_PATHS:
            continue
        target = tokens[2] if len(tokens) > 2 and tokens[1] == "-m" else tokens[1]
        if target.startswith(f"{_HOST_REPO_ROOT}/.venv/"):
            continue
        units.append(path)
    assert units, "no venv-python-direct unit found -- the glob or filter regressed"
    return units


def _scrubbed_env(*, repo_root: Path) -> dict[str, str]:
    """`PATH`, `HOME`, and `PYTHONPATH=<repo_root>/src` ONLY. The bare repo
    root is deliberately absent (gap 2 above /
    `test_execstart_env_excludes_repo_root_from_pythonpath`): a `PYTHONPATH`
    that happened to include it would let `scripts.*` import through
    `PYTHONPATH` instead of through the `-m`/`WorkingDirectory` mechanism the
    real fix relies on, and this test would stop proving anything about the
    unit's actual invocation shape.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "PYTHONPATH": str(repo_root / "src"),
    }


def _run_execstart(
    unit_text: str, *, repo_root: Path, home: Path
) -> subprocess.CompletedProcess[str]:
    argv, cwd = resolve_execstart_invocation(unit_text, repo_root=repo_root, home=home)
    return subprocess.run(
        argv,
        cwd=cwd,
        env=_scrubbed_env(repo_root=repo_root),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def repo_root() -> Path:
    return _REPO_ROOT


@pytest.fixture
def home() -> Path:
    return Path.home()


@pytest.mark.parametrize("unit_path", _venv_python_direct_script_units(), ids=lambda p: p.name)
def test_every_venv_python_execstart_imports_under_its_working_directory(
    unit_path: Path, repo_root: Path, home: Path
) -> None:
    """`[breezy-discovery-pull.service]`: RED against the pre-2e109ec
    ExecStart (`test_pre_2e109ec_discovery_pull_execstart_fails_module_not_
    found` below), GREEN against the current, `-m`-based one.
    `[breezy-fee-evidence-pull.service]`: a characterization guard -- it
    only ever imports the installed `breezy` package, so it is expected
    GREEN today, but a future edit that adds a sibling `scripts.*` import
    would now be caught here rather than shipping to the next timer tick.
    """
    result = _run_execstart(unit_path.read_text(), repo_root=repo_root, home=home)
    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    assert "ImportError" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr


# Historical fixture: the pre-2e109ec `breezy-discovery-pull.service`
# ExecStart (`git show be06f14^:deploy/systemd/breezy-discovery-pull.
# service`), embedded verbatim rather than shelled out to git history --
# this repo's own `test_family_tally_v2.py:1971-1976` states the reasoning:
# a future history squash could make a commit-relative `git show` fixture
# unresolvable, where an embedded string cannot regress.
_PRE_2E109EC_DISCOVERY_PULL_UNIT = (
    "\n[Service]\n"
    "WorkingDirectory=/home/jon/breezy\n"
    "ExecStart=/home/jon/breezy/.venv/bin/python "
    "/home/jon/breezy/scripts/analysis/discovery_venue_pull.py "
    "--node-log-dir %h/.local/share/breezy/logs "
    "--out-dir /home/jon/breezy/data/evidence/discovery_set_equality "
    '--user-agent "${BREEZY_USER_AGENT}"\n'
)


def test_pre_2e109ec_discovery_pull_execstart_fails_module_not_found(
    repo_root: Path, home: Path
) -> None:
    """RED fixture: proves this harness actually reproduces the 09-26
    16:52:47Z failure class, not merely that today's fixed unit passes."""
    result = _run_execstart(_PRE_2E109EC_DISCOVERY_PULL_UNIT, repo_root=repo_root, home=home)
    assert result.returncode != 0
    assert "ModuleNotFoundError: No module named 'scripts'" in result.stderr, result.stderr


def test_execstart_env_excludes_repo_root_from_pythonpath(repo_root: Path) -> None:
    env = _scrubbed_env(repo_root=repo_root)
    entries = env["PYTHONPATH"].split(os.pathsep)
    assert str(repo_root) not in entries, entries
    assert str(repo_root / "src") in entries, entries


def test_execstart_working_directory_is_honoured(
    tmp_path: Path, repo_root: Path, home: Path
) -> None:
    """The `-m` fix works ONLY because `WorkingDirectory=` is the repo root
    (cwd is what `-m` puts on `sys.path[0]`). Point `WorkingDirectory=` at
    an unrelated, empty `tmp_path` instead: the identical `-m` invocation
    must now fail, which is only possible if this harness actually reads
    and uses the directive rather than hardcoding the real repo root the
    way `test_discovery_pull_exec_import.py`'s `cwd=None` branch does for
    its direct-file case."""
    unit_text = f"""
[Service]
WorkingDirectory={tmp_path}
ExecStart=/home/jon/breezy/.venv/bin/python -m scripts.analysis.discovery_venue_pull --help
"""
    argv, cwd = resolve_execstart_invocation(unit_text, repo_root=repo_root, home=home)
    assert cwd == tmp_path

    result = subprocess.run(
        argv,
        cwd=cwd,
        env=_scrubbed_env(repo_root=repo_root),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stderr, result.stderr


def test_specifier_and_trailing_argument_tokens_are_dropped_not_expanded(
    repo_root: Path, home: Path
) -> None:
    """Edge case (r1 spec `:231`): every real covered unit's `%h` and
    `${VAR}` tokens appear only in ARGUMENTS after the module/script (e.g.
    `breezy-discovery-pull.service`'s `--node-log-dir %h/... --user-agent
    "${BREEZY_USER_AGENT}"`). Neither needs real shell-style expansion here
    because both are replaced wholesale by `--help`. A `%h` appearing
    BEFORE the module -- in `WorkingDirectory=` -- is a systemd specifier,
    never a shell variable, and must still resolve to the real, literal
    home directory rather than being passed through unexpanded.
    """
    unit_text = (
        "\n[Service]\n"
        "WorkingDirectory=%h/breezy-alt-checkout\n"
        "ExecStart=/home/jon/breezy/.venv/bin/python "
        "-m scripts.analysis.discovery_venue_pull "
        '--node-log-dir %h/logs --user-agent "${BREEZY_USER_AGENT}"\n'
    )
    argv, cwd = resolve_execstart_invocation(unit_text, repo_root=repo_root, home=home)

    assert cwd == home / "breezy-alt-checkout"
    joined = " ".join(argv)
    assert "%h" not in joined, argv
    assert "${BREEZY_USER_AGENT}" not in joined, argv
    assert argv[-1] == "--help"


def test_directive_reader_joins_backslash_newline_continuations_like_systemd() -> None:
    """systemd joins a line ending in `\\` with the next (replacing the pair with one space)
    BEFORE it looks for the directive; a naive reader splits the ExecStart in two."""
    text = (
        "[Service]\nExecStart=/usr/bin/flock -n \\\n"
        "  /usr/bin/bwrap --clearenv \\\n  -- /bin/true\nType=exec\n"
    )
    joined = _directive(text, "ExecStart")
    assert joined is not None
    assert shlex.split(joined) == [
        "/usr/bin/flock",
        "-n",
        "/usr/bin/bwrap",
        "--clearenv",
        "--",
        "/bin/true",
    ]
    assert _directive(text, "Type") == "exec"
    # a comment line is never a continuation target, and a lone trailing `\` ends the file safely
    assert _directive("ExecStart=/bin/a \\\n", "ExecStart") == "/bin/a"


def test_bwrap_wrapped_collector_unit_is_scanned_and_is_not_a_direct_venv_python_unit() -> None:
    """The collector's ExecStart parses (continuations joined) and is deliberately NOT in the
    direct-venv-python set: its first token is flock, and its imports are proven for real by
    `test_us_source_collector_unit.py::test_bwrap_probe_real_collector_help_runs_under_the_profile`."""
    unit = _SYSTEMD_DIR / "us-source-collector@.service"
    exec_start = _directive(unit.read_text(), "ExecStart")
    assert exec_start is not None
    tokens = shlex.split(_expand_home_specifier(exec_start, home=Path("/placeholder-home")))
    assert tokens[0] == "/usr/bin/flock" and "/usr/bin/bwrap" in tokens
    assert unit not in _venv_python_direct_script_units()
