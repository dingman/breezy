"""Shared throwaway toolchain for the parallel-gate driver tests: a fake pytest, fake
python/bwrap, a universe of node ids, a fake HOME and a per-test run dir."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PARALLEL_SH: Final[Path] = REPO_ROOT / "scripts" / "ci" / "run_tests_parallel.sh"

# ---------------------------------------------------------------------------
# shell driver, with a fake pytest
# ---------------------------------------------------------------------------

_FAKE_PYTEST: Final[str] = r"""
import json, os, signal, sys, time
from pathlib import Path
sys.path.insert(0, os.environ["FAKE_SCRIPTS_DIR"])
import gate_shards as gs

args = sys.argv[1:]
log = Path(os.environ["BREEZY_FAKE_LOG"])
universe = json.loads(Path(os.environ["BREEZY_FAKE_UNIVERSE"]).read_text())
opts = {"-p", "--basetemp", "--junitxml", "-m"}
positional, xml, basetemp, collect = [], None, None, False
i = 0
while i < len(args):
    a = args[i]
    if a.startswith("--basetemp="):
        basetemp = a.split("=", 1)[1]
    elif a == "--basetemp":
        basetemp = args[i + 1]; i += 1
    elif a == "--junitxml":
        xml = args[i + 1]; i += 1
    elif a in opts:
        i += 1
    elif a in ("--collect-only", "--co", "--collectonly"):
        collect = True
    elif not a.startswith("-"):
        positional.append(a)
    i += 1
with log.open("a") as handle:
    handle.write(json.dumps({
        "gate_dir": os.environ.get("BREEZY_GATE_DIR"), "tmpdir": os.environ.get("TMPDIR"),
        "basetemp": basetemp, "collect": collect, "args": positional,
        "phase2": os.environ.get("BREEZY_BWRAP_HOST_PHASE"),
    }) + "\n")
if os.environ.get("BREEZY_BWRAP_HOST_PHASE") == "1":
    sys.exit(int(os.environ.get("BREEZY_FAKE_PHASE2_RC", "0")))
