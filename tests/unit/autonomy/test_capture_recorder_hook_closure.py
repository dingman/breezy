"""AUT-1 WP3 step 1 (E-7 rule 2): the wrapped hook has no import path to a venue adapter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE = (
    "import sys, breezy.runtime.capture_recorder_hook_cli\n"
    "bad = sorted(m for m in sys.modules if m.startswith(('breezy.adapters', 'nautilus_trader')))\n"
    "print(','.join(bad))\n"
)


def test_hook_closure_imports_no_venue_adapter_or_nautilus() -> None:
    done = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert done.stdout.strip() == "", done.stdout


def test_probe_is_not_vacuous() -> None:
    """Positive control: the same probe flags a module that does import the adapter."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, breezy.adapters.polymarket_us.recorder_watchdog\n"
                "print(any(m.startswith('breezy.adapters') for m in sys.modules))"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert done.stdout.strip() == "True"
