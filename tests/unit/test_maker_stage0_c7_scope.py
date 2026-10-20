"""Pinned at Commit 1 of backlog/s2-c7-prefilter-2026-10-20; re-pin is a reviewed
diff of the JSON only; retired after the S2 evidence commit.

Verdict-closure byte pin (delta section 2.17). Importing the replay CLI and the
station-day child must not grow, and every non-exempt file stays at its Commit-1 digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PIN_PATH = Path(__file__).resolve().parent / "data" / "maker_stage0_c7_closure_pins.json"
EXEMPT = frozenset(
    {
        "scripts/analysis/maker_stage0_probe.py",
        "scripts/analysis/maker_stage0_probe_report.py",
        "scripts/analysis/maker_stage0_catalog_read.py",
        "scripts/analysis/maker_stage0_prefilter.py",
    }
)
_PROBE = "scripts/analysis/maker_stage0_probe.py"
# ``isolated_runner`` (and the ``scans_install`` it hands the child) lives here. The
# driver reaches it through ``maker_stage0_modes``; the child imports modes lazily.
_CHILD = "scripts.analysis.maker_stage0_isolate"
# -I ignores PYTHONPATH, so the child inserts the same two entries from cwd (REPO_ROOT).
_CODE = f"""
import json
import sys
from pathlib import Path

root = Path.cwd().resolve()
sys.path[:0] = [str(root / "src"), str(root)]
import scripts.analysis.maker_stage0_replay
import {_CHILD}
found: dict[str, str] = {{}}
for module in sys.modules.values():
    file = getattr(module, "__file__", None)
    if file is None:
        continue
    path = Path(file).resolve()
    if path.is_relative_to(root):
        found[path.relative_to(root).as_posix()] = str(path)
print(json.dumps(found, sort_keys=True))
"""


def _closure() -> dict[str, str]:
    """relpath -> resolved path for every repo file the verdict closure imported."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(REPO_ROOT / "src"), str(REPO_ROOT)))
    done = subprocess.run(
        [sys.executable, "-I", "-c", _CODE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    loaded: dict[str, str] = json.loads(done.stdout)
    return loaded


def _sha256(rel: str) -> str:
    return hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest()


def test_verdict_closure_bytes_match_the_commit1_pin() -> None:
    loaded = _closure()
    assert _PROBE in loaded
    resolved = Path(loaded[_PROBE])
    assert str(resolved).startswith(str(REPO_ROOT))
    assert resolved.is_relative_to(REPO_ROOT)
    pins: dict[str, str] = json.loads(_PIN_PATH.read_text(encoding="utf-8"))
    assert set(loaded) == set(pins)
    assert EXEMPT <= set(loaded)
    for rel, digest in pins.items():
        if rel in EXEMPT:
            continue
        assert _sha256(rel) == digest, rel
