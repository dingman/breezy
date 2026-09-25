"""RED-first suite for `scripts/analysis/argv_digest.py` (AUD-19b §6 C6 step 2).

Dynamically loaded from `scripts/analysis` via the same sibling-import
convention the module under test documents (`scripts/` is unimportable as a
package from `src/breezy`).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from argv_digest import argv_sha256


def test_argv_sha256_matches_the_documented_formula() -> None:
    argv = ["--station", "LAX", "--climate-day", "2026-09-04"]
    expected = hashlib.sha256("\n".join(argv).encode("utf-8")).hexdigest()
    assert argv_sha256(argv) == expected


def test_argv_sha256_is_order_sensitive_and_change_sensitive() -> None:
    """A15: the same vector hashes equal; changing OR reordering any one
    argument hashes differently."""
    base = ["--a", "1", "--b", "2"]
    same = ["--a", "1", "--b", "2"]
    changed = ["--a", "1", "--b", "3"]
    reordered = ["--b", "2", "--a", "1"]
    assert argv_sha256(base) == argv_sha256(same)
    assert argv_sha256(base) != argv_sha256(changed)
    assert argv_sha256(base) != argv_sha256(reordered)


def test_argv_sha256_of_empty_vector_is_the_empty_string_digest() -> None:
    assert argv_sha256([]) == hashlib.sha256(b"").hexdigest()