if universe.get("ignore_term"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
nap = universe.get("sleep_collect_s" if collect else "sleep_s", 0)
if nap:
    with Path(universe["pid_file"]).open("a") as handle:
        handle.write(f"{os.getpid()}\n")
    time.sleep(nap)

def selected(nodeid):
    if not positional:
        return True
    for a in positional:
        if nodeid == a or nodeid.startswith(a + "::") or nodeid.startswith(a + "["):
            return True
    return False

chosen = [n for n in universe["ids"] if selected(n)]
drop = universe.get("drop_from_run", [])
fail = universe.get("fail", [])
skip = universe.get("skip", {})
once = universe.get("fail_once", [])
seen_path = Path(os.environ["BREEZY_FAKE_UNIVERSE"]).with_suffix(".seen")
seen = seen_path.read_text().split() if seen_path.exists() else []
if collect:
    for n in chosen:
        print(n)
    print(f"{len(chosen)} tests collected")
    if os.environ.get("BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE"):
        Path(os.environ["BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE"]).write_text("collect-only")
    cases = []
    for path in universe.get("collect_skip_files", []):
        cls, name = gs.file_key(path)
        skipped = '<skipped message="collection skipped">x</skipped>'
        cases.append(f'<testcase classname="{cls}" name="{name}">{skipped}</testcase>')
    if xml:
        Path(xml).parent.mkdir(parents=True, exist_ok=True)
        body = "".join(cases)
        Path(xml).write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
    sys.exit(0)

rc = 0
cases = []
for n in chosen:
    if n in drop:
        continue
    cls, name = gs.nodeid_to_key(n)
    child = ""
    if n in fail or (n in once and n not in seen):
        child = '<failure message="boom">x</failure>'; rc = 1
        if n in once:
            seen.append(n)
    elif n in skip:
        child = f'<skipped type="pytest.skip" message="{skip[n]}">f:1: {skip[n]}</skipped>'
    cases.append(f'<testcase classname="{cls}" name="{name}" time="0.01">{child}</testcase>')
if xml:
    Path(xml).parent.mkdir(parents=True, exist_ok=True)
    Path(xml).write_text('<testsuites><testsuite>' + "".join(cases) + '</testsuite></testsuites>')
if once:
    seen_path.write_text("\n".join(seen))
sys.exit(int(universe.get("force_rc", rc)))
"""


def _exe(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


#: Fake HOMEs made by ``_Fake``; the driver refuses a gate dir inside the repo tree and
#: ``tmp_path`` is inside it (basetemp lives in the tree), so the fake HOME is made under
#: the real one and removed at session end.
_FAKE_HOMES: Final[list[Path]] = []


@pytest.fixture(scope="session", autouse=True)
def _remove_fake_homes() -> Iterator[None]:
    yield
    for home in _FAKE_HOMES:
        shutil.rmtree(home, ignore_errors=True)


def _make_fake_home() -> Path:
    base = Path.home() / ".cache" / "gs-test-homes"
    base.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="h-", dir=base))
    _FAKE_HOMES.append(home)
    return home


class _Fake:
    """A throwaway toolchain: fake python/bwrap/unshare plus a universe of ids."""

    def __init__(self, root: Path, universe: dict[str, Any]) -> None:
        self.root = root
        self.home = _make_fake_home()
        root.mkdir(parents=True)
        self.bin = root / "bin"
        self.bin.mkdir()
        (root / "fake_pytest.py").write_text(_FAKE_PYTEST, encoding="utf-8")
        real = sys.executable
        _exe(
            self.bin / "python",
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "if [[ ${1:-} == '-I' ]]; then\n"
            "  printf '%s\\n' tests/integration/test_bwrap_host_phase_witness.py; exit 0\nfi\n"
            f'exec "{real}" "{root}/fake_pytest.py" "${{@:3}}"\n',
        )
        _exe(
            self.bin / "bwrap",
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "while [[ $# -gt 0 ]]; do\n  case $1 in\n"
            '    --setenv) export "$2=$3"; shift 3;;\n'
            "    --dev-bind|--ro-bind) shift 3;;\n    --chdir|--dev|--proc) shift 2;;\n"
            "    --unshare-*|--disable-userns) shift;;\n    *) break;;\n  esac\ndone\n"
            'exec "$@"\n',
        )
        self.universe_path = root / "universe.json"
        self.universe_path.write_text(json.dumps(universe), encoding="utf-8")
        self.log = root / "calls.jsonl"
        self.reference = root / "reference.json"
        self.reference.write_text(
            json.dumps({"version": 1, "non_pass": {"0": [], "1": []}}), encoding="utf-8"
        )

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.home),
            "BREEZY_PYTHON": str(self.bin / "python"),
            "BREEZY_GATE_TOOL_PYTHON": sys.executable,
            "BREEZY_FAKE_LOG": str(self.log),
            "BREEZY_FAKE_UNIVERSE": str(self.universe_path),
            "FAKE_SCRIPTS_DIR": str(REPO_ROOT / "scripts" / "ci"),
            "BREEZY_GATE_REFERENCE": str(self.reference),
            "BREEZY_GATE_TAIL_MAX_WAIT_S": "0",
            "PYTHONPATH": str(REPO_ROOT / "src"),
        }
        if extra:
            env.update(extra)
        return env

    def calls(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line]


_SHELL_IDS: Final[list[str]] = [
    "tests/unit/test_one.py::test_a",
    "tests/unit/test_one.py::test_b[1]",
    "tests/unit/test_one.py::test_b[2]",
    "tests/unit/test_two.py::test_c",
    "tests/unit/test_three.py::test_d",
    "tests/unit/test_tier_infra.py::test_tail_member",
]


@pytest.fixture
def run_dir() -> Iterator[Path]:
    path = REPO_ROOT / ".pytest-tmp" / f"gs-{uuid.uuid4().hex[:8]}"
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _run_parallel(
    fake: _Fake, run_dir: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PARALLEL_SH), "--run-dir", str(run_dir), *args],
        cwd=REPO_ROOT,
        env=fake.env(extra_env),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _gate_root(home: Path, run_dir: Path) -> Path:
    """Where the parallel driver keeps its per-job gate dirs (outside the tree)."""
    return home / ".cache" / "breezy-gate" / "par" / run_dir.name


def _fake(tmp_path: Path, **universe: Any) -> _Fake:
    return _Fake(tmp_path / "fake", {"ids": _SHELL_IDS, **universe})
