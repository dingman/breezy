"""AUD-02 WP-D1 regression: the unit's ExecStart must actually IMPORT.

2026-09-26 16:52:47Z first live run: `breezy-discovery-pull.service` died
with ``ModuleNotFoundError: No module named 'scripts'`` before it ever
reached its own argparse -- ``discovery_venue_pull.py`` does
``from scripts.analysis.discovery_set_equality import ...`` (a
package-qualified import of a *sibling script module*, not the installed
``breezy`` package every other discovery/venue script under ``scripts/``
relies on), but the old ExecStart invoked the file directly
(``python /path/to/discovery_venue_pull.py``), which puts only the script's
OWN directory on ``sys.path[0]`` -- never the repo root -- so the
``scripts`` namespace package was never importable. `tests/unit/
test_discovery_pull_deploy.py` and `tests/unit/test_discovery_venue_pull.py`
both existed before this bug shipped and neither caught it: the deploy test
is text-parsing only (never spawns a process) and the unit test imports the
module in-process under pytest, which is invoked via `python -m pytest`
(scripts/ci/run_tests_no_egress.sh) -- `-m` puts the CURRENT WORKING
DIRECTORY on `sys.path[0]`, so the same import that fails under the unit's
own invocation style silently succeeds under pytest's.

This test runs the REAL interpreter against the REAL script (never a stub,
matching test_score_live_trials_deploy.py's own
`subprocess.run(["/home/jon/breezy/.venv/bin/python", str(_REPO_ROOT / ...)])`
idiom) with `--help` substituted for the unit's real flags -- `--help` still
forces the top-level `from scripts.analysis... import ...` to execute
before argparse ever runs, so a ModuleNotFoundError surfaces exactly as it
did on the host, with no node-log/out-dir I/O and no egress.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVICE = _REPO_ROOT / "deploy" / "systemd" / "breezy-discovery-pull.service"
_HOST_PREFIX = "/home/jon/breezy/"
_PYTHON = "/home/jon/breezy/.venv/bin/python"


def _directive_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


def _directive(text: str, name: str) -> str:
    prefix = f"{name}="
    matches = [line[len(prefix) :] for line in _directive_lines(text) if line.startswith(prefix)]
    assert len(matches) == 1, matches
    return matches[0]


def test_exec_start_entry_point_imports_cleanly_as_the_unit_invokes_it() -> None:
    """Run the unit's ExecStart shape (interpreter + module/script it
    resolves to) against THIS worktree's copy of the code, exactly as
    `test_score_live_trials_deploy.py::
    test_the_counter_json_carries_the_champion_manifest_sha256` runs
    `structural_dead_stop.py` against the worktree rather than the host's
    checkout. `--help` replaces the required `--node-log-dir`/`--out-dir`/
    `--user-agent` flags -- no real I/O, no egress -- but the import at
    module load time still runs first.
    """
    exec_start = _directive(_SERVICE.read_text(), "ExecStart")
    tokens = exec_start.split()
    assert tokens[0] == _PYTHON, tokens

    if tokens[1] == "-m":
        # module invocation: `-m scripts.analysis.discovery_venue_pull`
        argv = [_PYTHON, "-m", tokens[2], "--help"]
        cwd = _REPO_ROOT
    else:
        # direct file invocation: swap the host's hardcoded path for this
        # worktree's copy of the same file.
        host_script = tokens[1]
        assert host_script.startswith(_HOST_PREFIX), host_script
        script = _REPO_ROOT / host_script[len(_HOST_PREFIX) :]
        argv = [_PYTHON, str(script), "--help"]
        cwd = None

    result = subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr
