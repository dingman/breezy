"""Stage 0 output comparison helpers, neutral so no test module imports another test module."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.analysis import maker_stage0_driver as drv

VOLATILE = {"run_manifest.json", "pins.json", "progress.jsonl"}  # times, code sha, paths, RSS


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalised(cfg: drv.RunConfig, name: str) -> bytes:
    """The artefact with run-specific values blanked: code sha, base dir, volatile files' shas."""
    code_sha = json.loads((cfg.out_dir / "run_manifest.json").read_text())["git_commit"]
    data = (cfg.out_dir / name).read_bytes()
    data = data.replace(code_sha.encode(), b"<CODE>")
    data = data.replace(str(cfg.out_dir.parent.parent).encode(), b"<BASE>")
    for volatile in VOLATILE:
        data = data.replace(_sha(cfg.out_dir / volatile).encode(), b"<VOLATILE>")
    return data
