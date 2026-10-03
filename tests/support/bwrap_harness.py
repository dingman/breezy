from __future__ import annotations

import os
import shutil
import subprocess


def run_raw_true() -> subprocess.CompletedProcess[str]:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise FileNotFoundError("bwrap")
    return subprocess.run(
        [
            bwrap,
            "--unshare-net",
            "--dev-bind",
            "/",
            "/",
            "/usr/bin/env",
            "-i",
            "PATH=/usr/bin:/bin",
            f"HOME={os.environ.get('HOME', '/tmp')}",
            "LANG=C.UTF-8",
            "/bin/true",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
